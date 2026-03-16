"""Binance Vision historical kline (OHLCV) data utilities.

Public data source: https://data.binance.vision
No API key required. Monthly and daily ZIP archives are downloaded and cached locally.

5-minute candle CSV column order (no header row):
    open_time, open, high, low, close, volume, close_time,
    quote_volume, trades, taker_buy_base_volume, taker_buy_quote_volume, ignore
"""

import io
import os
import zipfile
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

_BASE = "https://data.binance.vision/data/spot"
_INTERVAL = "5m"
_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]


def _normalize_pair(symbol: str) -> str:
    """Convert a bare symbol (BTC) to a Binance USDT spot pair (BTCUSDT)."""
    s = symbol.upper().strip()
    if s.endswith("USDT"):
        return s
    return s + "USDT"


def _load_zip(url: str, csv_name: str, cache_file: str) -> Optional[pd.DataFrame]:
    """Download a Binance Vision ZIP, extract its CSV, cache it, and return a DataFrame."""
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, header=None, names=_COLUMNS)
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, header=None, names=_COLUMNS)
        df.to_csv(cache_file, index=False, header=False)
        return df
    except Exception as e:
        print(f"[binance_utils] Failed to fetch {url}: {e}")
        return None


def _monthly(pair: str, year: int, month: int, cache_dir: str) -> Optional[pd.DataFrame]:
    tag = f"{pair}-{_INTERVAL}-{year}-{month:02d}"
    url = f"{_BASE}/monthly/klines/{pair}/{_INTERVAL}/{tag}.zip"
    return _load_zip(url, f"{tag}.csv", os.path.join(cache_dir, f"{tag}.csv"))


def _daily(pair: str, year: int, month: int, day: int, cache_dir: str) -> Optional[pd.DataFrame]:
    tag = f"{pair}-{_INTERVAL}-{year}-{month:02d}-{day:02d}"
    url = f"{_BASE}/daily/klines/{pair}/{_INTERVAL}/{tag}.zip"
    return _load_zip(url, f"{tag}.csv", os.path.join(cache_dir, f"{tag}.csv"))


def fetch_klines(
    symbol: str,
    start_date: str,
    end_date: str,
    cache_dir: str = "./data/binance_cache",
) -> Optional[pd.DataFrame]:
    """
    Fetch 5m OHLCV klines from Binance Vision for the given date range.

    Uses monthly archives for fully completed past months; falls back to
    individual daily files for the current (incomplete) month.
    All files are cached locally under cache_dir.

    Returns a DataFrame with parsed datetime open_time and numeric OHLCV columns,
    or None if no data could be retrieved.
    """
    os.makedirs(cache_dir, exist_ok=True)
    pair = _normalize_pair(symbol)
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    now = datetime.utcnow()

    frames = []
    cur = start.replace(day=1)

    while cur <= end:
        y, m = cur.year, cur.month
        next_month = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_complete = next_month <= now

        if month_complete:
            df = _monthly(pair, y, m, cache_dir)
            if df is not None:
                frames.append(df)
        else:
            # Current/incomplete month: fetch day-by-day
            first_day = start.day if (y == start.year and m == start.month) else 1
            day_cur = cur.replace(day=first_day)
            day_end = min(end, now - timedelta(days=1))
            while day_cur <= day_end and day_cur.month == m:
                df = _daily(pair, y, m, day_cur.day, cache_dir)
                if df is not None:
                    frames.append(df)
                day_cur += timedelta(days=1)

        cur = next_month

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    combined["open_time"] = pd.to_datetime(
        combined["open_time"], unit="ms", utc=True
    ).dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")
    combined["trades"] = pd.to_numeric(combined["trades"], errors="coerce")

    combined = combined[
        (combined["open_time"] >= start) &
        (combined["open_time"] < end + timedelta(days=1))
    ].sort_values("open_time").reset_index(drop=True)

    return combined if not combined.empty else None


def get_binance_price_history(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """
    Return daily OHLCV summary aggregated from 5m Binance Vision candles.
    """
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return (
            f"No Binance Vision data found for {pair} "
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
        f" — Binance Vision 5m candles\nPair: {pair}\n\n"
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
    and 5-day support/resistance from Binance Vision 5m candles.
    """
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return (
            f"No Binance Vision data found for {pair} "
            f"({start.strftime('%Y-%m-%d')} to {curr_date})."
        )

    closes = df["close"]
    volumes = df["volume"]

    # RSI(14) on 5m closes
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
        f"## {symbol.upper()} Technical Analysis — Binance Vision 5m Candles\n"
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
