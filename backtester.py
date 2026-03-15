"""
Backtester v4 — GPU-accelerated portfolio simulation with walk-forward optimization.

Features:
- GPU-accelerated Monte Carlo via CuPy (falls back to NumPy if no CUDA)
- Vectorized signals using numpy arrays instead of row-by-row loops
- Walk-forward validation: train on rolling windows, test out-of-sample
- Parameter optimizer: grid search TP/SL/threshold combos
- Live-logic mode: uses actual Analyst + RiskManager for realistic simulation
- Portfolio backtest across multiple assets simultaneously
- Per-symbol weight allocation and independent signal evaluation
- Compound vs non-compound mode
- Monthly DCA injection into shared cash pool
- Per-asset performance breakdown
- Detailed metrics: Sharpe, Sortino, Calmar, max drawdown, win rate
"""

import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import config as global_config
from market_data import MarketData
from technical import TechnicalAnalysis

logger = logging.getLogger("phantom.backtester")

# ─── GPU Detection ───────────────────────────────────────────────────────────
_GPU_AVAILABLE = False
try:
    import cupy as cp
    if cp.cuda.runtime.getDeviceCount() > 0:
        _GPU_AVAILABLE = True
        logger.info(f"GPU detected: {cp.cuda.runtime.getDeviceProperties(0)['name'].decode()}")
except Exception:
    cp = None

def _xp():
    """Return cupy if GPU available, else numpy."""
    return cp if _GPU_AVAILABLE else np


# ═══════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════

@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    symbols: list = field(default_factory=lambda: ["BTC/USD"])
    symbol_weights: dict = field(default_factory=dict)
    initial_capital: float = 1000.0
    monthly_injection: float = 40.0
    days_to_backtest: int = 180
    timeframe: str = "1h"
    take_profit_pct: float = field(default_factory=lambda: global_config.take_profit_pct)
    stop_loss_pct: float = field(default_factory=lambda: global_config.stop_loss_pct)
    max_position_pct: float = field(default_factory=lambda: global_config.max_position_pct)
    compound: bool = True
    commission_pct: float = 0.001  # 0.1% per trade
    slippage_pct: float = 0.0005  # 0.05% slippage
    insider_mode: bool = False
    live_logic: bool = False  # Use real Analyst + RiskManager (slower, more realistic)
    # Backward compat
    symbol: str = ""

    def __post_init__(self):
        if self.symbol and len(self.symbols) <= 1 and self.symbols[0] == "BTC/USD":
            self.symbols = [self.symbol]
        if not self.symbols:
            self.symbols = ["BTC/USD"]
        if not self.symbol_weights:
            n = len(self.symbols)
            self.symbol_weights = {s: 1.0 / n for s in self.symbols}
        total = sum(self.symbol_weights.values())
        if total > 0:
            self.symbol_weights = {k: v / total for k, v in self.symbol_weights.items()}


@dataclass
class Trade:
    """Record of a single trade."""
    symbol: str
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    capital_at_entry: float
    capital_after: float


@dataclass
class BacktestResult:
    """Complete backtest results."""
    config: dict
    trades: list
    equity_curve: list
    metrics: dict
    monthly_breakdown: list
    compound_projection: list
    asset_performance: dict = field(default_factory=dict)
    optimization_results: dict = field(default_factory=dict)


# ═══════════════════════════════════════════
# SIGNAL STRATEGY (mirrors analyst.py scoring)
# ═══════════════════════════════════════════

class SignalStrategy:
    """Rule-based strategy matching the live analyst's weighted scoring."""

    def __init__(self, tp_pct: float = 0.03, sl_pct: float = 0.015, buy_threshold: int = 3):
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.buy_threshold = buy_threshold

    def generate_signals_vectorized(self, bars: pd.DataFrame) -> np.ndarray:
        """Generate signals for ALL bars at once using numpy. Returns array of -1/0/1."""
        n = len(bars)
        buy_scores = np.zeros(n)
        sell_scores = np.zeros(n)

        rsi = bars["rsi"].values.astype(float)
        bb_pct = bars["bb_pct"].values.astype(float)
        macd_hist = bars["macd_histogram"].values.astype(float)

        vol_ratio = bars["volume_ratio"].values.astype(float) if "volume_ratio" in bars else np.ones(n)
        adx = bars["adx"].values.astype(float) if "adx" in bars else np.full(n, np.nan)
        stoch_k = bars["stoch_k"].values.astype(float) if "stoch_k" in bars else np.full(n, np.nan)

        # RSI scoring
        buy_scores += np.where(rsi < 30, 3, np.where(rsi < 35, 2, np.where(rsi < 40, 1, 0)))
        squeeze_mask = (rsi > 70) & (vol_ratio > 2.5)
        sell_overbought = np.where(rsi > 70, 3, np.where(rsi > 65, 2, np.where(rsi > 60, 1, 0)))
        buy_scores += np.where(squeeze_mask, 2, 0)
        sell_scores += np.where(squeeze_mask, 0, sell_overbought)

        # Bollinger Bands
        buy_scores += np.where(bb_pct < 0.0, 3, np.where(bb_pct < 0.15, 2, np.where(bb_pct < 0.25, 1, 0)))
        sell_scores += np.where(bb_pct > 1.0, 3, np.where(bb_pct > 0.85, 2, np.where(bb_pct > 0.75, 1, 0)))

        # MACD + crossover
        buy_scores += np.where(macd_hist > 0, 1, 0)
        sell_scores += np.where(macd_hist < 0, 1, 0)
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = 0
        buy_scores += np.where((macd_hist > 0) & (prev_hist <= 0), 2, 0)
        sell_scores += np.where((macd_hist < 0) & (prev_hist >= 0), 2, 0)

        # ADX trend boost
        adx_valid = ~np.isnan(adx) & (adx > 25)
        buy_scores += np.where(adx_valid & (buy_scores > sell_scores), 1, 0)
        sell_scores += np.where(adx_valid & (sell_scores > buy_scores), 1, 0)

        # Stochastic
        stoch_valid = ~np.isnan(stoch_k)
        buy_scores += np.where(stoch_valid & (stoch_k < 20), 1, 0)
        sell_scores += np.where(stoch_valid & (stoch_k > 80), 1, 0)

        # Volume confirmation
        vol_valid = ~np.isnan(vol_ratio) & (vol_ratio > 1.5)
        buy_scores += np.where(vol_valid & (buy_scores > sell_scores), 1, 0)
        sell_scores += np.where(vol_valid & (sell_scores > buy_scores), 1, 0)

        signals = np.zeros(n, dtype=int)
        signals[(buy_scores >= self.buy_threshold) & (buy_scores > sell_scores)] = 1
        signals[(sell_scores >= self.buy_threshold) & (sell_scores > buy_scores)] = -1
        signals[0] = 0
        return signals

    def generate_signal(self, row: pd.Series, prev_row: pd.Series = None) -> str:
        """Single-bar signal (backward compatible)."""
        rsi = row.get("rsi")
        bb_pct = row.get("bb_pct")
        macd_hist = row.get("macd_histogram")
        vol_ratio = row.get("volume_ratio")
        adx = row.get("adx")
        stoch_k = row.get("stoch_k")

        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in [rsi, bb_pct, macd_hist]):
            return "HOLD"

        buy_score = 0
        sell_score = 0

        if rsi < 30: buy_score += 3
        elif rsi < 35: buy_score += 2
        elif rsi < 40: buy_score += 1
        elif rsi > 70:
            if vol_ratio is not None and vol_ratio > 2.5: buy_score += 2
            else: sell_score += 3
        elif rsi > 65: sell_score += 2 if (vol_ratio is None or vol_ratio < 2.0) else 0
        elif rsi > 60: sell_score += 1

        if bb_pct is not None:
            if bb_pct < 0.0: buy_score += 3
            elif bb_pct < 0.15: buy_score += 2
            elif bb_pct < 0.25: buy_score += 1
            elif bb_pct > 1.0: sell_score += 3
            elif bb_pct > 0.85: sell_score += 2
            elif bb_pct > 0.75: sell_score += 1

        if macd_hist > 0:
            buy_score += 1
            if prev_row is not None:
                prev_hist = prev_row.get("macd_histogram", 0)
                if prev_hist is not None and not np.isnan(prev_hist) and prev_hist <= 0:
                    buy_score += 2
        elif macd_hist < 0:
            sell_score += 1
            if prev_row is not None:
                prev_hist = prev_row.get("macd_histogram", 0)
                if prev_hist is not None and not np.isnan(prev_hist) and prev_hist >= 0:
                    sell_score += 2

        if adx is not None and not np.isnan(adx) and adx > 25:
            if buy_score > sell_score: buy_score += 1
            elif sell_score > buy_score: sell_score += 1

        if stoch_k is not None and not np.isnan(stoch_k):
            if stoch_k < 20: buy_score += 1
            elif stoch_k > 80: sell_score += 1

        if vol_ratio is not None and not np.isnan(vol_ratio) and vol_ratio > 1.5:
            if buy_score > sell_score: buy_score += 1
            elif sell_score > buy_score: sell_score += 1

        if buy_score >= self.buy_threshold and buy_score > sell_score: return "BUY"
        elif sell_score >= self.buy_threshold and sell_score > buy_score: return "SELL"
        return "HOLD"


# ═══════════════════════════════════════════
# LIVE LOGIC ADAPTER (uses real Analyst + RiskManager)
# ═══════════════════════════════════════════

class LiveLogicAdapter:
    """Uses the actual Analyst and RiskManager for realistic backtesting.

    Slower than SignalStrategy but more accurate — tests the REAL decision logic
    including news context placeholders, score details, and position sizing.
    """

    def __init__(self):
        from analyst import Analyst
        from risk_manager import RiskManager
        self._analyst = Analyst()
        self._risk_manager = RiskManager()
        self._technical = TechnicalAnalysis()

    def compute_signals(self, bars: pd.DataFrame, i: int) -> dict:
        """Build the signals dict that Analyst expects, from indicator row."""
        if i < 50:
            return {}
        row = bars.iloc[i]
        prev = bars.iloc[i - 1]
        rsi = row.get("rsi", 50)
        bb_pct = row.get("bb_pct", 0.5)
        adx = row.get("adx", 15)
        macd_hist = row.get("macd_histogram", 0)

        rsi_signal = "NEUTRAL"
        if rsi < 30: rsi_signal = "OVERSOLD"
        elif rsi > 70: rsi_signal = "OVERBOUGHT"
        elif rsi > 50: rsi_signal = "BULLISH"
        else: rsi_signal = "BEARISH"

        bb_signal = "MID RANGE"
        if bb_pct < 0.0: bb_signal = "OVERSOLD"
        elif bb_pct > 1.0: bb_signal = "OVERBOUGHT"
        elif bb_pct < 0.15: bb_signal = "NEAR LOWER BAND"
        elif bb_pct > 0.85: bb_signal = "NEAR UPPER BAND"

        macd_signal = "NEUTRAL"
        prev_hist = prev.get("macd_histogram", 0)
        if macd_hist > 0:
            macd_signal = "BULLISH CROSSOVER" if (prev_hist is not None and prev_hist <= 0) else "BULLISH"
        elif macd_hist < 0:
            macd_signal = "BEARISH CROSSOVER" if (prev_hist is not None and prev_hist >= 0) else "BEARISH"

        adx_signal = "TRENDING" if adx > 25 else "NO TREND"
        plus_di = row.get("plus_di", 0)
        minus_di = row.get("minus_di", 0)

        vol_ratio = row.get("volume_ratio", 1.0)
        vol_signal = "SPIKE" if vol_ratio > 1.5 else "NORMAL"

        atr = row.get("atr", 0)
        close = row.get("close", 0)
        atr_pct = (atr / close * 100) if close > 0 else 0

        return {
            "current_price": close,
            "rsi": {"value": rsi, "signal": rsi_signal},
            "bollinger": {"signal": bb_signal},
            "macd": {"signal": macd_signal},
            "adx": {"value": adx, "signal": adx_signal, "direction": "UP" if plus_di > minus_di else "DOWN"},
            "volume": {"signal": vol_signal},
            "stochastic": {"signal": "NEUTRAL"},
            "divergence": {"type": "none", "strength": 0},
            "atr": atr,
            "atr_pct": atr_pct,
            "pct_change_1h": {"value": (close - prev.get("close", close)) / prev.get("close", close) * 100 if prev.get("close", 0) > 0 else 0},
        }

    def get_decision(self, symbol: str, bars: pd.DataFrame, i: int) -> dict:
        signals = self.compute_signals(bars, i)
        if not signals:
            return {"action": "HOLD", "confidence": 0}
        return self._analyst._heuristic_decision(
            symbol, signals, None, None, None, "Backtest", None
        )

    def get_position_size(self, account: dict, decision: dict, symbol: str) -> float:
        return self._risk_manager.calculate_position_size(account, decision, symbol, positions=[])


# ═══════════════════════════════════════════
# INSIDER UNIVERSE
# ═══════════════════════════════════════════
INSIDER_UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD",
    "NVDA", "TSLA", "MSTR", "COIN", "MARA", "PLTR",
    "TQQQ", "SOXL", "UPRO", "LABU",
    "TSM", "NVO", "BABA", "MELI", "SONY",
    "GLD", "SLV", "NUGT", "MP", "URA", "FCX",
    "SQQQ", "SOXS", "UVXY",
]


# ═══════════════════════════════════════════
# BACKTESTER ENGINE
# ═══════════════════════════════════════════

class Backtester:
    """Run portfolio backtests with optional GPU acceleration."""

    def __init__(self):
        self.market_data = MarketData()
        self.technical = TechnicalAnalysis()
        self._cached_bars = {}

    @property
    def gpu_available(self) -> bool:
        return _GPU_AVAILABLE

    def run(self, cfg: BacktestConfig = None) -> BacktestResult:
        """Execute a full backtest across all configured symbols."""
        if cfg is None:
            cfg = BacktestConfig()

        t0 = time.time()

        if cfg.insider_mode:
            self._activate_insider_mode(cfg)

        logger.info(f"Backtest: {cfg.symbols}, ${cfg.initial_capital}, {cfg.days_to_backtest}d"
                     f"{' [LIVE LOGIC]' if cfg.live_logic else ''}")

        symbol_bars = self._fetch_and_prepare(cfg)
        if not symbol_bars:
            return self._empty_result(cfg)

        min_bars = min(len(b) for b in symbol_bars.values())
        for sym in symbol_bars:
            symbol_bars[sym] = symbol_bars[sym].tail(min_bars).reset_index(drop=True)

        if cfg.live_logic:
            trades, equity_curve = self._simulate_live_logic(symbol_bars, cfg)
        else:
            strategy = SignalStrategy(tp_pct=cfg.take_profit_pct, sl_pct=cfg.stop_loss_pct)
            trades, equity_curve = self._simulate_portfolio(symbol_bars, cfg, strategy)

        metrics = self._compute_metrics(trades, equity_curve, cfg)
        asset_perf = self._compute_asset_performance(trades, list(symbol_bars.keys()))
        monthly = self._compute_monthly_breakdown(equity_curve, cfg)
        projection = self._compute_compound_projection(metrics, cfg)

        elapsed = time.time() - t0
        metrics["backtest_time_seconds"] = round(elapsed, 2)
        metrics["gpu_used"] = False
        metrics["live_logic"] = cfg.live_logic

        result = BacktestResult(
            config={k: v for k, v in vars(cfg).items()},
            trades=[vars(t) if isinstance(t, Trade) else t for t in trades],
            equity_curve=equity_curve,
            metrics=metrics,
            monthly_breakdown=monthly,
            compound_projection=projection,
            asset_performance=asset_perf,
        )

        final_eq = equity_curve[-1]["equity"] if equity_curve else cfg.initial_capital
        logger.info(f"Backtest done: {len(trades)} trades, ${final_eq:.2f}, {elapsed:.1f}s")
        return result

    def _fetch_and_prepare(self, cfg: BacktestConfig) -> dict:
        """Fetch bars and compute indicators. Cached for optimizer reuse."""
        cache_key = (tuple(cfg.symbols), cfg.days_to_backtest, cfg.timeframe)
        if cache_key in self._cached_bars:
            return self._cached_bars[cache_key]

        symbol_bars = {}
        for sym in cfg.symbols:
            bars = self.market_data.get_bars(sym, days=cfg.days_to_backtest, timeframe=cfg.timeframe)
            if bars.empty or len(bars) < 50:
                logger.warning(f"Skipping {sym}: insufficient data ({len(bars)} bars)")
                continue
            bars = self.technical.compute_all(bars)
            bars = bars.dropna(subset=["rsi", "bb_pct", "macd_histogram"]).reset_index(drop=True)
            if len(bars) >= 30:
                symbol_bars[sym] = bars

        if symbol_bars:
            self._cached_bars[cache_key] = symbol_bars
        return symbol_bars

    def _activate_insider_mode(self, cfg: BacktestConfig):
        """Scan universe for best-performing assets over the backtest period."""
        logger.info("INSIDER MODE: Scanning universe...")
        candidates = []
        universe = list(set(INSIDER_UNIVERSE + global_config.crypto_pairs + global_config.stock_symbols))

        for sym in universe:
            try:
                bars = self.market_data.get_bars(sym, days=cfg.days_to_backtest, timeframe="1d")
                if not bars.empty and len(bars) > 10:
                    start_price = float(bars.iloc[0]["close"])
                    end_price = float(bars.iloc[-1]["close"])
                    ret = (end_price - start_price) / start_price
                    candidates.append((sym, ret))
            except Exception:
                continue

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_picks = candidates[:4]

        if top_picks:
            cfg.symbols = [x[0] for x in top_picks]
            returns = [max(x[1], 0.01) for x in top_picks]
            total_score = sum(returns)
            cfg.symbol_weights = {x[0]: r / total_score for x, r in zip(top_picks, returns)}
            logger.info(f"INSIDER PICKS: {', '.join([f'{x[0]} ({x[1]*100:+.0f}%)' for x in top_picks])}")

    # ─── Standard Simulation (fast, vectorized signals) ──────────────────────

    def _simulate_portfolio(self, symbol_bars: dict, cfg: BacktestConfig,
                            strategy: SignalStrategy) -> tuple:
        """Multi-symbol portfolio sim with vectorized signals."""
        cash = cfg.initial_capital
        total_injected = cfg.initial_capital
        withdrawn_profits = 0.0

        # Pre-compute ALL signals vectorized
        symbol_signals = {}
        for sym, bars in symbol_bars.items():
            symbol_signals[sym] = strategy.generate_signals_vectorized(bars)

        positions = {sym: None for sym in symbol_bars}
        trades = []
        equity_curve = []

        bars_per_month = 24 * 30 if cfg.timeframe == "1h" else 30
        next_injection_idx = bars_per_month
        min_bars = min(len(b) for b in symbol_bars.values())

        for i in range(1, min_bars):
            if i >= next_injection_idx and cfg.monthly_injection > 0:
                cash += cfg.monthly_injection
                total_injected += cfg.monthly_injection
                next_injection_idx += bars_per_month

            for sym, bars in symbol_bars.items():
                price = float(bars.iloc[i]["close"])
                timestamp = str(bars.iloc[i].get("timestamp", i))
                pos = positions[sym]

                if pos is not None:
                    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
                    close_reason = None
                    if pnl_pct >= cfg.take_profit_pct:
                        close_reason = "TAKE_PROFIT"
                    elif pnl_pct <= -cfg.stop_loss_pct:
                        close_reason = "STOP_LOSS"

                    if close_reason:
                        exit_price = price * (1 - cfg.slippage_pct) if close_reason == "STOP_LOSS" else price
                        pnl = pos["qty"] * (exit_price - pos["entry_price"])
                        commission = pos["qty"] * exit_price * cfg.commission_pct
                        net_pnl = pnl - commission
                        cash += pos["qty"] * exit_price - commission

                        if not cfg.compound and net_pnl > 0:
                            cash -= net_pnl
                            withdrawn_profits += net_pnl

                        trades.append(Trade(
                            symbol=sym, entry_time=pos["entry_time"], exit_time=timestamp,
                            side="long", entry_price=pos["entry_price"], exit_price=exit_price,
                            quantity=pos["qty"], pnl=round(net_pnl, 4),
                            pnl_pct=round(pnl_pct * 100, 2), exit_reason=close_reason,
                            capital_at_entry=pos["capital_at_entry"], capital_after=round(cash, 2),
                        ))
                        positions[sym] = None
                        continue

                signal = symbol_signals[sym][i]

                if signal == 1 and positions[sym] is None and cash > 1:
                    weight = cfg.symbol_weights.get(sym, 1.0 / len(symbol_bars))
                    alloc = cash * cfg.max_position_pct * weight
                    alloc = min(alloc, cash * 0.95)
                    if alloc < 1.0:
                        continue
                    commission = alloc * cfg.commission_pct
                    buy_amount = alloc - commission
                    qty = buy_amount / price
                    cash -= alloc
                    positions[sym] = {
                        "entry_price": price, "qty": qty,
                        "entry_time": timestamp, "entry_idx": i,
                        "capital_at_entry": round(cash + alloc, 2),
                    }

                elif signal == -1 and positions[sym] is not None:
                    pos = positions[sym]
                    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
                    pnl = pos["qty"] * (price - pos["entry_price"])
                    commission = pos["qty"] * price * cfg.commission_pct
                    net_pnl = pnl - commission
                    cash += pos["qty"] * price - commission

                    if not cfg.compound and net_pnl > 0:
                        cash -= net_pnl
                        withdrawn_profits += net_pnl

                    trades.append(Trade(
                        symbol=sym, entry_time=pos["entry_time"], exit_time=timestamp,
                        side="long", entry_price=pos["entry_price"], exit_price=price,
                        quantity=pos["qty"], pnl=round(net_pnl, 4),
                        pnl_pct=round(pnl_pct * 100, 2), exit_reason="SIGNAL_SELL",
                        capital_at_entry=pos["capital_at_entry"], capital_after=round(cash, 2),
                    ))
                    positions[sym] = None

            # Equity snapshot
            unrealized = sum(
                pos["qty"] * (float(symbol_bars[sym].iloc[i]["close"]) - pos["entry_price"])
                for sym, pos in positions.items() if pos is not None
            )
            cost_basis = sum(
                pos["qty"] * pos["entry_price"]
                for pos in positions.values() if pos is not None
            )
            equity = cash + cost_basis + unrealized
            ref_sym = list(symbol_bars.keys())[0]
            ref_ts = str(symbol_bars[ref_sym].iloc[i].get("timestamp", i))

            equity_curve.append({
                "bar_index": i, "timestamp": ref_ts,
                "equity": round(equity, 2), "cash": round(cash, 2),
                "total_injected": round(total_injected, 2),
                "withdrawn_profits": round(withdrawn_profits, 2),
                "positions_open": sum(1 for p in positions.values() if p is not None),
            })

        # Close remaining
        for sym, pos in positions.items():
            if pos is not None:
                last_price = float(symbol_bars[sym].iloc[-1]["close"])
                pnl = pos["qty"] * (last_price - pos["entry_price"])
                commission = pos["qty"] * last_price * cfg.commission_pct
                net_pnl = pnl - commission
                cash += pos["qty"] * last_price - commission
                trades.append(Trade(
                    symbol=sym, entry_time=pos["entry_time"],
                    exit_time=str(symbol_bars[sym].iloc[-1].get("timestamp", "end")),
                    side="long", entry_price=pos["entry_price"], exit_price=last_price,
                    quantity=pos["qty"], pnl=round(net_pnl, 4),
                    pnl_pct=round(((last_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2),
                    exit_reason="BACKTEST_END",
                    capital_at_entry=pos["capital_at_entry"], capital_after=round(cash, 2),
                ))

        return trades, equity_curve

    # ─── Live Logic Simulation (uses real Analyst + RiskManager) ─────────────

    def _simulate_live_logic(self, symbol_bars: dict, cfg: BacktestConfig) -> tuple:
        """Simulate using the REAL Analyst and RiskManager — most realistic mode."""
        adapter = LiveLogicAdapter()
        cash = cfg.initial_capital
        total_injected = cfg.initial_capital
        withdrawn_profits = 0.0
        positions = {sym: None for sym in symbol_bars}
        trades = []
        equity_curve = []

        bars_per_month = 24 * 30 if cfg.timeframe == "1h" else 30
        next_injection_idx = bars_per_month
        min_bars = min(len(b) for b in symbol_bars.values())

        mock_account = {
            "equity": cash, "cash": cash,
            "buying_power": cash * 2, "non_marginable_buying_power": cash,
        }

        for i in range(50, min_bars):  # Start at 50 for indicator warmup
            if i >= next_injection_idx and cfg.monthly_injection > 0:
                cash += cfg.monthly_injection
                total_injected += cfg.monthly_injection
                next_injection_idx += bars_per_month

            for sym, bars in symbol_bars.items():
                price = float(bars.iloc[i]["close"])
                timestamp = str(bars.iloc[i].get("timestamp", i))
                pos = positions[sym]

                # Update mock account
                unrealized_all = sum(
                    p["qty"] * (float(symbol_bars[s].iloc[i]["close"]) - p["entry_price"])
                    for s, p in positions.items() if p is not None
                )
                mock_account["equity"] = cash + unrealized_all
                mock_account["cash"] = cash
                mock_account["non_marginable_buying_power"] = cash

                # Check exits
                if pos is not None:
                    pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
                    close_reason = None

                    # SL with slippage (use low of bar if available)
                    low = float(bars.iloc[i].get("low", price))
                    if low <= pos["entry_price"] * (1 - cfg.stop_loss_pct):
                        close_reason = "STOP_LOSS"
                        price = pos["entry_price"] * (1 - cfg.stop_loss_pct) * (1 - cfg.slippage_pct)

                    # TP
                    high = float(bars.iloc[i].get("high", price))
                    if not close_reason and high >= pos["entry_price"] * (1 + cfg.take_profit_pct):
                        close_reason = "TAKE_PROFIT"
                        price = pos["entry_price"] * (1 + cfg.take_profit_pct)

                    # Signal sell
                    if not close_reason:
                        decision = adapter.get_decision(sym, bars, i)
                        if decision.get("action") == "SELL":
                            close_reason = "SIGNAL_SELL"

                    if close_reason:
                        pnl_pct_actual = (price - pos["entry_price"]) / pos["entry_price"]
                        pnl = pos["qty"] * (price - pos["entry_price"])
                        commission = pos["qty"] * price * cfg.commission_pct
                        net_pnl = pnl - commission
                        cash += pos["qty"] * price - commission

                        if not cfg.compound and net_pnl > 0:
                            cash -= net_pnl
                            withdrawn_profits += net_pnl

                        trades.append(Trade(
                            symbol=sym, entry_time=pos["entry_time"], exit_time=timestamp,
                            side="long", entry_price=pos["entry_price"], exit_price=round(price, 6),
                            quantity=pos["qty"], pnl=round(net_pnl, 4),
                            pnl_pct=round(pnl_pct_actual * 100, 2), exit_reason=close_reason,
                            capital_at_entry=pos["capital_at_entry"], capital_after=round(cash, 2),
                        ))
                        positions[sym] = None
                        continue

                # Check entries
                if positions[sym] is None and cash > 10:
                    decision = adapter.get_decision(sym, bars, i)
                    if decision.get("action") == "BUY":
                        size_usd = adapter.get_position_size(mock_account, decision, sym)
                        size_usd = min(size_usd, cash * 0.95)
                        if size_usd > 10:
                            entry_price = price
                            commission = size_usd * cfg.commission_pct
                            qty = (size_usd - commission) / entry_price
                            cash -= size_usd
                            positions[sym] = {
                                "entry_price": entry_price, "qty": qty,
                                "entry_time": timestamp, "entry_idx": i,
                                "capital_at_entry": round(cash + size_usd, 2),
                            }

            # Equity snapshot
            unrealized = sum(
                pos["qty"] * (float(symbol_bars[sym].iloc[i]["close"]) - pos["entry_price"])
                for sym, pos in positions.items() if pos is not None
            )
            cost_basis = sum(
                pos["qty"] * pos["entry_price"]
                for pos in positions.values() if pos is not None
            )
            equity = cash + cost_basis + unrealized
            ref_sym = list(symbol_bars.keys())[0]
            ref_ts = str(symbol_bars[ref_sym].iloc[i].get("timestamp", i))

            equity_curve.append({
                "bar_index": i, "timestamp": ref_ts,
                "equity": round(equity, 2), "cash": round(cash, 2),
                "total_injected": round(total_injected, 2),
                "withdrawn_profits": round(withdrawn_profits, 2),
                "positions_open": sum(1 for p in positions.values() if p is not None),
            })

        # Close remaining
        for sym, pos in positions.items():
            if pos is not None:
                last_price = float(symbol_bars[sym].iloc[-1]["close"])
                pnl = pos["qty"] * (last_price - pos["entry_price"])
                commission = pos["qty"] * last_price * cfg.commission_pct
                net_pnl = pnl - commission
                cash += pos["qty"] * last_price - commission
                trades.append(Trade(
                    symbol=sym, entry_time=pos["entry_time"],
                    exit_time=str(symbol_bars[sym].iloc[-1].get("timestamp", "end")),
                    side="long", entry_price=pos["entry_price"], exit_price=last_price,
                    quantity=pos["qty"], pnl=round(net_pnl, 4),
                    pnl_pct=round(((last_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2),
                    exit_reason="BACKTEST_END",
                    capital_at_entry=pos["capital_at_entry"], capital_after=round(cash, 2),
                ))

        return trades, equity_curve

    # ═══════════════════════════════════════════
    # MONTE CARLO — GPU ACCELERATED
    # ═══════════════════════════════════════════

    def run_monte_carlo(self, cfg: BacktestConfig = None, simulations: int = 500,
                        months: int = 18, use_cached_result: BacktestResult = None) -> dict:
        """GPU-accelerated Monte Carlo simulation."""
        if cfg is None:
            cfg = BacktestConfig()

        result = use_cached_result if use_cached_result else self.run(cfg)
        if not result.trades:
            return {"error": "No trades to simulate from"}

        all_pnl_pcts = []
        for t in result.trades:
            pnl_pct = (t["pnl_pct"] if isinstance(t, dict) else t.pnl_pct) / 100
            all_pnl_pcts.append(pnl_pct)

        total_trades = len(result.trades)
        months_in_bt = max(cfg.days_to_backtest / 30, 1)
        trades_per_month = max(1, int(total_trades / months_in_bt))

        xp = _xp()
        t0 = time.time()

        pnl_array = xp.array(all_pnl_pcts, dtype=xp.float32)
        initial_equity = float(result.metrics.get("final_equity", cfg.initial_capital))
        pos_size_pct = float(cfg.max_position_pct)

        rand_indices = xp.random.randint(0, len(pnl_array), size=(simulations, months, trades_per_month))
        trade_returns = pnl_array[rand_indices]

        equities = xp.full(simulations, initial_equity, dtype=xp.float64)
        for m in range(months):
            monthly_returns = trade_returns[:, m, :]
            monthly_pnl = xp.sum(monthly_returns * pos_size_pct, axis=1) * equities
            equities = equities + monthly_pnl + cfg.monthly_injection
            equities = xp.maximum(equities, 0)

        if _GPU_AVAILABLE:
            final_equities = cp.asnumpy(equities)
        else:
            final_equities = equities

        final_equities.sort()
        elapsed = time.time() - t0

        return {
            "simulations": simulations,
            "months_projected": months,
            "monthly_injection": cfg.monthly_injection,
            "trades_per_month": trades_per_month,
            "gpu_accelerated": _GPU_AVAILABLE,
            "compute_time_seconds": round(elapsed, 3),
            "percentiles": {
                "p5": round(float(np.percentile(final_equities, 5)), 2),
                "p10": round(float(np.percentile(final_equities, 10)), 2),
                "p25": round(float(np.percentile(final_equities, 25)), 2),
                "p50_median": round(float(np.percentile(final_equities, 50)), 2),
                "p75": round(float(np.percentile(final_equities, 75)), 2),
                "p90": round(float(np.percentile(final_equities, 90)), 2),
                "p95": round(float(np.percentile(final_equities, 95)), 2),
            },
            "mean": round(float(np.mean(final_equities)), 2),
            "std": round(float(np.std(final_equities)), 2),
            "prob_above_1500": round(float(np.sum(final_equities >= 1500) / simulations * 100), 1),
            "prob_above_1000": round(float(np.sum(final_equities >= 1000) / simulations * 100), 1),
            "prob_above_500": round(float(np.sum(final_equities >= 500) / simulations * 100), 1),
            "prob_loss": round(float(np.sum(final_equities < cfg.initial_capital) / simulations * 100), 1),
            "min": round(float(np.min(final_equities)), 2),
            "max": round(float(np.max(final_equities)), 2),
        }

    # ═══════════════════════════════════════════
    # WALK-FORWARD VALIDATION
    # ═══════════════════════════════════════════

    def run_walk_forward(self, cfg: BacktestConfig = None, n_windows: int = 4,
                         train_pct: float = 0.7) -> dict:
        """Walk-forward: train on rolling windows, test out-of-sample."""
        if cfg is None:
            cfg = BacktestConfig()

        t0 = time.time()
        symbol_bars = self._fetch_and_prepare(cfg)
        if not symbol_bars:
            return {"error": "Insufficient data"}

        min_bars = min(len(b) for b in symbol_bars.values())
        for sym in symbol_bars:
            symbol_bars[sym] = symbol_bars[sym].tail(min_bars).reset_index(drop=True)

        window_size = min_bars // n_windows
        if window_size < 100:
            return {"error": f"Not enough data for {n_windows} windows"}

        windows = []
        cumulative_oos_pnl = 0.0

        for w in range(n_windows):
            start = w * window_size
            end = min(start + window_size, min_bars)
            train_end = start + int((end - start) * train_pct)

            train_bars = {sym: bars.iloc[start:train_end].reset_index(drop=True)
                          for sym, bars in symbol_bars.items()}
            test_bars = {sym: bars.iloc[train_end:end].reset_index(drop=True)
                         for sym, bars in symbol_bars.items()}

            min_train = min(len(b) for b in train_bars.values())
            min_test = min(len(b) for b in test_bars.values())
            if min_train < 30 or min_test < 20:
                continue

            best_tp, best_sl, best_pnl = cfg.take_profit_pct, cfg.stop_loss_pct, -999999
            for tp in [0.02, 0.03, 0.05, 0.08]:
                for sl in [0.01, 0.015, 0.025, 0.04]:
                    if sl >= tp:
                        continue
                    strategy = SignalStrategy(tp_pct=tp, sl_pct=sl)
                    train_cfg = BacktestConfig(
                        symbols=cfg.symbols, initial_capital=cfg.initial_capital,
                        max_position_pct=cfg.max_position_pct, compound=cfg.compound,
                        commission_pct=cfg.commission_pct,
                        take_profit_pct=tp, stop_loss_pct=sl,
                    )
                    trades, eq = self._simulate_portfolio(train_bars, train_cfg, strategy)
                    pnl = sum(t.pnl for t in trades) if trades else 0
                    if pnl > best_pnl:
                        best_pnl = pnl
                        best_tp, best_sl = tp, sl

            test_strategy = SignalStrategy(tp_pct=best_tp, sl_pct=best_sl)
            test_cfg = BacktestConfig(
                symbols=cfg.symbols, initial_capital=cfg.initial_capital,
                max_position_pct=cfg.max_position_pct, compound=cfg.compound,
                commission_pct=cfg.commission_pct,
                take_profit_pct=best_tp, stop_loss_pct=best_sl,
            )
            test_trades, test_eq = self._simulate_portfolio(test_bars, test_cfg, test_strategy)
            oos_pnl = sum(t.pnl for t in test_trades) if test_trades else 0
            cumulative_oos_pnl += oos_pnl
            oos_wins = sum(1 for t in test_trades if t.pnl > 0)

            windows.append({
                "window": w + 1, "train_bars": min_train, "test_bars": min_test,
                "optimized_tp": best_tp, "optimized_sl": best_sl,
                "train_pnl": round(best_pnl, 2), "oos_pnl": round(oos_pnl, 2),
                "oos_trades": len(test_trades),
                "oos_win_rate": round(oos_wins / len(test_trades) * 100, 1) if test_trades else 0,
            })

        elapsed = time.time() - t0
        oos_pnls = [w["oos_pnl"] for w in windows]
        profitable_windows = sum(1 for p in oos_pnls if p > 0)

        return {
            "n_windows": len(windows), "train_pct": train_pct, "windows": windows,
            "cumulative_oos_pnl": round(cumulative_oos_pnl, 2),
            "profitable_windows": profitable_windows,
            "robustness_score": round(profitable_windows / len(windows) * 100, 1) if windows else 0,
            "avg_oos_pnl": round(float(np.mean(oos_pnls)), 2) if oos_pnls else 0,
            "compute_time_seconds": round(elapsed, 2),
        }

    # ═══════════════════════════════════════════
    # PARAMETER OPTIMIZER
    # ═══════════════════════════════════════════

    def optimize_parameters(self, cfg: BacktestConfig = None,
                            tp_range: list = None, sl_range: list = None) -> dict:
        """Grid search over TP/SL combos."""
        if cfg is None:
            cfg = BacktestConfig()
        if tp_range is None:
            tp_range = [0.02, 0.03, 0.05, 0.08, 0.10]
        if sl_range is None:
            sl_range = [0.01, 0.015, 0.02, 0.03, 0.04]

        t0 = time.time()
        symbol_bars = self._fetch_and_prepare(cfg)
        if not symbol_bars:
            return {"error": "Insufficient data"}

        min_bars = min(len(b) for b in symbol_bars.values())
        for sym in symbol_bars:
            symbol_bars[sym] = symbol_bars[sym].tail(min_bars).reset_index(drop=True)

        results = []

        for tp in tp_range:
            for sl in sl_range:
                if sl >= tp:
                    continue
                strategy = SignalStrategy(tp_pct=tp, sl_pct=sl)
                test_cfg = BacktestConfig(
                    symbols=cfg.symbols, initial_capital=cfg.initial_capital,
                    monthly_injection=cfg.monthly_injection, max_position_pct=cfg.max_position_pct,
                    compound=cfg.compound, commission_pct=cfg.commission_pct,
                    take_profit_pct=tp, stop_loss_pct=sl,
                )
                trades, eq_curve = self._simulate_portfolio(symbol_bars, test_cfg, strategy)
                if not trades:
                    continue

                pnls = [t.pnl for t in trades]
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]
                final_eq = eq_curve[-1]["equity"] if eq_curve else cfg.initial_capital

                equities = [e["equity"] for e in eq_curve]
                peak = equities[0]
                max_dd = 0
                for eq in equities:
                    if eq > peak: peak = eq
                    dd = (peak - eq) / peak if peak > 0 else 0
                    max_dd = max(max_dd, dd)

                profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 999
                total_return = (final_eq / cfg.initial_capital - 1) * 100

                results.append({
                    "tp_pct": tp, "sl_pct": sl,
                    "tp_sl_ratio": round(tp / sl, 2),
                    "total_trades": len(trades),
                    "win_rate": round(len(wins) / len(trades) * 100, 1),
                    "total_return_pct": round(total_return, 2),
                    "final_equity": round(final_eq, 2),
                    "net_pnl": round(sum(pnls), 2),
                    "profit_factor": round(profit_factor, 2),
                    "max_drawdown_pct": round(max_dd * 100, 2),
                    "score": round(total_return / (max_dd * 100) if max_dd > 0 else total_return, 2),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        elapsed = time.time() - t0

        return {
            "combinations_tested": len(results),
            "compute_time_seconds": round(elapsed, 2),
            "best": results[0] if results else None,
            "top_5": results[:5],
            "all_results": results,
        }

    # ═══════════════════════════════════════════
    # METRICS
    # ═══════════════════════════════════════════

    def _compute_asset_performance(self, trades: list, symbols: list) -> dict:
        result = {}
        for sym in symbols:
            sym_trades = [t for t in trades if (t.symbol if isinstance(t, Trade) else t["symbol"]) == sym]
            if not sym_trades:
                result[sym] = {"trades": 0, "pnl": 0, "win_rate": 0, "avg_pnl": 0}
                continue
            pnls = [t.pnl if isinstance(t, Trade) else t["pnl"] for t in sym_trades]
            wins = [p for p in pnls if p > 0]
            result[sym] = {
                "trades": len(sym_trades), "pnl": round(sum(pnls), 2),
                "win_rate": round(len(wins) / len(sym_trades) * 100, 1),
                "avg_pnl": round(sum(pnls) / len(sym_trades), 4),
                "largest_win": round(max(pnls), 4) if pnls else 0,
                "largest_loss": round(min(pnls), 4) if pnls else 0,
            }
        return result

    def _compute_metrics(self, trades: list, equity_curve: list, cfg: BacktestConfig) -> dict:
        if not trades:
            return {"error": "No trades executed"}

        pnls = [t.pnl if isinstance(t, Trade) else t["pnl"] for t in trades]
        pnl_pcts = [t.pnl_pct if isinstance(t, Trade) else t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        final_equity = equity_curve[-1]["equity"] if equity_curve else cfg.initial_capital
        total_injected = equity_curve[-1]["total_injected"] if equity_curve else cfg.initial_capital
        net_profit = final_equity - total_injected

        equities = np.array([e["equity"] for e in equity_curve])
        peaks = np.maximum.accumulate(equities)
        drawdowns = (peaks - equities) / np.where(peaks > 0, peaks, 1)
        max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0

        months = cfg.days_to_backtest / 30
        total_return = (final_equity / total_injected) - 1 if total_injected > 0 else 0
        monthly_return = total_return / months if months > 0 else 0

        if len(pnl_pcts) > 1:
            sharpe = (np.mean(pnl_pcts) / np.std(pnl_pcts)) * math.sqrt(252) if np.std(pnl_pcts) > 0 else 0
        else:
            sharpe = 0

        neg_pcts = [p for p in pnl_pcts if p < 0]
        sortino = (np.mean(pnl_pcts) / np.std(neg_pcts)) * math.sqrt(252) if neg_pcts and np.std(neg_pcts) > 0 else 0

        annual_return = total_return * (365 / max(cfg.days_to_backtest, 1))
        calmar = annual_return / max_drawdown if max_drawdown > 0 else 0

        return {
            "total_trades": len(trades), "winning_trades": len(wins), "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_pnl": round(sum(pnls), 2), "net_profit": round(net_profit, 2),
            "avg_win": round(float(np.mean(wins)), 4) if wins else 0,
            "avg_loss": round(float(np.mean(losses)), 4) if losses else 0,
            "largest_win": round(max(pnls), 4) if pnls else 0,
            "largest_loss": round(min(pnls), 4) if pnls else 0,
            "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) != 0 else float("inf"),
            "initial_capital": cfg.initial_capital,
            "total_injected": round(total_injected, 2),
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100, 2),
            "avg_monthly_return_pct": round(monthly_return * 100, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2), "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "symbols_tested": len(cfg.symbols), "days_tested": cfg.days_to_backtest,
        }

    def _compute_monthly_breakdown(self, equity_curve: list, cfg: BacktestConfig) -> list:
        if not equity_curve:
            return []
        bars_per_month = 24 * 30 if cfg.timeframe == "1h" else 30
        months = []
        month_num = 1
        for start_idx in range(0, len(equity_curve), bars_per_month):
            end_idx = min(start_idx + bars_per_month - 1, len(equity_curve) - 1)
            start_eq = equity_curve[start_idx]["equity"]
            end_eq = equity_curve[end_idx]["equity"]
            injected = cfg.monthly_injection if month_num > 1 else 0
            net_eq_change = end_eq - start_eq - injected
            return_pct = (net_eq_change / start_eq * 100) if start_eq > 0 else 0
            months.append({
                "month": month_num, "start_equity": round(start_eq, 2),
                "end_equity": round(end_eq, 2), "injected": round(injected, 2),
                "net_profit": round(net_eq_change, 2), "return_pct": round(return_pct, 2),
            })
            month_num += 1
        return months

    def _compute_compound_projection(self, metrics: dict, cfg: BacktestConfig,
                                     months_ahead: int = 24) -> list:
        avg_monthly = metrics.get("avg_monthly_return_pct", 0) / 100
        final_equity = metrics.get("final_equity", cfg.initial_capital)
        scenarios = {
            "conservative": max(avg_monthly * 0.5, 0.01),
            "realistic": max(avg_monthly * 0.75, 0.02),
            "optimistic": max(avg_monthly, 0.03),
        }
        projection = []
        for month in range(0, months_ahead + 1):
            entry = {"month": month}
            for name, rate in scenarios.items():
                if month == 0:
                    entry[f"{name}_equity"] = round(final_equity, 2)
                    entry[f"{name}_injected"] = round(
                        cfg.initial_capital + (cfg.days_to_backtest / 30) * cfg.monthly_injection, 2)
                    entry[f"{name}_profit"] = round(final_equity - entry[f"{name}_injected"], 2)
                else:
                    prev = projection[month - 1]
                    new_eq = prev[f"{name}_equity"] * (1 + rate) + cfg.monthly_injection
                    total_inj = prev[f"{name}_injected"] + cfg.monthly_injection
                    entry[f"{name}_equity"] = round(new_eq, 2)
                    entry[f"{name}_injected"] = round(total_inj, 2)
                    entry[f"{name}_profit"] = round(new_eq - total_inj, 2)
            projection.append(entry)
        return projection

    def _empty_result(self, cfg: BacktestConfig) -> BacktestResult:
        return BacktestResult(
            config=vars(cfg), trades=[], equity_curve=[],
            metrics={"error": "Insufficient data"},
            monthly_breakdown=[], compound_projection=[], asset_performance={},
        )

    def save_result(self, result: BacktestResult, filepath: str = None):
        if filepath is None:
            filepath = str(Path(global_config.trades_file).parent / "backtest_result.json")
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "config": result.config, "trades": result.trades,
            "metrics": result.metrics, "asset_performance": result.asset_performance,
            "monthly_breakdown": result.monthly_breakdown,
            "compound_projection": result.compound_projection,
            "equity_curve_summary": {
                "start": result.equity_curve[0] if result.equity_curve else None,
                "end": result.equity_curve[-1] if result.equity_curve else None,
                "total_bars": len(result.equity_curve),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Backtest saved to {filepath}")


# ═══════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════

if __name__ == "__main__":
    symbols = global_config.crypto_pairs + global_config.stock_symbols
    symbols = list(set(symbols))
    cfg = BacktestConfig(symbols=symbols[:6], days_to_backtest=90, initial_capital=10000)
    bt = Backtester()
    result = bt.run(cfg)
    if "error" not in result.metrics:
        print(f"Final equity: ${result.metrics['final_equity']:,.2f}")
        print(f"Return: {result.metrics['total_return_pct']}%")
        print(f"Win rate: {result.metrics['win_rate']}%")
        print(f"Trades: {result.metrics['total_trades']}")
        bt.save_result(result)
