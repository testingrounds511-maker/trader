"""Configuration for Phantom Trader — FundedNext Free Trial + Full Intelligence Stack."""

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
    """Bot configuration — loads from .env with sensible defaults."""

    # ── MT5 Connection ──
    mt5_path: str = ""
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""

    # ── AI Engines ──
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"
    groq_api_key: str = ""

    # ── Trading ──
    symbols: list = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD"
    ])
    # Legacy fields for wolf_engine compatibility
    crypto_pairs: list = field(default_factory=list)
    stock_symbols: list = field(default_factory=list)

    timeframe: str = "H1"
    check_interval: int = 5        # minutes between cycles
    initial_capital_usd: float = 6000.0

    # ── Risk Management (conservative for prop firm) ──
    risk_profile: str = "conservative"
    risk_per_trade_pct: float = 0.01    # 1% risk per trade
    max_position_pct: float = 0.25      # max 25% in one position
    max_daily_trades: int = 10
    max_correlated_pairs: int = 3
    sl_atr_multiplier: float = 1.5      # SL = 1.5x ATR
    tp_rr_ratio: float = 2.0            # TP = 2x risk (2:1 R:R)
    take_profit_pct: float = 0.03       # 3% TP per trade (legacy)
    stop_loss_pct: float = 0.015        # 1.5% SL per trade (legacy)
    max_slippage_tolerance_pct: float = 0.002  # 0.2% max slippage

    # ── Capital Base Mode ──
    # "broker" = use raw broker equity
    # "cap_to_initial" = scale down to INITIAL_CAPITAL_USD for sizing
    capital_base_mode: str = "broker"

    # ── Execution ──
    manual_mode: bool = True        # Default: manual confirm (safe for FN)
    is_paper: bool = True           # FundedNext free trial IS paper trading

    # ── Safety margins (buffer before FN limits) ──
    daily_loss_buffer: float = 0.005    # Stop at 4.5% (0.5% buffer)
    max_loss_buffer: float = 0.01       # Stop at 9% (1% buffer)

    # ── Intelligence APIs (all optional) ──
    newsapi_key: str = ""
    quiver_api_key: str = ""
    finnhub_api_key: str = ""
    twitter_bearer_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "phantom-trader/3.6"

    # ── News ──
    news_fast_lane: bool = True     # Urgent news triggers immediate analysis

    # ── Paths ──
    trades_file: str = "data/trades.json"

    def __post_init__(self):
        # MT5
        self.mt5_path = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
        self.mt5_login = int(os.getenv("MT5_LOGIN", "0"))
        self.mt5_password = os.getenv("MT5_PASSWORD", "")
        self.mt5_server = os.getenv("MT5_SERVER", "")

        # AI
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.claude_model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.groq_model_fallbacks = [
            s.strip() for s in os.getenv("GROQ_MODEL_FALLBACKS", "llama-3.1-8b-instant").split(",") if s.strip()
        ]

        # Trading
        symbols_env = os.getenv("SYMBOLS", "")
        if symbols_env:
            self.symbols = [s.strip() for s in symbols_env.split(",")]

        self.timeframe = os.getenv("TIMEFRAME", "H1")
        self.check_interval = int(os.getenv("CHECK_INTERVAL_MINUTES", os.getenv("CHECK_INTERVAL_SECONDS", "300")))
        # Normalize: if value > 60, assume seconds
        if self.check_interval > 60:
            self.check_interval = self.check_interval // 60

        self.risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
        self.manual_mode = os.getenv("MANUAL_MODE", "true").lower() == "true"
        self.initial_capital_usd = float(os.getenv("INITIAL_CAPITAL_USD", "6000"))
        self.capital_base_mode = os.getenv("CAPITAL_BASE_MODE", "broker")

        # Intelligence
        self.newsapi_key = os.getenv("NEWSAPI_KEY", "")
        self.quiver_api_key = os.getenv("QUIVER_API_KEY", "")
        self.finnhub_api_key = os.getenv("FINNHUB_API_KEY", "")
        self.twitter_bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")
        self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")

        # Populate legacy fields for wolf_engine compatibility
        # For FundedNext forex, everything goes into symbols (no crypto/stock split)
        self.crypto_pairs = []
        self.stock_symbols = list(self.symbols)

    # ── Feature flags ──
    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_quiver(self) -> bool:
        return bool(self.quiver_api_key)

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def has_twitter(self) -> bool:
        return bool(self.twitter_bearer_token)

    @property
    def has_reddit(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

    @property
    def has_newsapi(self) -> bool:
        return bool(self.newsapi_key)

    # ── FN Safety ──
    @property
    def effective_daily_loss_limit(self) -> float:
        return FN_RULES.DAILY_LOSS_LIMIT_PCT - self.daily_loss_buffer

    @property
    def effective_max_loss_limit(self) -> float:
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
        indices = ["US30", "US500", "NAS100", "UK100", "GER40", "JPN225",
                   "AUS200", "FRA40", "ESP35"]
        for idx in indices:
            if idx in symbol:
                return FN_RULES.LEVERAGE_INDICES

        commodities = ["XAUUSD", "XAGUSD", "XBRUSD", "XTIUSD", "XNGUSD",
                       "GOLD", "SILVER", "OIL"]
        for comm in commodities:
            if comm in symbol:
                return FN_RULES.LEVERAGE_COMMODITIES

        return FN_RULES.LEVERAGE_FOREX


config = Config()
