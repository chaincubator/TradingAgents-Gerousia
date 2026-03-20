"""Polymarket prediction-market data utilities — v3.

Enhancements over v2:
  • Tighter time bucketing: intraday (<6h), overnight (6-24h), short (1-3d),
    weekly (3-7d), medium (7-30d) — markets prioritised by urgency tier.
  • Probability velocity: per-market YES-prob delta vs. last run (signals.jsonl).
    Fast-moving markets (>=3%/h) are flagged as highest-priority signals.
  • OB conviction score: bid-ask spread as fraction of mid-price used as a
    weight multiplier that down-grades illiquid or disagreement-heavy markets.
  • Urgency x conviction weighted aggregate: effective_weight =
    volume x (1/hours_to_expiry) x conviction, so intraday markets dominate.
  • Multi-horizon probability ladder: separate implied price ranges (P25-P75,
    P10-P90) per time bucket from price-level markets.
  • Price level magnets: cluster market price-strike levels into ~1% bins;
    bins with multiple references are crowd support/resistance zones.
  • Consensus breadth score: fraction of relevant markets that are non-neutral
    and directionally aligned — distinguishes broad consensus from outliers.
  • Lognormal implied volatility: annualised sigma fitted per bucket from the
    probability surface (requires scipy; silently skipped if absent).
  • Cross-asset coherence: new public function comparing directional signals
    and probability velocities across multiple symbols via saved JSONL logs.

Public API (no API key required):
  Gamma API : https://gamma-api.polymarket.com/markets
  CLOB API  : https://clob.polymarket.com/book?token_id={token_id}
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

try:
    from scipy.stats import norm as _sp_norm
    from scipy.optimize import curve_fit as _sp_curve_fit
    _SCIPY_IV = True
except ImportError:
    _SCIPY_IV = False


# ── API constants ─────────────────────────────────────────────────────────────
_GAMMA   = "https://gamma-api.polymarket.com"
_CLOB    = "https://clob.polymarket.com"
_TIMEOUT = 15

_CATEGORIES = ["Crypto", "Finance", "Economy", "Trending"]

# ── Time bucket definitions ───────────────────────────────────────────────────
_BUCKET_INTRADAY  = "intraday"   # <= 6h
_BUCKET_OVERNIGHT = "overnight"  # 6-24h
_BUCKET_SHORT     = "short"      # 1-3d
_BUCKET_WEEKLY    = "weekly"     # 3-7d
_BUCKET_MEDIUM    = "medium"     # 7-30d

_BUCKET_ORDER = [_BUCKET_INTRADAY, _BUCKET_OVERNIGHT,
                 _BUCKET_SHORT, _BUCKET_WEEKLY, _BUCKET_MEDIUM]

# Representative horizon (days) used for lognormal IV per bucket
_BUCKET_HORIZON_DAYS: Dict[str, float] = {
    _BUCKET_INTRADAY:  0.25,
    _BUCKET_OVERNIGHT: 0.5,
    _BUCKET_SHORT:     2.0,
    _BUCKET_WEEKLY:    5.0,
    _BUCKET_MEDIUM:    15.0,
}

_SHORT_TERM_DAYS = 30       # overall market inclusion cutoff
_NEUTRAL_BAND    = (0.35, 0.65)
_MIN_VELOCITY_PH = 0.03     # flag velocity if |change| >= 3%/hour

# ── Symbol → search terms ─────────────────────────────────────────────────────
_SYMBOL_TERMS: Dict[str, List[str]] = {
    "BTC":  ["bitcoin", "btc"], "ETH":  ["ethereum", "eth"],
    "SOL":  ["solana", "sol"],  "BNB":  ["bnb", "binance"],
    "XRP":  ["xrp", "ripple"],  "ADA":  ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"], "AVAX": ["avalanche", "avax"],
    "LINK": ["chainlink", "link"], "DOT": ["polkadot", "dot"],
    "SUI":  ["sui"],            "INJ":  ["injective", "inj"],
    "ARB":  ["arbitrum", "arb"], "OP":  ["optimism", "op"],
    "MORPHO": ["morpho"],       "SONIC": ["sonic"], "MON": ["monad", "mon"],
    "GOLD":   ["gold", "xauusd", "gold price"],
    "SILVER": ["silver", "xagusd"],
    "OIL":    ["oil price", "crude oil", "wti", "brent"],
    "SPX":    ["s&p 500", "sp500", "spx"], "NDX": ["nasdaq", "ndx"],
    "QQQ":    ["nasdaq", "qqq"],           "SPY": ["s&p 500", "spy etf"],
    "EWY":    ["south korea", "kospi", "korean"],
    "EWZ":    ["brazil", "bovespa"],
    "TLT":    ["treasury", "tlt", "10-year bond"],
}

_CRYPTO_MACRO = [
    "federal reserve", "fed rate", "rate cut", "rate hike", "interest rate",
    "inflation", "cpi", "recession", "crypto market", "bitcoin etf",
]
_EQUITY_MACRO = [
    "federal reserve", "fed rate", "interest rate", "inflation",
    "gdp", "recession", "earnings season", "stock market", "tariff",
]

_BULLISH_WORDS = [
    "above", "over", "exceed", "surpass", "reach", "hit", "rally", "rise",
    "gain", "increase", "up", "high", "bull", "buy", "grow", "recover",
    "rate cut", "dovish", "easing", "ath", "all-time high",
]
_BEARISH_WORDS = [
    "below", "under", "fall", "drop", "crash", "decline", "decrease",
    "down", "low", "bear", "sell", "lose", "loss", "correction",
    "recession", "rate hike", "hawkish", "tightening", "bankruptcy",
]


# ── Basic helpers ─────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _days_to_expiry(end_date_str: str) -> int:
    """Integer days to expiry (kept for backward compat)."""
    if not end_date_str:
        return 9999
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return max(0, (end - datetime.now(timezone.utc)).days)
    except Exception:
        return 9999


def _hours_to_expiry(end_date_str: str) -> float:
    """Float hours to expiry — finer resolution than _days_to_expiry."""
    if not end_date_str:
        return float("inf")
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        delta = (end - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta / 3600.0)
    except Exception:
        return float("inf")


def _classify_bucket(hours: float) -> str:
    if hours <= 6:        return _BUCKET_INTRADAY
    if hours <= 24:       return _BUCKET_OVERNIGHT
    if hours <= 72:       return _BUCKET_SHORT
    if hours <= 168:      return _BUCKET_WEEKLY
    return _BUCKET_MEDIUM


def _urgency(hours: float) -> float:
    """Weight inversely proportional to hours-to-expiry; floor at 0.5h."""
    return 1.0 / max(hours, 0.5)


def _parse_time_horizon(hours: float) -> str:
    if hours <= 0:    return "expired"
    if hours <= 6:    return f"{hours:.1f}h"
    if hours <= 24:   return f"{hours:.0f}h"
    if hours <= 168:  return f"{hours/24:.1f}d"
    if hours <= 720:  return f"{hours/168:.1f}w"
    return f"{hours/720:.1f}mo"


def _compute_relevance(question: str, symbol: str) -> float:
    q     = question.lower()
    s     = symbol.upper()
    terms = _SYMBOL_TERMS.get(s, [s.lower()])
    if any(t in q for t in terms):
        return 1.0
    from tradingagents.dataflows.tradfi_utils import classify_symbol
    atype = classify_symbol(s)
    if atype == "crypto" and any(t in q for t in _CRYPTO_MACRO):
        return 0.65
    if atype == "tradfi" and any(t in q for t in _EQUITY_MACRO):
        return 0.50
    return 0.0


def _is_nonneutral(yes_prob: float) -> bool:
    return yes_prob < _NEUTRAL_BAND[0] or yes_prob > _NEUTRAL_BAND[1]


def _derive_signal(question: str, yes_prob: float) -> Tuple[str, float]:
    q         = question.lower()
    bull_hits = sum(1 for w in _BULLISH_WORDS if w in q)
    bear_hits = sum(1 for w in _BEARISH_WORDS if w in q)
    if bull_hits > bear_hits:
        return "bullish", yes_prob
    if bear_hits > bull_hits:
        return "bearish", 1.0 - yes_prob
    return "neutral", 0.5


# ── Order book helpers ────────────────────────────────────────────────────────

def weighted_order_book_price(levels: List[dict], max_usd: float = 1000.0) -> Optional[float]:
    total_value = total_size = 0.0
    for level in levels[:3]:
        price = float(level.get("price", 0) or 0)
        size  = float(level.get("size",  0) or 0)
        if price <= 0 or size <= 0:
            continue
        level_usd = price * size
        if total_value + level_usd > max_usd:
            partial = (max_usd - total_value) / price
            total_size  += partial
            total_value += max_usd - total_value
            break
        total_value += level_usd
        total_size  += size
    return round(total_value / total_size, 4) if total_size > 0 else None


def _fetch_order_book(token_id: str) -> Optional[dict]:
    data = _get(f"{_CLOB}/book", params={"token_id": token_id})
    if not data:
        return None
    bids, asks = data.get("bids") or [], data.get("asks") or []
    return {
        "bids": bids, "asks": asks,
        "weighted_bid": weighted_order_book_price(bids),
        "weighted_ask": weighted_order_book_price(asks),
    }


def _ob_conviction(ob: Optional[dict]) -> float:
    """
    OB-derived conviction score in [0.1, 1.0].
    Tight spread -> near 1.0 (confident market).
    Wide spread  -> near 0.1 (uncertain, down-weight).
    Returns 1.0 when no OB data (neutral — don't penalise).
    """
    if not ob:
        return 1.0
    bid = ob.get("weighted_bid") or 0.0
    ask = ob.get("weighted_ask") or 0.0
    if ask <= 0 or bid <= 0 or ask <= bid:
        return 1.0
    mid         = (bid + ask) / 2.0
    spread_frac = (ask - bid) / max(mid, 1e-6)
    return max(0.1, round(1.0 - min(spread_frac, 0.9), 3))


# ── Probability surface helpers ───────────────────────────────────────────────

_PRICE_PATTERNS = [
    re.compile(r'\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)'),
    re.compile(r'([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:dollars?|usd)', re.I),
    re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*[kK]\b'),
]


def _extract_price_level(question: str) -> Optional[float]:
    q = question.lower()
    for pat in _PRICE_PATTERNS[:2]:
        m = pat.search(question)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    m = _PRICE_PATTERNS[2].search(q)
    if m:
        try:
            return float(m.group(1)) * 1000
        except ValueError:
            pass
    return None


def _is_above_market(question: str) -> Optional[bool]:
    q = question.lower()
    above_words = ["above", "over", "exceed", "surpass", "reach", "higher than",
                   "more than", "at least", "greater than", "tops", "hits"]
    below_words = ["below", "under", "less than", "lower than", "drops below",
                   "falls below", "beneath"]
    above = any(w in q for w in above_words)
    below = any(w in q for w in below_words)
    if above and not below:
        return True
    if below and not above:
        return False
    return None


def _interpolate_quantile(prices: List[float], survivals: List[float],
                          target_s: float) -> Optional[float]:
    n = len(prices)
    for i in range(n - 1):
        s_hi, s_lo = survivals[i], survivals[i + 1]
        p_lo, p_hi = prices[i],   prices[i + 1]
        if s_lo <= target_s <= s_hi:
            if s_hi == s_lo:
                return (p_lo + p_hi) / 2.0
            t = (s_hi - target_s) / (s_hi - s_lo)
            return p_lo + t * (p_hi - p_lo)
    if target_s > survivals[0] and n >= 2:
        dp = prices[1] - prices[0]
        ds = survivals[0] - survivals[1]
        if ds > 0:
            return prices[0] - (target_s - survivals[0]) / ds * dp
        return prices[0] * 0.85
    if target_s < survivals[-1] and n >= 2:
        dp = prices[-1] - prices[-2]
        ds = survivals[-2] - survivals[-1]
        if ds > 0:
            return prices[-1] + (survivals[-1] - target_s) / ds * dp
        return prices[-1] * 1.15
    return None


def _build_price_ranges(price_points: List[Tuple[float, float]]) -> Optional[dict]:
    if len(price_points) < 2:
        return None
    pts    = sorted(price_points, key=lambda x: x[0])
    prices = [p[0] for p in pts]
    survs  = [p[1] for p in pts]
    targets = {"q05": 0.95, "q10": 0.90, "q25": 0.75,
               "q50": 0.50, "q75": 0.25, "q90": 0.10, "q95": 0.05}
    q = {}
    for name, ts in targets.items():
        v = _interpolate_quantile(prices, survs, ts)
        if v is not None:
            q[name] = round(v, 2)
    if "q25" not in q or "q75" not in q:
        return None
    return {
        **q,
        "p50_range":     [q.get("q25"), q.get("q75")],
        "p90_range":     [q.get("q10"), q.get("q90")],
        "surface_points": pts,
    }


def _price_position_signal(current: float, ranges: dict) -> str:
    q10, q25 = ranges.get("q10"), ranges.get("q25")
    q75, q90 = ranges.get("q75"), ranges.get("q90")
    if q10 and current < q10:
        return "STRONGLY BEARISH — below 90% CI lower bound"
    if q25 and current < q25:
        return "BEARISH — below 50% CI lower bound"
    if q75 and current > q75:
        return "BULLISH — above 50% CI upper bound"
    if q90 and current > q90:
        return "STRONGLY BULLISH — above 90% CI upper bound"
    return "NEUTRAL — within 50% confidence interval"


# ── New analytics helpers ─────────────────────────────────────────────────────

def _load_prev_snapshot(
    cache_dir: str, symbol: str
) -> Tuple[Optional[datetime], Dict[str, float]]:
    """
    Load the most recent previous per-market probability snapshot from
    signals.jsonl.  Returns (timestamp, {question: yes_prob}) or (None, {}).
    """
    path = Path(cache_dir) / symbol.upper() / "signals.jsonl"
    if not path.exists():
        return None, {}
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        for raw in reversed(lines):
            try:
                data = json.loads(raw)
                snaps = data.get("market_snapshots", [])
                if not snaps:
                    continue
                ts_str = data.get("ts", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
                probs = {s["question"]: s["yes_prob"] for s in snaps if "question" in s}
                if probs:
                    return ts, probs
            except Exception:
                continue
    except Exception:
        pass
    return None, {}


def _compute_velocity(
    prev_ts: Optional[datetime],
    prev_probs: Dict[str, float],
    current_entries: List[dict],
) -> Dict[str, float]:
    """
    Compute per-market probability velocity (change per hour).
    Only returns entries where |velocity| >= _MIN_VELOCITY_PH.
    """
    if not prev_ts or not prev_probs:
        return {}
    elapsed = (datetime.now(timezone.utc) - prev_ts).total_seconds() / 3600.0
    if elapsed < 0.1:
        return {}
    result = {}
    for e in current_entries:
        q = e["question"]
        prev_p = prev_probs.get(q)
        if prev_p is None:
            continue
        vel = (e["yes_prob"] - prev_p) / elapsed
        if abs(vel) >= _MIN_VELOCITY_PH:
            result[q] = round(vel, 4)
    return result


def _price_level_magnets(
    price_surface_pts: List[Tuple[float, float]],
    current_price: Optional[float] = None,
) -> List[dict]:
    """
    Cluster market price-strike levels into ~1% bins.
    Bins with >= 2 market references are crowd support/resistance magnets.
    Returns list of {level, count, avg_survival, label} sorted by count desc.
    """
    if len(price_surface_pts) < 2:
        return []
    prices = [p[0] for p in price_surface_pts]
    median_price = float(np.median(prices))
    if median_price <= 0:
        return []
    # Auto bucket size: ~1% of median, rounded to a nice number
    raw  = median_price * 0.01
    mag  = 10 ** int(np.log10(max(raw, 1.0)))
    bsz  = max(round(raw / mag) * mag, 1.0)

    buckets: Dict[float, dict] = {}
    for price, surv in price_surface_pts:
        key = round(price / bsz) * bsz
        if key not in buckets:
            buckets[key] = {"count": 0, "survivals": []}
        buckets[key]["count"]    += 1
        buckets[key]["survivals"].append(surv)

    result = []
    for level, v in buckets.items():
        avg_s = float(np.mean(v["survivals"]))
        label = ""
        if v["count"] >= 2:
            if current_price:
                pct_away = (level - current_price) / current_price * 100
                label = f"{pct_away:+.1f}% from spot"
        result.append({
            "level":        level,
            "count":        v["count"],
            "avg_survival": round(avg_s, 3),
            "label":        label,
        })
    result.sort(key=lambda x: (-x["count"], x["level"]))
    return result


def _consensus_breadth(
    all_enriched: List[dict],
    directional: List[dict],
) -> dict:
    """
    Compute consensus breadth:
      non_neutral_pct   fraction of markets outside the neutral band
      bull_breadth      fraction of non-neutral markets pointing bullish
      conviction        "strong" | "moderate" | "mixed" | "absent"
    """
    total = len(all_enriched)
    if total == 0:
        return {"total": 0, "non_neutral_count": 0, "non_neutral_pct": 0.0,
                "bull_count": 0, "bear_count": 0, "bull_breadth": 0.5,
                "conviction": "absent"}
    nn       = [e for e in all_enriched if _is_nonneutral(e["yes_prob"])]
    bull_nn  = [e for e in nn if e["signal"] == "bullish"]
    bear_nn  = [e for e in nn if e["signal"] == "bearish"]
    nn_pct   = len(nn) / total
    bull_brd = len(bull_nn) / len(nn) if nn else 0.5

    if nn_pct < 0.25:
        conv = "absent"
    elif bull_brd > 0.75 or bull_brd < 0.25:
        conv = "strong" if nn_pct > 0.50 else "moderate"
    elif bull_brd > 0.60 or bull_brd < 0.40:
        conv = "moderate"
    else:
        conv = "mixed"

    return {
        "total":            total,
        "non_neutral_count": len(nn),
        "non_neutral_pct":  round(nn_pct, 3),
        "bull_count":       len(bull_nn),
        "bear_count":       len(bear_nn),
        "bull_breadth":     round(bull_brd, 3),
        "conviction":       conv,
    }


def _fit_lognormal_iv(
    pts: List[Tuple[float, float]],
    S0: float,
    horizon_days: float,
) -> Optional[float]:
    """
    Fit annualised lognormal implied volatility to (price, survival_prob) pairs.
    Model: S(x) = 1 - Phi[ (ln(x/S0) + 0.5*sigma^2*T) / (sigma*sqrt(T)) ]
    where T = horizon_days / 365.
    Returns annualised sigma or None on failure.
    """
    if not _SCIPY_IV or len(pts) < 3 or S0 <= 0 or horizon_days <= 0:
        return None
    T = horizon_days / 365.0
    prices    = np.array([p[0] for p in pts], dtype=float)
    survivals = np.clip([p[1] for p in pts], 0.02, 0.98)

    def model(x, sigma):
        if sigma <= 1e-4:
            return np.full_like(x, 0.5)
        sqrtT = np.sqrt(T)
        z = (np.log(x / S0) + 0.5 * sigma ** 2 * T) / (sigma * sqrtT)
        return 1.0 - _sp_norm.cdf(z)

    try:
        popt, _ = _sp_curve_fit(
            model, prices, survivals, p0=[0.6],
            bounds=(0.01, 10.0), maxfev=2000,
        )
        sigma = float(popt[0])
        return round(sigma, 4) if 0.01 <= sigma <= 10.0 else None
    except Exception:
        return None


def _build_multi_horizon_ladder(
    all_enriched: List[dict],
    current_price: Optional[float],
) -> Dict[str, dict]:
    """
    Build separate implied price ranges per time bucket from price-level markets.
    Returns {bucket_name: {ranges..., iv, n_markets, position_signal}} for
    buckets that have >= 2 price-level data points.
    """
    bucket_pts: Dict[str, List[Tuple[float, float]]] = {b: [] for b in _BUCKET_ORDER}
    for e in all_enriched:
        pl = e.get("price_level")
        ia = e.get("is_above")
        if pl is None or ia is None:
            continue
        surv = e["yes_prob"] if ia else (1.0 - e["yes_prob"])
        bucket_pts[e["bucket"]].append((pl, surv))

    result = {}
    for bname in _BUCKET_ORDER:
        pts = bucket_pts[bname]
        if len(pts) < 2:
            continue
        ranges = _build_price_ranges(pts)
        if not ranges:
            continue
        horizon_d = _BUCKET_HORIZON_DAYS[bname]
        iv = None
        pos_sig = None
        if current_price and current_price > 0:
            iv      = _fit_lognormal_iv(pts, current_price, horizon_d)
            pos_sig = _price_position_signal(current_price, ranges)
        result[bname] = {
            **ranges,
            "iv":              iv,
            "n_markets":       len(pts),
            "position_signal": pos_sig,
        }
    return result


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _save_price_levels(cache_dir: str, symbol: str, data: dict):
    d = Path(cache_dir) / symbol.upper()
    d.mkdir(parents=True, exist_ok=True)
    (d / "price_levels.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


def read_price_levels_cache(symbol: str, cache_dir: str) -> str:
    """
    Read the latest cached price-levels data and return a compact string
    suitable for injection into agent prompts.
    Includes multi-horizon ladder and breadth data if available.
    """
    path = Path(cache_dir) / symbol.upper() / "price_levels.json"
    if not path.exists():
        return ""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("no_directional_signal") and not d.get("ranges"):
            return (f"NA — no non-neutral Polymarket markets found for "
                    f"{symbol.upper()} on {d.get('date', '')}.")
        lines = [f"Polymarket Price Ranges for {symbol.upper()} ({d.get('date', '')})"]

        # Multi-horizon ladder first (if available)
        ladder = d.get("multi_horizon_ladder", {})
        if ladder:
            lines.append("  Probability Ladder:")
            for bname in _BUCKET_ORDER:
                bl = ladder.get(bname)
                if not bl:
                    continue
                q50  = bl.get("q50")
                p50  = bl.get("p50_range", [None, None])
                iv   = bl.get("iv")
                pos  = bl.get("position_signal", "")
                iv_s = f"  IV={iv:.0%}" if iv else ""
                q50_s = f"${q50:,.0f}" if q50 else "N/A"
                ci_s  = (f"${p50[0]:,.0f}-${p50[1]:,.0f}"
                         if p50[0] and p50[1] else "N/A")
                lines.append(f"    [{bname}] P50={q50_s}  50%CI=[{ci_s}]{iv_s}  {pos}")
        else:
            # Fall back to single-range display
            r = d.get("ranges", {})
            if r.get("q50"):
                lines.append(f"  Median expected: ${r['q50']:,.0f}")
            p50 = r.get("p50_range", [None, None])
            p90 = r.get("p90_range", [None, None])
            if p50[0] and p50[1]:
                lines.append(f"  50% CI: ${p50[0]:,.0f} - ${p50[1]:,.0f}")
            if p90[0] and p90[1]:
                lines.append(f"  90% CI: ${p90[0]:,.0f} - ${p90[1]:,.0f}")

        if d.get("current_price"):
            lines.append(f"  Current price: ${d['current_price']:,.2f}")
        if d.get("position_signal"):
            lines.append(f"  Signal vs range: {d['position_signal']}")

        bp = d.get("bull_probability")
        if bp is not None:
            lines.append(f"  Overall bull probability: {bp:.0%}")

        brd = d.get("breadth", {})
        if brd.get("conviction"):
            lines.append(f"  Conviction: {brd['conviction']}  "
                         f"({brd.get('non_neutral_count', 0)}/{brd.get('total', 0)} "
                         f"markets non-neutral)")
        return "\n".join(lines)
    except Exception:
        return ""


# ── Main public function ──────────────────────────────────────────────────────

def get_polymarket_sentiment(
    symbol: str,
    curr_date: str,
    cache_dir: str = "./data/polymarket_cache",
    current_price: Optional[float] = None,
) -> str:
    """
    Fetch live Polymarket markets, compute urgency x conviction weighted
    directional bias, probability velocity, multi-horizon price ladder,
    price level magnets, consensus breadth, and lognormal implied volatility.

    Caches structured data (price_levels.json, signals.jsonl) for downstream
    agents via read_price_levels_cache().
    """
    symbol_upper = symbol.upper()

    # ── 1. Fetch markets ──────────────────────────────────────────────────────
    all_markets: List[dict] = []
    seen_ids: set = set()
    for cat in _CATEGORIES:
        data = _get(f"{_GAMMA}/markets", params={
            "active": "true", "closed": "false",
            "order": "volume", "ascending": "false",
            "limit": 100, "category": cat,
        })
        raw = (data if isinstance(data, list)
               else (data or {}).get("data") or (data or {}).get("markets") or [])
        for m in raw:
            mid = m.get("id") or m.get("conditionId", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_markets.append(m)
        time.sleep(0.1)

    if not all_markets:
        return "NA — Polymarket API unavailable; no live markets could be fetched."

    # ── 2. Score relevance, compute hours/bucket ──────────────────────────────
    scored = []
    for m in all_markets:
        q     = m.get("question", "") or ""
        score = _compute_relevance(q, symbol_upper)
        if score < 0.5:
            continue
        end_str     = m.get("endDate") or m.get("end_date", "")
        hours       = _hours_to_expiry(end_str)
        days        = hours / 24.0
        if days > _SHORT_TERM_DAYS:
            continue
        m["_relevance"] = score
        m["_hours"]     = hours
        m["_bucket"]    = _classify_bucket(hours)
        scored.append(m)

    if not scored:
        return (f"NA — no live Polymarket markets with a clear causal relationship to "
                f"{symbol_upper} were found across Crypto / Finance / Economy / Trending.")

    # Sort: highest urgency first, then by relevance, then by volume
    scored.sort(key=lambda m: (
        -_urgency(m["_hours"]),
        -m["_relevance"],
        -float(m.get("volume", 0) or 0),
    ))

    # ── 3. Load previous snapshot for velocity ────────────────────────────────
    prev_ts, prev_probs = _load_prev_snapshot(cache_dir, symbol_upper)

    # ── 4. Enrich markets with OB + conviction ────────────────────────────────
    all_enriched:      List[dict]               = []
    price_surface_pts: List[Tuple[float, float]] = []   # global surface (all buckets)
    directional:       List[dict]               = []

    for m in scored[:25]:
        tokens         = m.get("tokens") or []
        outcome_prices = m.get("outcomePrices") or []
        hours          = m["_hours"]
        bucket         = m["_bucket"]

        # Get YES probability
        yes_prob     = None
        yes_token_id = None
        for i, tok in enumerate(tokens):
            if tok.get("outcome", "").lower() == "yes":
                yes_token_id = tok.get("token_id") or tok.get("tokenId")
                if i < len(outcome_prices):
                    try:
                        yes_prob = float(outcome_prices[i])
                    except (ValueError, TypeError):
                        pass
                break
        if yes_prob is None and outcome_prices:
            try:
                yes_prob = float(outcome_prices[0])
            except (ValueError, TypeError):
                yes_prob = 0.5
        yes_prob = yes_prob if yes_prob is not None else 0.5

        # OB enrichment + conviction score
        ob          = None
        ob_mid      = None
        conviction  = 1.0
        if yes_token_id:
            ob = _fetch_order_book(yes_token_id)
            if ob and ob.get("weighted_bid") and ob.get("weighted_ask"):
                ob_mid   = round((ob["weighted_bid"] + ob["weighted_ask"]) / 2, 4)
                yes_prob = ob_mid
            conviction = _ob_conviction(ob)
            time.sleep(0.05)

        q              = m.get("question", "")
        signal, bull_p = _derive_signal(q, yes_prob)
        volume         = float(m.get("volume", 0) or 0)
        urgency_val    = _urgency(hours)
        price_lvl      = _extract_price_level(q)
        is_above       = _is_above_market(q)
        horizon_str    = _parse_time_horizon(hours)

        entry = {
            "question":    q,
            "yes_prob":    round(yes_prob, 3),
            "signal":      signal,
            "bull_prob":   round(bull_p, 3),
            "volume":      volume,
            "hours":       hours,
            "bucket":      bucket,
            "horizon":     horizon_str,
            "end_date":    m.get("endDate") or m.get("end_date", ""),
            "ob_mid":      ob_mid,
            "conviction":  conviction,
            "urgency":     urgency_val,
            "price_level": price_lvl,
            "is_above":    is_above,
            "relevance":   m["_relevance"],
        }
        all_enriched.append(entry)

        # Global probability surface
        if price_lvl is not None and is_above is not None:
            surv = yes_prob if is_above else (1.0 - yes_prob)
            price_surface_pts.append((price_lvl, surv))

        # Directional filter: non-neutral
        if _is_nonneutral(yes_prob):
            directional.append(entry)

    # ── 5. Probability velocity ───────────────────────────────────────────────
    velocity_map = _compute_velocity(prev_ts, prev_probs, all_enriched)

    # ── 6. Multi-horizon probability ladder ───────────────────────────────────
    multi_ladder = _build_multi_horizon_ladder(all_enriched, current_price)

    # ── 7. Urgency x conviction weighted aggregate ────────────────────────────
    no_directional_signal = False
    if directional:
        total_eff = sum(
            e["volume"] * e["urgency"] * e["conviction"]
            for e in directional if e["volume"] > 0
        ) or 1.0
        agg_bull_p = sum(
            e["bull_prob"] * e["volume"] * e["urgency"] * e["conviction"]
            for e in directional if e["volume"] > 0
        ) / total_eff
        agg_bull_p = round(max(0.0, min(1.0, agg_bull_p)), 3)
        agg_bear_p = round(1.0 - agg_bull_p, 3)
    else:
        no_directional_signal = True
        agg_bull_p = agg_bear_p = None

    # ── 8. Consensus breadth ──────────────────────────────────────────────────
    breadth = _consensus_breadth(all_enriched, directional)

    # ── 9. Global price ranges (from all buckets combined) ────────────────────
    global_ranges = _build_price_ranges(price_surface_pts) if price_surface_pts else None
    position_signal = None
    if global_ranges and current_price and current_price > 0:
        position_signal = _price_position_signal(current_price, global_ranges)

    # ── 10. Price level magnets ────────────────────────────────────────────────
    magnets = _price_level_magnets(price_surface_pts, current_price)

    # ── 11. Save enhanced JSONL cache ─────────────────────────────────────────
    cache_data = {
        "symbol":              symbol_upper,
        "date":                curr_date,
        "ts":                  datetime.now(timezone.utc).isoformat(),
        "current_price":       current_price,
        "bull_probability":    agg_bull_p,
        "bear_probability":    agg_bear_p,
        "no_directional_signal": no_directional_signal,
        "position_signal":     position_signal,
        "ranges":              global_ranges or {},
        "multi_horizon_ladder": multi_ladder,
        "breadth":             breadth,
        "magnets":             magnets,
        "surface_points":      [{"price": p, "survival": s}
                                 for p, s in sorted(price_surface_pts)],
        "directional_markets": len(directional),
        "market_snapshots":    [
            {"question": e["question"], "yes_prob": e["yes_prob"],
             "bucket": e["bucket"], "hours": e["hours"]}
            for e in all_enriched
        ],
    }
    _save_price_levels(cache_dir, symbol_upper, cache_data)
    log_dir = Path(cache_dir) / symbol_upper
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "signals.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(cache_data, default=str) + "\n")

    # ── 12. Format report ─────────────────────────────────────────────────────
    if no_directional_signal:
        bias_line = (
            f"**Directional Bias:** NA — no non-neutral short-term markets found for "
            f"{symbol_upper}; cannot derive a signal from Polymarket."
        )
    else:
        bias_tag = ("Bullish" if agg_bull_p > 0.55 else
                    ("Bearish" if agg_bull_p < 0.45 else "Neutral"))
        bias_line = (
            f"**Directional Bias (urgency x conviction weighted):** {bias_tag}  |  "
            f"Bull: **{agg_bull_p:.0%}**  Bear: **{agg_bear_p:.0%}**"
        )

    conv_str = breadth["conviction"].upper()
    breadth_line = (
        f"**Consensus Breadth:** {breadth['non_neutral_count']}/{breadth['total']} markets "
        f"non-neutral ({breadth['non_neutral_pct']:.0%})  —  "
        f"{breadth['bull_count']} bullish / {breadth['bear_count']} bearish  —  "
        f"**{conv_str}** conviction"
    )

    lines = [
        f"## {symbol_upper} Polymarket Prediction Market Signals\n",
        bias_line + "\n",
        breadth_line + "\n",
    ]

    # Probability velocity section
    if velocity_map:
        elapsed_h = ((datetime.now(timezone.utc) - prev_ts).total_seconds() / 3600.0
                     if prev_ts else 0.0)
        lines += [
            f"### Probability Velocity (last {elapsed_h:.1f}h)\n",
            "| Market | Current | Change/h | Direction | Bucket |",
            "|--------|---------|----------|-----------|--------|",
        ]
        vel_entries = sorted(velocity_map.items(), key=lambda x: -abs(x[1]))
        for q_text, vel in vel_entries[:8]:
            entry = next((e for e in all_enriched if e["question"] == q_text), None)
            if not entry:
                continue
            cur_p   = entry["yes_prob"]
            vel_str = f"{vel:+.1%}/h"
            dir_str = "RISING" if vel > 0 else "FALLING"
            q_short = q_text[:60] + ("..." if len(q_text) > 60 else "")
            lines.append(
                f"| {q_short} | {cur_p:.0%} | {vel_str} | {dir_str} | {entry['bucket']} |"
            )
        lines.append("")

    # Multi-horizon probability ladder
    if multi_ladder:
        lines += [
            "\n### Multi-Horizon Probability Ladder\n",
            "| Bucket | N | P50 | 50% CI | 90% CI | vs Spot | Ann. IV |",
            "|--------|---|-----|--------|--------|---------|---------|",
        ]
        for bname in _BUCKET_ORDER:
            bl = multi_ladder.get(bname)
            if not bl:
                continue
            q50   = bl.get("q50")
            p50r  = bl.get("p50_range", [None, None])
            p90r  = bl.get("p90_range", [None, None])
            iv    = bl.get("iv")
            pos   = bl.get("position_signal", "—")
            nm    = bl.get("n_markets", 0)
            q50_s = f"${q50:,.0f}" if q50 else "N/A"
            ci50  = (f"${p50r[0]:,.0f}–${p50r[1]:,.0f}"
                     if p50r[0] and p50r[1] else "N/A")
            ci90  = (f"${p90r[0]:,.0f}–${p90r[1]:,.0f}"
                     if p90r[0] and p90r[1] else "N/A")
            iv_s  = f"{iv:.0%}" if iv else "N/A"
            pos_s = pos.split(" —")[0] if pos else "—"
            lines.append(
                f"| {bname} | {nm} | {q50_s} | {ci50} | {ci90} | {pos_s} | {iv_s} |"
            )
        lines.append("")

    # Price level magnets
    hot_magnets = [mg for mg in magnets if mg["count"] >= 2]
    if hot_magnets:
        lines += [
            "\n### Price Level Magnets (multi-market references)\n",
            "| Level | Markets referencing | Avg P(>level) | Distance from spot |",
            "|-------|---------------------|---------------|--------------------|",
        ]
        for mg in hot_magnets[:8]:
            lvl_s   = f"${mg['level']:,.0f}"
            dist_s  = mg["label"] or "—"
            lines.append(
                f"| {lvl_s} | {mg['count']} | {mg['avg_survival']:.0%} | {dist_s} |"
            )
        lines.append("")

    # Global probability surface (if available and no ladder)
    if global_ranges and not multi_ladder:
        q10, q25 = global_ranges.get("q10"), global_ranges.get("q25")
        q50      = global_ranges.get("q50")
        q75, q90 = global_ranges.get("q75"), global_ranges.get("q90")
        lines += [
            "\n### Implied Price Ranges (all horizons combined)\n",
            "| Confidence | Lower | Upper | Width |",
            "|------------|-------|-------|-------|",
        ]
        if q25 and q75:
            lines.append(f"| 50% CI | ${q25:,.0f} | ${q75:,.0f} | ${q75-q25:,.0f} |")
        if q10 and q90:
            lines.append(f"| 90% CI | ${q10:,.0f} | ${q90:,.0f} | ${q90-q10:,.0f} |")
        if q50:
            lines.append(f"\n**Median expected price:** ${q50:,.0f}")
        if current_price and position_signal:
            lines.append(f"**Current price:** ${current_price:,.2f}  ->  **{position_signal}**\n")

    # Non-neutral markets grouped by bucket
    if directional:
        lines.append("\n### Non-Neutral Directional Markets by Bucket\n")
        for bname in _BUCKET_ORDER:
            bucket_dir = [e for e in directional if e["bucket"] == bname]
            if not bucket_dir:
                continue
            bucket_label = {
                _BUCKET_INTRADAY:  "intraday  (<6h)",
                _BUCKET_OVERNIGHT: "overnight (6-24h)",
                _BUCKET_SHORT:     "short     (1-3d)",
                _BUCKET_WEEKLY:    "weekly    (3-7d)",
                _BUCKET_MEDIUM:    "medium    (7-30d)",
            }[bname]
            lines.append(f"**[{bucket_label}]**")
            lines.append("| Question | YES% | Signal | ETA | Vol |")
            lines.append("|----------|------|--------|-----|-----|")
            for e in sorted(bucket_dir, key=lambda x: -x["volume"])[:6]:
                q_s   = e["question"][:60] + ("..." if len(e["question"]) > 60 else "")
                vol_s = f"${e['volume']:,.0f}" if e["volume"] > 0 else "—"
                lines.append(
                    f"| {q_s} | {e['yes_prob']:.0%} | {e['signal'].upper()} "
                    f"| {e['horizon']} | {vol_s} |"
                )
            lines.append("")

    lines += [
        "\n---\n",
        f"*{len(all_enriched)} markets analysed. "
        f"Weighted by urgency x OB-conviction. "
        f"Price ranges and velocity cached for downstream agents.*",
    ]
    return "\n".join(lines)


# ── Cross-asset coherence ─────────────────────────────────────────────────────

def get_cross_asset_coherence(
    symbols: List[str],
    curr_date: str,
    cache_dir: str = "./data/polymarket_cache",
) -> str:
    """
    Compare the latest Polymarket directional signals and probability velocities
    across multiple symbols.  Uses saved signals.jsonl snapshots — no API calls.

    A macro regime signal is inferred when >= 60% of symbols with non-neutral
    readings agree on direction.  Divergence signals asset-specific moves.

    Returns a formatted Markdown section for injection into agent prompts.
    """
    snapshots: List[dict] = []

    for sym in symbols:
        path = Path(cache_dir) / sym.upper() / "signals.jsonl"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            latest = prev = None
            for raw in reversed(lines):
                try:
                    d = json.loads(raw)
                    if latest is None:
                        latest = d
                    elif prev is None:
                        prev = d
                        break
                except Exception:
                    continue
            if latest is None:
                continue

            # Compute velocity from last two snapshots
            vel = None
            if prev is not None:
                try:
                    ts_now  = datetime.fromisoformat(
                        latest["ts"].replace("Z", "+00:00"))
                    ts_prev = datetime.fromisoformat(
                        prev["ts"].replace("Z", "+00:00"))
                    elapsed = (ts_now - ts_prev).total_seconds() / 3600.0
                    bp_now  = latest.get("bull_probability")
                    bp_prev = prev.get("bull_probability")
                    if elapsed > 0.1 and bp_now is not None and bp_prev is not None:
                        vel = round((bp_now - bp_prev) / elapsed, 4)
                except Exception:
                    pass

            snapshots.append({
                "symbol":         sym.upper(),
                "bull_prob":      latest.get("bull_probability"),
                "no_signal":      latest.get("no_directional_signal", True),
                "position":       latest.get("position_signal", ""),
                "breadth":        latest.get("breadth", {}),
                "ts":             latest.get("ts", ""),
                "velocity":       vel,
            })
        except Exception:
            continue

    if not snapshots:
        return (f"NA — no Polymarket snapshots found for {', '.join(s.upper() for s in symbols)}. "
                "Run get_polymarket_sentiment for each symbol first.")

    # Classify each symbol
    bullish_syms = [s for s in snapshots
                    if not s["no_signal"] and s["bull_prob"] is not None
                    and s["bull_prob"] > 0.55]
    bearish_syms = [s for s in snapshots
                    if not s["no_signal"] and s["bull_prob"] is not None
                    and s["bull_prob"] < 0.45]
    neutral_syms = [s for s in snapshots
                    if s["no_signal"] or s["bull_prob"] is None
                    or 0.45 <= s["bull_prob"] <= 0.55]

    n_signal = len(bullish_syms) + len(bearish_syms)
    n_total  = len(snapshots)

    if n_signal == 0:
        regime = "NEUTRAL — no directional Polymarket signal across tracked assets"
    elif len(bullish_syms) >= 0.60 * n_signal:
        regime = f"RISK-ON macro signal — {len(bullish_syms)}/{n_signal} signalling assets are BULLISH"
    elif len(bearish_syms) >= 0.60 * n_signal:
        regime = f"RISK-OFF macro signal — {len(bearish_syms)}/{n_signal} signalling assets are BEARISH"
    else:
        regime = (f"MIXED / IDIOSYNCRATIC — "
                  f"{len(bullish_syms)} bullish / {len(bearish_syms)} bearish "
                  f"across {n_signal} signalling assets")

    # Velocity summary
    rising  = [s for s in snapshots if s["velocity"] and s["velocity"] > _MIN_VELOCITY_PH]
    falling = [s for s in snapshots if s["velocity"] and s["velocity"] < -_MIN_VELOCITY_PH]

    lines = [
        f"## Cross-Asset Polymarket Coherence ({curr_date})\n",
        f"**Macro Regime:** {regime}\n",
        f"Assets tracked: {n_total}  |  With signal: {n_signal}  |  "
        f"Bullish: {len(bullish_syms)}  Bearish: {len(bearish_syms)}  Neutral: {len(neutral_syms)}\n",
        "\n### Per-Asset Signal Summary\n",
        "| Symbol | Bull % | Direction | Conviction | Velocity/h | Position |",
        "|--------|--------|-----------|------------|------------|----------|",
    ]

    for s in sorted(snapshots, key=lambda x: -(x["bull_prob"] or 0.5)):
        bp    = s["bull_prob"]
        bp_s  = f"{bp:.0%}" if bp is not None else "N/A"
        dir_s = ("BULL" if bp and bp > 0.55 else
                 ("BEAR" if bp and bp < 0.45 else "NEUTRAL"))
        conv  = s["breadth"].get("conviction", "—") if s["breadth"] else "—"
        vel   = s["velocity"]
        vel_s = f"{vel:+.2%}/h" if vel is not None else "—"
        pos   = (s["position"] or "").split(" —")[0][:30] if s["position"] else "—"
        lines.append(
            f"| {s['symbol']} | {bp_s} | {dir_s} | {conv} | {vel_s} | {pos} |"
        )

    if rising or falling:
        lines.append("\n**Fast-moving signals:**")
        for s in rising:
            lines.append(f"- {s['symbol']}: bull prob rising at {s['velocity']:+.2%}/h")
        for s in falling:
            lines.append(f"- {s['symbol']}: bull prob falling at {s['velocity']:+.2%}/h")

    lines.append(f"\n*Derived from cached signals.jsonl — no live API calls.*")
    return "\n".join(lines)
