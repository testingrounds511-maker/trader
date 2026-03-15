"""News Sentinel — fetches news/sentiment and manages economic calendar events.

Real data sources (in priority order):
  1. Twitter/X       — requires TWITTER_BEARER_TOKEN in .env (API v2)
  2. NewsAPI         — requires NEWSAPI_KEY in .env
  3. RSS feeds       — Yahoo Finance, Reuters, CoinDesk (free, no key)
  4. Reddit (PRAW)   — requires REDDIT_CLIENT_ID + SECRET in .env

Economic Calendar:
  - Forex Factory live events (via economic_calendar.py)
  - Static known events for 2026 (FOMC, CPI, NFP, earnings)
"""

import logging
import threading
import time
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests

from config import config

logger = logging.getLogger("phantom.news")

# ─── Simple TextBlob-free sentiment ──────────────────────────────────────────

_BULL_WORDS = {
    "surge", "rally", "soar", "gain", "rise", "bull", "beat", "record",
    "breakout", "outperform", "upgrade", "buy", "strong", "recovery",
    "boom", "pump", "profit", "growth", "high", "positive", "up",
}
_BEAR_WORDS = {
    "crash", "plunge", "drop", "fall", "bear", "miss", "sell", "weak",
    "recession", "inflation", "rate hike", "default", "loss", "low",
    "decline", "negative", "down", "halt", "dump", "fear", "panic",
}


def _naive_sentiment(text: str) -> tuple[str, float]:
    """Very fast keyword-based sentiment without any ML dependency."""
    words = text.lower().split()
    bull = sum(1 for w in words if w in _BULL_WORDS)
    bear = sum(1 for w in words if w in _BEAR_WORDS)
    if bull > bear:
        return "BULLISH", min(0.4 + bull * 0.1, 0.95)
    elif bear > bull:
        return "BEARISH", min(0.4 + bear * 0.1, 0.95)
    return "NEUTRAL", 0.0


# ─── RSS Fetcher ──────────────────────────────────────────────────────────────

RSS_FEEDS = {
    "yahoo_finance":  "https://finance.yahoo.com/news/rssindex",
    "reuters_biz":    "https://feeds.reuters.com/reuters/businessNews",
    "coindesk":       "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph":  "https://cointelegraph.com/rss",
    "marketwatch":    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
}
_RSS_TIMEOUT = 7


def _fetch_rss_alerts(portfolio_symbols: list[str]) -> list[dict]:
    """Parse financial RSS feeds and return normalized alert dicts."""
    try:
        import feedparser  # noqa: PLC0415
    except ImportError:
        logger.debug("feedparser not installed, skipping RSS")
        return []

    alerts = []
    sym_lower = {s.lower().replace("/usd", "").replace("/usdt", "") for s in portfolio_symbols}

    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url, request_headers={
                "User-Agent": "PhantomTrader/3.5 RSS reader"
            })
            for entry in feed.entries[:8]:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = f"{title} {summary}"

                # Find which portfolio assets this article mentions
                mentioned = [
                    s for s in portfolio_symbols
                    if s.lower().replace("/usd", "") in text.lower()
                    or s.lower().replace("/usdt", "") in text.lower()
                ]

                label, score = _naive_sentiment(text)
                if label == "NEUTRAL" and not mentioned:
                    continue  # Skip noise

                alerts.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "title": title[:200],
                    "source": f"RSS:{source}",
                    "urgency": "HIGH" if score > 0.7 else "LOW",
                    "sentiment": {"label": label, "score": score},
                    "affected_assets": mentioned or _infer_assets(text, portfolio_symbols),
                })
        except Exception as e:
            logger.debug(f"RSS fetch failed ({source}): {e}")

    return alerts


def _infer_assets(text: str, symbols: list[str]) -> list[str]:
    """Best-effort: match keywords like 'bitcoin', 'nvidia', 'crypto' to portfolio."""
    kw_map = {
        "bitcoin": "BTC/USD", "btc": "BTC/USD",
        "ethereum": "ETH/USD", "eth": "ETH/USD",
        "solana": "SOL/USD", "sol": "SOL/USD",
        "nvidia": "NVDA", "nvda": "NVDA",
        "tesla": "TSLA", "tsla": "TSLA",
        "coinbase": "COIN",
        "google": "GOOGL", "alphabet": "GOOGL",
        "amazon": "AMZN", "amzn": "AMZN",
        "microsoft": "MSFT", "msft": "MSFT", "azure": "MSFT",
        "meta": "META", "facebook": "META",
        "apple": "AAPL", "aapl": "AAPL",
        "palantir": "PLTR", "pltr": "PLTR",
        "microstrategy": "MSTR", "mstr": "MSTR",
        "amd": "AMD",
        "crypto": "BTC/USD",
    }
    tl = text.lower()
    found = set()
    for kw, asset in kw_map.items():
        if asset in symbols:
            if re.search(r'\b' + re.escape(kw) + r'\b', tl):
                found.add(asset)
    return list(found)[:3]


# ─── NewsAPI Fetcher ──────────────────────────────────────────────────────────

_NEWSAPI_BASE = "https://newsapi.org/v2/everything"
_NEWSAPI_TIMEOUT = 8
_NEWSAPI_KEYWORDS = (
    "bitcoin OR ethereum OR crypto OR NVDA OR Tesla OR "
    "stock market OR Federal Reserve OR inflation OR earnings"
)

# Cache to avoid 429 rate-limit errors.
# Free tier: ~100 req/day → fetch at most once every 15 minutes.
_newsapi_cache: list[dict] = []
_newsapi_last_fetch: float = 0.0
_NEWSAPI_MIN_INTERVAL = 900  # seconds (15 min)


def _fetch_newsapi_alerts(api_key: str, portfolio_symbols: list[str]) -> list[dict]:
    """Fetch real headlines from NewsAPI (cached — max 1 call per 15 min)."""
    global _newsapi_cache, _newsapi_last_fetch

    if not api_key:
        return []

    import time
    now = time.monotonic()
    elapsed = now - _newsapi_last_fetch
    if elapsed < _NEWSAPI_MIN_INTERVAL:
        remaining = int(_NEWSAPI_MIN_INTERVAL - elapsed)
        logger.debug(f"NewsAPI: using cached results ({len(_newsapi_cache)} items) — next fetch in {remaining}s")
        return _newsapi_cache

    try:
        params = {
            "q": _NEWSAPI_KEYWORDS,
            "apiKey": api_key,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
        }
        r = requests.get(_NEWSAPI_BASE, params=params, timeout=_NEWSAPI_TIMEOUT)
        if r.status_code == 429:
            logger.warning("NewsAPI: rate-limit (429) — will retry in 15 min")
            _newsapi_last_fetch = now  # back off, don't hammer the API
            return _newsapi_cache
        r.raise_for_status()
        data = r.json()
        articles = data.get("articles", [])

        alerts = []
        for a in articles:
            title = a.get("title", "") or ""
            description = a.get("description", "") or ""
            text = f"{title} {description}"
            label, score = _naive_sentiment(text)
            mentioned = _infer_assets(text, portfolio_symbols)

            if label == "NEUTRAL" and not mentioned:
                continue

            published = a.get("publishedAt", datetime.now(timezone.utc).isoformat())
            alerts.append({
                "timestamp": published,
                "title": title[:200],
                "source": f"NewsAPI:{a.get('source', {}).get('name', 'unknown')}",
                "urgency": "HIGH" if score > 0.75 else "LOW",
                "sentiment": {"label": label, "score": score},
                "affected_assets": mentioned,
            })

        _newsapi_cache = alerts
        _newsapi_last_fetch = now
        logger.info(f"NewsAPI: fetched {len(alerts)} alerts (next fetch in 15 min)")
        return alerts
    except Exception as e:
        logger.warning(f"NewsAPI fetch failed: {e}")
        return _newsapi_cache  # return stale cache rather than empty on error


# ─── Reddit Fetcher ───────────────────────────────────────────────────────────

_REDDIT_SUBS = ["wallstreetbets", "CryptoCurrency", "stocks", "investing", "Superstonk"]
_REDDIT_LIMIT = 10  # posts per subreddit


def _fetch_reddit_alerts(
    client_id: str,
    client_secret: str,
    user_agent: str,
    portfolio_symbols: list[str],
) -> list[dict]:
    """Use PRAW to scan hot posts in finance subreddits."""
    if not (client_id and client_secret):
        return []
    try:
        import praw  # noqa: PLC0415

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            ratelimit_seconds=30,
        )
        alerts = []
        for sub_name in _REDDIT_SUBS:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.hot(limit=_REDDIT_LIMIT):
                    title = post.title or ""
                    text = f"{title} {post.selftext[:200] if post.selftext else ''}"
                    label, score = _naive_sentiment(text)
                    mentioned = _infer_assets(text, portfolio_symbols)

                    # Only include posts with signal or asset mention
                    if label == "NEUTRAL" and not mentioned:
                        continue
                    # Only include posts with some traction
                    if post.score < 50 and post.num_comments < 10:
                        continue

                    urgency = "HIGH" if (post.score > 1000 or post.num_comments > 200) else "LOW"
                    created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat()
                    alerts.append({
                        "timestamp": created,
                        "title": f"[r/{sub_name}] {title[:180]}",
                        "source": f"Reddit:r/{sub_name}",
                        "urgency": urgency,
                        "sentiment": {"label": label, "score": score},
                        "affected_assets": mentioned,
                        "reddit_score": post.score,
                    })
            except Exception as e:
                logger.debug(f"Reddit r/{sub_name} failed: {e}")
        return alerts
    except ImportError:
        logger.debug("praw not installed, skipping Reddit")
        return []
    except Exception as e:
        logger.warning(f"Reddit fetch failed: {e}")
        return []


# ─── Twitter/X Fetcher (API v2) ──────────────────────────────────────────────

_TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
_TWITTER_TIMEOUT = 10

# Pentagon/military OSINT keywords — detect elevated chatter
_PENTAGON_KEYWORDS = [
    "pentagon lights", "pentagon late night", "pentagon activity",
    "military mobilization", "defense readiness", "DEFCON",
    "carrier strike group", "B-2 deployed", "nuclear submarine",
    "CENTCOM", "troop deployment", "air strike", "military operation",
]

# Defense stocks to flag when Pentagon chatter is elevated
DEFENSE_TICKERS = ["LMT", "RTX", "NOC", "GD", "BA"]


def _fetch_twitter_alerts(
    bearer_token: str,
    portfolio_symbols: list[str],
) -> tuple[list[dict], bool]:
    """
    Fetch recent tweets from watchlist accounts using Twitter API v2 Recent Search.
    Returns (alerts, pentagon_elevated) — pentagon_elevated=True when military chatter is high.
    """
    if not bearer_token:
        return [], False

    try:
        from watchlist import TWITTER_WATCHLIST, get_tier1_handles
    except ImportError:
        logger.debug("watchlist.py not found, skipping Twitter")
        return [], False

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "User-Agent": "PhantomTrader/3.5",
    }

    alerts = []
    pentagon_hits = 0

    # Build search query: tweets from tier 1-2 accounts (most impactful)
    # Twitter API v2 free tier: 10k tweets/month, so we must be selective
    priority_handles = [
        h for h, info in TWITTER_WATCHLIST.items()
        if info["tier"] <= 3 or info["tier"] == 5  # FIX: Include Tier 5 (OSINT/Military)
    ]

    # Search in batches (API limits query length to ~512 chars)
    batch_size = 8
    for i in range(0, len(priority_handles), batch_size):
        batch = priority_handles[i:i + batch_size]
        from_query = " OR ".join(f"from:{h}" for h in batch)
        query = f"({from_query}) -is:retweet"

        try:
            params = {
                "query": query,
                "max_results": 10,
                "tweet.fields": "created_at,author_id,text",
                "sort_order": "recency",
            }
            r = requests.get(
                _TWITTER_SEARCH_URL, headers=headers,
                params=params, timeout=_TWITTER_TIMEOUT,
            )

            if r.status_code == 429:
                logger.warning("Twitter API rate limited — skipping this cycle")
                break
            if r.status_code != 200:
                logger.debug(f"Twitter API error {r.status_code}: {r.text[:200]}")
                continue

            data = r.json()
            tweets = data.get("data", [])

            for tweet in tweets:
                text = tweet.get("text", "")
                created = tweet.get("created_at", datetime.now(timezone.utc).isoformat())

                # Sentiment analysis
                label, score = _naive_sentiment(text)

                # Match to portfolio assets using watchlist keywords
                mentioned = []
                text_lower = text.lower()
                for handle, info in TWITTER_WATCHLIST.items():
                    for kw in info.get("keywords", []):
                        if kw.lower() in text_lower:
                            mentioned.extend(info["assets"])
                            break

                # Also try general asset inference
                if not mentioned:
                    mentioned = _infer_assets(text, portfolio_symbols)

                # Expand "ALL" to actual portfolio symbols
                if "ALL" in mentioned:
                    mentioned = portfolio_symbols[:5]  # Top 5 symbols
                mentioned = list(set(mentioned))[:5]

                # Check for Pentagon/military OSINT signals
                is_pentagon = any(kw in text_lower for kw in _PENTAGON_KEYWORDS)
                if is_pentagon:
                    pentagon_hits += 1
                    mentioned.extend(DEFENSE_TICKERS)
                    mentioned = list(set(mentioned))

                if label == "NEUTRAL" and not mentioned and not is_pentagon:
                    continue

                # Determine urgency from watchlist tier
                tier = TWITTER_WATCHLIST.get(tweet.get("author_id"), {}).get("tier", 3)
                # Try to find tier by handle if author_id lookup fails (batch logic approximation)
                if tier == 3: 
                    tier = min([TWITTER_WATCHLIST.get(h, {}).get("tier", 99) for h in batch])

                urgency = "HIGH" if tier <= 2 else "LOW"
                
                # POWER-UP: Tier 1 accounts (Elon, Saylor) get sentiment score boost
                if tier == 1:
                    score *= 1.5

                if is_pentagon:
                    urgency = "HIGH"

                alerts.append({
                    "timestamp": created,
                    "title": f"[X] {text[:180]}",
                    "source": f"Twitter/X",
                    "urgency": urgency,
                    "sentiment": {"label": label, "score": score},
                    "affected_assets": mentioned,
                    "is_pentagon_osint": is_pentagon,
                })

        except requests.exceptions.RequestException as e:
            logger.debug(f"Twitter batch fetch failed: {e}")
            continue

    # Pentagon chatter is elevated if 2+ hits in a single scan
    pentagon_elevated = pentagon_hits >= 2

    if pentagon_elevated:
        logger.warning(
            f"PENTAGON OSINT: {pentagon_hits} military chatter signals detected on Twitter"
        )

    return alerts, pentagon_elevated


# ─── Economic Calendar (delegated to economic_calendar.py) ────────────────────
# The real calendar lives in economic_calendar.py (MarketCalendar).
# This is a thin wrapper for backwards compatibility with code that references
# sentinel.calendar.should_reduce_exposure(symbol).

from economic_calendar import MarketCalendar as _RealCalendar


class EconomicCalendar(_RealCalendar):
    """Backwards-compatible alias. All logic lives in economic_calendar.py now."""
    pass


# ─── News Sentinel ────────────────────────────────────────────────────────────

class NewsSentinel:
    def __init__(self):
        self.running = False
        self.thread = None
        self.alerts: list[dict] = []
        self.calendar = EconomicCalendar()
        self.last_scan = None
        self.last_scan_counts = {"newsapi": 0, "rss": 0, "reddit": 0, "twitter": 0}
        self.pentagon_elevated = False  # True when military chatter is high on Twitter
        self.sources_status = {
            "rss": True,
            "newsapi": config.has_newsapi,
            "reddit": config.has_reddit,
            "twitter": config.has_twitter,
        }

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.thread.start()
        logger.info(
            f"News Sentinel started — sources: "
            f"Twitter={'on' if config.has_twitter else 'off'}, "
            f"RSS=on, NewsAPI={'on' if config.has_newsapi else 'off'}, "
            f"Reddit={'on' if config.has_reddit else 'off'}"
        )

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _scan_loop(self):
        while self.running:
            try:
                self._fetch_news()
                self.last_scan = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                logger.error(f"News scan error: {e}")

            for _ in range(config.news_check_interval):
                if not self.running:
                    return
                time.sleep(1)

    def _fetch_news(self):
        all_symbols = config.crypto_pairs + config.stock_symbols
        new_alerts = []
        counts = {"newsapi": 0, "rss": 0, "reddit": 0, "twitter": 0}

        # ── 1. Twitter/X (fastest, highest alpha) ───────────────────────
        if config.has_twitter:
            tw, pentagon = _fetch_twitter_alerts(
                config.twitter_bearer_token, all_symbols,
            )
            new_alerts.extend(tw)
            counts["twitter"] = len(tw)
            self.pentagon_elevated = pentagon

        # ── 2. NewsAPI (highest quality) ──────────────────────────────────
        if config.has_newsapi:
            na = _fetch_newsapi_alerts(config.newsapi_key, all_symbols)
            new_alerts.extend(na)
            counts["newsapi"] = len(na)

        # ── 2. RSS feeds ──────────────────────────────────────────────────
        rss = _fetch_rss_alerts(all_symbols)
        new_alerts.extend(rss)
        counts["rss"] = len(rss)

        # ── 3. Reddit (PRAW) ─────────────────────────────────────────────
        if config.has_reddit:
            rd = _fetch_reddit_alerts(
                config.reddit_client_id,
                config.reddit_client_secret,
                config.reddit_user_agent,
                all_symbols,
            )
            new_alerts.extend(rd)
            counts["reddit"] = len(rd)

        # De-duplicate by title
        seen_titles = {a["title"] for a in self.alerts[-20:]}
        for a in new_alerts:
            if a["title"] not in seen_titles:
                self.alerts.append(a)
                seen_titles.add(a["title"])

        self.alerts = self.alerts[-100:]  # Keep last 100
        self.last_scan_counts = counts

        if sum(counts.values()) > 0:
            logger.info(
                f"News fetch: Twitter={counts['twitter']} NewsAPI={counts['newsapi']} "
                f"RSS={counts['rss']} Reddit={counts['reddit']}"
            )

    def get_sentiment_summary(self, symbol: str) -> dict:
        """Aggregated sentiment for a symbol."""
        clean_sym = symbol.upper().replace("/USD", "").replace("/USDT", "")
        relevant = [
            a for a in self.alerts
            if symbol in a.get("affected_assets", [])
            or clean_sym in a.get("affected_assets", [])
            or re.search(r'\b' + re.escape(clean_sym) + r'\b', a.get("title", "").upper())
        ]
        if not relevant:
            return {"label": "NEUTRAL", "avg_sentiment": 0, "count": 0, "latest": None}

        score = 0
        for a in relevant:
            s = a["sentiment"]["label"]
            if s == "BULLISH":
                score += 1
            elif s == "BEARISH":
                score -= 1

        label = "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"
        return {
            "label": label,
            "avg_sentiment": round(score / len(relevant), 2),
            "count": len(relevant),
            "latest": relevant[-1]["title"],
        }

    def get_fast_lane_alerts(self, since_minutes: int = 2) -> list:
        """High-urgency alerts from the last N minutes."""
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(minutes=since_minutes)
        return [
            a for a in self.alerts
            if a["urgency"] == "HIGH"
            and datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")) > threshold
        ]

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "last_scan": self.last_scan,
            "total_alerts": len(self.alerts),
            "sources": self.sources_status,
            "last_scan_counts": self.last_scan_counts,
            "pentagon_elevated": self.pentagon_elevated,
        }

    def get_recent_alerts(self, n: int = 20) -> list[dict]:
        return list(reversed(self.alerts[-n:]))
