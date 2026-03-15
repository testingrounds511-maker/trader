"""
TITANIUM VANGUARD - GDELT Collector
Recolecta eventos geopolíticos de GDELT v2 API
"""

import aiohttp
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import json

from collectors.base import BaseCollector
from models import Event


class GDELTCollector(BaseCollector):
    """
    Collector para GDELT (Global Event Data on Location and Tone)
    Obtiene eventos geopolíticos de alta relevancia
    
    Documentación: https://api.gdeltproject.org/api/v2/
    """
    
    def __init__(self, config=None):
        """Inicializa GDELT Collector"""
        super().__init__(config)
        self.base_url = self.config.gdelt_base_url
        self.timeout = aiohttp.ClientTimeout(total=self.config.gdelt_timeout)
        self.batch_size = self.config.gdelt_batch_size

        # Validar URL base de GDELT
        if self.base_url and "gdeltproject.org" not in self.base_url:
            self.logger.warning(f"URL base sospechosa: {self.base_url} - debe ser https://api.gdeltproject.org/api/v2")

        self.logger.info(f"GDELTCollector inicializado: {self.base_url}")
    
    async def fetch(self) -> List[Dict]:
        """
        Obtiene eventos de GDELT API
        
        Returns:
            List[Dict]: Eventos crudos de GDELT
        """
        try:
            self.logger.info("Fetching eventos de GDELT...")
            
            # Búsqueda de últimas 24 horas
            now = datetime.now(timezone.utc)
            yesterday = now - timedelta(days=1)
            
            # Parámetros de búsqueda (query simplificado para mayor compatibilidad)
            params = {
                "query": "(military OR conflict OR diplomacy OR china OR russia OR ukraine) sourcelang:eng",
                "format": "json",
                "maxrecords": self.batch_size,
                "sort": "DateDesc",
                "startdatetime": yesterday.strftime("%Y%m%d%H%M%S"),
                "enddatetime": now.strftime("%Y%m%d%H%M%S"),
                "mode": "ArtList"
            }
            
            self.logger.debug(f"Parámetros GDELT: {params}")
            
            # Hacer request
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # GDELT v2 DOC API endpoint para búsqueda de artículos
                url = f"{self.base_url}/doc/doc"

                self.logger.debug(f"Requesting GDELT: {url}")

                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        self.logger.error(f"GDELT API error {response.status}: {response_text[:300]}")
                        return []

                    data = await response.json()

                    # Validar respuesta de GDELT
                    if not isinstance(data, dict):
                        self.logger.error(f"GDELT returned invalid data type: {type(data)}")
                        return []

                    # Extraer artículos
                    articles = data.get("articles", [])
                    if not articles:
                        self.logger.warning("GDELT returned 0 articles")
                    else:
                        self.logger.info(f"Obtenidos {len(articles)} artículos de GDELT")

                    return articles
        
        except asyncio.TimeoutError:
            self.logger.error(f"GDELT request timeout after {self.config.gdelt_timeout}s")
            return []
        except aiohttp.ClientError as e:
            self.logger.error(f"GDELT network error: {e}")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"GDELT returned invalid JSON: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching GDELT: {type(e).__name__}: {e}")
            return []
    
    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        """
        Convierte datos de GDELT a Event objects
        
        Args:
            raw_data: Artículos crudos de GDELT
        
        Returns:
            List[Event]: Eventos parseados
        """
        events = []
        
        for i, article in enumerate(raw_data):
            try:
                # Mapear campos GDELT a Event
                event_id = f"gdelt_{article.get('url', '').replace('/', '_')[:100]}"
                
                event_date = (
                    self._parse_date(article.get("datePublished"))
                    or self._parse_date(article.get("dateAdded"))
                    or datetime.now(timezone.utc)
                )
                published_date = self._parse_date(article.get("dateAdded")) or event_date

                event = Event(
                    id=event_id,
                    title=article.get("title", "Sin título"),
                    description=article.get("summary", article.get("description", "")),
                    source_url=article.get("url"),
                    source_name=article.get("source", "GDELT"),
                    
                    # Fechas
                    event_date=event_date,
                    published_date=published_date,
                    
                    # Ubicación
                    country=self._extract_country(article),
                    region=self._extract_region(article),
                    
                    # Clasificación
                    event_type=self._classify_event_type(article),
                    category="news",
                    
                    # Relevancia (estimación basada en longitud y contenido)
                    relevance_score=self._calculate_relevance(article),
                    
                    # Metadata
                    language=article.get("language", "en"),
                    tags=self._extract_tags(article),
                    raw_data=article,
                )
                
                events.append(event)
            
            except Exception as e:
                self.logger.warning(f"Error parseando artículo {i}: {e}")
                continue
        
        self.logger.info(f"Parseados {len(events)} eventos de {len(raw_data)} artículos")
        return events
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parsea fechas de GDELT"""
        if not date_str:
            return None
        
        try:
            # GDELT usa formato ISO 8601
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except:
            self.logger.warning(f"No puedo parsear fecha: {date_str}")
            return None
    
    def _extract_country(self, article: Dict) -> Optional[str]:
        """Extrae país del artículo"""
        # Buscar en campos de ubicación
        for field in ["country", "geo", "location"]:
            if field in article:
                return article[field]
        
        # Default basado en contenido
        return None
    
    def _extract_region(self, article: Dict) -> Optional[str]:
        """Extrae región del artículo"""
        regions = {
            "Chile": "South America",
            "Peru": "South America",
            "Argentina": "South America",
            "China": "Asia-Pacific",
            "Japan": "Asia-Pacific",
            "India": "Asia-Pacific",
        }
        
        country = self._extract_country(article)
        return regions.get(country)
    
    def _classify_event_type(self, article: Dict) -> str:
        """Clasifica el tipo de evento"""
        title_lower = article.get("title", "").lower()
        
        if any(word in title_lower for word in ["conflict", "war", "attack", "military"]):
            return "conflict"
        elif any(word in title_lower for word in ["diplomacy", "meeting", "summit", "agreement"]):
            return "diplomacy"
        elif any(word in title_lower for word in ["trade", "economic", "commerce", "tariff"]):
            return "economic"
        elif any(word in title_lower for word in ["protest", "demonstration", "strike"]):
            return "unrest"
        else:
            return "other"
    
    def _calculate_relevance(self, article: Dict) -> float:
        """Calcula score de relevancia (0.0 - 1.0)"""
        score = 0.5  # Base
        
        # Factores que aumentan relevancia
        if article.get("summary"):
            score += 0.2
        
        if article.get("source") in ["Reuters", "AP", "BBC", "AFP"]:
            score += 0.2
        
        # Clamp entre 0 y 1
        return min(1.0, max(0.0, score))
    
    def _extract_tags(self, article: Dict) -> List[str]:
        """Extrae tags del artículo"""
        tags = []
        
        # De keywords si existen
        if "keywords" in article:
            tags.extend(article["keywords"].split(","))
        
        # Basado en contenido
        title_lower = article.get("title", "").lower()
        
        if "china" in title_lower:
            tags.append("china")
        if "chile" in title_lower:
            tags.append("chile")
        if "usa" in title_lower or "united states" in title_lower:
            tags.append("usa")
        
        return list(set(tags))  # Remover duplicados
