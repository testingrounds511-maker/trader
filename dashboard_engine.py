"""Dashboard engine bridge.

Provides a sync-compatible interface for Streamlit while supporting:
- Legacy TradingEngine (v3.5, threading)
- PhantomWolfEngine (v3.6, asyncio)
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any

from config import config
from market_data import MarketData

logger = logging.getLogger("phantom.dashboard_engine")

MODE_LEGACY = "legacy"
MODE_WOLF = "wolf"


def _normalize_mode(raw_mode: str) -> str:
    raw = (raw_mode or "").strip().lower()
    if raw in {"legacy", "v35", "v3.5"}:
        return MODE_LEGACY
    return MODE_WOLF


class DashboardEngine:
    """Facade used by app.py (`start/stop/pause/resume/get_state`)."""

    def __init__(self):
        self.mode = _normalize_mode(os.getenv("DASHBOARD_ENGINE_MODE", "wolf"))
        self.market_data = MarketData()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        if self.mode == MODE_LEGACY:
            from engine import TradingEngine

            self._engine = TradingEngine()
            self.market_data = self._engine.market_data
            logger.info("Dashboard engine mode: legacy v3.5")
        else:
            from wolf_engine import PhantomWolfEngine

            self._engine = PhantomWolfEngine()
            logger.info("Dashboard engine mode: wolf v3.6")

    def start(self):
        if self.mode == MODE_LEGACY:
            self._engine.start()
            return

        if self._thread and self._thread.is_alive():
            self._engine.resume()
            return

        self._thread = threading.Thread(
            target=self._run_wolf_loop,
            name="phantom-wolf-ui",
            daemon=True,
        )
        self._thread.start()

    def _run_wolf_loop(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._engine.run())
        except Exception as e:
            logger.error(f"Wolf engine crashed in dashboard thread: {e}")
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            loop.close()
            self._loop = None

    def stop(self):
        if self.mode == MODE_LEGACY:
            self._engine.stop()
            return

        if self._loop and self._thread and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._engine.request_stop)
            self._thread.join(timeout=15)

    def pause(self):
        self._engine.pause()

    def resume(self):
        self._engine.resume()

    def force_close_all(self):
        if self.mode == MODE_LEGACY:
            return self._engine.force_close_all()

        if self._loop and self._thread and self._thread.is_alive():
            fut = asyncio.run_coroutine_threadsafe(
                self._engine.force_close_all(), self._loop
            )
            try:
                return fut.result(timeout=30)
            except Exception as e:
                return {"error": str(e)}

        try:
            return asyncio.run(self._engine.force_close_all())
        except Exception as e:
            return {"error": str(e)}

    def get_state(self) -> dict[str, Any]:
        if self.mode == MODE_LEGACY:
            state = self._engine.get_state() or {}
            state.setdefault("engine_mode", "legacy_v3.5")
            state.setdefault("engine_version", "3.5")
            state.setdefault("wolf_log_tail", [])
            return state

        return self._build_wolf_state()

    def _build_wolf_state(self) -> dict[str, Any]:
        snapshot = self._engine.get_state() or {}

        account = snapshot.get("account")
        if not isinstance(account, dict):
            account = self._engine.executor.get_account()
        if "error" in account:
            account = {}

        account_raw = snapshot.get("account_raw")
        if not isinstance(account_raw, dict):
            account_raw = self._engine.executor.get_account()
        if "error" in account_raw:
            account_raw = dict(account)

        positions = snapshot.get("positions")
        if not isinstance(positions, list):
            positions = self._engine.executor.get_all_positions()

        decision_log = snapshot.get("decision_log")
        if not isinstance(decision_log, list):
            decision_log = list(self._engine.decision_log[-200:])

        trade_history = snapshot.get("trade_history")
        if not isinstance(trade_history, list):
            trade_history = list(self._engine.trade_history[-500:])

        errors = snapshot.get("errors")
        if not isinstance(errors, list):
            errors = list(self._engine.errors[-50:])

        last_decisions = snapshot.get("last_decisions")
        if not isinstance(last_decisions, dict):
            last_decisions = dict(self._engine.last_decisions)

        modules = snapshot.get("modules")
        if not isinstance(modules, dict):
            modules = {
                "nlp": self._engine.nlp is not None,
                "intel_feed": self._engine.intel_feed is not None,
                "thematic": self._engine.thematic is not None,
                "arbitrage": self._engine.arbitrage is not None,
            }

        ratchet = snapshot.get("ratchet")
        if not isinstance(ratchet, dict):
            ratchet = self._engine.ratchet.get_status()

        compliance = snapshot.get("compliance")
        if not isinstance(compliance, dict):
            compliance = self._engine.compliance.get_status()

        capital_mode = snapshot.get("capital_mode")
        if not isinstance(capital_mode, dict):
            capital_mode = {
                "mode": config.capital_base_mode,
                "scale_factor": float(account.get("_capital_scale_factor", 1.0) or 1.0),
                "effective_equity": float(account.get("equity", 0) or 0),
                "raw_equity": float(account_raw.get("equity", account.get("equity", 0)) or 0),
            }

        running_fallback = bool(self._thread and self._thread.is_alive())
        cycle_time = snapshot.get("last_cycle_time", self._engine.last_cycle_time)
        cfg = self._config_snapshot()
        state: dict[str, Any] = {
            "engine_mode": "wolf_v3.6",
            "engine_version": snapshot.get("version", getattr(self._engine, "VERSION", "3.6.0")),
            "running": bool(snapshot.get("running", running_fallback)),
            "paused": bool(snapshot.get("paused", self._engine.paused)),
            "cycle_count": int(snapshot.get("cycle_count", self._engine.cycle_count)),
            "last_cycle_time": cycle_time,
            "last_cycle": cycle_time,
            "account": account,
            "account_raw": account_raw,
            "capital_mode": capital_mode,
            "positions": positions,
            "last_decisions": last_decisions,
            "decision_log": decision_log[-200:],
            "trade_history": trade_history[-500:],
            "errors": errors[-50:],
            "ratchet": ratchet,
            "compliance": compliance,
            "modules": modules,
            "wolf_log_tail": self._tail_file(Path("data") / "wolf_engine.log", max_lines=120),
            "risk_status": self._engine.risk_manager.get_status(),
            "api_costs": {"estimated_cost_usd": 0.0},
            "fear_metrics": {"level": 0.0, "factor": 1.0},
            "sentinel_status": {
                "total_alerts": 0,
                "last_scan": None,
                "sources": {
                    "rss": bool(modules.get("intel_feed")),
                    "newsapi": False,
                    "twitter": False,
                    "reddit": False,
                },
            },
            "recent_alerts": [],
            "market_intelligence": {"fear_greed_value": 50, "fear_greed_label": "Neutral"},
            "market_data_provider": {},
            "global_markets": {},
            "calendar": {},
            "onchain": {},
            "polymarket": {"status": {}, "opportunities": []},
            "config": cfg,
        }
        return state

    @staticmethod
    def _tail_file(path: Path, max_lines: int = 120) -> list[str]:
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return [line.rstrip("\r\n") for line in lines[-max_lines:]]
        except Exception:
            return []

    @staticmethod
    def _config_snapshot() -> dict[str, Any]:
        return {
            "crypto_pairs": list(config.crypto_pairs),
            "stock_symbols": list(config.stock_symbols),
            "night_stocks": list(config.night_stocks),
            "interval": config.check_interval,
            "risk_profile": config.risk_profile,
            "is_paper": config.is_paper,
            "initial_capital_usd": config.initial_capital_usd,
            "capital_base_mode": config.capital_base_mode,
            "tp": config.take_profit_pct,
            "sl": config.stop_loss_pct,
            "news_fast_lane": config.news_fast_lane,
            "dca_mode": config.dca_mode,
            "night_trading_enabled": config.night_trading_enabled,
            "polymarket_enabled": config.polymarket_enabled,
        }
