"""Market data fetcher via MetaTrader 5 Python API."""

import logging
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd

from config import config

logger = logging.getLogger("phantom.market_data")

# Timeframe mapping
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
}


class MarketData:
    """Fetches market data from MT5."""

    def __init__(self):
        self._initialized = False

    def initialize(self) -> bool:
        """Connect to MT5 terminal."""
        if self._initialized:
            return True

        if not mt5.initialize(path=config.mt5_path):
            logger.error(f"MT5 init failed: {mt5.last_error()}")
            return False

        if config.mt5_login:
            authorized = mt5.login(
                login=config.mt5_login,
                password=config.mt5_password,
                server=config.mt5_server,
            )
            if not authorized:
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                return False

        self._initialized = True
        account = mt5.account_info()
        logger.info(f"MT5 connected: {account.server} | Balance: ${account.balance:.2f}")
        return True

    def shutdown(self):
        """Disconnect from MT5."""
        mt5.shutdown()
        self._initialized = False

    def get_account_info(self) -> dict:
        """Get current account info."""
        if not self.initialize():
            return {}
        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "profit": info.profit,
            "leverage": info.leverage,
            "currency": info.currency,
            "server": info.server,
            "login": info.login,
        }

    def get_candles(self, symbol: str, timeframe: str = None, count: int = 200) -> pd.DataFrame:
        """Fetch OHLCV candles."""
        if not self.initialize():
            return pd.DataFrame()

        tf = TF_MAP.get(timeframe or config.timeframe, mt5.TIMEFRAME_H1)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)

        if rates is None or len(rates) == 0:
            logger.warning(f"No data for {symbol}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={
            "time": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "tick_volume": "volume",
            "spread": "spread",
        }, inplace=True)
        return df

    def get_current_price(self, symbol: str) -> dict:
        """Get current bid/ask."""
        if not self.initialize():
            return {}
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {}
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
            "spread": round((tick.ask - tick.bid) * 10000, 1),  # in pips for forex
        }

    def get_symbol_info(self, symbol: str) -> dict:
        """Get symbol specifications."""
        if not self.initialize():
            return {}
        info = mt5.symbol_info(symbol)
        if info is None:
            return {}
        return {
            "name": info.name,
            "digits": info.digits,
            "point": info.point,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_mode": info.trade_mode,
            "spread": info.spread,
        }

    def get_open_positions(self) -> list[dict]:
        """Get all open positions."""
        if not self.initialize():
            return []
        positions = mt5.positions_get()
        if positions is None:
            return []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "time": datetime.fromtimestamp(p.time, tz=timezone.utc),
                "magic": p.magic,
                "comment": p.comment,
            }
            for p in positions
        ]

    def get_total_positions_count(self) -> int:
        """Count open positions."""
        positions = mt5.positions_get()
        return len(positions) if positions else 0
