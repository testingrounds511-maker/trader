"""v3.6 — Phantom Wolf Async Engine ("Quantum Predator").

Asynchronous orchestrator that replaces the threading-based TradingEngine.
Reuses existing sync modules (Executor, RiskManager, Analyst, TechnicalAnalysis)
via asyncio.to_thread() and adds new async capabilities (NLP, arbitrage, etc.).
"""

import asyncio
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import config
from executor import Executor
from risk_manager import RiskManager
from analyst import Analyst
from technical import TechnicalAnalysis
from data_layer import AsyncMarketDataProxy, SessionManager
from compliance import BrokerComplianceManager
from risk_management import CapitalRatchetManager

logger = logging.getLogger("phantom.wolf")


class PhantomWolfEngine:
    """Async trading engine with continuous 1-second resolution loop.

    Architecture:
        - Main loop runs every CHECK_INTERVAL, evaluating all symbols
        - Background tasks: IntelligenceFeed (RSS), ArbitrageMonitor (WebSocket)
        - All orders routed through BrokerComplianceManager (limit only, no market)
        - Capital protected by CapitalRatchetManager (HWM tiers)
    """

    VERSION = "3.6.0"

    def __init__(self):
        # ── Existing sync modules (reused) ──
        self.executor = Executor()
        self.risk_manager = RiskManager()
        self.analyst = Analyst()
        self.technical = TechnicalAnalysis()

        # ── New v3.6 async modules ──
        self.data_proxy = AsyncMarketDataProxy()
        self.compliance = BrokerComplianceManager(config.initial_capital_usd)
        self.ratchet = CapitalRatchetManager(config.initial_capital_usd)

        # Optional modules (feature-flagged)
        self.nlp = None
        self.intel_feed = None
        self.thematic = None
        self.arbitrage = None

        # ── State ──
        self.running = False
        self.paused = False
        self.cycle_count = 0
        self.last_cycle_time: str | None = None
        self.last_decisions: dict = {}
        self.decision_log: list[dict] = []
        self.trade_history: list[dict] = []
        self.errors: list[dict] = []

        # Previous signal cache for confirmation
        self._prev_signals: dict[str, str] = {}

        # State snapshot for dashboard
        self._state_snapshot: dict = {}
        self._stop_event: asyncio.Event | None = None
        self._capital_mode_notice_logged = False
        self._capital_mismatch_notice_logged = False

        # DB
        self.db_path = "data/trades.db"
        self._load_history()

    def _load_history(self):
        try:
            Path("data").mkdir(exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS trades
                         (timestamp TEXT, action TEXT, symbol TEXT, price REAL,
                          pnl REAL, confidence REAL, reasoning TEXT,
                          news_factor TEXT, score REAL)''')
            c.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 500")
            rows = c.fetchall()
            self.trade_history = []
            for r in rows:
                self.trade_history.append({
                    "timestamp": r[0], "action": r[1], "symbol": r[2],
                    "price": r[3], "pnl": r[4], "confidence": r[5],
                    "reasoning": r[6], "news_factor": r[7], "score": r[8],
                })
            self.trade_history.reverse()
            conn.close()
        except Exception as e:
            logger.warning(f"Could not load history: {e}")

    def _record_trade_db(self, trade: dict):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?)", (
                trade["timestamp"], trade["action"], trade["symbol"],
                float(trade.get("price") or 0), float(trade.get("pnl") or 0),
                float(trade.get("confidence") or 0), trade.get("reasoning", ""),
                trade.get("news_factor", ""), float(trade.get("score") or 0),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Could not save trade to DB: {e}")

    def _build_effective_account(self, raw_account: dict) -> dict:
        """Build an account view used for sizing/compliance.

        When CAPITAL_BASE_MODE=cap_to_initial, broker balances are scaled down
        proportionally so risk sizing behaves as if equity started at INITIAL_CAPITAL_USD.
        """
        account = dict(raw_account)
        raw_equity = float(raw_account.get("equity", 0) or 0)
        mode = getattr(config, "capital_base_mode", "broker")
        scale = 1.0

        if mode == "cap_to_initial" and raw_equity > 0:
            target = max(1.0, float(config.initial_capital_usd))
            scale = min(1.0, target / raw_equity)

        def _scaled(key: str) -> float:
            return float(raw_account.get(key, 0) or 0) * scale

        for key in (
            "equity",
            "cash",
            "buying_power",
            "regt_buying_power",
            "non_marginable_buying_power",
            "portfolio_value",
        ):
            account[key] = _scaled(key)

        account["_capital_scale_factor"] = scale
        account["_raw_equity"] = raw_equity
        account["_raw_cash"] = float(raw_account.get("cash", 0) or 0)
        account["_capital_mode"] = mode
        return account

    @staticmethod
    def _scaled_amount_from_account(amount: float, account: dict | None) -> float:
        if amount <= 0:
            return 0.0
        if not account:
            return amount
        scale = float(account.get("_capital_scale_factor", 1.0) or 1.0)
        return max(0.0, amount * scale)

    # ────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────

    async def run(self):
        """Main entry point — runs the async engine until interrupted."""
        if self.running:
            logger.warning("Engine already running")
            return

        self.running = True
        self._stop_event = asyncio.Event()
        stop_event = self._stop_event

        logger.info(f"Phantom Wolf v{self.VERSION} — Quantum Predator Engine starting")
        logger.info(f"  Capital: ${config.initial_capital_usd:.2f} | Profile: {config.risk_profile}")
        logger.info(f"  Capital Base Mode: {config.capital_base_mode}")
        logger.info(f"  Symbols: {len(config.crypto_pairs)} crypto + {len(config.stock_symbols)} stocks")

        # Initialize optional modules
        await self._init_optional_modules()

        # Log active integrations
        integrations = []
        if self.nlp:
            integrations.append("Groq NLP")
        if self.thematic:
            integrations.append("Thematic (Quiver)")
        if self.intel_feed:
            integrations.append("Intelligence Feed (RSS)")
        if self.arbitrage:
            integrations.append("BTC Arbitrage (WebSocket)")
        logger.info(f"  Integrations: {', '.join(integrations) if integrations else 'Base only'}")

        try:
            async with asyncio.TaskGroup() as tg:
                # Core trading loop
                tg.create_task(self._main_loop(stop_event))

                # Background intelligence feed
                if self.intel_feed:
                    tg.create_task(self.intel_feed.run(stop_event))

                # Background BTC arbitrage monitor
                if self.arbitrage:
                    tg.create_task(
                        self.arbitrage.run(stop_event, self._on_arbitrage_signal)
                    )

        except* KeyboardInterrupt:
            logger.info("KeyboardInterrupt — shutting down")
        except* Exception as eg:
            for exc in eg.exceptions:
                logger.error(f"TaskGroup error: {exc}")
        finally:
            self.running = False
            await self._shutdown()
            self._stop_event = None

    def request_stop(self):
        """Signal the async loop to stop on the next tick."""
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()

    async def _init_optional_modules(self):
        """Initialize feature-flagged modules."""
        if config.has_groq:
            try:
                from nlp_engine import NLPEngine
                self.nlp = NLPEngine()
                logger.info("NLP Engine (Groq) initialized")
            except ImportError:
                logger.warning("nlp_engine.py not found — NLP disabled")

        if config.has_groq:  # Intel feed needs NLP to be useful
            try:
                from intelligence_feed import IntelligenceFeed
                self.intel_feed = IntelligenceFeed()
                logger.info("Intelligence Feed (RSS) initialized")
            except ImportError:
                logger.warning("intelligence_feed.py not found — RSS disabled")

        if config.has_quiver:
            try:
                from thematic import ThematicProtocol
                self.thematic = ThematicProtocol()
                logger.info("Thematic Protocol (Quiver) initialized")
            except ImportError:
                logger.warning("thematic.py not found — Thematic disabled")

        # Arbitrage runs without special keys (uses Alpaca websocket)
        try:
            from arbitrage import ArbitrageMonitor
            self.arbitrage = ArbitrageMonitor()
            logger.info("Arbitrage Monitor (BTC WebSocket) initialized")
        except ImportError:
            logger.warning("arbitrage.py not found — Arbitrage disabled")

    async def _shutdown(self):
        """Clean shutdown of all async resources."""
        logger.info("Shutting down async engine...")
        await SessionManager.close()
        logger.info("Phantom Wolf engine stopped")

    # ────────────────────────────────────────────
    # Main Loop
    # ────────────────────────────────────────────

    async def _main_loop(self, stop_event: asyncio.Event):
        """Continuous loop with 1-second resolution, executing cycles at interval."""
        interval_secs = max(60, config.check_interval * 60)
        last_cycle_time = 0.0

        logger.info(f"Main loop started — cycle interval: {config.check_interval}min")

        while not stop_event.is_set():
            now = time.monotonic()

            if now - last_cycle_time >= interval_secs:
                try:
                    await self._execute_cycle()
                except Exception as e:
                    self.errors.append({
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    self.errors = self.errors[-50:]
                    logger.error(f"Cycle error: {e}")
                last_cycle_time = now

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                break  # stop_event was set
            except asyncio.TimeoutError:
                continue

    # ────────────────────────────────────────────
    # Trading Cycle
    # ────────────────────────────────────────────

    async def _execute_cycle(self):
        """One full trading cycle — async version of engine._execute_multi_asset_cycle."""
        if self.paused:
            return

        self.cycle_count += 1
        self.last_cycle_time = datetime.now(timezone.utc).isoformat()
        cycle_id = f"W{self.cycle_count:04d}"
        logger.info(f"--- Wolf Cycle {cycle_id} ---")

        # 1. Health check
        healthy = await asyncio.to_thread(self.executor.check_health)
        if not healthy:
            logger.critical("ALPACA API DOWN — HALTING CYCLE")
            return

        # 2. Account state (raw broker account + effective sizing account)
        raw_account = await asyncio.to_thread(self.executor.get_account)
        if "error" in raw_account:
            logger.error(f"Account error: {raw_account['error']}")
            return

        account = self._build_effective_account(raw_account)
        equity = float(account.get("equity", 0))
        raw_equity = float(account.get("_raw_equity", equity))
        scale = float(account.get("_capital_scale_factor", 1.0))
        mode = str(account.get("_capital_mode", "broker"))
        if mode == "cap_to_initial" and scale < 0.999 and not self._capital_mode_notice_logged:
            logger.info(
                f"CAPITAL MODE: cap_to_initial active | raw_equity=${raw_equity:.2f} "
                f"-> effective_equity=${equity:.2f} (scale={scale:.6f})"
            )
            self._capital_mode_notice_logged = True

        # 3. Capital Ratchet check
        ratchet_action = self.ratchet.update(equity)
        ratchet_status = self.ratchet.get_status()
        logger.info(
            f"RATCHET: Equity ${equity:.2f} | HWM ${ratchet_status['high_water_mark']:.2f} "
            f"| Floor ${ratchet_status['current_floor']:.2f} "
            f"| Tiers {ratchet_status['tiers_reached']}"
        )

        if ratchet_action.get("warning"):
            logger.warning(ratchet_action["warning"])

        if ratchet_action["liquidate"]:
            # Guard: verify API is actually reachable before liquidating.
            # A network outage can report $0 equity, triggering a false breach.
            api_ok = await asyncio.to_thread(self.executor.check_health)
            if not api_ok:
                logger.critical(
                    "RATCHET BREACH detected BUT Alpaca API unreachable — "
                    "SKIPPING liquidation (possible network outage)"
                )
                return
            logger.critical("RATCHET BREACH — executing terminal breaker")
            await self.ratchet.execute_terminal_breaker(self.executor)
            if ratchet_action["exit"]:
                logger.critical("TERMINAL EXIT — sys.exit()")
                sys.exit(1)
            return

        # 4. Compliance: settled cash
        self.compliance.cleanup_settled()
        settled_cash = self.compliance.get_settled_cash(account)
        max_per_trade = self.compliance.max_trade_size(settled_cash)
        logger.info(
            f"COMPLIANCE: Settled Cash ${settled_cash:.2f} | "
            f"Max/Trade ${max_per_trade:.2f} | "
            f"Pending {self.compliance.get_status()['pending_settlements']} settlements"
        )

        # 5. Drawdown recovery + cooldowns (existing risk manager)
        self.risk_manager.check_drawdown_recovery(equity)
        self.risk_manager.decrement_cooldowns()

        # 6. Get all positions
        all_positions = await asyncio.to_thread(self.executor.get_all_positions)

        if mode == "cap_to_initial" and not self._capital_mismatch_notice_logged:
            total_mv = sum(abs(float(p.get("market_value", 0) or 0)) for p in all_positions)
            if equity > 0 and total_mv > (equity * 2.0):
                logger.warning(
                    f"CAPITAL MODE MISMATCH: open positions=${total_mv:.2f} "
                    f"vs effective_equity=${equity:.2f}. "
                    "Use Force Close All to reset if this came from a previous uncapped run."
                )
                self._capital_mismatch_notice_logged = True

        # 7. Portfolio exposure
        exposure = self.risk_manager.check_portfolio_exposure(all_positions, equity)
        if exposure >= self.risk_manager.max_portfolio_exposure_pct:
            logger.info(f"Portfolio exposure {exposure:.0%} — managing positions only")

        # 8. Market status
        market_open = await asyncio.to_thread(self.executor.is_market_open)

        # 9. Parallel quote fetch for ALL instruments
        all_symbols = list(set(config.crypto_pairs + config.stock_symbols))
        if market_open:
            active_symbols = all_symbols
        else:
            # Market closed: crypto only (+ manage existing stock positions)
            active_symbols = config.crypto_pairs
            logger.info("Stock market closed — crypto only this cycle")

        quotes = await self.data_proxy.get_quotes_batch(active_symbols)
        logger.info(f"Fetched {len(quotes)}/{len(active_symbols)} quotes")

        # 10. NLP intelligence (if available)
        nlp_signals: dict = {}
        if self.nlp and self.intel_feed:
            headlines = self.intel_feed.get_latest_headlines()
            if headlines:
                nlp_signals = await self.nlp.analyze_batch(headlines)
                if nlp_signals:
                    logger.info(
                        f"NLP: {len(nlp_signals)} high-confidence signals "
                        f"from {len(headlines)} headlines"
                    )

        # 11. Thematic overrides
        thematic_overrides: dict = {}
        if self.thematic:
            thematic_overrides = await self.thematic.scan()
            if thematic_overrides:
                logger.info(f"THEMATIC: {list(thematic_overrides.keys())}")

        # 12. Process each symbol
        for symbol in active_symbols:
            if self.paused:
                break
            quote = quotes.get(symbol)
            if not quote:
                continue
            await self._analyze_and_trade(
                cycle_id=cycle_id,
                symbol=symbol,
                account=account,
                all_positions=all_positions,
                quote=quote,
                settled_cash=settled_cash,
                max_per_trade=max_per_trade,
                nlp_signal=nlp_signals.get(symbol),
                thematic_overrides=thematic_overrides,
            )

        # 13. Manage existing stock positions even when market closed
        if not market_open:
            stock_positions = [p for p in all_positions if "/" not in p["symbol"]]
            for pos in stock_positions:
                sym = pos["symbol"]
                quote = quotes.get(sym)
                if quote:
                    await self._manage_existing_position(
                        cycle_id, sym, pos, quote, account
                    )

        # 14. Update state snapshot for dashboard
        self._update_state_snapshot(account, raw_account, all_positions, ratchet_status)

    # ────────────────────────────────────────────
    # Per-Symbol Analysis & Trading
    # ────────────────────────────────────────────

    async def _analyze_and_trade(
        self,
        cycle_id: str,
        symbol: str,
        account: dict,
        all_positions: list,
        quote: dict,
        settled_cash: float,
        max_per_trade: float,
        nlp_signal: dict | None = None,
        thematic_overrides: dict | None = None,
    ):
        """Analyze one symbol and potentially trade (async)."""
        try:
            current_price = quote.get("mid", 0)
            ask_price = quote.get("ask", current_price)
            if current_price <= 0:
                return

            # 1. Market data — multi-timeframe (sync, via to_thread)
            mtf_bars = await self.data_proxy.get_multi_timeframe_bars(symbol)
            bars_1h = mtf_bars.get("1h")
            bars_4h = mtf_bars.get("4h")

            if bars_1h is None or bars_1h.empty:
                return

            # 2. Technical indicators
            bars_ind = self.technical.compute_all(bars_1h)
            signals = self.technical.get_signals(bars_ind)

            # 3. Multi-timeframe trend
            multi_tf = self.technical.compute_multi_timeframe_trend(
                bars_ind, bars_4h if bars_4h is not None else bars_1h
            )

            # 4. Current position
            position = await asyncio.to_thread(self.executor.get_position, symbol)

            # 5. NLP override: if Groq returned high-confidence signal, boost score.
            nlp_conf_min = config.nlp_action_confidence_min
            if nlp_signal and nlp_signal.get("confidence", 0) >= nlp_conf_min:
                signals["nlp_override"] = nlp_signal
                logger.info(
                    f"[{symbol}] NLP OVERRIDE: {nlp_signal['action']} "
                    f"conf={nlp_signal['confidence']:.2f}"
                )

            # 6. Thematic override: congress trades or crisis mode
            if thematic_overrides:
                congress = thematic_overrides.get(symbol, {})
                if congress.get("congress_buy"):
                    signals["congress_buy"] = True
                    logger.info(
                        f"[{symbol}] CONGRESS BUY detected: "
                        f"{congress.get('representative', 'Unknown')}"
                    )
                if thematic_overrides.get("risk_mode") == "defense":
                    defense_basket = thematic_overrides.get("defense_basket", [])
                    if symbol not in defense_basket:
                        # Reduce non-defense exposure during crisis
                        signals["crisis_penalty"] = True

            # 7. Analysis (existing heuristic, sync)
            equity = float(account.get("equity", 0))
            exposure_pct = self.risk_manager.check_portfolio_exposure(
                all_positions, equity
            ) * 100

            symbol_trades = [
                t for t in self.trade_history if t.get("symbol") == symbol
            ]
            decision = await asyncio.to_thread(
                self.analyst.analyze,
                symbol=symbol,
                signals=signals,
                position=position,
                recent_trades=symbol_trades[-5:],
                news_context={"source": "nlp", "sentiment": nlp_signal.get("action", "neutral") if nlp_signal else "neutral"},
                calendar_context={"reduce": False},
                multi_tf=multi_tf,
                portfolio_exposure=exposure_pct,
                market_intelligence={"score_delta": 0},
            )

            # NLP high-confidence override: force action.
            if nlp_signal and nlp_signal.get("confidence", 0) >= nlp_conf_min:
                nlp_action = nlp_signal.get("action", "").upper()
                if nlp_action in ("BUY", "SELL"):
                    decision["action"] = nlp_action
                    decision["confidence"] = max(
                        decision.get("confidence", 0),
                        nlp_signal["confidence"],
                    )
                    decision["reasoning"] = (
                        f"NLP Override ({nlp_signal['confidence']:.0%}): "
                        + decision.get("reasoning", "")
                    )

            self.last_decisions[symbol] = decision
            self.decision_log.append({
                "cycle": cycle_id,
                "symbol": symbol,
                "decision": decision,
                "signals": signals,
            })
            self.decision_log = self.decision_log[-200:]

            # 8. Position management
            if position:
                close_check = self.risk_manager.should_close_position(
                    position, decision, current_price=current_price,
                )
                if close_check["close"]:
                    await self._execute_close(
                        symbol, position, decision, close_check, account
                    )
                    return

            # 9. Signal confirmation (optional)
            if config.signal_confirmation and decision["action"] == "BUY" and position is None:
                prev_dir = self._prev_signals.get(symbol, "NEUTRAL")
                if prev_dir not in ("BUY", "BULLISH"):
                    self._prev_signals[symbol] = decision["action"]
                    return

            # 10. New trade — ALL LIMIT ORDERS via compliance
            if decision["action"] == "BUY" and position is None:
                notional = self.risk_manager.calculate_position_size(
                    account, decision, symbol, positions=all_positions,
                )
                # Compliance: cap to settled cash tranche
                notional = min(notional, max_per_trade)
                # Compliance: never exceed settled cash
                notional = min(notional, settled_cash)

                if notional >= 1.0:
                    result = await self.compliance.execute_sniper_limit(
                        executor=self.executor,
                        symbol=symbol,
                        side="buy",
                        notional=notional,
                        ask_price=ask_price,
                    )

                    if "error" not in result and result.get("status") != "canceled":
                        self.risk_manager.update_trailing_stop(symbol, current_price)
                        self._record_trade_entry(
                            "BUY", symbol, result, decision, notional
                        )
                        # Update local cash to prevent double-spending in cycle
                        settled_cash -= notional
                        for key in ["cash", "buying_power"]:
                            if key in account:
                                account[key] = max(
                                    0.0, float(account[key]) - notional
                                )
                    elif result.get("status") == "canceled":
                        logger.info(
                            f"[{symbol}] SNIPER MISS — order timed out"
                        )
                else:
                    logger.debug(
                        f"[{symbol}] SKIP BUY: notional ${notional:.2f} < $1.00"
                    )

            elif decision["action"] == "SELL" and position is not None:
                result = await asyncio.to_thread(
                    self.executor.close_position, symbol
                )
                if "error" not in result:
                    pnl = position.get("unrealized_pl", 0)
                    is_crypto = "/" in symbol
                    settled_amount = self._scaled_amount_from_account(
                        abs(position.get("market_value", 0)), account
                    )
                    self.compliance.record_sell(
                        settled_amount, is_crypto
                    )
                    self.risk_manager.record_trade_result(
                        pnl, symbol=symbol, is_stop_loss=False
                    )
                    if pnl < 0:
                        self.risk_manager.record_symbol_loss(symbol, pnl)
                    self.risk_manager.clear_position_tracking(symbol)
                    self._record_trade_close("SELL", symbol, position, result, decision, pnl)

            # Update signal direction
            if decision["action"] in ("BUY", "SELL"):
                self._prev_signals[symbol] = decision["action"]
            else:
                self._prev_signals[symbol] = "NEUTRAL"

        except Exception as e:
            logger.error(f"[{symbol}] Trade error: {e}")

    async def _manage_existing_position(
        self, cycle_id: str, symbol: str, position: dict, quote: dict, account: dict
    ):
        """Check TP/SL for existing positions (used when market closed for stocks)."""
        current_price = quote.get("mid", 0)
        if current_price <= 0:
            return

        decision = self.last_decisions.get(symbol, {
            "action": "HOLD", "confidence": 0.5,
            "take_profit_pct": config.take_profit_pct,
            "stop_loss_pct": config.stop_loss_pct,
        })

        close_check = self.risk_manager.should_close_position(
            position, decision, current_price=current_price,
        )
        if close_check["close"]:
            await self._execute_close(symbol, position, decision, close_check, account)

    async def _execute_close(
        self, symbol: str, position: dict, decision: dict,
        close_check: dict, account: dict,
    ):
        """Execute a position close (partial or full)."""
        is_partial = close_check.get("partial", False)
        close_pct = close_check.get("close_pct", 1.0)
        is_crypto = "/" in symbol

        if is_partial:
            result = await asyncio.to_thread(
                self.executor.close_position, symbol, percentage=close_pct * 100
            )
            if "error" not in result:
                pnl_partial = position.get("unrealized_pl", 0) * close_pct
                self.risk_manager.record_trade_result(
                    pnl_partial, symbol=symbol, is_stop_loss=False
                )
                settled_amount = self._scaled_amount_from_account(
                    abs(position.get("market_value", 0)) * close_pct, account
                )
                self.compliance.record_sell(
                    settled_amount, is_crypto
                )
                self._record_trade_close(
                    "PARTIAL_TP", symbol, position, result, decision, pnl_partial
                )
                logger.info(
                    f"[{symbol}] PARTIAL TP: closed {close_pct:.0%} — SL to break-even"
                )
        else:
            result = await asyncio.to_thread(
                self.executor.close_position, symbol
            )
            if "error" not in result:
                pnl = position.get("unrealized_pl", 0)
                is_sl = close_check.get("is_stop_loss", False)
                self.risk_manager.record_trade_result(
                    pnl, symbol=symbol, is_stop_loss=is_sl
                )
                if pnl < 0:
                    self.risk_manager.record_symbol_loss(symbol, pnl)
                self.risk_manager.clear_position_tracking(symbol)
                settled_amount = self._scaled_amount_from_account(
                    abs(position.get("market_value", 0)), account
                )
                self.compliance.record_sell(
                    settled_amount, is_crypto
                )
                label = "SL" if is_sl else "CLOSE"
                self._record_trade_close(label, symbol, position, result, decision, pnl)

    # ────────────────────────────────────────────
    # Arbitrage Callback
    # ────────────────────────────────────────────

    async def _on_arbitrage_signal(self, direction: str, proxies: list[str]):
        """Called by ArbitrageMonitor when BTC lead-lag signal fires."""
        if self.paused:
            return

        raw_account = await asyncio.to_thread(self.executor.get_account)
        if "error" in raw_account:
            return
        account = self._build_effective_account(raw_account)

        settled_cash = self.compliance.get_settled_cash(account)
        max_per_trade = self.compliance.max_trade_size(settled_cash)

        # Split allocation across proxy tickers
        per_proxy = min(max_per_trade, settled_cash / max(len(proxies), 1))

        for symbol in proxies:
            if per_proxy < 1.0:
                break

            quote = await self.data_proxy.get_single_quote(symbol)
            if not quote:
                continue

            ask = quote.get("ask", quote.get("mid", 0))
            if ask <= 0:
                continue

            if direction == "BUY":
                result = await self.compliance.execute_sniper_limit(
                    executor=self.executor,
                    symbol=symbol,
                    side="buy",
                    notional=per_proxy,
                    ask_price=ask,
                    timeout_seconds=10.0,
                )
                if "error" not in result and result.get("status") != "canceled":
                    logger.warning(
                        f"ARBITRAGE BUY: {symbol} ${per_proxy:.2f} "
                        f"(BTC lead-lag signal)"
                    )
                    settled_cash -= per_proxy

    # ────────────────────────────────────────────
    # Trade Recording
    # ────────────────────────────────────────────

    def _record_trade_entry(
        self, action: str, symbol: str, result: dict, decision: dict, notional: float
    ):
        trade = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "symbol": symbol,
            "price": float(result.get("limit_price") or result.get("filled_avg_price") or 0),
            "pnl": 0,
            "confidence": decision.get("confidence", 0),
            "reasoning": decision.get("reasoning", ""),
            "news_factor": decision.get("news_factor", "none"),
            "score": decision.get("score", 0),
        }
        self.trade_history.append(trade)
        self.trade_history = self.trade_history[-500:]
        self._record_trade_db(trade)
        logger.info(
            f"[{symbol}] {action} ${notional:.2f} | "
            f"conf={decision.get('confidence', 0):.2f} | "
            f"{decision.get('reasoning', '')[:60]}"
        )

    def _record_trade_close(
        self, action: str, symbol: str, position: dict | None,
        result: dict, decision: dict, pnl: float,
    ):
        trade = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "symbol": symbol,
            "price": position.get("current_price", 0) if position else 0,
            "pnl": pnl,
            "confidence": decision.get("confidence", 0),
            "reasoning": decision.get("reasoning", ""),
            "news_factor": decision.get("news_factor", "none"),
            "score": decision.get("score", 0),
        }
        self.trade_history.append(trade)
        self.trade_history = self.trade_history[-500:]
        self._record_trade_db(trade)
        pnl_emoji = "+" if pnl >= 0 else ""
        logger.info(f"[{symbol}] {action} PnL: {pnl_emoji}${pnl:.2f}")

    # ────────────────────────────────────────────
    # Dashboard State
    # ────────────────────────────────────────────

    def _update_state_snapshot(
        self, account: dict, raw_account: dict, positions: list, ratchet_status: dict
    ):
        """Thread-safe state snapshot for Streamlit dashboard."""
        scale = float(account.get("_capital_scale_factor", 1.0) or 1.0)
        mode = str(account.get("_capital_mode", "broker"))
        self._state_snapshot = {
            "version": self.VERSION,
            "running": self.running,
            "paused": self.paused,
            "cycle_count": self.cycle_count,
            "last_cycle_time": self.last_cycle_time,
            "account": account,
            "account_raw": raw_account,
            "capital_mode": {
                "mode": mode,
                "scale_factor": scale,
                "effective_equity": float(account.get("equity", 0) or 0),
                "raw_equity": float(raw_account.get("equity", 0) or 0),
            },
            "positions": positions,
            "ratchet": ratchet_status,
            "compliance": self.compliance.get_status(),
            "last_decisions": dict(self.last_decisions),
            "trade_count": len(self.trade_history),
            "error_count": len(self.errors),
            "modules": {
                "nlp": self.nlp is not None,
                "intel_feed": self.intel_feed is not None,
                "thematic": self.thematic is not None,
                "arbitrage": self.arbitrage is not None,
            },
        }

    def get_state(self) -> dict:
        """Sync-compatible state getter for Streamlit dashboard."""
        return self._state_snapshot

    # ────────────────────────────────────────────
    # Control Methods (for dashboard)
    # ────────────────────────────────────────────

    def pause(self):
        self.paused = True
        logger.info("Engine paused")

    def resume(self):
        self.paused = False
        logger.info("Engine resumed")

    async def force_close_all(self):
        """Emergency: close all positions."""
        self.paused = True
        result = await asyncio.to_thread(self.executor.close_all_positions)
        logger.warning(f"FORCE CLOSE ALL: {result}")
        return result
