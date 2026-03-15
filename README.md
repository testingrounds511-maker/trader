# 👻 PHANTOM TRADER v3 — FundedNext Free Trial Edition

> Claude AI-powered forex trading bot for MetaTrader 5.
> Configured specifically for FundedNext Free Trial rules.

---

## 📋 FundedNext Free Trial Rules (Hardcoded)

| Rule                    | Value                                      |
|-------------------------|--------------------------------------------|
| Profit Target           | 5% of initial balance                      |
| Daily Loss Limit        | 5% of account balance                      |
| Maximum Loss Limit      | 10% of initial balance                     |
| Time Limit              | 14 calendar days from first trade          |
| Minimum Trading Days    | 3 days within 14-day period                |
| Max Open Positions      | 30 at a time                               |
| Leverage (Forex)        | 1:100                                      |
| Leverage (Commodities)  | 1:40                                       |
| Leverage (Indices)      | 1:20                                       |
| Platform                | MetaTrader 5                               |
| Account Type            | Swap account                               |
| Weekend Holding         | Allowed                                    |
| EAs                     | NOT allowed (we use Python scripts, not EA) |
| Balance Options         | $6,000 — $200,000                          |

⚠️ **IMPORTANT**: FundedNext prohibits Expert Advisors (EAs). This bot uses
Python's MetaTrader5 library which communicates via IPC, NOT as an MT5 EA.
However, this is a gray area — use at your own discretion. The bot includes
a "MANUAL CONFIRM" mode where it suggests trades and YOU click to execute.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│              PHANTOM TRADER v3 — FundedNext Edition       │
│                                                          │
│  ┌───────────┐    ┌───────────┐    ┌──────────────────┐  │
│  │  MT5 Data  │───▶│  Claude   │───▶│  MT5 Executor    │  │
│  │  Feed      │    │  Analyst  │    │  (or Manual)     │  │
│  └───────────┘    └───────────┘    └──────────────────┘  │
│        │                │                │               │
│        ▼                ▼                ▼               │
│  ┌──────────────────────────────────────────────────────┐│
│  │   FundedNext Rule Guardian (always-on compliance)    ││
│  │   • Daily Loss: -5% → STOP   • Max Loss: -10% → STOP││
│  │   • Max 30 positions  • Profit Target: +5% → DONE!  ││
│  └──────────────────────────────────────────────────────┘│
│        │                                                 │
│  ┌──────────────────────────────────────────────────────┐│
│  │         Streamlit GUI Dashboard                      ││
│  │  • Rule Compliance  • P&L  • Positions  • Trades    ││
│  └──────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 Setup

### Prerequisites
- Windows 10/11 (MT5 Python API requires Windows)
- Python 3.10+
- MetaTrader 5 installed with FundedNext Free Trial account
- Anthropic API key

### 1. Install

```bash
cd phantom-fn
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
copy .env.example .env
# Edit .env with your credentials
```

### 3. MT5 Setup
1. Sign up at https://app.fundednext.com/subscribe/1?account=swap&account-type=free-trial
2. Choose balance ($6K-$200K — recommend $100K for meaningful lot sizes)
3. Install MT5, log in with credentials from FundedNext email
4. Enable: Tools → Options → Expert Advisors → Allow algorithmic trading

### 4. Run

```bash
python main.py           # Full auto mode
python main.py --manual  # Manual confirm mode (RECOMMENDED for FN)
python main.py --check   # Validate config only
```

---

## ⚡ Execution Modes

### 🤖 AUTO Mode
Bot executes trades automatically via MT5 Python API.
⚠️ May violate FundedNext EA policy — use at your own risk.

### 👤 MANUAL Mode (Recommended)
Bot analyzes markets, shows signals on dashboard with entry/SL/TP.
YOU place the trade manually in MT5. Bot monitors compliance.

---

## 📁 Project Structure

```
phantom-fn/
├── main.py                 # Entry point
├── config.py               # Configuration + FN rules
├── requirements.txt        # Dependencies
├── .env.example            # Template config
├── bot/
│   ├── engine.py           # Main trading loop
│   ├── analyst.py          # Claude AI analysis
│   ├── executor.py         # MT5 trade execution
│   ├── market_data.py      # MT5 data fetcher
│   ├── technical.py        # TA indicators
│   └── risk_manager.py     # FundedNext rule guardian
├── sentinel/
│   └── news.py             # News sentiment monitor
├── dashboard/
│   └── app.py              # Streamlit GUI
└── data/
    └── trades.json         # Trade history
```
