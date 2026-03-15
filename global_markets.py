"""Global Markets Module — Contra-horario para Chile.

Detecta qué bolsas mundiales están abiertas en la hora nocturna chilena
y proporciona instrumentos relevantes accesibles via Alpaca (extended hours + crypto).

Zona horaria Chile: UTC-4 (invierno CLT) / UTC-3 (verano CLST)
"""

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("phantom.global_markets")

# ═══════════════════════════════════════════════════════════════════════════════
# MARKET SCHEDULES (UTC times)
# ═══════════════════════════════════════════════════════════════════════════════

GLOBAL_MARKETS = {
    "ASX": {
        "name": "Australian Securities Exchange",
        "country": "🇦🇺 Australia",
        "open_utc": (23, 30),   # 23:30 UTC (prev day) = 10:00 AEDT
        "close_utc": (6, 0),    # 06:00 UTC = 17:00 AEDT
        "crosses_midnight": True,
        "instruments": ["EWA", "BHP", "RIO"],  # Australia ETF, via ADRs
        "currency": "AUD",
        "etf_proxy": "EWA",      # iShares MSCI Australia ETF
        "description": "Minería, commodities, bancos australianos",
    },
    "TSE": {
        "name": "Tokyo Stock Exchange",
        "country": "🇯🇵 Japan",
        "open_utc": (0, 0),     # 00:00 UTC = 09:00 JST
        "close_utc": (6, 30),   # 06:30 UTC = 15:30 JST (con break 2:30-3:30 UTC)
        "crosses_midnight": False,
        "instruments": ["EWJ", "SONY", "TM"],  # Japan ETF + ADRs
        "currency": "JPY",
        "etf_proxy": "EWJ",      # iShares MSCI Japan ETF
        "description": "Tech, automotriz, electrónica japonesa",
    },
    "HKEX": {
        "name": "Hong Kong Stock Exchange",
        "country": "🇭🇰 Hong Kong",
        "open_utc": (1, 30),    # 01:30 UTC = 09:30 HKT
        "close_utc": (8, 0),    # 08:00 UTC = 16:00 HKT
        "crosses_midnight": False,
        "instruments": ["FXI", "BABA", "PDD"],  # HK/China ETF + ADRs
        "currency": "HKD",
        "etf_proxy": "FXI",      # iShares China Large-Cap ETF
        "description": "Tech china, financiero HK, e-commerce Asia",
    },
    "SSE": {
        "name": "Shanghai Stock Exchange",
        "country": "🇨🇳 China",
        "open_utc": (1, 30),    # 01:30 UTC = 09:30 CST
        "close_utc": (7, 0),    # 07:00 UTC = 15:00 CST
        "crosses_midnight": False,
        "instruments": ["MCHI", "KWEB", "BABA"],  # China ETFs + ADRs
        "currency": "CNY",
        "etf_proxy": "MCHI",     # iShares MSCI China ETF
        "description": "Manufactura, fintech, EV chino, semiconductores",
    },
    "KOSPI": {
        "name": "Korea Stock Exchange",
        "country": "🇰🇷 South Korea",
        "open_utc": (0, 0),     # 00:00 UTC = 09:00 KST
        "close_utc": (6, 30),   # 06:30 UTC = 15:30 KST
        "crosses_midnight": False,
        "instruments": ["EWY", "Samsung-ADR"],  # Korea ETF
        "currency": "KRW",
        "etf_proxy": "EWY",      # iShares MSCI South Korea ETF
        "description": "Semiconductores (Samsung/SK Hynix), K-chips, displays",
    },
    "SGX": {
        "name": "Singapore Exchange",
        "country": "🇸🇬 Singapore",
        "open_utc": (1, 0),     # 01:00 UTC = 09:00 SGT
        "close_utc": (9, 0),    # 09:00 UTC = 17:00 SGT
        "crosses_midnight": False,
        "instruments": ["EWS"],  # Singapore ETF
        "currency": "SGD",
        "etf_proxy": "EWS",      # iShares MSCI Singapore ETF
        "description": "Hub financiero Asia, REITs, shipping",
    },
    "INDIA_NSE": {
        "name": "National Stock Exchange (India)",
        "country": "🇮🇳 India",
        "open_utc": (3, 45),    # 03:45 UTC = 09:15 IST
        "close_utc": (10, 0),   # 10:00 UTC = 15:30 IST
        "crosses_midnight": False,
        "instruments": ["INDA", "INDY"],  # India ETFs
        "currency": "INR",
        "etf_proxy": "INDA",     # iShares MSCI India ETF
        "description": "IT, farmacéutica, banca india — economía de mayor crecimiento",
    },
    "LSE": {
        "name": "London Stock Exchange",
        "country": "🇬🇧 United Kingdom",
        "open_utc": (8, 0),     # 08:00 UTC = 09:00 BST/GMT
        "close_utc": (16, 30),  # 16:30 UTC
        "crosses_midnight": False,
        "instruments": ["EWU", "NVO", "SAP"],  # UK ETF + European ADRs
        "currency": "GBP",
        "etf_proxy": "EWU",      # iShares MSCI United Kingdom ETF
        "description": "Finanzas, energía, farmacéutica europea",
    },
    "XETRA": {
        "name": "Deutsche Börse (Frankfurt)",
        "country": "🇩🇪 Germany",
        "open_utc": (7, 0),     # 07:00 UTC = 09:00 CET
        "close_utc": (15, 30),  # 15:30 UTC
        "crosses_midnight": False,
        "instruments": ["EWG", "SAP"],  # Germany ETF + SAP ADR
        "currency": "EUR",
        "etf_proxy": "EWG",      # iShares MSCI Germany ETF
        "description": "Automóvil, industria, química alemana",
    },
    "CRYPTO_24_7": {
        "name": "Crypto Markets (24/7)",
        "country": "🌐 Global",
        "open_utc": (0, 0),
        "close_utc": (23, 59),
        "crosses_midnight": True,
        "instruments": ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "XRP/USD", "AVAX/USD", "LINK/USD"],
        "currency": "USD",
        "etf_proxy": None,
        "description": "Cripto opera 24/7 — ideal para operación nocturna",
    },
}

# Instrumentos que Alpaca puede operar en EXTENDED HOURS (pre/after market)
# Estos son ETFs internacionales disponibles en NYSE/NASDAQ
EXTENDED_HOURS_INSTRUMENTS = {
    # Asia ETFs (accesibles via pre-market US)
    "EWJ": "iShares MSCI Japan ETF",
    "EWA": "iShares MSCI Australia ETF",
    "EWY": "iShares MSCI South Korea ETF",
    "EWS": "iShares MSCI Singapore ETF",
    "INDA": "iShares MSCI India ETF",
    "FXI": "iShares China Large-Cap ETF",
    "MCHI": "iShares MSCI China ETF",
    "KWEB": "KraneShares CSI China Internet ETF",

    # Europe ETFs
    "EWU": "iShares MSCI United Kingdom ETF",
    "EWG": "iShares MSCI Germany ETF",
    "EWQ": "iShares MSCI France ETF",

    # Emerging Markets
    "EEM": "iShares MSCI Emerging Markets ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF",

    # Global
    "ACWI": "iShares MSCI ACWI ETF",

    # ADRs líquidos (ya en el portfolio)
    "TSM": "Taiwan Semiconductor (TSE listed, ADR)",
    "SONY": "Sony Group (TSE listed, ADR)",
    "NVO": "Novo Nordisk (Copenhagen, ADR)",
    "BABA": "Alibaba (NYSE ADR, HK underlying)",
    "PDD": "Temu/Pinduoduo (NASDAQ, China underlying)",
    "MELI": "MercadoLibre (LatAm, NASDAQ)",
}

# Horario Chile (UTC-4 invierno CLT, UTC-3 verano CLST)
CHILE_UTC_OFFSET_WINTER = -4   # Claro de la noche en invierno
CHILE_UTC_OFFSET_SUMMER = -3   # Hora de verano (primavera/verano austral)


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET STATUS DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketWindow:
    market_id: str
    name: str
    country: str
    is_open: bool
    opens_in_minutes: Optional[int]  # None if already open or closed for today
    closes_in_minutes: Optional[int]  # None if closed
    instruments: list
    etf_proxy: Optional[str]
    description: str


class GlobalMarketDetector:
    """Detects which global markets are currently open and relevant for night trading from Chile."""

    def __init__(self):
        self.chile_tz_offset = CHILE_UTC_OFFSET_WINTER  # Default invierno

    def get_chile_time(self) -> datetime:
        """Get current time in Chile (auto-detects summer/winter)."""
        now_utc = datetime.now(timezone.utc)

        # Auto-detect DST for Chile (aprox: Nov-Mar es verano CLST = UTC-3)
        month = now_utc.month
        if month in [11, 12, 1, 2, 3]:  # Verano austral (Chile)
            offset = CHILE_UTC_OFFSET_SUMMER
        else:
            offset = CHILE_UTC_OFFSET_WINTER

        self.chile_tz_offset = offset
        chile_time = now_utc + timedelta(hours=offset)
        return chile_time

    def is_market_open(self, market_config: dict) -> bool:
        """Check if a market is currently open based on UTC time."""
        now_utc = datetime.now(timezone.utc)
        now_h, now_m = now_utc.hour, now_utc.minute
        now_minutes = now_h * 60 + now_m

        open_h, open_m = market_config["open_utc"]
        close_h, close_m = market_config["close_utc"]

        open_minutes = open_h * 60 + open_m
        close_minutes = close_h * 60 + close_m

        if market_config.get("crosses_midnight", False):
            # Market crosses midnight: open after open_minutes OR before close_minutes
            if market_config["market_id"] == "CRYPTO_24_7":
                return True  # Always open
            return now_minutes >= open_minutes or now_minutes < close_minutes
        else:
            return open_minutes <= now_minutes < close_minutes

    def get_open_markets(self) -> list[MarketWindow]:
        """Get list of currently open global markets."""
        open_markets = []
        now_utc = datetime.now(timezone.utc)
        now_minutes = now_utc.hour * 60 + now_utc.minute

        for market_id, cfg in GLOBAL_MARKETS.items():
            cfg["market_id"] = market_id
            is_open = self.is_market_open(cfg)

            open_h, open_m = cfg["open_utc"]
            close_h, close_m = cfg["close_utc"]
            open_minutes = open_h * 60 + open_m
            close_minutes = close_h * 60 + close_m

            # Calculate time to open/close
            opens_in = None
            closes_in = None

            if is_open:
                if close_minutes > now_minutes:
                    closes_in = close_minutes - now_minutes
                else:
                    # Closes next day
                    closes_in = (24 * 60 - now_minutes) + close_minutes
            else:
                if open_minutes > now_minutes:
                    opens_in = open_minutes - now_minutes
                else:
                    # Opens tomorrow
                    opens_in = (24 * 60 - now_minutes) + open_minutes

            open_markets.append(MarketWindow(
                market_id=market_id,
                name=cfg["name"],
                country=cfg["country"],
                is_open=is_open,
                opens_in_minutes=opens_in,
                closes_in_minutes=closes_in,
                instruments=cfg["instruments"],
                etf_proxy=cfg.get("etf_proxy"),
                description=cfg["description"],
            ))

        # Sort: open markets first, then by opens_in ascending
        open_markets.sort(key=lambda m: (0 if m.is_open else 1, m.opens_in_minutes or 9999))
        return open_markets

    def get_night_trading_instruments(self) -> dict:
        """Get instruments available for night trading from Chile right now."""
        chile_time = self.get_chile_time()
        chile_hour = chile_time.hour

        # Define "night" in Chile: 20:00 - 08:00 CLT
        is_night_in_chile = chile_hour >= 20 or chile_hour < 8

        open_markets = self.get_open_markets()
        active_markets = [m for m in open_markets if m.is_open]

        # Collect all tradeable instruments
        crypto_instruments = []
        stock_instruments = []  # Extended hours via Alpaca
        etf_proxies = []

        for market in active_markets:
            for instrument in market.instruments:
                if "/" in instrument:
                    crypto_instruments.append(instrument)
                elif instrument in EXTENDED_HOURS_INSTRUMENTS:
                    stock_instruments.append(instrument)
                    if market.etf_proxy and market.etf_proxy not in etf_proxies:
                        etf_proxies.append(market.etf_proxy)

        return {
            "is_night_in_chile": is_night_in_chile,
            "chile_time": chile_time.strftime("%Y-%m-%d %H:%M CLT"),
            "chile_hour": chile_hour,
            "active_markets_count": len(active_markets),
            "active_markets": [m.country for m in active_markets],
            "crypto_instruments": list(set(crypto_instruments)),
            "extended_hours_instruments": list(set(stock_instruments)),
            "etf_proxies": etf_proxies,
            "all_tradeable": list(set(crypto_instruments + stock_instruments)),
        }

    def get_market_context_for_symbol(self, symbol: str) -> dict:
        """Get global market context relevant to a specific symbol."""
        context = {
            "relevant_markets": [],
            "is_primary_market_open": False,
            "trading_session": "UNKNOWN",
            "notes": "",
        }

        symbol_upper = symbol.upper().replace("/USD", "").replace("/USDT", "")

        # Check which markets are relevant
        for market_id, cfg in GLOBAL_MARKETS.items():
            if symbol in cfg["instruments"] or symbol_upper in [i.replace("/USD", "") for i in cfg["instruments"]]:
                cfg_copy = dict(cfg)
                cfg_copy["market_id"] = market_id
                is_open = self.is_market_open(cfg_copy)
                context["relevant_markets"].append({
                    "market": cfg["name"],
                    "country": cfg["country"],
                    "is_open": is_open,
                })
                if is_open:
                    context["is_primary_market_open"] = True

        # Determine trading session
        now_utc = datetime.now(timezone.utc)
        h = now_utc.hour

        if 0 <= h < 7:
            context["trading_session"] = "ASIA_SESSION"
        elif 7 <= h < 12:
            context["trading_session"] = "ASIA_EUROPE_OVERLAP"
        elif 12 <= h < 14:
            context["trading_session"] = "EUROPE_SESSION"
        elif 14 <= h < 16:
            context["trading_session"] = "EUROPE_US_OVERLAP"
        elif 16 <= h < 21:
            context["trading_session"] = "US_SESSION"
        else:
            context["trading_session"] = "ASIA_OPEN"

        return context

    def should_use_extended_hours(self, symbol: str) -> bool:
        """Determine if we should use extended hours trading for this symbol."""
        # Crypto: always yes (24/7)
        if "/" in symbol:
            return True

        # For stocks: use extended hours if the regular market is closed but Asian/European market is active
        now_utc = datetime.now(timezone.utc)
        h = now_utc.hour

        # Regular US market: 14:30 - 21:00 UTC (9:30 AM - 4:00 PM ET)
        us_regular = 14 <= h < 21

        # If US regular hours → no need for extended hours
        if us_regular:
            return False

        # Check if symbol is an international ETF/ADR worth trading in extended hours
        if symbol in EXTENDED_HOURS_INSTRUMENTS:
            # Extended hours: 4:00 AM - 9:30 AM ET (09:00 - 14:30 UTC)
            # and 4:00 PM - 8:00 PM ET (21:00 - 01:00 UTC)
            extended = (9 <= h < 14) or (21 <= h < 24) or (0 <= h < 1)
            return extended

        return False

    def get_status(self) -> dict:
        """Get full status for dashboard display."""
        open_markets = self.get_open_markets()
        night_info = self.get_night_trading_instruments()

        open_list = [m for m in open_markets if m.is_open]
        upcoming_list = [m for m in open_markets if not m.is_open and (m.opens_in_minutes or 9999) < 120]

        return {
            "chile_time": night_info["chile_time"],
            "chile_hour": night_info["chile_hour"],
            "is_night_in_chile": night_info["is_night_in_chile"],
            "open_markets": [
                {
                    "id": m.market_id,
                    "name": m.name,
                    "country": m.country,
                    "closes_in": m.closes_in_minutes,
                    "instruments": m.instruments[:3],
                    "description": m.description,
                }
                for m in open_list
            ],
            "upcoming_markets": [
                {
                    "id": m.market_id,
                    "name": m.name,
                    "country": m.country,
                    "opens_in": m.opens_in_minutes,
                }
                for m in upcoming_list
            ],
            "tradeable_now": night_info["all_tradeable"],
            "crypto_instruments": night_info["crypto_instruments"],
            "extended_hours_instruments": night_info["extended_hours_instruments"],
            "all_markets": open_markets,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NIGHT TRADING WATCHLIST — Instrumentos extra para horario nocturno Chile
# ═══════════════════════════════════════════════════════════════════════════════

NIGHT_WATCHLIST = {
    # Asia ETFs (core para horario nocturno)
    "stocks": [
        "EWJ",   # Japan
        "EWY",   # South Korea
        "MCHI",  # China MSCI
        "KWEB",  # China Internet (Alibaba, Tencent, JD via proxy)
        "FXI",   # China Large Cap (Baidu, NetEase)
        "EWA",   # Australia (minería, bancos)
        "INDA",  # India (el nuevo gigante)
        "EWS",   # Singapore (hub financiero Asia)
        "EWG",   # Germany (automóvil, industria)
        "EWU",   # UK (finanzas, energía)
    ],
    # Crypto premium para operación nocturna (mercados Asia son muy activos)
    "crypto_night": [
        "BTC/USD",
        "ETH/USD",
        "SOL/USD",
        "BNB/USD",     # Binance token — muy activo en Asia
        "XRP/USD",     # Ripple — adoptado por bancos japoneses
        "AVAX/USD",
        "DOGE/USD",    # Alta actividad en Asia
        "LINK/USD",
    ],
}


# Singleton
_detector_instance: Optional[GlobalMarketDetector] = None

def get_global_market_detector() -> GlobalMarketDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = GlobalMarketDetector()
    return _detector_instance
