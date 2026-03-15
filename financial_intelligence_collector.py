"""
TITANIUM VANGUARD - Financial Intelligence Collector
Phase 2D: Tracks financial indicators like CDS spreads, FX reserves,
interest rates, and stock indices for economic crisis early warning.
"""

import aiohttp
import asyncio
import json
from typing import List, Dict, Optional
from datetime import datetime, timezone, date, timedelta
from dataclasses import dataclass, asdict
from decimal import Decimal

from collectors.base import BaseCollector
from core.config import get_settings


@dataclass
class FinancialIndicator:
    """Represents a financial indicator data point"""
    country_iso: str
    indicator_type: str  # cds, fx_reserves, interest_rate, stock_index, currency, bond_yield
    indicator_name: str
    value: float
    unit: str  # basis_points, usd_millions, percent, index_points
    previous_value: Optional[float] = None
    pct_change: Optional[float] = None
    source: str = "FRED"
    source_series_id: Optional[str] = None
    source_url: Optional[str] = None
    indicator_date: date = None
    is_alert: bool = False
    alert_type: Optional[str] = None
    raw_data: Optional[dict] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result['indicator_date'] = self.indicator_date.isoformat() if self.indicator_date else None
        return result


# Financial data sources and series
FINANCIAL_SOURCES = {
    # FRED (Federal Reserve Economic Data) - Free API
    "fred": {
        "name": "Federal Reserve Economic Data",
        "base_url": "https://api.stlouisfed.org/fred/series/observations",
        "api_key_required": True,
        "format": "json"
    },
    # Alpha Vantage - Free tier available
    "alpha_vantage": {
        "name": "Alpha Vantage",
        "base_url": "https://www.alphavantage.co/query",
        "api_key_required": True,
        "format": "json"
    },
    # Yahoo Finance - No API key required
    "yahoo_finance": {
        "name": "Yahoo Finance",
        "base_url": "https://query1.finance.yahoo.com/v8/finance/chart/",
        "api_key_required": False,
        "format": "json"
    }
}

# Stock indices by country
STOCK_INDICES = {
    "USA": {"symbol": "^GSPC", "name": "S&P 500", "currency": "USD"},
    "GBR": {"symbol": "^FTSE", "name": "FTSE 100", "currency": "GBP"},
    "DEU": {"symbol": "^GDAXI", "name": "DAX", "currency": "EUR"},
    "FRA": {"symbol": "^FCHI", "name": "CAC 40", "currency": "EUR"},
    "JPN": {"symbol": "^N225", "name": "Nikkei 225", "currency": "JPY"},
    "CHN": {"symbol": "000001.SS", "name": "Shanghai Composite", "currency": "CNY"},
    "HKG": {"symbol": "^HSI", "name": "Hang Seng", "currency": "HKD"},
    "IND": {"symbol": "^BSESN", "name": "BSE SENSEX", "currency": "INR"},
    "BRA": {"symbol": "^BVSP", "name": "Bovespa", "currency": "BRL"},
    "RUS": {"symbol": "IMOEX.ME", "name": "MOEX Russia", "currency": "RUB"},
    "KOR": {"symbol": "^KS11", "name": "KOSPI", "currency": "KRW"},
    "AUS": {"symbol": "^AXJO", "name": "ASX 200", "currency": "AUD"},
    "CAN": {"symbol": "^GSPTSE", "name": "S&P/TSX", "currency": "CAD"},
    "MEX": {"symbol": "^MXX", "name": "IPC Mexico", "currency": "MXN"},
    "CHE": {"symbol": "^SSMI", "name": "SMI", "currency": "CHF"},
    "SGP": {"symbol": "^STI", "name": "STI", "currency": "SGD"},
    "TWN": {"symbol": "^TWII", "name": "TAIEX", "currency": "TWD"},
    "TUR": {"symbol": "XU100.IS", "name": "BIST 100", "currency": "TRY"},
    "ZAF": {"symbol": "^JTOPI", "name": "JSE Top 40", "currency": "ZAR"},
    "ARG": {"symbol": "^MERV", "name": "MERVAL", "currency": "ARS"},
}

# Currency pairs for FX monitoring
CURRENCY_PAIRS = {
    "EUR": {"symbol": "EURUSD=X", "name": "EUR/USD"},
    "GBP": {"symbol": "GBPUSD=X", "name": "GBP/USD"},
    "JPY": {"symbol": "USDJPY=X", "name": "USD/JPY"},
    "CNY": {"symbol": "USDCNY=X", "name": "USD/CNY"},
    "RUB": {"symbol": "USDRUB=X", "name": "USD/RUB"},
    "BRL": {"symbol": "USDBRL=X", "name": "USD/BRL"},
    "INR": {"symbol": "USDINR=X", "name": "USD/INR"},
    "TRY": {"symbol": "USDTRY=X", "name": "USD/TRY"},
    "MXN": {"symbol": "USDMXN=X", "name": "USD/MXN"},
    "ZAR": {"symbol": "USDZAR=X", "name": "USD/ZAR"},
    "ARS": {"symbol": "USDARS=X", "name": "USD/ARS"},
    "KRW": {"symbol": "USDKRW=X", "name": "USD/KRW"},
    "CHF": {"symbol": "USDCHF=X", "name": "USD/CHF"},
    "AUD": {"symbol": "AUDUSD=X", "name": "AUD/USD"},
    "CAD": {"symbol": "USDCAD=X", "name": "USD/CAD"},
}

# FRED series for interest rates and economic indicators
FRED_SERIES = {
    # Interest Rates
    "USA_INTEREST": {"series_id": "FEDFUNDS", "name": "Federal Funds Rate", "country": "USA", "type": "interest_rate"},
    "EUR_INTEREST": {"series_id": "ECBDFR", "name": "ECB Deposit Rate", "country": "EUR", "type": "interest_rate"},
    "GBR_INTEREST": {"series_id": "BOGZ1FL072052006Q", "name": "UK Bank Rate", "country": "GBR", "type": "interest_rate"},
    "JPN_INTEREST": {"series_id": "IRSTCI01JPM156N", "name": "Japan Policy Rate", "country": "JPN", "type": "interest_rate"},

    # Treasury Yields
    "USA_10Y": {"series_id": "DGS10", "name": "US 10-Year Treasury", "country": "USA", "type": "bond_yield"},
    "USA_2Y": {"series_id": "DGS2", "name": "US 2-Year Treasury", "country": "USA", "type": "bond_yield"},

    # Credit Spreads (proxy for CDS)
    "USA_HY_SPREAD": {"series_id": "BAMLH0A0HYM2", "name": "US High Yield Spread", "country": "USA", "type": "cds"},
    "USA_IG_SPREAD": {"series_id": "BAMLC0A0CM", "name": "US Investment Grade Spread", "country": "USA", "type": "cds"},

    # VIX (Fear Index)
    "VIX": {"series_id": "VIXCLS", "name": "VIX Volatility Index", "country": "USA", "type": "volatility"},
}

# Alert thresholds for different indicator types
ALERT_THRESHOLDS = {
    "stock_index": {"pct_change": 3.0},  # 3% daily move
    "currency": {"pct_change": 2.0},  # 2% daily move
    "interest_rate": {"pct_change": 25.0},  # 25 bps move
    "bond_yield": {"pct_change": 10.0},  # 10% relative move
    "cds": {"pct_change": 20.0},  # 20% spread widening
    "volatility": {"absolute": 30.0},  # VIX above 30
}


class FinancialIntelligenceCollector(BaseCollector):
    """
    Collector for financial indicators and economic intelligence.
    Tracks stock indices, currencies, interest rates, and credit spreads.
    """

    def __init__(self, config=None):
        super().__init__(config)
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            "User-Agent": "TITANIUM-VANGUARD/2.0 (Geopolitical Intelligence System)",
            "Accept": "application/json",
        }
        self.logger.info("FinancialIntelligenceCollector initialized")

    async def fetch(self) -> List[Dict]:
        """
        Fetch financial data from multiple sources.

        Returns:
            List of raw financial indicator data
        """
        all_indicators = []

        # Fetch stock indices
        stock_data = await self._fetch_stock_indices()
        all_indicators.extend(stock_data)

        # Fetch currency rates
        currency_data = await self._fetch_currency_rates()
        all_indicators.extend(currency_data)

        # Fetch simulated economic indicators
        # (In production, these would come from FRED API with key)
        economic_data = self._get_economic_indicators()
        all_indicators.extend(economic_data)

        self.logger.info(f"Total fetched: {len(all_indicators)} financial indicators")
        return all_indicators

    async def _fetch_stock_indices(self) -> List[Dict]:
        """Fetch stock index data from Yahoo Finance"""
        indicators = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for country_iso, index_info in STOCK_INDICES.items():
                try:
                    symbol = index_info["symbol"]
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

                    params = {
                        "interval": "1d",
                        "range": "5d"
                    }

                    async with session.get(url, params=params, headers=self.headers, ssl=False) as response:
                        if response.status != 200:
                            self.logger.debug(f"Failed to fetch {symbol}: {response.status}")
                            continue

                        data = await response.json()

                        # Extract price data
                        result = data.get("chart", {}).get("result", [])
                        if not result:
                            continue

                        quote = result[0].get("indicators", {}).get("quote", [{}])[0]
                        timestamps = result[0].get("timestamp", [])

                        if not quote.get("close") or not timestamps:
                            continue

                        # Get latest and previous close
                        closes = [c for c in quote["close"] if c is not None]
                        if len(closes) < 2:
                            continue

                        current = closes[-1]
                        previous = closes[-2]
                        pct_change = ((current - previous) / previous) * 100

                        # Check for alert
                        is_alert = abs(pct_change) >= ALERT_THRESHOLDS["stock_index"]["pct_change"]

                        indicators.append({
                            "country_iso": country_iso,
                            "indicator_type": "stock_index",
                            "indicator_name": index_info["name"],
                            "value": round(current, 2),
                            "unit": "index_points",
                            "previous_value": round(previous, 2),
                            "pct_change": round(pct_change, 2),
                            "source": "Yahoo Finance",
                            "source_series_id": symbol,
                            "is_alert": is_alert,
                            "alert_type": "spike" if pct_change > 0 else "drop" if is_alert else None,
                            "raw_data": {"currency": index_info["currency"]}
                        })

                except Exception as e:
                    self.logger.debug(f"Error fetching {country_iso} index: {e}")
                    continue

                # Small delay between requests
                await asyncio.sleep(0.3)

        self.logger.info(f"Fetched {len(indicators)} stock indices")
        return indicators

    async def _fetch_currency_rates(self) -> List[Dict]:
        """Fetch currency exchange rates from Yahoo Finance"""
        indicators = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for currency, pair_info in CURRENCY_PAIRS.items():
                try:
                    symbol = pair_info["symbol"]
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

                    params = {
                        "interval": "1d",
                        "range": "5d"
                    }

                    async with session.get(url, params=params, headers=self.headers, ssl=False) as response:
                        if response.status != 200:
                            continue

                        data = await response.json()

                        result = data.get("chart", {}).get("result", [])
                        if not result:
                            continue

                        quote = result[0].get("indicators", {}).get("quote", [{}])[0]

                        if not quote.get("close"):
                            continue

                        closes = [c for c in quote["close"] if c is not None]
                        if len(closes) < 2:
                            continue

                        current = closes[-1]
                        previous = closes[-2]
                        pct_change = ((current - previous) / previous) * 100

                        # Map currency to country
                        country_map = {
                            "EUR": "EUR", "GBP": "GBR", "JPY": "JPN", "CNY": "CHN",
                            "RUB": "RUS", "BRL": "BRA", "INR": "IND", "TRY": "TUR",
                            "MXN": "MEX", "ZAR": "ZAF", "ARS": "ARG", "KRW": "KOR",
                            "CHF": "CHE", "AUD": "AUS", "CAD": "CAN"
                        }
                        country_iso = country_map.get(currency, currency)

                        # Check for alert
                        is_alert = abs(pct_change) >= ALERT_THRESHOLDS["currency"]["pct_change"]

                        indicators.append({
                            "country_iso": country_iso,
                            "indicator_type": "currency",
                            "indicator_name": pair_info["name"],
                            "value": round(current, 4),
                            "unit": "exchange_rate",
                            "previous_value": round(previous, 4),
                            "pct_change": round(pct_change, 2),
                            "source": "Yahoo Finance",
                            "source_series_id": symbol,
                            "is_alert": is_alert,
                            "alert_type": "depreciation" if pct_change > 0 and "USD" in pair_info["name"][:3] else "appreciation" if is_alert else None,
                            "raw_data": None
                        })

                except Exception as e:
                    self.logger.debug(f"Error fetching {currency}: {e}")
                    continue

                await asyncio.sleep(0.3)

        self.logger.info(f"Fetched {len(indicators)} currency rates")
        return indicators

    def _get_economic_indicators(self) -> List[Dict]:
        """
        Get economic indicators (simulated data when API key not available).
        In production, this would fetch from FRED API.
        """
        indicators = []

        # Simulated recent data for major economies
        economic_data = [
            # Interest Rates
            {"country": "USA", "type": "interest_rate", "name": "Federal Funds Rate", "value": 5.33, "unit": "percent"},
            {"country": "EUR", "type": "interest_rate", "name": "ECB Main Rate", "value": 4.50, "unit": "percent"},
            {"country": "GBR", "type": "interest_rate", "name": "BoE Bank Rate", "value": 5.25, "unit": "percent"},
            {"country": "JPN", "type": "interest_rate", "name": "BoJ Policy Rate", "value": 0.10, "unit": "percent"},
            {"country": "CHN", "type": "interest_rate", "name": "PBoC LPR 1Y", "value": 3.45, "unit": "percent"},

            # 10-Year Yields
            {"country": "USA", "type": "bond_yield", "name": "US 10Y Treasury", "value": 4.25, "unit": "percent"},
            {"country": "DEU", "type": "bond_yield", "name": "German 10Y Bund", "value": 2.35, "unit": "percent"},
            {"country": "JPN", "type": "bond_yield", "name": "JGB 10Y", "value": 0.75, "unit": "percent"},
            {"country": "GBR", "type": "bond_yield", "name": "UK 10Y Gilt", "value": 4.15, "unit": "percent"},
            {"country": "ITA", "type": "bond_yield", "name": "Italian BTP 10Y", "value": 3.85, "unit": "percent"},

            # Credit Spreads (CDS proxy)
            {"country": "USA", "type": "cds", "name": "US IG Credit Spread", "value": 120, "unit": "basis_points"},
            {"country": "USA", "type": "cds", "name": "US HY Credit Spread", "value": 380, "unit": "basis_points"},
            {"country": "EUR", "type": "cds", "name": "EUR IG Credit Spread", "value": 95, "unit": "basis_points"},

            # Volatility
            {"country": "USA", "type": "volatility", "name": "VIX Index", "value": 14.5, "unit": "index_points"},

            # FX Reserves (billions USD)
            {"country": "CHN", "type": "fx_reserves", "name": "FX Reserves", "value": 3220, "unit": "usd_billions"},
            {"country": "JPN", "type": "fx_reserves", "name": "FX Reserves", "value": 1290, "unit": "usd_billions"},
            {"country": "CHE", "type": "fx_reserves", "name": "FX Reserves", "value": 780, "unit": "usd_billions"},
            {"country": "IND", "type": "fx_reserves", "name": "FX Reserves", "value": 595, "unit": "usd_billions"},
            {"country": "RUS", "type": "fx_reserves", "name": "FX Reserves", "value": 580, "unit": "usd_billions"},
            {"country": "SAU", "type": "fx_reserves", "name": "FX Reserves", "value": 450, "unit": "usd_billions"},
            {"country": "KOR", "type": "fx_reserves", "name": "FX Reserves", "value": 420, "unit": "usd_billions"},
            {"country": "BRA", "type": "fx_reserves", "name": "FX Reserves", "value": 350, "unit": "usd_billions"},
            {"country": "SGP", "type": "fx_reserves", "name": "FX Reserves", "value": 290, "unit": "usd_billions"},
            {"country": "THA", "type": "fx_reserves", "name": "FX Reserves", "value": 220, "unit": "usd_billions"},
        ]

        for data in economic_data:
            # Check for alert conditions
            is_alert = False
            alert_type = None

            if data["type"] == "volatility" and data["value"] >= ALERT_THRESHOLDS["volatility"]["absolute"]:
                is_alert = True
                alert_type = "high_volatility"

            indicators.append({
                "country_iso": data["country"],
                "indicator_type": data["type"],
                "indicator_name": data["name"],
                "value": data["value"],
                "unit": data["unit"],
                "previous_value": None,
                "pct_change": None,
                "source": "IMF/FRED",
                "source_series_id": None,
                "is_alert": is_alert,
                "alert_type": alert_type,
                "raw_data": {"simulated": True}
            })

        return indicators

    async def parse(self, raw_data: List[Dict]) -> List[FinancialIndicator]:
        """Parse raw data into FinancialIndicator objects"""
        indicators = []
        seen = set()

        for data in raw_data:
            try:
                # Create unique key
                key = f"{data.get('country_iso')}_{data.get('indicator_type')}_{data.get('indicator_name')}"
                if key in seen:
                    continue
                seen.add(key)

                indicator = FinancialIndicator(
                    country_iso=data.get("country_iso", "UNK"),
                    indicator_type=data.get("indicator_type", "unknown"),
                    indicator_name=data.get("indicator_name", "Unknown"),
                    value=float(data.get("value", 0)),
                    unit=data.get("unit", "unknown"),
                    previous_value=float(data["previous_value"]) if data.get("previous_value") else None,
                    pct_change=float(data["pct_change"]) if data.get("pct_change") else None,
                    source=data.get("source", "Unknown"),
                    source_series_id=data.get("source_series_id"),
                    source_url=data.get("source_url"),
                    indicator_date=date.today(),
                    is_alert=data.get("is_alert", False),
                    alert_type=data.get("alert_type"),
                    raw_data=data.get("raw_data")
                )

                indicators.append(indicator)

            except Exception as e:
                self.logger.warning(f"Error parsing indicator: {e}")
                continue

        self.logger.info(f"Parsed {len(indicators)} financial indicators")
        return indicators

    async def save(self, indicators: List[FinancialIndicator]) -> int:
        """Save financial indicators to database"""
        saved = 0

        try:
            from sqlalchemy import text

            with self.db.session() as session:
                for indicator in indicators:
                    try:
                        # Check for duplicates (same indicator on same date)
                        result = session.execute(
                            text("""
                                SELECT id FROM financial_indicators
                                WHERE country_iso = :country_iso
                                  AND indicator_type = :indicator_type
                                  AND indicator_name = :indicator_name
                                  AND indicator_date = :indicator_date
                            """),
                            {
                                "country_iso": indicator.country_iso,
                                "indicator_type": indicator.indicator_type,
                                "indicator_name": indicator.indicator_name,
                                "indicator_date": indicator.indicator_date
                            }
                        )

                        existing = result.fetchone()
                        if existing:
                            # Update existing record
                            session.execute(
                                text("""
                                    UPDATE financial_indicators
                                    SET value = :value,
                                        previous_value = :previous_value,
                                        pct_change = :pct_change,
                                        is_alert = :is_alert,
                                        alert_type = :alert_type,
                                        recorded_at = :recorded_at
                                    WHERE id = :id
                                """),
                                {
                                    "id": existing[0],
                                    "value": indicator.value,
                                    "previous_value": indicator.previous_value,
                                    "pct_change": indicator.pct_change,
                                    "is_alert": indicator.is_alert,
                                    "alert_type": indicator.alert_type,
                                    "recorded_at": datetime.now(timezone.utc)
                                }
                            )
                        else:
                            # Insert new record
                            session.execute(
                                text("""
                                    INSERT INTO financial_indicators (
                                        country_iso, indicator_type, indicator_name,
                                        value, unit, previous_value, pct_change,
                                        source, source_series_id, source_url,
                                        indicator_date, is_alert, alert_type,
                                        raw_data
                                    ) VALUES (
                                        :country_iso, :indicator_type, :indicator_name,
                                        :value, :unit, :previous_value, :pct_change,
                                        :source, :source_series_id, :source_url,
                                        :indicator_date, :is_alert, :alert_type,
                                        :raw_data
                                    )
                                """),
                                {
                                    "country_iso": indicator.country_iso,
                                    "indicator_type": indicator.indicator_type,
                                    "indicator_name": indicator.indicator_name,
                                    "value": indicator.value,
                                    "unit": indicator.unit,
                                    "previous_value": indicator.previous_value,
                                    "pct_change": indicator.pct_change,
                                    "source": indicator.source,
                                    "source_series_id": indicator.source_series_id,
                                    "source_url": indicator.source_url,
                                    "indicator_date": indicator.indicator_date,
                                    "is_alert": indicator.is_alert,
                                    "alert_type": indicator.alert_type,
                                    "raw_data": json.dumps(indicator.raw_data) if indicator.raw_data else None
                                }
                            )

                        saved += 1

                    except Exception as e:
                        self.logger.warning(f"Error saving indicator: {e}")
                        continue

                session.commit()

            self.logger.info(f"Saved {saved} financial indicators")

        except Exception as e:
            self.logger.error(f"Error in save: {e}")

        return saved

    async def validate(self, indicator) -> bool:
        """Validate a financial indicator"""
        if not hasattr(indicator, 'country_iso') or not indicator.country_iso:
            return False
        if not hasattr(indicator, 'value') or indicator.value is None:
            return False
        return True

    async def detect_financial_contagion(self, threshold_pct: float = 5.0) -> List[Dict]:
        """
        Detect potential financial contagion signals.
        Identifies correlated movements across markets.

        Args:
            threshold_pct: Percentage threshold for significant moves

        Returns:
            List of contagion alerts
        """
        from sqlalchemy import text

        alerts = []

        try:
            with self.db.session() as session:
                # Get recent indicators with significant moves
                result = session.execute(
                    text("""
                        SELECT country_iso, indicator_type, indicator_name,
                               value, pct_change, indicator_date
                        FROM financial_indicators
                        WHERE indicator_date >= :cutoff_date
                          AND ABS(pct_change) >= :threshold
                        ORDER BY ABS(pct_change) DESC
                    """),
                    {
                        "cutoff_date": date.today() - timedelta(days=7),
                        "threshold": threshold_pct
                    }
                )

                rows = result.fetchall()

                for row in rows:
                    alerts.append({
                        "country": row[0],
                        "indicator_type": row[1],
                        "indicator_name": row[2],
                        "value": row[3],
                        "pct_change": row[4],
                        "date": row[5].isoformat() if row[5] else None,
                        "severity": "HIGH" if abs(row[4] or 0) > threshold_pct * 2 else "MEDIUM"
                    })

        except Exception as e:
            self.logger.error(f"Error detecting contagion: {e}")

        return alerts

    async def get_country_risk_score(self, country_iso: str) -> Dict:
        """
        Calculate composite risk score for a country based on financial indicators.

        Args:
            country_iso: ISO country code

        Returns:
            Risk assessment dict
        """
        from sqlalchemy import text

        try:
            with self.db.session() as session:
                result = session.execute(
                    text("""
                        SELECT indicator_type, indicator_name, value, pct_change, is_alert
                        FROM financial_indicators
                        WHERE country_iso = :country_iso
                          AND indicator_date = :today
                    """),
                    {"country_iso": country_iso, "today": date.today()}
                )

                rows = result.fetchall()

                if not rows:
                    return {"country": country_iso, "risk_score": None, "message": "No data available"}

                # Calculate risk factors
                alert_count = sum(1 for row in rows if row[4])
                avg_change = sum(abs(row[3] or 0) for row in rows) / len(rows)

                # Simple risk score (0-100)
                risk_score = min(100, (alert_count * 20) + (avg_change * 5))

                return {
                    "country": country_iso,
                    "risk_score": round(risk_score, 1),
                    "alert_count": alert_count,
                    "avg_change": round(avg_change, 2),
                    "risk_level": "HIGH" if risk_score >= 60 else "MEDIUM" if risk_score >= 30 else "LOW"
                }

        except Exception as e:
            self.logger.error(f"Error calculating risk score: {e}")
            return {"country": country_iso, "error": str(e)}

    async def run(self) -> Dict:
        """Execute the full collection pipeline"""
        try:
            self.logger.info(f"Starting {self.name}...")
            start_time = datetime.now(timezone.utc)

            # Fetch
            raw_data = await self.fetch()

            # Parse
            indicators = await self.parse(raw_data)

            # Validate
            valid_indicators = [i for i in indicators if await self.validate(i)]

            # Save
            saved = await self.save(valid_indicators)

            # Stats
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Count by type
            type_counts = {}
            alert_counts = {}
            for i in valid_indicators:
                type_counts[i.indicator_type] = type_counts.get(i.indicator_type, 0) + 1
                if i.is_alert:
                    alert_counts[i.indicator_type] = alert_counts.get(i.indicator_type, 0) + 1

            stats = {
                "collector": self.name,
                "status": "success",
                "raw_fetched": len(raw_data),
                "parsed": len(indicators),
                "valid": len(valid_indicators),
                "saved": saved,
                "by_type": type_counts,
                "alerts": alert_counts,
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            self.logger.info(f"{self.name} completed: {saved} indicators saved")
            return stats

        except Exception as e:
            self.logger.error(f"Error in run: {e}", exc_info=True)
            return {
                "collector": self.name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }


async def main():
    """Test the collector"""
    collector = FinancialIntelligenceCollector()
    result = await collector.run()
    print(f"Collection result: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
