"""Binance historical kline (OHLCV) data utilities.

Uses the python-binance client to fetch 5-minute candle data from the
Binance REST API.  No API key is required for public market data endpoints.
Results are cached locally as CSV to minimise repeated network calls.

Kline column order (matches Binance API response):
    open_time, open, high, low, close, volume, close_time,
    quote_volume, trades, taker_buy_base_volume, taker_buy_quote_volume, ignore
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from binance.client import Client

_INTERVAL = Client.KLINE_INTERVAL_5MINUTE

_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]


def _normalize_pair(symbol: str) -> str:
    """Convert a bare symbol (BTC) to a Binance USDT spot pair (BTCUSDT)."""
    s = symbol.upper().strip()
    return s if s.endswith("USDT") else s + "USDT"


def _get_client() -> Client:
    """Return a Binance client. No API keys needed for public kline data."""
    return Client()


def fetch_klines(
    symbol: str,
    start_date: str,
    end_date: str,
    cache_dir: str = "./data/binance_cache",
) -> Optional[pd.DataFrame]:
    """
    Fetch 5m OHLCV klines via the Binance API for the given date range.

    Pagination is handled automatically by python-binance.
    Results are cached as a CSV under cache_dir keyed by (pair, start, end)
    so repeated calls for the same range are served from disk.

    Args:
        symbol:     Crypto symbol, e.g. "BTC", "ETH", or "BTCUSDT"
        start_date: Start date in "YYYY-MM-DD" format
        end_date:   End date in "YYYY-MM-DD" format (inclusive)
        cache_dir:  Directory for local CSV cache

    Returns:
        DataFrame with parsed datetime open_time and numeric OHLCV columns,
        or None if no data could be retrieved.
    """
    os.makedirs(cache_dir, exist_ok=True)
    pair = _normalize_pair(symbol)
    cache_file = os.path.join(cache_dir, f"{pair}-5m-{start_date}-{end_date}.csv")

    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file)
        df["open_time"] = pd.to_datetime(df["open_time"])
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
        return df if not df.empty else None

    try:
        client = _get_client()
        raw = client.get_historical_klines(pair, _INTERVAL, start_date, end_date)
    except Exception as e:
        print(f"[binance_utils] Failed to fetch klines for {pair}: {e}")
        return None

    if not raw:
        return None

    df = pd.DataFrame(raw, columns=_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    df = df.sort_values("open_time").reset_index(drop=True)

    df.to_csv(cache_file, index=False)
    return df


def get_binance_price_history(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """
    Return daily OHLCV summary aggregated from 5m Binance klines.
    """
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return (
            f"No Binance data found for {pair} "
            f"({start.strftime('%Y-%m-%d')} to {curr_date})."
        )

    df["date"] = df["open_time"].dt.date
    daily = df.groupby("date").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        trades=("trades", "sum"),
    ).reset_index()

    header = (
        f"## {symbol.upper()} Price History ({look_back_days}d)"
        f" — Binance 5m candles\nPair: {pair}\n\n"
        f"{'Date':<12} {'Open':>12} {'High':>12} {'Low':>12}"
        f" {'Close':>12} {'Volume':>18}\n"
        + "-" * 80 + "\n"
    )
    rows = "".join(
        f"{str(row['date']):<12} {row['open']:>12.2f} {row['high']:>12.2f} "
        f"{row['low']:>12.2f} {row['close']:>12.2f} {row['volume']:>18.4f}\n"
        for _, row in daily.iterrows()
    )
    summary = (
        f"\n**Summary:**\n"
        f"- Period High:       ${daily['high'].max():,.2f}\n"
        f"- Period Low:        ${daily['low'].min():,.2f}\n"
        f"- Latest Close:      ${daily['close'].iloc[-1]:,.2f}\n"
        f"- Avg Daily Volume:  {daily['volume'].mean():,.4f} {symbol.upper()}\n"
        f"- Total 5m Candles:  {len(df):,}\n"
    )
    return header + rows + summary


def get_binance_technical_analysis(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """
    Compute RSI(14), EMA20/50, Bollinger Bands (20, 2σ), VWAP(24h),
    and 5-day support/resistance from Binance 5m klines.
    """
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return (
            f"No Binance data found for {pair} "
            f"({start.strftime('%Y-%m-%d')} to {curr_date})."
        )

    closes = df["close"]
    volumes = df["volume"]

    # RSI(14)
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi_val = (100 - 100 / (1 + rs)).iloc[-1]

    # EMA20 and EMA50
    ema20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = closes.ewm(span=50, adjust=False).mean().iloc[-1]

    # Bollinger Bands (20-period, 2 std dev)
    sma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()
    bb_upper = (sma20 + 2 * std20).iloc[-1]
    bb_lower = (sma20 - 2 * std20).iloc[-1]

    # VWAP over the last 24 hours of candles
    last_24h = df[df["open_time"] >= df["open_time"].iloc[-1] - timedelta(hours=24)]
    if not last_24h.empty and last_24h["volume"].sum() > 0:
        tp = (last_24h["high"] + last_24h["low"] + last_24h["close"]) / 3
        vwap = (tp * last_24h["volume"]).sum() / last_24h["volume"].sum()
    else:
        vwap = closes.iloc[-1]

    # Support / resistance from last 5 days of 5m candles
    last_5d = df[df["open_time"] >= df["open_time"].iloc[-1] - timedelta(days=5)]
    support = last_5d["low"].min()
    resistance = last_5d["high"].max()

    current_price = closes.iloc[-1]
    trend = "Bullish" if ema20 > ema50 else "Bearish"
    rsi_label = "Overbought" if rsi_val > 70 else ("Oversold" if rsi_val < 30 else "Neutral")
    avg_vol_24h = last_24h["volume"].mean() if not last_24h.empty else 0
    avg_vol_period = volumes.mean()
    vol_signal = "Above average" if avg_vol_24h > avg_vol_period else "Below average"

    return (
        f"## {symbol.upper()} Technical Analysis — Binance 5m Candles\n"
        f"Pair: {pair}\n\n"
        f"**Current Price:** ${current_price:,.2f}\n\n"
        f"**Trend (EMA20 vs EMA50):** {trend}\n"
        f"- EMA20: ${ema20:,.2f}\n"
        f"- EMA50: ${ema50:,.2f}\n\n"
        f"**RSI(14):** {rsi_val:.1f} — {rsi_label}\n\n"
        f"**Bollinger Bands (20, 2\u03c3):**\n"
        f"- Upper: ${bb_upper:,.2f}\n"
        f"- Lower: ${bb_lower:,.2f}\n\n"
        f"**VWAP (24h):** ${vwap:,.2f}\n\n"
        f"**Recent Levels (5d):**\n"
        f"- Resistance: ${resistance:,.2f}\n"
        f"- Support:    ${support:,.2f}\n\n"
        f"**Volume (5m candles):**\n"
        f"- 24h Average:    {avg_vol_24h:,.4f} {symbol.upper()}\n"
        f"- Period Average: {avg_vol_period:,.4f} {symbol.upper()}\n"
        f"- Signal: {vol_signal}\n"
    )
