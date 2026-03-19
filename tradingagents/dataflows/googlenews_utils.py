"""Google News utilities — RSS-based implementation.

Replaced the previous BeautifulSoup HTML-scraping approach, which broke
whenever Google changed its CSS class names and depended on non-standard
packages (beautifulsoup4, tenacity).

This implementation uses the publicly available Google News RSS endpoint,
parsed with feedparser (already a project dependency).  No API key is
required and the feed is significantly more stable than HTML scraping.
"""

import urllib.parse
from datetime import datetime
from typing import List, Optional

import feedparser


def getNewsData(
    query: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 20,
) -> List[dict]:
    """
    Fetch news articles via Google News RSS for a given query.

    Args:
        query:       Search terms (e.g. "bitcoin price", "Federal Reserve")
        start_date:  Optional earliest date (yyyy-mm-dd or mm/dd/yyyy).
                     Appended to the query as 'after:YYYY-MM-DD'.
        end_date:    Ignored (Google News RSS only surfaces recent articles).
        max_results: Maximum number of articles to return.

    Returns:
        List of dicts with keys: title, link, snippet, source, date.
        Returns an empty list on any failure so callers degrade gracefully.
    """
    # Normalise date format for Google's 'after:' operator
    after_clause = ""
    if start_date:
        try:
            if "/" in start_date:
                dt = datetime.strptime(start_date, "%m/%d/%Y")
            else:
                dt = datetime.strptime(start_date, "%Y-%m-%d")
            after_clause = f" after:{dt.strftime('%Y-%m-%d')}"
        except ValueError:
            pass

    full_query  = query + after_clause
    encoded     = urllib.parse.quote(full_query)
    url         = (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    )

    try:
        feed    = feedparser.parse(url)
        results = []
        for entry in feed.entries[:max_results]:
            # Google News RSS wraps the real source in the title as "title - Source"
            title = entry.get("title", "")
            source = ""
            if hasattr(entry, "source") and hasattr(entry.source, "title"):
                source = entry.source.title
            elif " - " in title:
                # Fallback: parse source from title suffix
                parts  = title.rsplit(" - ", 1)
                title  = parts[0].strip()
                source = parts[1].strip()

            results.append({
                "title":   title,
                "link":    entry.get("link", ""),
                "snippet": entry.get("summary", "")[:400],
                "source":  source,
                "date":    entry.get("published", ""),
            })
        return results
    except Exception as e:
        print(f"[googlenews] RSS fetch failed: {e}")
        return []
