"""v3.6 — Thematic Narrative Engine.

Two protocols that capture macro inefficiencies:
1. Capitol Protocol: Mirror congress trades (Quiver Quantitative API)
2. WWIII Protocol: Crisis detection → emergency risk-off to defense basket
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

from config import config
from data_layer import SessionManager

logger = logging.getLogger("phantom.thematic")

# ── Crisis Detection ──
# March 2026: NATO 5% GDP defense target, European rearmament, tariff escalation
DEFENSE_BASKET = ["LMT", "RTX", "NOC", "GD", "GLD", "SLV", "XLE", "UVXY"]
CRISIS_RISK_ASSETS = ["BTC/USD", "ETH/USD", "SOL/USD", "TQQQ", "SOXL", "SPXL"]

# Multi-word phrases to reduce false positives ("trade war" won't match "war" alone)
CRISIS_KEYWORDS_STRICT = [
    "declaration of war", "martial law", "nuclear strike", "military invasion",
    "troops deployed", "missile launch", "bombing raid", "nato article 5",
    "armed conflict", "military escalation", "naval blockade",
]
# Single-word keywords that need 3+ co-occurrences per headline to count
CRISIS_KEYWORDS_LOOSE = [
    "invasion", "nuclear", "mobilization", "retaliation", "attacked",
    "bombardment", "airstrike", "warhead",
]

# Quiver Quantitative API
QUIVER_BASE = "https://api.quiverquant.com/beta"
QUIVER_CONGRESS = f"{QUIVER_BASE}/live/congresstrading"


class ThematicProtocol:
    """Thematic overlays that modify trading behavior based on
    macro narrative signals (congress trades, geopolitical crises)."""

    def __init__(self):
        self.capitol_enabled = config.has_quiver
        self.wwiii_active = False
        self._wwiii_activated_at: datetime | None = None
        self._wwiii_cooldown_hours = 6  # Stay in crisis mode for 6h minimum
        self._last_congress_scan: datetime | None = None
        self._congress_cache: dict = {}
        self._congress_scan_interval = timedelta(hours=4)

    async def scan(self) -> dict:
        """Run all thematic scans. Returns override dictionary.

        The override dict can contain:
            - Per-symbol overrides (e.g., {symbol: {"congress_buy": True}})
            - Global overrides (e.g., {"risk_mode": "defense", "defense_basket": [...]})
        """
        overrides: dict = {}

        # Capitol Protocol: Congress trades
        if self.capitol_enabled:
            congress = await self._scan_congress_trades()
            overrides.update(congress)

        # WWIII Protocol: Crisis detection from recent headlines
        crisis = self._check_crisis_status()
        if crisis["active"]:
            overrides["risk_mode"] = "defense"
            overrides["defense_basket"] = DEFENSE_BASKET
            overrides["crisis_assets"] = CRISIS_RISK_ASSETS
            overrides["reduce_exposure_pct"] = 0.5
            if not self.wwiii_active:
                logger.critical(
                    f"WWIII PROTOCOL ACTIVATED — "
                    f"crisis keywords detected. Defense basket: {DEFENSE_BASKET}"
                )
            self.wwiii_active = True
            self._wwiii_activated_at = datetime.now(timezone.utc)

        return overrides

    # ── Capitol Protocol ──

    async def _scan_congress_trades(self) -> dict:
        """Fetch recent congress trades from Quiver Quantitative API.

        Looks for clustering: multiple representatives buying the same
        ticker within a 72-hour window → mirror trade signal.
        """
        if not config.has_quiver:
            return {}

        # Rate limit: scan every 4 hours max
        now = datetime.now(timezone.utc)
        if (
            self._last_congress_scan
            and (now - self._last_congress_scan) < self._congress_scan_interval
        ):
            return self._congress_cache

        session = await SessionManager.get_session()
        try:
            headers = {
                "Authorization": f"Bearer {config.quiver_api_key}",
                "Accept": "application/json",
            }
            async with session.get(
                QUIVER_CONGRESS,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    logger.warning("Quiver API: Invalid key (401)")
                    return {}
                if resp.status == 429:
                    logger.warning("Quiver API: Rate limited (429)")
                    return {}
                if resp.status != 200:
                    logger.debug(f"Quiver API: HTTP {resp.status}")
                    return {}

                trades = await resp.json()

            self._last_congress_scan = now
            return self._analyze_congress_clustering(trades)

        except aiohttp.ClientError as e:
            logger.debug(f"Quiver API error: {e}")
            return {}
        except Exception as e:
            logger.warning(f"Quiver API unexpected error: {e}")
            return {}

    def _analyze_congress_clustering(self, trades: list) -> dict:
        """Detect clustering: multiple congress members buying same ticker.

        A cluster = 2+ distinct representatives buying the same ticker
        within the last 72 hours.
        """
        if not trades:
            return {}

        # Our tradeable universe
        our_universe = set(config.stock_symbols + config.crypto_pairs)

        # Count purchases per ticker (recent only)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
        ticker_buyers: dict[str, set[str]] = {}

        for trade in trades:
            ticker = trade.get("Ticker", "").upper().strip()
            tx_type = trade.get("Transaction", "").lower()
            representative = trade.get("Representative", "Unknown")

            # Only track purchases in our universe
            if ticker not in our_universe:
                continue
            if "purchase" not in tx_type:
                continue

            # Parse date (Quiver format varies)
            try:
                tx_date_str = trade.get("TransactionDate", "")
                if tx_date_str:
                    tx_date = datetime.fromisoformat(tx_date_str.replace("Z", "+00:00"))
                    if tx_date.tzinfo is None:
                        tx_date = tx_date.replace(tzinfo=timezone.utc)
                    if tx_date < cutoff:
                        continue
            except (ValueError, TypeError):
                continue  # If date parsing fails, skip — cannot verify recency

            if ticker not in ticker_buyers:
                ticker_buyers[ticker] = set()
            ticker_buyers[ticker].add(representative)

        # Build overrides for clustered tickers (2+ distinct buyers)
        overrides: dict = {}
        for ticker, buyers in ticker_buyers.items():
            if len(buyers) >= 2:
                overrides[ticker] = {
                    "congress_buy": True,
                    "representatives": list(buyers),
                    "buyer_count": len(buyers),
                }
                logger.info(
                    f"CAPITOL PROTOCOL: {ticker} — {len(buyers)} congress members buying: "
                    f"{', '.join(list(buyers)[:3])}"
                )

        self._congress_cache = overrides
        return overrides

    # ── WWIII Protocol ──

    def activate_crisis(self, reason: str = "manual"):
        """Manually activate WWIII protocol."""
        self.wwiii_active = True
        self._wwiii_activated_at = datetime.now(timezone.utc)
        logger.critical(f"WWIII PROTOCOL MANUALLY ACTIVATED: {reason}")

    def deactivate_crisis(self):
        """Manually deactivate WWIII protocol."""
        self.wwiii_active = False
        self._wwiii_activated_at = None
        logger.info("WWIII protocol deactivated")

    def check_headlines_for_crisis(self, headlines: list[dict]) -> bool:
        """Scan headlines for geopolitical crisis keywords.

        Uses two-tier matching: strict multi-word phrases (1 match = crisis headline)
        and loose single words (need 3+ in same headline to count).
        Returns True if 3+ crisis headlines detected.
        """
        if not headlines:
            return False

        crisis_count = 0
        for headline in headlines:
            title = headline.get("title", "").lower()
            summary = headline.get("summary", "").lower()
            text = f"{title} {summary}"

            # Tier 1: Any strict multi-word phrase = crisis headline
            strict_matches = [kw for kw in CRISIS_KEYWORDS_STRICT if kw in text]
            if strict_matches:
                crisis_count += 1
                logger.warning(
                    f"Crisis STRICT match: '{headline.get('title', '')[:80]}' "
                    f"keywords={strict_matches}"
                )
                continue

            # Tier 2: Need 3+ loose keywords in same headline
            loose_matches = [kw for kw in CRISIS_KEYWORDS_LOOSE if kw in text]
            if len(loose_matches) >= 3:
                crisis_count += 1
                logger.warning(
                    f"Crisis LOOSE match: '{headline.get('title', '')[:80]}' "
                    f"keywords={loose_matches}"
                )

        # Need 3+ crisis headlines to activate
        return crisis_count >= 3

    def _check_crisis_status(self) -> dict:
        """Check if WWIII protocol should be active."""
        if not self.wwiii_active:
            return {"active": False}

        # Check cooldown: stay in crisis mode for minimum duration
        if self._wwiii_activated_at:
            elapsed = datetime.now(timezone.utc) - self._wwiii_activated_at
            if elapsed > timedelta(hours=self._wwiii_cooldown_hours):
                logger.info("WWIII protocol cooldown expired — deactivating")
                self.wwiii_active = False
                self._wwiii_activated_at = None
                return {"active": False}

        return {"active": True}

    def get_emergency_risk_off_actions(self) -> dict:
        """Get the specific actions for WWIII risk-off.

        Returns instructions for the engine to:
        1. Close all positions in crisis-risk assets
        2. Buy defense basket
        """
        return {
            "close_symbols": CRISIS_RISK_ASSETS,
            "buy_symbols": DEFENSE_BASKET,
            "reasoning": "WWIII Protocol — geopolitical crisis detected",
        }

    # ── Status ──

    def get_status(self) -> dict:
        return {
            "capitol_enabled": self.capitol_enabled,
            "wwiii_active": self.wwiii_active,
            "wwiii_activated_at": (
                self._wwiii_activated_at.isoformat()
                if self._wwiii_activated_at else None
            ),
            "congress_cache_size": len(self._congress_cache),
            "defense_basket": DEFENSE_BASKET,
        }
