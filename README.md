# 👻 PHANTOM TRADER — Complete Trading Intelligence Platform

> **Codename:** Phantom Wolf | **Target:** FundedNext Free Trial ($6,000)
> **Deploy:** Nitro V14 "Kiwiclaw" (i5 / 16GB / RTX 3050 6GB)
> **Brain:** Claude Haiku 4.5 (Anthropic API) + Groq NLP Sniper
> **Operator:** JT @ DIPLANE/MINREL

---

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [FundedNext Rules](#fundednext-free-trial-rules)
3. [Architecture](#architecture)
4. [Module Inventory (48 files)](#module-inventory)
5. [Deployment on Kiwiclaw](#deployment-guide-kiwiclaw)
6. [Configuration](#configuration)
7. [Execution Modes](#execution-modes)
8. [Strategy Logic](#strategy-logic)
9. [Risk Management Stack (5 Layers)](#risk-management-stack)
10. [Intelligence Network](#intelligence-network)
11. [Dashboard](#dashboard)
12. [Operational Playbook (14-Day Plan)](#operational-playbook)
13. [API Costs](#api-cost-estimate)

---

## System Overview

Phantom Trader is a multi-module trading intelligence platform built across **48+ Python files**. Originally designed for Alpaca (US stocks + crypto), now adapted for **MetaTrader 5** targeting the **FundedNext Free Trial** prop firm challenge.

The system combines:
- **Claude AI** for trade decisions (technical + fundamental + sentiment)
- **Groq NLP Sniper** for real-time headline analysis (SEC, DOJ, FDA, Reuters)
- **Multi-timeframe technical analysis** (RSI, MACD, Bollinger, ADX, ATR)
- **Intelligence feeds** from RSS, Reddit, Twitter, GDELT
- **5-layer risk management** stack enforcing FundedNext compliance
- **Async architecture** (Wolf Engine v3.6) with 1-second resolution loop
- **12+ TITANIUM OSINT collectors** (GDELT, military ADS-B, sanctions, ship tracking, commodities, financial intel, earthquakes, official documents)
- **Lead-lag arbitrage** via WebSocket (BTC price spike → equity lag trades)
- **Congressional trade mirroring** (Quiver Quantitative API)
- **WWIII Protocol** — crisis detection auto-rotating to defense basket
- **GPU-accelerated backtester** with Monte Carlo + walk-forward optimization
- **Capital ratchet** (HWM tiers that lock in profits, never go down)

---

## FundedNext Free Trial Rules

**Active Account: $6,000 balance** (confirmed from FN dashboard)

| Rule | Value | Dollar Amount | Bot Safety Buffer |
|------|-------|---------------|-------------------|
| Profit Target | 5% | $300 | — (target, not limit) |
| Daily Loss Limit | 5% | $300/day | Stops at 4.5% ($270) |
| Maximum Loss Limit | 10% | $600 total | Stops at 9% ($540) |
| Time Limit | 14 calendar days | — | Warning at day 12 |
| Min Trading Days | 3 days | — | Auto-tracked |
| Max Open Positions | 30 | — | Hard block at 30 |
| Leverage (Forex) | 1:100 | — | Auto-detected |
| Leverage (Commodities) | 1:40 | — | Auto-detected |
| Leverage (Indices) | 1:20 | — | Auto-detected |
| Platform | MetaTrader 5 | — | Python IPC (not EA) |
| EAs | **PROHIBITED** | — | Manual mode default |
| Weekend Holding | Allowed | — | No Friday close needed |

**EA POLICY:** FundedNext prohibits Expert Advisors. This bot uses Python's `MetaTrader5` library (interprocess communication), technically NOT an EA. Default **MANUAL MODE** makes it a pure analysis/signal tool — you execute in MT5.

---

## Architecture

```
╔══════════════════════════════════════════════════════════════════╗
║                   PHANTOM WOLF v3.6                              ║
║              "Quantum Predator" Async Engine                     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  ║
║  │  MT5 Data   │  │  Claude AI  │  │  Groq NLP Sniper        │  ║
║  │  market_data│  │  analyst.py │  │  nlp_engine.py          │  ║
║  │  data_layer │  │             │  │  (headline → sentiment) │  ║
║  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  ║
║         │                │                       │               ║
║         ▼                ▼                       ▼               ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │              wolf_engine.py — Async Orchestrator          │   ║
║  │  • 1-sec resolution loop  • TaskGroup concurrency         │   ║
║  │  • Multi-TF analysis      • Signal confirmation (2-cycle) │   ║
║  └─────────────────────────┬────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │                 RISK MANAGEMENT STACK (5 layers)           │   ║
║  │                                                            │   ║
║  │  L1: FundedNext Rule Guardian  (risk_manager.py)           │   ║
║  │      → Daily loss 5%, Max loss 10%, 30 pos limit           │   ║
║  │                                                            │   ║
║  │  L2: Capital Ratchet System    (risk_management.py)        │   ║
║  │      → HWM tiers: +15%→lock 5%, +30%→lock 15%             │   ║
║  │                                                            │   ║
║  │  L3: Broker Compliance         (compliance.py)             │   ║
║  │      → Limit orders only, capital tranching, slippage      │   ║
║  │                                                            │   ║
║  │  L4: Per-Trade Risk Manager    (risk_manager.py)           │   ║
║  │      → 1% max risk, correlation limits, cooldowns          │   ║
║  │                                                            │   ║
║  │  L5: Emergency Circuit Breaker                             │   ║
║  │      → API health check before liquidation                 │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │              INTELLIGENCE NETWORK                          │   ║
║  │  📡 SEC/DOJ/FDA/CNBC RSS    📰 NewsAPI + Reddit            │   ║
║  │  🐦 Twitter 40+ accounts    🌍 GDELT events                │   ║
║  │  💰 Financial intel (SEC)   🎯 Congress trades             │   ║
║  │  ⚡ BTC arbitrage WebSocket  📅 Economic calendar           │   ║
║  │  🚢 Ship tracking  ✈️ Military ADS-B  🏛️ Sanctions         │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │  MT5 EXECUTOR → Auto: order_send() | Manual: signal card   │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                            │                                     ║
║  ┌─────────────────────────┴────────────────────────────────┐   ║
║  │  STREAMLIT DASHBOARD — FN compliance + signals + P&L       │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Module Inventory

### Core Trading (Active for FundedNext)

| File | Lines | Role |
|------|-------|------|
| `wolf_engine.py` | 892 | Async orchestrator — main loop, signal flow, position mgmt |
| `engine.py` | ~300 | Sync engine (legacy backup) |
| `analyst.py` | 179 | Claude AI decision maker — prompt builder, JSON parser |
| `executor.py` | ~200 | MT5 trade execution — orders, SL/TP, position close |
| `market_data.py` | ~150 | MT5 candle/tick/account data fetcher |
| `technical.py` | ~150 | RSI, MACD, BB, ADX, ATR, EMA, SMA, pivots |
| `config.py` | 138 | FN rules (frozen dataclass) + env config |
| `main.py` | ~80 | Entry point + Streamlit launch |
| `wolf_main.py` | ~100 | Wolf engine entry point |
| `app.py` | ~400 | Streamlit dashboard with FN compliance |

### Risk Management (5 Layers)

| File | Lines | Role |
|------|-------|------|
| `risk_manager.py` | ~250 | L1: FN Rule Guardian + L4: per-trade risk |
| `risk_management.py` | 174 | L2: Capital Ratchet / HWM tiers |
| `compliance.py` | 237 | L3: Limit orders, T+1 settlement, tranching |

### Intelligence Network

| File | Lines | Role |
|------|-------|------|
| `intelligence_feed.py` | 175 | Async RSS: SEC, DOJ, FDA, CNBC, CoinDesk |
| `nlp_engine.py` | 249 | Groq NLP: headline → sentiment/action JSON |
| `news.py` | ~600 | News sentinel: RSS + NewsAPI + Reddit + urgency |
| `news_collector.py` | ~350 | Multi-source news aggregator |
| `watchlist.py` | 324 | Twitter/X 40+ accounts in 5 tiers |
| `twitter_collector.py` | ~650 | Twitter scraper with keyword matching |
| `reddit_collector.py` | ~850 | Reddit monitor (WSB, crypto subs) |
| `reddit_rss_collector.py` | ~450 | Reddit RSS fallback (no API needed) |
| `economic_calendar.py` | ~350 | FOMC, CPI, NFP, earnings dates |
| `thematic.py` | 291 | Congress trades + WWIII crisis detector |
| `arbitrage.py` | 324 | BTC lead-lag WebSocket detector |

### TITANIUM OSINT Collectors

| File | Lines | Role |
|------|-------|------|
| `gdelt_collector.py` | ~250 | Global events → geopolitical risk |
| `financial_intelligence_collector.py` | ~800 | SEC filings, earnings, insider trades |
| `commodity_price_collector.py` | ~300 | Oil, gold, copper, wheat feeds |
| `corporate_intel_collector.py` | ~150 | M&A, IPO, bankruptcy tracking |
| `sanctions_tracker.py` | ~850 | OFAC/EU sanctions monitoring |
| `military_adsb_collector.py` | ~300 | Military aircraft tracking |
| `military_procurement_collector.py` | ~770 | Defense contract monitoring |
| `ship_tracking_collector.py` | ~300 | Maritime AIS vessel tracking |
| `trade_agreement_collector.py` | ~120 | International trade deals |
| `travel_advisory_collector.py` | ~200 | State Dept travel advisories |
| `usgs_earthquake_collector.py` | ~250 | Seismic events → supply chain risk |
| `official_documents_collector.py` | ~570 | Government document scraper |
| `onchain.py` | ~280 | On-chain crypto analytics |
| `polymarket.py` | ~850 | Prediction market sentiment |

### Infrastructure

| File | Lines | Role |
|------|-------|------|
| `data_layer.py` | 392 | Async aiohttp session + data proxy |
| `data_feeds.py` | ~400 | Multi-source data feed aggregator |
| `global_markets.py` | ~500 | Global market session awareness |
| `dashboard_engine.py` | ~250 | Dashboard state management |
| `manager.py` | ~350 | Process/service manager |
| `base.py` | ~200 | Base classes and utilities |
| `backtester.py` | 1158 | GPU Monte Carlo + walk-forward optimizer |

**Total: ~48 files, ~15,000+ lines of Python**

---

## Deployment Guide (Kiwiclaw)

### Hardware: Nitro V14
- CPU: Intel i5 (12th gen) — handles async loop + TA easily
- RAM: 16GB — plenty for all modules + MT5
- GPU: RTX 3050 6GB — CuPy Monte Carlo in backtester
- OS: Windows 10/11 (required for MT5 Python API)

### Step 1: MT5 + FundedNext

Already done — $6K Free Trial active. Ensure:
1. MT5 installed and logged in with FN credentials
2. Tools → Options → Expert Advisors → Allow algorithmic trading ✓
3. Note: login number, password, server name from FN email

### Step 2: Python Environment

```powershell
cd trader
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
```

### Step 3: Configure .env

```powershell
copy .env.example .env
notepad .env
```

Fill in MT5 credentials + Anthropic API key (minimum). All intel feeds are optional.

### Step 4: First Run (Validation)

```powershell
python main.py --check
```

This validates config, MT5 connection, and FN account info without trading.

### Step 5: Launch

```powershell
# Dashboard mode (recommended)
python main.py

# Or Wolf async engine directly
python wolf_main.py

# Or use the batch launcher
phantom.bat
```

---

## Configuration

### Minimum Required (.env)

```env
MT5_LOGIN=<your_number>
MT5_PASSWORD=<your_password>
MT5_SERVER=<FundedNext-Server>
ANTHROPIC_API_KEY=<your_key>
```

### Recommended Symbols for $6K Account

```env
SYMBOLS=EURUSD,GBPUSD,USDJPY,XAUUSD
```

Why these 4:
- **EURUSD:** Most liquid pair, tightest spread, 1:100 leverage
- **GBPUSD:** High volatility, good for momentum
- **USDJPY:** Low spread, strong trends, BOJ catalyst potential
- **XAUUSD:** High ATR = bigger moves, 1:40 leverage (still good for $6K)

### Position Sizing for $6K

With 1% risk ($60 per trade) and 1:100 leverage:
- EURUSD: ~0.04-0.06 lots (depending on SL distance)
- XAUUSD: ~0.02-0.03 lots (wider ATR, so smaller lot)

The bot calculates this automatically via `technical.calculate_lot_size()`.

---

## Execution Modes

### 👤 MANUAL (Default)
Bot analyzes → shows signal on dashboard → YOU execute in MT5.
Safe for FN EA policy. Recommended.

### 🤖 AUTO (`MANUAL_MODE=false`)
Bot executes via `mt5.order_send()`. Gray area with FN.
All FN rules still enforced by risk stack.

### 📊 BACKTEST
```powershell
python -c "from backtester import Backtester, BacktestConfig; b=Backtester(); b.run(BacktestConfig(symbols=['EURUSD'], initial_capital=6000, days_to_backtest=90))"
```
GPU-accelerated Monte Carlo on RTX 3050.

---

## Strategy Logic

### Signal Flow

```
1. Fetch 200 H1 candles per symbol from MT5
2. Compute: RSI(14), MACD(12,26,9), BB(20,2), ADX(14), ATR(14), EMA(20,50)
3. Multi-TF confirmation: H1 signal + H4 trend alignment
4. NLP (if Groq available): headline sentiment from RSS feeds
5. Claude AI receives: technicals + account + news + FN rules context
6. Claude returns: BUY/SELL/HOLD, confidence, SL, TP, reasoning
7. Signal confirmation: same direction on 2 consecutive cycles
8. Risk check: FN compliance (all 5 layers)
9. Sizing: 1% risk, ATR-based SL (1.5x), TP at 2:1 R:R
10. Execute (auto) or display (manual)
```

### Math for $6K Challenge

- Risk per trade: 1% = $60
- R:R ratio: 2:1 → Win = +$120, Loss = -$60
- Target: $300 (5%) = 2.5 winning trades net
- With 50% win rate over 10 trades: 5W × $120 - 5L × $60 = $300 ✓
- Conservative path: 3-5 good trades in 14 days

---

## Risk Management Stack

### L1: FundedNext Rule Guardian
- Frozen `FundedNextRules` dataclass — immutable at runtime
- Daily loss: blocks at 4.5% (0.5% buffer before 5%)
- Max drawdown: blocks at 9% (1% buffer before 10%)
- Position limit: hard block at 30
- Profit target detection: stops trading at +5%
- Emergency close-all within 1% of max loss

### L2: Capital Ratchet (HWM)
- +15% equity → floor locks at +5%
- +30% equity → floor locks at +15%
- +50% equity → floor locks at +30%
- Breach below floor → liquidate everything

### L3: Broker Compliance
- Limit orders only (no market order slippage)
- Max 25% settled cash per trade (tranching)
- T+1 settlement tracking

### L4: Per-Trade Risk
- 1% max equity risk per position
- Max 3 correlated pairs (e.g., EURUSD + GBPUSD + EURGBP)
- Cooldown after 3 consecutive losses
- Max 10 trades per day

### L5: Emergency Circuit Breaker
- Health check API before any liquidation
- Prevents false breach on network outage ($0 equity ghost)

---

## Intelligence Network

### Free (No API Keys)
- RSS: SEC press, DOJ news, FDA approvals, CNBC, Reuters, CoinDesk
- Reddit RSS: r/wallstreetbets, r/cryptocurrency
- Economic calendar: FOMC, CPI, NFP hardcoded
- Urgent keywords: "flash crash", "rate cut", "halted"

### With Keys (Optional)
- **Groq NLP** → headline → structured sentiment JSON
- **NewsAPI** → broader coverage, keyword filter
- **Quiver** → congressional trade mirror
- **Finnhub** → alternative market data
- **Twitter/X** → 40+ curated accounts (5 tiers)

### TITANIUM Collectors (Deep Intel)
12+ OSINT collectors from the TITANIUM VANGUARD platform:
- Sanctions → currency impact
- Military ADS-B → defense basket rotation
- Commodity prices → XAUUSD correlation
- Ship tracking → trade flow signals
- GDELT → geopolitical event risk

---

## Dashboard

Streamlit GUI at `localhost:8501`:

**Top Row:** Balance | Equity | Profit vs Target | Daily Loss | Max DD | Days Left

**Compliance:** Green/yellow/red status per FN rule + progress bars

**Signals (Manual):** Direction, symbol, lot, entry, SL, TP, confidence, reasoning

**Positions:** Live table with P/L per position

**Decision Log:** Last 20 AI decisions color-coded

**Trade History:** All trades with timestamps

**API Costs:** Token count + estimated USD

---

## Operational Playbook

### Day 1-2: Setup & Calibration
- Deploy on Kiwiclaw, verify MT5 connection
- Run MANUAL mode, observe signals (don't trade yet)
- Verify FN dashboard matches bot's compliance panel
- Backtest on 90 days of H1 data

### Day 3-5: Conservative Start
- Take only ≥80% confidence signals
- Max 2-3 trades per day
- Focus: EURUSD, GBPUSD (tightest spreads)
- Goal: complete 3 minimum trading days

### Day 6-10: Push for Target
- Lower threshold to 70% if win rate > 50%
- Add XAUUSD for volatility plays
- Stop if daily loss > 3%
- Goal: accumulate towards $300

### Day 11-14: Protect & Close
- Target reached → STOP TRADING, close everything
- Close to target → only very high confidence
- In drawdown → reduce sizes, wait for A+ setups
- Day 14 → account auto-disables

### Emergency Procedures
- Daily loss > 4% → bot pauses entries
- Max DD > 8% → bot warns, reduces sizes
- Max DD > 9% → bot blocks all trades
- Network outage → pause, do NOT liquidate on stale data

---

## API Cost Estimate

| Component | Per Analysis | Daily (20 cycles × 4 symbols) |
|-----------|-------------|-------------------------------|
| Claude Haiku 4.5 | ~$0.001 | ~$0.08 |
| Groq NLP | Free tier | $0.00 |
| NewsAPI | Free tier | $0.00 |
| **Total** | | **~$0.08/day** |

**14-day trial: ~$1.12 in API costs.**

---

*"In prop trading, survival IS the strategy. The bot that protects capital today lives to compound tomorrow."*
