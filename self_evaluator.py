"""Self-Evaluator — Weekly performance review with Groq-powered lesson extraction.

Every Sunday at midnight UTC (or on-demand), analyzes the week's trades,
extracts lessons via Groq LLM, and stores them in TradeMemory.
The lessons accumulate over time, making the bot progressively smarter.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

from config import config
from trade_memory import TradeMemory

logger = logging.getLogger("phantom.evaluator")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

EVALUATOR_SYSTEM = """You are a trading performance analyst. You review a week of forex trades
and extract actionable lessons to improve future performance.

You receive: trade results with entry conditions (RSI, trend, session, confidence).

You must respond ONLY with valid JSON:
{
    "overall_assessment": "brief 1-sentence summary",
    "win_rate_comment": "what the win rate tells us",
    "lessons": [
        "Specific, actionable lesson 1 (e.g., 'Avoid SELL on EURUSD during London session when RSI > 40')",
        "Specific, actionable lesson 2",
        "Specific, actionable lesson 3"
    ],
    "parameter_suggestions": {
        "symbols_to_avoid": ["SYMBOL"],
        "symbols_to_focus": ["SYMBOL"],
        "best_sessions": ["session_name"],
        "worst_sessions": ["session_name"],
        "confidence_threshold_suggestion": 0.0,
        "sl_atr_suggestion": 0.0,
        "tp_rr_suggestion": 0.0
    },
    "risk_warning": "any concern about drawdown or overexposure"
}

Be brutally honest. If the strategy is losing money, say so and explain why.
Focus on PATTERNS, not individual trades. Max 5 lessons."""


TRADE_REVIEW_SYSTEM = """You are a trade reviewer. After a losing trade, you analyze what went wrong.

You receive: the trade details including entry conditions and outcome.

Respond ONLY with valid JSON:
{
    "what_went_wrong": "brief explanation",
    "lesson": "one specific, actionable rule to add (max 20 words)",
    "severity": "minor" | "major" | "critical"
}

Be specific. Not 'be more careful' but 'do not sell GBPUSD when RSI is above 45 and price is near support'."""


class SelfEvaluator:
    """Analyzes trading performance and extracts lessons using Groq."""

    def __init__(self, memory: TradeMemory):
        self.memory = memory
        self._last_evaluation: str | None = None
        self._evaluation_count = 0

    async def evaluate_week(self) -> dict:
        """Run full weekly evaluation. Call every Sunday or on-demand."""
        logger.info("Starting weekly self-evaluation...")

        # Get this week's trades
        trades = self._get_recent_trades(days=7)
        if len(trades) < 3:
            logger.info(f"Only {len(trades)} trades this week — skipping evaluation")
            return {"skipped": True, "reason": "insufficient trades"}

        # Build evaluation prompt
        prompt = self._build_evaluation_prompt(trades)

        # Get Groq analysis
        evaluation = await self._call_groq(EVALUATOR_SYSTEM, prompt)
        if not evaluation:
            return {"error": "Groq evaluation failed"}

        # Store lessons
        lessons = evaluation.get("lessons", [])
        for lesson in lessons[:5]:
            self.memory.add_lesson(lesson, source="weekly_evaluation")

        # Log parameter suggestions
        params = evaluation.get("parameter_suggestions", {})
        if params:
            logger.info(f"EVALUATOR parameter suggestions: {json.dumps(params)}")

        self._last_evaluation = datetime.now(timezone.utc).isoformat()
        self._evaluation_count += 1

        logger.info(
            f"Weekly evaluation complete: {len(lessons)} lessons extracted | "
            f"Assessment: {evaluation.get('overall_assessment', 'N/A')}"
        )

        return evaluation

    async def evaluate_single_trade(self, trade: dict) -> dict | None:
        """Evaluate a single losing trade immediately after it closes."""
        pnl = float(trade.get("pnl", 0))
        if pnl >= 0:
            return None  # Only evaluate losers

        prompt = self._build_trade_review_prompt(trade)
        review = await self._call_groq(TRADE_REVIEW_SYSTEM, prompt)

        if review and review.get("lesson"):
            severity = review.get("severity", "minor")
            if severity in ("major", "critical"):
                self.memory.add_lesson(review["lesson"], source=f"trade_review_{severity}")
                logger.info(f"Trade lesson ({severity}): {review['lesson']}")

        return review

    def _get_recent_trades(self, days: int = 7) -> list[dict]:
        """Fetch recent trades from memory DB."""
        import sqlite3
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = sqlite3.connect("data/trade_memory.db")
        c = conn.cursor()
        c.execute("""SELECT symbol, direction, pnl, pnl_pct, rsi_at_entry,
                            trend_at_entry, session, confidence, reasoning, exit_reason,
                            hour_utc, day_of_week, atr_at_entry
                     FROM closed_trades WHERE timestamp > ?
                     ORDER BY timestamp""", (cutoff,))
        columns = ["symbol", "direction", "pnl", "pnl_pct", "rsi", "trend",
                    "session", "confidence", "reasoning", "exit_reason",
                    "hour_utc", "day_of_week", "atr"]
        rows = c.fetchall()
        conn.close()
        return [dict(zip(columns, r)) for r in rows]

    def _build_evaluation_prompt(self, trades: list[dict]) -> str:
        """Build the weekly evaluation prompt."""
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        summary = f"""WEEKLY TRADING REVIEW ({len(trades)} trades)

SUMMARY:
- Wins: {len(wins)} | Losses: {len(losses)}
- Win Rate: {len(wins)/len(trades)*100:.1f}%
- Total P/L: ${sum(t['pnl'] for t in trades):.2f}
- Avg Winner: ${sum(t['pnl'] for t in wins)/len(wins):.2f if wins else 0}
- Avg Loser: ${sum(t['pnl'] for t in losses)/len(losses):.2f if losses else 0}

INDIVIDUAL TRADES:
"""
        for i, t in enumerate(trades, 1):
            result = "WIN" if t["pnl"] > 0 else "LOSS"
            summary += (
                f"{i}. {result} | {t['direction']} {t['symbol']} | "
                f"P/L: ${t['pnl']:.2f} ({t['pnl_pct']:.1f}%) | "
                f"RSI: {t['rsi']:.0f} | Trend: {t['trend']} | "
                f"Session: {t['session']} | Conf: {t['confidence']:.0%} | "
                f"Exit: {t['exit_reason']}\n"
            )

        return summary

    def _build_trade_review_prompt(self, trade: dict) -> str:
        """Build prompt for single trade review."""
        return f"""LOSING TRADE REVIEW:

Symbol: {trade.get('symbol')}
Direction: {trade.get('direction')}
P/L: ${trade.get('pnl', 0):.2f}
Entry RSI: {trade.get('rsi', 'N/A')}
Trend at entry: {trade.get('trend', 'N/A')}
Session: {trade.get('session', 'N/A')}
Confidence: {trade.get('confidence', 0):.0%}
Original reasoning: {trade.get('reasoning', 'N/A')}
Exit reason: {trade.get('exit_reason', 'N/A')}

What pattern or mistake caused this loss?"""

    async def _call_groq(self, system: str, prompt: str) -> dict | None:
        """Call Groq API for evaluation."""
        if not config.has_groq:
            logger.warning("Groq not configured — cannot evaluate")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {config.groq_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": config.groq_model if hasattr(config, 'groq_model') and config.groq_model else "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 800,
                    "response_format": {"type": "json_object"},
                }

                async with session.post(GROQ_API_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Groq eval error {resp.status}: {body[:200]}")
                        return None

                    data = await resp.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    return json.loads(text)

        except Exception as e:
            logger.error(f"Groq evaluation failed: {e}")
            return None

    def get_status(self) -> dict:
        return {
            "last_evaluation": self._last_evaluation,
            "evaluation_count": self._evaluation_count,
            "total_lessons": len(self.memory.lessons),
        }
