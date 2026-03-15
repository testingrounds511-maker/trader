"""
TITANIUM VANGUARD - Reddit RSS Collector
Collects public posts from Reddit via RSS/Atom feeds (no API keys required).
"""

import asyncio
import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import aiohttp

from collectors.base import BaseCollector
from models import Event


class RedditRSSCollector(BaseCollector):
    """
    Reddit collector using RSS/Atom feeds.
    Works without API credentials and avoids asyncpraw dependency.
    """

    FEED_TEMPLATE = "https://www.reddit.com/r/{subreddit}/.rss?limit={limit}"

    TRUSTED_DOMAINS = {
        "reuters.com": 0.95,
        "apnews.com": 0.95,
        "bbc.com": 0.90,
        "bbc.co.uk": 0.90,
        "aljazeera.com": 0.85,
        "theguardian.com": 0.85,
        "ft.com": 0.85,
        "wsj.com": 0.85,
        "economist.com": 0.80,
        "nytimes.com": 0.80,
        "washingtonpost.com": 0.80,
        "bloomberg.com": 0.75,
        "cnn.com": 0.70,
        "afp.com": 0.90,
        "dw.com": 0.80,
        "scmp.com": 0.75,
        "straitstimes.com": 0.75,
    }

    REDDIT_DOMAINS = {
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "np.reddit.com",
        "redd.it",
        "redditmedia.com",
    }

    COUNTRY_KEYWORDS = {
        "chile": "Chile",
        "peru": "Peru",
        "argentina": "Argentina",
        "china": "China",
        "russia": "Russia",
        "united states": "USA",
        "usa": "USA",
        "japan": "Japan",
        "india": "India",
        "france": "France",
        "germany": "Germany",
        "uk": "United Kingdom",
        "united kingdom": "United Kingdom",
        "brazil": "Brazil",
        "mexico": "Mexico",
        "south korea": "South Korea",
        "north korea": "North Korea",
        "iran": "Iran",
        "israel": "Israel",
        "saudi arabia": "Saudi Arabia",
        "taiwan": "Taiwan",
        "vietnam": "Vietnam",
        "thailand": "Thailand",
    }

    def __init__(self, config=None):
        super().__init__(config)
        self.subreddits = self._load_subreddits()
        self.posts_per_subreddit = self.config.reddit_posts_per_subreddit
        self.timeout = aiohttp.ClientTimeout(total=self.config.collector_timeout)
        self.user_agent = self.config.reddit_user_agent or "TITANIUM-VANGUARD/2.0"
        self.max_concurrent = 5

        self.logger.info(f"RedditRSSCollector initialized: {len(self.subreddits)} subreddits")

    def _load_subreddits(self) -> List[str]:
        """Load subreddits from config or default list."""
        if hasattr(self.config, "reddit_subreddits") and self.config.reddit_subreddits:
            subs = [s.strip() for s in self.config.reddit_subreddits.split(",")]
            if subs and subs[0]:
                return subs

        return [
            "geopolitics",
            "worldpolitics",
            "internationalpolitics",
            "worldnews",
            "news",
            "Military",
            "Economics",
            "China",
            "Russia",
            "Ukraine",
        ]

    async def fetch(self) -> List[Dict]:
        """Fetch RSS/Atom feeds for all subreddits."""
        self.logger.info(f"Fetching Reddit RSS feeds for {len(self.subreddits)} subreddits...")

        headers = {"User-Agent": self.user_agent}
        connector = aiohttp.TCPConnector(limit_per_host=self.max_concurrent)

        async with aiohttp.ClientSession(timeout=self.timeout, headers=headers, connector=connector) as session:
            semaphore = asyncio.Semaphore(self.max_concurrent)
            tasks = [
                self._fetch_subreddit_feed(session, semaphore, subreddit)
                for subreddit in self.subreddits
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_entries = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.warning(f"Error fetching subreddit feed: {result}")
                continue
            if result:
                all_entries.extend(result)

        self.logger.info(f"Fetched {len(all_entries)} RSS entries from Reddit")
        return all_entries

    async def _fetch_subreddit_feed(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        subreddit: str,
    ) -> List[Dict]:
        url = self.FEED_TEMPLATE.format(subreddit=subreddit, limit=self.posts_per_subreddit)

        async with semaphore:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        feed_text = await response.text()
                        return self._parse_feed(feed_text, subreddit)
                    if response.status in (403, 429):
                        self.logger.warning(f"RSS blocked for r/{subreddit}: {response.status}")
                        return []
                    self.logger.warning(f"RSS error for r/{subreddit}: {response.status}")
                    return []
            except Exception as e:
                self.logger.warning(f"RSS fetch failed for r/{subreddit}: {e}")
                return []

    def _parse_feed(self, feed_text: str, subreddit: str) -> List[Dict]:
        entries = []

        try:
            root = ET.fromstring(feed_text)
        except ET.ParseError as e:
            self.logger.warning(f"RSS parse error for r/{subreddit}: {e}")
            return entries

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            entry_id = entry.findtext("atom:id", default="").strip()
            title = entry.findtext("atom:title", default="").strip()
            published = entry.findtext("atom:published", default="").strip()
            updated = entry.findtext("atom:updated", default="").strip()

            author = ""
            author_node = entry.find("atom:author/atom:name", ns)
            if author_node is not None and author_node.text:
                author = author_node.text.strip()

            content_html = ""
            content_node = entry.find("atom:content", ns)
            if content_node is None:
                content_node = entry.find("atom:summary", ns)
            if content_node is not None and content_node.text:
                content_html = content_node.text

            link_hrefs = []
            for link in entry.findall("atom:link", ns):
                href = link.attrib.get("href")
                if href:
                    link_hrefs.append(href)

            external_url, entry_link = self._extract_urls(content_html, link_hrefs)

            entries.append(
                {
                    "id": entry_id,
                    "title": title,
                    "published": published,
                    "updated": updated,
                    "author": author,
                    "subreddit": subreddit,
                    "content_html": content_html,
                    "external_url": external_url,
                    "link": entry_link,
                }
            )

        return entries

    def _extract_urls(self, content_html: str, link_hrefs: List[str]) -> Tuple[str, str]:
        """Return (external_url, entry_link)."""
        candidates = []
        for href in link_hrefs:
            if href:
                candidates.append(href)

        if content_html:
            for href in re.findall(r'href=[\'"]([^\'"]+)', content_html):
                candidates.append(href)

        external_url = ""
        entry_link = ""

        for href in candidates:
            if self._is_reddit_url(href):
                if not entry_link:
                    entry_link = href
                continue
            external_url = href
            break

        if not entry_link:
            entry_link = candidates[0] if candidates else ""

        return external_url, entry_link

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        """Convert RSS entries to Event objects."""
        events = []

        for item in raw_data:
            try:
                title = item.get("title") or "Reddit post"
                content_text = self._strip_html(item.get("content_html", ""))
                combined_text = f"{title} {content_text}".strip()

                event_date = self._parse_date(item.get("published") or item.get("updated"))
                if not event_date:
                    event_date = datetime.now(timezone.utc)

                source_url = item.get("external_url") or item.get("link") or None
                domain = self._extract_domain(source_url)
                domain_trust = self._validate_domain_trust(domain)

                country, primary_actors = self._extract_country_and_actors(combined_text)
                region = self._extract_region(country)
                event_type = self._classify_event_type(combined_text)
                relevance = self._calculate_relevance_score(combined_text, source_url, domain_trust)

                event_id = self._generate_event_id(item)

                event = Event(
                    id=event_id,
                    title=title[:500],
                    description=self._build_description(item, content_text, domain_trust),
                    source_url=source_url,
                    source_name=self._clean_domain_name(domain) if domain else "Reddit",
                    event_date=event_date,
                    published_date=event_date,
                    country=country,
                    region=region,
                    event_type=event_type,
                    category="reddit",
                    primary_actors=primary_actors,
                    relevance_score=relevance,
                    language="en",
                    tags=self._extract_tags(combined_text, domain_trust),
                    raw_data=item,
                )

                events.append(event)
            except Exception as e:
                self.logger.warning(f"Error parsing RSS entry: {e}")
                continue

        self.logger.info(f"Parsed {len(events)} events from {len(raw_data)} RSS entries")
        return events

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            return None

    def _extract_domain(self, url: Optional[str]) -> str:
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    def _is_reddit_url(self, url: str) -> bool:
        try:
            domain = self._extract_domain(url)
            return any(domain == rd or domain.endswith("." + rd) for rd in self.REDDIT_DOMAINS)
        except Exception:
            return False

    def _validate_domain_trust(self, domain: str) -> Dict:
        trust_score = self.TRUSTED_DOMAINS.get(domain, 0.5)
        is_trusted = trust_score >= 0.70

        if trust_score >= 0.85:
            category = "major_news"
            reason = "Trusted news source"
        elif trust_score >= 0.70:
            category = "regional_news"
            reason = "Known regional source"
        elif "blog" in domain or "medium.com" in domain:
            category = "blog"
            reason = "Blog/independent"
            trust_score = 0.4
        elif "reddit.com" in domain:
            category = "social_media"
            reason = "Reddit discussion"
            trust_score = 0.3
        else:
            category = "unknown"
            reason = "Unknown domain"

        return {
            "is_trusted": is_trusted,
            "trust_score": trust_score,
            "reason": reason,
            "category": category,
        }

    def _extract_country_and_actors(self, text: str) -> Tuple[Optional[str], List[str]]:
        text_lower = text.lower()
        actors = []
        country = None

        for keyword, name in self.COUNTRY_KEYWORDS.items():
            if keyword in text_lower and name not in actors:
                actors.append(name)
                if not country:
                    country = name

        return country, actors

    def _extract_region(self, country: Optional[str]) -> Optional[str]:
        regions = {
            "Chile": "South America",
            "Peru": "South America",
            "Argentina": "South America",
            "Brazil": "South America",
            "Mexico": "North America",
            "China": "Asia-Pacific",
            "Japan": "Asia-Pacific",
            "India": "Asia-Pacific",
            "South Korea": "Asia-Pacific",
            "Taiwan": "Asia-Pacific",
            "Vietnam": "Asia-Pacific",
            "Thailand": "Asia-Pacific",
            "Russia": "Europe",
            "USA": "North America",
            "France": "Europe",
            "Germany": "Europe",
            "United Kingdom": "Europe",
            "Iran": "Middle East",
            "Israel": "Middle East",
            "Saudi Arabia": "Middle East",
        }
        return regions.get(country)

    def _classify_event_type(self, text: str) -> str:
        text_lower = text.lower()
        if any(word in text_lower for word in ["military", "conflict", "war", "attack", "troops"]):
            return "military"
        if any(word in text_lower for word in ["trade", "tariff", "export", "commerce", "economic"]):
            return "economic"
        if any(word in text_lower for word in ["diplomatic", "meeting", "summit", "agreement", "negotiation"]):
            return "diplomacy"
        if any(word in text_lower for word in ["sanction", "embargo", "restriction"]):
            return "sanctions"
        return "geopolitical"

    def _calculate_relevance_score(self, text: str, source_url: Optional[str], domain_trust: Dict) -> float:
        score = 0.45

        if source_url and not self._is_reddit_url(source_url):
            score += 0.15

        if domain_trust["trust_score"] >= 0.85:
            score += 0.2
        elif domain_trust["trust_score"] >= 0.70:
            score += 0.1

        if any(word in text.lower() for word in ["crisis", "war", "attack", "sanction", "summit"]):
            score += 0.1

        return max(0.0, min(1.0, score))

    def _extract_tags(self, text: str, domain_trust: Dict) -> List[str]:
        tags = ["reddit-rss"]
        text_lower = text.lower()

        tag_keywords = {
            "military": ["military", "defense", "army", "troops", "weapons"],
            "economic": ["economic", "trade", "commerce", "tariff", "business"],
            "diplomatic": ["diplomatic", "summit", "negotiation", "agreement"],
            "security": ["security", "threat", "conflict", "crisis"],
            "geopolitical": ["geopolitical", "strategic", "region"],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(tag)

        if domain_trust.get("is_trusted"):
            tags.append("trusted-source")

        return list(set(tags))

    def _clean_domain_name(self, domain: str) -> str:
        if not domain:
            return "Reddit"
        name_map = {
            "reuters.com": "Reuters",
            "apnews.com": "AP News",
            "bbc.com": "BBC",
            "bbc.co.uk": "BBC",
            "aljazeera.com": "Al Jazeera",
            "theguardian.com": "The Guardian",
            "nytimes.com": "New York Times",
            "wsj.com": "Wall Street Journal",
            "cnn.com": "CNN",
        }
        return name_map.get(domain, domain.upper())

    def _build_description(self, item: Dict, content_text: str, domain_trust: Dict) -> str:
        parts = []

        if content_text:
            parts.append(content_text[:500])

        if item.get("author"):
            parts.append(f"Author: {item['author']}")
        if item.get("subreddit"):
            parts.append(f"Subreddit: r/{item['subreddit']}")
        parts.append(f"Domain Trust: {domain_trust['trust_score']:.2f} ({domain_trust['category']})")

        return " | ".join(parts)

    def _strip_html(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<[^>]+>", " ", text)
        cleaned = html.unescape(cleaned)
        return " ".join(cleaned.split())

    def _generate_event_id(self, item: Dict) -> str:
        seed = item.get("id") or item.get("link") or item.get("title", "")
        hash_suffix = hashlib.md5(seed.encode()).hexdigest()[:10]
        return f"reddit_rss_{hash_suffix}"
