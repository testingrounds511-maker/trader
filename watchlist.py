"""Twitter/X account watchlist for Phantom Trader News Sentinel.

Each account is categorized by tier (impact speed) and tagged
with the assets it typically moves. The sentinel uses these tags
to route alerts to the correct trading engine.
"""

TWITTER_WATCHLIST = {
    # ═══════════════════════════════════════════
    # TIER 1 — MARKET MOVERS (instant alert)
    # Single tweet can move prices within minutes
    # ═══════════════════════════════════════════
    "elonmusk": {
        "name": "Elon Musk",
        "tier": 1,
        "assets": ["BTC/USD", "ETH/USD", "DOGE/USD", "TSLA"],
        "keywords": ["bitcoin", "btc", "doge", "dogecoin", "crypto", "tesla", "AI"],
        "impact": "extreme",
        "description": "Moves DOGE, BTC, TSLA with single tweets",
    },
    "JensenHuang": {
        "name": "Jensen Huang",
        "tier": 1,
        "assets": ["NVDA"],
        "keywords": ["nvidia", "gpu", "blackwell", "AI", "chip", "data center", "inference"],
        "impact": "extreme",
        "description": "NVIDIA CEO — product/deal news = instant NVDA move",
    },
    "sundaborpichai": {
        "name": "Sundar Pichai",
        "tier": 1,
        "assets": ["GOOGL"],
        "keywords": ["google", "gemini", "AI", "cloud", "search", "android", "waymo"],
        "impact": "high",
        "description": "Google CEO — GOOGL product announcements",
    },
    "daborioamodei": {
        "name": "Dario Amodei",
        "tier": 1,
        "assets": ["GOOGL", "NVDA"],  # Indirect: Google investor, NVDA customer
        "keywords": ["anthropic", "claude", "AI", "safety", "frontier"],
        "impact": "medium",
        "description": "Anthropic CEO — AI industry signals",
    },
    "sataboryanadella": {
        "name": "Satya Nadella",
        "tier": 1,
        "assets": ["NVDA", "GOOGL", "QQQ"],
        "keywords": ["microsoft", "copilot", "azure", "AI", "openai"],
        "impact": "high",
        "description": "Microsoft CEO — AI/cloud partnership signals",
    },
    "saylor": {
        "name": "Michael Saylor",
        "tier": 1,
        "assets": ["BTC/USD"],
        "keywords": ["bitcoin", "btc", "strategy", "purchase", "acquired", "treasury"],
        "impact": "extreme",
        "description": "Strategy holds 712K+ BTC — purchases move market",
    },
    "VitalikButerin": {
        "name": "Vitalik Buterin",
        "tier": 1,
        "assets": ["ETH/USD"],
        "keywords": ["ethereum", "eth", "L2", "rollup", "upgrade", "EIP", "merge"],
        "impact": "high",
        "description": "Ethereum co-founder — roadmap shifts trigger ETH moves",
    },
    "cz_binance": {
        "name": "Changpeng Zhao (CZ)",
        "tier": 1,
        "assets": ["BTC/USD", "ETH/USD"],
        "keywords": ["binance", "crypto", "bitcoin", "listing", "regulation"],
        "impact": "high",
        "description": "Binance founder — exchange + crypto market signals",
    },
    "CathieDWood": {
        "name": "Cathie Wood",
        "tier": 1,
        "assets": ["NVDA", "GOOGL", "QQQ", "BTC/USD"],
        "keywords": ["ark", "invest", "innovation", "AI", "bitcoin", "tesla", "disruptive"],
        "impact": "high",
        "description": "ARK Invest CEO — tech stock conviction calls",
    },

    # ═══════════════════════════════════════════
    # TIER 2 — BREAKING NEWS SPEED (< 60 sec)
    # Fastest financial headlines on Twitter
    # ═══════════════════════════════════════════
    "DeItaone": {
        "name": "Walter Bloomberg",
        "tier": 2,
        "assets": ["ALL"],  # Covers everything
        "keywords": [],  # All tweets are relevant
        "impact": "high",
        "description": "THE fastest market-moving headlines on Twitter",
    },
    "unusual_whales": {
        "name": "Unusual Whales",
        "tier": 2,
        "assets": ["ALL"],
        "keywords": ["unusual", "options", "flow", "insider", "congress", "dark pool"],
        "impact": "high",
        "description": "Options flow, insider trades, congressional trades",
    },
    "WatcherGuru": {
        "name": "Watcher Guru",
        "tier": 2,
        "assets": ["BTC/USD", "ETH/USD"],
        "keywords": ["breaking", "just in", "bitcoin", "ethereum", "crypto"],
        "impact": "high",
        "description": "Fastest crypto breaking news — verified unbiased",
    },
    "whale_alert": {
        "name": "Whale Alert",
        "tier": 2,
        "assets": ["BTC/USD", "ETH/USD"],
        "keywords": ["transferred", "minted", "burned", "whale"],
        "impact": "medium",
        "description": "Large on-chain crypto transactions (100+ BTC, 1000+ ETH)",
    },
    "zaborerohedge": {
        "name": "Zerohedge",
        "tier": 2,
        "assets": ["ALL"],
        "keywords": ["breaking", "fed", "inflation", "crash", "recession", "war"],
        "impact": "medium",
        "description": "Market-moving macro/geopolitical news",
    },
    "Newsquawk": {
        "name": "Newsquawk",
        "tier": 2,
        "assets": ["ALL"],
        "keywords": [],
        "impact": "high",
        "description": "Real-time audio/text financial news wire",
    },
    "FirstSquawk": {
        "name": "First Squawk",
        "tier": 2,
        "assets": ["ALL"],
        "keywords": [],
        "impact": "high",
        "description": "Breaking market headlines — among the fastest",
    },

    # ═══════════════════════════════════════════
    # TIER 3 — ANALYSTS & SMART MONEY
    # Alpha through analysis, not breaking news
    # ═══════════════════════════════════════════
    "DanIves": {
        "name": "Dan Ives (Wedbush)",
        "tier": 3,
        "assets": ["NVDA", "GOOGL", "QQQ"],
        "keywords": ["nvidia", "AI", "price target", "upgrade", "tech"],
        "impact": "medium",
        "description": "Top tech analyst — NVDA/AI price targets move stocks",
    },
    "jam_croissant": {
        "name": "Cem Karsan",
        "tier": 3,
        "assets": ["SPY", "QQQ"],
        "keywords": ["vol", "gamma", "options", "expiration", "vix", "dealer"],
        "impact": "medium",
        "description": "Options/volatility expert — macro vol calls",
    },
    "Citrini7": {
        "name": "Citrini",
        "tier": 3,
        "assets": ["NVDA", "QQQ"],
        "keywords": ["AI", "semiconductor", "megatrend", "nvidia"],
        "impact": "medium",
        "description": "Early AI/NVDA thesis — theme investor",
    },
    "elerianm": {
        "name": "Mohamed El-Erian",
        "tier": 3,
        "assets": ["SPY", "QQQ", "BTC/USD"],
        "keywords": ["fed", "rates", "inflation", "economy", "recession", "employment"],
        "impact": "medium",
        "description": "Premier macro/Fed/rates analyst",
    },
    "NickTimiraos": {
        "name": "Nick Timiraos (WSJ)",
        "tier": 3,
        "assets": ["SPY", "QQQ", "BTC/USD"],
        "keywords": ["fed", "rate", "fomc", "powell", "cut", "hike", "pause"],
        "impact": "extreme",
        "description": "THE 'Fed Whisperer' — WSJ Fed reporter, leaks Fed moves",
    },
    "NorthmanTrader": {
        "name": "Sven Henrich",
        "tier": 3,
        "assets": ["SPY", "QQQ"],
        "keywords": ["technical", "chart", "support", "resistance", "divergence"],
        "impact": "low",
        "description": "Technical analysis, market structure",
    },
    "FedGuy12": {
        "name": "Joseph Wang (ex-Fed)",
        "tier": 3,
        "assets": ["SPY", "QQQ", "BTC/USD"],
        "keywords": ["fed", "treasury", "liquidity", "QT", "balance sheet", "repo"],
        "impact": "medium",
        "description": "Ex-Fed trader — balance sheet / rates deep dives",
    },

    # ═══════════════════════════════════════════
    # TIER 4 — CRYPTO-SPECIFIC INTELLIGENCE
    # ═══════════════════════════════════════════
    "Arthur_0x": {
        "name": "Arthur Hayes",
        "tier": 4,
        "assets": ["BTC/USD", "ETH/USD"],
        "keywords": ["bitcoin", "ethereum", "macro", "print", "liquidity", "dxy"],
        "impact": "medium",
        "description": "BitMEX founder — macro + crypto thesis, bold calls",
    },
    "Pentosh1": {
        "name": "Pentoshi",
        "tier": 4,
        "assets": ["BTC/USD", "ETH/USD"],
        "keywords": ["btc", "eth", "chart", "long", "short", "target"],
        "impact": "medium",
        "description": "Respected crypto technical trader",
    },
    "CryptoCapo_": {
        "name": "Crypto Capo",
        "tier": 4,
        "assets": ["BTC/USD", "ETH/USD"],
        "keywords": ["bitcoin", "ethereum", "setup", "target", "invalidation"],
        "impact": "low",
        "description": "BTC/ETH technical analysis",
    },

    # ═══════════════════════════════════════════
    # TIER 5 — PENTAGON / MILITARY OSINT
    # Geopolitical signals → Defense sector rotation
    # ═══════════════════════════════════════════
    "IntelCrab": {
        "name": "IntelCrab",
        "tier": 5,
        "assets": ["LMT", "RTX", "NOC", "GD", "BA"],
        "keywords": ["pentagon", "military", "deployed", "strike", "carrier", "DEFCON",
                      "mobilization", "airspace", "missile", "troops"],
        "impact": "high",
        "description": "OSINT aggregator — military movements and conflicts",
    },
    "sentdefender": {
        "name": "OSINTdefender",
        "tier": 5,
        "assets": ["LMT", "RTX", "NOC", "GD", "BA"],
        "keywords": ["pentagon", "military", "deployed", "strike", "carrier",
                      "missile", "troops", "defense", "nato", "warship"],
        "impact": "high",
        "description": "Defense & military OSINT — conflict tracking",
    },
    "Aviation_Intel": {
        "name": "Aviation Intel",
        "tier": 5,
        "assets": ["LMT", "RTX", "NOC", "BA"],
        "keywords": ["military aircraft", "B-2", "B-52", "F-35", "tanker",
                      "refueling", "deployed", "scrambled", "airspace"],
        "impact": "medium",
        "description": "Military aviation tracking — deployment patterns",
    },
    "RALee85": {
        "name": "Rob Lee",
        "tier": 5,
        "assets": ["LMT", "RTX", "NOC", "GD"],
        "keywords": ["military", "defense", "conflict", "war", "troops", "weapons"],
        "impact": "medium",
        "description": "Military analyst — conflict zone intelligence",
    },

    # ═══════════════════════════════════════════
    # TIER 6 — INSTITUTIONAL / NEWS ORGS
    # ═══════════════════════════════════════════
    "business": {
        "name": "Bloomberg",
        "tier": 6,
        "assets": ["ALL"],
        "keywords": [],
        "impact": "high",
        "description": "Bloomberg Business — institutional-grade market news",
    },
    "ReutersBiz": {
        "name": "Reuters Business",
        "tier": 6,
        "assets": ["ALL"],
        "keywords": [],
        "impact": "high",
        "description": "Global financial wire service",
    },
    "CNBC": {
        "name": "CNBC",
        "tier": 6,
        "assets": ["ALL"],
        "keywords": [],
        "impact": "medium",
        "description": "Market-moving interviews and breaking news",
    },
}


# Quick lookup helpers
def get_accounts_by_tier(tier: int) -> dict:
    return {k: v for k, v in TWITTER_WATCHLIST.items() if v["tier"] == tier}


def get_accounts_for_asset(asset: str) -> dict:
    return {
        k: v for k, v in TWITTER_WATCHLIST.items()
        if asset in v["assets"] or "ALL" in v["assets"]
    }


def get_all_handles() -> list[str]:
    return list(TWITTER_WATCHLIST.keys())


def get_tier1_handles() -> list[str]:
    return [k for k, v in TWITTER_WATCHLIST.items() if v["tier"] == 1]
