"""Real economic calendar + earnings dates.

Sources:
  - Forex Factory (nfs.faireconomy.media) — free, no auth, weekly JSON
  - Static known events for 2026 (FOMC, CPI, NFP, earnings)
  - Static quarterly earnings for key portfolio stocks

Replaces the mock EconomicCalendar from news.py.
"""

import logging
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger("phantom.calendar")

_HEADERS = {"User-Agent": "PhantomTrader/3.5"}
_TIMEOUT = 10

# ─── Forex Factory Economic Calendar ─────────────────────────────────────────

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

_IMPACT_MAP = {
    "High": "HIGH",
    "Medium": "MEDIUM",
    "Low": "LOW",
    "Holiday": "HOLIDAY",
}

_RELEVANT_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY"}


class ForexFactoryCalendar:
    """Fetches real economic events from Forex Factory's free JSON endpoint."""

    CACHE_TTL = 3600  # 1 hour

    def __init__(self):
        self._cache: list[dict] = []
        self._cache_time: float = 0
        self._lock = threading.Lock()

    def fetch_events(self) -> list[dict]:
        with self._lock:
            if self._cache and (time.time() - self._cache_time) < self.CACHE_TTL:
                return self._cache

        try:
            r = requests.get(FF_URL, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            raw = r.json()
            events = self._parse(raw)
        except Exception as e:
            logger.debug(f"Forex Factory fetch failed: {e}")
            events = self._cache or []

        with self._lock:
            self._cache = events
            self._cache_time = time.time()
        return events

    def _parse(self, raw: list) -> list[dict]:
        events = []
        for item in raw:
            country = item.get("country", "")
            if country not in _RELEVANT_CURRENCIES:
                continue
            impact = _IMPACT_MAP.get(item.get("impact", ""), "LOW")
            title = item.get("title", "Unknown Event")
            date_str = item.get("date", "")
            try:
                event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            events.append({
                "title": title,
                "time": event_time,
                "impact": impact,
                "country": country,
                "forecast": item.get("forecast", ""),
                "previous": item.get("previous", ""),
                "source": "forex_factory",
            })
        return sorted(events, key=lambda e: e["time"])


# ─── Static Known Events ─────────────────────────────────────────────────────

KNOWN_EVENTS_2026 = [
    {"date": "2026-01-29", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-02-07", "name": "US Non-Farm Payrolls (Jan)", "impact": "HIGH", "assets": ["SPY", "QQQ"]},
    {"date": "2026-02-12", "name": "US CPI (Jan)", "impact": "HIGH", "assets": ["SPY", "QQQ", "BTC/USD"]},
    {"date": "2026-02-26", "name": "NVIDIA Earnings (Q4 FY26)", "impact": "HIGH", "assets": ["NVDA", "SOXL"]},
    {"date": "2026-03-07", "name": "US Non-Farm Payrolls (Feb)", "impact": "HIGH", "assets": ["SPY", "QQQ"]},
    {"date": "2026-03-12", "name": "US CPI (Feb)", "impact": "HIGH", "assets": ["SPY", "QQQ", "BTC/USD"]},
    {"date": "2026-03-18", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-04-03", "name": "US Non-Farm Payrolls (Mar)", "impact": "HIGH", "assets": ["SPY", "QQQ"]},
    {"date": "2026-04-14", "name": "US CPI (Mar)", "impact": "HIGH", "assets": ["SPY", "QQQ", "BTC/USD"]},
    {"date": "2026-05-06", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-05-28", "name": "NVIDIA Earnings (Q1 FY27)", "impact": "HIGH", "assets": ["NVDA", "SOXL"]},
    {"date": "2026-06-17", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-07-29", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-08-26", "name": "NVIDIA Earnings (Q2 FY27)", "impact": "HIGH", "assets": ["NVDA", "SOXL"]},
    {"date": "2026-09-16", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-10-28", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
    {"date": "2026-11-25", "name": "NVIDIA Earnings (Q3 FY27)", "impact": "HIGH", "assets": ["NVDA", "SOXL"]},
    {"date": "2026-12-16", "name": "FOMC Rate Decision", "impact": "HIGH", "assets": ["ALL"]},
]


# ─── Earnings Calendar ────────────────────────────────────────────────────────

# Approximate quarterly earnings (month, day) for portfolio stocks.
EARNINGS_SCHEDULE = {
    "NVDA":  [(2, 26), (5, 28), (8, 26), (11, 25)],
    "AMD":   [(1, 28), (4, 29), (7, 29), (10, 28)],
    "TSLA":  [(1, 22), (4, 22), (7, 22), (10, 21)],
    "PLTR":  [(2, 4),  (5, 5),  (8, 4),  (11, 3)],
    "COIN":  [(2, 13), (5, 8),  (8, 1),  (11, 6)],
    "MSTR":  [(2, 4),  (4, 29), (8, 1),  (10, 29)],
    "TSM":   [(1, 16), (4, 17), (7, 17), (10, 16)],
    "SONY":  [(2, 4),  (5, 9),  (8, 1),  (10, 31)],
    "BABA":  [(2, 6),  (5, 15), (8, 15), (11, 14)],
    "PDD":   [(3, 20), (6, 12), (8, 26), (11, 21)],
    "MELI":  [(2, 20), (5, 7),  (8, 3),  (11, 5)],
    "NU":    [(2, 20), (5, 14), (8, 13), (11, 13)],
    "NVO":   [(2, 5),  (5, 2),  (8, 7),  (11, 6)],
    "SAP":   [(1, 23), (4, 22), (7, 21), (10, 20)],
}


class EarningsCalendar:
    """Tracks upcoming earnings dates for portfolio stocks."""

    def __init__(self):
        self._upcoming: list[dict] = []

    def _refresh(self):
        now = datetime.now(timezone.utc)
        year = now.year
        self._upcoming = []
        for symbol, dates in EARNINGS_SCHEDULE.items():
            for month, day in dates:
                for y in [year, year + 1]:
                    try:
                        dt = datetime(y, month, day, 21, 0, tzinfo=timezone.utc)
                        hours_until = (dt - now).total_seconds() / 3600
                        if -24 < hours_until < 720:
                            self._upcoming.append({
                                "symbol": symbol,
                                "title": f"{symbol} Earnings Report",
                                "time": dt,
                                "impact": "HIGH",
                                "hours_until": round(hours_until, 1),
                                "source": "earnings",
                            })
                    except ValueError:
                        continue
        self._upcoming.sort(key=lambda e: e.get("hours_until", 999))

    def get_upcoming(self, days: int = 14) -> list[dict]:
        self._refresh()
        max_hours = days * 24
        return [e for e in self._upcoming if 0 < e.get("hours_until", 999) < max_hours]

    def is_earnings_imminent(self, symbol: str, hours: int = 24) -> dict:
        self._refresh()
        for e in self._upcoming:
            if e["symbol"] == symbol and 0 < e.get("hours_until", 999) < hours:
                return {"imminent": True, "hours_until": e["hours_until"], "title": e["title"]}
        return {"imminent": False}


# ─── Unified Market Calendar ──────────────────────────────────────────────────

class MarketCalendar:
    """
    Unified calendar: Forex Factory live events + static known events + earnings.
    Drop-in replacement for the mock EconomicCalendar in news.py.
    """

    def __init__(self):
        self.forex_factory = ForexFactoryCalendar()
        self.earnings = EarningsCalendar()
        self._static_events = KNOWN_EVENTS_2026
        logger.info("MarketCalendar initialized (Forex Factory + Static + Earnings)")

    def should_reduce_exposure(self, symbol: str) -> dict:
        """Check if a high-impact event or earnings is imminent."""
        now = datetime.now(timezone.utc)
        is_crypto = "/" in symbol

        # 1. Forex Factory live events (within 30min, USD-only for stocks, skip for crypto)
        # Only USD events matter for US stocks/ETFs. EUR/JPY/GBP events don't affect SPY, GLD, etc.
        if not is_crypto:
            for event in self.forex_factory.fetch_events():
                if event["impact"] != "HIGH":
                    continue
                if event.get("country") != "USD":
                    continue  # Non-USD events don't affect US stocks
                hours_to = (event["time"] - now).total_seconds() / 3600
                if 0 < hours_to < 0.5:
                    logger.info(f"[{symbol}] FF event blocking: '{event['title']}' in {hours_to:.2f}h (at {event['time']})")
                    return {
                        "reduce": True,
                        "reason": f"Upcoming {event['title']} ({event['country']})",
                        "hours_until": round(hours_to, 2),
                        "source": "forex_factory",
                    }

        # 2. Static known events (within 4h, match by asset)
        for event in self._static_events:
            try:
                event_date = datetime.strptime(event["date"], "%Y-%m-%d").replace(
                    hour=14, minute=30, tzinfo=timezone.utc  # Typical US release time
                )
                hours_to = (event_date - now).total_seconds() / 3600
                if 0 < hours_to < 4:
                    assets = event.get("assets", [])
                    if "ALL" in assets or symbol in assets:
                        return {
                            "reduce": True,
                            "reason": f"{event['name']}",
                            "hours_until": round(hours_to, 1),
                            "source": "static_calendar",
                        }
            except (ValueError, KeyError):
                continue

        # 3. Earnings for this specific symbol (within 24h)
        earnings = self.earnings.is_earnings_imminent(symbol, hours=24)
        if earnings["imminent"]:
            return {
                "reduce": True,
                "reason": f"{earnings['title']} in {earnings['hours_until']:.1f}h",
                "hours_until": earnings["hours_until"],
                "source": "earnings",
            }

        return {"reduce": False}

    def get_upcoming(self, hours: int = 72) -> list[dict]:
        """All upcoming events within N hours, from all sources."""
        now = datetime.now(timezone.utc)
        events = []

        # Forex Factory
        for e in self.forex_factory.fetch_events():
            h = (e["time"] - now).total_seconds() / 3600
            if 0 < h < hours:
                events.append({
                    "title": e["title"],
                    "impact": e["impact"],
                    "hours_until": round(h, 1),
                    "country": e.get("country", "USD"),
                    "forecast": e.get("forecast", ""),
                    "previous": e.get("previous", ""),
                    "type": "economic",
                    "source": "forex_factory",
                })

        # Static events
        for e in self._static_events:
            try:
                dt = datetime.strptime(e["date"], "%Y-%m-%d").replace(
                    hour=14, minute=30, tzinfo=timezone.utc
                )
                h = (dt - now).total_seconds() / 3600
                if 0 < h < hours:
                    events.append({
                        "title": e["name"],
                        "impact": e["impact"],
                        "hours_until": round(h, 1),
                        "country": "USD",
                        "type": "earnings" if "Earnings" in e["name"] else "economic",
                        "source": "static",
                    })
            except (ValueError, KeyError):
                continue

        # Earnings
        for e in self.earnings.get_upcoming(days=max(int(hours / 24) + 1, 1)):
            if 0 < e["hours_until"] < hours:
                events.append({
                    "title": e["title"],
                    "impact": "HIGH",
                    "hours_until": e["hours_until"],
                    "country": "USD",
                    "type": "earnings",
                    "source": "earnings_schedule",
                })

        # De-duplicate by title proximity
        seen = set()
        unique = []
        for e in sorted(events, key=lambda x: x["hours_until"]):
            key = e["title"][:30]
            if key not in seen:
                unique.append(e)
                seen.add(key)
        return unique

    def get_earnings_this_week(self) -> list[dict]:
        return self.earnings.get_upcoming(days=7)

    def get_status(self) -> dict:
        upcoming = self.get_upcoming(hours=48)
        high_impact = [e for e in upcoming if e["impact"] == "HIGH"]
        earnings = self.get_earnings_this_week()
        return {
            "events_next_48h": len(upcoming),
            "high_impact_next_48h": len(high_impact),
            "earnings_this_week": [
                {"symbol": e.get("symbol", e["title"].split()[0]), "hours_until": e["hours_until"]}
                for e in earnings
            ],
            "next_event": upcoming[0] if upcoming else None,
            "upcoming_events": upcoming[:10],
        }
