"""
TITANIUM V2 - USGS Earthquake Collector
Real-time seismic data from USGS Earthquake Hazards API.

Geopolitical relevance:
- Earthquakes destabilize fragile states (Haiti, Nepal, Turkey, Syria)
- Trigger humanitarian crises, displacement, resource competition
- Near nuclear/military facilities = national security concern
- Tsunami risk = coastal population displacement

API: https://earthquake.usgs.gov/fdsnws/event/1/
Free, no auth required, GeoJSON format, updates every minute.
"""

import hashlib
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta

import aiohttp
from sqlalchemy import text

from collectors.base import BaseCollector
from core.logger import get_logger
from models.event import Event

logger = get_logger(__name__)

USGS_API = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# Severity mapping: USGS magnitude -> TITANIUM severity (1-10)
MAG_SEVERITY = [
    (7.0, 10, "catastrophic"),
    (6.0, 8, "severe"),
    (5.0, 6, "strong"),
    (4.0, 4, "moderate"),
    (3.0, 3, "light"),
    (0.0, 2, "minor"),
]

# Strategic locations near military/nuclear facilities (lat, lon, radius_km, label)
STRATEGIC_ZONES = [
    (37.2, 127.0, 200, "Korean Peninsula"),
    (36.2, 59.6, 300, "Iran Nuclear Belt"),
    (33.5, 36.3, 200, "Levant/Syria"),
    (39.9, 32.9, 300, "Turkey/Anatolia"),
    (28.6, 77.2, 300, "India-Pakistan Border"),
    (35.7, 139.7, 300, "Japan Pacific Ring"),
    (14.6, 121.0, 300, "Philippines Ring of Fire"),
    (-6.2, 106.8, 300, "Indonesia Seismic"),
    (38.9, 125.8, 200, "North Korea Nuclear"),
    (51.4, 30.1, 200, "Chernobyl/Ukraine"),
]


class USGSEarthquakeCollector(BaseCollector):
    def __init__(self, config=None, min_magnitude: float = 4.0,
                 lookback_hours: int = 24):
        super().__init__(config)
        self.name = "USGSEarthquakeCollector"
        self.min_magnitude = min_magnitude
        self.lookback_hours = lookback_hours
        self._country_cache: Dict[str, str] = {}

    async def fetch(self) -> List[Dict]:
        raw = []
        start = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        params = {
            "format": "geojson",
            "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "minmagnitude": self.min_magnitude,
            "orderby": "magnitude",
            "limit": 100,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    USGS_API, params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={"User-Agent": "TITANIUM-V2/2.0"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        features = data.get("features", [])
                        for f in features:
                            props = f.get("properties", {})
                            geom = f.get("geometry", {})
                            coords = geom.get("coordinates", [0, 0, 0])
                            raw.append({
                                "usgs_id": f.get("id", ""),
                                "title": props.get("title", ""),
                                "place": props.get("place", ""),
                                "magnitude": props.get("mag", 0),
                                "mag_type": props.get("magType", ""),
                                "time": props.get("time", 0),
                                "updated": props.get("updated", 0),
                                "url": props.get("url", ""),
                                "detail_url": props.get("detail", ""),
                                "felt": props.get("felt"),
                                "tsunami": props.get("tsunami", 0),
                                "significance": props.get("sig", 0),
                                "alert": props.get("alert"),
                                "status": props.get("status", ""),
                                "longitude": coords[0] if len(coords) > 0 else None,
                                "latitude": coords[1] if len(coords) > 1 else None,
                                "depth_km": coords[2] if len(coords) > 2 else None,
                            })
                    else:
                        self.logger.warning(f"USGS API returned {resp.status}")
            self.logger.info(f"USGS: {len(raw)} earthquakes fetched (M>={self.min_magnitude})")
        except Exception as e:
            self.logger.warning(f"USGS fetch failed: {e}")
        return raw

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        events = []
        for eq in raw_data:
            try:
                mag = float(eq.get("magnitude") or 0)
                severity, sev_label = self._mag_to_severity(mag)

                ts_ms = eq.get("time", 0)
                event_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else datetime.now(timezone.utc)

                lat = eq.get("latitude")
                lon = eq.get("longitude")
                depth = eq.get("depth_km", 0)

                place = eq.get("place") or "Unknown"
                country_iso = self._resolve_country(lat, lon, place)
                country_name = self._country_name_from_place(place)

                strategic = self._check_strategic(lat, lon)
                tsunami_risk = bool(eq.get("tsunami", 0))

                title = f"M{mag:.1f} Earthquake - {place}"
                if tsunami_risk:
                    title = f"[TSUNAMI WARNING] {title}"
                if strategic:
                    title = f"[STRATEGIC] {title}"

                relevance = self._calc_relevance(mag, strategic, tsunami_risk, eq.get("significance", 0))

                eid = hashlib.sha256(
                    f"usgs_{eq.get('usgs_id', '')}".encode()
                ).hexdigest()[:32]

                desc_parts = [
                    f"Magnitude {mag:.1f} ({eq.get('mag_type', 'ml')}) earthquake at depth {depth:.1f}km.",
                    f"Location: {place}.",
                ]
                if eq.get("felt"):
                    desc_parts.append(f"Felt by {eq['felt']} people.")
                if tsunami_risk:
                    desc_parts.append("TSUNAMI WARNING ISSUED.")
                if strategic:
                    desc_parts.append(f"Near strategic zone: {strategic}.")
                if eq.get("alert"):
                    desc_parts.append(f"PAGER alert level: {eq['alert'].upper()}.")

                events.append(Event(
                    id=f"usgs_{eid}",
                    title=title,
                    description=" ".join(desc_parts),
                    source_url=eq.get("url", ""),
                    source_name="usgs_earthquake",
                    event_date=event_time,
                    published_date=event_time,
                    country=country_name,
                    country_iso=country_iso,
                    latitude=lat,
                    longitude=lon,
                    event_type="natural_disaster",
                    category="seismic",
                    severity=severity,
                    relevance_score=relevance,
                    tags={
                        "magnitude": mag,
                        "mag_type": eq.get("mag_type"),
                        "depth_km": depth,
                        "tsunami": tsunami_risk,
                        "strategic_zone": strategic,
                        "pager_alert": eq.get("alert"),
                        "felt_reports": eq.get("felt"),
                        "significance": eq.get("significance"),
                    },
                    raw_data=eq,
                ))
            except Exception as e:
                self.logger.warning(f"Failed to parse earthquake: {e}")
        return events

    def _mag_to_severity(self, mag):
        for threshold, sev, label in MAG_SEVERITY:
            if mag >= threshold:
                return sev, label
        return 1, "micro"

    def _calc_relevance(self, mag, strategic, tsunami, significance):
        base = min(0.5, mag / 14.0)
        if strategic:
            base += 0.2
        if tsunami:
            base += 0.2
        if significance and significance > 500:
            base += 0.1
        return min(1.0, max(0.1, base))

    def _check_strategic(self, lat, lon):
        if lat is None or lon is None:
            return None
        for zlat, zlon, radius_km, label in STRATEGIC_ZONES:
            dist = ((lat - zlat) ** 2 + (lon - zlon) ** 2) ** 0.5 * 111
            if dist <= radius_km:
                return label
        return None

    def _country_name_from_place(self, place):
        if "," in place:
            return place.split(",")[-1].strip()
        return place

    def _resolve_country(self, lat, lon, place):
        country_part = self._country_name_from_place(place)
        if country_part in self._country_cache:
            return self._country_cache[country_part]
        try:
            with self.db.get_session() as session:
                row = session.execute(
                    text("SELECT iso_code FROM countries WHERE LOWER(name) = LOWER(:n)"),
                    {"n": country_part}
                ).fetchone()
                if not row:
                    row = session.execute(
                        text("SELECT iso_code FROM countries WHERE LOWER(name) LIKE :p"),
                        {"p": f"%{country_part.lower()}%"}
                    ).fetchone()
                if row:
                    self._country_cache[country_part] = row[0]
                    return row[0]
        except Exception:
            pass
        return None
