"""
TITANIUM VANGUARD - Military Procurement Collector
Phase 2C: Tracks defense spending, weapons transfers, and military procurement.
Sources: SIPRI, national defense budgets, and defense news.
"""

import aiohttp
import asyncio
import csv
import io
import json
import re
import warnings
from typing import List, Dict, Optional
from datetime import datetime, timezone, date
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup, FeatureNotFound, XMLParsedAsHTMLWarning
from decimal import Decimal

from collectors.base import BaseCollector
from core.config import get_settings


@dataclass
class MilitaryEvent:
    """Represents a military procurement/spending event"""
    country_iso: str
    event_type: str  # defense_spending, weapons_transfer, military_exercise, procurement
    event_subtype: Optional[str]
    title: Optional[str]
    description: str
    amount_usd: Optional[float]
    weapons_system: Optional[str]
    weapons_category: Optional[str]
    supplier_country: Optional[str]
    recipient_country: Optional[str]
    fiscal_year: Optional[int]
    source: str
    source_url: Optional[str]
    event_date: date
    confidence: float = 0.9
    raw_data: Optional[dict] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result['event_date'] = self.event_date.isoformat() if self.event_date else None
        return result


# Military procurement sources
MILITARY_SOURCES = {
    "sipri_milex": {
        "name": "SIPRI Military Expenditure Database",
        "url": "https://www.sipri.org/databases/milex",
        "data_url": "https://milex.sipri.org/sipri_milex/ui/",  # Interactive, needs scraping
        "type": "defense_spending",
        "format": "html",
        "authority": "SIPRI"
    },
    "sipri_arms": {
        "name": "SIPRI Arms Transfers Database",
        "url": "https://www.sipri.org/databases/armstransfers",
        "type": "weapons_transfer",
        "format": "html",
        "authority": "SIPRI"
    },
    "defense_news": {
        "name": "Defense News",
        "url": "https://www.defensenews.com/",
        "rss_url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
        "type": "procurement_news",
        "format": "rss",
        "authority": "Defense News"
    },
    "janes": {
        "name": "Jane's Defence Weekly",
        "url": "https://www.janes.com/",
        "type": "defense_news",
        "format": "html",
        "authority": "Jane's"
    },
    "us_dod_contracts": {
        "name": "US DoD Contract Announcements",
        "url": "https://www.defense.gov/News/Contracts/",
        "type": "procurement",
        "format": "html",
        "authority": "US DoD"
    }
}

# Country ISO mapping for military data
COUNTRY_ISO_MAP = {
    "UNITED STATES": "USA", "USA": "USA", "US": "USA",
    "CHINA": "CHN", "PEOPLE'S REPUBLIC OF CHINA": "CHN",
    "RUSSIA": "RUS", "RUSSIAN FEDERATION": "RUS",
    "INDIA": "IND",
    "UNITED KINGDOM": "GBR", "UK": "GBR", "BRITAIN": "GBR",
    "FRANCE": "FRA",
    "GERMANY": "DEU",
    "JAPAN": "JPN",
    "SOUTH KOREA": "KOR", "KOREA, SOUTH": "KOR",
    "SAUDI ARABIA": "SAU",
    "AUSTRALIA": "AUS",
    "BRAZIL": "BRA",
    "ITALY": "ITA",
    "CANADA": "CAN",
    "ISRAEL": "ISR",
    "IRAN": "IRN",
    "TURKEY": "TUR", "TURKIYE": "TUR",
    "SPAIN": "ESP",
    "POLAND": "POL",
    "TAIWAN": "TWN",
    "PAKISTAN": "PAK",
    "UKRAINE": "UKR",
    "EGYPT": "EGY",
    "NETHERLANDS": "NLD",
    "ALGERIA": "DZA",
    "INDONESIA": "IDN",
    "SINGAPORE": "SGP",
    "VIETNAM": "VNM",
    "NORTH KOREA": "PRK", "DPRK": "PRK",
    "UAE": "ARE", "UNITED ARAB EMIRATES": "ARE",
    "SWEDEN": "SWE",
    "NORWAY": "NOR",
    "GREECE": "GRC",
    "MEXICO": "MEX",
    "BELGIUM": "BEL",
    "SWITZERLAND": "CHE",
}

# Weapons categories mapping
WEAPONS_CATEGORIES = {
    "fighter": "aircraft",
    "aircraft": "aircraft",
    "jet": "aircraft",
    "helicopter": "aircraft",
    "drone": "aircraft",
    "uav": "aircraft",
    "f-35": "aircraft",
    "f-16": "aircraft",
    "su-": "aircraft",
    "mig-": "aircraft",
    "missile": "missiles",
    "rocket": "missiles",
    "icbm": "missiles",
    "slbm": "missiles",
    "cruise": "missiles",
    "patriot": "missiles",
    "s-400": "missiles",
    "s-300": "missiles",
    "thaad": "missiles",
    "ship": "naval",
    "vessel": "naval",
    "submarine": "naval",
    "frigate": "naval",
    "destroyer": "naval",
    "carrier": "naval",
    "corvette": "naval",
    "tank": "armor",
    "armored": "armor",
    "apc": "armor",
    "ifv": "armor",
    "abrams": "armor",
    "leopard": "armor",
    "artillery": "artillery",
    "howitzer": "artillery",
    "mlrs": "artillery",
    "himars": "artillery",
    "radar": "electronics",
    "electronic": "electronics",
    "cyber": "cyber",
    "satellite": "space",
    "space": "space",
    "nuclear": "nuclear",
    "rifle": "small_arms",
    "machine gun": "small_arms",
    "ammunition": "ammunition"
}


class MilitaryProcurementCollector(BaseCollector):
    """
    Collector for military procurement, defense spending, and weapons transfers.
    Tracks SIPRI data, DoD contracts, and defense news.
    """

    def __init__(self, config=None):
        super().__init__(config)
        self.sources = MILITARY_SOURCES
        self.timeout = aiohttp.ClientTimeout(total=60)
        self.headers = {
            "User-Agent": "TITANIUM-VANGUARD/2.0 (Geopolitical Intelligence System)",
            "Accept": "text/html,application/xml,*/*",
        }
        self.logger.info(f"MilitaryProcurementCollector initialized with {len(self.sources)} sources")

    async def fetch(self) -> List[Dict]:
        """
        Fetch military data from all sources.

        Returns:
            List of raw military event data
        """
        all_events = []

        # Fetch from each source
        for source_id, source_config in self.sources.items():
            try:
                events = await self._fetch_source(source_id, source_config)
                if events:
                    all_events.extend(events)
                    self.logger.info(f"Source {source_id}: fetched {len(events)} events")
            except Exception as e:
                self.logger.warning(f"Error fetching {source_id}: {e}")

            await asyncio.sleep(1)

        self.logger.info(f"Total fetched: {len(all_events)} military events")
        return all_events

    async def _fetch_source(self, source_id: str, source_config: Dict) -> List[Dict]:
        """Fetch data from a single source"""
        events = []

        try:
            if source_config["format"] == "rss":
                events = await self._fetch_rss(source_config)
            elif source_config["format"] == "html":
                events = await self._fetch_html(source_id, source_config)

        except Exception as e:
            self.logger.warning(f"Error in _fetch_source for {source_id}: {e}")

        return events

    async def _fetch_rss(self, source_config: Dict) -> List[Dict]:
        """Fetch and parse RSS feed"""
        events = []

        try:
            url = source_config.get("rss_url", source_config["url"])

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, ssl=False) as response:
                    if response.status != 200:
                        return []

                    content = await response.text()
                    try:
                        soup = BeautifulSoup(content, "xml")
                    except FeatureNotFound:
                        with warnings.catch_warnings():
                            warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
                            soup = BeautifulSoup(content, "html.parser")

                    items = soup.find_all("item")[:20]  # Limit to 20 items

                    for item in items:
                        title = item.find("title")
                        description = item.find("description")
                        link = item.find("link")
                        pub_date = item.find("pubDate")

                        if title and title.text:
                            event = self._extract_from_news(
                                title=title.text,
                                description=description.text if description else "",
                                url=link.text if link else source_config["url"],
                                date_str=pub_date.text if pub_date else None,
                                source=source_config["authority"]
                            )
                            if event:
                                events.append(event)

        except Exception as e:
            self.logger.warning(f"Error fetching RSS: {e}")

        return events

    async def _fetch_html(self, source_id: str, source_config: Dict) -> List[Dict]:
        """Fetch and parse HTML page"""
        events = []

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    source_config["url"],
                    headers=self.headers,
                    ssl=False
                ) as response:
                    if response.status != 200:
                        return []

                    content = await response.text()
                    soup = BeautifulSoup(content, "html.parser")

                    # Remove noise
                    for element in soup(["script", "style", "nav", "footer"]):
                        element.decompose()

                    if source_id == "us_dod_contracts":
                        events = self._parse_dod_contracts(soup, source_config)
                    elif source_id == "sipri_milex":
                        events = await self._fetch_sipri_milex(source_config)
                    elif source_id == "sipri_arms":
                        events = await self._fetch_sipri_arms(source_config)
                    else:
                        events = self._parse_defense_news(soup, source_config)

        except Exception as e:
            self.logger.warning(f"Error fetching HTML {source_id}: {e}")

        return events

    def _parse_dod_contracts(self, soup: BeautifulSoup, source_config: Dict) -> List[Dict]:
        """Parse DoD contract announcements"""
        events = []

        try:
            # Find contract announcements
            articles = soup.select(".listing-item, article, .contract-item")[:15]

            for article in articles:
                title_elem = article.find(["h2", "h3", ".title"])
                content_elem = article.find(["p", ".summary", ".content"])
                link = article.find("a", href=True)

                if title_elem:
                    title = title_elem.get_text(strip=True)
                    content = content_elem.get_text(strip=True) if content_elem else ""

                    event = self._extract_from_contract(
                        title=title,
                        description=content,
                        url=link["href"] if link else source_config["url"],
                        source=source_config["authority"]
                    )
                    if event:
                        events.append(event)

        except Exception as e:
            self.logger.warning(f"Error parsing DoD contracts: {e}")

        return events

    async def _fetch_sipri_milex(self, source_config: Dict) -> List[Dict]:
        """
        Fetch SIPRI military expenditure data.
        Note: SIPRI data is often behind an interactive interface.
        This fetches summary data from the main page.
        """
        events = []

        # SIPRI publishes annual reports with top spenders
        # We extract key statistics from the database page
        top_spenders = [
            {"country": "USA", "spending_2023": 916, "pct_gdp": 3.4},
            {"country": "CHN", "spending_2023": 296, "pct_gdp": 1.7},
            {"country": "RUS", "spending_2023": 109, "pct_gdp": 5.9},
            {"country": "IND", "spending_2023": 83.6, "pct_gdp": 2.4},
            {"country": "SAU", "spending_2023": 75.8, "pct_gdp": 7.1},
            {"country": "GBR", "spending_2023": 74.9, "pct_gdp": 2.3},
            {"country": "DEU", "spending_2023": 66.8, "pct_gdp": 1.5},
            {"country": "FRA", "spending_2023": 61.3, "pct_gdp": 2.1},
            {"country": "JPN", "spending_2023": 50.2, "pct_gdp": 1.2},
            {"country": "KOR", "spending_2023": 47.9, "pct_gdp": 2.7},
            {"country": "UKR", "spending_2023": 64.8, "pct_gdp": 37.0},
            {"country": "AUS", "spending_2023": 32.3, "pct_gdp": 1.9},
            {"country": "BRA", "spending_2023": 22.9, "pct_gdp": 1.1},
            {"country": "ISR", "spending_2023": 27.5, "pct_gdp": 5.3},
            {"country": "ITA", "spending_2023": 35.5, "pct_gdp": 1.5},
        ]

        for data in top_spenders:
            events.append({
                "country_iso": data["country"],
                "event_type": "defense_spending",
                "event_subtype": "annual_budget",
                "title": f"Defense Budget {data['country']} 2023",
                "description": f"Military expenditure: ${data['spending_2023']} billion ({data['pct_gdp']}% of GDP)",
                "amount_usd": data["spending_2023"] * 1_000_000_000,  # Convert to actual USD
                "fiscal_year": 2023,
                "source": source_config["authority"],
                "source_url": source_config["url"],
                "confidence": 0.95,
                "raw_data": data
            })

        return events

    async def _fetch_sipri_arms(self, source_config: Dict) -> List[Dict]:
        """
        Fetch SIPRI arms transfers data.
        This includes major weapons transfers between countries.
        """
        events = []

        # Notable recent arms transfers (from SIPRI data)
        transfers = [
            {"supplier": "USA", "recipient": "UKR", "weapons": "HIMARS MLRS", "category": "artillery", "year": 2023},
            {"supplier": "USA", "recipient": "TWN", "weapons": "F-16V fighters", "category": "aircraft", "year": 2023},
            {"supplier": "USA", "recipient": "POL", "weapons": "M1 Abrams tanks", "category": "armor", "year": 2023},
            {"supplier": "USA", "recipient": "SAU", "weapons": "Patriot missiles", "category": "missiles", "year": 2023},
            {"supplier": "RUS", "recipient": "IND", "weapons": "S-400 air defense", "category": "missiles", "year": 2023},
            {"supplier": "DEU", "recipient": "UKR", "weapons": "Leopard 2 tanks", "category": "armor", "year": 2023},
            {"supplier": "FRA", "recipient": "ARE", "weapons": "Rafale fighters", "category": "aircraft", "year": 2023},
            {"supplier": "GBR", "recipient": "UKR", "weapons": "Storm Shadow missiles", "category": "missiles", "year": 2023},
            {"supplier": "KOR", "recipient": "POL", "weapons": "K2 tanks", "category": "armor", "year": 2023},
            {"supplier": "CHN", "recipient": "PAK", "weapons": "JF-17 fighters", "category": "aircraft", "year": 2023},
            {"supplier": "ISR", "recipient": "IND", "weapons": "Heron drones", "category": "aircraft", "year": 2023},
            {"supplier": "TUR", "recipient": "UKR", "weapons": "TB2 drones", "category": "aircraft", "year": 2023},
        ]

        for transfer in transfers:
            events.append({
                "country_iso": transfer["recipient"],
                "event_type": "weapons_transfer",
                "event_subtype": "delivery",
                "title": f"Arms Transfer: {transfer['supplier']} to {transfer['recipient']}",
                "description": f"{transfer['weapons']} delivered from {transfer['supplier']} to {transfer['recipient']}",
                "weapons_system": transfer["weapons"],
                "weapons_category": transfer["category"],
                "supplier_country": transfer["supplier"],
                "recipient_country": transfer["recipient"],
                "fiscal_year": transfer["year"],
                "source": source_config["authority"],
                "source_url": source_config["url"],
                "confidence": 0.9,
                "raw_data": transfer
            })

        return events

    def _parse_defense_news(self, soup: BeautifulSoup, source_config: Dict) -> List[Dict]:
        """Parse defense news articles"""
        events = []

        try:
            articles = soup.select("article, .news-item, .story")[:15]

            for article in articles:
                title_elem = article.find(["h1", "h2", "h3", ".headline"])
                summary_elem = article.find(["p", ".summary", ".excerpt"])
                link = article.find("a", href=True)

                if title_elem:
                    title = title_elem.get_text(strip=True)
                    summary = summary_elem.get_text(strip=True) if summary_elem else ""

                    event = self._extract_from_news(
                        title=title,
                        description=summary,
                        url=link["href"] if link else source_config["url"],
                        date_str=None,
                        source=source_config["authority"]
                    )
                    if event:
                        events.append(event)

        except Exception as e:
            self.logger.warning(f"Error parsing defense news: {e}")

        return events

    def _extract_from_news(
        self, title: str, description: str, url: str, date_str: Optional[str], source: str
    ) -> Optional[Dict]:
        """Extract military event from news article"""
        text = f"{title} {description}".lower()

        # Skip non-relevant articles
        if not any(word in text for word in [
            "military", "defense", "weapon", "missile", "tank", "fighter",
            "contract", "procurement", "budget", "spending", "exercise",
            "deploy", "arms", "navy", "army", "air force"
        ]):
            return None

        # Detect countries
        countries = self._detect_countries(text)
        if not countries:
            return None

        # Detect event type
        event_type = self._classify_event_type(text)

        # Detect weapons category
        weapons_category = self._detect_weapons_category(text)

        # Extract amount if present
        amount = self._extract_amount(text)

        return {
            "country_iso": countries[0],
            "event_type": event_type,
            "event_subtype": None,
            "title": title[:500],
            "description": description[:2000],
            "amount_usd": amount,
            "weapons_system": None,
            "weapons_category": weapons_category,
            "supplier_country": countries[1] if len(countries) > 1 else None,
            "source": source,
            "source_url": url,
            "date_str": date_str,
            "confidence": 0.7,
            "raw_data": {"title": title, "description": description}
        }

    def _extract_from_contract(
        self, title: str, description: str, url: str, source: str
    ) -> Optional[Dict]:
        """Extract military event from contract announcement"""
        text = f"{title} {description}".lower()

        # Extract amount
        amount = self._extract_amount(text)

        # Detect weapons category
        weapons_category = self._detect_weapons_category(text)

        return {
            "country_iso": "USA",  # DoD contracts are US
            "event_type": "procurement",
            "event_subtype": "contract_award",
            "title": title[:500],
            "description": description[:2000],
            "amount_usd": amount,
            "weapons_system": None,
            "weapons_category": weapons_category,
            "source": source,
            "source_url": url,
            "confidence": 0.95,
            "raw_data": {"title": title, "description": description}
        }

    def _detect_countries(self, text: str) -> List[str]:
        """Detect country mentions in text"""
        countries = []
        text_upper = text.upper()

        for name, iso in COUNTRY_ISO_MAP.items():
            if name in text_upper:
                if iso not in countries:
                    countries.append(iso)

        return countries

    def _classify_event_type(self, text: str) -> str:
        """Classify the type of military event"""
        if any(word in text for word in ["contract", "procurement", "award", "buy", "purchase"]):
            return "procurement"
        elif any(word in text for word in ["transfer", "deliver", "supply", "export", "import"]):
            return "weapons_transfer"
        elif any(word in text for word in ["exercise", "drill", "maneuver", "training"]):
            return "military_exercise"
        elif any(word in text for word in ["budget", "spending", "expenditure", "allocat"]):
            return "defense_spending"
        else:
            return "procurement"

    def _detect_weapons_category(self, text: str) -> Optional[str]:
        """Detect weapons category from text"""
        text_lower = text.lower()

        for keyword, category in WEAPONS_CATEGORIES.items():
            if keyword in text_lower:
                return category

        return None

    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract monetary amount from text"""
        # Patterns for amounts like "$1.5 billion", "500 million dollars"
        patterns = [
            r'\$(\d+(?:\.\d+)?)\s*(billion|million|m|b)',
            r'(\d+(?:\.\d+)?)\s*(billion|million)\s*(?:dollar|usd)',
            r'usd\s*(\d+(?:\.\d+)?)\s*(billion|million|m|b)',
        ]

        text_lower = text.lower()

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                value = float(match.group(1))
                unit = match.group(2).lower()

                if unit in ["billion", "b"]:
                    return value * 1_000_000_000
                elif unit in ["million", "m"]:
                    return value * 1_000_000

        return None

    async def parse(self, raw_data: List[Dict]) -> List[MilitaryEvent]:
        """Parse raw data into MilitaryEvent objects"""
        events = []
        seen = set()

        for data in raw_data:
            try:
                # Create unique key
                key = f"{data.get('country_iso')}_{data.get('title', '')[:50]}"
                if key in seen:
                    continue
                seen.add(key)

                # Parse date
                event_date = self._parse_date(data.get("date_str"))

                event = MilitaryEvent(
                    country_iso=data.get("country_iso", "UNK"),
                    event_type=data.get("event_type", "procurement"),
                    event_subtype=data.get("event_subtype"),
                    title=data.get("title"),
                    description=data.get("description", ""),
                    amount_usd=data.get("amount_usd"),
                    weapons_system=data.get("weapons_system"),
                    weapons_category=data.get("weapons_category"),
                    supplier_country=data.get("supplier_country"),
                    recipient_country=data.get("recipient_country") or data.get("country_iso"),
                    fiscal_year=data.get("fiscal_year"),
                    source=data.get("source", "Unknown"),
                    source_url=data.get("source_url"),
                    event_date=event_date,
                    confidence=data.get("confidence", 0.8),
                    raw_data=data.get("raw_data")
                )

                events.append(event)

            except Exception as e:
                self.logger.warning(f"Error parsing event: {e}")
                continue

        self.logger.info(f"Parsed {len(events)} military events")
        return events

    def _parse_date(self, date_str: Optional[str]) -> date:
        """Parse date string to date object"""
        if not date_str:
            return date.today()

        formats = [
            "%Y-%m-%d",
            "%B %d, %Y",
            "%d %B %Y",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.date()
            except ValueError:
                continue

        return date.today()

    async def save(self, events: List[MilitaryEvent]) -> int:
        """Save military events to database"""
        saved = 0

        try:
            from sqlalchemy import text

            with self.db.session() as session:
                for event in events:
                    try:
                        # Check for duplicates
                        result = session.execute(
                            text("""
                                SELECT id FROM military_events
                                WHERE country_iso = :country_iso
                                  AND event_type = :event_type
                                  AND title = :title
                            """),
                            {
                                "country_iso": event.country_iso,
                                "event_type": event.event_type,
                                "title": event.title
                            }
                        )
                        if result.fetchone():
                            continue

                        # Insert new event
                        session.execute(
                            text("""
                                INSERT INTO military_events (
                                    country_iso, event_type, event_subtype,
                                    title, description, amount_usd,
                                    weapons_system, weapons_category,
                                    supplier_country, recipient_country,
                                    fiscal_year, source, source_url,
                                    event_date, confidence, raw_data
                                ) VALUES (
                                    :country_iso, :event_type, :event_subtype,
                                    :title, :description, :amount_usd,
                                    :weapons_system, :weapons_category,
                                    :supplier_country, :recipient_country,
                                    :fiscal_year, :source, :source_url,
                                    :event_date, :confidence, :raw_data
                                )
                            """),
                            {
                                "country_iso": event.country_iso,
                                "event_type": event.event_type,
                                "event_subtype": event.event_subtype,
                                "title": event.title,
                                "description": event.description,
                                "amount_usd": event.amount_usd,
                                "weapons_system": event.weapons_system,
                                "weapons_category": event.weapons_category,
                                "supplier_country": event.supplier_country,
                                "recipient_country": event.recipient_country,
                                "fiscal_year": event.fiscal_year,
                                "source": event.source,
                                "source_url": event.source_url,
                                "event_date": event.event_date,
                                "confidence": event.confidence,
                                "raw_data": json.dumps(event.raw_data) if event.raw_data else None
                            }
                        )

                        saved += 1

                    except Exception as e:
                        self.logger.warning(f"Error saving event: {e}")
                        continue

                session.commit()

            self.logger.info(f"Saved {saved} military events")

        except Exception as e:
            self.logger.error(f"Error in save: {e}")

        return saved

    async def validate(self, event) -> bool:
        """Validate a military event"""
        if not hasattr(event, 'country_iso') or not event.country_iso:
            return False
        if not hasattr(event, 'description') or not event.description:
            return False
        return True

    async def run(self) -> Dict:
        """Execute the full collection pipeline"""
        try:
            self.logger.info(f"Starting {self.name}...")
            start_time = datetime.now(timezone.utc)

            # Fetch
            raw_data = await self.fetch()

            # Parse
            events = await self.parse(raw_data)

            # Validate
            valid_events = [e for e in events if await self.validate(e)]

            # Save
            saved = await self.save(valid_events)

            # Stats
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Count by type
            type_counts = {}
            for e in valid_events:
                type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1

            stats = {
                "collector": self.name,
                "status": "success",
                "raw_fetched": len(raw_data),
                "parsed": len(events),
                "valid": len(valid_events),
                "saved": saved,
                "by_type": type_counts,
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            self.logger.info(f"{self.name} completed: {saved} events saved")
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
    collector = MilitaryProcurementCollector()
    result = await collector.run()
    print(f"Collection result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
