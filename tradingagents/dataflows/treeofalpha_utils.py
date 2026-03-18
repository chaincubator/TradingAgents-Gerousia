"""Tree of Alpha social sentiment utilities.

Fetches crypto news and social (Twitter/X) data from the Tree of Alpha API.
API docs: https://docs.treeofalpha.com/
API key: set the TREE_OF_ALPHA_API environment variable.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import requests

_BASE = "https://news.treeofalpha.com/api"


def _session() -> requests.Session:
    api_key = os.getenv("TREE_OF_ALPHA_API", "")
    s = requests.Session()
    if api_key:
        s.headers.update({"Authorization": f"Bearer {api_key}"})
    return s


def _ts_ms(dt: datetime) -> int:
    """Convert datetime to Unix milliseconds."""
    return int(dt.timestamp() * 1000)


def _fetch(endpoint: str, params: dict) -> Optional[list]:
    try:
        resp = _session().get(f"{_BASE}/{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[treeofalpha] {endpoint} error: {e}")
        return None


def get_treeofalpha_sentiment(
    symbol: str,
    curr_date: str,
    look_back_days: int = 7,
) -> str:
    """
    Fetch combined crypto news and social sentiment from Tree of Alpha
    for a given symbol and date range.

    Args:
        symbol:         Crypto symbol, e.g. 'BTC', 'ETH'
        curr_date:      End date in YYYY-MM-DD format
        look_back_days: How many days of history to fetch (default 7)

    Returns:
        Formatted string with news and social posts, or an error message.
    """
    if not os.getenv("TREE_OF_ALPHA_API"):
        return (
            "TREE_OF_ALPHA_API environment variable is not set. "
            "Set it to your Tree of Alpha API key to enable social sentiment."
        )

    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    start_ms = _ts_ms(start)
    end_ms = _ts_ms(end + timedelta(days=1))

    sym = symbol.upper()
    params = {"limit": 100, "search": sym}

    # ── News ──────────────────────────────────────────────────────────────
    news_data = _fetch("news", params) or []
    news_items = [
        item for item in news_data
        if start_ms <= item.get("time", 0) <= end_ms
    ]

    # ── Social / Twitter ──────────────────────────────────────────────────
    social_data = _fetch("twitter", params) or []
    social_items = [
        item for item in social_data
        if start_ms <= item.get("time", 0) <= end_ms
    ]

    if not news_items and not social_items:
        return (
            f"No Tree of Alpha data found for {sym} "
            f"({start.strftime('%Y-%m-%d')} → {curr_date})."
        )

    lines = [
        f"## {sym} Social Sentiment — Tree of Alpha "
        f"({look_back_days}d ending {curr_date})\n"
    ]

    if news_items:
        lines.append(f"### News ({len(news_items)} items)\n")
        for item in news_items[:20]:
            ts = datetime.utcfromtimestamp(
                item.get("time", 0) / 1000
            ).strftime("%Y-%m-%d %H:%M UTC")
            title = (item.get("title") or item.get("body") or "")[:200]
            source = item.get("source", "unknown")
            link = item.get("link") or item.get("url") or ""
            lines.append(f"**[{ts}] {source}**: {title}")
            if link:
                lines.append(f"  {link}")
            lines.append("")

    if social_items:
        lines.append(f"### Social Posts ({len(social_items)} items)\n")
        for item in social_items[:20]:
            ts = datetime.utcfromtimestamp(
                item.get("time", 0) / 1000
            ).strftime("%Y-%m-%d %H:%M UTC")
            body = (item.get("body") or item.get("text") or "")[:200]
            user = item.get("username") or item.get("user") or "unknown"
            link = item.get("link") or item.get("url") or ""
            lines.append(f"**[{ts}] @{user}**: {body}")
            if link:
                lines.append(f"  {link}")
            lines.append("")

    return "\n".join(lines)
