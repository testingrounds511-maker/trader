"""
TITANIUM VANGUARD - Twitter/X Collector
Recolecta inteligencia geopolítica desde Twitter/X en tiempo real
"""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

try:
    import tweepy
    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False

from collectors.base import BaseCollector
from models import Event


class TwitterCollector(BaseCollector):
    """
    Collector de inteligencia geopolítica desde Twitter/X.

    Estrategia:
    1. Monitorear cuentas oficiales (gobiernos, militares, medios)
    2. Rastrear hashtags de eventos críticos
    3. Analizar engagement (likes, retweets, replies)
    4. Detectar narrativas coordinadas
    5. Extraer URLs de tweets para verificación
    6. Analizar sentimiento y urgencia con Dolphin Mixtral
    """

    # ===== CUENTAS OFICIALES A MONITOREAR =====
    OFFICIAL_ACCOUNTS = {
        "governments": [
            "StateDept",           # USA State Department
            "MoFAChina",           # China Foreign Ministry
            "MID_RF",              # Russia Foreign Ministry
            "MEAIndia",            # India External Affairs
            "FCDOGovUK",           # UK Foreign Office
            "GermanyDiplo",        # Germany Foreign Office
        ],
        "military": [
            "DeptofDefense",       # US DoD
            "NATO",                # NATO
            "IDF",                 # Israel Defense Forces
            "ChineseMilitary",     # PLA
        ],
        "news_agencies": [
            "BBCNews",             # BBC Breaking
            "ReutersWorld",        # Reuters World
            "AP",                  # Associated Press
            "AFP",                 # Agence France-Presse
            "AlJazeera",           # Al Jazeera
        ],
        "geopolitics_experts": [
            # Think tanks y analistas verificados
            # Se pueden agregar según necesidad
        ]
    }

    # ===== HASHTAGS CRÍTICOS =====
    CRITICAL_HASHTAGS = {
        "conflicts": [
            "Ukraine", "Gaza", "Taiwan", "SouthChinaSea",
            "Kashmir", "Crimea", "Syria", "Yemen",
        ],
        "diplomacy": [
            "UN", "G7", "G20", "BRICS", "NATO", "ASEAN", "AU",
        ],
        "military": [
            "Military", "Defense", "AirStrike", "MilitaryExercise",
            "Deployment", "Naval", "AirForce",
        ],
        "economic": [
            "Trade", "Tariff", "Sanctions", "Embargo",
            "USMCA", "FTA", "TradeWar",
        ],
    }

    # ===== KEYWORDS DE ESCALAMIENTO =====
    ESCALATION_KEYWORDS = {
        "military": [
            "military exercise", "deployment", "strike", "attack",
            "warship", "nuclear", "missile", "artillery",
            "invasion", "occupation", "territorial dispute",
        ],
        "economic": [
            "sanction", "embargo", "tariff", "trade war",
            "economic pressure", "financial sanction",
        ],
        "diplomatic": [
            "ultimatum", "threat", "warning", "retaliation",
            "protest", "demand", "expel diplomat",
        ],
    }

    # ===== ACTORES CONOCIDOS =====
    KNOWN_COUNTRIES = [
        "China", "Russia", "USA", "United States", "India", "Japan",
        "Germany", "France", "UK", "United Kingdom", "Iran", "Israel",
        "Saudi Arabia", "Turkey", "Ukraine", "Taiwan", "North Korea",
        "South Korea", "Brazil", "Mexico", "Chile", "Argentina",
    ]

    def __init__(self, config=None):
        """Inicializa Twitter Collector"""
        super().__init__(config)

        if not TWEEPY_AVAILABLE:
            self.logger.error("tweepy no está instalado. Instalar con: pip install tweepy")
            raise ImportError("tweepy is required for TwitterCollector")

        # Configuración
        self.api_key = self.config.twitter_api_key
        self.api_secret = self.config.twitter_api_secret
        self.access_token = self.config.twitter_access_token
        self.access_token_secret = self.config.twitter_access_token_secret
        self.bearer_token = self.config.twitter_bearer_token

        # Cargar accounts y hashtags desde config
        self.accounts_to_monitor = self._load_accounts()
        self.hashtags_to_track = self._load_hashtags()

        self.tweets_per_account = self.config.twitter_tweets_per_account

        # Inicializar Twitter API (v2 con tweepy)
        self.client = None
        if self.bearer_token:
            try:
                self.client = tweepy.Client(
                    bearer_token=self.bearer_token,
                    consumer_key=self.api_key,
                    consumer_secret=self.api_secret,
                    access_token=self.access_token,
                    access_token_secret=self.access_token_secret,
                    wait_on_rate_limit=True,  # Auto wait on rate limits
                )
                self.logger.info("Twitter API v2 client inicializado")
            except Exception as e:
                self.logger.error(f"Error inicializando Twitter client: {e}")
                self.client = None
        else:
            self.logger.warning("Twitter bearer token no configurado - collector deshabilitado")

        self.logger.info(f"TwitterCollector inicializado: {len(self.accounts_to_monitor)} cuentas, {len(self.hashtags_to_track)} hashtags")

    def _load_accounts(self) -> List[str]:
        """Carga lista de cuentas desde config"""
        if hasattr(self.config, 'twitter_accounts_to_monitor') and self.config.twitter_accounts_to_monitor:
            accounts = [a.strip().lstrip('@') for a in self.config.twitter_accounts_to_monitor.split(',')]
            if accounts and accounts[0]:
                return accounts

        # Si no, usar todas las categorías
        all_accounts = []
        for category_accounts in self.OFFICIAL_ACCOUNTS.values():
            all_accounts.extend(category_accounts)
        return all_accounts

    def _load_hashtags(self) -> List[str]:
        """Carga lista de hashtags desde config"""
        if hasattr(self.config, 'twitter_hashtags') and self.config.twitter_hashtags:
            hashtags = [h.strip().lstrip('#') for h in self.config.twitter_hashtags.split(',')]
            if hashtags and hashtags[0]:
                return hashtags

        # Si no, usar todos los hashtags críticos
        all_hashtags = []
        for category_hashtags in self.CRITICAL_HASHTAGS.values():
            all_hashtags.extend(category_hashtags)
        return all_hashtags

    async def fetch(self) -> List[Dict]:
        """
        Obtiene tweets de múltiples fuentes:

        1. Timeline de cuentas oficiales
        2. Búsqueda de hashtags trending
        3. Tweets con engagement alto

        Returns:
            Lista de tweet objects (raw)
        """
        if not self.client:
            self.logger.warning("Twitter client no inicializado")
            return []

        try:
            self.logger.info(f"Fetching tweets de {len(self.accounts_to_monitor)} cuentas...")

            all_tweets = []

            # ESTRATEGIA 1: Fetch timelines de cuentas oficiales
            account_tweets = await self._fetch_accounts_timelines()
            all_tweets.extend(account_tweets)

            # ESTRATEGIA 2: Búsqueda por hashtags
            hashtag_tweets = await self._fetch_hashtag_tweets()
            all_tweets.extend(hashtag_tweets)

            # Remover duplicados por tweet ID
            unique_tweets = self._remove_duplicates(all_tweets)

            self.logger.info(f"Obtenidos {len(unique_tweets)} tweets únicos de Twitter")

            return unique_tweets

        except Exception as e:
            self.logger.error(f"Error en fetch: {e}")
            return []

    async def _fetch_accounts_timelines(self) -> List[Dict]:
        """
        Fetch timelines de cuentas oficiales en paralelo

        Returns:
            Lista de tweets
        """
        all_tweets = []

        for account in self.accounts_to_monitor[:10]:  # Limitar a 10 primeras para testing
            try:
                # Get user ID
                user = self.client.get_user(username=account)

                if not user.data:
                    self.logger.warning(f"Cuenta @{account} no encontrada")
                    continue

                user_id = user.data.id

                # Fetch user timeline (últimos tweets)
                tweets = self.client.get_users_tweets(
                    id=user_id,
                    max_results=self.tweets_per_account,
                    tweet_fields=['created_at', 'public_metrics', 'entities', 'referenced_tweets'],
                    exclude=['retweets', 'replies'],  # Solo tweets originales
                )

                if not tweets.data:
                    continue

                # Convertir a dict
                for tweet in tweets.data:
                    tweet_dict = self._tweet_to_dict(tweet, account)
                    all_tweets.append(tweet_dict)

                self.logger.debug(f"Account @{account}: {len(tweets.data)} tweets")

            except tweepy.errors.TooManyRequests:
                self.logger.warning(f"Rate limit alcanzado en cuenta @{account}")
                await asyncio.sleep(60)  # Wait 1 min
                continue

            except Exception as e:
                self.logger.warning(f"Error fetching @{account}: {e}")
                continue

        return all_tweets

    async def _fetch_hashtag_tweets(self) -> List[Dict]:
        """
        Busca tweets por hashtags

        Returns:
            Lista de tweets
        """
        all_tweets = []

        for hashtag in self.hashtags_to_track[:5]:  # Limitar a 5 primeros hashtags
            try:
                # Búsqueda por hashtag (últimas 24 horas)
                query = f"#{hashtag} -is:retweet lang:en"

                tweets = self.client.search_recent_tweets(
                    query=query,
                    max_results=20,
                    tweet_fields=['created_at', 'public_metrics', 'entities', 'referenced_tweets'],
                )

                if not tweets.data:
                    continue

                for tweet in tweets.data:
                    tweet_dict = self._tweet_to_dict(tweet, f"hashtag_{hashtag}")
                    all_tweets.append(tweet_dict)

                self.logger.debug(f"Hashtag #{hashtag}: {len(tweets.data)} tweets")

            except tweepy.errors.TooManyRequests:
                self.logger.warning(f"Rate limit alcanzado en hashtag #{hashtag}")
                await asyncio.sleep(60)
                continue

            except Exception as e:
                self.logger.warning(f"Error searching #{hashtag}: {e}")
                continue

        return all_tweets

    def _tweet_to_dict(self, tweet, source: str) -> Dict:
        """
        Convierte Tweet object a diccionario

        Args:
            tweet: Tweepy Tweet object
            source: Fuente (account name o hashtag)

        Returns:
            Dict con datos del tweet
        """
        return {
            "id": tweet.id,
            "text": tweet.text,
            "created_at": tweet.created_at.timestamp() if tweet.created_at else None,
            "source": source,
            "metrics": {
                "likes": tweet.public_metrics.get("like_count", 0) if tweet.public_metrics else 0,
                "retweets": tweet.public_metrics.get("retweet_count", 0) if tweet.public_metrics else 0,
                "replies": tweet.public_metrics.get("reply_count", 0) if tweet.public_metrics else 0,
                "quotes": tweet.public_metrics.get("quote_count", 0) if tweet.public_metrics else 0,
            },
            "entities": tweet.entities if hasattr(tweet, 'entities') else None,
            "referenced_tweets": tweet.referenced_tweets if hasattr(tweet, 'referenced_tweets') else None,
        }

    def _remove_duplicates(self, tweets: List[Dict]) -> List[Dict]:
        """Remueve tweets duplicados por ID"""
        seen_ids = set()
        unique = []

        for tweet in tweets:
            if tweet["id"] not in seen_ids:
                seen_ids.add(tweet["id"])
                unique.append(tweet)

        return unique

    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        """
        Transforma tweets → Event objects

        Para cada tweet:
        1. Extraer texto, URLs, entidades
        2. Analizar con NLP:
           - Actores (países, organizaciones)
           - Sentimiento (escalada vs calma)
           - Tema (militar, económico, diplomacia)
           - Urgencia (lenguaje de crisis)
        3. Calcular relevance_score basado en engagement
        4. Detectar escalamiento
        5. Retornar Event

        Args:
            raw_data: Lista de tweet dicts

        Returns:
            Lista de Event objects
        """
        events = []

        for tweet in raw_data:
            try:
                # Validar que sea tweet relevante
                if not self._is_valid_tweet(tweet):
                    continue

                # Extraer URLs del tweet
                urls = self._extract_urls(tweet)

                # Analizar actores y tema
                actors_data = self._analyze_tweet_actors(tweet["text"])

                # Calcular relevance_score basado en engagement
                relevance = self._calculate_relevance_score(tweet, actors_data)

                # Detectar escalamiento
                escalation = self._detect_escalation_patterns(tweet["text"])

                # Analizar sentimiento (básico - Dolphin para profundo)
                sentiment = self._analyze_sentiment_basic(tweet["text"])

                # Extraer país principal
                country = actors_data["countries"][0] if actors_data["countries"] else None
                region = self._extract_region(country)

                # Crear ID único
                event_id = f"twitter_{tweet['id']}"

                # Crear Event object
                event = Event(
                    id=event_id,
                    title=tweet["text"][:500],  # Usar texto del tweet como título
                    description=self._create_description(tweet, actors_data, escalation),
                    source_url=urls[0] if urls else f"https://twitter.com/i/status/{tweet['id']}",
                    source_name=f"Twitter @{tweet['source']}",

                    # Fechas
                    event_date=datetime.fromtimestamp(tweet["created_at"], tz=timezone.utc) if tweet["created_at"] else datetime.now(timezone.utc),
                    published_date=datetime.fromtimestamp(tweet["created_at"], tz=timezone.utc) if tweet["created_at"] else datetime.now(timezone.utc),

                    # Ubicación
                    country=country,
                    region=region,

                    # Clasificación
                    event_type=actors_data.get("event_type", "geopolitical"),
                    category="twitter",

                    # Actores
                    primary_actors=actors_data["countries"][:3],

                    # Relevancia
                    relevance_score=relevance,

                    # Metadata
                    language="en",
                    tags=self._extract_tags(tweet, actors_data, escalation, sentiment),

                    # Raw data
                    raw_data={
                        "tweet": tweet,
                        "actors_analysis": actors_data,
                        "escalation_patterns": escalation,
                        "sentiment": sentiment,
                        "urls": urls,
                    },
                )

                events.append(event)

            except Exception as e:
                self.logger.warning(f"Error parseando tweet {tweet.get('id')}: {e}")
                continue

        self.logger.info(f"Parseados {len(events)} eventos de {len(raw_data)} tweets")
        return events

    def _is_valid_tweet(self, tweet: Dict) -> bool:
        """
        Valida que el tweet sea relevante

        Filters:
        - Tweets muy cortos (< 20 caracteres)
        - Tweets sin métricas
        """
        if not tweet.get("text") or len(tweet["text"]) < 20:
            return False

        # Requiere al menos algún engagement
        metrics = tweet.get("metrics", {})
        total_engagement = metrics.get("likes", 0) + metrics.get("retweets", 0)

        if total_engagement < 5:
            return False

        return True

    def _extract_urls(self, tweet: Dict) -> List[str]:
        """Extrae URLs del tweet"""
        urls = []

        entities = tweet.get("entities")
        if entities and "urls" in entities:
            for url_entity in entities["urls"]:
                expanded_url = url_entity.get("expanded_url")
                if expanded_url:
                    urls.append(expanded_url)

        return urls

    def _analyze_tweet_actors(self, text: str) -> Dict:
        """
        Extrae actores del texto del tweet

        Returns:
            {
                "countries": [...],
                "event_type": "military|economic|diplomacy",
                "confidence": 0.0-1.0
            }
        """
        countries = []

        # Detectar países
        for country in self.KNOWN_COUNTRIES:
            if country.lower() in text.lower():
                if country not in countries:
                    countries.append(country)

        # Clasificar tipo de evento
        text_lower = text.lower()

        if any(word in text_lower for word in ["military", "war", "attack", "strike", "troops"]):
            event_type = "military"
        elif any(word in text_lower for word in ["trade", "tariff", "economic", "sanction", "embargo"]):
            event_type = "economic"
        elif any(word in text_lower for word in ["diplomatic", "summit", "meeting", "agreement"]):
            event_type = "diplomacy"
        elif any(word in text_lower for word in ["conflict", "crisis", "tension"]):
            event_type = "conflict"
        else:
            event_type = "geopolitical"

        confidence = min(1.0, len(countries) * 0.4)

        return {
            "countries": countries,
            "event_type": event_type,
            "confidence": confidence,
        }

    def _calculate_relevance_score(self, tweet: Dict, actors_data: Dict) -> float:
        """
        Calcula relevancia basada en engagement y actores

        Base:
        - Likes (30%)
        - Retweets (40%)
        - Replies (20%)
        - Quotes (10%)

        Bonuses:
        - Cuenta oficial: +0.15
        - URL externa: +0.10
        - Múltiples actores: +0.05

        Returns:
            Score 0.0-1.0
        """
        metrics = tweet.get("metrics", {})

        # Normalizar engagement (logarítmico)
        import math
        likes = metrics.get("likes", 0)
        retweets = metrics.get("retweets", 0)
        replies = metrics.get("replies", 0)
        quotes = metrics.get("quotes", 0)

        normalized_likes = min(1.0, math.log(likes + 1) / math.log(10000))
        normalized_retweets = min(1.0, math.log(retweets + 1) / math.log(5000))
        normalized_replies = min(1.0, math.log(replies + 1) / math.log(1000))
        normalized_quotes = min(1.0, math.log(quotes + 1) / math.log(500))

        base_score = (
            normalized_likes * 0.3 +
            normalized_retweets * 0.4 +
            normalized_replies * 0.2 +
            normalized_quotes * 0.1
        )

        # Bonuses
        bonuses = 0.0

        # Cuenta oficial
        source = tweet.get("source", "")
        official_accounts = []
        for accounts in self.OFFICIAL_ACCOUNTS.values():
            official_accounts.extend(accounts)

        if any(account in source for account in official_accounts):
            bonuses += 0.15

        # Múltiples actores
        if len(actors_data.get("countries", [])) > 1:
            bonuses += 0.05

        final_score = min(1.0, base_score + bonuses)
        return max(0.0, final_score)

    def _detect_escalation_patterns(self, text: str) -> Dict:
        """
        Detecta keywords de escalamiento

        Returns:
            {
                "has_escalation": bool,
                "escalation_type": str,
                "keywords_found": list,
                "risk_level": 0.0-1.0
            }
        """
        text_lower = text.lower()
        found_keywords = []
        escalation_type = None

        for esc_type, keywords in self.ESCALATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found_keywords.append(keyword)
                    escalation_type = esc_type

        has_escalation = len(found_keywords) > 0
        risk_level = min(1.0, len(found_keywords) * 0.25)

        return {
            "has_escalation": has_escalation,
            "escalation_type": escalation_type,
            "keywords_found": found_keywords,
            "risk_level": risk_level,
        }

    def _analyze_sentiment_basic(self, text: str) -> Dict:
        """
        Análisis básico de sentimiento (negativo = escalada)

        Para análisis profundo, usar Dolphin Mixtral posteriormente

        Returns:
            {
                "sentiment": -1.0 to 1.0,
                "urgency": 0.0 to 1.0
            }
        """
        text_lower = text.lower()

        # Keywords negativos (escalada)
        negative_keywords = ["war", "attack", "threat", "crisis", "conflict", "strike", "invasion"]
        negative_count = sum(1 for kw in negative_keywords if kw in text_lower)

        # Keywords positivos (calma)
        positive_keywords = ["peace", "agreement", "cooperation", "dialogue", "treaty"]
        positive_count = sum(1 for kw in positive_keywords if kw in text_lower)

        # Sentiment score
        if negative_count + positive_count == 0:
            sentiment = 0.0
        else:
            sentiment = (positive_count - negative_count) / (positive_count + negative_count)

        # Urgency basado en palabras de urgencia
        urgency_keywords = ["breaking", "urgent", "immediate", "now", "alert"]
        urgency_count = sum(1 for kw in urgency_keywords if kw in text_lower)
        urgency = min(1.0, urgency_count * 0.3)

        return {
            "sentiment": sentiment,
            "urgency": urgency,
        }

    def _extract_region(self, country: Optional[str]) -> Optional[str]:
        """Mapea país a región"""
        regions = {
            "China": "Asia-Pacific",
            "Japan": "Asia-Pacific",
            "India": "Asia-Pacific",
            "Taiwan": "Asia-Pacific",
            "South Korea": "Asia-Pacific",
            "North Korea": "Asia-Pacific",
            "USA": "North America",
            "United States": "North America",
            "Mexico": "North America",
            "Russia": "Europe",
            "Germany": "Europe",
            "France": "Europe",
            "UK": "Europe",
            "United Kingdom": "Europe",
            "Ukraine": "Europe",
            "Iran": "Middle East",
            "Israel": "Middle East",
            "Saudi Arabia": "Middle East",
            "Chile": "South America",
            "Argentina": "South America",
            "Brazil": "South America",
        }

        return regions.get(country)

    def _create_description(self, tweet: Dict, actors_data: Dict, escalation: Dict) -> str:
        """Crea descripción del evento"""
        parts = []

        # Métricas de engagement
        metrics = tweet.get("metrics", {})
        parts.append(f"Engagement: {metrics.get('likes', 0)} likes, {metrics.get('retweets', 0)} RTs, {metrics.get('replies', 0)} replies")

        # Actores detectados
        if actors_data.get("countries"):
            parts.append(f"Actores: {', '.join(actors_data['countries'])}")

        # Escalamiento
        if escalation.get("has_escalation"):
            parts.append(f"Escalation Risk: {escalation['risk_level']:.1%} ({escalation['escalation_type']})")

        # Fuente
        parts.append(f"Fuente: @{tweet['source']}")

        return " | ".join(parts)

    def _extract_tags(self, tweet: Dict, actors_data: Dict, escalation: Dict, sentiment: Dict) -> List[str]:
        """Extrae tags del tweet"""
        tags = []

        # Tag de tipo de evento
        if actors_data.get("event_type"):
            tags.append(actors_data["event_type"])

        # Tag de escalamiento
        if escalation.get("has_escalation"):
            tags.append("escalation")
            tags.append(f"escalation-{escalation['escalation_type']}")

        # Tag de sentimiento
        if sentiment.get("sentiment", 0) < -0.3:
            tags.append("negative-sentiment")
        elif sentiment.get("sentiment", 0) > 0.3:
            tags.append("positive-sentiment")

        # Tag de urgencia
        if sentiment.get("urgency", 0) > 0.5:
            tags.append("urgent")

        # Tag de alto engagement
        metrics = tweet.get("metrics", {})
        if metrics.get("retweets", 0) > 1000:
            tags.append("viral")

        # Tag de cuenta oficial
        source = tweet.get("source", "")
        official_accounts = []
        for accounts in self.OFFICIAL_ACCOUNTS.values():
            official_accounts.extend(accounts)

        if any(account in source for account in official_accounts):
            tags.append("official-account")

        return list(set(tags))
