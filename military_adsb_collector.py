"""
TITANIUM V2 - Military ADSB Collector
Tracks military/government aircraft via open ADS-B data.

Intelligence value:
- Unusual military flight patterns = deployment/escalation signal
- Reconnaissance aircraft near borders = tension indicator
- Tanker/transport surges = logistics buildup
- VIP/government jets = diplomatic movements

Data sources:
- ADS-B Exchange API (community-funded, unfiltered)
- OpenSky Network (academic, free tier)
Both provide real-time aircraft positions with ICAO hex codes.

Military aircraft identified by:
1. ICAO hex ranges assigned to military (per country)
2. Known military callsign prefixes (RCH, JAKE, EVAC, etc.)
3. Aircraft type codes (C17, KC135, E3, P8, RC135, etc.)
"""

import hashlib
from typing import List, Dict, Optional, Set
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import aiohttp

from collectors.base import BaseCollector
from core.logger import get_logger
from models.event import Event

logger = get_logger(__name__)

# OpenSky free API (no auth needed for state vectors)
OPENSKY_URL = "https://opensky-network.org/api/states/all"

# Known military callsign prefixes
MILITARY_CALLSIGNS = {
    "RCH", "JAKE", "EVAC", "REACH", "MOOSE", "DUKE", "COBRA",
    "DOOM", "HAWK", "VALOR", "TOPCAT", "GORDO", "TEAL", "IRON",
    "NATO", "FORTE", "HOMER", "LAGR", "SAM", "EXEC", "SPAR",
    "KNIFE", "ANGRY", "SKULL", "VIPER", "TITAN", "ATLAS",
    "NCHO", "ROCKY", "POLO", "TROJAN", "VIKING", "REAPER",
    "CNV", "RRR", "IAM", "SHF", "MMF", "CFC",
}

# Military aircraft type designators
MILITARY_TYPES = {
    "C17", "C5", "C130", "C5M", "KC135", "KC10", "KC46",
    "E3", "E6", "E8", "RC135", "P8", "P3", "EP3",
    "B52", "B1", "B2", "F15", "F16", "F22", "F35",
    "A10", "V22", "MV22", "CV22", "C40", "C32", "C37",
    "C2", "E2", "EA18", "C12", "UC35", "T38", "T6",
    "H60", "H53", "H47", "AH64", "CH47", "UH60",
    "MQ9", "RQ4", "MQ4", "RQ170",
    "A400", "C295", "CN235", "IL76", "AN124", "AN225",
    "TU95", "TU160", "SU27", "SU35", "MIG31",
    "J20", "Y20", "H6",
    "EUFI", "RFAL", "TORN",
}

# ICAO hex ranges for military (partial, major nations)
MILITARY_ICAO_RANGES = [
    ("AE0000", "AE ffff", "USA"),
    ("AF0000", "AFffff", "USA"),
    ("3F0000", "3Fffff", "Germany"),
    ("43C000", "43Cfff", "UK"),
    ("3A0000", "3Affff", "France"),
    ("300000", "33ffff", "Italy"),
    ("340000", "37ffff", "Spain"),
    ("780000", "7Fffff", "China"),
    ("100000", "1Fffff", "Russia"),
]

# Geopolitical hotspot bounding boxes (min_lat, max_lat, min_lon, max_lon, label)
HOTSPOTS = [
    (33.0, 42.0, 25.0, 45.0, "Eastern Mediterranean / Middle East"),
    (48.0, 56.0, 22.0, 40.0, "Ukraine / Eastern Europe"),
    (24.0, 42.0, 44.0, 64.0, "Persian Gulf / Iran"),
    (33.0, 43.0, 124.0, 132.0, "Korean Peninsula"),
    (20.0, 28.0, 118.0, 128.0, "Taiwan Strait / South China Sea"),
    (60.0, 72.0, 10.0, 45.0, "Arctic / Nordic"),
    (54.0, 60.0, 18.0, 28.0, "Baltic Region"),
    (10.0, 20.0, 42.0, 52.0, "Horn of Africa / Yemen"),
]


class MilitaryADSBCollector(BaseCollector):
    def __init__(self, config=None, lookback_minutes: int = 30):
        super().__init__(config)
        self.name = "MilitaryADSBCollector"
        self.lookback_minutes = lookback_minutes

    async def fetch(self) -> List[Dict]:
        raw = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    OPENSKY_URL,
                    timeout=aiohttp.ClientTimeout(total=60),
                    headers={"User-Agent": "TITANIUM-V2/2.0"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        states = data.get("states", [])
                        now_ts = data.get("time", 0)
                        for s in states:
                            if len(s) < 17:
                                continue
                            icao = (s[0] or "").strip()
                            callsign = (s[1] or "").strip()
                            origin = (s[2] or "").strip()
                            lat = s[6]
                            lon = s[5]
                            alt = s[7] or s[13]
                            velocity = s[9]
                            on_ground = s[8]

                            if not self._is_military(icao, callsign):
                                continue

                            raw.append({
                                "icao24": icao,
                                "callsign": callsign,
                                "origin_country": origin,
                                "latitude": lat,
                                "longitude": lon,
                                "altitude_m": alt,
                                "velocity_ms": velocity,
                                "on_ground": on_ground,
                                "heading": s[10],
                                "vertical_rate": s[11],
                                "squawk": s[14],
                                "timestamp": now_ts,
                            })
                    elif resp.status == 429:
                        self.logger.warning("OpenSky rate limited, try again later")
                    else:
                        self.logger.warning(f"OpenSky API returned {resp.status}")
            self.logger.info(f"ADSB: {len(raw)} military aircraft detected")
        except Exception as e:
            self.logger.warning(f"ADSB fetch failed: {e}")
        return raw

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        if not raw_data:
            return []

        # Group by hotspot region for aggregated events
        hotspot_groups: Dict[str, List[Dict]] = defaultdict(list)
        notable_aircraft = []

        for ac in raw_data:
            lat = ac.get("latitude")
            lon = ac.get("longitude")
            hotspot = self._check_hotspot(lat, lon)

            if hotspot:
                hotspot_groups[hotspot].append(ac)

            # Flag high-interest individual aircraft
            callsign = ac.get("callsign", "")
            if any(callsign.startswith(p) for p in ("FORTE", "HOMER", "LAGR", "SAM", "EXEC", "REAPER", "RCH")):
                notable_aircraft.append(ac)

        events = []
        now = datetime.now(timezone.utc)

        # Create aggregated hotspot events
        for hotspot, aircraft_list in hotspot_groups.items():
            if len(aircraft_list) < 2:
                continue

            countries = set(ac.get("origin_country", "Unknown") for ac in aircraft_list)
            callsigns = [ac.get("callsign", "?") for ac in aircraft_list if ac.get("callsign")]

            severity = self._hotspot_severity(len(aircraft_list), countries)
            eid = hashlib.sha256(
                f"adsb_hotspot_{hotspot}_{now.strftime('%Y%m%d%H')}".encode()
            ).hexdigest()[:32]

            avg_lat = sum(ac["latitude"] for ac in aircraft_list if ac.get("latitude")) / max(len(aircraft_list), 1)
            avg_lon = sum(ac["longitude"] for ac in aircraft_list if ac.get("longitude")) / max(len(aircraft_list), 1)

            events.append(Event(
                id=f"adsb_{eid}",
                title=f"Military Air Activity: {len(aircraft_list)} aircraft in {hotspot}",
                description=(
                    f"{len(aircraft_list)} military aircraft detected in {hotspot}. "
                    f"Origin countries: {', '.join(sorted(countries))}. "
                    f"Callsigns: {', '.join(callsigns[:10])}."
                ),
                source_url="https://opensky-network.org",
                source_name="military_adsb_opensky",
                event_date=now,
                published_date=now,
                latitude=avg_lat,
                longitude=avg_lon,
                event_type="military_movement",
                category="military",
                severity=severity,
                relevance_score=min(1.0, 0.4 + len(aircraft_list) * 0.05),
                tags={
                    "aircraft_count": len(aircraft_list),
                    "origin_countries": sorted(countries),
                    "hotspot": hotspot,
                    "callsigns": callsigns[:20],
                },
                raw_data={"aircraft": aircraft_list[:20]},
            ))

        # Create events for notable individual aircraft
        for ac in notable_aircraft:
            callsign = ac.get("callsign", "UNKNOWN")
            origin = ac.get("origin_country", "Unknown")
            hotspot = self._check_hotspot(ac.get("latitude"), ac.get("longitude"))

            eid = hashlib.sha256(
                f"adsb_notable_{callsign}_{now.strftime('%Y%m%d%H')}".encode()
            ).hexdigest()[:32]

            alt_ft = int((ac.get("altitude_m") or 0) * 3.281)
            speed_kts = int((ac.get("velocity_ms") or 0) * 1.944)

            desc = f"Notable military aircraft {callsign} ({origin}) detected"
            if hotspot:
                desc += f" in {hotspot}"
            desc += f". Altitude: {alt_ft}ft, Speed: {speed_kts}kts."

            events.append(Event(
                id=f"adsb_n_{eid}",
                title=f"Military Aircraft: {callsign} ({origin})",
                description=desc,
                source_url="https://opensky-network.org",
                source_name="military_adsb_opensky",
                event_date=now,
                published_date=now,
                latitude=ac.get("latitude"),
                longitude=ac.get("longitude"),
                event_type="military_movement",
                category="military",
                severity=6 if hotspot else 4,
                relevance_score=0.7 if hotspot else 0.5,
                tags={
                    "callsign": callsign,
                    "icao24": ac.get("icao24"),
                    "origin_country": origin,
                    "altitude_ft": alt_ft,
                    "speed_kts": speed_kts,
                    "hotspot": hotspot,
                },
                raw_data=ac,
            ))

        return events

    def _is_military(self, icao: str, callsign: str) -> bool:
        # Check callsign prefix
        cs_upper = callsign.upper()
        for prefix in MILITARY_CALLSIGNS:
            if cs_upper.startswith(prefix):
                return True

        # Check ICAO hex range
        try:
            icao_int = int(icao, 16)
            for range_start, range_end, country in MILITARY_ICAO_RANGES:
                start = int(range_start.replace(" ", ""), 16)
                end = int(range_end.replace(" ", ""), 16)
                if start <= icao_int <= end:
                    return True
        except (ValueError, TypeError):
            pass

        return False

    def _check_hotspot(self, lat, lon):
        if lat is None or lon is None:
            return None
        for min_lat, max_lat, min_lon, max_lon, label in HOTSPOTS:
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                return label
        return None

    def _hotspot_severity(self, count, countries):
        if count >= 10 or len(countries) >= 3:
            return 8
        elif count >= 5:
            return 6
        elif count >= 3:
            return 5
        return 4
