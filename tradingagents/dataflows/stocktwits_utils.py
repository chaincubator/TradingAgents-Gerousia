"""StockTwits message stream and sentiment utilities.

Uses the StockTwits public REST API — no API key required for reading.
Rate limit: ~200 requests/hour for unauthenticated clients.

Symbol conventions on StockTwits:
  US stocks / ETFs : plain ticker             e.g. AAPL, GLD, SPY
  Crypto            : ticker with .X suffix   e.g. BTC.X, ETH.X
  (auto-handled by this module based on symbol type)

Relevant endpoint:
  GET https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json
"""

import requests
from datetime import datetime
from typing import List, Optional

_API_BASE   = "https://api.stocktwits.com/api/2"
_USER_AGENT = "TradingAgents:v1.0 (financial-analysis-bot)"
_TIMEOUT    = 12

# Crypto tickers that require the .X suffix on StockTwits
_CRYPTO_TICKERS = {
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "AVAX",
    "LINK", "DOT", "SUI", "ARB", "OP", "INJ", "MORPHO", "TIA",
    "NEAR", "ATOM", "LTC", "BCH", "ETC", "SHIB", "PEPE", "FLOKI",
    "ICP", "HBAR", "FIL", "MKR", "APT", "GRT", "RUNE", "MINA",
    "SEI", "WLD", "STX", "JUP", "PYTH", "OP",
}


def _st_symbol(ticker: str) -> str:
    """Return StockTwits-formatted symbol (appends .X for crypto)."""
    s = ticker.upper().strip()
    if s in _CRYPTO_TICKERS:
        return f"{s}.X"
    return s


def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT,
                         headers={"User-Agent": _USER_AGENT})
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def get_stocktwits_sentiment(
    symbol: str,
    curr_date: str,
    max_messages: int = 30,
) -> str:
    """
    Fetch the most recent StockTwits messages for a symbol and return a
    formatted Markdown sentiment report.

    Includes:
      - Bullish/Bearish breakdown of tagged messages
      - Top 10 most recent/liked messages with sentiment labels
      - Follower-weighted sentiment (high-follower accounts weighted 2x)

    Returns "NA — ..." on API failure or unknown symbol.
    """
    st_sym = _st_symbol(symbol)
    data   = _get(f"{_API_BASE}/streams/symbol/{st_sym}.json",
                  params={"limit": max_messages})

    if data is None:
        return f"NA — StockTwits API unavailable for {symbol}."

    resp_status = data.get("response", {}).get("status")
    if resp_status not in (None, 200):
        err = data.get("response", {}).get("error_message", "unknown error")
        return f"NA — StockTwits error for {st_sym}: {err}"

    messages: List[dict] = data.get("messages", [])
    if not messages:
        return f"NA — no StockTwits messages found for {st_sym}."

    # ── Sentiment counts ───────────────────────────────────────────────────────
    bullish = [m for m in messages
               if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish"]
    bearish = [m for m in messages
               if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish"]
    n_tagged = len(bullish) + len(bearish)

    # ── Follower-weighted sentiment ────────────────────────────────────────────
    def follower_weight(m: dict) -> float:
        f = m.get("user", {}).get("followers", 0) or 0
        return 2.0 if f > 1000 else 1.0

    bull_w = sum(follower_weight(m) for m in bullish)
    bear_w = sum(follower_weight(m) for m in bearish)
    total_w = bull_w + bear_w

    if total_w > 0:
        bull_wpct = bull_w / total_w
        bear_wpct = bear_w / total_w
    else:
        bull_wpct = bear_wpct = None

    # ── Bias label ─────────────────────────────────────────────────────────────
    raw_bull_pct = len(bullish) / n_tagged if n_tagged else None
    if bull_wpct is None:
        bias = "NEUTRAL (no tagged messages)"
    elif bull_wpct > 0.65:
        bias = f"BULLISH ({bull_wpct:.0%} follower-weighted)"
    elif bull_wpct < 0.35:
        bias = f"BEARISH ({bear_wpct:.0%} follower-weighted)"
    else:
        bias = f"MIXED — Bull {bull_wpct:.0%} / Bear {bear_wpct:.0%} (follower-weighted)"

    lines = [
        f"## {symbol.upper()} StockTwits Sentiment — {curr_date}\n",
        f"**Sentiment bias:** {bias}",
        f"**Tagged messages:** {n_tagged}/{len(messages)}  "
        f"({len(bullish)} bullish / {len(bearish)} bearish)",
    ]
    if raw_bull_pct is not None:
        lines.append(
            f"**Raw %:** Bull {raw_bull_pct:.0%} / Bear {1-raw_bull_pct:.0%}"
        )
    lines.append("")

    # ── Top messages ───────────────────────────────────────────────────────────
    def msg_sort_key(m: dict):
        # Tagged messages first, then by follower count, then by likes
        tagged   = m.get("entities", {}).get("sentiment", {}).get("basic") is not None
        likes    = int(m.get("likes", {}).get("total", 0) or 0)
        followers = int(m.get("user", {}).get("followers", 0) or 0)
        return (not tagged, -followers, -likes)

    top = sorted(messages, key=msg_sort_key)[:10]
    lines.append("**Recent messages:**")
    for m in top:
        snt  = (m.get("entities", {}).get("sentiment", {}).get("basic") or "")
        tag  = f"[{snt.upper()}] " if snt else ""
        user = m.get("user", {}).get("username", "anon")
        flw  = int(m.get("user", {}).get("followers", 0) or 0)
        body = (m.get("body", "") or "").replace("\n", " ").strip()[:220]
        ts   = (m.get("created_at", "") or "")[:10]
        flw_s = f" ({flw:,} followers)" if flw > 100 else ""
        lines.append(f"- {tag}@{user}{flw_s} ({ts}): {body}")

    lines.append("")

    # ── Sentiment table ────────────────────────────────────────────────────────
    lines += [
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total messages | {len(messages)} |",
        f"| Tagged (bull+bear) | {n_tagged} ({n_tagged/len(messages):.0%}) |",
        f"| Bullish | {len(bullish)} |",
        f"| Bearish | {len(bearish)} |",
        f"| Follower-wtd bull % | {f'{bull_wpct:.0%}' if bull_wpct is not None else 'N/A'} |",
    ]

    return "\n".join(lines)
