"""Technical analysis indicators for forex trading."""

import logging

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange

logger = logging.getLogger("phantom.technical")


class TechnicalAnalysis:
    """Compute technical indicators on OHLCV data."""

    def analyze(self, df: pd.DataFrame) -> dict:
        """Run full technical analysis and return indicator summary."""
        if df.empty or len(df) < 50:
            return {"error": "Insufficient data (need 50+ candles)"}

        try:
            close = df["close"]
            high = df["high"]
            low = df["low"]

            # Trend indicators
            ema_20 = EMAIndicator(close, window=20).ema_indicator()
            ema_50 = EMAIndicator(close, window=50).ema_indicator()
            sma_200 = SMAIndicator(close, window=200).sma_indicator() if len(df) >= 200 else pd.Series([np.nan])

            macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
            adx = ADXIndicator(high, low, close, window=14)

            # Momentum
            rsi = RSIIndicator(close, window=14).rsi()

            # Volatility
            bb = BollingerBands(close, window=20, window_dev=2)
            atr = AverageTrueRange(high, low, close, window=14)

            current_close = close.iloc[-1]
            current_ema20 = ema_20.iloc[-1]
            current_ema50 = ema_50.iloc[-1]
            current_rsi = rsi.iloc[-1]
            current_macd = macd.macd().iloc[-1]
            current_macd_signal = macd.macd_signal().iloc[-1]
            current_macd_hist = macd.macd_diff().iloc[-1]
            current_adx = adx.adx().iloc[-1]
            current_atr = atr.average_true_range().iloc[-1]
            current_bb_upper = bb.bollinger_hband().iloc[-1]
            current_bb_lower = bb.bollinger_lband().iloc[-1]
            current_bb_mid = bb.bollinger_mavg().iloc[-1]

            # Signals
            trend = "BULLISH" if current_ema20 > current_ema50 else "BEARISH"
            rsi_signal = "OVERBOUGHT" if current_rsi > 70 else "OVERSOLD" if current_rsi < 30 else "NEUTRAL"
            macd_signal = "BULLISH" if current_macd > current_macd_signal else "BEARISH"
            bb_position = "ABOVE" if current_close > current_bb_upper else "BELOW" if current_close < current_bb_lower else "INSIDE"
            trend_strength = "STRONG" if current_adx > 25 else "WEAK"

            # Support/Resistance (simple pivot points)
            recent = df.tail(20)
            support = recent["low"].min()
            resistance = recent["high"].max()

            return {
                "current_price": round(current_close, 5),
                "ema_20": round(current_ema20, 5),
                "ema_50": round(current_ema50, 5),
                "sma_200": round(sma_200.iloc[-1], 5) if not np.isnan(sma_200.iloc[-1]) else None,
                "rsi": round(current_rsi, 2),
                "rsi_signal": rsi_signal,
                "macd": round(current_macd, 6),
                "macd_signal": round(current_macd_signal, 6),
                "macd_histogram": round(current_macd_hist, 6),
                "macd_direction": macd_signal,
                "adx": round(current_adx, 2),
                "trend_strength": trend_strength,
                "trend": trend,
                "bb_upper": round(current_bb_upper, 5),
                "bb_lower": round(current_bb_lower, 5),
                "bb_mid": round(current_bb_mid, 5),
                "bb_position": bb_position,
                "atr": round(current_atr, 5),
                "support": round(support, 5),
                "resistance": round(resistance, 5),
                "candles_analyzed": len(df),
            }
        except Exception as e:
            logger.error(f"TA error: {e}")
            return {"error": str(e)}

    def calculate_lot_size(
        self,
        account_balance: float,
        risk_pct: float,
        sl_distance_pips: float,
        pip_value: float = 10.0,  # Standard lot pip value for most forex pairs
    ) -> float:
        """Calculate position size based on risk management.

        For forex (standard lots):
        - 1 lot = 100,000 units, pip value ≈ $10 for XXX/USD pairs
        - Mini lot (0.1) = 10,000 units, pip value ≈ $1
        """
        if sl_distance_pips <= 0:
            return 0.01  # Minimum

        risk_amount = account_balance * risk_pct
        lot_size = risk_amount / (sl_distance_pips * pip_value)

        # Clamp to FundedNext limits
        lot_size = max(0.01, min(lot_size, 100.0))  # Min 0.01, max 100 lots
        lot_size = round(lot_size, 2)  # Round to 2 decimal places

        return lot_size

    def pips_from_price(self, price_diff: float, digits: int = 5) -> float:
        """Convert price difference to pips."""
        if digits == 5 or digits == 3:  # Standard forex or JPY pairs
            return abs(price_diff) * (10 ** (digits - 1))
        return abs(price_diff) * (10 ** digits)
