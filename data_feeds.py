"""Real-time market intelligence feeds — no auth required (free public APIs).

Sources:
  - Alternative.me  → Crypto Fear & Greed Index
  - CNN / market    → Classic Fear & Greed (scraped from alternative source)
  - CoinGecko       → Trending coins, BTC dominance, global market cap
  - FRED            → Fed Funds Rate (requires free FRED_API_KEY, optional)

All feeds are cached internally to avoid rate-limiting.
"""

import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional
import requests

logger = logging.getLogger("phantom.feeds")

# ─── Constants ────────────────────────────────────────────────────────────────
ALTERNATIVE_ME_URL = "https://api.alternative.me/fng/?limit=3&format=json"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"

_HEADERS = {
    "User-Agent": "PhantomTrader/3.5 (educational trading bot)",
    "Accept": "application/json",
}
_TIMEOUT = 8  # seconds


def _safe_get(url: str, params: dict = None) -> Optional[dict]:
    """Wrapper that returns None on any network error instead of raising."""
    try:
        r = requests.get(url, headers=_HEADERS, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug(f"Feed fetch failed ({url}): {e}")
        return None


# ─── Fear & Greed Feed ────────────────────────────────────────────────────────

class FearGreedFeed:
    """
    Crypto Fear & Greed Index from Alternative.me (0 = Extreme Fear, 100 = Extreme Greed).

    Trading interpretation (contrarian):
      < 20  → Extreme Fear     → Strong BUY signal (people are panicking)
      20-35 → Fear             → Moderate BUY
      35-65 → Neutral          → No extra bias
      65-80 → Greed            → Moderate SELL signal
      > 80  → Extreme Greed    → Strong SELL (people are FOMO-ing, top incoming)
    """

    CACHE_TTL = 1800  # 30 minutes

    def __init__(self):
        self._cache: Optional[dict] = None
        self._cache_time: float = 0
        self._lock = threading.Lock()

    def get(self) -> dict:
        """Return current Fear & Greed data, using cache if fresh."""
        with self._lock:
            if self._cache and (time.time() - self._cache_time) < self.CACHE_TTL:
                return self._cache

        data = _safe_get(ALTERNATIVE_ME_URL)
        result = self._parse(data)

        with self._lock:
            self._cache = result
            self._cache_time = time.time()
        return result

    def _parse(self, data: Optional[dict]) -> dict:
        if not data or "data" not in data or not data["data"]:
            return self._fallback()
        try:
            latest = data["data"][0]
            value = int(latest["value"])
            label = latest["value_classification"]  # "Extreme Fear", "Fear", etc.
            ts = datetime.fromtimestamp(int(latest["timestamp"]), tz=timezone.utc).isoformat()

            # Previous day for delta
            delta = 0
            if len(data["data"]) > 1:
                prev = int(data["data"][1]["value"])
                delta = value - prev

            # Analyst signal (contrarian)
            if value < 20:
                signal = "STRONG_BUY"
                score_delta = 2.5
            elif value < 35:
                signal = "BUY"
                score_delta = 1.5
            elif value > 80:
                signal = "STRONG_SELL"
                score_delta = -2.5
            elif value > 65:
                signal = "SELL"
                score_delta = -1.5
            else:
                signal = "NEUTRAL"
                score_delta = 0.0

            return {
                "value": value,
                "label": label,
                "signal": signal,
                "score_delta": score_delta,  # Contribution to analyst heuristic score
                "delta_24h": delta,
                "timestamp": ts,
                "source": "alternative.me",
                "available": True,
            }
        except Exception as e:
            logger.warning(f"FearGreed parse error: {e}")
            return self._fallback()

    @staticmethod
    def _fallback() -> dict:
        return {
            "value": 50,
            "label": "Neutral",
            "signal": "NEUTRAL",
            "score_delta": 0.0,
            "delta_24h": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "fallback",
            "available": False,
        }

    def get_score_contribution(self) -> float:
        """Quick helper: just return the score delta for the analyst."""
        return self.get()["score_delta"]


# ─── CoinGecko Feed ───────────────────────────────────────────────────────────

class CoinGeckoFeed:
    """
    CoinGecko public API (free tier, no key).

    Provides:
      - Global market cap, 24h change
      - BTC dominance
      - Top trending coins (last 24h search trending)
    """

    CACHE_TTL = 900  # 15 minutes

    def __init__(self):
        self._global_cache: Optional[dict] = None
        self._trending_cache: Optional[dict] = None
        self._cache_time: float = 0
        self._lock = threading.Lock()

    def _refresh(self):
        with self._lock:
            now = time.time()
            if now - self._cache_time < self.CACHE_TTL:
                return

            global_data = _safe_get(COINGECKO_GLOBAL_URL)
            trending_data = _safe_get(COINGECKO_TRENDING_URL)

            self._global_cache = global_data
            self._trending_cache = trending_data
            self._cache_time = now

    def get_global(self) -> dict:
        """Return global market stats."""
        self._refresh()
        with self._lock:
            data = self._global_cache
        return self._parse_global(data)

    def get_trending(self) -> list[dict]:
        """Return top 7 trending coins."""
        self._refresh()
        with self._lock:
            data = self._trending_cache
        return self._parse_trending(data)

    def _parse_global(self, data: Optional[dict]) -> dict:
        if not data or "data" not in data:
            return {"available": False}
        try:
            d = data["data"]
            total_mcap = d.get("total_market_cap", {}).get("usd", 0)
            mcap_change = d.get("market_cap_change_percentage_24h_usd", 0)
            btc_dom = d.get("market_cap_percentage", {}).get("btc", 0)
            eth_dom = d.get("market_cap_percentage", {}).get("eth", 0)
            active_cryptos = d.get("active_cryptocurrencies", 0)
            total_volume = d.get("total_volume", {}).get("usd", 0)

            # Market mood from mcap change
            if mcap_change > 3:
                market_mood = "BULLISH"
            elif mcap_change < -3:
                market_mood = "BEARISH"
            else:
                market_mood = "NEUTRAL"

            return {
                "total_market_cap_usd": total_mcap,
                "market_cap_change_24h_pct": round(mcap_change, 2),
                "btc_dominance": round(btc_dom, 1),
                "eth_dominance": round(eth_dom, 1),
                "total_volume_24h_usd": total_volume,
                "active_cryptocurrencies": active_cryptos,
                "market_mood": market_mood,
                "available": True,
            }
        except Exception as e:
            logger.debug(f"CoinGecko global parse: {e}")
            return {"available": False}

    def _parse_trending(self, data: Optional[dict]) -> list[dict]:
        if not data or "coins" not in data:
            return []
        try:
            results = []
            for item in data["coins"][:7]:
                c = item.get("item", {})
                results.append({
                    "name": c.get("name", "?"),
                    "symbol": c.get("symbol", "?").upper(),
                    "market_cap_rank": c.get("market_cap_rank"),
                    "score": c.get("score", 0),  # 0=most trending
                    "thumb": c.get("thumb", ""),
                    "price_btc": c.get("price_btc", 0),
                })
            return results
        except Exception as e:
            logger.debug(f"CoinGecko trending parse: {e}")
            return []

    def is_symbol_trending(self, symbol: str) -> bool:
        """Check if a crypto symbol is currently trending (boosts score)."""
        sym = symbol.upper().replace("/USD", "").replace("/USDT", "")
        return any(c["symbol"] == sym for c in self.get_trending())


# ─── FRED Macro Feed (optional) ───────────────────────────────────────────────

class FREDFeed:
    """
    FRED (Federal Reserve) economic data.
    Requires FRED_API_KEY in .env (free at https://fred.stlouisfed.org/docs/api/api_key.html).

    Key series:
      FEDFUNDS   → Federal Funds Rate
      CPIAUCSL   → CPI (month)
      T10Y2Y     → Yield curve (10Y-2Y spread, negative = inversion warning)
      UNRATE     → Unemployment rate
    """

    CACHE_TTL = 3600  # 1 hour
    SERIES = {
        "fed_rate": "FEDFUNDS",
        "cpi": "CPIAUCSL",
        "yield_curve": "T10Y2Y",
        "unemployment": "UNRATE",
    }

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._cache: dict = {}
        self._cache_time: float = 0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def get_macro_context(self) -> dict:
        if not self.available:
            return {"available": False}

        if time.time() - self._cache_time < self.CACHE_TTL:
            return self._cache

        result = {"available": True}
        for name, series_id in self.SERIES.items():
            val = self._fetch_latest(series_id)
            result[name] = val

        # Derive signals
        yc = result.get("yield_curve")
        if isinstance(yc, float):
            result["yield_curve_inverted"] = yc < 0
            result["recession_signal"] = yc < -0.5  # Deep inversion

        self._cache = result
        self._cache_time = time.time()
        return result

    def _fetch_latest(self, series_id: str) -> Optional[float]:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        }
        data = _safe_get(FRED_SERIES_URL, params)
        if not data:
            return None
        try:
            obs = data.get("observations", [])
            if obs:
                val = obs[0].get("value", ".")
                return float(val) if val != "." else None
        except Exception:
            return None


# ─── Master Feed Manager ──────────────────────────────────────────────────────

class DataFeedManager:
    """
    Singleton-style manager that owns all data feeds.
    Call .get_context() to get a unified dict ready for the analyst.
    """

    def __init__(self, fred_api_key: str = ""):
        self.fear_greed = FearGreedFeed()
        self.coingecko = CoinGeckoFeed()
        self.fred = FREDFeed(api_key=fred_api_key)
        logger.info(
            f"DataFeedManager init — FRED: {'enabled' if self.fred.available else 'disabled (no key)'}"
        )

    def get_context(self, symbol: str = "") -> dict:
        """Return unified market intelligence context for the analyst."""
        fg = self.fear_greed.get()
        cg_global = self.coingecko.get_global()
        trending = self.coingecko.get_trending()
        macro = self.fred.get_macro_context()

        is_crypto = "/" in symbol
        is_trending = self.coingecko.is_symbol_trending(symbol) if is_crypto else False

        # Combined score delta for analyst heuristic
        # Fear & Greed applies equally to ALL assets — macro fear/greed moves everything
        fg_delta = fg["score_delta"]
        score_delta = fg_delta

        if is_trending:
            score_delta += 1.0  # Trending coin gets +1 boost

        # BTC dominance rising while ETH/alts falling → risk-off for alts
        btc_dom = cg_global.get("btc_dominance", 50)
        if is_crypto and "/USD" in symbol and "BTC" not in symbol:
            if btc_dom > 60:
                score_delta -= 0.5  # Alts underperforming when BTC dominates

        # FRED macro signals — yield curve inversion = risk-off for everything
        if macro.get("available"):
            if macro.get("recession_signal"):
                score_delta -= 1.5  # Deep yield curve inversion — strong risk-off
            elif macro.get("yield_curve_inverted"):
                score_delta -= 0.75  # Mild inversion — cautious

        return {
            "fear_greed": fg,
            "crypto_market": cg_global,
            "trending_coins": trending[:5],
            "macro": macro,
            "symbol_context": {
                "is_trending": is_trending,
                "btc_dominance": btc_dom,
            },
            "score_delta": round(score_delta, 2),  # Net contribution to analyst score
        }

    def get_status(self) -> dict:
        """Status dict for the dashboard."""
        fg = self.fear_greed.get()
        cg = self.coingecko.get_global()
        return {
            "fear_greed_value": fg["value"],
            "fear_greed_label": fg["label"],
            "fear_greed_signal": fg["signal"],
            "fear_greed_delta_24h": fg.get("delta_24h", 0),
            "crypto_market_cap_change_24h": cg.get("market_cap_change_24h_pct"),
            "btc_dominance": cg.get("btc_dominance"),
            "market_mood": cg.get("market_mood", "NEUTRAL"),
            "fred_available": self.fred.available,
            "trending_coins": self.coingecko.get_trending()[:5],
        }
