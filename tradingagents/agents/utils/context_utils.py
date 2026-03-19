"""Utilities for safe agent context building.

When a data source had no relevant data, it returns a string starting
with "NA —".  Use is_na() to detect these and ctx() to silently drop
them when building LLM prompt context so agents only reason over the
data that actually exists.
"""


def is_na(report: str) -> bool:
    """Return True if a report signals no data was available."""
    if not report or not report.strip():
        return True
    return report.strip().upper().startswith("NA")


def ctx(label: str, report: str) -> str:
    """
    Return a labelled context block, or an empty string if the report is NA.

    Usage:
        prompt = (
            ctx("Market 5m report", market_report) +
            ctx("Polymarket signals", polymarket_report) +   # silently skipped if NA
            ctx("FRED macro", fred_report)                   # silently skipped if NA
        )
    """
    if is_na(report):
        return ""
    return f"{label}:\n{report}\n\n"
