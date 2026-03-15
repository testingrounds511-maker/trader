"""v3.6 — Capital Ratchet System (High-Water Mark Protection).

Portfolio-level risk management that locks in gains via hardcoded
equity tiers. Operates on top of the per-trade risk_manager.py.
"""

import logging
import sys
from datetime import datetime, timezone

from config import config

logger = logging.getLogger("phantom.ratchet")

# ── HWM Tiers: (gain_multiplier, floor_multiplier) ──
# Tiers are relative to initial capital. Once equity crosses
# initial * gain_multiplier, floor locks at initial * floor_multiplier.
# Example: initial=$100k, tier (1.15, 1.05) → at $115k, floor locks at $105k.
HWM_TIER_RATIOS = [
    (1.15, 1.05),   # +15% gain → lock 5% profit
    (1.30, 1.15),   # +30% gain → lock 15% profit
    (1.50, 1.30),   # +50% gain → lock 30% profit
    (2.00, 1.70),   # +100% gain → lock 70% profit
]


class CapitalRatchetManager:
    """Protects capital gains using a one-way ratchet mechanism.

    The floor only goes UP, never down. Once a tier is crossed,
    gains are partially locked in. If equity breaches the floor,
    the system liquidates everything to protect infrastructure funds.

    Tiers scale relative to initial capital so they work for any account size.
    """

    def __init__(self, initial_capital: float | None = None):
        self.initial_capital = initial_capital or config.initial_capital_usd
        self.high_water_mark: float = self.initial_capital
        self.current_floor: float = self.initial_capital * 0.80  # Default: 80% of starting capital
        self._tiers_reached: set[float] = set()
        self._terminal_triggered: bool = False
        self._breach_timestamp: str | None = None

    def update(self, equity: float) -> dict:
        """Called every cycle with current portfolio equity.

        Returns:
            dict with keys:
                - liquidate (bool): True if all positions must be closed NOW
                - exit (bool): True if the bot should sys.exit() after liquidation
                - floor (float): Current floor value
                - hwm (float): Current high-water mark
                - warning (str|None): Warning message if approaching floor
        """
        actions = {
            "liquidate": False,
            "exit": False,
            "floor": self.current_floor,
            "hwm": self.high_water_mark,
            "warning": None,
        }

        if equity <= 0:
            actions["liquidate"] = True
            actions["exit"] = True
            logger.critical("EQUITY IS ZERO OR NEGATIVE — TERMINAL BREAKER")
            return actions

        # Update High Water Mark
        if equity > self.high_water_mark:
            old_hwm = self.high_water_mark
            self.high_water_mark = equity
            actions["hwm"] = equity
            if equity - old_hwm >= 10.0:  # Log significant HWM jumps
                logger.info(
                    f"HWM updated: ${old_hwm:.2f} → ${equity:.2f} "
                    f"(+${equity - old_hwm:.2f})"
                )

        # Check tier promotions (one-way ratchet) — thresholds scale with initial capital
        HWM_TIERS = [(self.initial_capital * g, self.initial_capital * f) for g, f in HWM_TIER_RATIOS]
        for threshold, floor in HWM_TIERS:
            if equity >= threshold and threshold not in self._tiers_reached:
                self._tiers_reached.add(threshold)
                old_floor = self.current_floor
                self.current_floor = max(self.current_floor, floor)
                actions["floor"] = self.current_floor
                logger.warning(
                    f"RATCHET TIER: Equity ${equity:.2f} crossed ${threshold:.0f} "
                    f"→ floor LOCKED at ${self.current_floor:.2f} "
                    f"(was ${old_floor:.2f})"
                )

        # Warning zone: within 10% of floor
        distance_to_floor = (equity - self.current_floor) / self.current_floor
        if 0 < distance_to_floor <= 0.10:
            actions["warning"] = (
                f"DANGER: Equity ${equity:.2f} is {distance_to_floor:.1%} "
                f"above floor ${self.current_floor:.2f}"
            )
            logger.warning(actions["warning"])

        # FLOOR BREACH — LIQUIDATE
        if equity <= self.current_floor:
            actions["liquidate"] = True
            self._breach_timestamp = datetime.now(timezone.utc).isoformat()

            logger.critical(
                f"RATCHET BREACH: Equity ${equity:.2f} <= "
                f"floor ${self.current_floor:.2f} → LIQUIDATE ALL"
            )

            # Terminal breaker: if we've passed any tier, this is a serious breach
            if self._tiers_reached:
                actions["exit"] = True
                self._terminal_triggered = True
                logger.critical(
                    f"TERMINAL BREAKER: Floor breach after reaching "
                    f"tier(s) {sorted(self._tiers_reached)} → SHUTDOWN"
                )

        return actions

    async def execute_terminal_breaker(self, executor) -> None:
        """Emergency liquidation + shutdown.

        Called by wolf_engine when update() returns liquidate=True.
        This is a one-way operation — the bot stops after execution.
        """
        import asyncio

        logger.critical("=" * 60)
        logger.critical("TERMINAL BREAKER ACTIVATED")
        logger.critical(f"  HWM: ${self.high_water_mark:.2f}")
        logger.critical(f"  Floor: ${self.current_floor:.2f}")
        logger.critical(f"  Tiers reached: {sorted(self._tiers_reached)}")
        logger.critical(f"  Breach time: {self._breach_timestamp}")
        logger.critical("  Action: CLOSE ALL POSITIONS + CANCEL ALL ORDERS")
        logger.critical("=" * 60)

        # Close all positions via Alpaca REST
        try:
            result = await asyncio.to_thread(executor.close_all_positions)
            logger.critical(f"Liquidation result: {result}")
        except Exception as e:
            logger.critical(f"Liquidation FAILED: {e}")

        # Log final state
        try:
            account = await asyncio.to_thread(executor.get_account)
            logger.critical(f"Final account state: {account}")
        except Exception:
            pass

    def get_status(self) -> dict:
        """Status snapshot for dashboard / logging."""
        return {
            "initial_capital": self.initial_capital,
            "high_water_mark": self.high_water_mark,
            "current_floor": self.current_floor,
            "tiers_reached": sorted(self._tiers_reached),
            "terminal_triggered": self._terminal_triggered,
            "breach_timestamp": self._breach_timestamp,
            "gain_pct": (
                (self.high_water_mark - self.initial_capital) / self.initial_capital * 100
                if self.initial_capital > 0 else 0
            ),
        }

    def reset(self, new_capital: float):
        """Reset ratchet state (for backtesting or manual restart)."""
        self.__init__(new_capital)
