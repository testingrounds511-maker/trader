"""v3.6 — Primary Sources Intelligence Feed.

Async RSS scanner for SEC EDGAR, DOJ, FDA, and financial news.
Feeds raw headlines to the NLP Engine for sentiment extraction.
"""

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
import feedparser

from data_layer import SessionManager

logger = logging.getLogger("phantom.intel")

# ── RSS Feed Sources (Primary, no Yahoo Finance dependency) ──
INTEL_FEEDS = {
    # SEC (8-K filings, enforcement actions)
    "sec_press": "https://www.sec.gov/news/pressreleases.rss",
    # DOJ (antitrust, sanctions, criminal charges)
    "doj_news": "https://www.justice.gov/feeds/opa/justice-news.xml",
    # FDA (drug approvals, recalls, warnings)
    "fda_press": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
    # Financial news (broad market coverage)
    "cnbc": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "reuters_business": "https://www.reutersagency.com/feed/?best-topics=business-finance",
    # Crypto
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
}


class IntelligenceFeed:
    """Continuously scans RSS feeds for new headlines and deduplicates them.

    Runs as a background asyncio task within the wolf engine's TaskGroup.
    Other modules access headlines via get_latest_headlines().
    """

    def __init__(self, scan_interval: int = 120):
        self._headlines: list[dict] = []
        self._seen_urls: set[str] = set()
        self._lock = asyncio.Lock()
        self._scan_interval = scan_interval  # seconds between full scans
        self._scan_count = 0
        self._error_count = 0

    async def run(self, stop_event: asyncio.Event):
        """Long-running background task — scans RSS feeds periodically."""
        logger.info(
            f"Intelligence Feed started — {len(INTEL_FEEDS)} sources, "
            f"interval={self._scan_interval}s"
        )

        while not stop_event.is_set():
            await self._scan_all_feeds()
            self._scan_count += 1

            # Wait for next scan or stop signal
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._scan_interval
                )
                break  # stop_event was set
            except asyncio.TimeoutError:
                continue

        logger.info("Intelligence Feed stopped")

    async def _scan_all_feeds(self):
        """Fetch all RSS feeds in parallel."""
        session = await SessionManager.get_session()
        tasks = [
            self._fetch_feed(session, name, url)
            for name, url in INTEL_FEEDS.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_count = sum(r for r in results if isinstance(r, int))
        if new_count > 0:
            logger.info(f"Intel scan #{self._scan_count}: {new_count} new headlines")

    async def _fetch_feed(
        self, session: aiohttp.ClientSession, name: str, url: str
    ) -> int:
        """Fetch and parse one RSS feed. Returns count of new headlines."""
        new_count = 0
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "PhantomWolf/3.6 IntelFeed"},
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"Intel feed {name}: HTTP {resp.status}")
                    return 0
                text = await resp.text()

            # feedparser is sync but fast — run in thread to avoid blocking
            feed = await asyncio.to_thread(feedparser.parse, text)

            async with self._lock:
                for entry in feed.entries[:15]:  # Max 15 entries per feed
                    entry_url = entry.get("link", entry.get("id", ""))
                    if not entry_url or entry_url in self._seen_urls:
                        continue

                    self._seen_urls.add(entry_url)
                    new_count += 1

                    headline = {
                        "title": self._clean_title(
                            entry.get("title", "No title")
                        ),
                        "source": name,
                        "url": entry_url,
                        "summary": self._clean_title(
                            entry.get("summary", "")
                        )[:200],
                        "published": entry.get("published", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    self._headlines.append(headline)

                # Keep only last 300 headlines
                if len(self._headlines) > 300:
                    self._headlines = self._headlines[-300:]

                # Trim seen URLs cache (keep last 1000)
                if len(self._seen_urls) > 1000:
                    # Keep most recent by rebuilding from headlines
                    self._seen_urls = {
                        h["url"] for h in self._headlines if h.get("url")
                    }

        except asyncio.TimeoutError:
            logger.debug(f"Intel feed {name}: timeout")
            self._error_count += 1
        except aiohttp.ClientError as e:
            logger.debug(f"Intel feed {name}: {e}")
            self._error_count += 1
        except Exception as e:
            logger.warning(f"Intel feed {name} unexpected error: {e}")
            self._error_count += 1

        return new_count

    @staticmethod
    def _clean_title(text: str) -> str:
        """Remove HTML tags and excess whitespace from title."""
        import re
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def get_latest_headlines(self, limit: int = 20) -> list[dict]:
        """Get most recent headlines (sync-safe, called from main loop)."""
        return self._headlines[-limit:]

    def get_headlines_by_source(self, source: str, limit: int = 10) -> list[dict]:
        """Get headlines filtered by source name."""
        return [
            h for h in self._headlines if h.get("source") == source
        ][-limit:]

    def get_status(self) -> dict:
        return {
            "total_headlines": len(self._headlines),
            "seen_urls": len(self._seen_urls),
            "scan_count": self._scan_count,
            "error_count": self._error_count,
            "sources": list(INTEL_FEEDS.keys()),
        }
