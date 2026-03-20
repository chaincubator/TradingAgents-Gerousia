"""Polymarket prediction-market data utilities — v4.

Probability surface methodology (per user spec):
  A market such as "Bitcoin above $X on March 20?" gives a single point on
  the survival function S(x) = P(price > x).  With multiple strikes at the
  same expiry, the full distribution can be inferred.

  Critical filters applied before any surface construction:
  • INFORMATIVE RANGE ONLY: only include surface points where the YES
    probability is strictly inside [SURFACE_MIN, SURFACE_MAX] = [3%, 97%].
    Near-certain outcomes (e.g. "above $62k" at 100% when BTC = $84k, or
    "above $90k" at 0.5%) add no distributional information and distort
    interpolation at the tails.  Only the "live" strikes where the market
    is actually pricing uncertainty contribute to the surface.
  • GROUPED BY RESOLUTION DATE: markets for the same expiry date form a
    coherent implied forward distribution.  Mixing "by March 20" with "by
    March 25" conflates different term horizons.  Each date gets its own
    surface, quantile table, and lognormal IV.
  • OB DEPTH WEIGHTING: when fitting lognormal IV, each surface point is
    weighted by its total order-book depth (sum of top-5 bid+ask USDC
    notional).  Deep, liquid markets constrain the fit more than thin ones.
  • FIRST-TO-HIT MARKETS: "Will Bitcoin hit $60k or $80k first?" markets
    are parsed as directional signals with implied downside/upside skew.
    When the current price lies between the two levels, approximate survival
    function points are also derived and added to the surface.

Other features (from v3):
  • Tighter time bucketing (intraday/overnight/short/weekly/medium)
  • Probability velocity from signals.jsonl
  • OB conviction (bid-ask spread) as aggregate weight multiplier
  • Urgency × conviction weighted directional aggregate
  • Price level magnets (cluster analysis)
  • Consensus breadth score
  • Cross-asset coherence function

Public API (no key required):
  Gamma : https://gamma-api.polymarket.com/markets
  CLOB  : https://clob.polymarket.com/book?token_id={token_id}
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
_BUCKET_INTRADAY  = "intraday"
_BUCKET_OVERNIGHT = "overnight"
_BUCKET_SHORT     = "short"
_BUCKET_WEEKLY    = "weekly"
_BUCKET_MEDIUM    = "medium"

_BUCKET_ORDER = [_BUCKET_INTRADAY, _BUCKET_OVERNIGHT,
                 _BUCKET_SHORT, _BUCKET_WEEKLY, _BUCKET_MEDIUM]

_SHORT_TERM_DAYS = 30
_NEUTRAL_BAND    = (0.35, 0.65)
_MIN_VELOCITY_PH = 0.03

# ── Probability surface informative range ─────────────────────────────────────
# Only strikes where the YES probability is inside this band contribute to the
# survival function.  Near-certain outcomes are excluded.
_SURFACE_MIN_PROB = 0.03
_SURFACE_MAX_PROB = 0.97


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

# ── Resolution date parsing ───────────────────────────────────────────────────
_MONTH_MAP: Dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}

# "on March 20", "by March 20th", "before April 1"
_RES_DATE_NAMED = re.compile(
    r'(?:on|by|before|end of)\s+'
    r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    r'\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?',
    re.I,
)
# "on 3/20" or "by 3/20/2026"
_RES_DATE_NUMERIC = re.compile(
    r'(?:on|by|before)\s+(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?',
    re.I,
)

# ── First-to-hit market parsing ───────────────────────────────────────────────
# e.g. "Will Bitcoin hit $60k or $80k first?"
_FIRST_HIT_RE = re.compile(
    r'(?:hit|reach|touch)\s+\$?([\d,]+\.?\d*\s*[kK]?)\s+or\s+\$?([\d,]+\.?\d*\s*[kK]?)\s+first',
    re.I,
)


# ── Basic helpers ─────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _days_to_expiry(end_date_str: str) -> int:
    if not end_date_str:
        return 9999
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return max(0, (end - datetime.now(timezone.utc)).days)
    except Exception:
        return 9999


def _hours_to_expiry(end_date_str: str) -> float:
    if not end_date_str:
        return float("inf")
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        delta = (end - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta / 3600.0)
    except Exception:
        return float("inf")


def _classify_bucket(hours: float) -> str:
    if hours <= 6:   return _BUCKET_INTRADAY
    if hours <= 24:  return _BUCKET_OVERNIGHT
    if hours <= 72:  return _BUCKET_SHORT
    if hours <= 168: return _BUCKET_WEEKLY
    return _BUCKET_MEDIUM


def _urgency(hours: float) -> float:
    return 1.0 / max(hours, 0.5)


def _parse_time_horizon(hours: float) -> str:
    if hours <= 0:   return "expired"
    if hours <= 6:   return f"{hours:.1f}h"
    if hours <= 24:  return f"{hours:.0f}h"
    if hours <= 168: return f"{hours/24:.1f}d"
    if hours <= 720: return f"{hours/168:.1f}w"
    return f"{hours/720:.1f}mo"


def _parse_resolution_date(question: str, end_date_str: str = "") -> Optional[str]:
    """
    Extract a specific resolution date from the market question string.
    Returns "YYYY-MM-DD" or None (fall back to end_date_str from API).
    """
    q = question.lower()
    now_year = datetime.now(timezone.utc).year

    m = _RES_DATE_NAMED.search(q)
    if m:
        month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
        month = _MONTH_MAP.get(month_str.lower().rstrip("."))
        if month:
            try:
                day  = int(day_str)
                year = int(year_str) if year_str else now_year
                if year < 100:
                    year += 2000
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    m = _RES_DATE_NUMERIC.search(q)
    if m:
        try:
            mo, da = int(m.group(1)), int(m.group(2))
            yr = int(m.group(3)) if m.group(3) else now_year
            if yr < 100:
                yr += 2000
            return datetime(yr, mo, da).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # Fall back to API end date
    if end_date_str:
        try:
            dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def _parse_k(s: str) -> Optional[float]:
    """Parse price string like '80k', '80,000', '80000' → float."""
    s = s.strip().replace(",", "")
    try:
        if s.lower().endswith("k"):
            return float(s[:-1]) * 1000
        return float(s)
    except ValueError:
        return None


def _parse_first_to_hit(
    question: str, yes_prob: float, current_price: Optional[float]
) -> Optional[dict]:
    """
    Parse "Will X hit $A or $B first?" markets.
    Returns a dict describing the two levels and the implied signal,
    or None if the question doesn't match.

    If current_price lies between A and B, also returns approximate
    survival function points using the linear approximation:
      S(A) ≈ 1 - yes_prob   (probability price will go that low before recovering)
      S(B) ≈ yes_prob        (... before going that high)
    These are APPROXIMATE — useful for directionality, not precise distribution.
    """
    m = _FIRST_HIT_RE.search(question)
    if not m:
        return None
    price_a = _parse_k(m.group(1))
    price_b = _parse_k(m.group(2))
    if price_a is None or price_b is None:
        return None

    lo, hi = (price_a, price_b) if price_a < price_b else (price_b, price_a)
    # YES = P(price_a hit first); determine which is lower
    p_lo_first = yes_prob if price_a < price_b else (1.0 - yes_prob)

    signal = "bearish" if p_lo_first > 0.5 else "bullish"

    surface_pts: List[Tuple[float, float]] = []
    if current_price and lo < current_price < hi:
        # Only add if in the informative range
        surv_lo = 1.0 - p_lo_first   # P(price > lo) ≈ 1 - P(lo hit first)
        surv_hi = p_lo_first          # P(price > hi) ≈ P(lo hit first) → rough approx
        if _SURFACE_MIN_PROB <= surv_lo <= _SURFACE_MAX_PROB:
            surface_pts.append((lo, surv_lo))
        if _SURFACE_MIN_PROB <= surv_hi <= _SURFACE_MAX_PROB:
            surface_pts.append((hi, surv_hi))

    return {
        "lo": lo, "hi": hi,
        "p_lo_first": round(p_lo_first, 3),
        "signal": signal,
        "surface_pts": surface_pts,
    }


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
    """Conviction score [0.1, 1.0] from bid-ask spread fraction."""
    if not ob:
        return 1.0
    bid = ob.get("weighted_bid") or 0.0
    ask = ob.get("weighted_ask") or 0.0
    if ask <= 0 or bid <= 0 or ask <= bid:
        return 1.0
    mid         = (bid + ask) / 2.0
    spread_frac = (ask - bid) / max(mid, 1e-6)
    return max(0.1, round(1.0 - min(spread_frac, 0.9), 3))


def _ob_depth(ob: Optional[dict]) -> float:
    """
    Total USDC-denominated notional across the top 5 bid + ask levels.
    Used as a weight for IV fitting: deeper markets constrain the fit more.
    """
    if not ob:
        return 0.0
    total = 0.0
    for side in ["bids", "asks"]:
        for level in (ob.get(side) or [])[:5]:
            price = float(level.get("price", 0) or 0)
            size  = float(level.get("size",  0) or 0)
            total += price * size
    return total


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
    """Build quantile table from (price, survival_prob) pairs."""
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
        "p50_range":      [q.get("q25"), q.get("q75")],
        "p90_range":      [q.get("q10"), q.get("q90")],
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
    path = Path(cache_dir) / symbol.upper() / "signals.jsonl"
    if not path.exists():
        return None, {}
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        for raw in reversed(lines):
            try:
                data  = json.loads(raw)
                snaps = data.get("market_snapshots", [])
                if not snaps:
                    continue
                ts_str = data.get("ts", "")
                ts     = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
                probs  = {s["question"]: s["yes_prob"] for s in snaps if "question" in s}
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
    if not prev_ts or not prev_probs:
        return {}
    elapsed = (datetime.now(timezone.utc) - prev_ts).total_seconds() / 3600.0
    if elapsed < 0.1:
        return {}
    result = {}
    for e in current_entries:
        q      = e["question"]
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
    """Cluster price-strike levels into ~1% bins to find crowd anchor levels."""
    if len(price_surface_pts) < 2:
        return []
    prices = [p[0] for p in price_surface_pts]
    median_price = float(np.median(prices))
    if median_price <= 0:
        return []
    raw = median_price * 0.01
    mag = 10 ** int(np.log10(max(raw, 1.0)))
    bsz = max(round(raw / mag) * mag, 1.0)

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
        if v["count"] >= 2 and current_price:
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


def _consensus_breadth(all_enriched: List[dict], directional: List[dict]) -> dict:
    total = len(all_enriched)
    if total == 0:
        return {"total": 0, "non_neutral_count": 0, "non_neutral_pct": 0.0,
                "bull_count": 0, "bear_count": 0, "bull_breadth": 0.5,
                "conviction": "absent"}
    nn      = [e for e in all_enriched if _is_nonneutral(e["yes_prob"])]
    bull_nn = [e for e in nn if e["signal"] == "bullish"]
    bear_nn = [e for e in nn if e["signal"] == "bearish"]
    nn_pct  = len(nn) / total
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
        "total":             total,
        "non_neutral_count": len(nn),
        "non_neutral_pct":   round(nn_pct, 3),
        "bull_count":        len(bull_nn),
        "bear_count":        len(bear_nn),
        "bull_breadth":      round(bull_brd, 3),
        "conviction":        conv,
    }


def _fit_lognormal_iv(
    pts: List[Tuple[float, float]],
    S0: float,
    horizon_days: float,
    depths: Optional[List[float]] = None,
) -> Optional[float]:
    """
    Fit annualised lognormal implied volatility to (price, survival_prob) pairs.

    Model: S(x) = 1 - Phi[ (ln(x/S0) + 0.5*sigma^2*T) / (sigma*sqrt(T)) ]

    When depths are provided, each point is weighted by sqrt(depth/max_depth)
    so that liquid markets (deep OB) constrain the fit more than thin ones.
    """
    if not _SCIPY_IV or len(pts) < 3 or S0 <= 0 or horizon_days <= 0:
        return None
    T         = horizon_days / 365.0
    prices    = np.array([p[0] for p in pts], dtype=float)
    survivals = np.clip([p[1] for p in pts], 0.02, 0.98)

    # Depth-derived sigma (measurement uncertainty): shallower = higher uncertainty
    sigma_w = None
    if depths and len(depths) == len(pts):
        max_d = max(depths) or 1.0
        # sigma[i] proportional to 1/sqrt(depth_i/max_d) — deeper = tighter constraint
        raw_w = np.array([max(d, 1.0) / max_d for d in depths])
        sigma_w = 1.0 / np.sqrt(np.clip(raw_w, 1e-3, 1.0))
        sigma_w = (sigma_w / sigma_w.mean()).tolist()  # normalise

    def model(x, sigma):
        if sigma <= 1e-4:
            return np.full_like(x, 0.5)
        sqrtT = np.sqrt(T)
        z = (np.log(x / S0) + 0.5 * sigma ** 2 * T) / (sigma * sqrtT)
        return 1.0 - _sp_norm.cdf(z)

    try:
        kwargs = {"sigma": sigma_w, "absolute_sigma": True} if sigma_w is not None else {}
        popt, _ = _sp_curve_fit(
            model, prices, survivals, p0=[0.6],
            bounds=(0.01, 10.0), maxfev=2000, **kwargs
        )
        sigma = float(popt[0])
        return round(sigma, 4) if 0.01 <= sigma <= 10.0 else None
    except Exception:
        return None


def _build_date_grouped_surfaces(
    all_enriched: List[dict],
    current_price: Optional[float],
) -> Dict[str, dict]:
    """
    Build implied price-range surfaces grouped by resolution date.

    Only strike-price markets within the informative probability range
    [SURFACE_MIN_PROB, SURFACE_MAX_PROB] = [3%, 97%] are included.
    Dates with fewer than 2 informative points are skipped.

    Returns: {resolution_date: {quantiles, iv, n_markets, position_signal, ...}}
    sorted by date ascending (nearest expiry first).
    """
    # Collect (price, surv, depth) per resolution date
    date_pts:    Dict[str, List[Tuple[float, float]]] = {}
    date_depths: Dict[str, List[float]]               = {}

    for e in all_enriched:
        pl  = e.get("price_level")
        ia  = e.get("is_above")
        yp  = e["yes_prob"]
        if pl is None or ia is None:
            continue
        # CRITICAL: skip near-certain outcomes
        if not (_SURFACE_MIN_PROB <= yp <= _SURFACE_MAX_PROB):
            continue
        surv     = yp if ia else (1.0 - yp)
        res_date = e.get("resolution_date") or e["bucket"]
        depth    = e.get("ob_depth", 0.0)

        if res_date not in date_pts:
            date_pts[res_date]    = []
            date_depths[res_date] = []
        date_pts[res_date].append((pl, surv))
        date_depths[res_date].append(depth)

    result = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for rdate in sorted(date_pts.keys()):
        pts    = date_pts[rdate]
        depths = date_depths[rdate]
        if len(pts) < 2:
            continue
        ranges = _build_price_ranges(pts)
        if not ranges:
            continue

        # Compute horizon in fractional days
        horizon_days = None
        try:
            rd = datetime.strptime(rdate, "%Y-%m-%d")
            diff = (rd - now).total_seconds() / 86400.0
            horizon_days = max(0.1, diff)
        except Exception:
            pass

        iv = None
        pos_sig = None
        if current_price and current_price > 0:
            iv      = _fit_lognormal_iv(pts, current_price,
                                        horizon_days or 7.0, depths)
            pos_sig = _price_position_signal(current_price, ranges)

        result[rdate] = {
            **ranges,
            "iv":              iv,
            "n_markets":       len(pts),
            "n_informative":   len(pts),   # explicit: these are all filtered
            "position_signal": pos_sig,
            "horizon_days":    horizon_days,
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
    Return a compact prompt-injectable string from the latest cached snapshot.
    Shows per-date probability surfaces if available.
    """
    path = Path(cache_dir) / symbol.upper() / "price_levels.json"
    if not path.exists():
        return ""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("no_directional_signal") and not d.get("date_surfaces"):
            return (f"NA — no non-neutral Polymarket markets found for "
                    f"{symbol.upper()} on {d.get('date', '')}.")
        lines = [f"Polymarket Price Ranges for {symbol.upper()} ({d.get('date', '')})"]

        # Date-grouped surfaces (primary output)
        date_surfs = d.get("date_surfaces", {})
        if date_surfs:
            lines.append("  Per-Date Probability Surfaces (informative range only):")
            for rdate, bl in sorted(date_surfs.items()):
                q50  = bl.get("q50")
                p50  = bl.get("p50_range", [None, None])
                iv   = bl.get("iv")
                pos  = bl.get("position_signal", "")
                nm   = bl.get("n_informative", 0)
                q50_s = f"${q50:,.0f}" if q50 else "N/A"
                ci_s  = (f"${p50[0]:,.0f}-${p50[1]:,.0f}"
                         if p50[0] and p50[1] else "N/A")
                iv_s  = f"  IV={iv:.0%}" if iv else ""
                pos_s = pos.split(" —")[0][:25] if pos else ""
                lines.append(
                    f"    [{rdate}] P50={q50_s}  50%CI=[{ci_s}]{iv_s}  "
                    f"{nm} markets  {pos_s}"
                )

        if d.get("current_price"):
            lines.append(f"  Spot: ${d['current_price']:,.2f}")
        bp = d.get("bull_probability")
        if bp is not None:
            lines.append(f"  Directional bias: Bull {bp:.0%} / Bear {1-bp:.0%}")
        brd = d.get("breadth", {})
        if brd.get("conviction"):
            lines.append(f"  Conviction: {brd['conviction']}")
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
    Fetch Polymarket markets and build an implied probability surface using
    only informative outcomes (3%–97% YES probability).  Markets are grouped
    by their resolution date to produce per-expiry price range tables with
    lognormal implied volatility.  First-to-hit markets are parsed for
    directional skew.  All other v3 features (velocity, conviction, breadth)
    are preserved.
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
        end_str = m.get("endDate") or m.get("end_date", "")
        hours   = _hours_to_expiry(end_str)
        days    = hours / 24.0
        if days > _SHORT_TERM_DAYS:
            continue
        m["_relevance"] = score
        m["_hours"]     = hours
        m["_bucket"]    = _classify_bucket(hours)
        m["_end_str"]   = end_str
        scored.append(m)

    if not scored:
        return (f"NA — no live Polymarket markets with a clear causal relationship to "
                f"{symbol_upper} were found across Crypto / Finance / Economy / Trending.")

    scored.sort(key=lambda m: (
        -_urgency(m["_hours"]),
        -m["_relevance"],
        -float(m.get("volume", 0) or 0),
    ))

    # ── 3. Load previous snapshot for velocity ────────────────────────────────
    prev_ts, prev_probs = _load_prev_snapshot(cache_dir, symbol_upper)

    # ── 4. Enrich markets ─────────────────────────────────────────────────────
    all_enriched:       List[dict]               = []
    # Global surface uses only informative-range points
    price_surface_pts:  List[Tuple[float, float]] = []
    directional:        List[dict]               = []
    first_to_hit_list:  List[dict]               = []

    for m in scored[:25]:
        tokens         = m.get("tokens") or []
        outcome_prices = m.get("outcomePrices") or []
        hours          = m["_hours"]
        bucket         = m["_bucket"]
        end_str        = m["_end_str"]

        # Resolve YES probability
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

        # OB enrichment
        ob          = None
        ob_mid      = None
        conviction  = 1.0
        depth_val   = 0.0
        if yes_token_id:
            ob = _fetch_order_book(yes_token_id)
            if ob and ob.get("weighted_bid") and ob.get("weighted_ask"):
                ob_mid   = round((ob["weighted_bid"] + ob["weighted_ask"]) / 2, 4)
                yes_prob = ob_mid
            conviction = _ob_conviction(ob)
            depth_val  = _ob_depth(ob)
            time.sleep(0.05)

        q              = m.get("question", "")
        signal, bull_p = _derive_signal(q, yes_prob)
        volume         = float(m.get("volume", 0) or 0)
        urgency_val    = _urgency(hours)
        price_lvl      = _extract_price_level(q)
        is_above       = _is_above_market(q)
        horizon_str    = _parse_time_horizon(hours)
        res_date       = _parse_resolution_date(q, end_str)

        entry = {
            "question":        q,
            "yes_prob":        round(yes_prob, 3),
            "signal":          signal,
            "bull_prob":       round(bull_p, 3),
            "volume":          volume,
            "hours":           hours,
            "bucket":          bucket,
            "horizon":         horizon_str,
            "end_date":        end_str,
            "ob_mid":          ob_mid,
            "conviction":      conviction,
            "urgency":         urgency_val,
            "price_level":     price_lvl,
            "is_above":        is_above,
            "resolution_date": res_date,
            "ob_depth":        depth_val,
            "relevance":       m["_relevance"],
        }
        all_enriched.append(entry)

        # ── Global surface: INFORMATIVE RANGE ONLY ────────────────────────────
        if price_lvl is not None and is_above is not None:
            if _SURFACE_MIN_PROB <= yes_prob <= _SURFACE_MAX_PROB:
                surv = yes_prob if is_above else (1.0 - yes_prob)
                price_surface_pts.append((price_lvl, surv))

        # ── First-to-hit markets ───────────────────────────────────────────────
        fth = _parse_first_to_hit(q, yes_prob, current_price)
        if fth:
            first_to_hit_list.append({"question": q[:80], **fth, "volume": volume})
            # Add approximate surface points if current price is between levels
            for sp in fth["surface_pts"]:
                price_surface_pts.append(sp)

        # Directional filter
        if _is_nonneutral(yes_prob):
            directional.append(entry)

    # ── 5. Probability velocity ───────────────────────────────────────────────
    velocity_map = _compute_velocity(prev_ts, prev_probs, all_enriched)

    # ── 6. Per-date probability surfaces ─────────────────────────────────────
    date_surfaces = _build_date_grouped_surfaces(all_enriched, current_price)
    # Inject first-to-hit approximate surface points for dates we found
    for fth in first_to_hit_list:
        for sp in fth.get("surface_pts", []):
            # Assign to their resolution date if known
            pass   # already added to price_surface_pts above

    # ── 7. Urgency × conviction weighted aggregate ────────────────────────────
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

    # ── 9. Global ranges (union of all informative surface points) ─────────────
    global_ranges   = _build_price_ranges(price_surface_pts) if price_surface_pts else None
    position_signal = None
    if global_ranges and current_price and current_price > 0:
        position_signal = _price_position_signal(current_price, global_ranges)

    # ── 10. Price level magnets ────────────────────────────────────────────────
    magnets = _price_level_magnets(price_surface_pts, current_price)

    # ── 11. Save cache ────────────────────────────────────────────────────────
    cache_data = {
        "symbol":               symbol_upper,
        "date":                 curr_date,
        "ts":                   datetime.now(timezone.utc).isoformat(),
        "current_price":        current_price,
        "bull_probability":     agg_bull_p,
        "bear_probability":     agg_bear_p,
        "no_directional_signal": no_directional_signal,
        "position_signal":      position_signal,
        "ranges":               global_ranges or {},
        "date_surfaces":        date_surfaces,
        "breadth":              breadth,
        "magnets":              magnets,
        "surface_points":       [{"price": p, "survival": s}
                                  for p, s in sorted(price_surface_pts)],
        "surface_filter":       f"[{_SURFACE_MIN_PROB:.0%}, {_SURFACE_MAX_PROB:.0%}]",
        "directional_markets":  len(directional),
        "market_snapshots":     [
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
            f"{symbol_upper}."
        )
    else:
        bias_tag = ("Bullish" if agg_bull_p > 0.55 else
                    ("Bearish" if agg_bull_p < 0.45 else "Neutral"))
        bias_line = (
            f"**Directional Bias (urgency x conviction weighted):** {bias_tag}  |  "
            f"Bull: **{agg_bull_p:.0%}**  Bear: **{agg_bear_p:.0%}**"
        )

    conv_str    = breadth["conviction"].upper()
    breadth_line = (
        f"**Consensus Breadth:** {breadth['non_neutral_count']}/{breadth['total']} "
        f"markets non-neutral ({breadth['non_neutral_pct']:.0%})  —  "
        f"{breadth['bull_count']} bullish / {breadth['bear_count']} bearish  —  "
        f"**{conv_str}** conviction"
    )

    lines = [
        f"## {symbol_upper} Polymarket Prediction Market Signals\n",
        bias_line + "\n",
        breadth_line + "\n",
    ]

    # Probability velocity
    if velocity_map:
        elapsed_h = ((datetime.now(timezone.utc) - prev_ts).total_seconds() / 3600.0
                     if prev_ts else 0.0)
        lines += [
            f"### Probability Velocity (last {elapsed_h:.1f}h)\n",
            "| Market | Current | Change/h | Direction | Bucket |",
            "|--------|---------|----------|-----------|--------|",
        ]
        for q_text, vel in sorted(velocity_map.items(), key=lambda x: -abs(x[1]))[:8]:
            entry = next((e for e in all_enriched if e["question"] == q_text), None)
            if not entry:
                continue
            q_s = q_text[:60] + ("..." if len(q_text) > 60 else "")
            lines.append(
                f"| {q_s} | {entry['yes_prob']:.0%} | {vel:+.1%}/h | "
                f"{'RISING' if vel > 0 else 'FALLING'} | {entry['bucket']} |"
            )
        lines.append("")

    # Per-date probability surfaces — the primary output
    if date_surfaces:
        n_filtered_out = sum(
            1 for e in all_enriched
            if e.get("price_level") and e.get("is_above") is not None
            and not (_SURFACE_MIN_PROB <= e["yes_prob"] <= _SURFACE_MAX_PROB)
        )
        lines += [
            f"\n### Implied Probability Surfaces — by Resolution Date\n",
            f"*(Only informative strikes [{_SURFACE_MIN_PROB:.0%}–{_SURFACE_MAX_PROB:.0%}] "
            f"used. {n_filtered_out} near-certain outcomes excluded.)*\n",
            "| Expiry | N | P10 | P25 | P50 | P75 | P90 | 50% CI | vs Spot | Ann. IV |",
            "|--------|---|-----|-----|-----|-----|-----|--------|---------|---------|",
        ]
        for rdate, bl in sorted(date_surfaces.items()):
            q10  = bl.get("q10")
            q25  = bl.get("q25")
            q50  = bl.get("q50")
            q75  = bl.get("q75")
            q90  = bl.get("q90")
            iv   = bl.get("iv")
            pos  = bl.get("position_signal", "—")
            nm   = bl.get("n_informative", 0)
            def _fs(v): return f"${v:,.0f}" if v else "—"
            ci50 = f"{_fs(q25)}–{_fs(q75)}"
            pos_s = pos.split(" —")[0][:15] if pos else "—"
            iv_s  = f"{iv:.0%}" if iv else "—"
            lines.append(
                f"| {rdate} | {nm} | {_fs(q10)} | {_fs(q25)} | {_fs(q50)} | "
                f"{_fs(q75)} | {_fs(q90)} | {ci50} | {pos_s} | {iv_s} |"
            )
        lines.append("")

        # Detail table: informative surface points per date
        lines.append("**Survival function surface (informative range only):**\n")
        for rdate, bl in sorted(date_surfaces.items()):
            pts = bl.get("surface_points", [])
            if not pts:
                continue
            lines.append(f"*{rdate}:*")
            lines.append("| Strike | P(price > strike) |")
            lines.append("|--------|------------------|")
            for price, surv in sorted(pts):
                lines.append(f"| ${price:,.0f} | {surv:.0%} |")
            lines.append("")

    # First-to-hit markets
    if first_to_hit_list:
        lines += [
            "\n### First-to-Hit Markets\n",
            "| Question | Lo level | Hi level | P(lo first) | Signal | Vol |",
            "|----------|----------|----------|-------------|--------|-----|",
        ]
        for fth in sorted(first_to_hit_list, key=lambda x: -x["volume"])[:6]:
            vol_s = f"${fth['volume']:,.0f}" if fth["volume"] > 0 else "—"
            lines.append(
                f"| {fth['question']} | ${fth['lo']:,.0f} | ${fth['hi']:,.0f} | "
                f"{fth['p_lo_first']:.0%} | {fth['signal'].upper()} | {vol_s} |"
            )
        lines.append("")

    # Price level magnets
    hot_magnets = [mg for mg in magnets if mg["count"] >= 2]
    if hot_magnets:
        lines += [
            "\n### Price Level Magnets (multi-market references)\n",
            "| Level | Markets | Avg P(>level) | Distance |",
            "|-------|---------|---------------|----------|",
        ]
        for mg in hot_magnets[:8]:
            lines.append(
                f"| ${mg['level']:,.0f} | {mg['count']} | "
                f"{mg['avg_survival']:.0%} | {mg['label'] or '—'} |"
            )
        lines.append("")

    # Non-neutral directional markets by bucket
    if directional:
        lines.append("\n### Non-Neutral Directional Markets by Bucket\n")
        bucket_label = {
            _BUCKET_INTRADAY:  "intraday  (<6h)",
            _BUCKET_OVERNIGHT: "overnight (6-24h)",
            _BUCKET_SHORT:     "short     (1-3d)",
            _BUCKET_WEEKLY:    "weekly    (3-7d)",
            _BUCKET_MEDIUM:    "medium    (7-30d)",
        }
        for bname in _BUCKET_ORDER:
            bd = [e for e in directional if e["bucket"] == bname]
            if not bd:
                continue
            lines.append(f"**[{bucket_label[bname]}]**")
            lines.append("| Question | YES% | Signal | ETA | Vol |")
            lines.append("|----------|------|--------|-----|-----|")
            for e in sorted(bd, key=lambda x: -x["volume"])[:6]:
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
        f"Probability surface built from informative range "
        f"[{_SURFACE_MIN_PROB:.0%}–{_SURFACE_MAX_PROB:.0%}] only, "
        f"grouped by resolution date. "
        f"Depth-weighted lognormal IV fitted per expiry.*",
    ]
    return "\n".join(lines)


# ── Cross-asset coherence ─────────────────────────────────────────────────────

def get_cross_asset_coherence(
    symbols: List[str],
    curr_date: str,
    cache_dir: str = "./data/polymarket_cache",
) -> str:
    """
    Compare latest Polymarket directional signals and probability velocities
    across multiple symbols using saved JSONL snapshots (no live API calls).
    """
    snapshots: List[dict] = []
    for sym in symbols:
        path = Path(cache_dir) / sym.upper() / "signals.jsonl"
        if not path.exists():
            continue
        try:
            lines  = path.read_text(encoding="utf-8").strip().split("\n")
            latest = prev = None
            for raw in reversed(lines):
                try:
                    dd = json.loads(raw)
                    if latest is None:
                        latest = dd
                    elif prev is None:
                        prev = dd
                        break
                except Exception:
                    continue
            if latest is None:
                continue
            vel = None
            if prev is not None:
                try:
                    ts_now  = datetime.fromisoformat(latest["ts"].replace("Z", "+00:00"))
                    ts_prev = datetime.fromisoformat(prev["ts"].replace("Z", "+00:00"))
                    elapsed = (ts_now - ts_prev).total_seconds() / 3600.0
                    bp_now  = latest.get("bull_probability")
                    bp_prev = prev.get("bull_probability")
                    if elapsed > 0.1 and bp_now is not None and bp_prev is not None:
                        vel = round((bp_now - bp_prev) / elapsed, 4)
                except Exception:
                    pass
            snapshots.append({
                "symbol":   sym.upper(),
                "bull_prob": latest.get("bull_probability"),
                "no_signal": latest.get("no_directional_signal", True),
                "position":  latest.get("position_signal", ""),
                "breadth":   latest.get("breadth", {}),
                "ts":        latest.get("ts", ""),
                "velocity":  vel,
            })
        except Exception:
            continue

    if not snapshots:
        return (f"NA — no Polymarket snapshots found for {', '.join(s.upper() for s in symbols)}. "
                "Run get_polymarket_sentiment for each symbol first.")

    bullish_syms = [s for s in snapshots
                    if not s["no_signal"] and s["bull_prob"] and s["bull_prob"] > 0.55]
    bearish_syms = [s for s in snapshots
                    if not s["no_signal"] and s["bull_prob"] and s["bull_prob"] < 0.45]
    n_signal = len(bullish_syms) + len(bearish_syms)

    if n_signal == 0:
        regime = "NEUTRAL — no directional signal across tracked assets"
    elif len(bullish_syms) >= 0.60 * n_signal:
        regime = f"RISK-ON — {len(bullish_syms)}/{n_signal} signalling assets BULLISH"
    elif len(bearish_syms) >= 0.60 * n_signal:
        regime = f"RISK-OFF — {len(bearish_syms)}/{n_signal} signalling assets BEARISH"
    else:
        regime = (f"MIXED / IDIOSYNCRATIC — "
                  f"{len(bullish_syms)} bullish / {len(bearish_syms)} bearish")

    rising  = [s for s in snapshots if s["velocity"] and s["velocity"] >  _MIN_VELOCITY_PH]
    falling = [s for s in snapshots if s["velocity"] and s["velocity"] < -_MIN_VELOCITY_PH]

    lines = [
        f"## Cross-Asset Polymarket Coherence ({curr_date})\n",
        f"**Macro Regime:** {regime}\n",
        f"Assets: {len(snapshots)}  |  Signal: {n_signal}  |  "
        f"Bull: {len(bullish_syms)}  Bear: {len(bearish_syms)}\n",
        "\n| Symbol | Bull % | Direction | Conviction | Velocity/h | Position |",
        "|--------|--------|-----------|------------|------------|----------|",
    ]
    for s in sorted(snapshots, key=lambda x: -(x["bull_prob"] or 0.5)):
        bp   = s["bull_prob"]
        bp_s = f"{bp:.0%}" if bp is not None else "N/A"
        dir_s = ("BULL" if bp and bp > 0.55 else ("BEAR" if bp and bp < 0.45 else "NEUTRAL"))
        conv  = s["breadth"].get("conviction", "—") if s["breadth"] else "—"
        vel   = s["velocity"]
        vel_s = f"{vel:+.2%}/h" if vel is not None else "—"
        pos   = (s["position"] or "").split(" —")[0][:25] if s["position"] else "—"
        lines.append(f"| {s['symbol']} | {bp_s} | {dir_s} | {conv} | {vel_s} | {pos} |")

    if rising or falling:
        lines.append("\n**Fast-moving signals:**")
        for s in rising:
            lines.append(f"- {s['symbol']}: rising {s['velocity']:+.2%}/h")
        for s in falling:
            lines.append(f"- {s['symbol']}: falling {s['velocity']:+.2%}/h")

    lines.append(f"\n*From cached signals.jsonl — no live API calls.*")
    return "\n".join(lines)
