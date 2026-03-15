"""
TITANIUM VANGUARD - News Collector
Recolecta noticias de NewsAPI
"""

import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
import hashlib

from collectors.base import BaseCollector
from models import Event


class NewsCollector(BaseCollector):
    """
    Collector para NewsAPI (https://newsapi.org)
    Obtiene noticias de múltiples fuentes internacionales
    """
    
    def __init__(self, config=None):
        """Inicializa News Collector"""
        super().__init__(config)
        self.api_key = self.config.news_api_key
        self.base_url = self.config.news_api_url
        self.timeout = aiohttp.ClientTimeout(total=self.config.collector_timeout)

        if not self.api_key:
            self.logger.warning("NEWS_API_KEY no configurada - collector deshabilitado")

        # Validar que la URL es correcta (debe ser https://newsapi.org/v2)
        if self.base_url and "newsapi.org" not in self.base_url:
            self.logger.warning(f"URL base sospechosa: {self.base_url} - debe ser https://newsapi.org/v2")

        self.logger.info(f"NewsCollector inicializado: {self.base_url}")
    
    async def fetch(self) -> List[Dict]:
        """
        Obtiene artículos de NewsAPI
        
        Returns:
            Lista de artículos crudos
        """
        if not self.api_key:
            self.logger.warning("NewsAPI key no disponible")
            return []
        
        try:
            self.logger.info("Fetching noticias de NewsAPI...")
            
            # Keywords de inteligencia geopolítica
            keywords = [
                "geopolitical crisis",
                "military conflict",
                "diplomatic tension",
                "border dispute",
                "sanctions",
                "international relations",
                "trade war",
                "strategic alliance",
            ]
            
            articles = []
            
            for keyword in keywords:
                try:
                    params = {
                        "q": keyword,
                        "apiKey": self.api_key,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "pageSize": 20,
                    }
                    
                    async with aiohttp.ClientSession(timeout=self.timeout) as session:
                        async with session.get(f"{self.base_url}/everything", params=params) as response:
                            if response.status == 200:
                                data = await response.json()

                                # Validar respuesta de NewsAPI
                                if data.get("status") != "ok":
                                    error_msg = data.get("message", "Unknown error")
                                    self.logger.error(f"NewsAPI returned error status: {error_msg}")
                                    continue

                                fetched_articles = data.get("articles", [])
                                if fetched_articles:
                                    articles.extend(fetched_articles)
                                    self.logger.debug(f"Keyword '{keyword}': {len(fetched_articles)} artículos")
                                else:
                                    self.logger.debug(f"Keyword '{keyword}': 0 artículos")

                            elif response.status == 429:
                                self.logger.warning(f"NewsAPI rate limit alcanzado - pausando requests")
                                break  # Salir del loop de keywords

                            elif response.status == 401:
                                response_text = await response.text()
                                self.logger.error(f"NewsAPI authentication error: {response.status} - {response_text}")
                                return []  # API key inválida, no continuar

                            else:
                                response_text = await response.text()
                                self.logger.warning(f"NewsAPI error {response.status}: {response_text[:200]}")
                
                except Exception as e:
                    self.logger.warning(f"Error fetching keyword '{keyword}': {e}")
                    continue
            
            # Remover duplicados por URL
            seen_urls = set()
            unique_articles = []
            
            for article in articles:
                url = article.get("url", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique_articles.append(article)
            
            self.logger.info(f"Obtenidos {len(unique_articles)} artículos únicos de NewsAPI")
            return unique_articles
        
        except Exception as e:
            self.logger.error(f"Error en fetch: {e}")
            return []
    
    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        """
        Convierte artículos de NewsAPI a Event objects
        
        Args:
            raw_data: Artículos crudos de NewsAPI
        
        Returns:
            Lista de Event objects
        """
        events = []
        
        for article in raw_data:
            try:
                # Crear ID único basado en URL
                url = article.get("url", "")
                event_id = f"news_{hashlib.md5(url.encode()).hexdigest()[:16]}"
                
                # Extraer país del título/descripción
                country = self._extract_country(article)
                region = self._extract_region(country)
                
                # Clasificar tipo de evento
                event_type = self._classify_event_type(article)
                
                title = (article.get("title") or "Sin título")[:500]
                description_text = article.get("description") or ""
                content_text = article.get("content") or ""
                description = description_text if description_text else content_text[:1000]

                event = Event(
                    id=event_id,
                    title=title,
                    description=description,
                    source_url=url,
                    source_name=article.get("source", {}).get("name", "NewsAPI"),
                    
                    # Fechas
                    event_date=self._parse_date(article.get("publishedAt")),
                    published_date=self._parse_date(article.get("publishedAt")) or datetime.now(timezone.utc),
                    
                    # Ubicación
                    country=country,
                    region=region,
                    
                    # Clasificación
                    event_type=event_type,
                    category="news",
                    
                    # Relevancia basada en keywords
                    relevance_score=self._calculate_relevance(article),
                    
                    # Metadata
                    language=article.get("language", "en"),
                    tags=self._extract_tags(article),
                    raw_data=article,
                )
                
                events.append(event)
            
            except Exception as e:
                self.logger.warning(f"Error parseando artículo: {e}")
                continue
        
        self.logger.info(f"Parseados {len(events)} eventos de {len(raw_data)} artículos")
        return events
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parsea fechas ISO 8601 de NewsAPI"""
        if not date_str:
            return None
        
        try:
            # NewsAPI usa ISO 8601: 2024-01-29T10:30:00Z
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except:
            return None
    
    def _extract_country(self, article: Dict) -> Optional[str]:
        """Extrae país mencionado en el artículo"""
        title = article.get("title") or ""
        description = article.get("description") or ""
        text = f"{title} {description}".lower()
        
        countries_keywords = {
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
        
        for keyword, country in countries_keywords.items():
            if keyword in text:
                return country
        
        return None
    
    def _extract_region(self, country: Optional[str]) -> Optional[str]:
        """Mapea país a región"""
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
    
    def _classify_event_type(self, article: Dict) -> str:
        """Clasifica tipo de evento"""
        title = article.get("title") or ""
        description = article.get("description") or ""
        text = f"{title} {description}".lower()
        
        if any(word in text for word in ["military", "conflict", "war", "attack", "troops"]):
            return "military"
        elif any(word in text for word in ["trade", "tariff", "export", "commerce", "economic"]):
            return "economic"
        elif any(word in text for word in ["diplomatic", "meeting", "summit", "agreement", "negotiation"]):
            return "diplomacy"
        elif any(word in text for word in ["sanction", "embargo", "restriction"]):
            return "sanctions"
        else:
            return "geopolitical"
    
    def _calculate_relevance(self, article: Dict) -> float:
        """Calcula relevancia del artículo"""
        score = 0.5  # Base
        
        # Factores que aumentan relevancia
        if article.get("description"):
            score += 0.15
        
        if article.get("urlToImage"):
            score += 0.1
        
        # Fuentes confiables
        trusted_sources = ["Reuters", "AP", "BBC", "AFP", "The Guardian", "The Times", "Financial Times"]
        source_name = article.get("source", {}).get("name", "")
        
        if any(trusted in source_name for trusted in trusted_sources):
            score += 0.25
        
        return min(1.0, max(0.0, score))
    
    def _extract_tags(self, article: Dict) -> List[str]:
        """Extrae tags del artículo"""
        tags = []
        title = article.get("title") or ""
        description = article.get("description") or ""
        text = f"{title} {description}".lower()
        
        tag_keywords = {
            "military": ["military", "defense", "army", "troops", "weapons"],
            "economic": ["economic", "trade", "commerce", "tariff", "business"],
            "diplomatic": ["diplomatic", "summit", "negotiation", "agreement"],
            "security": ["security", "threat", "conflict", "crisis"],
            "geopolitical": ["geopolitical", "strategic", "region"],
        }
        
        for tag, keywords in tag_keywords.items():
            if any(kw in text for kw in keywords):
                tags.append(tag)
        
        return list(set(tags))
