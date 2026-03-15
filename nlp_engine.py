"""v3.6 - Groq NLP Sniper.

Interprets headlines, SEC filings, and macro data via Groq's
OpenAI-compatible API. Uses model failover to handle deprecations.
"""

import asyncio
import json
import logging

from config import config
from data_layer import SessionManager

logger = logging.getLogger("phantom.nlp")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# System prompt instructs the model to return strict JSON.
NLP_SYSTEM_PROMPT = """You are a quantitative financial analyst AI. Your job is to analyze
news headlines, SEC filings, DOJ announcements, FDA approvals, and macroeconomic data.

For each headline, you MUST return ONLY a valid JSON object with these exact fields:
{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "target_etf": "TQQQ" | "SQQQ" | "UVXY" | "GLD" | "LMT" | "NONE",
  "affected_symbols": ["SYMBOL1", "SYMBOL2"],
  "confidence": 0.0 to 1.0,
  "action": "BUY" | "SELL" | "HOLD",
  "catalyst": "EARNINGS" | "REGULATORY" | "GEOPOLITICAL_CRISIS" | "MACRO" | "SECTOR" | "OTHER",
  "reasoning": "brief explanation (max 50 words)"
}

Rules:
- confidence >= 0.85 means VERY strong conviction (only for clear, actionable events)
- confidence 0.5-0.84 means moderate signal
- confidence < 0.5 means noise/uncertain
- GEOPOLITICAL_CRISIS catalyst should only be used for actual military/sanctions events
- For FDA approvals, target the specific biotech symbol
- For SEC enforcement, the affected company should be SELL
- NEVER return anything outside the JSON object. No explanations, no markdown."""

# Map ETF targets to tradeable symbols.
ETF_SYMBOL_MAP = {
    "TQQQ": "TQQQ",  # 3x Nasdaq bull
    "SQQQ": "SQQQ",  # 3x Nasdaq bear
    "UVXY": "UVXY",  # VIX bull (crisis hedge)
    "GLD": "GLD",    # Gold
    "LMT": "LMT",    # Defense (Lockheed Martin)
}


class NLPEngine:
    """Groq-powered NLP sentiment engine with model failover."""

    def __init__(self):
        self.enabled = config.has_groq
        self._rate_limiter = asyncio.Semaphore(5)  # max concurrent Groq calls
        self._call_count = 0
        self._error_count = 0

        self._model_pool = self._build_model_pool()
        self._active_model_idx = 0

    def _build_model_pool(self) -> list[str]:
        pool: list[str] = []
        for model in [config.groq_model, *(config.groq_model_fallbacks or [])]:
            m = str(model or "").strip()
            if m and m not in pool:
                pool.append(m)
        # Absolute fallback if user clears env accidentally.
        if not pool:
            pool = ["llama-3.3-70b-versatile"]
        return pool

    @property
    def _active_model(self) -> str:
        return self._model_pool[self._active_model_idx]

    @staticmethod
    def _model_unavailable_error(body: str) -> bool:
        lower = (body or "").lower()
        indicators = (
            "decommissioned",
            "no longer supported",
            "model not found",
            "does not exist",
            "invalid model",
            "unsupported model",
        )
        return any(k in lower for k in indicators)

    async def analyze_headline(self, headline: str) -> dict | None:
        """Analyze one headline and return parsed signal JSON."""
        if not self.enabled or not headline:
            return None

        async with self._rate_limiter:
            session = await SessionManager.get_session()
            headers = {
                "Authorization": f"Bearer {config.groq_api_key}",
                "Content-Type": "application/json",
            }

            model_count = len(self._model_pool)
            for offset in range(model_count):
                model_idx = (self._active_model_idx + offset) % model_count
                model_name = self._model_pool[model_idx]
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": NLP_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analyze this headline:\n\n{headline}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 256,
                    "response_format": {"type": "json_object"},
                }

                try:
                    async with session.post(
                        GROQ_API_URL,
                        json=payload,
                        headers=headers,
                        timeout=__import__("aiohttp").ClientTimeout(total=10),
                    ) as resp:
                        self._call_count += 1

                        if resp.status == 429:
                            logger.warning("Groq 429 rate limit - backing off 3s")
                            await asyncio.sleep(3)
                            return None

                        if resp.status != 200:
                            body = await resp.text()
                            self._error_count += 1

                            # Try next model if this one is unavailable/deprecated.
                            if resp.status in (400, 404) and self._model_unavailable_error(body):
                                logger.warning(
                                    f"Groq model unavailable: {model_name} "
                                    f"(status {resp.status}) - trying fallback"
                                )
                                continue

                            logger.warning(
                                f"Groq API error {resp.status} [{model_name}]: {body[:200]}"
                            )
                            return None

                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"]
                        result = json.loads(content)

                        # Validate minimal required fields.
                        if not all(k in result for k in ("sentiment", "confidence", "action")):
                            logger.warning(f"Groq returned incomplete JSON: {result}")
                            return None

                        # Clamp confidence.
                        result["confidence"] = max(
                            0.0, min(1.0, float(result.get("confidence", 0)))
                        )

                        # Stick to the model that just worked.
                        if model_idx != self._active_model_idx:
                            old = self._active_model
                            self._active_model_idx = model_idx
                            logger.info(f"Groq model failover: {old} -> {self._active_model}")

                        return result

                except json.JSONDecodeError as e:
                    logger.warning(f"Groq JSON parse error [{model_name}]: {e}")
                    self._error_count += 1
                    return None
                except Exception as e:
                    logger.warning(f"Groq API error [{model_name}]: {e}")
                    self._error_count += 1
                    return None

            logger.error("Groq NLP: all configured models failed")
            return None

    async def analyze_batch(self, headlines: list[dict]) -> dict[str, dict]:
        """Analyze headlines and return per-symbol actionable signals."""
        if not self.enabled or not headlines:
            return {}

        # Limit batch size to avoid rate limits (free tiers are tight).
        batch = headlines[:15]
        tasks = [self.analyze_headline(h.get("title", "")) for h in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals: dict[str, dict] = {}
        action_conf_min = config.nlp_action_confidence_min

        for headline, result in zip(batch, results):
            if isinstance(result, Exception) or result is None:
                continue

            confidence = result.get("confidence", 0)
            action = result.get("action", "HOLD").upper()
            sentiment = result.get("sentiment", "NEUTRAL")

            logger.debug(
                f"NLP: [{sentiment}] conf={confidence:.2f} action={action} "
                f"headline='{headline.get('title', '')[:60]}'"
            )

            # Only act on high-confidence signals.
            if confidence >= action_conf_min and action in ("BUY", "SELL"):
                affected = result.get("affected_symbols", [])
                target_etf = result.get("target_etf", "NONE")

                if target_etf != "NONE" and target_etf in ETF_SYMBOL_MAP:
                    affected.append(ETF_SYMBOL_MAP[target_etf])

                for sym in affected:
                    sym = sym.upper().strip()
                    if sym and sym != "NONE":
                        signals[sym] = {
                            "action": action,
                            "confidence": confidence,
                            "sentiment": sentiment,
                            "catalyst": result.get("catalyst", "OTHER"),
                            "reasoning": result.get("reasoning", "NLP signal"),
                            "source": "groq_nlp",
                            "headline": headline.get("title", "")[:100],
                        }

        if signals:
            logger.info(
                f"NLP batch: {len(signals)} actionable signals from {len(batch)} headlines "
                f"(calls={self._call_count}, errors={self._error_count}, "
                f"model={self._active_model}, conf_min={action_conf_min:.2f})"
            )

        return signals

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "calls": self._call_count,
            "errors": self._error_count,
            "active_model": self._active_model,
            "model_pool": list(self._model_pool),
            "confidence_min": config.nlp_action_confidence_min,
        }
