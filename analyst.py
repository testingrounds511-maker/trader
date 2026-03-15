"""Claude AI Analyst — Generates trading decisions using Anthropic API."""

import json
import logging
from datetime import datetime, timezone

from anthropic import Anthropic

from config import config, FN_RULES

logger = logging.getLogger("phantom.analyst")


SYSTEM_PROMPT = """You are a professional forex trading analyst for a prop firm challenge.
You analyze technical indicators and market context to make trading decisions.

CRITICAL RULES (FundedNext Free Trial):
- Profit target: 5% of initial balance
- Daily loss limit: 5% — if approaching, do NOT take risky trades
- Max overall loss: 10% — protect capital above all
- Max 30 open positions at once
- Conservative position sizing: 1% risk per trade max
- Risk/Reward minimum 1:2

You must respond ONLY with valid JSON in this exact format:
{
    "decision": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 to 1.0,
    "entry_price": float or null,
    "stop_loss": float,
    "take_profit": float,
    "lot_size_suggestion": float,
    "reasoning": "Brief 1-2 sentence explanation",
    "risk_level": "LOW" | "MEDIUM" | "HIGH"
}

If conditions are uncertain, ALWAYS choose HOLD. Capital preservation > profit.
Only take HIGH confidence trades (0.7+). This is a prop firm challenge, not gambling."""


class Analyst:
    """Uses Claude AI to analyze market conditions and suggest trades."""

    def __init__(self):
        self.client = Anthropic(api_key=config.anthropic_api_key)
        self.total_tokens = 0
        self.total_cost = 0.0

    def analyze(
        self,
        symbol: str,
        technical: dict,
        account_info: dict,
        risk_status: dict,
        news_sentiment: str = "neutral",
        open_positions: list = None,
    ) -> dict:
        """Get AI trading decision for a symbol."""
        try:
            prompt = self._build_prompt(
                symbol, technical, account_info, risk_status,
                news_sentiment, open_positions or []
            )

            response = self.client.messages.create(
                model=config.claude_model,
                max_tokens=500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Track costs
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            self.total_tokens += input_tokens + output_tokens
            # Haiku pricing: $0.25/1M input, $1.25/1M output
            self.total_cost += (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000

            # Parse JSON response
            text = response.content[0].text.strip()
            # Handle markdown code blocks
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            decision = json.loads(text)
            decision["symbol"] = symbol
            decision["timestamp"] = datetime.now(timezone.utc).isoformat()

            logger.info(
                f"{symbol}: {decision['decision']} "
                f"(confidence: {decision['confidence']}, risk: {decision['risk_level']})"
            )
            return decision

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response for {symbol}: {e}")
            return self._hold_decision(symbol, f"Parse error: {e}")
        except Exception as e:
            logger.error(f"Analyst error for {symbol}: {e}")
            return self._hold_decision(symbol, f"Error: {e}")

    def _build_prompt(
        self,
        symbol: str,
        technical: dict,
        account_info: dict,
        risk_status: dict,
        news_sentiment: str,
        open_positions: list,
    ) -> str:
        """Build the analysis prompt."""
        # Current positions in this symbol
        existing = [p for p in open_positions if p.get("symbol") == symbol]
        position_info = "No existing position"
        if existing:
            pos = existing[0]
            position_info = (
                f"EXISTING {pos['type']} position: {pos['volume']} lots @ {pos['price_open']}, "
                f"current P/L: ${pos['profit']:.2f}"
            )

        # Account context
        balance = account_info.get("balance", 0)
        equity = account_info.get("equity", 0)
        profit_pct = ((equity - risk_status.get("initial_balance", balance)) / 
                      risk_status.get("initial_balance", balance) * 100) if risk_status.get("initial_balance") else 0

        return f"""ANALYZE {symbol} FOR TRADING DECISION

== TECHNICAL INDICATORS ==
Price: {technical.get('current_price')}
Trend: {technical.get('trend')} (Strength: {technical.get('trend_strength')})
EMA 20: {technical.get('ema_20')} | EMA 50: {technical.get('ema_50')}
RSI: {technical.get('rsi')} ({technical.get('rsi_signal')})
MACD: {technical.get('macd')} | Signal: {technical.get('macd_signal')} | Hist: {technical.get('macd_histogram')} ({technical.get('macd_direction')})
ADX: {technical.get('adx')}
Bollinger: Upper={technical.get('bb_upper')} | Mid={technical.get('bb_mid')} | Lower={technical.get('bb_lower')} (Price {technical.get('bb_position')})
ATR: {technical.get('atr')}
Support: {technical.get('support')} | Resistance: {technical.get('resistance')}

== ACCOUNT STATUS ==
Balance: ${balance:.2f} | Equity: ${equity:.2f}
Profit vs Target: {profit_pct:.2f}% / 5.00% target
Days Remaining: {risk_status.get('days_remaining', '?')} of 14
Trading Days: {risk_status.get('trading_days_count', 0)} / {FN_RULES.MIN_TRADING_DAYS} minimum
Open Positions: {len(open_positions)} / {FN_RULES.MAX_OPEN_POSITIONS} max

== POSITION IN {symbol} ==
{position_info}

== NEWS SENTIMENT ==
{news_sentiment}

== RISK BUDGET ==
Max risk this trade: {config.risk_per_trade_pct * 100:.1f}% of balance (${balance * config.risk_per_trade_pct:.2f})
Use ATR for SL calculation: SL = {config.sl_atr_multiplier}x ATR, TP = {config.tp_rr_ratio}:1 R:R

Respond with JSON only."""

    def _hold_decision(self, symbol: str, reason: str) -> dict:
        return {
            "symbol": symbol,
            "decision": "HOLD",
            "confidence": 0.0,
            "entry_price": None,
            "stop_loss": 0,
            "take_profit": 0,
            "lot_size_suggestion": 0,
            "reasoning": reason,
            "risk_level": "HIGH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_cost_estimate(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.total_cost, 4),
        }
