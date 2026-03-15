"""Configuration for Phantom Trader v3 — FundedNext Free Trial Edition."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════
# FUNDEDNEXT FREE TRIAL RULES — DO NOT MODIFY
# ═══════════════════════════════════════════════════
@dataclass(frozen=True)
class FundedNextRules:
    """Immutable FundedNext Free Trial constraints."""
    PROFIT_TARGET_PCT: float = 0.05          # 5% profit target
    DAILY_LOSS_LIMIT_PCT: float = 0.05       # 5% daily loss limit
    MAX_LOSS_LIMIT_PCT: float = 0.10         # 10% max overall loss
    TIME_LIMIT_DAYS: int = 14                # 14 calendar days
    MIN_TRADING_DAYS: int = 3                # Minimum 3 trading days
    MAX_OPEN_POSITIONS: int = 30             # Max 30 simultaneous positions
    LEVERAGE_FOREX: int = 100                # 1:100 for forex
    LEVERAGE_COMMODITIES: int = 40           # 1:40 for commodities
    LEVERAGE_INDICES: int = 20               # 1:20 for indices
    PLATFORM: str = "MT5"
    ACCOUNT_TYPE: str = "swap"
    EAS_ALLOWED: bool = False                # EAs are NOT allowed
    WEEKEND_HOLDING: bool = True             # Weekend holding OK


FN_RULES = FundedNextRules()


@dataclass
class Config:
    """Bot configuration."""
    # MT5 Connection
    mt5_path: str = ""
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    # Trading
    symbols: list = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"
    ])
    timeframe: str = "H1"           # 1-hour candles
    check_interval: int = 300       # 5 minutes between cycles

    # Risk Management (conservative for prop firm)
    risk_per_trade_pct: float = 0.01    # 1% risk per trade
    max_daily_trades: int = 10          # Max trades per day
    max_correlated_pairs: int = 3       # Max correlated positions
    sl_atr_multiplier: float = 1.5      # SL = 1.5x ATR
    tp_rr_ratio: float = 2.0            # TP = 2x risk (2:1 R:R)

    # Execution mode
    manual_mode: bool = True        # Default: manual confirm

    # Safety margins (buffer before FN limits)
    daily_loss_buffer: float = 0.005    # Stop at 4.5% (0.5% buffer)
    max_loss_buffer: float = 0.01       # Stop at 9% (1% buffer)

    # Paths
    trades_file: str = "data/trades.json"

    # News
    newsapi_key: str = ""

    def __post_init__(self):
        self.mt5_path = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
        self.mt5_login = int(os.getenv("MT5_LOGIN", "0"))
        self.mt5_password = os.getenv("MT5_PASSWORD", "")
        self.mt5_server = os.getenv("MT5_SERVER", "")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.claude_model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

        symbols_env = os.getenv("SYMBOLS", "")
        if symbols_env:
            self.symbols = [s.strip() for s in symbols_env.split(",")]

        self.timeframe = os.getenv("TIMEFRAME", "H1")
        self.check_interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
        self.risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
        self.manual_mode = os.getenv("MANUAL_MODE", "true").lower() == "true"
        self.newsapi_key = os.getenv("NEWSAPI_KEY", "")

    @property
    def effective_daily_loss_limit(self) -> float:
        """Daily loss limit with safety buffer."""
        return FN_RULES.DAILY_LOSS_LIMIT_PCT - self.daily_loss_buffer

    @property
    def effective_max_loss_limit(self) -> float:
        """Max loss limit with safety buffer."""
        return FN_RULES.MAX_LOSS_LIMIT_PCT - self.max_loss_buffer

    def validate(self) -> list[str]:
        errors = []
        if not self.mt5_login:
            errors.append("MT5_LOGIN not set")
        if not self.mt5_password:
            errors.append("MT5_PASSWORD not set")
        if not self.mt5_server:
            errors.append("MT5_SERVER not set")
        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY not set")
        if self.risk_per_trade_pct > 0.02:
            errors.append("Risk per trade > 2% is too aggressive for prop firm")
        return errors

    def get_leverage(self, symbol: str) -> int:
        """Return appropriate leverage based on instrument type."""
        symbol = symbol.upper()
        # Indices
        indices = ["US30", "US500", "NAS100", "UK100", "GER40", "JPN225",
                   "AUS200", "FRA40", "ESP35"]
        for idx in indices:
            if idx in symbol:
                return FN_RULES.LEVERAGE_INDICES

        # Commodities
        commodities = ["XAUUSD", "XAGUSD", "XBRUSD", "XTIUSD", "XNGUSD",
                       "GOLD", "SILVER", "OIL"]
        for comm in commodities:
            if comm in symbol:
                return FN_RULES.LEVERAGE_COMMODITIES

        # Default: Forex
        return FN_RULES.LEVERAGE_FOREX


config = Config()
