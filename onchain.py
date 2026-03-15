"""On-chain data + market breadth indicators.

Sources (all free, no auth):
  - Blockchain.com  → BTC hash rate, mempool size, avg block size
  - Mempool.space   → BTC fee estimates, mempool congestion
  - Market breadth  → VIX proxy via UVXY/VIX data from Alpaca

These indicators add macro context to crypto trading decisions:
  - High mempool + high fees → network congestion → possible sell pressure
  - Hash rate rising → miner confidence → bullish
  - VIX > 30 → market fear → cautious on stocks, possibly bullish crypto (safe haven thesis)
"""

import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("phantom.onchain")

_HEADERS = {"User-Agent": "PhantomTrader/3.5"}
_TIMEOUT = 8


def _safe_get(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:
        logger.debug(f"On-chain fetch failed ({url}): {e}")
        return None


def _safe_get_json(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug(f"On-chain JSON failed ({url}): {e}")
        return None


# ─── Bitcoin On-Chain ─────────────────────────────────────────────────────────

# Blockchain.com free API endpoints (no auth)
_BC_BASE = "https://blockchain.info"


class BitcoinOnChain:
    """
    BTC on-chain metrics from Blockchain.com's free API.

    Indicators and their trading interpretation:
      - Hash Rate: rising = miners bullish, falling = capitulation risk
      - Mempool (unconfirmed tx): high = congestion = possible sell pressure
      - Avg Block Size: stable ~1.5MB normal, >2MB = high activity
      - Difficulty: rising = network growing = bullish long-term
    """

    CACHE_TTL = 600  # 10 minutes

    def __init__(self):
        self._cache: Optional[dict] = None
        self._cache_time: float = 0
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            if self._cache and (time.time() - self._cache_time) < self.CACHE_TTL:
                return self._cache

        result = self._fetch()
        with self._lock:
            self._cache = result
            self._cache_time = time.time()
        return result

    def _fetch(self) -> dict:
        # Fetch multiple on-chain metrics in parallel-ish (sequential but fast)
        hashrate = _safe_get(f"{_BC_BASE}/q/hashrate")
        unconfirmed = _safe_get(f"{_BC_BASE}/q/unconfirmedcount")
        difficulty = _safe_get(f"{_BC_BASE}/q/getdifficulty")
        block_count = _safe_get(f"{_BC_BASE}/q/getblockcount")

        # Parse
        try:
            hr = float(hashrate) if hashrate else None
        except (ValueError, TypeError):
            hr = None
        try:
            unconf = int(unconfirmed) if unconfirmed else None
        except (ValueError, TypeError):
            unconf = None
        try:
            diff = float(difficulty) if difficulty else None
        except (ValueError, TypeError):
            diff = None
        try:
            blocks = int(block_count) if block_count else None
        except (ValueError, TypeError):
            blocks = None

        # Derive signals
        signals = []
        score_delta = 0.0

        if unconf is not None:
            if unconf > 100000:
                signals.append(f"HIGH mempool ({unconf:,} unconfirmed)")
                score_delta -= 0.5  # Congestion = possible sell pressure
            elif unconf > 50000:
                signals.append(f"Elevated mempool ({unconf:,})")
            else:
                signals.append(f"Clear mempool ({unconf:,})")
                score_delta += 0.3  # Low congestion = healthy network

        if hr is not None:
            # Hash rate in GH/s from blockchain.info
            hr_th = hr / 1e12  # Convert to TH/s for display
            signals.append(f"Hash rate: {hr_th:.0f} TH/s")

        return {
            "hashrate_raw": hr,
            "unconfirmed_tx": unconf,
            "difficulty": diff,
            "block_height": blocks,
            "signals": signals,
            "score_delta": round(score_delta, 2),
            "available": hr is not None or unconf is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ─── Mempool Fee Estimates ────────────────────────────────────────────────────

_MEMPOOL_FEES_URL = "https://mempool.space/api/v1/fees/recommended"


class MempoolFees:
    """
    BTC fee estimates from mempool.space (free, no auth).
    High fees = high demand to move BTC = possibly bearish (people moving to sell).
    Low fees = calm network = neutral/bullish (hodling).
    """

    CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self._cache: Optional[dict] = None
        self._cache_time: float = 0
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            if self._cache and (time.time() - self._cache_time) < self.CACHE_TTL:
                return self._cache

        data = _safe_get_json(_MEMPOOL_FEES_URL)
        if not data:
            return {"available": False}

        fastest = data.get("fastestFee", 0)
        half_hour = data.get("halfHourFee", 0)
        hour = data.get("hourFee", 0)
        economy = data.get("economyFee", 0)

        # Fee-based signal
        if fastest > 100:
            fee_signal = "EXTREME_FEES"
            fee_score = -1.0
        elif fastest > 50:
            fee_signal = "HIGH_FEES"
            fee_score = -0.5
        elif fastest < 5:
            fee_signal = "LOW_FEES"
            fee_score = 0.5  # Calm network = bullish
        else:
            fee_signal = "NORMAL_FEES"
            fee_score = 0.0

        result = {
            "fastest_fee": fastest,
            "half_hour_fee": half_hour,
            "hour_fee": hour,
            "economy_fee": economy,
            "signal": fee_signal,
            "score_delta": fee_score,
            "available": True,
        }
        with self._lock:
            self._cache = result
            self._cache_time = time.time()
        return result


# ─── Market Breadth / VIX ─────────────────────────────────────────────────────

class MarketBreadth:
    """
    Market breadth indicators.
    Uses VIX level (passed in from Alpaca market data) to assess equity market fear.

    VIX interpretation:
      < 15  → Complacency (low vol, market calm, possibly fragile)
      15-20 → Normal
      20-30 → Elevated fear
      > 30  → Panic (historically good time to buy)
      > 40  → Extreme panic (March 2020 / COVID levels)
    """

    def get_vix_context(self, vix_level: float) -> dict:
        if vix_level <= 0:
            return {"available": False}

        if vix_level > 40:
            signal = "EXTREME_PANIC"
            score_delta = 2.0  # Contrarian buy
            label = "Extreme Panic"
        elif vix_level > 30:
            signal = "PANIC"
            score_delta = 1.5
            label = "Panic"
        elif vix_level > 25:
            signal = "FEAR"
            score_delta = 0.5
            label = "Elevated Fear"
        elif vix_level > 20:
            signal = "CAUTIOUS"
            score_delta = 0.0
            label = "Cautious"
        elif vix_level < 12:
            signal = "COMPLACENT"
            score_delta = -0.5  # Market too calm, fragile
            label = "Complacent"
        else:
            signal = "NORMAL"
            score_delta = 0.0
            label = "Normal"

        return {
            "vix": round(vix_level, 2),
            "signal": signal,
            "label": label,
            "score_delta": score_delta,
            "available": True,
        }


# ─── Unified On-Chain Manager ─────────────────────────────────────────────────

class OnChainManager:
    """
    Combined on-chain + market breadth context.
    Call .get_context() to get a unified dict for the analyst.
    """

    def __init__(self):
        self.btc = BitcoinOnChain()
        self.fees = MempoolFees()
        self.breadth = MarketBreadth()
        logger.info("OnChainManager initialized")

    def get_context(self, symbol: str = "", vix_level: float = 0.0) -> dict:
        """Return on-chain + breadth context for a symbol."""
        is_crypto = "/" in symbol
        is_btc = "BTC" in symbol.upper()

        btc_data = {}
        fee_data = {}
        onchain_score = 0.0

        # Only fetch on-chain data for crypto trades
        if is_crypto:
            btc_data = self.btc.get()
            fee_data = self.fees.get()
            onchain_score += btc_data.get("score_delta", 0)
            onchain_score += fee_data.get("score_delta", 0)

        # VIX context applies to stocks (and as macro context for all)
        vix_data = self.breadth.get_vix_context(vix_level)
        if not is_crypto and vix_data.get("available"):
            onchain_score += vix_data.get("score_delta", 0)

        return {
            "btc_onchain": btc_data if is_crypto else {},
            "mempool_fees": fee_data if is_crypto else {},
            "vix": vix_data,
            "onchain_score_delta": round(onchain_score, 2),
            "available": btc_data.get("available", False) or vix_data.get("available", False),
        }

    def get_status(self) -> dict:
        btc = self.btc.get()
        fees = self.fees.get()
        return {
            "btc_unconfirmed_tx": btc.get("unconfirmed_tx"),
            "btc_block_height": btc.get("block_height"),
            "btc_signals": btc.get("signals", []),
            "fee_fastest": fees.get("fastest_fee"),
            "fee_signal": fees.get("signal"),
            "available": btc.get("available", False),
        }
