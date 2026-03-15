"""
TITANIUM V2 - Trade Agreement Collector
"""
import json
from datetime import datetime
from typing import List, Dict

from collectors.base import BaseCollector
from models.trade_agreement import TradeAgreement
from sqlalchemy.orm import Session

class TradeAgreementCollector(BaseCollector):

    def __init__(self, config=None):
        super().__init__(config)
        self.seed_file = "data/seed/trade_agreements.json"

    async def fetch(self) -> List[Dict]:
        """
        Loads trade agreement data from a local JSON seed file.
        """
        try:
            with open(self.seed_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.logger.info(f"Loaded {len(data)} trade agreements from {self.seed_file}")
            return data
        except FileNotFoundError:
            self.logger.error(f"Seed file not found: {self.seed_file}")
            return []
        except Exception as e:
            self.logger.error(f"Error loading seed file: {e}")
            return []

    async def parse(self, raw_data: List[Dict]) -> List[TradeAgreement]:
        """
        Parses raw dictionary data into TradeAgreement model objects.
        """
        agreements = []
        for item in raw_data:
            signed_date = datetime.strptime(item['signed_date'], '%Y-%m-%d').date() if item.get('signed_date') else None
            effective_date = datetime.strptime(item['effective_date'], '%Y-%m-%d').date() if item.get('effective_date') else None

            agreement = TradeAgreement(
                name=item['name'],
                short_name=item.get('short_name'),
                status=item.get('status', 'active'),
                agreement_type=item.get('agreement_type'),
                region_scope=item.get('region_scope'),
                member_countries=item.get('member_countries', []),
                signed_date=signed_date,
                effective_date=effective_date,
                description=item.get('description'),
                key_articles=item.get('key_articles'),
                official_url=item.get('official_url'),
                source='seed_data'
            )
            agreements.append(agreement)
        return agreements

    async def save(self, agreements: List[TradeAgreement]) -> int:
        """
        Saves TradeAgreement objects to the database, updating existing ones.
        """
        saved_count = 0
        with self.db.session() as session:
            for agreement in agreements:
                try:
                    existing = session.query(TradeAgreement).filter_by(name=agreement.name).first()
                    if existing:
                        # Update existing
                        existing.short_name = agreement.short_name
                        existing.status = agreement.status
                        existing.agreement_type = agreement.agreement_type
                        existing.region_scope = agreement.region_scope
                        existing.member_countries = agreement.member_countries
                        existing.signed_date = agreement.signed_date
                        existing.effective_date = agreement.effective_date
                        existing.description = agreement.description
                        existing.key_articles = agreement.key_articles
                        existing.official_url = agreement.official_url
                        existing.last_updated = datetime.utcnow()
                    else:
                        # Add new
                        session.add(agreement)
                    
                    session.commit()
                    saved_count += 1
                except Exception as e:
                    self.logger.error(f"Error saving agreement {agreement.name}: {e}")
                    session.rollback()
        
        self.logger.info(f"Saved or updated {saved_count} trade agreements.")
        return saved_count
    
    async def run_once(self):
        """
        Runs the collector one time to seed the database.
        """
        self.logger.info("Running trade agreement seeder...")
        raw_data = await self.fetch()
        if not raw_data:
            return {"status": "failed", "reason": "No data from fetch"}
        
        agreements = await self.parse(raw_data)
        saved = await self.save(agreements)
        
        return {"status": "success", "seeded": saved}

