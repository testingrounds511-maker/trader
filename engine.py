"""Trading Engine — Main loop coordinating all modules."""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config import config, FN_RULES
from bot.market_data import MarketData
from bot.technical import TechnicalAnalysis
from bot.analyst import Analyst
from bot.executor import Executor
from bot.risk_manager import RiskManager

logger = logging.getLogger("phantom.engine")


class TradingEngine:
    """Main trading engine with FundedNext compliance."""

    def __init__(self):
        self.market = MarketData()
        self.technical = TechnicalAnalysis()
        self.analyst = Analyst()
        self.executor = Executor()
        self.risk = RiskManager()

        self.running = False
        self.paused = False
        self._thread: threading.Thread | None = None

        self.cycle_count = 0
        self.last_cycle_time: str | None = None
        self.signals: list[dict] = []       # Pending signals (manual mode)
        self.trade_history: list[dict] = []
        self.decision_log: list[dict] = []
        self.errors: list[dict] = []

        self._load_history()

    def _load_history(self):
        try:
            path = Path(config.trades_file)
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                    self.trade_history = data.get("trades", [])
                    self.signals = data.get("signals", [])
        except Exception as e:
            logger.warning(f"Load history: {e}")

    def _save_history(self):
        try:
            Path("data").mkdir(exist_ok=True)
            with open(config.trades_file, "w") as f:
                json.dump({
                    "trades": self.trade_history[-500:],
                    "signals": self.signals[-50:],
                }, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Save history: {e}")

    def start(self):
        errors = config.validate()
        if errors:
            for e in errors:
                logger.error(f"Config: {e}")
            return False

        if not self.market.initialize():
            logger.error("Failed to connect to MT5")
            return False

        # Set initial balance
        account = self.market.get_account_info()
        self.risk.set_initial_balance(account.get("balance", 0))

        self.running = True
        self.paused = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        mode = "MANUAL CONFIRM" if config.manual_mode else "AUTO EXECUTE"
        logger.info(f"👻 Phantom Trader v3 started | Mode: {mode}")
        return True

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=30)
        self._save_history()
        self.market.shutdown()
        logger.info("🛑 Engine stopped")

    def pause(self):
        self.paused = True
        logger.info("⏸️ Paused")

    def resume(self):
        self.paused = False
        logger.info("▶️ Resumed")

    def _run_loop(self):
        while self.running:
            if not self.paused:
                try:
                    self._execute_cycle()
                except Exception as e:
                    error_entry = {
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    self.errors.append(error_entry)
                    logger.error(f"Cycle error: {e}")

            # Wait for next cycle
            for _ in range(config.check_interval):
                if not self.running:
                    break
                time.sleep(1)

    def _execute_cycle(self):
        """One complete analysis + trading cycle."""
        self.cycle_count += 1
        now = datetime.now(timezone.utc)
        self.last_cycle_time = now.isoformat()

        logger.info(f"═══ Cycle #{self.cycle_count} ═══")

        # Get account info
        account = self.market.get_account_info()
        if not account:
            logger.error("Cannot get account info")
            return

        positions = self.market.get_open_positions()
        position_count = len(positions)

        # Emergency check
        emergency = self.risk.should_close_all(account)
        if emergency["close_all"]:
            logger.warning(f"🚨 {emergency['reason']}")
            if not config.manual_mode:
                self.executor.close_all_positions()
            else:
                self.signals.append({
                    "type": "EMERGENCY",
                    "message": emergency["reason"],
                    "timestamp": now.isoformat(),
                })
            return

        # Check compliance
        risk_status = self.risk.get_status()
        compliance = self.risk.can_trade(account, position_count)

        if not compliance["allowed"]:
            for reason in compliance["reasons"]:
                logger.info(f"⛔ {reason}")
            return

        for warning in compliance.get("warnings", []):
            logger.warning(warning)

        # Analyze each symbol
        for symbol in config.symbols:
            try:
                self._analyze_symbol(symbol, account, positions, risk_status)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")

        self._save_history()

    def _analyze_symbol(
        self,
        symbol: str,
        account: dict,
        positions: list,
        risk_status: dict,
    ):
        """Analyze a single symbol and generate signal/trade."""
        # Skip if already have position in this symbol
        existing = [p for p in positions if p.get("symbol") == symbol]
        if existing:
            logger.debug(f"{symbol}: already have position, skipping")
            return

        # Get market data
        candles = self.market.get_candles(symbol, count=200)
        if candles.empty:
            return

        # Technical analysis
        ta = self.technical.analyze(candles)
        if "error" in ta:
            logger.warning(f"{symbol} TA error: {ta['error']}")
            return

        # Get AI analysis
        decision = self.analyst.analyze(
            symbol=symbol,
            technical=ta,
            account_info=account,
            risk_status=risk_status,
            open_positions=positions,
        )

        # Log decision
        self.decision_log.append(decision)
        if len(self.decision_log) > 100:
            self.decision_log = self.decision_log[-100:]

        # Only act on BUY/SELL with high confidence
        if decision["decision"] == "HOLD":
            return

        if decision.get("confidence", 0) < 0.7:
            logger.info(f"{symbol}: Low confidence ({decision['confidence']}), holding")
            return

        # Calculate proper lot size
        symbol_info = self.market.get_symbol_info(symbol)
        if not symbol_info:
            return

        max_risk = self.risk.get_max_risk_for_trade(account)
        if max_risk <= 0:
            logger.info(f"{symbol}: No risk budget available")
            return

        # Use ATR for SL distance
        atr = ta.get("atr", 0)
        sl_distance = atr * config.sl_atr_multiplier
        price = ta["current_price"]

        if decision["decision"] == "BUY":
            sl_price = price - sl_distance
            tp_price = price + (sl_distance * config.tp_rr_ratio)
        else:  # SELL
            sl_price = price + sl_distance
            tp_price = price - (sl_distance * config.tp_rr_ratio)

        # Calculate lot size
        digits = symbol_info.get("digits", 5)
        sl_pips = self.technical.pips_from_price(sl_distance, digits)
        lot_size = self.technical.calculate_lot_size(
            account_balance=account.get("balance", 0),
            risk_pct=min(max_risk, config.risk_per_trade_pct),
            sl_distance_pips=sl_pips,
        )

        # Execute or signal
        trade_data = {
            "symbol": symbol,
            "direction": decision["decision"],
            "lot_size": lot_size,
            "entry_price": price,
            "sl": round(sl_price, digits),
            "tp": round(tp_price, digits),
            "confidence": decision["confidence"],
            "reasoning": decision["reasoning"],
            "risk_level": decision["risk_level"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        result = self.executor.place_trade(
            symbol=symbol,
            direction=decision["decision"],
            lot_size=lot_size,
            sl_price=sl_price,
            tp_price=tp_price,
            comment=f"Phantom|{decision['confidence']:.0%}",
        )

        if result.get("success"):
            trade_data["ticket"] = result["ticket"]
            trade_data["status"] = "EXECUTED"
            self.trade_history.append(trade_data)
            self.risk.record_trade_day()
        elif result.get("mode") == "MANUAL":
            trade_data["status"] = "SIGNAL"
            self.signals.append(trade_data)
            self.risk.record_trade_day()
            logger.info(
                f"📡 SIGNAL: {decision['decision']} {symbol} | "
                f"Lot: {lot_size} | SL: {sl_price:.5f} | TP: {tp_price:.5f}"
            )
        else:
            trade_data["status"] = "FAILED"
            trade_data["error"] = result.get("error", "Unknown")
            self.trade_history.append(trade_data)

    def clear_signal(self, index: int):
        """Remove a signal after manual execution or dismissal."""
        if 0 <= index < len(self.signals):
            self.signals.pop(index)

    def get_state(self) -> dict:
        """Get complete engine state for dashboard."""
        account = self.market.get_account_info()
        positions = self.market.get_open_positions()
        risk_status = self.risk.get_status()

        # Calculate live P&L
        equity = account.get("equity", 0)
        initial = risk_status.get("initial_balance", 0)
        profit_pct = ((equity - initial) / initial * 100) if initial else 0
        daily_loss = self.risk._calc_daily_loss(account) * 100
        max_loss = self.risk._calc_max_loss(equity) * 100

        compliance = self.risk.can_trade(account, len(positions))

        return {
            "running": self.running,
            "paused": self.paused,
            "manual_mode": config.manual_mode,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle_time,
            "account": account,
            "positions": positions,
            "signals": self.signals,
            "trade_history": self.trade_history[-50:],
            "decision_log": self.decision_log[-20:],
            "errors": self.errors[-10:],
            "risk_status": risk_status,
            "compliance": compliance,
            "live_metrics": {
                "profit_pct": round(profit_pct, 2),
                "daily_loss_pct": round(daily_loss, 2),
                "max_drawdown_pct": round(max_loss, 2),
                "target_pct": FN_RULES.PROFIT_TARGET_PCT * 100,
                "daily_limit_pct": FN_RULES.DAILY_LOSS_LIMIT_PCT * 100,
                "max_limit_pct": FN_RULES.MAX_LOSS_LIMIT_PCT * 100,
            },
            "api_costs": self.analyst.get_cost_estimate(),
            "config": {
                "symbols": config.symbols,
                "timeframe": config.timeframe,
                "interval": config.check_interval,
                "risk_per_trade": config.risk_per_trade_pct,
                "manual_mode": config.manual_mode,
            },
        }
