"""Polymarket prediction-market data utilities.

Fetches live Polymarket markets across Crypto / Finance / Economy / Trending,
filters to those with a clear causal relationship to the asset being analysed,
derives a market-implied bull/bear probability with time horizon, optionally
enriches key markets with CLOB order-book data (weighted first 3 levels or
$1,000, whichever comes first), and appends a timestamped record to disk.

Public endpoints used (no API key required):
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
_GAMMA = "https://gamma-api.polymarket.com"
_CLOB  = "https://clob.polymarket.com"
_TIMEOUT = 15

# Categories to query (Polymarket category names)
_CATEGORIES = ["Crypto", "Finance", "Economy", "Trending"]

# ── Symbol → search terms ─────────────────────────────────────────────────────
_SYMBOL_TERMS: Dict[str, List[str]] = {
    # Major crypto
    "BTC":      ["bitcoin", "btc"],
    "ETH":      ["ethereum", "eth"],
    "SOL":      ["solana", "sol"],
    "BNB":      ["bnb", "binance"],
    "XRP":      ["xrp", "ripple"],
    "ADA":      ["cardano", "ada"],
    "DOGE":     ["dogecoin", "doge"],
    "AVAX":     ["avalanche", "avax"],
    "LINK":     ["chainlink", "link"],
    "DOT":      ["polkadot", "dot"],
    "MATIC":    ["polygon", "matic"],
    "SUI":      ["sui"],
    "INJ":      ["injective", "inj"],
    "ARB":      ["arbitrum", "arb"],
    "OP":       ["optimism", "op"],
    "MORPHO":   ["morpho"],
    "SONIC":    ["sonic"],
    "MON":      ["monad", "mon"],
    # TradFi commodities
    "GOLD":     ["gold", "xauusd", "gold price", "precious metal"],
    "SILVER":   ["silver", "xagusd", "silver price"],
    "OIL":      ["oil price", "crude oil", "wti", "brent", "petroleum"],
    "NATGAS":   ["natural gas", "natgas"],
    "COPPER":   ["copper"],
    "WHEAT":    ["wheat"],
    "CORN":     ["corn"],
    # US equity indices
    "SPX":      ["s&p 500", "sp500", "spx", "s&p500"],
    "ES":       ["s&p 500", "sp500"],
    "SPY":      ["s&p 500", "spy etf", "spdr"],
    "NDX":      ["nasdaq", "ndx", "nasdaq 100"],
    "QQQ":      ["nasdaq", "qqq", "tech stocks"],
    "DJI":      ["dow jones", "djia", "dow"],
    "RUT":      ["russell 2000", "small cap"],
    "IWM":      ["russell 2000", "iwm"],
    # Country ETFs
    "EWY":      ["south korea", "kospi", "korean"],
    "EWZ":      ["brazil", "bovespa", "ibovespa"],
    "EWJ":      ["japan", "nikkei", "topix"],
    "FXI":      ["china", "chinese stock", "csi", "hang seng"],
    "EEM":      ["emerging market"],
    # Fixed income
    "TLT":      ["treasury", "tlt", "10-year", "10 year bond", "us bond"],
    "HYG":      ["high yield", "junk bond"],
}

# Macro terms relevant to ALL crypto assets
_CRYPTO_MACRO: List[str] = [
    "federal reserve", "fed rate", "rate cut", "rate hike", "interest rate",
    "inflation", "cpi", "pce", "ppi", "recession", "us economy", "gdp",
    "crypto market", "cryptocurrency", "bitcoin etf", "crypto regulation",
    "sec crypto", "stablecoin", "tether", "usdt", "usdc",
]

# Macro terms relevant to equity / TradFi assets
_EQUITY_MACRO: List[str] = [
    "federal reserve", "fed rate", "interest rate", "inflation", "cpi",
    "gdp", "recession", "earnings season", "market crash", "stock market",
    "tariff", "trade war", "fiscal", "debt ceiling",
]

# ── Signal keyword heuristics ─────────────────────────────────────────────────
# If a market question contains these words, YES outcome = bullish
_BULLISH_WORDS = [
    "above", "over", "exceed", "surpass", "reach", "hit", "rally", "rise",
    "gain", "increase", "up", "high", "bull", "buy", "grow", "recover",
    "rate cut", "dovish", "easing", "stimulus", "ath", "all-time high",
]
# If a market question contains these words, YES outcome = bearish
_BEARISH_WORDS = [
    "below", "under", "fall", "drop", "crash", "decline", "decrease",
    "down", "low", "bear", "sell", "lose", "loss", "correction", "dump",
    "recession", "rate hike", "hawkish", "tightening", "bankruptcy",
    "liquidate", "collapse",
]


# ── Helper functions ──────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _get_symbol_terms(symbol: str) -> List[str]:
    s = symbol.upper()
    return _SYMBOL_TERMS.get(s, [s.lower()])


def _compute_relevance(question: str, symbol: str) -> float:
    """Return a 0–1 relevance score for a Polymarket market question."""
    q    = question.lower()
    s    = symbol.upper()
    terms = _get_symbol_terms(s)

    # Direct symbol / full-name match — highest score
    if any(t in q for t in terms):
        return 1.0

    # Crypto macro for crypto assets
    from tradingagents.dataflows.tradfi_utils import classify_symbol
    asset_type = classify_symbol(s)

    if asset_type == "crypto":
        if any(t in q for t in _CRYPTO_MACRO):
            return 0.65
    elif asset_type == "tradfi":
        if any(t in q for t in _EQUITY_MACRO):
            return 0.50
    return 0.0


def _derive_signal(question: str, yes_prob: float) -> Tuple[str, float]:
    """
    Return (signal_direction, bull_prob) for a binary YES/NO market.
    signal_direction: "bullish" | "bearish" | "neutral"
    bull_prob:        probability that the outcome is bullish (0–1)
    """
    q = question.lower()
    bull_hits = sum(1 for w in _BULLISH_WORDS if w in q)
    bear_hits  = sum(1 for w in _BEARISH_WORDS if w in q)

    if bull_hits > bear_hits:
        return "bullish", yes_prob          # YES → price goes up
    if bear_hits > bull_hits:
        return "bearish", 1.0 - yes_prob    # YES → price goes down → bull = 1-p
    return "neutral", 0.5


def _parse_time_horizon(end_date_str: str) -> str:
    """Return a human-readable time horizon from an ISO end-date string."""
    if not end_date_str:
        return "unknown"
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = (end - now).days
        if days <= 0:   return "expired"
        if days <= 1:   return "intraday"
        if days <= 7:   return f"{days}d"
        if days <= 30:  return f"{days // 7}w"
        if days <= 365: return f"{days // 30}mo"
        return f"{days // 365}y"
    except Exception:
        return "unknown"


def weighted_order_book_price(levels: List[dict], max_usd: float = 1000.0) -> Optional[float]:
    """
    Compute a volume-weighted price from CLOB order-book levels.
    Uses the first 3 price levels OR up to max_usd depth, whichever is smaller.

    Args:
        levels:  List of {"price": str, "size": str} dicts from the CLOB API.
        max_usd: Maximum cumulative dollar value to consume.

    Returns:
        Weighted average price (probability) or None.
    """
    total_value = 0.0
    total_size  = 0.0

    for level in levels[:3]:
        price = float(level.get("price", 0) or 0)
        size  = float(level.get("size",  0) or 0)
        if price <= 0 or size <= 0:
            continue
        level_usd = price * size
        if total_value + level_usd > max_usd:
            remaining   = max_usd - total_value
            partial_units = remaining / price
            total_size  += partial_units
            total_value += remaining
            break
        total_value += level_usd
        total_size  += size

    return round(total_value / total_size, 4) if total_size > 0 else None


def _fetch_order_book(token_id: str) -> Optional[dict]:
    """Fetch CLOB order book for a single outcome token."""
    data = _get(f"{_CLOB}/book", params={"token_id": token_id})
    if not data:
        return None
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    return {
        "bids": bids,
        "asks": asks,
        "weighted_bid": weighted_order_book_price(bids),
        "weighted_ask": weighted_order_book_price(asks),
    }


# ── Main public function ──────────────────────────────────────────────────────

def get_polymarket_sentiment(
    symbol: str,
    curr_date: str,
    cache_dir: str = "./data/polymarket_cache",
) -> str:
    """
    Fetch live Polymarket markets relevant to the asset, derive bull/bear
    market-implied probabilities, optionally enrich with order-book data,
    append a timestamped record to disk, and return a formatted Markdown report.

    Args:
        symbol:    Asset ticker (e.g. "BTC", "ETH", "GOLD", "SPX")
        curr_date: Analysis date in YYYY-MM-DD format
        cache_dir: Directory for the appended signal log files

    Returns:
        Formatted Markdown report.
    """
    symbol_upper = symbol.upper()

    # ── 1. Fetch markets across all four categories ───────────────────────────
    all_markets: List[dict] = []
    seen_ids: set = set()

    for cat in _CATEGORIES:
        data = _get(f"{_GAMMA}/markets", params={
            "active":     "true",
            "closed":     "false",
            "order":      "volume",
            "ascending":  "false",
            "limit":      100,
            "category":   cat,
        })
        if data and isinstance(data, list):
            markets_raw = data
        elif data and isinstance(data, dict):
            markets_raw = data.get("data") or data.get("markets") or []
        else:
            markets_raw = []

        for m in markets_raw:
            mid = m.get("id") or m.get("conditionId", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_markets.append(m)
        time.sleep(0.1)   # polite rate limiting

    if not all_markets:
        return (
            f"Polymarket: no live markets could be fetched. "
            "The API may be temporarily unavailable."
        )

    # ── 2. Filter and score by relevance ──────────────────────────────────────
    relevant: List[dict] = []
    for m in all_markets:
        q     = m.get("question", "") or ""
        score = _compute_relevance(q, symbol_upper)
        if score >= 0.5:
            m["_relevance"] = score
            relevant.append(m)

    if not relevant:
        return (
            f"No Polymarket markets with a clear causal relationship to "
            f"{symbol_upper} were found across Crypto / Finance / Economy / "
            f"Trending categories."
        )

    # Sort: direct match first, then by volume
    relevant.sort(key=lambda m: (-m["_relevance"], -float(m.get("volume", 0) or 0)))
    relevant = relevant[:15]   # cap at 15 most relevant

    # ── 3. Enrich with order-book data and derive signals ─────────────────────
    enriched: List[dict] = []
    for m in relevant:
        tokens       = m.get("tokens") or []
        outcome_prices = m.get("outcomePrices") or []
        outcomes      = m.get("outcomes") or ["Yes", "No"]

        # Find YES outcome
        yes_prob    = None
        yes_token_id = None
        for i, tok in enumerate(tokens):
            out = tok.get("outcome", "")
            if out.lower() == "yes":
                yes_token_id = tok.get("token_id") or tok.get("tokenId")
                if i < len(outcome_prices):
                    try:
                        yes_prob = float(outcome_prices[i])
                    except (ValueError, TypeError):
                        pass
                break
        # Fallback if no explicit Yes token
        if yes_prob is None and outcome_prices:
            try:
                yes_prob = float(outcome_prices[0])
            except (ValueError, TypeError):
                yes_prob = 0.5

        yes_prob = yes_prob if yes_prob is not None else 0.5

        # Order-book enrichment for YES token
        ob_mid = None
        if yes_token_id:
            ob = _fetch_order_book(yes_token_id)
            if ob and ob.get("weighted_bid") and ob.get("weighted_ask"):
                ob_mid = round(
                    (ob["weighted_bid"] + ob["weighted_ask"]) / 2, 4
                )
                # Use OB mid-price as a more accurate probability if available
                yes_prob = ob_mid
            time.sleep(0.05)

        signal, bull_p = _derive_signal(m.get("question", ""), yes_prob)
        horizon        = _parse_time_horizon(m.get("endDate") or m.get("end_date", ""))
        volume         = float(m.get("volume", 0) or 0)

        enriched.append({
            "question":   m.get("question", ""),
            "yes_prob":   round(yes_prob, 3),
            "signal":     signal,
            "bull_prob":  round(bull_p, 3),
            "volume":     volume,
            "horizon":    horizon,
            "end_date":   m.get("endDate") or m.get("end_date", ""),
            "ob_mid":     ob_mid,
            "relevance":  m["_relevance"],
        })

    # ── 4. Aggregate bull/bear probability (volume-weighted) ──────────────────
    total_vol   = sum(e["volume"] for e in enriched if e["volume"] > 0) or 1.0
    agg_bull_p  = sum(
        e["bull_prob"] * (e["volume"] / total_vol)
        for e in enriched if e["volume"] > 0
    )
    agg_bull_p  = round(max(0.0, min(1.0, agg_bull_p)), 3)
    agg_bear_p  = round(1.0 - agg_bull_p, 3)

    # Dominant time horizon (most common non-expired)
    horizons = [e["horizon"] for e in enriched if e["horizon"] not in ("expired", "unknown")]
    dominant_horizon = max(set(horizons), key=horizons.count) if horizons else "various"

    # ── 5. Append to disk log ─────────────────────────────────────────────────
    log_dir = Path(cache_dir) / symbol_upper
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "signals.jsonl"

    record = {
        "ts":             datetime.now(timezone.utc).isoformat(),
        "ticker":         symbol_upper,
        "analysis_date":  curr_date,
        "markets_found":  len(enriched),
        "bull_probability": agg_bull_p,
        "bear_probability": agg_bear_p,
        "dominant_horizon": dominant_horizon,
        "markets": [
            {k: v for k, v in e.items() if k != "relevance"}
            for e in enriched
        ],
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # ── 6. Format Markdown report ─────────────────────────────────────────────
    bias = "Bullish" if agg_bull_p > 0.55 else ("Bearish" if agg_bull_p < 0.45 else "Neutral")

    lines = [
        f"## {symbol_upper} Polymarket Prediction Market Signals\n",
        f"**Market-implied bias:** {bias}  |  "
        f"Bull probability: **{agg_bull_p:.0%}**  |  "
        f"Bear probability: **{agg_bear_p:.0%}**  |  "
        f"Dominant horizon: **{dominant_horizon}**\n",
        f"*{len(enriched)} markets analysed across Crypto / Finance / Economy / Trending*\n",
        "---\n",
        "| Market Question | YES prob | OB mid | Signal | Horizon | Volume |",
        "|-----------------|----------|--------|--------|---------|--------|",
    ]
    for e in enriched:
        ob_str  = f"{e['ob_mid']:.2%}" if e["ob_mid"] else "—"
        vol_str = f"${e['volume']:,.0f}" if e["volume"] > 0 else "—"
        q_short = e["question"][:70] + ("…" if len(e["question"]) > 70 else "")
        lines.append(
            f"| {q_short} | {e['yes_prob']:.2%} | {ob_str} "
            f"| {e['signal'].upper()} | {e['horizon']} | {vol_str} |"
        )

    lines += [
        "\n",
        "### Interpretation\n",
        f"- **Aggregate bull probability** ({agg_bull_p:.0%}) is derived from the "
        "volume-weighted YES probabilities of all relevant markets, directionally "
        "adjusted so that bearish-outcome markets (e.g. 'Will BTC fall below $X?') "
        "are inverted before aggregation.\n",
        "- Order-book mid-prices (when available) replace the last-trade price "
        "as a more accurate probability estimate.\n",
        f"- Log appended → {log_path}\n",
    ]

    return "\n".join(lines)
