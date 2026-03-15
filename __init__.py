"""News sentiment monitor — lightweight forex news feed."""

import logging
import threading
import time
from datetime import datetime, timezone

import requests

from config import config

logger = logging.getLogger("phantom.sentinel")


class NewsSentinel:
    """Monitors forex news for sentiment signals."""

    def __init__(self):
        self.running = False
        self._thread: threading.Thread | None = None
        self.latest_sentiment: dict = {}  # symbol -> sentiment string
        self.headlines: list[dict] = []

    def start(self):
        if not config.newsapi_key:
            logger.info("News sentinel disabled (no API key)")
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def get_sentiment(self, symbol: str) -> str:
        """Get current sentiment for a symbol."""
        return self.latest_sentiment.get(symbol, "neutral — no recent news data")

    def _loop(self):
        while self.running:
            try:
                self._fetch_news()
            except Exception as e:
                logger.debug(f"News fetch error: {e}")
            time.sleep(300)  # Check every 5 minutes

    def _fetch_news(self):
        """Fetch forex headlines from NewsAPI."""
        keywords = ["forex", "EURUSD", "dollar", "fed rate", "ECB", "BOJ",
                     "gold price", "oil price", "inflation"]

        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": " OR ".join(keywords[:5]),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 10,
                "apiKey": config.newsapi_key,
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return

            articles = resp.json().get("articles", [])
            self.headlines = [
                {
                    "title": a.get("title", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "published": a.get("publishedAt", ""),
                }
                for a in articles[:10]
            ]

            # Simple keyword sentiment for each symbol
            for symbol in config.symbols:
                base = symbol[:3]
                quote = symbol[3:]
                relevant = [h["title"] for h in self.headlines
                            if base.lower() in h["title"].lower()
                            or quote.lower() in h["title"].lower()]

                if relevant:
                    self.latest_sentiment[symbol] = (
                        f"Recent headlines mentioning {symbol}: " +
                        " | ".join(relevant[:3])
                    )

        except Exception as e:
            logger.debug(f"NewsAPI error: {e}")
