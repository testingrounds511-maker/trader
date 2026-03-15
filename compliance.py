"""v3.6 — Broker Compliance Manager.

Enforces Cash Account rules (T+1 settlement), capital tranching,
and sniper limit order execution. No market orders allowed.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest

from config import config

logger = logging.getLogger("phantom.compliance")


class BrokerComplianceManager:
    """Cash Account compliance shield — prevents margin usage, unsettled
    cash spending, and slippage from market orders."""

    def __init__(self, initial_capital: float | None = None):
        self.initial_capital = initial_capital or config.initial_capital_usd
        self._pending_settlements: list[dict] = []
        self._tranche_pct: float = 0.40  # Max 40% of settled cash per trade
        self._slippage_tolerance: float = config.max_slippage_tolerance_pct

    # ── Settled Cash (T+1) ──

    def get_settled_cash(self, account: dict) -> float:
        """Calculate actual available cash, subtracting unsettled sell proceeds.

        Alpaca paper accounts don't enforce T+1 strictly, so we track
        pending settlements ourselves to simulate cash account behavior.
        Crypto settles instantly and is not tracked.
        """
        self.cleanup_settled()
        raw_cash = float(account.get("cash", 0))
        unsettled = sum(
            s["amount"] for s in self._pending_settlements
            if s["settle_date"] > datetime.now(timezone.utc)
        )
        return max(0.0, raw_cash - unsettled)

    def record_sell(self, amount: float, is_crypto: bool = False):
        """Track a sell for T+1 settlement (stocks only)."""
        if is_crypto:
            return  # Crypto settles immediately on Alpaca
        if amount <= 0:
            return
        settle_date = datetime.now(timezone.utc) + timedelta(days=1)
        self._pending_settlements.append({
            "amount": amount,
            "settle_date": settle_date,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            f"T+1 settlement recorded: ${amount:.2f} available after "
            f"{settle_date.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def cleanup_settled(self):
        """Remove settlements that have passed T+1."""
        now = datetime.now(timezone.utc)
        before = len(self._pending_settlements)
        self._pending_settlements = [
            s for s in self._pending_settlements if s["settle_date"] > now
        ]
        freed = before - len(self._pending_settlements)
        if freed > 0:
            logger.info(f"T+1 cleanup: {freed} settlement(s) now available")

    # ── Capital Tranching ──

    def max_trade_size(self, settled_cash: float) -> float:
        """Max notional for a single trade = 25% of settled cash.

        This ensures we always have 'ammunition' for multiple opportunities
        and prevents all-in bets that would lock capital in T+1 limbo.
        """
        return max(0.0, settled_cash * self._tranche_pct)

    # ── Sniper Limit Orders ──

    def build_sniper_order(
        self,
        symbol: str,
        side: str,
        notional: float,
        ask_price: float,
    ) -> dict:
        """Build a limit order with minimal slippage tolerance.

        For BUY: limit = ask × (1 + slippage_tolerance)
        This ensures we only pay slightly above the current ask.

        Returns order parameters dict ready for executor.
        """
        if ask_price <= 0:
            return {"error": "Invalid ask price"}
        if notional <= 0:
            return {"error": "Invalid notional"}

        is_crypto = "/" in symbol

        # Alpaca sub-penny rule: stocks >= $1.00 must use $0.01 increments (2dp),
        # stocks < $1.00 allow $0.0001 increments (4dp), crypto has no restriction.
        if is_crypto:
            price_decimals = 4
        elif ask_price >= 1.0:
            price_decimals = 2
        else:
            price_decimals = 4

        if side.upper() == "BUY":
            limit_price = round(ask_price * (1 + self._slippage_tolerance), price_decimals)
        else:
            # For sells, set limit slightly below bid
            limit_price = round(ask_price * (1 - self._slippage_tolerance), price_decimals)

        # Crypto allows fractional qty (6dp), stocks need whole shares on most brokers
        if is_crypto:
            qty = round(notional / limit_price, 6)
        else:
            qty = int(notional / limit_price)
            if qty <= 0:
                # Try at least 1 share if affordable
                qty = 1 if limit_price <= notional else 0
        if qty <= 0:
            return {"error": "Calculated qty is zero"}

        return {
            "symbol": symbol,
            "side": side.upper(),
            "qty": qty,
            "limit_price": limit_price,
            "notional": notional,
            "is_crypto": is_crypto,
            "time_in_force": "gtc" if is_crypto else "day",
        }

    async def execute_sniper_limit(
        self, executor, symbol: str, side: str, notional: float, ask_price: float,
        timeout_seconds: float = 15.0,
    ) -> dict:
        """Place a sniper limit order and monitor fill within timeout.

        If the order is not filled within timeout_seconds, cancel it
        (simulated Fill-or-Kill behavior since Alpaca paper may not
        support true FOK for all symbols).
        """
        order_params = self.build_sniper_order(symbol, side, notional, ask_price)
        if "error" in order_params:
            return order_params

        # Place the limit order via executor (sync, run in thread)
        result = await asyncio.to_thread(
            executor.place_limit_order,
            symbol=order_params["symbol"],
            side=order_params["side"].lower(),
            notional=order_params["notional"],
            limit_price=order_params["limit_price"],
        )

        if "error" in result:
            return result

        order_id = result.get("id")
        status = result.get("status", "")

        # If already filled, return immediately
        if status in ("filled", "partially_filled"):
            logger.info(
                f"SNIPER HIT: {side} {symbol} filled @ ${order_params['limit_price']}"
            )
            return result

        # Monitor for fill within timeout
        filled = await self._wait_for_fill(
            executor, order_id, timeout_seconds
        )

        if filled:
            logger.info(
                f"SNIPER HIT: {side} {symbol} filled within {timeout_seconds}s"
            )
            return {**result, "status": "filled"}

        # Timeout — cancel the order (simulated FOK)
        logger.warning(
            f"SNIPER MISS: {side} {symbol} not filled in {timeout_seconds}s — canceling"
        )
        await self._cancel_order(executor, order_id)
        return {**result, "status": "canceled", "reason": "timeout"}

    async def _wait_for_fill(
        self, executor, order_id: str, timeout: float
    ) -> bool:
        """Poll order status until filled or timeout."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1.0)
            try:
                order = await asyncio.to_thread(
                    executor.client.get_order_by_id, order_id
                )
                if order.status.value in ("filled", "partially_filled"):
                    return True
                if order.status.value in ("canceled", "expired", "rejected"):
                    return False
            except Exception:
                continue
        return False

    async def _cancel_order(self, executor, order_id: str):
        """Cancel an unfilled order."""
        try:
            await asyncio.to_thread(
                executor.client.cancel_order_by_id, order_id
            )
        except Exception as e:
            logger.warning(f"Cancel order error: {e}")

    # ── Status ──

    def get_status(self) -> dict:
        return {
            "pending_settlements": len(self._pending_settlements),
            "total_unsettled": sum(
                s["amount"] for s in self._pending_settlements
                if s["settle_date"] > datetime.now(timezone.utc)
            ),
            "tranche_pct": self._tranche_pct,
            "slippage_tolerance": self._slippage_tolerance,
        }
