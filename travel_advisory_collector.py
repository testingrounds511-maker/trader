"""
TITANIUM V2 - Travel Advisory Collector
Collects travel advisories from US State Department RSS.

Advisory levels and CII impact:
  1: Exercise Normal Precautions   -> CII +2,  severity 2
  2: Exercise Increased Caution    -> CII +5,  severity 4
  3: Reconsider Travel             -> CII +10, severity 6
  4: Do Not Travel                 -> CII +15, severity 8, CII floor 60
"""

import re
import hashlib
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import text

from collectors.base import BaseCollector
from core.database import Database
from core.logger import get_logger
from models.event import Event

logger = get_logger(__name__)

ADVISORY_LEVELS = {
    1: {"label": "Exercise Normal Precautions", "cii_boost": 2, "severity": 2},
    2: {"label": "Exercise Increased Caution", "cii_boost": 5, "severity": 4},
    3: {"label": "Reconsider Travel", "cii_boost": 10, "severity": 6},
    4: {"label": "Do Not Travel", "cii_boost": 15, "severity": 8, "cii_floor": 60},
}

US_STATE_DEPT_URL = "https://travel.state.gov/_res/rss/TAsTWs.xml"

COUNTRY_NAME_FIXES = {
    "Burma (Myanmar)": "MMR", "Korea, North": "PRK", "Korea, South": "KOR",
    "Congo, Democratic Republic of the": "COD", "Congo, Republic of the": "COG",
    "Czechia": "CZE", "Czech Republic": "CZE", "Timor-Leste": "TLS",
    "Brunei": "BRN", "Laos": "LAO", "Palestinian Territories": "PSE",
    "The Bahamas": "BHS", "The Gambia": "GMB", "Trinidad and Tobago": "TTO",
    "United Kingdom": "GBR", "United States": "USA",
}


class TravelAdvisoryCollector(BaseCollector):
    def __init__(self, config=None):
        super().__init__(config)
        self.name = "TravelAdvisoryCollector"
        self._country_cache: Dict[str, str] = {}

    async def fetch(self) -> List[Dict]:
        raw = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    US_STATE_DEPT_URL,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={"User-Agent": "TITANIUM-V2/2.0"}
                ) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        root = ET.fromstring(content)
                        for item in root.findall(".//item"):
                            raw.append({
                                "title": item.findtext("title", ""),
                                "description": item.findtext("description", ""),
                                "link": item.findtext("link", ""),
                                "pub_date": item.findtext("pubDate", ""),
                                "source": "us_state_dept",
                            })
            self.logger.info(f"US State Dept: {len(raw)} advisories fetched")
        except Exception as e:
            self.logger.warning(f"US State Dept fetch failed: {e}")
        return raw

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        events = []
        for item in raw_data:
            try:
                title = item.get("title", "")
                level_match = re.search(r'Level\s+(\d)', title)
                level = int(level_match.group(1)) if level_match else 1

                country_match = re.match(r'^(.+?)\s*[-\u2013]\s*(?:Level|Travel)', title)
                country_name = country_match.group(1).strip() if country_match else title.split("-")[0].strip()

                country_iso = self._resolve_iso(country_name)
                if not country_iso:
                    continue

                try:
                    published = datetime.strptime(item.get("pub_date", ""), "%a, %d %b %Y %H:%M:%S %z")
                except (ValueError, TypeError):
                    published = datetime.now(timezone.utc)

                level_info = ADVISORY_LEVELS.get(level, ADVISORY_LEVELS[1])
                eid = hashlib.sha256(
                    f"advisory_us_{country_iso}_{level}".encode()
                ).hexdigest()[:32]

                events.append(Event(
                    id=f"tadv_{eid}",
                    title=title,
                    description=(item.get("description") or "")[:2000],
                    source_url=item.get("link", ""),
                    source_name="travel_advisory_us_state_dept",
                    event_date=published,
                    published_date=published,
                    country=country_name,
                    country_iso=country_iso,
                    event_type="travel_advisory",
                    category="security",
                    severity=level_info["severity"],
                    relevance_score=0.7 + (level * 0.075),
                    tags={"advisory_level": level, "source": "us_state_dept"},
                    raw_data={
                        "country": country_name, "country_iso": country_iso,
                        "level": level, "level_label": level_info["label"],
                        "cii_boost": level_info["cii_boost"],
                        "cii_floor": level_info.get("cii_floor"),
                    },
                ))
            except Exception as e:
                self.logger.warning(f"Failed to parse advisory: {e}")
        return events

    def _resolve_iso(self, name: str) -> Optional[str]:
        if name in COUNTRY_NAME_FIXES:
            return COUNTRY_NAME_FIXES[name]
        if name in self._country_cache:
            return self._country_cache[name]
        with self.db.get_session() as session:
            row = session.execute(
                text("SELECT iso_code FROM countries WHERE LOWER(name) = LOWER(:n)"),
                {"n": name}
            ).fetchone()
            if not row:
                row = session.execute(
                    text("SELECT iso_code FROM countries WHERE LOWER(name) LIKE :p"),
                    {"p": f"%{name.lower()}%"}
                ).fetchone()
            if row:
                self._country_cache[name] = row[0]
                return row[0]
        return None

    def get_advisory_cii_adjustments(self) -> Dict[str, dict]:
        adjustments = {}
        with self.db.get_session() as session:
            result = session.execute(text('''
                SELECT country_iso, MAX((raw_data->>'advisory_level')::int) as max_level
                FROM events
                WHERE source_name LIKE 'travel_advisory_%' AND is_active = true
                  AND event_date >= NOW() - INTERVAL '30 days' AND country_iso IS NOT NULL
                GROUP BY country_iso
            '''))
            for row in result.mappings():
                info = ADVISORY_LEVELS.get(row["max_level"], ADVISORY_LEVELS[1])
                adjustments[row["country_iso"]] = {
                    "level": row["max_level"],
                    "cii_boost": info["cii_boost"],
                    "cii_floor": info.get("cii_floor"),
                }
        return adjustments
