"""Federal Reserve Bank of St. Louis — FRED database utilities.

Fetches macro-economic indicators across four categories:
  Growth    — GDP, industrial production, consumer spending / sentiment
  Inflation — CPI, PCE, PPI, breakeven rates, real yields
  Labor     — unemployment, payrolls, job openings, wages
  Liquidity — money supply, Fed balance sheet, rates, credit spreads

API key: set FRED_API environment variable.
Docs   : https://fred.stlouisfed.org/docs/api/fred/
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

_BASE   = "https://api.stlouisfed.org/fred"
_TIMEOUT = 15


# ── Series catalogue ──────────────────────────────────────────────────────────

_SERIES: Dict[str, Dict] = {
    # ── Growth ────────────────────────────────────────────────────────────────
    "A191RL1Q225SBEA": {
        "name": "Real GDP Growth (QoQ, %)",
        "category": "growth",
        "unit": "%",
        "interpret": "positive = expansion; negative = contraction",
    },
    "INDPRO": {
        "name": "Industrial Production Index",
        "category": "growth",
        "unit": "index",
        "interpret": "rising = expanding output; falling = contraction",
    },
    "PCE": {
        "name": "Personal Consumption Expenditures ($B)",
        "category": "growth",
        "unit": "bn USD",
        "interpret": "YoY growth drives ~70% of US GDP",
    },
    "UMCSENT": {
        "name": "U. of Michigan Consumer Sentiment",
        "category": "growth",
        "unit": "index",
        "interpret": ">90 = strong; <70 = weak; leads spending",
    },
    "RSAFS": {
        "name": "Retail Sales (ex-autos, $M)",
        "category": "growth",
        "unit": "mn USD",
        "interpret": "YoY trend indicates consumer demand health",
    },
    # ── Inflation ─────────────────────────────────────────────────────────────
    "CPIAUCSL": {
        "name": "CPI All Items (headline, YoY %)",
        "category": "inflation",
        "unit": "%",
        "interpret": "Fed watches closely; >3% = hot; <2% = below target",
    },
    "CPILFESL": {
        "name": "Core CPI (ex-food & energy, YoY %)",
        "category": "inflation",
        "unit": "%",
        "interpret": "Fed target ~2%; most persistent component",
    },
    "PCEPI": {
        "name": "PCE Price Index (YoY %)",
        "category": "inflation",
        "unit": "%",
        "interpret": "Fed's preferred broad inflation gauge; 2% = target",
    },
    "PCEPILFE": {
        "name": "Core PCE (ex-food & energy, YoY %)",
        "category": "inflation",
        "unit": "%",
        "interpret": "Fed's primary policy target; >2.5% = rate-hold pressure",
    },
    "T5YIE": {
        "name": "5-Year Breakeven Inflation Rate (%)",
        "category": "inflation",
        "unit": "%",
        "interpret": "market-implied 5Y avg inflation; rising = expectations unanchoring",
    },
    "T10YIE": {
        "name": "10-Year Breakeven Inflation Rate (%)",
        "category": "inflation",
        "unit": "%",
        "interpret": "long-run inflation expectations; >2.5% = concern",
    },
    "DFII10": {
        "name": "10-Year TIPS Real Yield (%)",
        "category": "inflation",
        "unit": "%",
        "interpret": "real cost of money; rising real yields = headwind for risk assets",
    },
    "PPIFIS": {
        "name": "PPI Final Demand (YoY %)",
        "category": "inflation",
        "unit": "%",
        "interpret": "upstream / producer prices; leads CPI by 2-3 months",
    },

    # ── Labor ─────────────────────────────────────────────────────────────────
    "UNRATE": {
        "name": "Unemployment Rate (%)",
        "category": "labor",
        "unit": "%",
        "interpret": "rising = labor softening; <4% = full employment",
    },
    "PAYEMS": {
        "name": "Nonfarm Payrolls (thousands)",
        "category": "labor",
        "unit": "k jobs",
        "interpret": "MoM change; +150k = healthy; <0 = contraction",
    },
    "ICSA": {
        "name": "Initial Jobless Claims (weekly)",
        "category": "labor",
        "unit": "claims",
        "interpret": "rising = layoffs accelerating; <250k = healthy",
    },
    "JOLTSJOL": {
        "name": "JOLTS Job Openings (thousands)",
        "category": "labor",
        "unit": "k openings",
        "interpret": "openings > unemployed = tight labor market",
    },
    "CES0500000003": {
        "name": "Avg Hourly Earnings ($/hr)",
        "category": "labor",
        "unit": "$/hr",
        "interpret": "YoY growth >4% = wage-push inflation risk",
    },
    "U6RATE": {
        "name": "U-6 Underemployment Rate (%)",
        "category": "labor",
        "unit": "%",
        "interpret": "broadest measure; includes part-time / discouraged",
    },

    # ── Liquidity ─────────────────────────────────────────────────────────────
    "M2SL": {
        "name": "M2 Money Supply ($B)",
        "category": "liquidity",
        "unit": "bn USD",
        "interpret": "YoY growth >7% = easy money; contraction = tightening",
    },
    "WALCL": {
        "name": "Fed Balance Sheet Total Assets ($M)",
        "category": "liquidity",
        "unit": "mn USD",
        "interpret": "expanding = QE / easy; shrinking = QT / tight",
    },
    "DFF": {
        "name": "Effective Federal Funds Rate (%)",
        "category": "liquidity",
        "unit": "%",
        "interpret": "current benchmark rate; higher = tighter conditions",
    },
    "T10Y2Y": {
        "name": "10Y−2Y Treasury Spread (%)",
        "category": "liquidity",
        "unit": "%",
        "interpret": "positive = normal; negative = inverted (recession risk)",
    },
    "T10YFF": {
        "name": "10Y Treasury minus Fed Funds (%)",
        "category": "liquidity",
        "unit": "%",
        "interpret": "measures term premium; negative = financial stress",
    },
    "BAMLH0A0HYM2": {
        "name": "US High-Yield OAS (credit spread, %)",
        "category": "liquidity",
        "unit": "%",
        "interpret": "<3.5% = risk-on; >6% = stress / recession fears",
    },
    "DEXUSEU": {
        "name": "USD/EUR Exchange Rate",
        "category": "liquidity",
        "unit": "USD per EUR",
        "interpret": "rising = weaker USD; falling = stronger USD (tighter global)",
    },
}

_CATEGORY_ORDER = ["growth", "inflation", "labor", "liquidity"]
_CATEGORY_LABELS = {
    "growth":    "Growth",
    "inflation": "Inflation",
    "labor":     "Labor Market",
    "liquidity": "Liquidity & Financial Conditions",
}


# ── API helpers ───────────────────────────────────────────────────────────────

def _api_key() -> Optional[str]:
    return os.getenv("FRED_API")


def _fetch_series(series_id: str, limit: int = 8) -> Optional[List[dict]]:
    """Fetch the last `limit` observations for a FRED series."""
    key = _api_key()
    if not key:
        return None
    try:
        r = requests.get(
            f"{_BASE}/series/observations",
            params={
                "series_id":  series_id,
                "api_key":    key,
                "file_type":  "json",
                "limit":      limit,
                "sort_order": "desc",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
        # Filter out missing values (".")
        return [o for o in obs if o.get("value") not in (".", None, "")]
    except Exception as e:
        print(f"[fred_utils] {series_id}: {e}")
        return None


def _pct_change(new: float, old: float) -> Optional[float]:
    if old == 0:
        return None
    return round((new - old) / abs(old) * 100, 2)


def _trend_arrow(change: Optional[float]) -> str:
    if change is None:
        return "→"
    if change > 0.5:
        return "▲"
    if change < -0.5:
        return "▼"
    return "→"


# ── Main public function ──────────────────────────────────────────────────────

def get_fred_macro_snapshot(
    curr_date: str = "",
) -> str:
    """
    Fetch the latest observations for Growth, Labor, and Liquidity indicators
    from the FRED database and return a formatted Markdown report.

    The API key must be set in the FRED_API environment variable.

    Returns:
        Formatted Markdown report with four sections:
        Growth | Inflation | Labor Market | Liquidity & Financial Conditions
    """
    key = _api_key()
    if not key:
        return (
            "FRED_API environment variable is not set. "
            "Set it to your FRED API key to enable macro indicator data."
        )

    # ── Fetch all series ──────────────────────────────────────────────────────
    results: Dict[str, dict] = {}
    for sid, meta in _SERIES.items():
        obs = _fetch_series(sid, limit=6)
        if not obs:
            continue
        try:
            latest_val   = float(obs[0]["value"])
            latest_date  = obs[0]["date"]
            prev_val     = float(obs[1]["value"]) if len(obs) > 1 else latest_val
            older_val    = float(obs[-1]["value"]) if len(obs) > 1 else latest_val

            abs_change   = round(latest_val - prev_val, 4)
            pct_chg_mom  = _pct_change(latest_val, prev_val)
            pct_chg_yoy  = _pct_change(latest_val, older_val)  # approx YoY
            arrow        = _trend_arrow(pct_chg_mom)

            results[sid] = {
                **meta,
                "latest":       latest_val,
                "latest_date":  latest_date,
                "prev":         prev_val,
                "abs_change":   abs_change,
                "pct_chg_mom":  pct_chg_mom,
                "pct_chg_yoy":  pct_chg_yoy,
                "arrow":        arrow,
            }
        except (ValueError, IndexError):
            continue

    if not results:
        return "FRED data could not be fetched. The API may be temporarily unavailable."

    # ── Format report ─────────────────────────────────────────────────────────
    lines = [
        "## FRED Macro Snapshot — Growth | Labor | Liquidity\n",
        f"*Source: Federal Reserve Bank of St. Louis (FRED)*  |  "
        f"*Retrieved: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*\n",
    ]

    for cat in _CATEGORY_ORDER:
        cat_results = {sid: r for sid, r in results.items() if r["category"] == cat}
        if not cat_results:
            continue

        lines.append(f"\n### {_CATEGORY_LABELS[cat]}\n")
        lines.append("| Indicator | Latest | Date | Change | Trend | Interpretation |")
        lines.append("|-----------|--------|------|--------|-------|----------------|")

        for sid, r in cat_results.items():
            val_str    = f"{r['latest']:,.2f} {r['unit']}"
            chg_str    = (
                f"{r['pct_chg_mom']:+.2f}%" if r["pct_chg_mom"] is not None
                else f"{r['abs_change']:+.4f}"
            )
            lines.append(
                f"| **{r['name']}** | {val_str} | {r['latest_date']} "
                f"| {chg_str} | {r['arrow']} | {r['interpret']} |"
            )

    # ── Synthesis summary ─────────────────────────────────────────────────────
    lines.append("\n---\n")
    lines.append("### Macro Regime Summary\n")

    # Growth signal
    gdp_r         = results.get("A191RL1Q225SBEA")
    growth_signal = "Expansion" if (gdp_r and gdp_r["latest"] > 0) else "Contraction"

    # Inflation signal
    cpi_r      = results.get("CPIAUCSL")
    core_cpi_r = results.get("CPILFESL")
    core_pce_r = results.get("PCEPILFE")
    be5y_r     = results.get("T5YIE")
    real_r     = results.get("DFII10")
    cpi_hot    = cpi_r      and cpi_r["latest"]      > 3.0
    core_hot   = core_cpi_r and core_cpi_r["latest"] > 2.5
    pce_hot    = core_pce_r and core_pce_r["latest"] > 2.5
    be_rising  = be5y_r     and be5y_r["latest"]     > 2.5
    real_high  = real_r     and real_r["latest"]     > 1.5
    hot_signals = sum([bool(cpi_hot), bool(core_hot), bool(pce_hot), bool(be_rising)])
    if hot_signals >= 3:
        inflation_signal = "Hot (multiple gauges above target)"
    elif hot_signals >= 1:
        inflation_signal = "Elevated (some gauges above target)"
    else:
        inflation_signal = "Cooling / On-Target"
    if real_high:
        inflation_signal += " | Real yields elevated → risk-asset headwind"

    # Labor signal
    unrate_r     = results.get("UNRATE")
    labor_signal = "Tight" if (unrate_r and unrate_r["latest"] < 4.5) else "Softening"

    # Liquidity signal
    t10y2y           = results.get("T10Y2Y")
    hy_r             = results.get("BAMLH0A0HYM2")
    spread_inverted  = t10y2y and t10y2y["latest"] < 0
    hy_stressed      = hy_r   and hy_r["latest"]   > 5.0
    liquidity_signal = "Tight / Risk-Off" if (spread_inverted or hy_stressed) else "Accommodative / Risk-On"

    lines += [
        "| Dimension     | Signal |",
        "|---------------|--------|",
        f"| **Growth**    | {growth_signal} |",
        f"| **Inflation** | {inflation_signal} |",
        f"| **Labor**     | {labor_signal} |",
        f"| **Liquidity** | {liquidity_signal} |",
        "",
        "*Use these macro regime signals to contextualise price-action and sentiment data.*",
    ]

    return "\n".join(lines)
