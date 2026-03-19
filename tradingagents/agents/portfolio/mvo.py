"""Mean-Variance Optimisation portfolio construction — enhanced edition.

Changes vs. v1:
  • Expected-return estimates: the trader agent now outputs EXPECTED RETURN
    and CONFIDENCE for each symbol. These replace the flat ±0.30 signal
    adjustment, giving agent-specific return estimates that are scaled by
    the reported confidence and by the agent's historical accuracy score.
  • Historical accuracy weighting: each symbol's weight is loaded from
    AnalysisCache (average of last 5 scored recommendations, mapped to
    [0.5, 1.5]).  Accurate agents get up to 1.5× weight; inaccurate ones
    as low as 0.5×.
  • Fast covariance: the Σ matrix is estimated from 7 days of 5-minute
    Binance returns (≈ 2 016 bars per symbol) rather than 90 days of daily
    returns.  This gives a risk estimate tuned to the short holding periods
    the traders target.  Annualisation: × 365 × 288 (24/7 crypto, 5-min).
    Falls back to 90-day daily covariance when 5-min data is unavailable.

Constraints (unchanged):
  Net leverage  = 100%  (Σw = 1)
  Gross leverage ≤ 200% (Σ|w| ≤ 2)
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

# ── Constants ─────────────────────────────────────────────────────────────────
_RISK_FREE       = 0.05
_MAX_GROSS       = 2.0
_FAST_DAYS       = 7         # trailing days for 5-min covariance
_FALLBACK_DAYS   = 90        # fallback lookback when 5-min unavailable
_BARS_PER_YEAR   = 365 * 288 # 5-min bars per year for 24/7 crypto (annualisation)
_MIN_BARS        = 100       # minimum bars to use 5-min covariance
_SIGNAL_ADJ      = {"buy": 0.30, "hold": 0.00, "sell": -0.30}


# ── Signal & structured output parsing ───────────────────────────────────────

def _extract_signal(text: str) -> str:
    t = (text or "").upper()
    if "BUY"  in t: return "buy"
    if "SELL" in t: return "sell"
    return "hold"


def _parse_tp_sl(text: str) -> Tuple[Optional[float], Optional[float], str]:
    tp, sl, validity = None, None, "unspecified"
    tp_m = re.search(r'TAKE\s*PROFIT\s*[:\-]\s*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    sl_m = re.search(r'STOP\s*LOSS\s*[:\-]\s*\$?([\d,]+\.?\d*)',   text, re.IGNORECASE)
    v_m  = re.search(r'VALIDITY\s*[:\-]\s*(.+?)(?:\n|$)',           text, re.IGNORECASE)
    if tp_m: tp       = float(tp_m.group(1).replace(',', ''))
    if sl_m: sl       = float(sl_m.group(1).replace(',', ''))
    if v_m:  validity = v_m.group(1).strip().rstrip('.')
    return tp, sl, validity


def _parse_expected_return(text: str) -> Optional[float]:
    """
    Extract expected return from 'EXPECTED RETURN: +12% over 7 days'.
    Returns the raw percentage as a decimal (e.g. +0.12), NOT annualised.
    Annualisation is done in the caller using the parsed horizon.
    """
    m = re.search(
        r'EXPECTED\s*RETURN\s*[:\-]\s*([+-]?\d+(?:\.\d+)?)\s*%',
        text, re.IGNORECASE
    )
    return float(m.group(1)) / 100.0 if m else None


def _parse_confidence(text: str) -> float:
    """Extract CONFIDENCE field (0–100%) and return as fraction 0–1."""
    m = re.search(r'CONFIDENCE\s*[:\-]\s*(\d+(?:\.\d+)?)\s*%', text, re.IGNORECASE)
    return min(1.0, float(m.group(1)) / 100.0) if m else 0.5


def _parse_horizon_days(text: str) -> int:
    """Extract TIME HORIZON or VALIDITY duration in days."""
    for pattern in [
        r'TIME\s*HORIZON\s*[:\-]\s*(.+?)(?:\n|$)',
        r'VALIDITY\s*[:\-]\s*(.+?)(?:\n|$)',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            s = m.group(1).strip().lower()
            dm = re.search(r'(\d+)\s*day',   s)
            wm = re.search(r'(\d+)\s*week',  s)
            mm = re.search(r'(\d+)\s*month', s)
            if dm: return int(dm.group(1))
            if wm: return int(wm.group(1)) * 7
            if mm: return int(mm.group(1)) * 30
    return 7  # default: 1 week


# ── Historical accuracy weighting ────────────────────────────────────────────

def _load_accuracy_weight(symbol: str, data_cache_dir: str) -> float:
    """
    Return a weight ∈ [0.5, 1.5] reflecting the agent's historical accuracy
    for this symbol, derived from the last 5 scored AnalysisCache recommendations.

    Mapping:  avg_score ∈ [-1, +1]  →  weight = 0.5 + 0.5 × (avg_score + 1)
      avg_score = +1 (always right)  →  weight = 1.5
      avg_score =  0 (coin-flip)     →  weight = 1.0
      avg_score = -1 (always wrong)  →  weight = 0.5
    """
    try:
        from tradingagents.dataflows.analysis_cache import AnalysisCache
        cache = AnalysisCache(symbol, data_cache_dir)
        scored = [
            r for r in cache.state.get("recommendations", [])
            if r.get("score") is not None
        ]
        if not scored:
            return 1.0
        recent = scored[-5:]  # last 5 recommendations
        avg_score = sum(r["score"] for r in recent) / len(recent)
        return round(0.5 + 0.5 * (avg_score + 1), 3)
    except Exception:
        return 1.0


# ── Return data helpers ───────────────────────────────────────────────────────

def _fast_5min_returns(
    symbols: List[str], curr_date: str, cache_dir: str,
) -> Optional[pd.DataFrame]:
    """
    Fetch 7 days of 5-minute returns for fast covariance estimation.
    Returns a DataFrame with one column per symbol; None if insufficient data.
    """
    end   = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=_FAST_DAYS)
    data  = {}
    for sym in symbols:
        df = fetch_klines(sym, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
        if df is None or df.empty:
            continue
        data[sym.upper()] = df["close"].pct_change().dropna()
    if not data:
        return None
    combined = pd.DataFrame(data).dropna()
    return combined if len(combined) >= _MIN_BARS else None


def _daily_returns_fallback(
    symbols: List[str], curr_date: str, lookback: int, cache_dir: str,
) -> Optional[pd.DataFrame]:
    """90-day daily returns fallback when 5-min data is unavailable."""
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


# ── MVO solver ────────────────────────────────────────────────────────────────

def _solve(mu: np.ndarray, cov: np.ndarray, appetite: str) -> np.ndarray:
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
    else:
        obj = lambda w: -float(w @ mu)
    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=constraints,
                   options={"ftol": 1e-9, "maxiter": 1000})
    return res.x if res.success else w0


# ── Main entry point ──────────────────────────────────────────────────────────

def run_portfolio_mvo(
    symbol_results: Dict[str, Dict],
    curr_date: str,
    lookback_days: int = _FALLBACK_DAYS,
) -> str:
    """
    Construct long/short MVO portfolios for three risk appetites.

    Expected returns per symbol are constructed by:
      1. Parsing the trader's EXPECTED RETURN + CONFIDENCE fields
      2. Annualising the raw return using the stated TIME HORIZON
      3. Scaling by the symbol's historical accuracy weight from AnalysisCache
      4. Falling back to a flat directional signal (±0.30) scaled by accuracy
         if the trader did not provide a structured expected return

    Covariance is estimated from 7-day 5-minute returns (fast, short-horizon).
    Falls back to 90-day daily returns if 5-min data is unavailable.
    """
    cfg           = get_config()
    binance_cache = os.path.join(cfg.get("data_cache_dir", "./data"), "binance_cache")
    data_cache    = cfg.get("data_cache_dir", "./data")

    symbols = [s.upper() for s in symbol_results.keys()]
    if len(symbols) < 2:
        return "Portfolio optimisation requires at least 2 symbols."

    # ── Covariance: try 5-min fast, fall back to daily ────────────────────────
    fast_df = _fast_5min_returns(symbols, curr_date, binance_cache)
    if fast_df is not None:
        available   = [s for s in symbols if s in fast_df.columns]
        if len(available) < 2:
            fast_df = None

    if fast_df is not None:
        returns_df    = fast_df[available]
        symbols       = available
        annualize_by  = _BARS_PER_YEAR          # 5-min bars per year
        cov_label     = f"7d × 5min ({len(returns_df):,} bars)"
    else:
        daily_df = _daily_returns_fallback(symbols, curr_date, lookback_days, binance_cache)
        if daily_df is None:
            return "Insufficient historical data to construct a portfolio."
        available  = [s for s in symbols if s in daily_df.columns]
        if len(available) < 2:
            return "Insufficient overlapping price history for portfolio optimisation."
        returns_df   = daily_df[available]
        symbols      = available
        annualize_by = 252
        cov_label    = f"{lookback_days}d daily"

    mu_hist = returns_df.mean().values  * annualize_by
    cov     = returns_df.cov().values   * annualize_by

    # ── Per-symbol: parse structured outputs + load accuracy weights ──────────
    trader_data   = {}
    accuracy_info = {}
    mu_components = []   # rows: [signal, agent_er, confidence, horizon, accuracy, blended]

    signal_adj = np.zeros(len(symbols))

    for i, s in enumerate(symbols):
        plan   = symbol_results.get(s, {}).get("trader_investment_plan", "")
        final  = symbol_results.get(s, {}).get("final_trade_decision", "")

        tp, sl, validity = _parse_tp_sl(plan)
        agent_er    = _parse_expected_return(plan)   # raw %, e.g. +0.12
        confidence  = _parse_confidence(plan)        # 0–1
        horizon_d   = _parse_horizon_days(plan)      # days
        accuracy    = _load_accuracy_weight(s, data_cache)
        signal      = _extract_signal(final)

        trader_data[s]   = {"tp": tp, "sl": sl, "validity": validity,
                            "confidence": confidence, "horizon_days": horizon_d}
        accuracy_info[s] = accuracy

        if agent_er is not None:
            # Annualise trader's expected return over the stated horizon
            ann_factor = 365.0 / max(horizon_d, 1)
            agent_mu   = agent_er * ann_factor
            # Blend: confidence weights the agent estimate vs the historical mean
            blended_adj = agent_mu * confidence * accuracy
        else:
            # No structured estimate — fall back to directional signal
            blended_adj = _SIGNAL_ADJ[signal] * accuracy

        signal_adj[i] = blended_adj
        mu_components.append({
            "signal":     signal,
            "agent_er":   agent_er,
            "confidence": confidence,
            "horizon_d":  horizon_d,
            "accuracy":   accuracy,
            "adj":        blended_adj,
        })

    mu_adj = mu_hist + signal_adj

    # ── Optimise for three risk appetites ─────────────────────────────────────
    appetites  = ("conservative", "moderate", "aggressive")
    portfolios = {}
    for ap in appetites:
        w      = _solve(mu_adj, cov, ap)
        wts    = dict(zip(symbols, w))
        ret    = float(w @ mu_adj)
        vol    = float(np.sqrt(max(float(w @ cov @ w), 1e-10)))
        sharpe = (ret - _RISK_FREE) / vol if vol > 0 else 0.0
        gross  = float(np.sum(np.abs(w)))
        portfolios[ap] = {"weights": wts, "return": ret,
                          "volatility": vol, "sharpe": sharpe, "gross": gross}

    # ── Format report ─────────────────────────────────────────────────────────
    icons = {"conservative": "🛡️", "moderate": "⚖️", "aggressive": "🚀"}

    lines = [
        "# Portfolio Recommendation — Mean-Variance Optimisation\n",
        f"**Symbols:** {', '.join(symbols)}  |  **Date:** {curr_date}  ",
        f"**Constraints:** Net leverage = 100% · Gross leverage ≤ 200%  ",
        f"**Covariance:** {cov_label}  |  **Annualisation:** ×{annualize_by:,}\n",
        "---\n",
    ]

    # 1. Portfolio allocation tables (with confidence + accuracy columns)
    for ap in appetites:
        d = portfolios[ap]
        lines += [
            f"## {icons[ap]} {ap.capitalize()} Portfolio\n",
            f"> Exp. Return: **{d['return']:+.1%}**  |  "
            f"Vol: **{d['volatility']:.1%}**  |  "
            f"Sharpe: **{d['sharpe']:.2f}**  |  "
            f"Gross: **{d['gross']:.0%}**\n",
            "| Symbol | Weight | Dir | Take Profit | Stop Loss | Validity | Confidence | Accuracy |",
            "|--------|--------|-----|-------------|-----------|----------|------------|----------|",
        ]
        for sym, wt in sorted(d["weights"].items(), key=lambda x: -abs(x[1])):
            direction = "LONG" if wt > 0.01 else ("SHORT" if wt < -0.01 else "FLAT")
            td  = trader_data.get(sym, {})
            acc = accuracy_info.get(sym, 1.0)
            tp_s  = f"${td['tp']:,.2f}"     if td.get("tp")  else "—"
            sl_s  = f"${td['sl']:,.2f}"     if td.get("sl")  else "—"
            val   = td.get("validity", "—")
            conf  = f"{td.get('confidence', 0.5):.0%}"
            acc_s = f"{acc:.2f}×"
            lines.append(
                f"| {sym} | {wt:+.1%} | {direction} | {tp_s} | {sl_s} | {val} | {conf} | {acc_s} |"
            )
        lines.append("")

    # 2. Agent structured recommendations
    lines += [
        "---\n",
        "## Agent Structured Recommendations\n",
        "| Symbol | Signal | Expected Return | Horizon | Confidence | Accuracy | Blended μ (ann.) |",
        "|--------|--------|-----------------|---------|------------|----------|------------------|",
    ]
    for i, s in enumerate(symbols):
        mc    = mu_components[i]
        sig   = mc["signal"].upper()
        er_s  = f"{mc['agent_er']:+.1%}" if mc["agent_er"] is not None else "—"
        h_s   = f"{mc['horizon_d']}d"
        conf  = f"{mc['confidence']:.0%}"
        acc   = f"{mc['accuracy']:.2f}×"
        adj   = f"{mc['adj']:+.1%}"
        lines.append(f"| {s} | {sig} | {er_s} | {h_s} | {conf} | {acc} | {adj} |")

    # 3. Historical μ vs blended μ comparison
    lines += [
        "\n---\n",
        "## Return Decomposition (annualised)\n",
        "| Symbol | Hist. μ | Signal adj. | Blended μ |",
        "|--------|---------|-------------|-----------|",
    ]
    for i, s in enumerate(symbols):
        lines.append(
            f"| {s} | {mu_hist[i]:+.1%} | {signal_adj[i]:+.1%} | {mu_adj[i]:+.1%} |"
        )

    return "\n".join(lines)
