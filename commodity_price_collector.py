"""
TITANIUM V2 - Commodity Price Collector
"""
import asyncio
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict

from collectors.base import BaseCollector
from models.commodity_snapshot import CommoditySnapshot
from models.event import Event
from sqlalchemy.orm import Session


class CommodityPriceCollector(BaseCollector):
    def __init__(self, config=None):
        super().__init__(config)
        self.COMMODITIES_CONFIG = {
            "copper": {
                "ticker": "HG=F",
                "name": "Copper Futures",
                "unit": "USD/lb",
                "category": "industrial_metal",
                "key_producers": ["CL", "PE", "CD", "ZM", "CN"],
                "key_consumers": ["CN", "US", "DE", "JP", "KR"],
            },
            "lithium": {
                "tickers": ["ALB", "SQM", "LTHM"],
                "etf": "LIT",
                "name": "Lithium (proxy via producers)",
                "unit": "index",
                "category": "battery_metal",
                "key_producers": ["AU", "CL", "AR", "CN"],
                "key_consumers": ["CN", "KR", "JP", "US", "DE"],
            },
            "oil_wti": {
                "ticker": "CL=F",
                "name": "WTI Crude Oil",
                "unit": "USD/bbl",
                "category": "energy",
                "key_producers": ["US", "SA", "RU", "IQ", "AE", "CA"],
                "key_consumers": ["US", "CN", "IN", "JP", "KR"],
            },
            "oil_brent": {
                "ticker": "BZ=F",
                "name": "Brent Crude Oil",
                "unit": "USD/bbl",
                "category": "energy",
                "key_producers": ["SA", "RU", "IQ", "AE", "NO"],
                "key_consumers": ["CN", "IN", "JP", "KR", "DE"],
            },
            "natural_gas": {
                "ticker": "NG=F",
                "name": "Natural Gas",
                "unit": "USD/MMBtu",
                "category": "energy",
                "key_producers": ["US", "RU", "QA", "IR", "CA", "NO"],
                "key_consumers": ["US", "RU", "CN", "IR", "JP"],
            },
            "gold": {
                "ticker": "GC=F",
                "name": "Gold",
                "unit": "USD/oz",
                "category": "precious_metal",
                "key_producers": ["CN", "AU", "RU", "US", "CA"],
                "key_consumers": ["CN", "IN", "US", "DE", "TR"],
            },
            "rare_earths": {
                "tickers": ["MP"],
                "etf": "REMX",
                "name": "Rare Earth Elements (proxy)",
                "unit": "index",
                "category": "strategic_mineral",
                "key_producers": ["CN", "MM", "AU", "US"],
                "key_consumers": ["CN", "JP", "US", "DE", "KR"],
            },
            "uranium": {
                "etf": "URA",
                "tickers": ["CCJ", "UEC"],
                "name": "Uranium (proxy)",
                "unit": "index",
                "category": "nuclear",
                "key_producers": ["KZ", "CA", "AU", "NA", "UZ"],
                "key_consumers": ["US", "FR", "CN", "RU", "KR"],
            },
            "iron_ore": {
                "tickers": ["BHP", "RIO", "VALE"],
                "name": "Iron Ore (proxy via miners)",
                "unit": "index",
                "category": "industrial_metal",
                "key_producers": ["AU", "BR", "CN", "IN"],
                "key_consumers": ["CN", "JP", "IN", "KR", "US"],
            },
        }

    async def fetch(self) -> List[Dict]:
        """
        Fetch commodity data from yfinance.
        Returns a list of dictionaries, each containing data for a commodity.
        """
        all_data = []
        for key, config in self.COMMODITIES_CONFIG.items():
            try:
                ticker_symbol = config.get("ticker") or config.get("etf")
                if not ticker_symbol:
                    self.logger.warning(f"Skipping {key} as no ticker or etf is configured.")
                    continue

                self.logger.info(f"Fetching data for {key} ({ticker_symbol})...")
                ticker = yf.Ticker(ticker_symbol)
                
                def get_history():
                    return ticker.history(period="3mo", interval="1d")

                hist = await asyncio.to_thread(get_history)

                if hist.empty:
                    self.logger.warning(f"No history found for {key} ({ticker_symbol})")
                    continue

                all_data.append({
                    "commodity_key": key,
                    "config": config,
                    "history": hist.reset_index()
                })
            except Exception as e:
                self.logger.error(f"Error fetching data for {key}: {e}")
        return all_data

    async def parse(self, raw_data: List[Dict]) -> List[CommoditySnapshot]:
        """
        Parses raw data from yfinance into CommoditySnapshot objects.
        """
        snapshots = []
        for item in raw_data:
            key = item["commodity_key"]
            config = item["config"]
            hist = item["history"]
            
            # Calculate technical indicators
            hist['pct_change_1d'] = hist['Close'].pct_change(1)
            hist['pct_change_7d'] = hist['Close'].pct_change(7)
            hist['pct_change_30d'] = hist['Close'].pct_change(30)
            hist['sma_20'] = hist['Close'].rolling(window=20).mean()
            hist['sma_50'] = hist['Close'].rolling(window=50).mean()
            hist['volatility_20d'] = hist['pct_change_1d'].rolling(window=20).std() * (252**0.5)

            for _, row in hist.iterrows():
                row_dict = row.to_dict()
                
                # Convert Timestamp to string for JSON serialization
                if 'Date' in row_dict and pd.notna(row_dict['Date']):
                    row_dict['Date'] = row_dict['Date'].isoformat()

                # Replace NaN with None for JSON serialization
                for key, value in row_dict.items():
                    if pd.isna(value):
                        row_dict[key] = None

                snapshot = CommoditySnapshot(
                    commodity_key=key,
                    ticker=config.get("ticker") or config.get("etf"),
                    snapshot_date=row['Date'].date() if pd.notna(row['Date']) else None,
                    price_close=row.get('Close'),
                    price_open=row.get('Open'),
                    price_high=row.get('High'),
                    price_low=row.get('Low'),
                    volume=row.get('Volume'),
                    pct_change_1d=row.get('pct_change_1d'),
                    pct_change_7d=row.get('pct_change_7d'),
                    pct_change_30d=row.get('pct_change_30d'),
                    sma_20=row.get('sma_20'),
                    sma_50=row.get('sma_50'),
                    volatility_20d=row.get('volatility_20d'),
                    unit=config.get("unit"),
                    source="yahoo_finance",
                    raw_data=row_dict,
                )
                snapshots.append(snapshot)
        return snapshots
    
    async def save(self, snapshots: List[CommoditySnapshot]) -> int:
        """
        Saves CommoditySnapshot objects to the database.
        """
        saved_count = 0
        with self.db.session() as session:
            for snapshot in snapshots:
                try:
                    # Check for existing entry
                    existing = session.query(CommoditySnapshot).filter_by(
                        commodity_key=snapshot.commodity_key,
                        snapshot_date=snapshot.snapshot_date
                    ).first()

                    if existing:
                        # Update existing record
                        existing.price_close = snapshot.price_close
                        existing.price_open = snapshot.price_open
                        existing.price_high = snapshot.price_high
                        existing.price_low = snapshot.price_low
                        existing.volume = snapshot.volume
                        existing.pct_change_1d = snapshot.pct_change_1d
                        existing.pct_change_7d = snapshot.pct_change_7d
                        existing.pct_change_30d = snapshot.pct_change_30d
                        existing.sma_20 = snapshot.sma_20
                        existing.sma_50 = snapshot.sma_50
                        existing.volatility_20d = snapshot.volatility_20d
                        existing.raw_data = snapshot.raw_data
                        existing.updated_at = datetime.utcnow()
                    else:
                        # Add new record
                        session.add(snapshot)
                    
                    session.commit()
                    saved_count += 1
                except Exception as e:
                    self.logger.error(f"Error saving snapshot for {snapshot.commodity_key} on {snapshot.snapshot_date}: {e}")
                    session.rollback()
        
        self.logger.info(f"Saved or updated {saved_count} commodity snapshots.")
        return saved_count

    async def run(self) -> Dict:
        """
        Executa el pipeline completo: fetch -> parse -> validate -> save
        
        Returns:
            Dict: Estadísticas de la ejecución
        """
        try:
            self.logger.info(f"Iniciando {self.name}...")
            start_time = datetime.utcnow()
            
            # Fetch
            self.logger.debug("Fetching datos...")
            raw_data = await self.fetch()
            self.logger.info(f"Obtenidos {len(raw_data)} elementos crudos")
            
            # Parse
            self.logger.debug("Parseando datos...")
            snapshots = await self.parse(raw_data)
            self.logger.info(f"Parseados {len(snapshots)} snapshots")
            
            # Save
            self.logger.debug("Guardando snapshots...")
            saved = await self.save(snapshots)
            
            # Estadísticas
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            self.last_run = datetime.utcnow()
            self.events_collected = saved
            
            stats = {
                "collector": self.name,
                "status": "success",
                "raw_data": len(raw_data),
                "parsed": len(snapshots),
                "saved": saved,
                "elapsed_seconds": elapsed,
                "timestamp": self.last_run.isoformat(),
            }
            
            self.logger.info(f"{self.name} completado: {stats}")
            return stats
        
        except Exception as e:
            self.logger.error(f"Error en run(): {e}", exc_info=True)
            self.last_error = str(e)
            return {
                "collector": self.name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

