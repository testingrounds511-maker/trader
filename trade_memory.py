"""Trade Memory — Learns from every closed trade.

Maintains a persistent database of trade outcomes and extracts
patterns: which symbols/sessions/conditions produce winners vs losers.
Feeds learned lessons into the analyst prompt for continuous improvement.
"""

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("phantom.memory")

DB_PATH = "data/trade_memory.db"


class TradeMemory:
    """Persistent trade memory with pattern extraction."""

    def __init__(self):
        Path("data").mkdir(exist_ok=True)
        self._init_db()
        self.lessons: list[str] = []
        self._load_lessons()

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            exit_price REAL,
            lot_size REAL,
            pnl REAL,
            pnl_pct REAL,
            sl REAL,
            tp REAL,
            atr_at_entry REAL,
            rsi_at_entry REAL,
            trend_at_entry TEXT,
            session TEXT,
            day_of_week INTEGER,
            hour_utc INTEGER,
            confidence REAL,
            reasoning TEXT,
            exit_reason TEXT,
            duration_minutes REAL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT,
            lesson TEXT,
            source TEXT,
            active INTEGER DEFAULT 1
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS performance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            win_rate REAL,
            avg_pnl REAL,
            avg_winner REAL,
            avg_loser REAL,
            best_session TEXT,
            worst_session TEXT,
            total_trades INTEGER,
            recommendation TEXT
        )""")
        conn.commit()
        conn.close()

    def record_trade(self, trade: dict):
        """Record a closed trade with full context."""
        now = datetime.now(timezone.utc)
        session = self._get_session(now.hour)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT INTO closed_trades 
            (timestamp, symbol, direction, entry_price, exit_price, lot_size,
             pnl, pnl_pct, sl, tp, atr_at_entry, rsi_at_entry, trend_at_entry,
             session, day_of_week, hour_utc, confidence, reasoning, exit_reason,
             duration_minutes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now.isoformat(),
                trade.get("symbol", ""),
                trade.get("direction", ""),
                float(trade.get("entry_price", 0)),
                float(trade.get("exit_price", 0)),
                float(trade.get("lot_size", 0)),
                float(trade.get("pnl", 0)),
                float(trade.get("pnl_pct", 0)),
                float(trade.get("sl", 0)),
                float(trade.get("tp", 0)),
                float(trade.get("atr", 0)),
                float(trade.get("rsi", 0)),
                trade.get("trend", ""),
                session,
                now.weekday(),
                now.hour,
                float(trade.get("confidence", 0)),
                trade.get("reasoning", ""),
                trade.get("exit_reason", ""),
                float(trade.get("duration_minutes", 0)),
            ))
        conn.commit()
        conn.close()
        logger.info(f"Trade recorded: {trade.get('symbol')} {trade.get('direction')} P/L: ${trade.get('pnl', 0):.2f}")

    def get_symbol_stats(self, symbol: str, days: int = 30) -> dict:
        """Get performance stats for a specific symbol."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""SELECT pnl, pnl_pct, direction, session, hour_utc, confidence,
                            rsi_at_entry, trend_at_entry
                     FROM closed_trades 
                     WHERE symbol = ? AND timestamp > ?""", (symbol, cutoff))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return {"total_trades": 0, "message": "No trade history"}

        wins = [r for r in rows if r[0] > 0]
        losses = [r for r in rows if r[0] <= 0]

        # Session analysis
        session_pnl = defaultdict(list)
        for r in rows:
            session_pnl[r[3]].append(r[0])

        best_session = max(session_pnl.items(), key=lambda x: sum(x[1]) / len(x[1])) if session_pnl else ("none", [0])
        worst_session = min(session_pnl.items(), key=lambda x: sum(x[1]) / len(x[1])) if session_pnl else ("none", [0])

        return {
            "total_trades": len(rows),
            "win_rate": round(len(wins) / len(rows) * 100, 1),
            "avg_pnl": round(sum(r[0] for r in rows) / len(rows), 2),
            "avg_winner": round(sum(r[0] for r in wins) / len(wins), 2) if wins else 0,
            "avg_loser": round(sum(r[0] for r in losses) / len(losses), 2) if losses else 0,
            "best_session": best_session[0],
            "worst_session": worst_session[0],
            "total_pnl": round(sum(r[0] for r in rows), 2),
        }

    def get_lessons_for_prompt(self, symbol: str = None, max_lessons: int = 5) -> str:
        """Get accumulated lessons formatted for the analyst prompt."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT lesson FROM lessons WHERE active = 1 ORDER BY id DESC LIMIT ?",
                  (max_lessons,))
        general_lessons = [r[0] for r in c.fetchall()]
        conn.close()

        # Add symbol-specific stats if available
        symbol_context = ""
        if symbol:
            stats = self.get_symbol_stats(symbol)
            if stats.get("total_trades", 0) >= 3:
                symbol_context = (
                    f"\n{symbol} HISTORY: {stats['total_trades']} trades, "
                    f"win rate {stats['win_rate']}%, avg P/L ${stats['avg_pnl']}, "
                    f"best session: {stats['best_session']}, "
                    f"worst session: {stats['worst_session']}"
                )

        if not general_lessons and not symbol_context:
            return ""

        parts = ["== LEARNED LESSONS (from past trades) =="]
        for lesson in general_lessons:
            parts.append(f"- {lesson}")
        if symbol_context:
            parts.append(symbol_context)

        return "\n".join(parts)

    def add_lesson(self, lesson: str, source: str = "auto"):
        """Add a new lesson to the knowledge base."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO lessons (created, lesson, source) VALUES (?,?,?)",
                  (datetime.now(timezone.utc).isoformat(), lesson, source))
        conn.commit()
        conn.close()
        logger.info(f"New lesson added: {lesson[:80]}...")

    def _load_lessons(self):
        """Load active lessons into memory."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT lesson FROM lessons WHERE active = 1")
        self.lessons = [r[0] for r in c.fetchall()]
        conn.close()

    @staticmethod
    def _get_session(hour_utc: int) -> str:
        """Determine forex session from UTC hour."""
        if 0 <= hour_utc < 8:
            return "asian"
        elif 8 <= hour_utc < 13:
            return "london"
        elif 13 <= hour_utc < 17:
            return "newyork"
        elif 17 <= hour_utc < 22:
            return "newyork_late"
        else:
            return "pacific"

    def get_all_stats(self, days: int = 30) -> dict:
        """Get aggregate stats across all symbols."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT symbol, pnl FROM closed_trades WHERE timestamp > ?", (cutoff,))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return {"total_trades": 0}

        symbol_pnl = defaultdict(list)
        for sym, pnl in rows:
            symbol_pnl[sym].append(pnl)

        wins = sum(1 for _, p in rows if p > 0)

        return {
            "total_trades": len(rows),
            "total_pnl": round(sum(p for _, p in rows), 2),
            "win_rate": round(wins / len(rows) * 100, 1),
            "by_symbol": {
                sym: {
                    "trades": len(pnls),
                    "total_pnl": round(sum(pnls), 2),
                    "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1),
                }
                for sym, pnls in symbol_pnl.items()
            },
            "lessons_count": len(self.lessons),
        }
