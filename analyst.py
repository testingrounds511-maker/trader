"""Analyst — Generates trading decisions using Groq (free) or Anthropic (paid).

Default: Groq with Llama 3.3 70B (free tier: 30 req/min).
Fallback: Anthropic Claude Haiku (if ANTHROPIC_API_KEY set).
Integrates lessons from TradeMemory for continuous improvement.
"""

import json
import logging
from datetime import datetime, timezone

import aiohttp

from config import config, FN_RULES

logger = logging.getLogger("phantom.analyst")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a professional forex trading analyst for a prop firm challenge.
You analyze technical indicators, market context, and lessons from past trades.

CRITICAL RULES (FundedNext):
- Profit target: 5% of initial balance
- Daily loss limit: 5% — if approaching, do NOT take risky trades
- Max overall loss: 10% — protect capital above all
- Max 30 open positions at once
- Conservative position sizing: 1% risk per trade max
- Risk/Reward minimum 1:2

You must respond ONLY with valid JSON in this exact format:
{
    "decision": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 to 1.0,
    "entry_price": float or null,
    "stop_loss": float,
    "take_profit": float,
    "lot_size_suggestion": float,
    "reasoning": "Brief 1-2 sentence explanation",
    "risk_level": "LOW" | "MEDIUM" | "HIGH"
}

IMPORTANT: Pay close attention to LEARNED LESSONS section if present.
These are patterns extracted from real past trades — respect them.

If conditions are uncertain, ALWAYS choose HOLD. Capital preservation > profit.
Only take HIGH confidence trades (0.7+). This is a prop firm challenge, not gambling."""


class Analyst:
    """Multi-provider analyst: Groq (free) → Anthropic (fallback)."""

    def __init__(self, trade_memory=None):
        self.memory = trade_memory
        self.total_tokens = 0
        self.total_cost = 0.0
        self._provider = "groq" if config.has_groq else "anthropic"
        self._call_count = 0
        self._error_count = 0

        # Groq model with fallback
        self._groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        self._active_groq_idx = 0

        logger.info(f"Analyst initialized — provider: {self._provider}")

    async def analyze_async(
        self,
        symbol: str,
        technical: dict,
        account_info: dict,
        risk_status: dict,
        news_sentiment: str = "neutral",
        open_positions: list = None,
    ) -> dict:
        """Async version — Get AI trading decision."""
        prompt = self._build_prompt(
            symbol, technical, account_info, risk_status,
            news_sentiment, open_positions or []
        )

        if self._provider == "groq":
            result = await self._call_groq(prompt)
        else:
            result = await self._call_anthropic(prompt)

        if result:
            result["symbol"] = symbol
            result["timestamp"] = datetime.now(timezone.utc).isoformat()
            result["provider"] = self._provider
            logger.info(
                f"{symbol}: {result['decision']} "
                f"(confidence: {result.get('confidence', 0)}, "
                f"provider: {self._provider})"
            )
            return result

        return self._hold_decision(symbol, "Analysis failed")

    def analyze(
        self,
        symbol: str,
        technical: dict,
        account_info: dict,
        risk_status: dict,
        news_sentiment: str = "neutral",
        open_positions: list = None,
    ) -> dict:
        """Sync version — wraps async for backward compatibility."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context — use to_thread or create task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.analyze_async(
                            symbol, technical, account_info, risk_status,
                            news_sentiment, open_positions
                        )
                    )
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(
                    self.analyze_async(
                        symbol, technical, account_info, risk_status,
                        news_sentiment, open_positions
                    )
                )
        except Exception as e:
            logger.error(f"Sync analyze error: {e}")
            return self._hold_decision(symbol, str(e))

    async def _call_groq(self, prompt: str) -> dict | None:
        """Call Groq API (free tier)."""
        for offset in range(len(self._groq_models)):
            model_idx = (self._active_groq_idx + offset) % len(self._groq_models)
            model = self._groq_models[model_idx]

            try:
                async with aiohttp.ClientSession() as session:
                    headers = {
                        "Authorization": f"Bearer {config.groq_api_key}",
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 400,
                        "response_format": {"type": "json_object"},
                    }

                    async with session.post(
                        GROQ_API_URL, json=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        self._call_count += 1

                        if resp.status == 429:
                            logger.warning("Groq rate limit — waiting 5s")
                            await __import__("asyncio").sleep(5)
                            continue

                        if resp.status != 200:
                            body = await resp.text()
                            if "decommissioned" in body.lower() or "not found" in body.lower():
                                self._active_groq_idx = (model_idx + 1) % len(self._groq_models)
                                continue
                            logger.error(f"Groq error {resp.status}: {body[:200]}")
                            continue

                        data = await resp.json()
                        text = data["choices"][0]["message"]["content"].strip()
                        if text.startswith("```"):
                            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                        tokens = data.get("usage", {})
                        self.total_tokens += tokens.get("total_tokens", 0)
                        # Groq free = $0
                        self.total_cost += 0.0

                        return json.loads(text)

            except json.JSONDecodeError as e:
                logger.error(f"Groq JSON parse error: {e}")
                self._error_count += 1
            except Exception as e:
                logger.error(f"Groq call failed: {e}")
                self._error_count += 1

        # All Groq models failed — try Anthropic fallback
        if config.anthropic_api_key:
            logger.warning("Groq failed — falling back to Anthropic")
            return await self._call_anthropic(prompt)

        return None

    async def _call_anthropic(self, prompt: str) -> dict | None:
        """Call Anthropic API (paid fallback)."""
        if not config.anthropic_api_key:
            return None

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=config.anthropic_api_key)

            response = client.messages.create(
                model=config.claude_model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            input_t = response.usage.input_tokens
            output_t = response.usage.output_tokens
            self.total_tokens += input_t + output_t
            self.total_cost += (input_t * 0.25 + output_t * 1.25) / 1_000_000

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            self._call_count += 1
            return json.loads(text)

        except Exception as e:
            logger.error(f"Anthropic call failed: {e}")
            self._error_count += 1
            return None

    def _build_prompt(
        self,
        symbol: str,
        technical: dict,
        account_info: dict,
        risk_status: dict,
        news_sentiment: str,
        open_positions: list,
    ) -> str:
        """Build analysis prompt with learned lessons."""
        existing = [p for p in open_positions if p.get("symbol") == symbol]
        position_info = "No existing position"
        if existing:
            pos = existing[0]
            position_info = (
                f"EXISTING {pos['type']} position: {pos['volume']} lots @ {pos['price_open']}, "
                f"current P/L: ${pos['profit']:.2f}"
            )

        balance = account_info.get("balance", 0)
        equity = account_info.get("equity", 0)
        initial = risk_status.get("initial_balance", balance)
        profit_pct = ((equity - initial) / initial * 100) if initial else 0

        # Get learned lessons from memory
        lessons_section = ""
        if self.memory:
            lessons_section = self.memory.get_lessons_for_prompt(symbol)

        # Get optimized params if available
        params_note = ""
        try:
            from auto_optimizer import AutoOptimizer
            optimizer = AutoOptimizer()
            p = optimizer.params
            if p.get("source") == "auto_optimizer":
                params_note = (
                    f"\n== AUTO-OPTIMIZED PARAMETERS ==\n"
                    f"SL: {p['sl_atr_multiplier']}x ATR | TP: {p['tp_rr_ratio']}:1 R:R | "
                    f"Min confidence: {p.get('confidence_threshold', 0.7):.0%}"
                )
        except Exception:
            pass

        return f"""ANALYZE {symbol} FOR TRADING DECISION

== TECHNICAL INDICATORS ==
Price: {technical.get('current_price')}
Trend: {technical.get('trend')} (Strength: {technical.get('trend_strength')})
EMA 20: {technical.get('ema_20')} | EMA 50: {technical.get('ema_50')}
RSI: {technical.get('rsi')} ({technical.get('rsi_signal')})
MACD: {technical.get('macd')} | Signal: {technical.get('macd_signal')} | Hist: {technical.get('macd_histogram')} ({technical.get('macd_direction')})
ADX: {technical.get('adx')}
BB: Upper={technical.get('bb_upper')} | Mid={technical.get('bb_mid')} | Lower={technical.get('bb_lower')} (Price {technical.get('bb_position')})
ATR: {technical.get('atr')}
Support: {technical.get('support')} | Resistance: {technical.get('resistance')}

== ACCOUNT STATUS ==
Balance: ${balance:.2f} | Equity: ${equity:.2f}
Profit vs Target: {profit_pct:.2f}% / 5.00% target
Days Remaining: {risk_status.get('days_remaining', '?')} of 14
Trading Days: {risk_status.get('trading_days_count', 0)} / {FN_RULES.MIN_TRADING_DAYS} min
Open Positions: {len(open_positions)} / {FN_RULES.MAX_OPEN_POSITIONS} max

== POSITION IN {symbol} ==
{position_info}

== NEWS SENTIMENT ==
{news_sentiment}
{lessons_section}
{params_note}
== RISK BUDGET ==
Max risk this trade: {config.risk_per_trade_pct * 100:.1f}% (${balance * config.risk_per_trade_pct:.2f})
SL = {config.sl_atr_multiplier}x ATR, TP = {config.tp_rr_ratio}:1 R:R

Respond with JSON only."""

    def _hold_decision(self, symbol: str, reason: str) -> dict:
        return {
            "symbol": symbol,
            "decision": "HOLD",
            "confidence": 0.0,
            "entry_price": None,
            "stop_loss": 0,
            "take_profit": 0,
            "lot_size_suggestion": 0,
            "reasoning": reason,
            "risk_level": "HIGH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": self._provider,
        }

    def get_cost_estimate(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.total_cost, 4),
            "provider": self._provider,
            "calls": self._call_count,
            "errors": self._error_count,
        }
