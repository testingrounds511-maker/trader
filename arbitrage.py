"""v3.6 - Lead-Lag Arbitrage Engine.

Monitors BTC/USD via Alpaca WebSocket for anomalous price movements.
When BTC jumps >1% in 5 seconds with a volume spike, fires buy/sell
signals for lag-correlated equities (MSTR, COIN, MARA).
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Awaitable, Callable, Iterable

from config import config

logger = logging.getLogger("phantom.arbitrage")

# Alpaca Crypto WebSocket (real-time trades)
ALPACA_CRYPTO_WS = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"

# Lag tickers: BTC-correlated equities that react slower than crypto
LAG_PROXIES = ["MSTR", "COIN", "MARA"]

# Trigger thresholds
TRIGGER_PCT = 0.01          # 1% price move
TRIGGER_WINDOW_S = 5.0      # Within 5 seconds
VOLUME_SPIKE_MULT = 2.0     # Volume 2x above rolling average
COOLDOWN_S = 300.0          # 5 minutes between triggers
MAX_BUFFER_SIZE = 500       # Max trades in buffer


class ArbitrageMonitor:
    """BTC/USD lead-lag detector using Alpaca crypto WebSocket."""

    def __init__(self):
        self._price_buffer: deque[tuple[float, float]] = deque(maxlen=MAX_BUFFER_SIZE)
        self._volume_buffer: deque[float] = deque(maxlen=MAX_BUFFER_SIZE)

        self._last_trigger_time: float = 0.0
        self._trigger_count: int = 0
        self._trade_count: int = 0
        self._reconnect_count: int = 0
        self._last_disconnect_log_at: float = 0.0
        self._on_signal: Callable[[str, list[str]], Awaitable[None]] | None = None

    @staticmethod
    def _as_messages(raw: str | bytes) -> list[dict]:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            data = json.loads(raw)
        except Exception:
            return []

        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    @staticmethod
    def _is_subscription_ack(msg: dict) -> bool:
        mtype = msg.get("T")
        if mtype == "subscription":
            trades = msg.get("trades", [])
            return isinstance(trades, Iterable) and "BTC/USD" in trades
        if mtype == "success" and str(msg.get("msg", "")).lower() in {
            "subscribed",
            "subscription",
        }:
            return True
        return False

    def _log_disconnect(self, text: str):
        """Rate-limit noisy disconnect logs while preserving useful signal."""
        now = time.monotonic()
        if now - self._last_disconnect_log_at >= 20:
            logger.warning(text)
            self._last_disconnect_log_at = now
        else:
            logger.debug(text)

    async def run(
        self,
        stop_event: asyncio.Event,
        on_signal: Callable[[str, list[str]], Awaitable[None]] | None = None,
    ):
        """Long-running task: connect and monitor BTC/USD trades."""
        try:
            import websockets
        except ImportError:
            logger.warning(
                "websockets package not installed - arbitrage monitor disabled. "
                "Install with: pip install websockets"
            )
            return

        self._on_signal = on_signal

        logger.info(
            f"Arbitrage Monitor starting - watching BTC/USD for "
            f"{TRIGGER_PCT:.0%} moves in {TRIGGER_WINDOW_S}s"
        )

        while not stop_event.is_set():
            started_at = time.monotonic()
            try:
                await self._connect_and_listen(stop_event, websockets)
                if stop_event.is_set():
                    break
            except websockets.exceptions.ConnectionClosed as e:
                self._log_disconnect(
                    f"Arbitrage WS closed: code={e.code} reason={e.reason or 'no reason'}"
                )
            except Exception as e:
                self._log_disconnect(f"Arbitrage WS error: {e}")

            if not stop_event.is_set():
                uptime = time.monotonic() - started_at
                # Reset reconnect pressure only after a stable session.
                if uptime >= 60:
                    self._reconnect_count = 0
                self._reconnect_count += 1
                wait = min(5 * self._reconnect_count, 60)
                logger.info(f"Arbitrage WS reconnecting in {wait}s...")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                    break
                except asyncio.TimeoutError:
                    continue

        logger.info("Arbitrage Monitor stopped")

    async def _wait_for_auth_ack(self, ws, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            for msg in self._as_messages(raw):
                if msg.get("T") == "error":
                    logger.error(f"Arbitrage WS auth failed: {msg}")
                    return False
                if msg.get("T") == "success" and msg.get("msg") == "authenticated":
                    logger.info("Arbitrage WS authenticated")
                    return True
        return False

    async def _wait_for_sub_ack(self, ws, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            for msg in self._as_messages(raw):
                if msg.get("T") == "error":
                    logger.error(f"Arbitrage WS subscribe failed: {msg}")
                    return False
                if self._is_subscription_ack(msg):
                    return True
        return False

    async def _connect_and_listen(self, stop_event, websockets):
        """Single WebSocket connection lifecycle."""
        async with websockets.connect(
            ALPACA_CRYPTO_WS,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            # 1) Receive initial hello from server (usually connected/success).
            try:
                hello_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Arbitrage WS: timeout waiting for server hello")
                return

            for msg in self._as_messages(hello_raw):
                if msg.get("T") == "error":
                    logger.error(f"Arbitrage WS hello error: {msg}")
                    return

            # 2) Authenticate and verify ack.
            auth_msg = json.dumps(
                {
                    "action": "auth",
                    "key": config.alpaca_api_key,
                    "secret": config.alpaca_secret_key,
                }
            )
            await ws.send(auth_msg)
            auth_ok = await self._wait_for_auth_ack(ws, timeout=12.0)
            if not auth_ok:
                logger.warning("Arbitrage WS auth timeout (no authenticated ack)")
                return

            # 3) Subscribe and verify ack.
            sub_msg = json.dumps({"action": "subscribe", "trades": ["BTC/USD"]})
            await ws.send(sub_msg)
            sub_ok = await self._wait_for_sub_ack(ws, timeout=10.0)
            if not sub_ok:
                logger.warning("Arbitrage WS subscribe timeout (no subscription ack)")
                return

            logger.info("Arbitrage WS subscribed to BTC/USD trades")

            # 4) Listen for trades.
            while not stop_event.is_set():
                try:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    # No trades for 30s: force ping/pong keepalive.
                    pong = await ws.ping()
                    await asyncio.wait_for(pong, timeout=10)
                    continue

                messages = self._as_messages(msg_raw)
                if not messages:
                    continue

                for msg in messages:
                    mtype = msg.get("T")
                    if mtype == "t":
                        await self._process_trade(msg)
                    elif mtype == "error":
                        raise RuntimeError(f"Arbitrage WS stream error: {msg}")

    async def _process_trade(self, trade: dict):
        """Process a single BTC/USD trade tick."""
        try:
            price = float(trade.get("p", 0))
            size = float(trade.get("s", 0))
        except (ValueError, TypeError):
            return

        if price <= 0:
            return

        now = time.monotonic()
        self._trade_count += 1

        # Add to buffers
        self._price_buffer.append((now, price))
        self._volume_buffer.append(size)

        # Check every 10 trades to reduce CPU
        if self._trade_count % 10 != 0:
            return

        # Trim price buffer to 60s window
        cutoff = now - 60.0
        while self._price_buffer and self._price_buffer[0][0] < cutoff:
            self._price_buffer.popleft()

        # Check for trigger condition
        await self._check_trigger(now, price, size)

    async def _check_trigger(self, now: float, current_price: float, current_size: float):
        """Check if BTC meets the lead-lag trigger conditions."""
        # Cooldown check
        if now - self._last_trigger_time < COOLDOWN_S:
            return

        # Get prices within 5-second window
        window_start = now - TRIGGER_WINDOW_S
        window_prices = [p for t, p in self._price_buffer if t >= window_start]

        if len(window_prices) < 2:
            return

        # Calculate price change
        first_price = window_prices[0]
        pct_change = (current_price - first_price) / first_price

        if abs(pct_change) < TRIGGER_PCT:
            return

        # Volume spike check
        if len(self._volume_buffer) < 10:
            return

        avg_volume = sum(self._volume_buffer) / len(self._volume_buffer)
        if avg_volume <= 0:
            return

        volume_ratio = current_size / avg_volume
        if volume_ratio < VOLUME_SPIKE_MULT:
            return

        # Trigger fired
        self._last_trigger_time = now
        self._trigger_count += 1

        direction = "BUY" if pct_change > 0 else "SELL"

        logger.warning(
            f"ARBITRAGE TRIGGER #{self._trigger_count}: "
            f"BTC/USD {pct_change:+.2%} in {TRIGGER_WINDOW_S}s | "
            f"Volume {volume_ratio:.1f}x avg | "
            f"-> {direction} proxies: {LAG_PROXIES}"
        )

        if self._on_signal:
            try:
                await self._on_signal(direction, LAG_PROXIES)
            except Exception as e:
                logger.error(f"Arbitrage signal callback error: {e}")

    def get_status(self) -> dict:
        """Status for logging/dashboard."""
        return {
            "trade_count": self._trade_count,
            "trigger_count": self._trigger_count,
            "buffer_size": len(self._price_buffer),
            "reconnect_count": self._reconnect_count,
            "last_trigger_ago_s": (
                round(time.monotonic() - self._last_trigger_time, 1)
                if self._last_trigger_time > 0
                else None
            ),
            "lag_proxies": LAG_PROXIES,
            "trigger_pct": TRIGGER_PCT,
            "trigger_window_s": TRIGGER_WINDOW_S,
        }
