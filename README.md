# 👻 PHANTOM TRADER v4 — Self-Learning Trading Intelligence Platform

> **Codename:** Phantom Wolf | **Version:** 4.0 "Quantum Predator"
> **Target:** FundedNext Free Trial ($6K) → FundedNext Futures (bots legal)
> **Deploy:** Kamatera VPS (30 días gratis) → ForexCheapVPS ($5/mes)
> **Brain:** Groq Llama 3.3 70B (gratis) + Anthropic Claude (fallback pagado)
> **Self-Learning:** Trade Memory + Weekly Self-Evaluator + Auto-Optimizer
> **Stack Cost:** $0/mes (Groq free + RSS free + MT5 free + Kamatera free trial)

---

## What is this

A 51-file Python trading platform that:
- Connects to MetaTrader 5 and trades forex automatically
- Uses AI (Groq free tier) to analyze technicals + news + sentiment
- Enforces FundedNext prop firm rules with 5 layers of risk management
- **Learns from every trade** — extracts lessons from losses, optimizes parameters weekly
- Runs 24/7 on a Windows VPS with zero human intervention
- Costs $0/month in API fees (Groq free tier + RSS feeds)

---

## Table of Contents

1. [FundedNext Rules](#fundednext-rules)
2. [Architecture](#architecture)
3. [Self-Learning System](#self-learning-system)
4. [Module Inventory (51 files)](#module-inventory)
5. [Risk Management (5 Layers)](#risk-management-5-layers)
6. [Intelligence Network](#intelligence-network)
7. [Deployment Guide](#deployment-guide)
8. [Configuration](#configuration)
9. [Strategy & Math](#strategy--math)
10. [Operational Playbook](#operational-playbook)
11. [Cost Breakdown](#cost-breakdown)
12. [Future Roadmap](#future-roadmap)

---

## FundedNext Rules

**Account: $6,000 Free Trial** → validated from FN dashboard

| Rule | Value | $ Amount | Bot Buffer |
|------|-------|----------|------------|
| Profit Target | 5% | $300 | — |
| Daily Loss Limit | 5% | $300/day | Stops at 4.5% ($270) |
| Max Loss Limit | 10% | $600 | Stops at 9% ($540) |
| Time Limit | 14 days | — | Warns at day 12 |
| Min Trading Days | 3 | — | Auto-tracked |
| Max Open Positions | 30 | — | Hard block |
| Leverage FX | 1:100 | — | Auto-detected |
| Leverage Commodities | 1:40 | — | Auto-detected |
| Leverage Indices | 1:20 | — | Auto-detected |
| EAs (Free Trial) | Prohibited | — | Python IPC, not EA |
| EAs (Futures) | **Allowed** | — | Full auto legal |

**Path:** Free Trial (validate) → Futures challenge ~$40 (bots legal) → Funded account

---

## Architecture

```
╔══════════════════════════════════════════════════════════════════╗
║                   PHANTOM WOLF v4.0                              ║
║          Self-Learning Async Trading Engine                      ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  ║
║  │  MT5 Data   │  │  Groq AI    │  │  Groq NLP Sniper        │  ║
║  │  market_data│  │  analyst.py │  │  nlp_engine.py          │  ║
║  │  (free)     │  │  (free)     │  │  (free)                 │  ║
║  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  ║
║         │                │                       │               ║
║         ▼                ▼                       ▼               ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  wolf_engine.py — Async orchestrator (1-sec resolution)   │   ║
║  └─────────────────────────┬────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │            🧠 SELF-LEARNING SYSTEM (NEW in v4)            │   ║
║  │                                                            │   ║
║  │  trade_memory.py     — Records every trade + context       │   ║
║  │  self_evaluator.py   — Weekly review + lesson extraction   │   ║
║  │  auto_optimizer.py   — Backtester grid search + apply      │   ║
║  │                                                            │   ║
║  │  Loop: trade → record → evaluate → learn → optimize →     │   ║
║  │        apply → trade better → repeat forever               │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │              RISK MANAGEMENT (5 layers)                    │   ║
║  │  L1: FN Rule Guardian    L2: Capital Ratchet (HWM)        │   ║
║  │  L3: Broker Compliance   L4: Per-Trade Risk               │   ║
║  │  L5: Emergency Circuit Breaker                            │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │              INTELLIGENCE NETWORK                          │   ║
║  │  RSS: SEC/DOJ/FDA/CNBC (free)  Reddit RSS (free)          │   ║
║  │  Twitter watchlist (40+ accounts)  GDELT events           │   ║
║  │  Economic calendar  Congressional trades  BTC arbitrage    │   ║
║  │  12 TITANIUM OSINT collectors                             │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                            │                                     ║
║  ┌──────────────┐  ┌──────┴───────┐  ┌──────────────────────┐  ║
║  │ MT5 Executor │  │  Streamlit   │  │  Telegram Alerts     │  ║
║  │ (auto/manual)│  │  Dashboard   │  │  (future)            │  ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Self-Learning System

The bot gets smarter every week through three interconnected modules:

### Trade Memory (`trade_memory.py`)
- SQLite database recording every trade with full context
- Entry conditions: RSI, trend, session, ATR, confidence, hour, day of week
- Computes win rate per symbol, per session, per hour
- Generates "learned lessons" section injected into every AI prompt
- The bot literally remembers what worked and what didn't

### Self-Evaluator (`self_evaluator.py`)
- After every losing trade: Groq analyzes what went wrong → extracts specific rule
- Example lesson: "Avoid SELL on GBPUSD when RSI > 45 near support"
- Every Sunday: full weekly review → 3-5 new lessons extracted
- Lessons accumulate permanently — bot gets smarter every week
- Severity scoring: minor lessons noted, major/critical lessons applied immediately

### Auto-Optimizer (`auto_optimizer.py`)
- Runs every weekend on recent market data
- Grid search: SL (1x-2.5x ATR) × TP (1.5:1-3:1 R:R) × Confidence (60-80%)
- Walk-forward validation using the GPU backtester (1,158 lines, CuPy optional)
- Only applies new parameters if improvement is statistically significant
- Saves optimization history for trend analysis

### The Learning Loop

```
Week 1: Bot trades with default params
  → 15 trades recorded with full context
  → 4 losing trades analyzed → 3 lessons extracted
  → Sunday: weekly evaluation → 4 more lessons
  → Backtester optimizes: SL 2.0x better than 1.5x → applied
  
Week 2: Bot trades with 7 lessons + optimized SL
  → Win rate improves from 45% to 52%
  → 2 new lessons → "London session best for EURUSD"
  → Optimizer confirms: keep SL 2.0x, increase TP to 2.5:1

Week 3: Bot trades with 9 lessons + refined params
  → Win rate 55%, avg R:R improved
  → The prompt now contains real trading wisdom
  
Week N: Bot has accumulated N×5 lessons
  → Each analysis considers dozens of learned patterns
  → Parameters continuously calibrated to market conditions
```

---

## Module Inventory

### Core Trading (13 files)

| File | Lines | Purpose |
|------|-------|---------|
| `wolf_engine.py` | 892 | Async orchestrator, main loop, position management |
| `engine.py` | ~300 | Sync engine (legacy backup) |
| `analyst.py` | ~320 | **Groq-first AI analyst** + learned lessons integration |
| `executor.py` | ~200 | MT5 trade execution, orders, SL/TP |
| `market_data.py` | ~150 | MT5 candle/tick/account data |
| `technical.py` | ~150 | RSI, MACD, BB, ADX, ATR, EMA, SMA, pivots |
| `config.py` | ~215 | FN rules (frozen) + all feature flags |
| `main.py` | ~80 | Entry point + Streamlit launch |
| `wolf_main.py` | ~100 | Wolf engine entry point |
| `app.py` | ~400 | Streamlit dashboard |
| `__init__.py` | ~60 | Package init |
| `phantom.bat` | ~170 | Windows batch launcher |
| `run_all.bat` | ~30 | Multi-service launcher |

### Self-Learning System (3 files) — NEW in v4

| File | Lines | Purpose |
|------|-------|---------|
| `trade_memory.py` | ~220 | Persistent trade DB + pattern extraction |
| `self_evaluator.py` | ~230 | Groq-powered weekly review + lesson extraction |
| `auto_optimizer.py` | ~250 | Automated grid search + walk-forward optimization |

### Risk Management (3 files)

| File | Lines | Purpose |
|------|-------|---------|
| `risk_manager.py` | ~250 | L1: FN Rule Guardian + L4: per-trade risk |
| `risk_management.py` | 174 | L2: Capital Ratchet / HWM tiers |
| `compliance.py` | 237 | L3: Limit orders, T+1, tranching |

### Intelligence Network (12 files)

| File | Lines | Purpose |
|------|-------|---------|
| `intelligence_feed.py` | 175 | Async RSS: SEC, DOJ, FDA, CNBC, CoinDesk |
| `nlp_engine.py` | 249 | Groq NLP: headline → sentiment JSON |
| `news.py` | ~600 | News sentinel: RSS + NewsAPI + Reddit |
| `news_collector.py` | ~350 | Multi-source aggregator |
| `watchlist.py` | 324 | Twitter 40+ accounts, 5 tiers |
| `twitter_collector.py` | ~650 | Twitter scraper |
| `reddit_collector.py` | ~850 | Reddit monitor (WSB, crypto) |
| `reddit_rss_collector.py` | ~450 | Reddit RSS (no API needed) |
| `economic_calendar.py` | ~350 | FOMC, CPI, NFP, earnings |
| `thematic.py` | 291 | Congress trades + WWIII protocol |
| `arbitrage.py` | 324 | BTC lead-lag WebSocket |
| `global_markets.py` | ~500 | Market session awareness |

### TITANIUM OSINT Collectors (14 files)

| File | Lines | Purpose |
|------|-------|---------|
| `gdelt_collector.py` | ~250 | Global events |
| `financial_intelligence_collector.py` | ~800 | SEC filings, earnings |
| `commodity_price_collector.py` | ~300 | Oil, gold, copper |
| `corporate_intel_collector.py` | ~150 | M&A, IPO tracking |
| `sanctions_tracker.py` | ~850 | OFAC/EU sanctions |
| `military_adsb_collector.py` | ~300 | Military aircraft |
| `military_procurement_collector.py` | ~770 | Defense contracts |
| `ship_tracking_collector.py` | ~300 | Maritime AIS |
| `trade_agreement_collector.py` | ~120 | Trade deals |
| `travel_advisory_collector.py` | ~200 | Travel advisories |
| `usgs_earthquake_collector.py` | ~250 | Seismic events |
| `official_documents_collector.py` | ~570 | Gov documents |
| `onchain.py` | ~280 | On-chain crypto |
| `polymarket.py` | ~850 | Prediction markets |

### Infrastructure (6 files)

| File | Lines | Purpose |
|------|-------|---------|
| `data_layer.py` | 392 | Async aiohttp session + data proxy |
| `data_feeds.py` | ~400 | Multi-source data feeds |
| `dashboard_engine.py` | ~250 | Dashboard state |
| `manager.py` | ~350 | Process manager |
| `base.py` | ~200 | Base classes |
| `backtester.py` | 1,158 | GPU Monte Carlo + walk-forward optimizer |

**Total: 51 files, ~16,000+ lines of Python**

---

## Risk Management (5 Layers)

### L1: FundedNext Rule Guardian
- `FundedNextRules` frozen dataclass — immutable at runtime
- Daily loss: blocks at 4.5% (0.5% buffer)
- Max drawdown: blocks at 9% (1% buffer)
- Position limit: hard block at 30
- Profit target detection: celebrates at +5%
- Emergency close-all within 1% of max loss

### L2: Capital Ratchet (HWM Tiers)
- +15% equity → floor locks at +5%
- +30% → locks at +15%
- +50% → locks at +30%
- +100% → locks at +70%
- Breach below floor → liquidate everything

### L3: Broker Compliance
- Limit orders only (no market order slippage)
- Max 25% settled cash per trade
- T+1 settlement tracking

### L4: Per-Trade Risk
- 1% max equity risk per position
- Max 3 correlated pairs
- Cooldown after 3 consecutive losses
- Max 10 trades per day

### L5: Emergency Circuit Breaker
- API health check before any liquidation
- Prevents false breach on network outage

---

## Intelligence Network

### Free (No API Keys)
- RSS: SEC, DOJ, FDA, CNBC, Reuters, CoinDesk
- Reddit RSS: r/wallstreetbets, r/cryptocurrency
- Economic calendar: FOMC, CPI, NFP hardcoded
- Urgent keywords: "flash crash", "rate cut", "halted"

### With Keys (Optional, all have free tiers)
- **Groq** → AI analyst + NLP (free: 30 req/min, 14,400/day)
- **NewsAPI** → broader news coverage (free: 100 req/day)
- **Quiver** → congressional trade mirror
- **Finnhub** → alternative market data
- **Twitter/X** → 40+ curated accounts

### TITANIUM Collectors (Deep Intel)
12+ OSINT collectors feeding geopolitical signals:
sanctions → currency impact, military ADS-B → defense rotation,
commodity prices → XAUUSD correlation, ship tracking → trade flows

---

## Deployment Guide

### Prerequisites
- FundedNext Free Trial account (already active, $6K)
- Groq API key (free at console.groq.com)
- Kamatera account (free 30-day trial at kamatera.com/free-trial)

### Step 1: Kamatera VPS (5 minutes)
```
1. Sign up at kamatera.com → $100 free credit
2. Create server: Windows Server 2022, 8GB RAM, 4 vCPUs, 80GB SSD
3. Location: New York (closest to FN servers)
4. Connect via Remote Desktop (RDP)
```

### Step 2: Install on VPS (15 minutes)
```powershell
# Install Python 3.12 from python.org
# Install Git from git-scm.com
# Install MetaTrader 5 from metaquotes.net

# Clone repo
git clone https://github.com/testingrounds511-maker/trader.git
cd trader

# Setup
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Configure
copy .env.example .env
notepad .env
# Fill: GROQ_API_KEY, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
```

### Step 3: MT5 Setup
```
1. Open MT5 → login with FundedNext credentials
2. Tools → Options → Expert Advisors → Allow algorithmic trading
3. Verify connection (green bar bottom-right)
```

### Step 4: Launch
```powershell
python main.py           # Dashboard mode
python main.py --auto    # Force auto execution
python main.py --check   # Validate config only
```

---

## Configuration

### Minimum Required (.env)
```env
GROQ_API_KEY=gsk_xxxxx          # Free at console.groq.com
MT5_LOGIN=12345678               # From FundedNext email
MT5_PASSWORD=xxxxx               # From FundedNext email
MT5_SERVER=FundedNext-Server     # From FundedNext email
```

### Recommended Symbols
```env
SYMBOLS=EURUSD,GBPUSD,USDJPY,XAUUSD
```
- EURUSD: most liquid, tightest spread, 1:100
- GBPUSD: high volatility, good momentum
- USDJPY: low spread, strong trends
- XAUUSD: big moves, 1:40 leverage

### Key Settings
```env
TIMEFRAME=H1                     # 1-hour candles
CHECK_INTERVAL_MINUTES=5         # Analyze every 5 min
RISK_PER_TRADE_PCT=0.01          # 1% risk per trade
MANUAL_MODE=false                # Auto execute (zona gris in Free Trial)
INITIAL_CAPITAL_USD=6000         # Match your FN account
```

---

## Strategy & Math

### Signal Flow
```
1. Fetch 200 H1 candles from MT5
2. Compute: RSI, MACD, BB, ADX, ATR, EMA(20,50)
3. Multi-TF confirmation: H1 + H4 trend
4. NLP: headline sentiment from RSS feeds
5. Groq receives: technicals + account + news + LEARNED LESSONS
6. Returns: BUY/SELL/HOLD with confidence, SL, TP
7. Signal confirmation: 2 consecutive cycles same direction
8. Risk check: all 5 layers pass
9. Sizing: 1% risk, ATR-based SL, 2:1 R:R
10. Execute in MT5
```

### Math for $6K / $300 Target
- Risk per trade: 1% = $60
- R:R ratio: 2:1 → Win = +$120, Loss = -$60
- Need: $300 net profit = 2.5 net winning trades
- With 50% win rate over 10 trades: 5×$120 - 5×$60 = $300 ✓
- Conservative: 3-5 good trades in 14 days

---

## Operational Playbook

### Phase 1: Validation (March 16-30) — $0 cost
- Deploy on Kamatera free trial
- Run Free Trial with bot in auto mode
- Bot learns from every trade
- Validate: does the strategy make money?

### Phase 2: Calibration (April) — $0 cost
- Second Free Trial (unlimited free trials)
- Self-evaluator + auto-optimizer running weekly
- Accumulated lessons improving decisions
- Target: consistent >50% win rate

### Phase 3: Real Challenge (May) — ~$40
- FundedNext Futures $6K challenge
- Bots 100% legal in Futures
- Bot runs full auto with learned wisdom
- Target: pass challenge (+5%)

### Phase 4: Funded Account (June-August)
- $6K funded → scaling to $25K → $50K
- 3-5% monthly → $750-2,500/month at $50K
- Profit split 90%
- Bot continuously learning and optimizing

### Phase 5: October 2026 Target
- Estimated accumulated profit: $2,000-$8,000
- Account scaled to $50K-$100K
- Bot running 24/7 self-optimized
- Foundation for long-term passive income

### Emergency Procedures
- Daily loss > 4%: bot pauses entries
- Max DD > 8%: reduces position sizes
- Max DD > 9%: blocks all trades
- Network outage: pause, does NOT liquidate on stale data

---

## Cost Breakdown

### Monthly Operating Cost

| Component | Cost |
|-----------|------|
| Groq API (analyst + NLP) | $0 (free tier) |
| MT5 data (via FundedNext) | $0 |
| RSS feeds (SEC, DOJ, CNBC) | $0 |
| Reddit RSS | $0 |
| VPS (Kamatera month 1) | $0 (free trial) |
| VPS (month 2+, ForexCheapVPS) | $5 |
| **Total month 1** | **$0** |
| **Total month 2+** | **$5** |

### Investment to Start

| Item | Cost |
|------|------|
| Groq signup | $0 |
| Kamatera signup | $0 ($2 auth, refunded) |
| FundedNext Free Trial | $0 |
| FundedNext Futures challenge | ~$40 (when ready) |
| **Total to validate** | **$0** |
| **Total to go live** | **~$45** |

---

## Future Roadmap

### Near-term (1-3 months)
- [ ] Telegram alert module (trade notifications to phone)
- [ ] Tradovate API executor (for FundedNext Futures)
- [ ] Multi-account support (parallel challenges)
- [ ] Dashboard improvements (equity curve chart, trade heatmap)

### Medium-term (3-6 months)
- [ ] OpenClaw integration (24/7 research agent)
- [ ] cTrader executor (additional platform support)
- [ ] Portfolio correlation matrix (cross-pair risk)
- [ ] Sentiment scoring model (trained on trade memory data)

### Long-term (6-12 months)
- [ ] Reinforcement Learning module (if GPU available)
- [ ] Multi-prop-firm scaling (FTMO + FundedNext + The5ers)
- [ ] Custom indicator development from learned patterns
- [ ] Public API for signal sharing

---

## Quick Reference

```bash
# Validate config
python main.py --check

# Run with dashboard
python main.py

# Force auto execution
python main.py --auto

# Force manual (signals only)
python main.py --manual

# Run Wolf async engine directly
python wolf_main.py

# Run backtester
python -c "from backtester import Backtester, BacktestConfig; \
  Backtester().run(BacktestConfig(symbols=['EURUSD'], \
  initial_capital=6000, days_to_backtest=90))"

# Run optimizer manually
python -c "from auto_optimizer import AutoOptimizer; \
  print(AutoOptimizer().run_optimization())"

# Check trade memory stats
python -c "from trade_memory import TradeMemory; \
  print(TradeMemory().get_all_stats())"
```

---

*"The bot that learns from its mistakes today compounds its wisdom tomorrow. In prop trading, the edge isn't speed — it's memory."*
