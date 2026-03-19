"""Polymarket prediction-market data utilities — enhanced edition.

Improvements over v1:
  • Short-term focus: prioritises markets expiring within 30 days.
  • Non-neutral filtering: only surfaces directional markets (YES prob
    outside 0.35–0.65) for the bull/bear aggregate.
  • Probability surface: when multiple "above/below $X" price-level markets
    exist for the same asset, the probabilities are treated as points on
    the survival function S(x) = P(price > x), and linear interpolation
    derives the implied price distribution:
        — P50 range  (25th–75th percentile, 50% confidence interval)
        — P90 range  (5th–95th percentile,  90% confidence interval)
        — Median expected price (50th percentile)
  • Current-price comparison: the current spot/close price is compared to
    the expected range to derive a directional signal.
  • Published to agents: price-range data is cached to disk as JSON and
    returned as a compact structured string for other agents to use.

Public endpoints (no API key required):
  Gamma API : https://gamma-api.polymarket.com/markets
  CLOB API  : https://clob.polymarket.com/book?token_id={token_id}
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# ── API constants ─────────────────────────────────────────────────────────────
_GAMMA   = "https://gamma-api.polymarket.com"
_CLOB    = "https://clob.polymarket.com"
_TIMEOUT = 15

_CATEGORIES = ["Crypto", "Finance", "Economy", "Trending"]

# Short-term threshold: only include markets expiring within this many days
_SHORT_TERM_DAYS = 30

# Non-neutral threshold: only include in directional aggregate if outside
# this range (i.e. the crowd has a clear view)
_NEUTRAL_BAND = (0.35, 0.65)

# ── Symbol → search terms ─────────────────────────────────────────────────────
_SYMBOL_TERMS: Dict[str, List[str]] = {
    "BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "eth"],
    "SOL": ["solana", "sol"],  "BNB": ["bnb", "binance"],
    "XRP": ["xrp", "ripple"], "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"], "AVAX": ["avalanche", "avax"],
    "LINK": ["chainlink", "link"], "DOT": ["polkadot", "dot"],
    "SUI": ["sui"], "INJ": ["injective", "inj"],
    "ARB": ["arbitrum", "arb"], "OP": ["optimism", "op"],
    "MORPHO": ["morpho"], "SONIC": ["sonic"], "MON": ["monad", "mon"],
    "GOLD": ["gold", "xauusd", "gold price"], "SILVER": ["silver", "xagusd"],
    "OIL": ["oil price", "crude oil", "wti", "brent"],
    "SPX": ["s&p 500", "sp500", "spx"], "NDX": ["nasdaq", "ndx"],
    "QQQ": ["nasdaq", "qqq"], "SPY": ["s&p 500", "spy etf"],
    "EWY": ["south korea", "kospi", "korean"],
    "EWZ": ["brazil", "bovespa"], "TLT": ["treasury", "tlt", "10-year bond"],
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


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _parse_time_horizon(days: int) -> str:
    if days <= 0:   return "expired"
    if days <= 1:   return "intraday"
    if days <= 7:   return f"{days}d"
    if days <= 30:  return f"{days // 7}w"
    if days <= 365: return f"{days // 30}mo"
    return f"{days // 365}y"


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


# ── Probability surface ───────────────────────────────────────────────────────

_PRICE_PATTERNS = [
    re.compile(r'\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)'),   # $90,000
    re.compile(r'([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:dollars?|usd)', re.I),
    re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*[kK]\b'),                  # 90k
]


def _extract_price_level(question: str) -> Optional[float]:
    """Extract a dollar price level from a market question string."""
    q = question.lower()
    # Try explicit dollar patterns first
    for pat in _PRICE_PATTERNS[:2]:
        m = pat.search(question)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    # Try "Xk" notation
    m = _PRICE_PATTERNS[2].search(q)
    if m:
        try:
            return float(m.group(1)) * 1000
        except ValueError:
            pass
    return None


def _is_above_market(question: str) -> Optional[bool]:
    """
    Return True  if YES outcome means price is ABOVE the level,
           False if YES outcome means price is BELOW the level,
           None  if ambiguous.
    """
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
    """
    Linear interpolation: find the price x where S(x) ≈ target_s.
    survivals[i] = P(price > prices[i])  — must be DECREASING with price.
    """
    n = len(prices)
    # Scan for the bracket where target_s lies
    for i in range(n - 1):
        s_hi, s_lo = survivals[i], survivals[i + 1]
        p_lo, p_hi = prices[i],    prices[i + 1]
        if s_lo <= target_s <= s_hi:
            if s_hi == s_lo:
                return (p_lo + p_hi) / 2.0
            t = (s_hi - target_s) / (s_hi - s_lo)   # 0 → p_lo, 1 → p_hi
            return p_lo + t * (p_hi - p_lo)
    # Extrapolate below lowest known price
    if target_s > survivals[0] and n >= 2:
        dp = prices[1] - prices[0]
        ds = survivals[0] - survivals[1]
        if ds > 0:
            return prices[0] - (target_s - survivals[0]) / ds * dp
        return prices[0] * 0.85
    # Extrapolate above highest known price
    if target_s < survivals[-1] and n >= 2:
        dp = prices[-1] - prices[-2]
        ds = survivals[-2] - survivals[-1]
        if ds > 0:
            return prices[-1] + (survivals[-1] - target_s) / ds * dp
        return prices[-1] * 1.15
    return None


def _build_price_ranges(price_points: List[Tuple[float, float]]) -> Optional[dict]:
    """
    Build quantile estimates from (price, survival_probability) pairs.

    Args:
        price_points: [(price, P(price > threshold)), ...] — may be unsorted.

    Returns:
        dict with keys: q10, q25, q50, q75, q90, p50_range, p90_range
        or None if insufficient data.
    """
    if len(price_points) < 2:
        return None
    # Sort by price ascending → survival decreasing
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
        "p50_range": [q.get("q25"), q.get("q75")],
        "p90_range": [q.get("q10"), q.get("q90")],
        "surface_points": pts,
    }


def _price_position_signal(current: float, ranges: dict) -> str:
    q10 = ranges.get("q10")
    q25 = ranges.get("q25")
    q50 = ranges.get("q50")
    q75 = ranges.get("q75")
    q90 = ranges.get("q90")
    if q10 and current < q10:
        return "STRONGLY BEARISH — below 90% CI lower bound"
    if q25 and current < q25:
        return "BEARISH — below 50% CI lower bound"
    if q75 and current > q75:
        return "BULLISH — above 50% CI upper bound"
    if q90 and current > q90:
        return "STRONGLY BULLISH — above 90% CI upper bound"
    return "NEUTRAL — within 50% confidence interval"


# ── Price-levels cache (for publishing to other agents) ───────────────────────

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
    """
    path = Path(cache_dir) / symbol.upper() / "price_levels.json"
    if not path.exists():
        return ""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("no_directional_signal") and not d.get("ranges"):
            return (f"NA — no non-neutral Polymarket markets found for "
                    f"{symbol.upper()} on {d.get('date','')}.")
        lines = [f"Polymarket Price Ranges for {symbol.upper()} ({d.get('date','')})"]
        r = d.get("ranges", {})
        if r.get("q50"):
            lines.append(f"  Median expected: ${r['q50']:,.0f}")
        p50 = r.get("p50_range", [None, None])
        p90 = r.get("p90_range", [None, None])
        if p50[0] and p50[1]:
            lines.append(f"  50% CI: ${p50[0]:,.0f} – ${p50[1]:,.0f}")
        if p90[0] and p90[1]:
            lines.append(f"  90% CI: ${p90[0]:,.0f} – ${p90[1]:,.0f}")
        if d.get("current_price"):
            lines.append(f"  Current price: ${d['current_price']:,.2f}")
        if d.get("position_signal"):
            lines.append(f"  Signal vs range: {d['position_signal']}")
        bp = d.get("bull_probability")
        if bp is not None:
            lines.append(f"  Overall bull probability (non-neutral markets): {bp:.0%}")
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
    Fetch live Polymarket markets, focusing on short-term (≤30d) markets
    with non-neutral expectations.  Builds a probability surface from
    price-level markets to derive 50% and 90% confidence price ranges.
    Compares current price to the expected range.
    Caches structured price-level data for other agents to consume.

    Returns:
        Formatted Markdown report string.
    """
    symbol_upper = symbol.upper()

    # ── 1. Fetch markets across all categories ────────────────────────────────
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

    # ── 2. Score relevance and compute days-to-expiry ─────────────────────────
    scored = []
    for m in all_markets:
        q     = m.get("question", "") or ""
        score = _compute_relevance(q, symbol_upper)
        if score < 0.5:
            continue
        days = _days_to_expiry(m.get("endDate") or m.get("end_date", ""))
        m["_relevance"] = score
        m["_days"]      = days
        scored.append(m)

    if not scored:
        return (f"NA — no live Polymarket markets with a clear causal relationship to "
                f"{symbol_upper} were found across Crypto / Finance / Economy / Trending.")

    # Sort: short-term first, then by relevance, then by volume
    scored.sort(key=lambda m: (
        m["_days"] > _SHORT_TERM_DAYS,
        -m["_relevance"],
        -float(m.get("volume", 0) or 0),
    ))

    # ── 3. Enrich with OB, extract YES prob, classify each market ─────────────
    price_surface_pts: List[Tuple[float, float]] = []   # (price, survival_prob)
    directional: List[dict] = []    # non-price or non-neutral price markets
    all_enriched: List[dict] = []

    for m in scored[:20]:
        tokens        = m.get("tokens") or []
        outcome_prices = m.get("outcomePrices") or []
        days          = m["_days"]

        # Get YES probability
        yes_prob    = None
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
        ob_mid = None
        if yes_token_id:
            ob = _fetch_order_book(yes_token_id)
            if ob and ob.get("weighted_bid") and ob.get("weighted_ask"):
                ob_mid   = round((ob["weighted_bid"] + ob["weighted_ask"]) / 2, 4)
                yes_prob = ob_mid
            time.sleep(0.05)

        q         = m.get("question", "")
        signal, bull_p = _derive_signal(q, yes_prob)
        horizon   = _parse_time_horizon(days)
        volume    = float(m.get("volume", 0) or 0)

        entry = {
            "question": q,
            "yes_prob": round(yes_prob, 3),
            "signal":   signal,
            "bull_prob": round(bull_p, 3),
            "volume":   volume,
            "days":     days,
            "horizon":  horizon,
            "end_date": m.get("endDate") or m.get("end_date", ""),
            "ob_mid":   ob_mid,
            "relevance": m["_relevance"],
        }
        all_enriched.append(entry)

        # ── Probability surface: price-level markets ──────────────────────────
        price_lvl = _extract_price_level(q)
        is_above  = _is_above_market(q)
        if price_lvl is not None and is_above is not None and days <= _SHORT_TERM_DAYS:
            # Convert to survival probability: P(price > level)
            surv = yes_prob if is_above else (1.0 - yes_prob)
            price_surface_pts.append((price_lvl, surv))

        # ── Directional (non-neutral, short-term) ─────────────────────────────
        if days <= _SHORT_TERM_DAYS and _is_nonneutral(yes_prob):
            directional.append(entry)

    # ── 4. Build probability surface and estimate ranges ──────────────────────
    ranges = None
    if price_surface_pts:
        ranges = _build_price_ranges(price_surface_pts)

    # ── 5. Position signal vs current price ───────────────────────────────────
    position_signal = None
    if ranges and current_price and current_price > 0:
        position_signal = _price_position_signal(current_price, ranges)

    # ── 6. Aggregate bull/bear — only from non-neutral short-term markets ──────
    # If no directional signal exists, we do NOT fabricate a 50/50 neutral.
    no_directional_signal = False
    if directional:
        total_vol  = sum(e["volume"] for e in directional if e["volume"] > 0) or 1.0
        agg_bull_p = sum(
            e["bull_prob"] * (e["volume"] / total_vol)
            for e in directional if e["volume"] > 0
        )
        agg_bull_p = round(max(0.0, min(1.0, agg_bull_p)), 3)
        agg_bear_p = round(1.0 - agg_bull_p, 3)
    else:
        # No non-neutral markets found — directional signal is genuinely absent
        no_directional_signal = True
        agg_bull_p = agg_bear_p = None

    # ── 7. Save structured price-level cache for other agents ─────────────────
    cache_data = {
        "symbol":              symbol_upper,
        "date":                curr_date,
        "ts":                  datetime.now(timezone.utc).isoformat(),
        "current_price":       current_price,
        "bull_probability":    agg_bull_p,
        "bear_probability":    agg_bear_p,
        "no_directional_signal": no_directional_signal,
        "position_signal":     position_signal,
        "ranges":              ranges or {},
        "surface_points":      [{"price": p, "survival": s}
                                 for p, s in sorted(price_surface_pts)],
        "directional_markets": len(directional),
    }
    _save_price_levels(cache_dir, symbol_upper, cache_data)

    # ── 8. Append signal log ───────────────────────────────────────────────────
    log_dir  = Path(cache_dir) / symbol_upper
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "signals.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(cache_data, default=str) + "\n")

    # ── 9. Format Markdown report ─────────────────────────────────────────────
    if no_directional_signal:
        bias_line = (
            f"**Directional bias:** NA — no non-neutral short-term (≤{_SHORT_TERM_DAYS}d) "
            "markets found; cannot derive a bull/bear signal from Polymarket."
        )
    else:
        bias = "Bullish" if agg_bull_p > 0.55 else ("Bearish" if agg_bull_p < 0.45 else "Neutral")
        bias_line = (
            f"**Directional bias (non-neutral, ≤{_SHORT_TERM_DAYS}d markets):** {bias}  |  "
            f"Bull: **{agg_bull_p:.0%}**  |  Bear: **{agg_bear_p:.0%}**"
        )

    lines = [
        f"## {symbol_upper} Polymarket Prediction Market Signals\n",
        bias_line + "\n",
    ]

    # Probability surface section
    if ranges:
        q10 = ranges.get("q10"); q25 = ranges.get("q25")
        q50 = ranges.get("q50"); q75 = ranges.get("q75"); q90 = ranges.get("q90")
        lines += [
            "### Probability Surface — Implied Price Ranges\n",
            f"Built from **{len(price_surface_pts)} price-level markets** "
            f"(≤{_SHORT_TERM_DAYS}d horizon).\n",
            "| Confidence | Lower bound | Upper bound | Width |",
            "|------------|-------------|-------------|-------|",
        ]
        if q25 and q75:
            width50 = q75 - q25
            lines.append(f"| **50% CI** (P25–P75) | ${q25:,.0f} | ${q75:,.0f} | ${width50:,.0f} |")
        if q10 and q90:
            width90 = q90 - q10
            lines.append(f"| **90% CI** (P10–P90) | ${q10:,.0f} | ${q90:,.0f} | ${width90:,.0f} |")
        if q50:
            lines.append(f"\n**Median (P50) expected price:** ${q50:,.0f}\n")
        if current_price and position_signal:
            lines.append(f"**Current price:** ${current_price:,.2f}  →  **{position_signal}**\n")

        # Surface detail
        lines.append("\n*Probability surface (survival function S(x) = P(price > x)):*\n")
        lines.append("| Price level | P(price > level) | OB enriched |")
        lines.append("|-------------|-----------------|-------------|")
        for price, surv in sorted(price_surface_pts):
            ob_flag = "✓" if any(
                abs(e["yes_prob"] - surv) < 0.02 and e.get("ob_mid")
                for e in all_enriched
            ) else "—"
            lines.append(f"| ${price:,.0f} | {surv:.1%} | {ob_flag} |")
        lines.append("")

    # Non-neutral directional markets
    if directional:
        lines += [
            f"\n### Non-Neutral Directional Markets (≤{_SHORT_TERM_DAYS}d, outside 35–65%)\n",
            "| Question | YES prob | Signal | Horizon | Volume |",
            "|----------|----------|--------|---------|--------|",
        ]
        for e in sorted(directional, key=lambda x: -x["volume"])[:10]:
            q_short = e["question"][:65] + ("…" if len(e["question"]) > 65 else "")
            vol_str = f"${e['volume']:,.0f}" if e["volume"] > 0 else "—"
            lines.append(
                f"| {q_short} | {e['yes_prob']:.0%} | {e['signal'].upper()} "
                f"| {e['horizon']} | {vol_str} |"
            )

    lines += [
        "\n---\n",
        f"*{len(all_enriched)} markets analysed across Crypto / Finance / Economy / Trending. "
        f"Price ranges cached for downstream agents.*",
    ]
    return "\n".join(lines)
