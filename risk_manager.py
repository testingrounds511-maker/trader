"""FundedNext Rule Guardian — Risk management enforcing FN Free Trial rules.

This is the most critical module. It PREVENTS the bot from violating
any FundedNext rule, acting as a hard safety layer.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import config, FN_RULES

logger = logging.getLogger("phantom.risk_manager")


class RiskManager:
    """Enforces FundedNext Free Trial compliance at all times."""

    def __init__(self):
        self.initial_balance: float = 0.0
        self.first_trade_date: datetime | None = None
        self.trading_days: set[str] = set()  # dates on which trades were made
        self._load_state()

    def _load_state(self):
        """Load persistent state."""
        try:
            path = Path("data/risk_state.json")
            if path.exists():
                with open(path) as f:
                    state = json.load(f)
                    self.initial_balance = state.get("initial_balance", 0)
                    self.first_trade_date = (
                        datetime.fromisoformat(state["first_trade_date"])
                        if state.get("first_trade_date")
                        else None
                    )
                    self.trading_days = set(state.get("trading_days", []))
        except Exception as e:
            logger.warning(f"Could not load risk state: {e}")

    def save_state(self):
        """Persist state to disk."""
        try:
            Path("data").mkdir(exist_ok=True)
            with open("data/risk_state.json", "w") as f:
                json.dump({
                    "initial_balance": self.initial_balance,
                    "first_trade_date": self.first_trade_date.isoformat() if self.first_trade_date else None,
                    "trading_days": list(self.trading_days),
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save risk state: {e}")

    def set_initial_balance(self, balance: float):
        """Set initial balance on first run."""
        if self.initial_balance == 0:
            self.initial_balance = balance
            self.save_state()
            logger.info(f"Initial balance set: ${balance:.2f}")

    def record_trade_day(self):
        """Record today as a trading day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.trading_days.add(today)
        if self.first_trade_date is None:
            self.first_trade_date = datetime.now(timezone.utc)
        self.save_state()

    # ═══════════════════════════════════════════
    # COMPLIANCE CHECKS
    # ═══════════════════════════════════════════

    def can_trade(self, account_info: dict, open_positions_count: int) -> dict:
        """Master check: can we open a new trade?

        Returns: {"allowed": bool, "reasons": [str], "warnings": [str]}
        """
        result = {"allowed": True, "reasons": [], "warnings": []}

        balance = account_info.get("balance", 0)
        equity = account_info.get("equity", 0)

        if self.initial_balance == 0:
            self.set_initial_balance(balance)

        # Check 1: Max open positions (FN limit: 30)
        if open_positions_count >= FN_RULES.MAX_OPEN_POSITIONS:
            result["allowed"] = False
            result["reasons"].append(
                f"Max positions reached ({open_positions_count}/{FN_RULES.MAX_OPEN_POSITIONS})"
            )

        # Check 2: Daily loss limit (5% with buffer)
        daily_loss = self._calc_daily_loss(account_info)
        daily_limit = config.effective_daily_loss_limit
        if daily_loss >= daily_limit:
            result["allowed"] = False
            result["reasons"].append(
                f"Daily loss limit reached: {daily_loss:.2%} >= {daily_limit:.2%}"
            )
        elif daily_loss >= daily_limit * 0.8:
            result["warnings"].append(
                f"⚠️ Approaching daily loss limit: {daily_loss:.2%} / {daily_limit:.2%}"
            )

        # Check 3: Maximum overall loss (10% with buffer)
        max_loss = self._calc_max_loss(equity)
        max_limit = config.effective_max_loss_limit
        if max_loss >= max_limit:
            result["allowed"] = False
            result["reasons"].append(
                f"Max overall loss limit reached: {max_loss:.2%} >= {max_limit:.2%}"
            )
        elif max_loss >= max_limit * 0.7:
            result["warnings"].append(
                f"⚠️ Approaching max loss limit: {max_loss:.2%} / {max_limit:.2%}"
            )

        # Check 4: Time limit (14 days)
        if self.first_trade_date:
            days_elapsed = (datetime.now(timezone.utc) - self.first_trade_date).days
            if days_elapsed >= FN_RULES.TIME_LIMIT_DAYS:
                result["allowed"] = False
                result["reasons"].append(
                    f"Trial period expired: {days_elapsed} days elapsed"
                )
            elif days_elapsed >= FN_RULES.TIME_LIMIT_DAYS - 2:
                result["warnings"].append(
                    f"⚠️ Only {FN_RULES.TIME_LIMIT_DAYS - days_elapsed} days left!"
                )

        # Check 5: Profit target reached!
        profit_pct = self._calc_profit_pct(equity)
        if profit_pct >= FN_RULES.PROFIT_TARGET_PCT:
            result["allowed"] = False
            result["reasons"].append(
                f"🎉 PROFIT TARGET REACHED! {profit_pct:.2%} >= {FN_RULES.PROFIT_TARGET_PCT:.2%}"
            )

        return result

    def get_max_risk_for_trade(self, account_info: dict) -> float:
        """Calculate maximum risk allowed for next trade considering limits."""
        equity = account_info.get("equity", 0)
        balance = account_info.get("balance", 0)

        # How much daily loss room do we have?
        daily_loss = self._calc_daily_loss(account_info)
        daily_room = max(0, config.effective_daily_loss_limit - daily_loss)

        # How much overall loss room?
        max_loss = self._calc_max_loss(equity)
        overall_room = max(0, config.effective_max_loss_limit - max_loss)

        # Take the minimum room and cap at configured risk
        available_risk = min(daily_room, overall_room, config.risk_per_trade_pct)

        return available_risk

    def _calc_daily_loss(self, account_info: dict) -> float:
        """Calculate today's loss as percentage of balance.

        FundedNext daily loss = (Yesterday's Balance - Today's Balance/Equity) / Yesterday's Balance
        We use a simplified version: (initial_balance - min(balance, equity)) / initial_balance
        """
        if self.initial_balance == 0:
            return 0.0

        balance = account_info.get("balance", 0)
        equity = account_info.get("equity", 0)
        current = min(balance, equity)

        loss = max(0, self.initial_balance - current) / self.initial_balance
        return loss

    def _calc_max_loss(self, equity: float) -> float:
        """Calculate overall drawdown from initial balance."""
        if self.initial_balance == 0:
            return 0.0
        loss = max(0, self.initial_balance - equity) / self.initial_balance
        return loss

    def _calc_profit_pct(self, equity: float) -> float:
        """Calculate profit percentage from initial balance."""
        if self.initial_balance == 0:
            return 0.0
        return (equity - self.initial_balance) / self.initial_balance

    def get_status(self) -> dict:
        """Full compliance dashboard status."""
        days_elapsed = 0
        days_remaining = FN_RULES.TIME_LIMIT_DAYS
        if self.first_trade_date:
            days_elapsed = (datetime.now(timezone.utc) - self.first_trade_date).days
            days_remaining = max(0, FN_RULES.TIME_LIMIT_DAYS - days_elapsed)

        trading_days_count = len(self.trading_days)
        min_days_met = trading_days_count >= FN_RULES.MIN_TRADING_DAYS

        return {
            "initial_balance": self.initial_balance,
            "first_trade_date": self.first_trade_date.isoformat() if self.first_trade_date else None,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "trading_days_count": trading_days_count,
            "min_trading_days_required": FN_RULES.MIN_TRADING_DAYS,
            "min_days_met": min_days_met,
            "profit_target_pct": FN_RULES.PROFIT_TARGET_PCT,
            "daily_loss_limit_pct": FN_RULES.DAILY_LOSS_LIMIT_PCT,
            "max_loss_limit_pct": FN_RULES.MAX_LOSS_LIMIT_PCT,
            "effective_daily_limit": config.effective_daily_loss_limit,
            "effective_max_limit": config.effective_max_loss_limit,
        }

    def should_close_all(self, account_info: dict) -> dict:
        """Emergency check: should we close all positions immediately?"""
        equity = account_info.get("equity", 0)
        max_loss = self._calc_max_loss(equity)

        # HARD STOP: if within 1% of max loss limit
        if max_loss >= (FN_RULES.MAX_LOSS_LIMIT_PCT - 0.01):
            return {
                "close_all": True,
                "reason": f"EMERGENCY: Max loss at {max_loss:.2%}, closing all to protect account",
            }

        # HARD STOP: Daily loss within 0.5% of limit
        daily_loss = self._calc_daily_loss(account_info)
        if daily_loss >= (FN_RULES.DAILY_LOSS_LIMIT_PCT - 0.005):
            return {
                "close_all": True,
                "reason": f"EMERGENCY: Daily loss at {daily_loss:.2%}, closing all to protect account",
            }

        return {"close_all": False}
