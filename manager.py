"""
TITANIUM VANGUARD - Collector Manager
Orquesta la ejecución de múltiples collectors

Phase 1: GDELT, NewsAPI, Reddit, Twitter
Phase 2: OfficialDocuments, Sanctions, Military, Financial
"""

import asyncio
import os
from datetime import datetime
from typing import Dict, List, Optional

from core.config import get_settings
from core.logger import get_logger

# Phase 1 Collectors
from collectors.gdelt_collector import GDELTCollector
from collectors.news_collector import NewsCollector
from collectors.reddit_rss_collector import RedditRSSCollector

# Phase 2 Collectors
from collectors.official_documents_collector import OfficialDocumentsCollector
from collectors.sanctions_tracker import SanctionsTracker
from collectors.military_procurement_collector import MilitaryProcurementCollector
from collectors.financial_intelligence_collector import FinancialIntelligenceCollector


class CollectorManager:
    """
    Gerencia la ejecución de todos los collectors
    Ejecuta en paralelo, maneja errores, reporta estado
    """
    
    def __init__(self, config=None):
        """
        Inicializa el manager
        
        Args:
            config: Settings instance
        """
        self.config = config or get_settings()
        self.logger = get_logger(__name__)
        
        # Instanciar collectors activos
        self.collectors = {}

        # GDELT - siempre activo (público)
        try:
            self.collectors["gdelt"] = GDELTCollector(self.config)
            self.logger.info("GDELT Collector activado")
        except Exception as e:
            self.logger.error(f"GDELT Collector fallo: {e}")

        # News API - requiere API key
        try:
            self.collectors["newsapi"] = NewsCollector(self.config)
            self.logger.info("NewsAPI Collector activado")
        except Exception as e:
            self.logger.error(f"NewsAPI Collector fallo: {e}")

        # Reddit - prefer RSS when no credentials or when forced
        try:
            if self._should_use_reddit_rss():
                self.collectors["reddit"] = RedditRSSCollector(self.config)
                self.logger.info("Reddit RSS Collector activado (sin credenciales)")
            else:
                from collectors.reddit_collector import RedditCollector
                self.collectors["reddit"] = RedditCollector(self.config)
                self.logger.info("Reddit Collector activado")
        except ImportError:
            # Fallback to RSS if asyncpraw is missing
            try:
                self.collectors["reddit"] = RedditRSSCollector(self.config)
                self.logger.info("Reddit RSS Collector activado (fallback)")
            except Exception as e:
                self.logger.warning(f"Reddit RSS Collector fallo: {e}")
        except Exception as e:
            self.logger.warning(f"Reddit Collector fallo: {e}")

        # Twitter - requiere credenciales
        try:
            from collectors.twitter_collector import TwitterCollector
            if hasattr(self.config, 'twitter_bearer_token') and self.config.twitter_bearer_token and self.config.twitter_bearer_token != "your_bearer_token_here":
                self.collectors["twitter"] = TwitterCollector(self.config)
                self.logger.info("Twitter Collector activado")
            else:
                self.logger.warning("Twitter Collector: requiere API keys en .env")
        except ImportError:
            self.logger.warning("Twitter Collector no disponible: instala tweepy")
        except Exception as e:
            self.logger.warning(f"Twitter Collector fallo: {e}")

        # ===== PHASE 2 COLLECTORS =====

        # Official Documents Collector - siempre activo (scraping publico)
        try:
            self.collectors["official_documents"] = OfficialDocumentsCollector(self.config)
            self.logger.info("Official Documents Collector activado")
        except Exception as e:
            self.logger.warning(f"Official Documents Collector fallo: {e}")

        # Sanctions Tracker - siempre activo (datos publicos)
        try:
            self.collectors["sanctions"] = SanctionsTracker(self.config)
            self.logger.info("Sanctions Tracker activado")
        except Exception as e:
            self.logger.warning(f"Sanctions Tracker fallo: {e}")

        # Military Procurement Collector - siempre activo
        try:
            self.collectors["military"] = MilitaryProcurementCollector(self.config)
            self.logger.info("Military Procurement Collector activado")
        except Exception as e:
            self.logger.warning(f"Military Procurement Collector fallo: {e}")

        # Financial Intelligence Collector - siempre activo (Yahoo Finance no requiere API key)
        try:
            self.collectors["financial"] = FinancialIntelligenceCollector(self.config)
            self.logger.info("Financial Intelligence Collector activado")
        except Exception as e:
            self.logger.warning(f"Financial Intelligence Collector fallo: {e}")

        # Travel Advisory Collector (WorldMonitor feature) - siempre activo
        try:
            from collectors.travel_advisory_collector import TravelAdvisoryCollector
            self.collectors["travel_advisory"] = TravelAdvisoryCollector()
            self.logger.info("Travel Advisory Collector activado")
        except Exception as e:
            self.logger.warning(f"Travel Advisory Collector fallo: {e}")

        # ===== PHASE 3 COLLECTORS (Commodity & Corporate) =====

        # Commodity Price Collector - Yahoo Finance (no API key required)
        try:
            from collectors.commodity_price_collector import CommodityPriceCollector
            self.collectors["commodity_price"] = CommodityPriceCollector(self.config)
            self.logger.info("Commodity Price Collector activado")
        except Exception as e:
            self.logger.warning(f"Commodity Price Collector fallo: {e}")

        # Trade Agreement Collector - web scraping
        try:
            from collectors.trade_agreement_collector import TradeAgreementCollector
            self.collectors["trade_agreement"] = TradeAgreementCollector(self.config)
            self.logger.info("Trade Agreement Collector activado")
        except Exception as e:
            self.logger.warning(f"Trade Agreement Collector fallo: {e}")

        # Corporate Intelligence Collector - SEC EDGAR / RSS
        try:
            from collectors.corporate_intel_collector import CorporateIntelCollector
            self.collectors["corporate_intel"] = CorporateIntelCollector(self.config)
            self.logger.info("Corporate Intel Collector activado")
        except Exception as e:
            self.logger.warning(f"Corporate Intel Collector fallo: {e}")

        self.logger.info(f"CollectorManager inicializado con {len(self.collectors)} collectors activos")

    def _should_use_reddit_rss(self) -> bool:
        """Decide whether to use RSS based on env or missing credentials."""
        env_value = os.getenv("REDDIT_USE_RSS", "").strip().lower()
        if env_value in ("1", "true", "yes", "on"):
            return True

        client_id = getattr(self.config, "reddit_client_id", None)
        client_secret = getattr(self.config, "reddit_client_secret", None)

        if not client_id or not client_secret:
            return True

        placeholders = {"your_client_id_here", "your_client_secret_here", "placeholder"}
        if client_id in placeholders or client_secret in placeholders:
            return True

        return False
    
    async def collect_all(self) -> Dict:
        """
        Ejecuta todos los collectors en paralelo
        
        Returns:
            Dict: Resultados consolidados
        """
        self.logger.info("Iniciando colección con todos los collectors...")
        
        try:
            # Ejecutar todos en paralelo
            tasks = [
                collector.run()
                for collector in self.collectors.values()
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Procesar resultados
            summary = self._process_results(results)
            
            self.logger.info(f"Colección completada: {summary}")
            return summary
        
        except Exception as e:
            self.logger.error(f"Error en collect_all(): {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }
    
    async def collect_by_type(self, collector_type: str) -> Dict:
        """
        Ejecuta un collector específico
        
        Args:
            collector_type: Tipo de collector (gdelt, news, etc)
        
        Returns:
            Dict: Resultado de la ejecución
        """
        if collector_type not in self.collectors:
            error = f"Collector desconocido: {collector_type}"
            self.logger.error(error)
            return {"status": "error", "error": error}
        
        self.logger.info(f"Ejecutando collector: {collector_type}")
        
        try:
            collector = self.collectors[collector_type]
            result = await collector.run()
            return result
        
        except Exception as e:
            self.logger.error(f"Error en {collector_type}: {e}", exc_info=True)
            return {
                "status": "error",
                "collector": collector_type,
                "error": str(e),
            }
    
    def get_status(self) -> Dict[str, Dict]:
        """
        Obtiene estado de todos los collectors
        
        Returns:
            Dict: Estado de cada collector
        """
        status = {}
        
        for name, collector in self.collectors.items():
            status[name] = collector.get_status()
        
        return status
    
    async def run_continuously(self, interval: int = 3600) -> None:
        """
        Ejecuta colección continuamente en intervalos
        
        Args:
            interval: Segundos entre ejecuciones (default: 1 hora)
        """
        self.logger.info(f"Iniciando ejecución continua cada {interval} segundos...")
        
        try:
            while True:
                self.logger.info(f"Ejecución a las {datetime.utcnow().isoformat()}")
                
                await self.collect_all()
                
                self.logger.info(f"Próxima ejecución en {interval} segundos")
                await asyncio.sleep(interval)
        
        except KeyboardInterrupt:
            self.logger.info("Ejecución continua detenida por usuario")
        except Exception as e:
            self.logger.error(f"Error en run_continuously(): {e}", exc_info=True)
    
    def _process_results(self, results: List) -> Dict:
        """
        Procesa resultados de collectors
        
        Args:
            results: Lista de resultados de cada collector
        
        Returns:
            Dict: Resumen consolidado
        """
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_events": 0,
            "total_saved": 0,
            "collectors_success": 0,
            "collectors_failed": 0,
            "collectors": {}
        }
        
        for result in results:
            if isinstance(result, Exception):
                summary["collectors_failed"] += 1
                self.logger.error(f"Exception en collector: {result}")
            elif isinstance(result, dict):
                collector_name = result.get("collector", "unknown")
                summary["collectors"][collector_name] = result
                
                if result.get("status") == "success":
                    summary["collectors_success"] += 1
                    summary["total_events"] += result.get("parsed", 0)
                    summary["total_saved"] += result.get("saved", 0)
                else:
                    summary["collectors_failed"] += 1
        
        return summary
    
    def add_collector(self, name: str, collector) -> None:
        """
        Agrega un nuevo collector al manager
        
        Args:
            name: Nombre del collector
            collector: Instancia de collector
        """
        self.collectors[name] = collector
        self.logger.info(f"Collector agregado: {name}")
    
    def remove_collector(self, name: str) -> bool:
        """
        Remueve un collector
        
        Args:
            name: Nombre del collector
        
        Returns:
            bool: True si fue removido
        """
        if name in self.collectors:
            del self.collectors[name]
            self.logger.info(f"Collector removido: {name}")
            return True
        return False


async def main():
    """Ejemplo de uso"""
    config = get_settings()
    manager = CollectorManager(config)
    
    # Ejecutar todos los collectors una vez
    result = await manager.collect_all()
    print(f"Resultado: {result}")
    
    # O ejecutar continuamente
    # await manager.run_continuously(interval=3600)


if __name__ == "__main__":
    from core.config import get_settings
    
    asyncio.run(main())
