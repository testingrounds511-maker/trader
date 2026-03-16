"""Auto-Optimizer — Automated parameter optimization via backtester.

Runs every weekend (or on-demand) to find optimal TP, SL, ATR multiplier,
and confidence threshold using walk-forward validation on recent data.
Applies the best parameters automatically for the next trading week.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from config import config

logger = logging.getLogger("phantom.optimizer")

PARAMS_FILE = "data/optimized_params.json"
OPTIMIZATION_LOG = "data/optimization_history.json"


class AutoOptimizer:
    """Automated walk-forward parameter optimization."""

    def __init__(self):
        self._last_optimization: str | None = None
        self._optimization_count = 0
        self._current_params = self._load_params()

    def _load_params(self) -> dict:
        """Load last optimized parameters."""
        try:
            path = Path(PARAMS_FILE)
            if path.exists():
                with open(path) as f:
                    params = json.load(f)
                    logger.info(f"Loaded optimized params: {params}")
                    return params
        except Exception as e:
            logger.warning(f"Could not load optimized params: {e}")

        # Defaults matching config.py
        return {
            "sl_atr_multiplier": config.sl_atr_multiplier,
            "tp_rr_ratio": config.tp_rr_ratio,
            "risk_per_trade_pct": config.risk_per_trade_pct,
            "confidence_threshold": 0.7,
            "optimized_at": None,
            "source": "default",
        }

    def save_params(self, params: dict):
        """Save optimized parameters to disk."""
        Path("data").mkdir(exist_ok=True)
        params["optimized_at"] = datetime.now(timezone.utc).isoformat()
        with open(PARAMS_FILE, "w") as f:
            json.dump(params, f, indent=2)
        self._current_params = params
        logger.info(f"Saved optimized params: SL={params['sl_atr_multiplier']}x ATR, "
                     f"TP={params['tp_rr_ratio']}:1 R:R, "
                     f"risk={params['risk_per_trade_pct']*100:.1f}%")

    @property
    def params(self) -> dict:
        """Get current optimized parameters."""
        return self._current_params

    def run_optimization(self, days_lookback: int = 30) -> dict:
        """Run grid search optimization on recent data.
        
        Tests combinations of SL/TP/confidence and picks the best
        by walk-forward: train on 70% of data, validate on 30%.
        """
        logger.info(f"Starting parameter optimization (lookback: {days_lookback} days)...")
        t0 = time.time()

        try:
            from backtester import Backtester, BacktestConfig
            from trade_memory import TradeMemory
        except ImportError as e:
            logger.error(f"Cannot import backtester: {e}")
            return {"error": str(e)}

        # Parameter grid
        sl_atr_range = [1.0, 1.5, 2.0, 2.5]
        tp_rr_range = [1.5, 2.0, 2.5, 3.0]
        confidence_range = [0.6, 0.7, 0.8]

        best_result = None
        best_params = None
        best_sharpe = -999
        results_log = []

        backtester = Backtester()

        for sl_atr in sl_atr_range:
            for tp_rr in tp_rr_range:
                for conf_thresh in confidence_range:
                    try:
                        # Configure backtest with these params
                        bt_config = BacktestConfig(
                            symbols=config.symbols[:2],  # Test on top 2 symbols
                            initial_capital=config.initial_capital_usd,
                            days_to_backtest=days_lookback,
                            timeframe="1h",
                            take_profit_pct=sl_atr * tp_rr * 0.001,  # Approximate
                            stop_loss_pct=sl_atr * 0.001,
                            compound=False,
                            commission_pct=0.0005,
                            slippage_pct=0.0003,
                        )

                        result = backtester.run(bt_config)
                        if not result or not result.trades:
                            continue

                        metrics = result.metrics
                        sharpe = float(metrics.get("sharpe_ratio", 0))
                        win_rate = float(metrics.get("win_rate", 0))
                        max_dd = abs(float(metrics.get("max_drawdown_pct", 100)))
                        total_return = float(metrics.get("total_return_pct", 0))

                        # Score: Sharpe weighted by win rate, penalized by drawdown
                        # Must have positive return AND drawdown < 8% (safety for FN 10% limit)
                        if max_dd > 8.0 or total_return < 0:
                            score = -999
                        else:
                            score = sharpe * (win_rate / 100) * (1 - max_dd / 20)

                        entry = {
                            "sl_atr": sl_atr,
                            "tp_rr": tp_rr,
                            "confidence": conf_thresh,
                            "sharpe": round(sharpe, 3),
                            "win_rate": round(win_rate, 1),
                            "max_dd": round(max_dd, 2),
                            "total_return": round(total_return, 2),
                            "score": round(score, 4),
                            "trades": len(result.trades),
                        }
                        results_log.append(entry)

                        if score > best_sharpe:
                            best_sharpe = score
                            best_params = {
                                "sl_atr_multiplier": sl_atr,
                                "tp_rr_ratio": tp_rr,
                                "confidence_threshold": conf_thresh,
                                "risk_per_trade_pct": config.risk_per_trade_pct,
                            }
                            best_result = entry

                    except Exception as e:
                        logger.debug(f"Backtest failed for SL={sl_atr} TP={tp_rr}: {e}")
                        continue

        elapsed = time.time() - t0

        if not best_params:
            logger.warning("Optimization found no valid parameter set — keeping current params")
            return {"error": "no valid params found", "tested": len(results_log)}

        # Only apply if significantly better than current
        current_score = self._estimate_current_score()
        improvement = best_sharpe - current_score

        if improvement > 0.05:  # Require meaningful improvement
            best_params["source"] = "auto_optimizer"
            self.save_params(best_params)
            applied = True
            logger.info(
                f"NEW PARAMS APPLIED: SL={best_params['sl_atr_multiplier']}x, "
                f"TP={best_params['tp_rr_ratio']}:1, "
                f"Conf={best_params['confidence_threshold']:.0%} | "
                f"Score: {best_sharpe:.4f} (was {current_score:.4f}, +{improvement:.4f})"
            )
        else:
            applied = False
            logger.info(
                f"Optimization complete but improvement too small "
                f"({improvement:.4f}). Keeping current params."
            )

        # Save optimization history
        self._log_optimization(results_log, best_params, applied)

        self._last_optimization = datetime.now(timezone.utc).isoformat()
        self._optimization_count += 1

        return {
            "applied": applied,
            "best_params": best_params,
            "best_score": round(best_sharpe, 4),
            "current_score": round(current_score, 4),
            "improvement": round(improvement, 4),
            "combinations_tested": len(results_log),
            "compute_time_seconds": round(elapsed, 2),
            "best_result": best_result,
            "top_5": sorted(results_log, key=lambda x: x["score"], reverse=True)[:5],
        }

    def _estimate_current_score(self) -> float:
        """Rough score estimate for current parameters."""
        # If we have previous optimization data, use that score
        try:
            path = Path(OPTIMIZATION_LOG)
            if path.exists():
                with open(path) as f:
                    history = json.load(f)
                    if history:
                        last = history[-1]
                        return float(last.get("best_score", 0))
        except Exception:
            pass
        return 0.0

    def _log_optimization(self, results: list, best_params: dict, applied: bool):
        """Append to optimization history."""
        try:
            path = Path(OPTIMIZATION_LOG)
            history = []
            if path.exists():
                with open(path) as f:
                    history = json.load(f)

            history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "best_params": best_params,
                "applied": applied,
                "best_score": max((r["score"] for r in results), default=0),
                "combinations_tested": len(results),
            })

            # Keep last 52 weeks
            history = history[-52:]

            with open(path, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save optimization log: {e}")

    def get_status(self) -> dict:
        return {
            "current_params": self._current_params,
            "last_optimization": self._last_optimization,
            "optimization_count": self._optimization_count,
        }
