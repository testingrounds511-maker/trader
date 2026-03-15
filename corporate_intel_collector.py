"""
TITANIUM V2 - Corporate Intelligence Collector
"""
import asyncio
from newsapi import NewsApiClient
from datetime import datetime, timedelta
from typing import List, Dict

from collectors.base import BaseCollector
from models.corporate_intelligence import CorporateIntelligence
from sqlalchemy.orm import Session

class CorporateIntelCollector(BaseCollector):
    
    def __init__(self, config=None):
        super().__init__(config)
        self.newsapi = NewsApiClient(api_key=self.config.news_api_key)
        self.TARGET_COMPANIES = {
            "Codelco": {"country": "CL", "sector": "Mining"},
            "SQM": {"country": "CL", "sector": "Chemicals"},
            "BHP": {"country": "AU", "sector": "Mining"},
            "Rio Tinto": {"country": "GB", "sector": "Mining"},
            "Glencore": {"country": "CH", "sector": "Commodities"},
            "Tesla": {"country": "US", "sector": "Automotive"},
            "BYD": {"country": "CN", "sector": "Automotive"},
            "Samsung SDI": {"country": "KR", "sector": "Electronics"},
            "LG Energy Solution": {"country": "KR", "sector": "Electronics"},
        }

    async def fetch(self) -> List[Dict]:
        """
        Fetches news articles for target companies from NewsAPI.
        """
        all_articles = []
        for company, meta in self.TARGET_COMPANIES.items():
            try:
                self.logger.info(f"Fetching news for {company}...")
                query = f'"{company}" AND (earnings OR "sec filing" OR expansion OR "joint venture" OR lawsuit OR "government contract")'
                
                def get_news():
                    return self.newsapi.get_everything(
                        q=query,
                        language='en',
                        sort_by='publishedAt',
                        page_size=10
                    )

                response = await asyncio.to_thread(get_news)

                if response['status'] == 'ok':
                    for article in response['articles']:
                        article['company_name'] = company
                        article['company_meta'] = meta
                        all_articles.append(article)
                else:
                    self.logger.error(f"NewsAPI error for {company}: {response.get('message')}")

            except Exception as e:
                self.logger.error(f"Error fetching news for {company}: {e}")

        self.logger.info(f"Fetched {len(all_articles)} total articles.")
        return all_articles

    async def parse(self, raw_data: List[Dict]) -> List[CorporateIntelligence]:
        """
        Parses raw article data into CorporateIntelligence model objects.
        """
        intels = []
        for article in raw_data:
            published_date = datetime.strptime(article['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').date()

            intel = CorporateIntelligence(
                company_name=article['company_name'],
                ticker=article['company_meta'].get('ticker'),
                country_hq=article['company_meta'].get('country'),
                industry=article['company_meta'].get('sector'),
                sector=article['company_meta'].get('sector'),
                intelligence_type='news',
                source_url=article['url'],
                title=article['title'],
                summary=article.get('description'),
                published_date=published_date,
                # Sentiment and topics would be filled by a processing step
            )
            intels.append(intel)
        return intels

    async def save(self, intels: List[CorporateIntelligence]) -> int:
        """
        Saves CorporateIntelligence objects to the database, avoiding duplicates.
        """
        saved_count = 0
        with self.db.session() as session:
            for intel in intels:
                try:
                    # Avoid duplicates based on company, url, and date
                    existing = session.query(CorporateIntelligence).filter_by(
                        company_name=intel.company_name,
                        source_url=intel.source_url,
                        published_date=intel.published_date
                    ).first()

                    if not existing:
                        session.add(intel)
                        session.commit()
                        saved_count += 1
                except Exception as e:
                    self.logger.error(f"Error saving corporate intel for {intel.company_name}: {e}")
                    session.rollback()
        
        self.logger.info(f"Saved {saved_count} new corporate intelligence items.")
        return saved_count
    
    async def run(self) -> Dict:
        """
        Custom run method to orchestrate the corporate intel collection.
        """
        try:
            self.logger.info(f"Starting {self.name}...")
            start_time = datetime.utcnow()
            
            raw_data = await self.fetch()
            intels = await self.parse(raw_data)
            saved = await self.save(intels)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            return {
                "collector": self.name,
                "status": "success",
                "fetched": len(raw_data),
                "parsed": len(intels),
                "saved": saved,
                "elapsed": elapsed
            }
        except Exception as e:
            self.logger.error(f"Error in {self.name} run: {e}", exc_info=True)
            return {"collector": self.name, "status": "error", "error": str(e)}

