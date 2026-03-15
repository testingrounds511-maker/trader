"""v3.6 — Async Market Data Proxy with aiohttp connection pooling.

Replaces synchronous requests/yfinance calls with concurrent async fetches.
Provides a shared SessionManager singleton for all async modules.
"""

import asyncio
import logging
import time
from typing import Any

import aiohttp
import pandas as pd

from config import config

logger = logging.getLogger("phantom.data_layer")

# ──────────────────────────────────────────────
# Session Manager (singleton aiohttp session)
# ──────────────────────────────────────────────

class SessionManager:
    """Module-level singleton for a shared aiohttp.ClientSession."""

    _session: aiohttp.ClientSession | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            async with cls._lock:
                # Double-check after acquiring lock
                if cls._session is None or cls._session.closed:
                    connector = aiohttp.TCPConnector(
                        limit=100,
                        ttl_dns_cache=300,
                        enable_cleanup_closed=True,
                    )
                    timeout = aiohttp.ClientTimeout(total=15, connect=5)
                    cls._session = aiohttp.ClientSession(
                        connector=connector,
                        timeout=timeout,
                    )
        return cls._session

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None


# ──────────────────────────────────────────────
# Alpaca REST endpoints (direct, no SDK)
# ──────────────────────────────────────────────

ALPACA_DATA_BASE = "https://data.alpaca.markets"
ALPACA_CRYPTO_QUOTES = f"{ALPACA_DATA_BASE}/v1beta3/crypto/us/latest/quotes"
ALPACA_STOCK_QUOTES = f"{ALPACA_DATA_BASE}/v2/stocks/quotes/latest"

FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"


# ──────────────────────────────────────────────
# Async Market Data Proxy
# ──────────────────────────────────────────────

class AsyncMarketDataProxy:
    """Fetches quotes for 55+ instruments concurrently via aiohttp."""

    def __init__(self):
        self._quote_cache: dict[str, tuple[float, dict]] = {}
        self._cache_ttl: float = 2.0  # seconds
        self._backoff_until: float = 0.0  # 429 backoff timestamp
        self._sync_market_data = None
        try:
            from market_data import MarketData
            self._sync_market_data = MarketData()
        except Exception as e:
            logger.warning(f"Could not initialize MarketData bridge: {e}")

    # ── Public API ──

    async def get_quotes_batch(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch bid/ask for all symbols in parallel.

        Splits into crypto vs stock batches and uses the most efficient
        endpoint for each (Alpaca multi-symbol for crypto, Finnhub or
        Alpaca for individual stocks).
        """
        crypto = [s for s in symbols if "/" in s]
        stocks = [s for s in symbols if "/" not in s]

        results: dict[str, dict] = {}

        tasks = []
        if crypto:
            tasks.append(self._fetch_crypto_batch(crypto))
        if stocks:
            tasks.append(self._fetch_stock_batch(stocks))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in batch_results:
            if isinstance(r, dict):
                results.update(r)
            elif isinstance(r, Exception):
                logger.warning(f"Batch quote error: {r}")

        return results

    async def get_single_quote(self, symbol: str) -> dict | None:
        """Get a single quote (with cache)."""
        cached = self._check_cache(symbol)
        if cached is not None:
            return cached

        session = await SessionManager.get_session()
        if "/" in symbol:
            return await self._fetch_crypto_single(session, symbol)
        return await self._fetch_stock_single(session, symbol)

    async def get_bars(self, symbol: str, days: int = 7, timeframe: str = "1h") -> pd.DataFrame:
        """Wraps existing sync MarketData.get_bars via to_thread.

        This avoids rewriting the complex yfinance/Massive/Alpaca
        priority chain — only quotes need full async treatment.
        """
        try:
            if self._sync_market_data is None:
                from market_data import MarketData
                self._sync_market_data = MarketData()
            return await asyncio.to_thread(
                self._sync_market_data.get_bars, symbol, days, timeframe
            )
        except Exception as e:
            logger.warning(f"Bars fetch failed for {symbol}: {e}")
            return pd.DataFrame()

    async def get_multi_timeframe_bars(self, symbol: str) -> dict[str, pd.DataFrame]:
        """Wraps existing sync MarketData.get_multi_timeframe_bars."""
        try:
            if self._sync_market_data is None:
                from market_data import MarketData
                self._sync_market_data = MarketData()
            return await asyncio.to_thread(
                self._sync_market_data.get_multi_timeframe_bars, symbol
            )
        except Exception as e:
            logger.warning(f"Multi-TF bars failed for {symbol}: {e}")
            return {}

    # ── Crypto batch (Alpaca multi-symbol endpoint) ──

    async def _fetch_crypto_batch(self, symbols: list[str]) -> dict[str, dict]:
        """Alpaca crypto quotes endpoint accepts multiple symbols at once."""
        results: dict[str, dict] = {}

        # Check cache first
        uncached = []
        for s in symbols:
            cached = self._check_cache(s)
            if cached is not None:
                results[s] = cached
            else:
                uncached.append(s)

        if not uncached:
            return results

        session = await SessionManager.get_session()
        headers = self._alpaca_headers()
        params = {"symbols": ",".join(uncached)}

        try:
            async with session.get(
                ALPACA_CRYPTO_QUOTES, headers=headers, params=params
            ) as resp:
                if resp.status == 429:
                    await self._handle_429("alpaca_crypto")
                    return results
                resp.raise_for_status()
                data = await resp.json()

            quotes = data.get("quotes", {})
            for sym, q in quotes.items():
                quote = {
                    "bid": float(q.get("bp", 0)),
                    "ask": float(q.get("ap", 0)),
                    "mid": (float(q.get("bp", 0)) + float(q.get("ap", 0))) / 2,
                    "spread": float(q.get("ap", 0)) - float(q.get("bp", 0)),
                    "timestamp": q.get("t", ""),
                }
                self._set_cache(sym, quote)
                results[sym] = quote

        except aiohttp.ClientError as e:
            logger.warning(f"Crypto batch error: {e}")
        except Exception as e:
            logger.error(f"Unexpected crypto batch error: {e}")

        return results

    # ── Stock batch (parallel individual fetches) ──

    async def _fetch_stock_batch(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch stock quotes — Finnhub first (faster, free), Alpaca fallback.

        Finnhub is preferred because Alpaca SIP requires a paid plan and returns
        403 on free/paper accounts, forcing expensive per-symbol yfinance fallbacks.
        """
        results: dict[str, dict] = {}

        uncached = []
        for s in symbols:
            cached = self._check_cache(s)
            if cached is not None:
                results[s] = cached
            else:
                uncached.append(s)

        if not uncached:
            return results

        session = await SessionManager.get_session()

        # Strategy: Finnhub parallel first (60 calls/min free), then Alpaca for misses
        if config.has_finnhub:
            # Batch Finnhub in chunks of 50 to respect rate limits
            for chunk_start in range(0, len(uncached), 50):
                chunk = uncached[chunk_start:chunk_start + 50]
                finnhub_tasks = [
                    self._fetch_finnhub_quote(session, s) for s in chunk
                ]
                finnhub_results = await asyncio.gather(
                    *finnhub_tasks, return_exceptions=True
                )
                for sym, r in zip(chunk, finnhub_results):
                    if isinstance(r, dict) and "bid" in r:
                        results[sym] = r

        # Alpaca fallback for any symbols Finnhub missed
        still_missing = [s for s in uncached if s not in results]
        if still_missing:
            for chunk_start in range(0, len(still_missing), 50):
                chunk = still_missing[chunk_start:chunk_start + 50]
                chunk_results = await self._fetch_stock_chunk_alpaca(session, chunk)
                results.update(chunk_results)

        return results

    async def _fetch_stock_chunk_alpaca(
        self, session: aiohttp.ClientSession, symbols: list[str]
    ) -> dict[str, dict]:
        """Alpaca stock multi-quote endpoint."""
        results: dict[str, dict] = {}
        headers = self._alpaca_headers()
        params = {"symbols": ",".join(symbols), "feed": config.alpaca_data_feed}

        try:
            async with session.get(
                ALPACA_STOCK_QUOTES, headers=headers, params=params
            ) as resp:
                if resp.status == 429:
                    await self._handle_429("alpaca_stocks")
                    return results
                resp.raise_for_status()
                data = await resp.json()

            quotes = data.get("quotes", {})
            for sym, q in quotes.items():
                quote = {
                    "bid": float(q.get("bp", 0)),
                    "ask": float(q.get("ap", 0)),
                    "mid": (float(q.get("bp", 0)) + float(q.get("ap", 0))) / 2,
                    "spread": float(q.get("ap", 0)) - float(q.get("bp", 0)),
                    "timestamp": q.get("t", ""),
                }
                self._set_cache(sym, quote)
                results[sym] = quote

        except aiohttp.ClientError as e:
            logger.warning(f"Stock Alpaca batch error: {e}")
        except Exception as e:
            logger.error(f"Unexpected stock batch error: {e}")

        return results

    # ── Single-symbol fetchers ──

    async def _fetch_crypto_single(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> dict | None:
        headers = self._alpaca_headers()
        params = {"symbols": symbol}
        try:
            async with session.get(
                ALPACA_CRYPTO_QUOTES, headers=headers, params=params
            ) as resp:
                if resp.status == 429:
                    await self._handle_429("alpaca_crypto")
                    return None
                resp.raise_for_status()
                data = await resp.json()
            q = data.get("quotes", {}).get(symbol)
            if not q:
                return None
            quote = {
                "bid": float(q.get("bp", 0)),
                "ask": float(q.get("ap", 0)),
                "mid": (float(q.get("bp", 0)) + float(q.get("ap", 0))) / 2,
                "spread": float(q.get("ap", 0)) - float(q.get("bp", 0)),
                "timestamp": q.get("t", ""),
            }
            self._set_cache(symbol, quote)
            return quote
        except Exception as e:
            logger.warning(f"Crypto single quote error ({symbol}): {e}")
            return None

    async def _fetch_stock_single(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> dict | None:
        # Try Finnhub first (faster, free tier)
        if config.has_finnhub:
            result = await self._fetch_finnhub_quote(session, symbol)
            if isinstance(result, dict):
                return result
        # Fallback to Alpaca
        chunk = await self._fetch_stock_chunk_alpaca(session, [symbol])
        return chunk.get(symbol)

    async def _fetch_finnhub_quote(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> dict | None:
        """Finnhub real-time quote (60 calls/min free tier)."""
        params = {"symbol": symbol, "token": config.finnhub_api_key}
        try:
            async with session.get(
                FINNHUB_QUOTE, params=params,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 429:
                    return None  # Rate limited, skip silently
                resp.raise_for_status()
                data = await resp.json()

            # Finnhub returns: c=current, h=high, l=low, o=open, pc=prev_close
            current = float(data.get("c", 0))
            if current <= 0:
                return None

            quote = {
                "bid": current * 0.999,  # Estimate: Finnhub doesn't give bid/ask
                "ask": current * 1.001,
                "mid": current,
                "spread": current * 0.002,
                "timestamp": "",
            }
            self._set_cache(symbol, quote)
            return quote
        except Exception:
            return None

    # ── Cache helpers ──

    def _check_cache(self, symbol: str) -> dict | None:
        cached = self._quote_cache.get(symbol)
        if cached and (time.monotonic() - cached[0]) < self._cache_ttl:
            return cached[1]
        return None

    def _set_cache(self, symbol: str, quote: dict):
        self._quote_cache[symbol] = (time.monotonic(), quote)

    # ── Rate limit / backoff ──

    async def _handle_429(self, source: str):
        wait = 5.0
        logger.warning(f"429 Rate Limited ({source}) — backing off {wait}s")
        self._backoff_until = time.monotonic() + wait
        await asyncio.sleep(wait)

    # ── Auth headers ──

    @staticmethod
    def _alpaca_headers() -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": config.alpaca_api_key,
            "APCA-API-SECRET-KEY": config.alpaca_secret_key,
        }
