"""Reddit live data fetching via Reddit's public JSON API.

Replaces the previous implementation that read from pre-downloaded local
JSONL files, which required a static dataset that went stale and was not
shipped with the repository.

This implementation calls Reddit's public read-only JSON API (no OAuth
required for public subreddits).  It respects a polite rate limit of
~0.15s between requests and retries once on 429 responses.

No API key or environment variable is needed.
"""

import time
import re
import requests
from datetime import datetime
from typing import Annotated, Dict, List, Optional

# ── Constants ──────────────────────────────────────────────────────────────────
_USER_AGENT  = "TradingAgents:v1.0 (financial-analysis-bot)"
_TIMEOUT     = 12
_RETRY_SLEEP = 1.5

# Category → subreddits queried for that category
_CATEGORY_SUBREDDITS: Dict[str, List[str]] = {
    "global_news":  ["worldnews", "news", "Finance", "economics", "investing"],
    "company_news": ["stocks", "investing", "StockMarket", "wallstreetbets"],
    "crypto_news":  ["CryptoCurrency", "CryptoMarkets", "Bitcoin", "ethereum"],
    "finance":      ["investing", "Finance", "StockMarket", "economics"],
}

# Crypto tickers → plain-English search terms used in Reddit search
_CRYPTO_TERMS: Dict[str, str] = {
    "BTC": "bitcoin",  "ETH": "ethereum", "SOL": "solana",   "XRP": "ripple",
    "ADA": "cardano",  "DOGE": "dogecoin", "BNB": "binance", "AVAX": "avalanche",
    "LINK": "chainlink", "DOT": "polkadot", "SUI": "sui",    "ARB": "arbitrum",
    "OP": "optimism",  "INJ": "injective", "MORPHO": "morpho", "TIA": "celestia",
    "NEAR": "near protocol", "ATOM": "cosmos", "LTC": "litecoin",
}

# Company name lookup for stock ticker → search term expansion
ticker_to_company: Dict[str, str] = {
    "AAPL": "Apple",          "MSFT": "Microsoft",      "GOOGL": "Google",
    "AMZN": "Amazon",         "TSLA": "Tesla",           "NVDA": "Nvidia",
    "META": "Meta Facebook",  "AMD": "AMD",              "INTC": "Intel",
    "QCOM": "Qualcomm",       "NFLX": "Netflix",         "CRM": "Salesforce",
    "PYPL": "PayPal",         "JPM": "JPMorgan",         "V": "Visa",
    "MA": "Mastercard",       "WMT": "Walmart",          "BABA": "Alibaba",
    "ADBE": "Adobe",          "ORCL": "Oracle",          "CSCO": "Cisco",
    "SHOP": "Shopify",        "AVGO": "Broadcom",        "PLTR": "Palantir",
    "SQ": "Block Square",     "UBER": "Uber",            "SNAP": "Snap",
    "SPOT": "Spotify",        "PINS": "Pinterest",       "ROKU": "Roku",
    "ASML": "ASML",           "TSM": "TSMC Taiwan Semiconductor",
    "JNJ": "Johnson Johnson", "PFE": "Pfizer",
    # TradFi instruments with perp futures
    "GOLD":   "gold price xauusd", "SILVER": "silver price",
    "OIL":    "crude oil WTI",     "NATGAS": "natural gas",
    "SPX":    "S&P 500 index",     "NDX":    "nasdaq 100",
    "SPY":    "SPY ETF",           "QQQ":    "QQQ ETF",
    "TLT":    "treasury bonds TLT", "GLD":   "gold GLD ETF",
}


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _reddit_get(url: str, params: dict = None) -> Optional[dict]:
    """GET with proper User-Agent and one retry on 429/timeout."""
    headers = {"User-Agent": _USER_AGENT}
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
            if r.status_code == 429:
                time.sleep(_RETRY_SLEEP * (attempt + 1))
                continue
            if r.status_code in (403, 404):
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 0:
                time.sleep(_RETRY_SLEEP)
    return None


# ── Subreddit query helpers ────────────────────────────────────────────────────

def _search_subreddit(subreddit: str, query: str, limit: int = 20) -> List[dict]:
    """Search posts in a subreddit matching query, sorted by new, last week."""
    data = _reddit_get(
        f"https://www.reddit.com/r/{subreddit}/search.json",
        params={"q": query, "sort": "new", "t": "week",
                "restrict_sr": "1", "limit": limit},
    )
    if not data:
        return []
    return [c.get("data", {}) for c in data.get("data", {}).get("children", []) if c.get("data")]


def _hot_subreddit(subreddit: str, limit: int = 20) -> List[dict]:
    """Fetch hot posts from a subreddit."""
    data = _reddit_get(
        f"https://www.reddit.com/r/{subreddit}/hot.json",
        params={"limit": limit},
    )
    if not data:
        return []
    return [c.get("data", {}) for c in data.get("data", {}).get("children", []) if c.get("data")]


def _to_post(raw: dict, fallback_date: str) -> dict:
    ts = raw.get("created_utc", 0)
    try:
        posted = datetime.utcfromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:
        posted = fallback_date
    return {
        "title":       raw.get("title", ""),
        "content":     raw.get("selftext", ""),
        "url":         raw.get("url", ""),
        "upvotes":     int(raw.get("ups", 0) or 0),
        "posted_date": posted,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_top_from_category(
    category: Annotated[str, "Category key: global_news, company_news, crypto_news"],
    date: Annotated[str, "Reference date (yyyy-mm-dd); kept for backward compat"],
    max_limit: Annotated[int, "Maximum total posts to return"],
    query: Annotated[str, "Optional ticker or search term"] = None,
    data_path: Annotated[str, "Ignored; kept for backward compat"] = "reddit_data",
) -> List[dict]:
    """
    Fetch top posts from Reddit for a given category via the live public JSON API.

    Previously this read from local JSONL files; it now calls Reddit's public
    JSON endpoints instead.  The `date` and `data_path` parameters are kept
    for backward compatibility but have no effect — only recent posts (last
    ~7 days) are available from the unauthenticated API.

    Handles crypto tickers automatically by redirecting to crypto subreddits
    and expanding the search term (e.g. "BTC" → "bitcoin").
    """
    ticker_up = (query or "").upper().strip()

    # Decide subreddits and search term
    if ticker_up in _CRYPTO_TERMS:
        subreddits  = _CATEGORY_SUBREDDITS["crypto_news"]
        search_term = _CRYPTO_TERMS[ticker_up]
    elif ticker_up:
        subreddits  = _CATEGORY_SUBREDDITS.get(category, _CATEGORY_SUBREDDITS["company_news"])
        search_term = ticker_to_company.get(ticker_up, query or "")
    else:
        subreddits  = _CATEGORY_SUBREDDITS.get(category, _CATEGORY_SUBREDDITS["global_news"])
        search_term = None

    limit_per  = max(3, max_limit // max(len(subreddits), 1))
    all_posts: List[dict] = []

    for sr in subreddits:
        try:
            if search_term:
                raw_list = _search_subreddit(sr, search_term, limit_per)
            else:
                raw_list = _hot_subreddit(sr, limit_per)
            for raw in raw_list:
                post = _to_post(raw, date)
                if post["title"]:   # skip empty stubs
                    all_posts.append(post)
        except Exception:
            pass
        time.sleep(0.15)  # polite rate limit

    all_posts.sort(key=lambda p: p["upvotes"], reverse=True)
    return all_posts[:max_limit]
