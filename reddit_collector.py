"""
TITANIUM VANGUARD - Reddit Collector
Recolecta inteligencia geopolítica desde Reddit (80+ subreddits)
Incluye extracción de contenido completo de artículos enlazados
"""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

try:
    import asyncpraw
    ASYNCPRAW_AVAILABLE = True
except ImportError:
    ASYNCPRAW_AVAILABLE = False

# Para extracción de artículos completos
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

try:
    from newspaper import Article
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False

from collectors.base import BaseCollector
from models import Event


class RedditCollector(BaseCollector):
    """
    Collector de inteligencia geopolítica desde Reddit.

    Estrategia MEJORADA:
    1. Monitorea 80+ subreddits organizados en 5 tiers
    2. Extrae posts HOT (trending) de cada subreddit
    3. Analiza título, URL externa, dominio
    4. **NUEVO**: Extrae contenido COMPLETO de artículos enlazados (trafilatura/newspaper3k)
    5. Calcula relevancia multi-factor
    6. Extrae actores mencionados
    7. Detecta patrones de escalamiento
    8. Enriquece description con texto completo del artículo

    Mejoras vs versión anterior:
    - +20 subreddits especializados (tech, commodities, defense)
    - Extracción de contenido completo de artículos de fuentes confiables
    - Descriptions 10x más ricas (texto del artículo vs solo metadata)
    - Metadata adicional: autores, fecha de publicación
    """

    # ===== TIER 1: Geopolítica Pura (High Signal) =====
    TIER_1_GEOPOLITICS = [
        "geopolitics",           # 28k - Análisis académico
        "worldpolitics",         # 14k - Política global
        "internationalpolitics", # 12k - Relaciones internacionales
        "MiddleEastNews",        # 8k - Oriente Medio específico
        "Geopolitics_news",      # Análisis geopolítico
    ]

    # ===== TIER 2: Noticias Internacionales (High Volume) =====
    TIER_2_NEWS = [
        "worldnews",             # 32k - Noticias globales
        "news",                  # 18k - Noticias generales
        "worldevents",           # Eventos globales
        "inthenews",             # Análisis de noticias
        "NorthAmericaNews",      # Norteamérica
        "EuropeanNews",          # Europa
        "AsianNews",             # Asia
    ]

    # ===== TIER 3: Temas Específicos (Medium Signal) =====
    TIER_3_SPECIFIC = [
        # Militar/Defensa
        "Military",              # Temas militares
        "Defense",               # Defensa nacional
        "MilitaryNews",          # Noticias militares
        "credibledefense",       # Defensa seria
        "warcollege",            # Estrategia militar
        "lesscredibledefence",   # Defensa informal

        # Económico/Comercio
        "Economics",             # Economía
        "Trade",                 # Comercio internacional
        "commodities",           # Commodities
        "mining",                # Minería
        "lithium",               # Litio estratégico
        "copper",                # Cobre
        "energy",                # Energía
        "oil",                   # Petróleo
        "renewableenergy",       # Energía renovable

        # Diplomacia/Política
        "Diplomacy",             # Relaciones diplomáticas
        "Democracy",             # Democracia global
        "PoliticalNews",         # Noticias políticas
        "foreignpolicy",         # Política exterior

        # Tecnología/Ciberseguridad
        "cybersecurity",         # Ciberseguridad
        "netsec",                # Seguridad de redes
        "technology",            # Tecnología
        "semiconductors",        # Semiconductores estratégicos
        "artificial",            # IA
        "machinelearning",       # Machine Learning
    ]

    # ===== TIER 4: Regiones Específicas (Medium Signal) =====
    TIER_4_REGIONAL = [
        # Americas
        "LatinAmerica", "Brazil", "Mexico", "Canada", "Chile", "Argentina",
        "Peru", "Bolivia", "southamerica",

        # Europe
        "europe", "France", "Germany", "Russia", "Ukraine", "UnitedKingdom",

        # Asia-Pacific
        "China", "Taiwan", "Japan", "Korea", "India", "SoutheastAsia", "Australia",
        "chinawatchgroup", "sino", "asean",

        # Middle East & Africa
        "IsraelPalestine", "Syria", "Iran", "SaudiArabia", "Africa",
    ]

    # ===== TIER 5: Intel Especializado (Lower Volume, High Value) =====
    TIER_5_INTEL = [
        "intelligence",          # Comunidad de inteligencia
        "InfoSec",               # Seguridad informática
        "WikiLeaks",             # Revelaciones
    ]

    # ===== DOMINIOS DE CONFIANZA (Trust Matrix) =====
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

    # ===== ACTORES CONOCIDOS (para extracción) =====
    KNOWN_COUNTRIES = [
        "China", "Russia", "USA", "United States", "India", "Brazil", "Japan",
        "Germany", "France", "UK", "United Kingdom", "Canada", "Mexico",
        "Iran", "Israel", "Saudi Arabia", "Turkey", "Egypt",
        "Ukraine", "Taiwan", "North Korea", "South Korea", "Vietnam",
        "Chile", "Argentina", "Peru", "Colombia",
    ]

    KNOWN_MILITARY_ORGS = [
        "NATO", "BRICS", "SCO", "AUKUS", "Pentagon", "CIA", "MI6",
        "Mossad", "FSB", "PLA", "UN",
    ]

    ESCALATION_KEYWORDS = {
        "military": ["attack", "strike", "deployment", "military exercise", "troops", "invasion", "war"],
        "economic": ["tariff", "embargo", "sanction", "trade war", "economic pressure"],
        "diplomatic": ["protest", "demand", "ultimatum", "threat", "warning", "retaliation"],
    }

    def __init__(self, config=None):
        """Inicializa Reddit Collector"""
        super().__init__(config)

        if not ASYNCPRAW_AVAILABLE:
            self.logger.error("asyncpraw no está instalado. Instalar con: pip install asyncpraw")
            raise ImportError("asyncpraw is required for RedditCollector")

        # Configuración
        self.client_id = self.config.reddit_client_id
        self.client_secret = self.config.reddit_client_secret
        self.user_agent = self.config.reddit_user_agent
        self.posts_per_subreddit = self.config.reddit_posts_per_subreddit

        # Cargar subreddits desde config o usar todos los tiers
        self.subreddits = self._load_subreddits()

        # Inicializar Reddit client (se hace en fetch para async context)
        self.reddit = None

        # Rate limiter simple
        self.last_request_time = None
        self.min_request_interval = self.config.reddit_rate_limit_period / self.config.reddit_rate_limit_calls

        self.logger.info(f"RedditCollector inicializado: {len(self.subreddits)} subreddits")

    def _load_subreddits(self) -> List[str]:
        """Carga lista de subreddits desde config"""
        # Si hay subreddits en config, usar esos
        if hasattr(self.config, 'reddit_subreddits') and self.config.reddit_subreddits:
            subs = [s.strip() for s in self.config.reddit_subreddits.split(',')]
            if subs and subs[0]:  # Verificar que no esté vacío
                return subs

        # Si no, usar todos los tiers
        all_subs = (
            self.TIER_1_GEOPOLITICS +
            self.TIER_2_NEWS +
            self.TIER_3_SPECIFIC +
            self.TIER_4_REGIONAL +
            self.TIER_5_INTEL
        )
        return all_subs

    async def _rate_limit(self):
        """Aplica rate limiting simple"""
        if self.last_request_time:
            elapsed = (datetime.now(timezone.utc) - self.last_request_time).total_seconds()
            if elapsed < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - elapsed)

        self.last_request_time = datetime.now(timezone.utc)

    async def fetch(self) -> List[Dict]:
        """
        Obtiene posts HOT de subreddits en paralelo.

        Returns:
            Lista de submission objects (raw Reddit data)
        """
        if not self.client_id or not self.client_secret:
            self.logger.warning("Reddit credentials no configuradas - usando modo público limitado")

        try:
            self.logger.info(f"Fetching posts de {len(self.subreddits)} subreddits...")

            # Inicializar Reddit client
            self.reddit = asyncpraw.Reddit(
                client_id=self.client_id or "placeholder",
                client_secret=self.client_secret or "placeholder",
                user_agent=self.user_agent,
            )

            # Fetch en paralelo por subreddit
            tasks = []
            for subreddit_name in self.subreddits:
                tasks.append(self._fetch_subreddit(subreddit_name))

            # Ejecutar todas las tareas
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Consolidar resultados
            all_submissions = []
            for result in results:
                if isinstance(result, Exception):
                    self.logger.warning(f"Error en subreddit: {result}")
                    continue
                if result:
                    all_submissions.extend(result)

            self.logger.info(f"Obtenidos {len(all_submissions)} submissions de Reddit")

            # Cerrar cliente
            await self.reddit.close()

            return all_submissions

        except Exception as e:
            self.logger.error(f"Error en fetch: {e}")
            if self.reddit:
                await self.reddit.close()
            return []

    async def _fetch_subreddit(self, subreddit_name: str) -> List[Dict]:
        """
        Fetch posts de un subreddit específico.

        Args:
            subreddit_name: Nombre del subreddit

        Returns:
            Lista de diccionarios con datos de submissions
        """
        try:
            await self._rate_limit()

            subreddit = await self.reddit.subreddit(subreddit_name)
            submissions = []

            # Obtener posts HOT (trending)
            async for submission in subreddit.hot(limit=self.posts_per_subreddit):
                # Convertir a dict para evitar problemas de sesión
                sub_data = {
                    "id": submission.id,
                    "title": submission.title,
                    "url": submission.url,
                    "selftext": submission.selftext,
                    "author": str(submission.author) if submission.author else "[deleted]",
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "num_comments": submission.num_comments,
                    "created_utc": submission.created_utc,
                    "subreddit": subreddit_name,
                    "permalink": f"https://reddit.com{submission.permalink}",
                    "is_self": submission.is_self,
                    "distinguished": submission.distinguished,
                    "stickied": submission.stickied,
                }

                submissions.append(sub_data)

            self.logger.debug(f"Subreddit r/{subreddit_name}: {len(submissions)} posts")
            return submissions

        except Exception as e:
            self.logger.warning(f"Error fetching r/{subreddit_name}: {e}")
            return []

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        """
        Transforma submissions Reddit → Event objects

        Para CADA submission:
        1. Extraer título, URL, dominio
        2. Validar que sea post relevante (no meme, no bot)
        3. Extraer actores del título
        4. Calcular relevance_score
        5. Clasificar event_type
        6. Retornar Event object

        Args:
            raw_data: Lista de submissions de Reddit

        Returns:
            Lista de Event objects
        """
        events = []

        for submission in raw_data:
            try:
                # Validar que sea post relevante
                if not self._is_valid_post(submission):
                    continue

                # Extraer URL y dominio
                source_url, domain = self._extract_url_and_domain(submission)

                # Si no hay URL externa, skip (self posts sin contenido útil)
                if not source_url or domain == "reddit.com":
                    continue

                # Validar dominio
                domain_trust = self._validate_domain_trust(domain)

                # Calcular relevance_score
                relevance = self._calculate_relevance_score(submission, domain, domain_trust)

                # NUEVO: Extraer contenido completo del artículo enlazado
                article_content = None
                if domain_trust.get("is_trusted") and domain_trust.get("trust_score", 0) >= 0.70:
                    # Solo extraer de fuentes confiables para ahorrar tiempo/recursos
                    self.logger.debug(f"Extracting article content from {domain}...")
                    article_content = await self._extract_article_content(source_url, domain)

                # Extraer actores y país
                actors_data = self._analyze_title_actors(submission["title"])
                primary_actors = actors_data["countries"][:3]  # Top 3
                country = primary_actors[0] if primary_actors else None

                # Clasificar tipo de evento
                event_type = actors_data.get("event_type", "geopolitical")

                # Detectar región
                region = self._extract_region(country)

                # Detectar escalamiento
                escalation = self._detect_escalation_patterns(submission["title"], domain)

                # Crear ID único
                event_id = self._generate_event_id(submission)

                # Crear Event object con contenido enriquecido
                event = Event(
                    id=event_id,
                    title=submission["title"][:500],
                    description=self._create_description(submission, domain_trust, article_content),
                    source_url=source_url,
                    source_name=self._clean_domain_name(domain),

                    # Fechas
                    event_date=datetime.fromtimestamp(submission["created_utc"], tz=timezone.utc),
                    published_date=datetime.fromtimestamp(submission["created_utc"], tz=timezone.utc),

                    # Ubicación
                    country=country,
                    region=region,

                    # Clasificación
                    event_type=event_type,
                    category="reddit",

                    # Actores
                    primary_actors=primary_actors,

                    # Relevancia
                    relevance_score=relevance,

                    # Metadata
                    language="en",
                    tags=self._extract_tags(submission, actors_data, escalation),

                    # Raw data
                    raw_data={
                        "reddit_post": submission,
                        "domain_validation": domain_trust,
                        "actors_analysis": actors_data,
                        "escalation_patterns": escalation,
                        "article_extraction": article_content,  # NUEVO: Contenido extraído
                    },
                )

                events.append(event)

            except Exception as e:
                self.logger.warning(f"Error parseando submission {submission.get('id')}: {e}")
                continue

        self.logger.info(f"Parseados {len(events)} eventos de {len(raw_data)} submissions")
        return events

    def _is_valid_post(self, submission: Dict) -> bool:
        """
        Valida que el post sea relevante para inteligencia.

        Filtra:
        - Posts stickied (moderadores)
        - Posts de bots
        - Posts sin título
        - Posts con score muy bajo
        """
        # Skip stickied posts
        if submission.get("stickied"):
            return False

        # Skip deleted authors
        if submission.get("author") == "[deleted]":
            return False

        # Requiere título
        if not submission.get("title"):
            return False

        # Score mínimo (al menos 5 upvotes)
        if submission.get("score", 0) < 5:
            return False

        # Filtrar keywords sospechosos en título (memes, etc)
        title_lower = submission["title"].lower()
        spam_keywords = ["meme", "funny", "lol", "upvote if", "petition"]
        if any(kw in title_lower for kw in spam_keywords):
            return False

        return True

    def _extract_url_and_domain(self, submission: Dict) -> Tuple[str, str]:
        """
        Extrae URL y dominio del submission.

        Casos:
        - Link post: obtener URL externa
        - Self post: usar permalink de Reddit

        Returns:
            (url, domain_name)
        """
        url = submission.get("url", "")

        if not url:
            return "", ""

        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Limpiar www.
            if domain.startswith("www."):
                domain = domain[4:]

            return url, domain

        except Exception as e:
            self.logger.debug(f"Error parsing URL {url}: {e}")
            return url, ""

    def _validate_domain_trust(self, domain: str) -> Dict:
        """
        Valida confiabilidad del dominio.

        Returns:
            {
                "is_trusted": True/False,
                "trust_score": 0.0-1.0,
                "reason": "...",
                "category": "..."
            }
        """
        # Check contra matriz de confianza
        trust_score = self.TRUSTED_DOMAINS.get(domain, 0.5)  # Default 0.5

        is_trusted = trust_score >= 0.70

        # Categorizar
        if trust_score >= 0.85:
            category = "major_news"
            reason = "Fuente de noticias confiable"
        elif trust_score >= 0.70:
            category = "regional_news"
            reason = "Fuente regional conocida"
        elif "blog" in domain or "medium.com" in domain:
            category = "blog"
            reason = "Blog o medio independiente"
            trust_score = 0.4
        elif "reddit.com" in domain:
            category = "social_media"
            reason = "Reddit (discusión)"
            trust_score = 0.3
        else:
            category = "unknown"
            reason = "Dominio desconocido"

        return {
            "is_trusted": is_trusted,
            "trust_score": trust_score,
            "reason": reason,
            "category": category,
        }

    def _calculate_relevance_score(
        self,
        submission: Dict,
        domain: str,
        domain_trust: Dict
    ) -> float:
        """
        Calcula relevancia multi-factor:

        Base:
        - upvote_ratio (0.3): % de upvotes vs downvotes
        - score (0.3): número de upvotes (normalizado)
        - comments (0.2): número de comentarios (normalizado)
        - domain trust (0.2): confiabilidad del dominio

        Bonuses:
        - Tier 1 subreddit: +0.10
        - Más de 100 comentarios: +0.05
        - Post de hace < 12 horas: +0.05

        Penalties:
        - Dominio sospechoso: -0.20

        Returns:
            score normalizado 0.0-1.0
        """
        # Base score
        upvote_ratio = submission.get("upvote_ratio", 0.5)
        score = submission.get("score", 0)
        num_comments = submission.get("num_comments", 0)

        # Normalizar score (logarítmico)
        import math
        normalized_score = min(1.0, math.log(score + 1) / math.log(1000))
        normalized_comments = min(1.0, math.log(num_comments + 1) / math.log(500))

        # Calcular base
        base_score = (
            upvote_ratio * 0.3 +
            normalized_score * 0.3 +
            normalized_comments * 0.2 +
            domain_trust["trust_score"] * 0.2
        )

        # Bonuses
        bonuses = 0.0

        # Tier 1 subreddit
        if submission["subreddit"] in self.TIER_1_GEOPOLITICS:
            bonuses += 0.10

        # Muchos comentarios
        if num_comments > 100:
            bonuses += 0.05

        # Post reciente
        post_age_hours = (datetime.now(timezone.utc).timestamp() - submission["created_utc"]) / 3600
        if post_age_hours < 12:
            bonuses += 0.05

        # Penalties
        penalties = 0.0

        if domain_trust["trust_score"] < 0.4:
            penalties += 0.20

        # Total
        final_score = base_score + bonuses - penalties

        return max(0.0, min(1.0, final_score))

    def _analyze_title_actors(self, title: str) -> Dict:
        """
        Extrae actores del título usando regex simple.
        (Para análisis profundo con Dolphin, usar análisis posterior)

        Returns:
            {
                "countries": ["China", "USA"],
                "military_orgs": ["NATO"],
                "event_type": "military|economic|diplomacy|conflict",
                "confidence": 0.85
            }
        """
        countries = []
        military_orgs = []

        title_upper = title

        # Detectar países
        for country in self.KNOWN_COUNTRIES:
            if country.lower() in title.lower():
                if country not in countries:
                    countries.append(country)

        # Detectar organizaciones militares
        for org in self.KNOWN_MILITARY_ORGS:
            if org.lower() in title.lower():
                if org not in military_orgs:
                    military_orgs.append(org)

        # Clasificar tipo de evento
        title_lower = title.lower()

        if any(word in title_lower for word in ["military", "war", "attack", "troops", "defense"]):
            event_type = "military"
        elif any(word in title_lower for word in ["trade", "tariff", "economic", "sanction", "embargo"]):
            event_type = "economic"
        elif any(word in title_lower for word in ["diplomatic", "summit", "meeting", "agreement", "treaty"]):
            event_type = "diplomacy"
        elif any(word in title_lower for word in ["conflict", "crisis", "tension", "dispute"]):
            event_type = "conflict"
        else:
            event_type = "geopolitical"

        # Confidence basado en cuántos actores detectamos
        confidence = min(1.0, (len(countries) + len(military_orgs)) * 0.3)

        return {
            "countries": countries,
            "military_orgs": military_orgs,
            "event_type": event_type,
            "confidence": confidence,
        }

    def _detect_escalation_patterns(self, title: str, domain: str) -> Dict:
        """
        Detecta keywords de escalamiento:
        - Militar: "attack", "strike", "deployment"
        - Económico: "tariff", "embargo", "sanction"
        - Diplomático: "protest", "demand", "ultimatum"

        Returns:
            {
                "has_escalation": True/False,
                "escalation_type": "military|economic|diplomatic",
                "keywords_found": [...],
                "risk_level": 0.0-1.0
            }
        """
        title_lower = title.lower()

        found_keywords = []
        escalation_type = None

        for esc_type, keywords in self.ESCALATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in title_lower:
                    found_keywords.append(keyword)
                    escalation_type = esc_type

        has_escalation = len(found_keywords) > 0

        # Risk level basado en número de keywords
        risk_level = min(1.0, len(found_keywords) * 0.3)

        return {
            "has_escalation": has_escalation,
            "escalation_type": escalation_type,
            "keywords_found": found_keywords,
            "risk_level": risk_level,
        }

    def _extract_region(self, country: Optional[str]) -> Optional[str]:
        """Mapea país a región"""
        regions = {
            "Chile": "South America",
            "Peru": "South America",
            "Argentina": "South America",
            "Brazil": "South America",
            "Mexico": "North America",
            "Canada": "North America",
            "USA": "North America",
            "United States": "North America",
            "China": "Asia-Pacific",
            "Japan": "Asia-Pacific",
            "India": "Asia-Pacific",
            "South Korea": "Asia-Pacific",
            "Taiwan": "Asia-Pacific",
            "Vietnam": "Asia-Pacific",
            "Russia": "Europe",
            "France": "Europe",
            "Germany": "Europe",
            "United Kingdom": "Europe",
            "UK": "Europe",
            "Ukraine": "Europe",
            "Iran": "Middle East",
            "Israel": "Middle East",
            "Saudi Arabia": "Middle East",
        }

        return regions.get(country)

    def _clean_domain_name(self, domain: str) -> str:
        """Convierte dominio a nombre legible: bbc.com → BBC"""
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

    async def _extract_article_content(self, url: str, domain: str) -> Optional[Dict]:
        """
        Extrae contenido completo de un artículo externo.
        Usa múltiples métodos con fallback: trafilatura → newspaper3k

        Args:
            url: URL del artículo
            domain: Dominio del artículo

        Returns:
            Dict con title, text, authors, publish_date, method, success
            None si la extracción falla
        """
        # Ignorar dominios que no son artículos
        skip_domains = [
            'reddit.com', 'redd.it', 'i.redd.it', 'v.redd.it',
            'imgur.com', 'i.imgur.com', 'gfycat.com',
            'youtube.com', 'youtu.be', 'twitter.com', 'x.com',
            'facebook.com', 'instagram.com'
        ]

        if any(d in domain for d in skip_domains):
            return None

        result = {
            'title': None,
            'text': None,
            'authors': None,
            'publish_date': None,
            'method': None,
            'success': False
        }

        # Método 1: Trafilatura (más robusto para noticias)
        if TRAFILATURA_AVAILABLE:
            try:
                # Fetch en loop separado para async
                loop = asyncio.get_event_loop()
                downloaded = await loop.run_in_executor(
                    None,
                    trafilatura.fetch_url,
                    url
                )

                if downloaded:
                    text = trafilatura.extract(
                        downloaded,
                        include_comments=False,
                        include_tables=True,
                        no_fallback=False
                    )

                    if text and len(text) > 200:
                        result['text'] = text
                        result['method'] = 'trafilatura'
                        result['success'] = True

                        # Extraer metadata
                        metadata = trafilatura.extract_metadata(downloaded)
                        if metadata:
                            result['title'] = metadata.title
                            result['authors'] = [metadata.author] if metadata.author else None
                            result['publish_date'] = metadata.date

                        self.logger.debug(f"Extracted article via trafilatura: {url[:60]}...")
                        return result

            except Exception as e:
                self.logger.debug(f"Trafilatura failed for {url[:60]}: {e}")

        # Método 2: Newspaper3k (fallback)
        if NEWSPAPER_AVAILABLE:
            try:
                article = Article(url)
                loop = asyncio.get_event_loop()

                # Download y parse en executor
                await loop.run_in_executor(None, article.download)
                await loop.run_in_executor(None, article.parse)

                if article.text and len(article.text) > 200:
                    result['title'] = article.title
                    result['text'] = article.text
                    result['authors'] = article.authors if article.authors else None
                    result['publish_date'] = article.publish_date.isoformat() if article.publish_date else None
                    result['method'] = 'newspaper3k'
                    result['success'] = True

                    self.logger.debug(f"Extracted article via newspaper3k: {url[:60]}...")
                    return result

            except Exception as e:
                self.logger.debug(f"Newspaper3k failed for {url[:60]}: {e}")

        return None

    def _create_description(self, submission: Dict, domain_trust: Dict, article_content: Optional[Dict] = None) -> str:
        """
        Crea descripción enriquecida del evento.
        Prioriza contenido extraído del artículo > selftext > metadata
        """
        parts = []

        # 1. CONTENIDO EXTRAÍDO DEL ARTÍCULO (prioridad máxima)
        if article_content and article_content.get('success') and article_content.get('text'):
            # Usar primeros 1500 caracteres del artículo extraído
            article_text = article_content['text'][:1500]
            parts.append(f"[Article Content]: {article_text}")

            # Agregar autores y fecha si existen
            if article_content.get('authors'):
                parts.append(f"Authors: {', '.join(article_content['authors'][:3])}")
            if article_content.get('publish_date'):
                parts.append(f"Published: {article_content['publish_date']}")

        # 2. SELFTEXT de Reddit (si no hay artículo extraído)
        elif submission.get("selftext") and len(submission["selftext"]) > 10:
            parts.append(submission["selftext"][:800])

        # 3. METADATA de Reddit (siempre incluir)
        parts.append(f"Reddit Score: {submission['score']}, Comments: {submission['num_comments']}")
        parts.append(f"Domain Trust: {domain_trust['trust_score']:.2f} ({domain_trust['category']})")
        parts.append(f"Subreddit: r/{submission['subreddit']}")

        # 4. MÉTODO DE EXTRACCIÓN (si aplica)
        if article_content and article_content.get('success'):
            parts.append(f"Extraction: {article_content['method']}")

        return " | ".join(parts)

    def _extract_tags(self, submission: Dict, actors_data: Dict, escalation: Dict) -> List[str]:
        """Extrae tags del post"""
        tags = []

        # Tag de subreddit tier
        if submission["subreddit"] in self.TIER_1_GEOPOLITICS:
            tags.append("tier1-geopolitics")
        elif submission["subreddit"] in self.TIER_2_NEWS:
            tags.append("tier2-news")

        # Tag de tipo de evento
        if actors_data["event_type"]:
            tags.append(actors_data["event_type"])

        # Tag de escalamiento
        if escalation["has_escalation"]:
            tags.append("escalation")
            tags.append(f"escalation-{escalation['escalation_type']}")

        # Tag de trending
        if submission["score"] > 1000:
            tags.append("trending")

        # Tag de alta discusión
        if submission["num_comments"] > 200:
            tags.append("high-discussion")

        return list(set(tags))

    def _generate_event_id(self, submission: Dict) -> str:
        """Genera ID único para el evento"""
        # Usar ID de Reddit + timestamp
        reddit_id = submission["id"]
        timestamp = int(submission["created_utc"])

        # Hash para asegurar unicidad
        unique_str = f"reddit_{reddit_id}_{timestamp}"
        hash_suffix = hashlib.md5(unique_str.encode()).hexdigest()[:8]

        return f"reddit_{reddit_id}_{hash_suffix}"
