"""Mean-Variance Optimisation portfolio construction.

Accepts individual symbol analysis results (including trader TP/SL/validity)
and historical Binance price data, then constructs long/short portfolios for
three risk appetites using scipy MVO.

Constraints:
  Net leverage  = 100%  (Σw = 1)
  Gross leverage ≤ 200% (Σ|w| ≤ 2)

Signal blending:
  Agent BUY  signal → +0.30 annualised return adjustment
  Agent HOLD signal →  0.00
  Agent SELL signal → -0.30
"""

import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from tradingagents.dataflows.binance_utils import fetch_klines
from tradingagents.dataflows.config import get_config

_SIGNAL_ADJ   = {"buy": 0.30, "hold": 0.00, "sell": -0.30}
_RISK_FREE    = 0.05
_LOOKBACK_DEFAULT = 90
_MAX_GROSS    = 2.0   # 200% gross leverage cap


def _extract_signal(text: str) -> str:
    t = (text or "").upper()
    if "BUY"  in t: return "buy"
    if "SELL" in t: return "sell"
    return "hold"


def _parse_tp_sl(text: str) -> Tuple[Optional[float], Optional[float], str]:
    """Extract (take_profit, stop_loss, validity) from a trader recommendation."""
    tp, sl, validity = None, None, "unspecified"
    tp_m = re.search(r'TAKE\s*PROFIT\s*[:\-]\s*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    sl_m = re.search(r'STOP\s*LOSS\s*[:\-]\s*\$?([\d,]+\.?\d*)',   text, re.IGNORECASE)
    v_m  = re.search(r'VALIDITY\s*[:\-]\s*(.+?)(?:\n|$)',           text, re.IGNORECASE)
    if tp_m: tp       = float(tp_m.group(1).replace(',', ''))
    if sl_m: sl       = float(sl_m.group(1).replace(',', ''))
    if v_m:  validity = v_m.group(1).strip().rstrip('.')
    return tp, sl, validity


def _daily_returns(
    symbols: List[str], curr_date: str, lookback: int, cache_dir: str,
) -> Optional[pd.DataFrame]:
    end   = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=lookback)
    data  = {}
    for sym in symbols:
        df = fetch_klines(sym, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
        if df is None or df.empty:
            continue
        df["date"] = df["open_time"].dt.date
        data[sym.upper()] = df.groupby("date")["close"].last().pct_change().dropna()
    if not data:
        return None
    combined = pd.DataFrame(data).dropna()
    return combined if len(combined) >= 10 else None


def _solve(mu: np.ndarray, cov: np.ndarray, appetite: str) -> np.ndarray:
    """
    Solve MVO with:
      - Net leverage  = 100%  (Σw = 1)
      - Gross leverage ≤ 200% (Σ|w| ≤ 2)
      - Individual weight bounds: [-1, +1]
    """
    n  = len(mu)
    w0 = np.ones(n) / n
    bounds = [(-1.0, 1.0)] * n
    constraints = [
        {"type": "eq",   "fun": lambda w: np.sum(w) - 1.0},
        {"type": "ineq", "fun": lambda w: _MAX_GROSS - np.sum(np.abs(w))},
    ]

    if appetite == "conservative":
        obj = lambda w: float(w @ cov @ w)
    elif appetite == "moderate":
        def obj(w):
            r = float(w @ mu) - _RISK_FREE
            v = float(np.sqrt(max(float(w @ cov @ w), 1e-10)))
            return -r / v
    else:  # aggressive
        obj = lambda w: -float(w @ mu)

    res = minimize(
        obj, w0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"ftol": 1e-9, "maxiter": 1000},
    )
    return res.x if res.success else w0


def run_portfolio_mvo(
    symbol_results: Dict[str, Dict],
    curr_date: str,
    lookback_days: int = _LOOKBACK_DEFAULT,
) -> str:
    """
    Construct long/short MVO portfolios for three risk appetites.

    Args:
        symbol_results: {symbol: {
                           "final_trade_decision": str,
                           "trader_investment_plan": str  (optional, for TP/SL)
                         }}
        curr_date:      analysis date in YYYY-MM-DD format
        lookback_days:  days of price history for covariance estimation

    Returns:
        Markdown report — portfolio allocation tables first, then supporting details.
    """
    cfg       = get_config()
    cache_dir = os.path.join(cfg.get("data_cache_dir", "./data"), "binance_cache")

    symbols = [s.upper() for s in symbol_results.keys()]
    if len(symbols) < 2:
        return "Portfolio optimisation requires at least 2 symbols."

    returns_df = _daily_returns(symbols, curr_date, lookback_days, cache_dir)
    if returns_df is None:
        return "Insufficient historical data to construct a portfolio."

    available = [s for s in symbols if s in returns_df.columns]
    if len(available) < 2:
        return "Insufficient overlapping price history for portfolio optimisation."

    returns_df = returns_df[available]
    symbols    = available

    # ── Annualised μ and Σ ───────────────────────────────────────────────────
    mu_hist    = returns_df.mean().values * 252
    cov        = returns_df.cov().values  * 252

    # ── Parse trader TP/SL/duration per symbol ───────────────────────────────
    trader_data = {}
    for s in symbols:
        plan = symbol_results.get(s, {}).get("trader_investment_plan", "")
        tp, sl, validity = _parse_tp_sl(plan)
        trader_data[s] = {"tp": tp, "sl": sl, "validity": validity}

    # ── Signal + TP/SL blending into expected returns ────────────────────────
    signal_adj = np.array([
        _SIGNAL_ADJ[_extract_signal(
            symbol_results.get(s, {}).get("final_trade_decision", "")
        )]
        for s in symbols
    ])
    mu_adj = mu_hist + signal_adj

    # ── Optimise ─────────────────────────────────────────────────────────────
    appetites  = ("conservative", "moderate", "aggressive")
    portfolios = {}
    for ap in appetites:
        w      = _solve(mu_adj, cov, ap)
        weights = dict(zip(symbols, w))
        ret    = float(w @ mu_adj)
        vol    = float(np.sqrt(max(float(w @ cov @ w), 1e-10)))
        sharpe = (ret - _RISK_FREE) / vol if vol > 0 else 0.0
        gross  = float(np.sum(np.abs(w)))
        portfolios[ap] = {"weights": weights, "return": ret,
                          "volatility": vol, "sharpe": sharpe, "gross": gross}

    # ── Format report (portfolio allocation at the top) ──────────────────────
    icons = {"conservative": "🛡️", "moderate": "⚖️", "aggressive": "🚀"}

    lines = [
        "# Portfolio Recommendation — Mean-Variance Optimisation\n",
        f"**Symbols:** {', '.join(symbols)}  |  **Date:** {curr_date}  ",
        f"**Constraints:** Net leverage = 100% · Gross leverage ≤ 200%  ",
        f"**History:** {lookback_days}-day Binance returns\n",
        "---\n",
    ]

    # ── 1. Portfolio allocation tables (prominent, at top) ───────────────────
    for ap in appetites:
        d = portfolios[ap]
        lines += [
            f"## {icons[ap]} {ap.capitalize()} Portfolio\n",
            f"> Exp. Return: **{d['return']:+.1%}**  |  "
            f"Volatility: **{d['volatility']:.1%}**  |  "
            f"Sharpe: **{d['sharpe']:.2f}**  |  "
            f"Gross leverage: **{d['gross']:.0%}**\n",
            "| Symbol | Weight | Direction | Take Profit | Stop Loss | Validity |",
            "|--------|--------|-----------|-------------|-----------|----------|",
        ]
        for sym, wt in sorted(d["weights"].items(), key=lambda x: -abs(x[1])):
            direction = "LONG" if wt > 0.01 else ("SHORT" if wt < -0.01 else "FLAT")
            td   = trader_data.get(sym, {})
            tp_s = f"${td['tp']:,.2f}" if td.get("tp") else "—"
            sl_s = f"${td['sl']:,.2f}" if td.get("sl") else "—"
            val  = td.get("validity", "—")
            lines.append(f"| {sym} | {wt:+.1%} | {direction} | {tp_s} | {sl_s} | {val} |")
        lines.append("")

    # ── 2. Trader recommendations detail ─────────────────────────────────────
    lines += [
        "---\n",
        "## Trader Recommendations\n",
        "| Symbol | Signal | Take Profit | Stop Loss | Validity |",
        "|--------|--------|-------------|-----------|----------|",
    ]
    for s in symbols:
        sig = _extract_signal(symbol_results.get(s, {}).get("final_trade_decision", ""))
        td  = trader_data.get(s, {})
        tp_s = f"${td['tp']:,.2f}" if td.get("tp") else "—"
        sl_s = f"${td['sl']:,.2f}" if td.get("sl") else "—"
        val  = td.get("validity", "—")
        lines.append(f"| {s} | {sig.upper()} | {tp_s} | {sl_s} | {val} |")

    # ── 3. Signal & return detail ─────────────────────────────────────────────
    lines += [
        "\n---\n",
        "## Agent Signals & Expected Returns\n",
        "| Symbol | Signal | Hist. μ (ann.) | Adj. | Blended μ |",
        "|--------|--------|----------------|------|-----------|",
    ]
    for i, s in enumerate(symbols):
        sig = _extract_signal(symbol_results.get(s, {}).get("final_trade_decision", ""))
        lines.append(
            f"| {s} | {sig.upper()} | {mu_hist[i]:+.1%} "
            f"| {signal_adj[i]:+.1%} | {mu_adj[i]:+.1%} |"
        )

    return "\n".join(lines)
