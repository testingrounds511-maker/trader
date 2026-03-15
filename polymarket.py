"""Polymarket Integration Module — Foundation for Prediction Market Betting.

Polymarket es un mercado de predicción descentralizado en Polygon blockchain.
Los mercados son preguntas binarias (Sí/No) con resolución on-chain.

ARQUITECTURA:
- PolymarketScanner: Obtiene mercados activos via API REST (no requiere wallet)
- PolymarketAnalyst: Usa el análisis Wolf para generar recomendaciones de apuesta
- PolymarketTrader: (FUTURO) Ejecuta apuestas via Polygon wallet + CLOB API

FLUJO:
1. Escanear mercados abiertos relacionados con assets del portfolio
2. Correr análisis Wolf + news sentiment sobre el tema del mercado
3. Generar recomendación: YES/NO + confidence + tamaño de apuesta sugerido
4. (Futuro) Ejecutar apuesta via CLOB API de Polymarket

API Docs: https://docs.polymarket.com/
CLOB API: https://clob.polymarket.com/
Gamma API: https://gamma-api.polymarket.com/ (mercados, no trading)
"""

import logging
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
import requests

logger = logging.getLogger("phantom.polymarket")

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PolymarketOpportunity:
    """A trading opportunity identified on Polymarket."""
    market_id: str
    question: str
    description: str
    category: str

    # Prices (0-1 scale, represents probability)
    yes_price: float          # Current YES token price ($0.60 = 60% probability)
    no_price: float           # Current NO token price

    # Our analysis
    wolf_prediction: str      # "YES" | "NO" | "ABSTAIN"
    wolf_confidence: float    # 0.0 - 1.0
    edge: float               # Our probability estimate - market probability
    suggested_bet_usd: float  # Suggested bet size

    # Market info
    volume_24h: float
    end_date: str
    liquidity: float

    # Rationale
    reasoning: str
    key_signals: list
    related_assets: list      # Which Wolf portfolio assets inform this bet

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "PENDING"   # PENDING | EXECUTED | EXPIRED | REJECTED


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET SCANNER — Fetches markets from Polymarket API
# ═══════════════════════════════════════════════════════════════════════════════

class PolymarketScanner:
    """Scans Polymarket for markets relevant to Wolf portfolio assets."""

    GAMMA_API = "https://gamma-api.polymarket.com"

    # Keywords that map to our Wolf portfolio assets
    ASSET_KEYWORDS = {
        "BTC/USD": ["bitcoin", "btc", "crypto", "digital asset"],
        "ETH/USD": ["ethereum", "eth", "defi", "blockchain"],
        "SOL/USD": ["solana", "sol"],
        "NVDA": ["nvidia", "nvda", "ai chip", "artificial intelligence", "semiconductor"],
        "TSLA": ["tesla", "tsla", "elon musk", "ev", "electric vehicle"],
        "MSTR": ["microstrategy", "mstr", "saylor", "bitcoin treasury"],
        "COIN": ["coinbase", "coin", "crypto exchange", "sec crypto"],
        "PLTR": ["palantir", "pltr", "government contract", "ai defense"],
        "TQQQ": ["nasdaq", "qqq", "tech rally", "tech crash"],
        "GLD": ["gold", "xau", "safe haven", "fed rate"],
        "BABA": ["alibaba", "baba", "china tech", "xi jinping"],
        "TSM": ["taiwan", "tsmc", "tsm", "semiconductor", "china invasion"],
        "URA": ["uranium", "nuclear energy", "nuclear"],
        "LIT": ["lithium", "ev battery", "lithium mining"],
    }

    # Category filters for high-quality markets
    RELEVANT_CATEGORIES = [
        "crypto", "finance", "economics", "technology",
        "politics", "geopolitics", "commodities"
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PhantomTrader/3.5 (prediction-market-research)",
            "Accept": "application/json",
        })
        self._markets_cache = []
        self._last_scan = None
        self._cache_duration_minutes = 15

    def fetch_active_markets(self, limit: int = 100) -> list[dict]:
        """Fetch currently active markets from Polymarket Gamma API."""
        # Use cache if fresh
        if self._last_scan and (datetime.now(timezone.utc) - self._last_scan).seconds < self._cache_duration_minutes * 60:
            return self._markets_cache

        try:
            resp = self.session.get(
                f"{self.GAMMA_API}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "order": "volume24hr",
                    "ascending": "false",
                },
                timeout=10,
            )
            resp.raise_for_status()
            markets = resp.json()
            self._markets_cache = markets if isinstance(markets, list) else markets.get("markets", [])
            self._last_scan = datetime.now(timezone.utc)
            logger.info(f"Polymarket: fetched {len(self._markets_cache)} active markets")
            return self._markets_cache

        except requests.exceptions.RequestException as e:
            logger.warning(f"Polymarket API error: {e} — no data available")
            return []
        except Exception as e:
            logger.error(f"Polymarket fetch error: {e}")
            return []

    def find_relevant_markets(self, portfolio_assets: list[str]) -> list[dict]:
        """Find Polymarket markets relevant to Wolf portfolio assets."""
        all_markets = self.fetch_active_markets()
        relevant = []

        for market in all_markets:
            question = (market.get("question", "") or "").lower()
            description = (market.get("description", "") or "").lower()
            text = question + " " + description

            matched_assets = []
            for asset in portfolio_assets:
                keywords = self.ASSET_KEYWORDS.get(asset, [asset.lower()])
                if any(kw in text for kw in keywords):
                    matched_assets.append(asset)

            if matched_assets:
                market["_matched_assets"] = matched_assets
                relevant.append(market)

        # Sort by volume
        relevant.sort(key=lambda m: float(m.get("volume24hr", 0) or 0), reverse=True)
        return relevant[:20]  # Top 20 most relevant



# ═══════════════════════════════════════════════════════════════════════════════
# WOLF ANALYST FOR POLYMARKET
# ═══════════════════════════════════════════════════════════════════════════════

class PolymarketAnalyst:
    """Uses Wolf analysis to generate Polymarket betting recommendations."""

    # Kelly criterion fraction — don't over-bet (use 1/4 Kelly for safety)
    KELLY_FRACTION = 0.25
    MIN_BET_USD = 5.0
    MAX_BET_USD = 50.0
    MIN_EDGE_TO_BET = 0.05   # Need at least 5% edge over market price

    def analyze_opportunity(
        self,
        market: dict,
        signals: dict,           # Wolf technical signals for related assets
        news_context: dict,      # Wolf news sentiment
        account_equity: float,   # Portfolio equity for sizing
    ) -> Optional[PolymarketOpportunity]:
        """Analyze a Polymarket market and generate a betting recommendation."""

        question = market.get("question", "")
        description = market.get("description", "")
        matched_assets = market.get("_matched_assets", [])

        # Parse prices
        prices = market.get("outcomePrices", ["0.5", "0.5"])
        try:
            yes_price = float(prices[0]) if isinstance(prices, list) else 0.5
            no_price = float(prices[1]) if isinstance(prices, list) else 0.5
        except (ValueError, IndexError):
            yes_price, no_price = 0.5, 0.5

        # ── Generate Wolf probability estimate ──
        wolf_yes_prob, reasoning, key_signals = self._estimate_probability(
            question=question,
            description=description,
            matched_assets=matched_assets,
            signals=signals,
            news_context=news_context,
        )

        wolf_no_prob = 1.0 - wolf_yes_prob

        # ── Calculate edge ──
        yes_edge = wolf_yes_prob - yes_price
        no_edge = wolf_no_prob - no_price

        # ── Determine recommendation ──
        if yes_edge > no_edge and yes_edge >= self.MIN_EDGE_TO_BET:
            prediction = "YES"
            edge = yes_edge
            confidence = min(0.4 + yes_edge * 2, 0.9)  # Scale to 0.4-0.9
        elif no_edge > yes_edge and no_edge >= self.MIN_EDGE_TO_BET:
            prediction = "NO"
            edge = no_edge
            confidence = min(0.4 + no_edge * 2, 0.9)
        else:
            # No sufficient edge
            prediction = "ABSTAIN"
            edge = max(yes_edge, no_edge)
            confidence = 0.3

        # ── Kelly Criterion sizing ──
        bet_size = 0.0
        if prediction != "ABSTAIN" and confidence > 0.4:
            if prediction == "YES":
                market_odds = (1 / yes_price) - 1 if yes_price > 0 else 0
                kelly_pct = (wolf_yes_prob * market_odds - (1 - wolf_yes_prob)) / market_odds if market_odds > 0 else 0
            else:
                market_odds = (1 / no_price) - 1 if no_price > 0 else 0
                kelly_pct = (wolf_no_prob * market_odds - (1 - wolf_no_prob)) / market_odds if market_odds > 0 else 0

            full_kelly = max(0, kelly_pct) * account_equity
            bet_size = full_kelly * self.KELLY_FRACTION  # Quarter Kelly
            bet_size = max(self.MIN_BET_USD, min(bet_size, self.MAX_BET_USD))
        else:
            bet_size = 0.0

        return PolymarketOpportunity(
            market_id=market.get("id", "unknown"),
            question=question,
            description=description[:200],
            category=market.get("category", "unknown"),
            yes_price=round(yes_price, 3),
            no_price=round(no_price, 3),
            wolf_prediction=prediction,
            wolf_confidence=round(confidence, 2),
            edge=round(edge, 3),
            suggested_bet_usd=round(bet_size, 2),
            volume_24h=float(market.get("volume24hr", 0) or 0),
            end_date=market.get("endDate", ""),
            liquidity=float(market.get("liquidity", 0) or 0),
            reasoning=reasoning,
            key_signals=key_signals,
            related_assets=matched_assets,
        )

    def _estimate_probability(
        self,
        question: str,
        description: str,
        matched_assets: list,
        signals: dict,
        news_context: dict,
    ) -> tuple[float, str, list]:
        """
        Estimate YES probability using Wolf signals and news context.
        Returns (probability_yes, reasoning, key_signals).
        """
        base_prob = 0.50  # Start neutral
        reasons = []
        key_signals = []

        q_lower = question.lower() + " " + description.lower()

        # ── Analyze news sentiment for related assets ──
        news_label = (news_context or {}).get("label", "NEUTRAL")
        news_score = (news_context or {}).get("avg_sentiment", 0)

        if news_label == "BULLISH" and news_score > 0.3:
            # Bullish news → lean YES on upward predictions
            if any(w in q_lower for w in ["reach", "above", "exceed", "break", "beat", "bull"]):
                base_prob += 0.10
                reasons.append("Bullish news sentiment")
                key_signals.append(f"News: BULLISH ({news_score:.2f})")
            elif any(w in q_lower for w in ["crash", "below", "fail", "miss", "bear", "down"]):
                base_prob -= 0.10
                reasons.append("Bullish news contradicts bearish outcome")
                key_signals.append("News: BULLISH (contra bearish Q)")
        elif news_label == "BEARISH" and news_score < -0.3:
            if any(w in q_lower for w in ["crash", "below", "fail", "miss", "bear", "down"]):
                base_prob += 0.10
                reasons.append("Bearish news supports bearish outcome")
                key_signals.append(f"News: BEARISH ({news_score:.2f})")
            elif any(w in q_lower for w in ["reach", "above", "exceed", "break", "beat", "bull"]):
                base_prob -= 0.10
                reasons.append("Bearish news contradicts bullish outcome")
                key_signals.append("News: BEARISH (contra bullish Q)")

        # ── Technical signals from matched assets ──
        # Use the most recently computed signals
        if signals:
            rsi_signal = (signals.get("rsi") or {}).get("signal", "NEUTRAL")
            macd_signal = (signals.get("macd") or {}).get("signal", "NEUTRAL")
            trend_1h = signals.get("trend_1h", "NEUTRAL")

            if rsi_signal in ("OVERSOLD", "BULLISH"):
                if any(w in q_lower for w in ["reach", "above", "beat", "bull", "high"]):
                    base_prob += 0.08
                    key_signals.append(f"RSI: {rsi_signal}")
            elif rsi_signal in ("OVERBOUGHT", "BEARISH"):
                if any(w in q_lower for w in ["reach", "above", "beat", "bull", "high"]):
                    base_prob -= 0.06
                    key_signals.append(f"RSI: {rsi_signal}")

            if "BULLISH" in macd_signal:
                if any(w in q_lower for w in ["reach", "exceed", "above", "beat"]):
                    base_prob += 0.07
                    key_signals.append("MACD: Bullish momentum")
            elif "BEARISH" in macd_signal:
                if any(w in q_lower for w in ["crash", "fail", "miss", "below"]):
                    base_prob += 0.07
                    key_signals.append("MACD: Bearish momentum confirmed")

        # ── Pattern recognition on question keywords ──
        # High-impact macro events (Fed, CPI, NFP) — historical base rates
        if "federal reserve" in q_lower or "fomc" in q_lower or "rate cut" in q_lower:
            reasons.append("Macro event — analyzing Fed signals")
            # CME FedWatch-style: when question is about cuts, lean based on context
            if "cut" in q_lower and news_label == "BULLISH":
                base_prob += 0.05
                key_signals.append("Fed cut expectation: Bullish sentiment")

        # Geopolitical events — high uncertainty, stay close to market
        if any(w in q_lower for w in ["war", "invasion", "conflict", "military", "nuclear"]):
            # These are already priced well by market participants
            # Reduce confidence but don't deviate much from market price
            base_prob = 0.5 * 0.3 + base_prob * 0.7  # Pull toward 0.5
            reasons.append("Geopolitical uncertainty — conservative estimate")
            key_signals.append("HIGH UNCERTAINTY: Geo-political")

        # Clamp to valid range
        base_prob = max(0.05, min(0.95, base_prob))

        reasoning = (
            f"Wolf analysis: P(YES)={base_prob:.1%}. "
            f"Signals: {', '.join(reasons[:3]) or 'Market neutral'}. "
            f"Based on {matched_assets} analysis."
        )

        return round(base_prob, 3), reasoning, key_signals[:5]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN POLYMARKET ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class PolymarketEngine:
    """Orchestrates Polymarket scanning, analysis, and opportunity tracking."""

    def __init__(self):
        self.scanner = PolymarketScanner()
        self.analyst = PolymarketAnalyst()
        self.opportunities: list[PolymarketOpportunity] = []
        self.enabled = True
        self.last_scan_time: Optional[datetime] = None
        self.scan_interval_minutes = 30

    def scan_and_analyze(
        self,
        portfolio_assets: list[str],
        last_signals: dict,      # symbol -> signals from Wolf engine
        last_news: dict,         # symbol -> news context from Wolf engine
        account_equity: float,
    ) -> list[PolymarketOpportunity]:
        """Main scan cycle: find relevant markets and generate opportunities."""

        if not self.enabled:
            return []

        # Rate limit: don't scan too often
        if self.last_scan_time:
            elapsed = (datetime.now(timezone.utc) - self.last_scan_time).seconds / 60
            if elapsed < self.scan_interval_minutes:
                return self.opportunities

        logger.info("PolymarketEngine: scanning for opportunities...")

        # Find relevant markets
        relevant_markets = self.scanner.find_relevant_markets(portfolio_assets)

        new_opportunities = []
        for market in relevant_markets[:10]:  # Analyze top 10
            matched_assets = market.get("_matched_assets", [])

            # Use signals from the first matched asset
            primary_asset = matched_assets[0] if matched_assets else None
            signals = last_signals.get(primary_asset, {}) if primary_asset else {}
            news = last_news.get(primary_asset, {}) if primary_asset else {}

            try:
                opp = self.analyst.analyze_opportunity(
                    market=market,
                    signals=signals,
                    news_context=news,
                    account_equity=account_equity,
                )
                if opp:
                    new_opportunities.append(opp)
            except Exception as e:
                logger.error(f"Polymarket analysis error for {market.get('id')}: {e}")

        # Sort by: ABSTAIN last, then by edge descending
        new_opportunities.sort(key=lambda o: (0 if o.wolf_prediction != "ABSTAIN" else 1, -o.edge))

        self.opportunities = new_opportunities
        self.last_scan_time = datetime.now(timezone.utc)

        good_opps = [o for o in new_opportunities if o.wolf_prediction != "ABSTAIN"]
        logger.info(f"PolymarketEngine: {len(good_opps)} actionable opportunities found")

        return self.opportunities

    def get_top_opportunities(self, n: int = 5) -> list[PolymarketOpportunity]:
        """Get top N opportunities by edge."""
        actionable = [o for o in self.opportunities if o.wolf_prediction != "ABSTAIN"]
        return sorted(actionable, key=lambda o: -o.edge)[:n]

    def get_status(self) -> dict:
        actionable = [o for o in self.opportunities if o.wolf_prediction != "ABSTAIN"]
        total_suggested_usd = sum(o.suggested_bet_usd for o in actionable)

        return {
            "enabled": self.enabled,
            "total_markets_analyzed": len(self.opportunities),
            "actionable_opportunities": len(actionable),
            "total_suggested_usd": round(total_suggested_usd, 2),
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "top_edge": round(max((o.edge for o in actionable), default=0), 3),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NOTES FOR FUTURE IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════════════════

"""
PARA EJECUTAR APUESTAS REALES EN POLYMARKET:
============================================

1. WALLET SETUP:
   - Necesitas una wallet en Polygon (Metamask, etc.)
   - Fondear con USDC en Polygon network
   - Aprobar el contrato de Polymarket para usar tus USDC

2. CLOB API (Conditional Limit Order Book):
   URL: https://clob.polymarket.com/
   Docs: https://docs.polymarket.com/

   Autenticación:
   - L1: firma de wallet (Ethereum signature)
   - L2: API key generada via firma L1

   Endpoints:
   - GET /markets → listar mercados
   - POST /order → crear orden de compra
   - GET /orders → ver órdenes activas
   - DELETE /order/{id} → cancelar orden

3. EJEMPLO DE ORDEN:
   ```python
   from py_clob_client.client import ClobClient
   from py_clob_client.order_builder.constants import BUY

   client = ClobClient(
       host="https://clob.polymarket.com",
       chain_id=137,  # Polygon
       private_key=WALLET_PRIVATE_KEY,
   )

   # Crear orden para comprar YES tokens
   order = client.create_market_order(
       token_id=MARKET_YES_TOKEN_ID,
       side=BUY,
       amount=10.0,  # $10 USDC
   )
   client.post_order(order)
   ```

4. SDK:
   pip install py-clob-client

5. CONSIDERACIONES:
   - Mínimo ~$5 USDC por apuesta
   - Fees: ~2% en algunos mercados
   - Liquidez varía mucho — verificar antes de apostar
   - Los mercados pueden tener spreads amplios
"""
