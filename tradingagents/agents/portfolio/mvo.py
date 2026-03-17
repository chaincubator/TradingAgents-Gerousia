"""Mean-Variance Optimisation portfolio construction.

Accepts individual symbol analysis results and historical Binance price data,
then constructs long/short portfolios for three risk appetites using scipy MVO.

Signal blending:
  Agent BUY  signal → +0.30 annualised return adjustment
  Agent HOLD signal →  0.00
  Agent SELL signal → -0.30
This shifts the expected-return vector so the optimiser tilts toward
agent-favoured symbols without ignoring historical covariance structure.
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from tradingagents.dataflows.binance_utils import fetch_klines
from tradingagents.dataflows.config import get_config

_SIGNAL_ADJ = {"buy": 0.30, "hold": 0.00, "sell": -0.30}
_RISK_FREE = 0.05       # annualised risk-free rate used for Sharpe calculation
_LOOKBACK_DEFAULT = 90  # days of price history for covariance estimation


def _extract_signal(text: str) -> str:
    t = (text or "").upper()
    if "BUY" in t:
        return "buy"
    if "SELL" in t:
        return "sell"
    return "hold"


def _daily_returns(
    symbols: List[str],
    curr_date: str,
    lookback: int,
    cache_dir: str,
) -> Optional[pd.DataFrame]:
    """Fetch daily close-to-close returns for all symbols from Binance 5m klines."""
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=lookback)
    data = {}
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
    Solve the MVO problem for the given risk appetite.

    Position space: long/short — weights ∈ [−1, +1], Σw = 1 (net-long).

    Conservative → global minimum variance
    Moderate     → maximum Sharpe ratio (risk-free = _RISK_FREE)
    Aggressive   → maximum expected return
    """
    n = len(mu)
    w0 = np.ones(n) / n
    bounds = [(-1.0, 1.0)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

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
        symbol_results: {symbol: {"final_trade_decision": str, ...}}
        curr_date:      analysis date in YYYY-MM-DD format
        lookback_days:  days of price history for covariance estimation

    Returns:
        Formatted Markdown report with signal table and three portfolio tables.
    """
    cfg = get_config()
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
    symbols = available

    # Annualised μ and Σ
    mu_hist = returns_df.mean().values * 252
    cov = returns_df.cov().values * 252

    # Blend agent signals into expected returns
    signal_adj = np.array([
        _SIGNAL_ADJ[_extract_signal(
            symbol_results.get(s, {}).get("final_trade_decision", "")
        )]
        for s in symbols
    ])
    mu_adj = mu_hist + signal_adj

    # Optimise for the three risk appetites
    appetites = ("conservative", "moderate", "aggressive")
    portfolios = {}
    for ap in appetites:
        w = _solve(mu_adj, cov, ap)
        weights = dict(zip(symbols, w))
        ret = float(w @ mu_adj)
        vol = float(np.sqrt(max(float(w @ cov @ w), 1e-10)))
        sharpe = (ret - _RISK_FREE) / vol if vol > 0 else 0.0
        portfolios[ap] = {
            "weights": weights,
            "return": ret,
            "volatility": vol,
            "sharpe": sharpe,
        }

    # ── Format report ──────────────────────────────────────────────────────
    icons = {"conservative": "🛡️", "moderate": "⚖️", "aggressive": "🚀"}
    lines = [
        "# Portfolio Construction — Mean-Variance Optimisation\n",
        f"**Symbols:** {', '.join(symbols)}  ",
        f"**Analysis date:** {curr_date}  ",
        f"**Return history:** {lookback_days}-day Binance 5m candles  ",
        "**Position space:** long/short — weights ∈ [−1, +1], Σw = 1\n",
        "---\n",
        "## Agent Signals & Expected Returns\n",
        "| Symbol | Signal | Hist. μ (ann.) | Adj. | Blended μ |",
        "|--------|--------|----------------|------|-----------|",
    ]
    for i, s in enumerate(symbols):
        sig = _extract_signal(
            symbol_results.get(s, {}).get("final_trade_decision", "")
        )
        lines.append(
            f"| {s} | {sig.upper()} | {mu_hist[i]:+.1%} "
            f"| {signal_adj[i]:+.1%} | {mu_adj[i]:+.1%} |"
        )
    lines.append("\n---\n")

    for ap in appetites:
        d = portfolios[ap]
        lines += [
            f"## {icons[ap]} {ap.capitalize()} Portfolio\n",
            f"> Expected Return: **{d['return']:+.1%}** | "
            f"Volatility: **{d['volatility']:.1%}** | "
            f"Sharpe: **{d['sharpe']:.2f}**\n",
            "| Symbol | Weight | Direction |",
            "|--------|--------|-----------|",
        ]
        for sym, wt in sorted(d["weights"].items(), key=lambda x: -abs(x[1])):
            direction = "LONG" if wt > 0.01 else ("SHORT" if wt < -0.01 else "FLAT")
            lines.append(f"| {sym} | {wt:+.1%} | {direction} |")
        lines.append("")

    return "\n".join(lines)
