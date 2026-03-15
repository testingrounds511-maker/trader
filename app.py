"""Phantom Trader v3 — FundedNext Dashboard.

Streamlit-based trading terminal with FN compliance monitoring.
"""

import json
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ═══════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════
st.set_page_config(
    page_title="PHANTOM TRADER v3 — FundedNext",
    page_icon="👻",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Outfit:wght@400;500;700&display=swap');

    .stApp {
        background-color: #0a0e17;
        color: #e0e6ed;
        font-family: 'Outfit', sans-serif;
    }

    .main-header {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.8rem;
        font-weight: 700;
        color: #00ff88;
        text-shadow: 0 0 20px rgba(0,255,136,0.3);
        padding: 0.5rem 0;
        border-bottom: 1px solid #1a2332;
        margin-bottom: 1rem;
    }

    .fn-badge {
        display: inline-block;
        background: linear-gradient(135deg, #ff6b35, #ff8c42);
        color: white;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 1px;
        margin-left: 10px;
        vertical-align: middle;
    }

    .signal-card {
        background: linear-gradient(135deg, #1a1f2e, #252b3d);
        border: 1px solid #00ff88;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        box-shadow: 0 0 15px rgba(0,255,136,0.1);
    }

    .signal-sell {
        border-color: #ff4757;
        box-shadow: 0 0 15px rgba(255,71,87,0.1);
    }

    .emergency-banner {
        background: linear-gradient(90deg, #ff4757, #ff6b81);
        color: white;
        padding: 0.8rem;
        border-radius: 8px;
        text-align: center;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        animation: pulse 2s infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
    }

    div[data-testid="stSidebar"] {
        background-color: #0d1117;
        border-right: 1px solid #1e2d42;
    }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════
# ENGINE SINGLETON
# ═══════════════════════════════════════════
@st.cache_resource
def get_engine():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from bot.engine import TradingEngine
    return TradingEngine()


engine = get_engine()


# ═══════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════
st.markdown(
    '<div class="main-header">👻 PHANTOM TRADER v3'
    '<span class="fn-badge">FUNDEDNEXT FREE TRIAL</span></div>',
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════
# SIDEBAR — Controls
# ═══════════════════════════════════════════
with st.sidebar:
    st.markdown("### Controls")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("START", use_container_width=True, type="primary"):
            if engine.start():
                st.success("Started!")
            else:
                st.error("Check config")
    with col2:
        if st.button("STOP", use_container_width=True):
            engine.stop()
            st.info("Stopped")

    col3, col4 = st.columns(2)
    with col3:
        if st.button("PAUSE", use_container_width=True):
            engine.pause()
    with col4:
        if st.button("RESUME", use_container_width=True):
            engine.resume()

    st.divider()

    st.markdown("### Status")
    state = engine.get_state()

    status_emoji = "🟢" if state["running"] and not state["paused"] else "🟡" if state["paused"] else "🔴"
    mode_emoji = "👤" if state["manual_mode"] else "🤖"
    st.markdown(f"{status_emoji} **Engine**: {'Running' if state['running'] else 'Stopped'}")
    st.markdown(f"{mode_emoji} **Mode**: {'Manual Confirm' if state['manual_mode'] else 'Auto Execute'}")
    st.markdown(f"🔄 **Cycles**: {state['cycle_count']}")
    if state["last_cycle"]:
        st.markdown(f"⏱️ **Last**: {state['last_cycle'][:19]}")

    st.divider()
    st.markdown("### API Costs")
    costs = state.get("api_costs", {})
    st.markdown(f"Tokens: {costs.get('total_tokens', 0):,}")
    st.markdown(f"Cost: ${costs.get('estimated_cost_usd', 0):.4f}")

    st.divider()
    st.markdown("### Config")
    cfg = state.get("config", {})
    st.markdown(f"**Symbols**: {', '.join(cfg.get('symbols', []))}")
    st.markdown(f"**Timeframe**: {cfg.get('timeframe', 'H1')}")
    st.markdown(f"**Interval**: {cfg.get('interval', 300)}s")
    st.markdown(f"**Risk/Trade**: {cfg.get('risk_per_trade', 0.01)*100:.1f}%")


# ═══════════════════════════════════════════
# MAIN CONTENT
# ═══════════════════════════════════════════
state = engine.get_state()
account = state.get("account", {})
metrics = state.get("live_metrics", {})
risk_status = state.get("risk_status", {})
compliance = state.get("compliance", {})

# ─── FN COMPLIANCE BANNER ───
if not compliance.get("allowed", True):
    reasons = compliance.get("reasons", [])
    for r in reasons:
        if "PROFIT TARGET" in r:
            st.markdown(
                '<div class="emergency-banner">🎉 PROFIT TARGET REACHED — CHALLENGE COMPLETE! 🎉</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="emergency-banner">⛔ TRADING BLOCKED: {r}</div>',
                unsafe_allow_html=True,
            )
    st.markdown("")

for w in compliance.get("warnings", []):
    st.warning(w)

# ─── TOP METRICS ROW ───
st.markdown("### Account & Compliance")
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    balance = account.get("balance", 0)
    st.metric("Balance", f"${balance:,.2f}")

with c2:
    equity = account.get("equity", 0)
    st.metric("Equity", f"${equity:,.2f}")

with c3:
    pct = metrics.get("profit_pct", 0)
    target = metrics.get("target_pct", 5)
    st.metric("Profit vs Target", f"{pct:.2f}%", f"Target: {target:.1f}%")

with c4:
    daily = metrics.get("daily_loss_pct", 0)
    limit = metrics.get("daily_limit_pct", 5)
    st.metric("Daily Loss", f"{daily:.2f}%", f"Limit: {limit:.1f}%", delta_color="inverse")

with c5:
    maxdd = metrics.get("max_drawdown_pct", 0)
    maxlimit = metrics.get("max_limit_pct", 10)
    st.metric("Max Drawdown", f"{maxdd:.2f}%", f"Limit: {maxlimit:.1f}%", delta_color="inverse")


# ─── FN PROGRESS BARS ───
st.markdown("### Challenge Progress")
col_a, col_b, col_c = st.columns(3)

with col_a:
    profit_pct = max(0, metrics.get("profit_pct", 0))
    progress = min(1.0, profit_pct / 5.0)
    st.markdown(f"**Profit Target**: {profit_pct:.2f}% / 5.00%")
    st.progress(progress)

with col_b:
    days_count = risk_status.get("trading_days_count", 0)
    days_progress = min(1.0, days_count / 3.0)
    st.markdown(f"**Trading Days**: {days_count} / 3 minimum")
    st.progress(days_progress)

with col_c:
    days_left = risk_status.get("days_remaining", 14)
    time_progress = min(1.0, (14 - days_left) / 14.0)
    st.markdown(f"**Time Remaining**: {days_left} days")
    st.progress(time_progress)


# ─── EQUITY CURVE ───
st.markdown("### Equity Curve")
history = state.get("trade_history", [])
if history and len(history) > 1:
    initial = risk_status.get("initial_balance", 100000)
    equity_data = [{"Trade": 0, "Equity": initial}]
    running = initial
    for i, t in enumerate(history):
        # Simple approximation from trade data
        running += t.get("profit", 0) if "profit" in t else 0
        equity_data.append({"Trade": i + 1, "Equity": running})

    eq_df = pd.DataFrame(equity_data)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=eq_df["Trade"], y=eq_df["Equity"],
        mode="lines",
        line=dict(color="#00ff88", width=2),
        fill="tozeroy",
        fillcolor="rgba(0,255,136,0.05)",
    ))
    # Target line
    fig.add_hline(y=initial * 1.05, line_dash="dash", line_color="#ffd93d",
                  annotation_text="5% Target")
    # Max loss line
    fig.add_hline(y=initial * 0.90, line_dash="dash", line_color="#ff4757",
                  annotation_text="10% Max Loss")

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0a0e17",
        plot_bgcolor="#0d1421",
        height=300,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_title="Trade #",
        yaxis_title="Equity ($)",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Equity curve will appear after trades are recorded")


# ─── SIGNALS (Manual Mode) ───
signals = state.get("signals", [])
if signals:
    st.markdown("### Pending Signals")
    st.caption("Execute these trades manually in MT5, then click Executed or Dismiss.")

    for i, sig in enumerate(signals):
        sig_type = sig.get("type", "")
        if sig_type == "EMERGENCY":
            st.error(f"🚨 **EMERGENCY**: {sig.get('message', 'Close all positions!')}")
            if st.button(f"Dismiss Emergency #{i}", key=f"dismiss_emg_{i}"):
                engine.clear_signal(i)
                st.rerun()
            continue

        direction = sig.get("direction", "?")
        symbol = sig.get("symbol", "?")
        css_class = "signal-card" if direction == "BUY" else "signal-card signal-sell"
        color = "#00ff88" if direction == "BUY" else "#ff4757"

        st.markdown(f"""
        <div class="{css_class}">
            <span style="color:{color}; font-size:1.2rem; font-weight:700;">
                {'🟢' if direction == 'BUY' else '🔴'} {direction} {symbol}
            </span>
            <span style="color:#6b7b8d; margin-left:15px;">
                Confidence: {sig.get('confidence', 0):.0%} | Risk: {sig.get('risk_level', '?')}
            </span>
            <br>
            <span style="font-family:'JetBrains Mono',monospace; font-size:0.9rem;">
                Entry: {sig.get('entry_price', 0):.5f} &nbsp;|&nbsp;
                SL: {sig.get('sl', 0):.5f} &nbsp;|&nbsp;
                TP: {sig.get('tp', 0):.5f} &nbsp;|&nbsp;
                Lots: {sig.get('lot_size', 0):.2f}
            </span>
            <br>
            <span style="color:#8b95a5; font-size:0.8rem;">
                {sig.get('reasoning', '')}
            </span>
        </div>
        """, unsafe_allow_html=True)

        col_exec, col_dismiss = st.columns([1, 1])
        with col_exec:
            if st.button(f"Executed #{i}", key=f"exec_{i}"):
                sig["status"] = "EXECUTED_MANUAL"
                engine.trade_history.append(sig)
                engine.clear_signal(i)
                st.rerun()
        with col_dismiss:
            if st.button(f"Dismiss #{i}", key=f"dismiss_{i}"):
                engine.clear_signal(i)
                st.rerun()


# ─── OPEN POSITIONS ───
st.markdown("### Open Positions")
positions = state.get("positions", [])

if positions:
    pos_data = []
    total_pl = 0
    for p in positions:
        pl = p.get("profit", 0)
        total_pl += pl
        pos_data.append({
            "Ticket": p.get("ticket", ""),
            "Symbol": p.get("symbol", ""),
            "Type": p.get("type", ""),
            "Volume": p.get("volume", 0),
            "Entry": f"{p.get('price_open', 0):.5f}",
            "Current": f"{p.get('price_current', 0):.5f}",
            "SL": f"{p.get('sl', 0):.5f}",
            "TP": f"{p.get('tp', 0):.5f}",
            "P/L": f"${pl:.2f}",
            "Swap": f"${p.get('swap', 0):.2f}",
        })
    st.dataframe(pd.DataFrame(pos_data), use_container_width=True, hide_index=True)
    color = "green" if total_pl >= 0 else "red"
    st.caption(f"Total positions: {len(positions)} / 30 max | Total P/L: ${total_pl:.2f}")
else:
    st.info("No open positions")


# ─── RECENT DECISIONS ───
st.markdown("### Recent AI Decisions")
decisions = state.get("decision_log", [])

if decisions:
    dec_data = []
    for d in reversed(decisions[-10:]):
        dec_data.append({
            "Time": d.get("timestamp", "")[:19],
            "Symbol": d.get("symbol", ""),
            "Decision": d.get("decision", ""),
            "Confidence": f"{d.get('confidence', 0):.0%}",
            "Risk": d.get("risk_level", ""),
            "Reasoning": d.get("reasoning", "")[:80],
        })
    st.dataframe(pd.DataFrame(dec_data), use_container_width=True, hide_index=True)
else:
    st.info("No decisions yet — start the engine")


# ─── TRADE HISTORY ───
with st.expander("Trade History", expanded=False):
    if history:
        hist_data = []
        for t in reversed(history[-30:]):
            hist_data.append({
                "Time": t.get("timestamp", "")[:19],
                "Symbol": t.get("symbol", ""),
                "Dir": t.get("direction", ""),
                "Lots": t.get("lot_size", 0),
                "Entry": t.get("entry_price", 0),
                "SL": t.get("sl", 0),
                "TP": t.get("tp", 0),
                "Status": t.get("status", ""),
                "Conf.": f"{t.get('confidence', 0):.0%}",
            })
        st.dataframe(pd.DataFrame(hist_data), use_container_width=True, hide_index=True)
    else:
        st.info("No trades yet")


# ─── ERRORS ───
errors = state.get("errors", [])
if errors:
    with st.expander(f"Errors ({len(errors)})"):
        for e in reversed(errors[-5:]):
            st.error(f"{e.get('timestamp', '')[:19]}: {e.get('error', '')}")


# ─── AUTO-REFRESH ───
if state["running"]:
    time.sleep(10)
    st.rerun()
