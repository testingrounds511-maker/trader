"""
TITANIUM VANGUARD - Official Documents Collector
Phase 2A: Collects policy documents, press releases, and official statements
from USA, China, EU, and Russia government sources.
"""

import aiohttp
import asyncio
import hashlib
import io
import json
from typing import List, Dict, Optional
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict

from collectors.base import BaseCollector
from core.config import get_settings


@dataclass
class OfficialDocument:
    """Represents an official government document"""
    url: str
    title: str
    content: str
    source_country: str
    source_organization: str
    document_type: str
    published_at: Optional[datetime] = None
    language: str = "en"
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        if result['published_at']:
            result['published_at'] = result['published_at'].isoformat()
        return result


# Source definitions for official documents
OFFICIAL_SOURCES = {
    # === USA ===
    "whitehouse_briefing": {
        "name": "White House Briefing Room",
        "url": "https://www.whitehouse.gov/briefing-room/",
        "country": "USA",
        "country_iso": "USA",
        "document_type": "policy_statement",
        "parser": "html",
        "selectors": {
            "articles": "article, .news-item, .briefing-item",
            "title": "h1, h2, .title",
            "content": ".body-content, article p, .content",
            "date": "time, .date, .published"
        }
    },
    "state_dept": {
        "name": "State Department Press",
        "url": "https://www.state.gov/press-releases/",
        "country": "USA",
        "country_iso": "USA",
        "document_type": "diplomatic_statement",
        "parser": "html",
        "selectors": {
            "articles": ".collection-result, article",
            "title": "h2 a, .title",
            "content": ".content, p",
            "date": ".date, time"
        }
    },
    "defense_gov": {
        "name": "Defense.gov News",
        "url": "https://www.defense.gov/News/",
        "country": "USA",
        "country_iso": "USA",
        "document_type": "military_statement",
        "parser": "html",
        "selectors": {
            "articles": ".listing-item, article",
            "title": "h2, .title",
            "content": ".summary, p",
            "date": ".date, time"
        }
    },

    # === CHINA ===
    "xinhua": {
        "name": "Xinhua News Agency",
        "url": "https://english.news.cn/",
        "country": "China",
        "country_iso": "CHN",
        "document_type": "official_statement",
        "parser": "html",
        "selectors": {
            "articles": ".item, .news-item, article",
            "title": "h3, h2, .title",
            "content": ".summary, p",
            "date": ".time, .date"
        }
    },
    "china_mfa": {
        "name": "China Foreign Ministry",
        "url": "https://www.fmprc.gov.cn/mfa_eng/xwfw_665399/s2510_665401/",
        "country": "China",
        "country_iso": "CHN",
        "document_type": "diplomatic_statement",
        "parser": "html",
        "selectors": {
            "articles": ".rebox_news li, article",
            "title": "a, .title",
            "content": ".content, p",
            "date": ".date"
        }
    },
    "china_mod": {
        "name": "China Defense Ministry",
        "url": "http://english.mod.gov.cn/news/",
        "country": "China",
        "country_iso": "CHN",
        "document_type": "military_statement",
        "parser": "html",
        "selectors": {
            "articles": ".news_list li, article",
            "title": "a, .title",
            "content": ".content, p",
            "date": ".date"
        }
    },

    # === EU ===
    "eu_commission": {
        "name": "European Commission Press",
        "url": "https://ec.europa.eu/commission/presscorner/home/en",
        "country": "EU",
        "country_iso": "EUR",  # Special code for EU
        "document_type": "policy_statement",
        "parser": "html",
        "selectors": {
            "articles": ".ecl-content-item, article",
            "title": "h2, .title",
            "content": ".ecl-content-item__description, p",
            "date": ".ecl-content-item__date, time"
        }
    },
    "eu_council": {
        "name": "Council of the European Union",
        "url": "https://www.consilium.europa.eu/en/press/",
        "country": "EU",
        "country_iso": "EUR",
        "document_type": "diplomatic_statement",
        "parser": "html",
        "selectors": {
            "articles": ".views-row, article",
            "title": "h3, .title",
            "content": ".teaser-text, p",
            "date": ".date"
        }
    },
    "eeas": {
        "name": "European External Action Service",
        "url": "https://www.eeas.europa.eu/eeas/press-material_en",
        "country": "EU",
        "country_iso": "EUR",
        "document_type": "foreign_policy",
        "parser": "html",
        "selectors": {
            "articles": ".views-row, article",
            "title": "h2, .title",
            "content": ".field-body, p",
            "date": ".date-display-single"
        }
    },

    # === RUSSIA ===
    "kremlin": {
        "name": "Kremlin Official",
        "url": "http://en.kremlin.ru/events/president/news",
        "country": "Russia",
        "country_iso": "RUS",
        "document_type": "official_statement",
        "parser": "html",
        "selectors": {
            "articles": ".hentry, article",
            "title": ".entry-title, h2",
            "content": ".entry-content, p",
            "date": ".published"
        }
    },
    "tass": {
        "name": "TASS State Agency",
        "url": "https://tass.com/politics",
        "country": "Russia",
        "country_iso": "RUS",
        "document_type": "news_statement",
        "parser": "html",
        "selectors": {
            "articles": ".news-list__item, article",
            "title": ".news-list__title, h2",
            "content": ".news-list__text, p",
            "date": ".news-list__date, time"
        }
    },
    "russia_mfa": {
        "name": "Russia Ministry of Foreign Affairs",
        "url": "https://www.mid.ru/en/press_service/spokesman/official_statement/",
        "country": "Russia",
        "country_iso": "RUS",
        "document_type": "diplomatic_statement",
        "parser": "html",
        "selectors": {
            "articles": ".announce-item, article",
            "title": ".announce-item__title, h2",
            "content": ".announce-item__text, p",
            "date": ".announce-item__date"
        }
    }
}


class OfficialDocumentsCollector(BaseCollector):
    """
    Collector for official government documents from USA, China, EU, Russia.
    Captures policy statements, press releases, and official communications.
    """

    def __init__(self, config=None):
        super().__init__(config)
        self.sources = OFFICIAL_SOURCES
        self.timeout = aiohttp.ClientTimeout(total=45)
        self.headers = {
            "User-Agent": "TITANIUM-VANGUARD/2.0 (Geopolitical Intelligence System)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.logger.info(f"OfficialDocumentsCollector initialized with {len(self.sources)} sources")

    async def fetch(self) -> List[Dict]:
        """
        Fetch documents from all official sources concurrently.

        Returns:
            List of raw document data
        """
        all_documents = []

        # Process sources in batches to avoid overwhelming
        source_items = list(self.sources.items())
        batch_size = 3  # Process 3 sources at a time

        for i in range(0, len(source_items), batch_size):
            batch = source_items[i:i + batch_size]
            tasks = [self._fetch_source(source_id, source_config) for source_id, source_config in batch]

            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        self.logger.warning(f"Source fetch error: {result}")
                    elif result:
                        all_documents.extend(result)

                # Small delay between batches to be respectful
                await asyncio.sleep(1)

            except Exception as e:
                self.logger.error(f"Batch fetch error: {e}")

        self.logger.info(f"Fetched {len(all_documents)} documents from official sources")
        return all_documents

    async def _fetch_source(self, source_id: str, source_config: Dict) -> List[Dict]:
        """
        Fetch documents from a single source.

        Args:
            source_id: Identifier for the source
            source_config: Configuration for the source

        Returns:
            List of raw documents from this source
        """
        documents = []

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    source_config["url"],
                    headers=self.headers,
                    ssl=False  # Some gov sites have cert issues
                ) as response:

                    if response.status != 200:
                        self.logger.warning(
                            f"Source {source_id} returned status {response.status}"
                        )
                        return []

                    content = await response.text()

                    # Parse HTML
                    soup = BeautifulSoup(content, "html.parser")

                    # Remove noise
                    for element in soup(["script", "style", "nav", "footer", "header"]):
                        element.decompose()

                    # Extract articles based on selectors
                    selectors = source_config.get("selectors", {})
                    articles = soup.select(selectors.get("articles", "article"))[:10]  # Limit to 10 per source

                    for article in articles:
                        try:
                            doc = self._extract_document(article, source_config, selectors)
                            if doc and doc.get("title"):
                                doc["source_id"] = source_id
                                documents.append(doc)
                        except Exception as e:
                            self.logger.debug(f"Error extracting article: {e}")
                            continue

                    self.logger.debug(f"Source {source_id}: extracted {len(documents)} documents")

        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout fetching {source_id}")
        except aiohttp.ClientError as e:
            self.logger.warning(f"HTTP error fetching {source_id}: {e}")
        except Exception as e:
            self.logger.warning(f"Error fetching {source_id}: {e}")

        return documents

    def _extract_document(self, article, source_config: Dict, selectors: Dict) -> Optional[Dict]:
        """
        Extract document data from an HTML article element.

        Args:
            article: BeautifulSoup element
            source_config: Source configuration
            selectors: CSS selectors for extraction

        Returns:
            Document data dict or None
        """
        # Extract title
        title_elem = article.select_one(selectors.get("title", "h2"))
        title = title_elem.get_text(strip=True) if title_elem else None

        if not title or len(title) < 10:
            return None

        # Extract content/summary
        content_elem = article.select_one(selectors.get("content", "p"))
        content = content_elem.get_text(strip=True) if content_elem else ""

        # Extract date
        date_elem = article.select_one(selectors.get("date", "time"))
        date_str = date_elem.get_text(strip=True) if date_elem else None

        # Extract URL
        link = article.find("a", href=True)
        url = link["href"] if link else None

        # Make URL absolute if relative
        if url and not url.startswith("http"):
            base_url = source_config["url"]
            if url.startswith("/"):
                # Get domain from base URL
                from urllib.parse import urlparse
                parsed = urlparse(base_url)
                url = f"{parsed.scheme}://{parsed.netloc}{url}"
            else:
                url = f"{base_url.rstrip('/')}/{url}"

        return {
            "title": title[:500],
            "content": content[:5000] if content else "",
            "url": url or source_config["url"],
            "date_str": date_str,
            "source_name": source_config["name"],
            "source_country": source_config["country"],
            "source_country_iso": source_config["country_iso"],
            "document_type": source_config["document_type"],
        }

    async def parse(self, raw_data: List[Dict]) -> List[OfficialDocument]:
        """
        Parse raw document data into OfficialDocument objects.

        Args:
            raw_data: Raw document dictionaries

        Returns:
            List of OfficialDocument objects
        """
        documents = []
        seen_urls = set()

        for doc in raw_data:
            try:
                url = doc.get("url", "")

                # Skip duplicates
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Parse date
                published_at = self._parse_date(doc.get("date_str"))

                official_doc = OfficialDocument(
                    url=url,
                    title=doc.get("title", "Untitled")[:500],
                    content=doc.get("content", "")[:10000],
                    source_country=doc.get("source_country_iso", "UNK"),
                    source_organization=doc.get("source_name", "Unknown"),
                    document_type=doc.get("document_type", "official_statement"),
                    published_at=published_at,
                    language=self._detect_language(doc.get("source_country", "")),
                    metadata={
                        "source_id": doc.get("source_id"),
                        "source_country_name": doc.get("source_country"),
                        "collected_at": datetime.now(timezone.utc).isoformat()
                    }
                )

                documents.append(official_doc)

            except Exception as e:
                self.logger.warning(f"Error parsing document: {e}")
                continue

        self.logger.info(f"Parsed {len(documents)} official documents")
        return documents

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime"""
        if not date_str:
            return datetime.now(timezone.utc)

        # Common date formats
        formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%B %d, %Y",
            "%d %B %Y",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%d.%m.%Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        return datetime.now(timezone.utc)

    def _detect_language(self, country: str) -> str:
        """Detect language based on country"""
        language_map = {
            "China": "zh",
            "Russia": "ru",
            "USA": "en",
            "EU": "en",
        }
        return language_map.get(country, "en")

    async def save(self, documents: List[OfficialDocument]) -> int:
        """
        Save official documents to the database.

        Args:
            documents: List of OfficialDocument objects

        Returns:
            Number of documents saved
        """
        saved = 0

        try:
            from sqlalchemy import text

            with self.db.session() as session:
                for doc in documents:
                    try:
                        # Check if document already exists by URL
                        result = session.execute(
                            text("SELECT id FROM official_documents WHERE url = :url"),
                            {"url": doc.url}
                        )
                        existing = result.fetchone()

                        if existing:
                            self.logger.debug(f"Document already exists: {doc.url[:50]}...")
                            continue

                        # Insert new document
                        session.execute(
                            text("""
                                INSERT INTO official_documents (
                                    url, title, content, source_country,
                                    source_organization, document_type,
                                    published_at, language, metadata,
                                    collected_at, relevance_score
                                ) VALUES (
                                    :url, :title, :content, :source_country,
                                    :source_organization, :document_type,
                                    :published_at, :language, :metadata,
                                    :collected_at, :relevance_score
                                )
                            """),
                            {
                                "url": doc.url,
                                "title": doc.title,
                                "content": doc.content,
                                "source_country": doc.source_country if doc.source_country != "EUR" else None,
                                "source_organization": doc.source_organization,
                                "document_type": doc.document_type,
                                "published_at": doc.published_at,
                                "language": doc.language,
                                "metadata": json.dumps(doc.metadata, ensure_ascii=False) if doc.metadata else None,
                                "collected_at": datetime.now(timezone.utc),
                                "relevance_score": 0.8  # High relevance for official sources
                            }
                        )

                        session.commit()
                        saved += 1

                    except Exception as e:
                        session.rollback()
                        self.logger.warning(f"Error saving document {doc.url[:50]}: {e}")
                        continue

            self.logger.info(f"Saved {saved} official documents")

        except Exception as e:
            self.logger.error(f"Error in save: {e}")

        return saved

    async def validate(self, doc) -> bool:
        """Validate an official document"""
        if not hasattr(doc, 'url') or not doc.url:
            return False
        if not hasattr(doc, 'title') or not doc.title or len(doc.title) < 10:
            return False
        return True

    async def run(self) -> Dict:
        """
        Execute the full collection pipeline.

        Returns:
            Statistics about the collection run
        """
        try:
            self.logger.info(f"Starting {self.name}...")
            start_time = datetime.now(timezone.utc)

            # Fetch
            raw_data = await self.fetch()
            self.logger.info(f"Fetched {len(raw_data)} raw documents")

            # Parse
            documents = await self.parse(raw_data)
            self.logger.info(f"Parsed {len(documents)} documents")

            # Validate
            valid_docs = [doc for doc in documents if await self.validate(doc)]
            self.logger.info(f"Validated {len(valid_docs)}/{len(documents)} documents")

            # Save
            saved = await self.save(valid_docs)

            # Stats
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.last_run = datetime.now(timezone.utc)
            self.events_collected = saved

            stats = {
                "collector": self.name,
                "status": "success",
                "sources_processed": len(self.sources),
                "raw_fetched": len(raw_data),
                "parsed": len(documents),
                "valid": len(valid_docs),
                "saved": saved,
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": self.last_run.isoformat(),
            }

            self.logger.info(f"{self.name} completed: {saved} documents saved")
            return stats

        except Exception as e:
            self.logger.error(f"Error in run: {e}", exc_info=True)
            self.last_error = str(e)
            return {
                "collector": self.name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    def get_sources_by_country(self, country: str) -> List[Dict]:
        """Get all sources for a specific country"""
        return [
            {"id": k, **v}
            for k, v in self.sources.items()
            if v.get("country") == country
        ]


# Convenience function for standalone testing
async def main():
    """Test the collector"""
    collector = OfficialDocumentsCollector()
    result = await collector.run()
    print(f"Collection result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
