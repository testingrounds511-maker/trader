"""
TITANIUM V2 - Ship/Maritime AIS Collector
Tracks naval and strategic maritime activity via open AIS data.

Intelligence value:
- Naval fleet movements near chokepoints = power projection
- Unusual cargo patterns = sanctions evasion / smuggling
- Dark ships (AIS off) in conflict zones = illicit activity
- Military vessels near disputed waters = escalation signal

Chokepoints monitored:
- Strait of Hormuz (oil), Suez Canal, Bab el-Mandeb (Yemen/Red Sea)
- Taiwan Strait, Malacca Strait, South China Sea
- Turkish Straits (Bosphorus/Dardanelles), Gibraltar
- GIUK Gap (North Atlantic NATO), Baltic Straits
"""

import hashlib
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import aiohttp

from collectors.base import BaseCollector
from core.logger import get_logger
from models.event import Event

logger = get_logger(__name__)

# Free AIS data sources
# Option 1: AISHub (community sharing, requires registration)
# Option 2: MarineTraffic API (paid, but has free academic tier)
# Option 3: UN Global Platform AIS (limited but free)
# We use a generic approach that can plug into any source

AISHUB_URL = "https://data.aishub.net/ws.php"

# Strategic maritime chokepoints (lat, lon, radius_km, label, daily_transit_volume)
CHOKEPOINTS = [
    (26.6, 56.2, 80, "Strait of Hormuz", 21_000_000),
    (30.5, 32.3, 50, "Suez Canal", 12_000_000),
    (12.6, 43.3, 80, "Bab el-Mandeb", 6_000_000),
    (24.5, 118.5, 100, "Taiwan Strait", 5_000_000),
    (1.3, 103.8, 80, "Malacca Strait", 16_000_000),
    (36.1, -5.4, 50, "Strait of Gibraltar", 4_000_000),
    (41.1, 29.0, 30, "Bosphorus", 3_000_000),
    (55.7, 12.6, 60, "Danish Straits / Baltic", 2_000_000),
    (63.0, -20.0, 200, "GIUK Gap", 0),
    (10.0, 112.0, 150, "South China Sea / Spratly", 0),
    (8.0, 50.0, 150, "Gulf of Aden", 0),
    (-4.0, 40.0, 100, "Mozambique Channel", 0),
]

# Ship type codes that indicate military/government
MILITARY_SHIP_TYPES = {
    35: "Military",
    55: "Law Enforcement",
    51: "Search and Rescue",
    52: "Tug (potential naval support)",
    58: "Medical Transport",
}

# Known naval vessel MMSI prefixes by nation (first 3 digits = MID)
NAVAL_MMSI_PREFIXES = {
    "338": "USA", "303": "USA",
    "273": "Russia",
    "412": "China", "413": "China",
    "431": "Japan",
    "440": "South Korea",
    "441": "South Korea",
    "230": "Finland",
    "226": "France", "227": "France",
    "211": "Germany",
    "232": "UK", "233": "UK", "234": "UK", "235": "UK",
    "247": "Italy",
    "224": "Spain", "225": "Spain",
    "351": "India",
    "525": "Indonesia",
    "548": "Philippines",
    "564": "Singapore",
    "574": "Vietnam",
    "503": "Australia",
}


class ShipTrackingCollector(BaseCollector):
    def __init__(self, config=None, aishub_key: str = None):
        super().__init__(config)
        self.name = "ShipTrackingCollector"
        self.api_key = aishub_key or getattr(self.config, "AISHUB_API_KEY", None)

    async def fetch(self) -> List[Dict]:
        raw = []
        if not self.api_key:
            self.logger.info("No AISHub API key, using chokepoint scan approach")
            return await self._fetch_chokepoint_scan()

        try:
            for cp_lat, cp_lon, radius_km, label, _ in CHOKEPOINTS:
                params = {
                    "username": self.api_key,
                    "format": "1",
                    "output": "json",
                    "compress": "0",
                    "latmin": cp_lat - (radius_km / 111),
                    "latmax": cp_lat + (radius_km / 111),
                    "lonmin": cp_lon - (radius_km / 111),
                    "lonmax": cp_lon + (radius_km / 111),
                }
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        AISHUB_URL, params=params,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for ship in data if isinstance(data, list) else data.get("data", []):
                                ship["chokepoint"] = label
                                raw.append(ship)
            self.logger.info(f"AIS: {len(raw)} vessels near chokepoints")
        except Exception as e:
            self.logger.warning(f"AIS fetch failed: {e}")
        return raw

    async def _fetch_chokepoint_scan(self) -> List[Dict]:
        """Fallback: generate intelligence events from recent maritime news + DB."""
        raw = []
        try:
            # Check our own DB for maritime-related events near chokepoints
            from sqlalchemy import text as sql_text
            with self.db.get_session() as session:
                result = session.execute(sql_text(
                    "SELECT id, title, description, latitude, longitude, country_iso, severity, event_date "
                    "FROM events WHERE is_active = true "
                    "AND event_date >= NOW() - INTERVAL '48 hours' "
                    "AND (event_type IN ('military_movement', 'naval', 'maritime', 'piracy', 'sanctions') "
                    "     OR LOWER(title) LIKE '%naval%' OR LOWER(title) LIKE '%ship%' "
                    "     OR LOWER(title) LIKE '%maritime%' OR LOWER(title) LIKE '%fleet%' "
                    "     OR LOWER(title) LIKE '%strait%' OR LOWER(title) LIKE '%blockade%' "
                    "     OR LOWER(title) LIKE '%carrier%' OR LOWER(title) LIKE '%destroyer%' "
                    "     OR LOWER(title) LIKE '%submarine%' OR LOWER(title) LIKE '%navy%') "
                    "ORDER BY event_date DESC LIMIT 50"
                ))
                for row in result.mappings():
                    raw.append({
                        "source": "db_maritime_scan",
                        "event_id": row["id"],
                        "title": row["title"],
                        "description": row.get("description"),
                        "latitude": row.get("latitude"),
                        "longitude": row.get("longitude"),
                        "country_iso": row.get("country_iso"),
                        "severity": row.get("severity"),
                        "event_date": row["event_date"].isoformat() if row.get("event_date") else None,
                    })
            self.logger.info(f"Maritime DB scan: {len(raw)} maritime events found")
        except Exception as e:
            self.logger.warning(f"Maritime DB scan failed: {e}")
        return raw

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        events = []
        now = datetime.now(timezone.utc)

        # If data came from DB scan (fallback mode), create chokepoint summary events
        db_events = [r for r in raw_data if r.get("source") == "db_maritime_scan"]
        ais_events = [r for r in raw_data if r.get("source") != "db_maritime_scan"]

        # Process AIS data (when API key available)
        if ais_events:
            events.extend(self._parse_ais_data(ais_events, now))

        # Process DB scan results into chokepoint intelligence
        if db_events:
            events.extend(self._parse_db_maritime(db_events, now))

        return events

    def _parse_ais_data(self, ais_data, now) -> List[Event]:
        events = []
        chokepoint_groups: Dict[str, List[Dict]] = defaultdict(list)

        for ship in ais_data:
            cp = ship.get("chokepoint", "Unknown")
            ship_type = ship.get("type", 0)
            mmsi = str(ship.get("mmsi", ""))

            is_military = (
                ship_type in MILITARY_SHIP_TYPES
                or any(mmsi.startswith(p) for p in NAVAL_MMSI_PREFIXES)
            )

            if is_military:
                chokepoint_groups[cp].append(ship)

        for cp, ships in chokepoint_groups.items():
            if not ships:
                continue

            nations = set()
            for s in ships:
                mmsi = str(s.get("mmsi", ""))
                for prefix, nation in NAVAL_MMSI_PREFIXES.items():
                    if mmsi.startswith(prefix):
                        nations.add(nation)
                        break

            severity = 5
            if len(ships) >= 5:
                severity = 8
            elif len(ships) >= 3:
                severity = 7
            elif len(nations) >= 2:
                severity = 6

            eid = hashlib.sha256(
                f"ais_{cp}_{now.strftime('%Y%m%d%H')}".encode()
            ).hexdigest()[:32]

            events.append(Event(
                id=f"ais_{eid}",
                title=f"Naval Activity: {len(ships)} military vessels at {cp}",
                description=(
                    f"{len(ships)} military/government vessels detected near {cp}. "
                    f"Nations: {', '.join(sorted(nations)) or 'Unknown'}. "
                    f"This chokepoint is strategically critical for global trade."
                ),
                source_url="https://www.aishub.net",
                source_name="ship_tracking_ais",
                event_date=now,
                published_date=now,
                event_type="naval_movement",
                category="military",
                severity=severity,
                relevance_score=min(1.0, 0.5 + len(ships) * 0.05),
                tags={
                    "vessel_count": len(ships),
                    "nations": sorted(nations),
                    "chokepoint": cp,
                },
                raw_data={"vessels": ships[:20]},
            ))

        return events

    def _parse_db_maritime(self, db_events, now) -> List[Event]:
        events = []
        # Check which chokepoints have nearby maritime activity
        cp_activity: Dict[str, List[Dict]] = defaultdict(list)

        for ev in db_events:
            lat = ev.get("latitude")
            lon = ev.get("longitude")
            if lat and lon:
                cp = self._nearest_chokepoint(lat, lon)
                if cp:
                    cp_activity[cp].append(ev)

        for cp, activity in cp_activity.items():
            if len(activity) < 2:
                continue

            max_sev = max((a.get("severity") or 3) for a in activity)
            eid = hashlib.sha256(
                f"maritime_intel_{cp}_{now.strftime('%Y%m%d%H')}".encode()
            ).hexdigest()[:32]

            titles = [a.get("title", "") for a in activity[:5]]

            events.append(Event(
                id=f"mar_{eid}",
                title=f"Maritime Intelligence: Activity near {cp}",
                description=(
                    f"{len(activity)} maritime-related events detected near {cp} "
                    f"in the last 48 hours. Key events: {'; '.join(titles[:3])}."
                ),
                source_url="",
                source_name="ship_tracking_intel",
                event_date=now,
                published_date=now,
                event_type="maritime_intelligence",
                category="military",
                severity=min(10, max_sev + 1),
                relevance_score=min(1.0, 0.4 + len(activity) * 0.1),
                tags={
                    "chokepoint": cp,
                    "event_count": len(activity),
                    "source_events": [a.get("event_id") for a in activity[:10]],
                },
                raw_data={"source_events": activity[:10]},
            ))

        return events

    def _nearest_chokepoint(self, lat, lon, max_km=200):
        best = None
        best_dist = max_km
        for cp_lat, cp_lon, radius_km, label, _ in CHOKEPOINTS:
            dist = ((lat - cp_lat) ** 2 + (lon - cp_lon) ** 2) ** 0.5 * 111
            if dist < best_dist:
                best_dist = dist
                best = label
        return best
