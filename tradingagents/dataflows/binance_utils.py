"""Binance historical kline (OHLCV) data utilities.

Uses the python-binance client to fetch 5-minute and 4-hour candle data
from the Binance REST API.  No API key required for public endpoints.
Technical indicators are computed with the `ta` library.

5m candles — short-window indicators, default 7-day lookback.
4h candles — standard indicators, default 730-day (2 yr) lookback.

Kline column order (Binance API response):
    open_time, open, high, low, close, volume, close_time,
    quote_volume, trades, taker_buy_base_volume, taker_buy_quote_volume, ignore
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from binance.client import Client

try:
    import ta as _ta
    _TA_AVAILABLE = True
except ImportError:
    _TA_AVAILABLE = False

from tradingagents.dataflows.advanced_indicators import format_advanced_indicators

_INTERVAL_5M = Client.KLINE_INTERVAL_5MINUTE
_INTERVAL_4H = Client.KLINE_INTERVAL_4HOUR

_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]


def _normalize_pair(symbol: str) -> str:
    s = symbol.upper().strip()
    return s if s.endswith("USDT") else s + "USDT"


def _get_client() -> Client:
    return Client()


def _load_cached(cache_file: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(cache_file):
        return None
    df = pd.read_csv(cache_file)
    df["open_time"] = pd.to_datetime(df["open_time"])
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    return df if not df.empty else None


def _parse_to_df(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    return df.sort_values("open_time").reset_index(drop=True)


def _fetch_master(
    symbol: str,
    start_date: str,
    end_date: str,
    cache_dir: str,
    interval_const: str,
    interval_tag: str,
    default_lookback_days: int,
) -> Optional[pd.DataFrame]:
    """
    Incremental master-cache strategy.
    Maintains a single {PAIR}-{INTERVAL}-master.csv per symbol.
    Only downloads candles newer than the latest stored timestamp.
    Returns a filtered view for [start_date, end_date].
    """
    os.makedirs(cache_dir, exist_ok=True)
    pair        = _normalize_pair(symbol)
    master_file = os.path.join(cache_dir, f"{pair}-{interval_tag}-master.csv")
    end_dt      = datetime.strptime(end_date, "%Y-%m-%d")

    existing   = _load_cached(master_file)
    fetch_from = None

    if existing is not None and not existing.empty:
        latest_ts = existing["open_time"].max()
        if latest_ts < end_dt:
            # Only fetch the gap between latest cached candle and end_date
            fetch_from = (latest_ts + timedelta(minutes=5)).strftime("%Y-%m-%d")
        # else: master already covers end_date — no API call needed
    else:
        # No master yet — bootstrap from default_lookback_days back
        bootstrap = end_dt - timedelta(days=default_lookback_days)
        actual_start = min(datetime.strptime(start_date, "%Y-%m-%d"), bootstrap)
        fetch_from = actual_start.strftime("%Y-%m-%d")

    if fetch_from is not None:
        try:
            raw = _get_client().get_historical_klines(
                pair, interval_const, fetch_from, end_date
            )
        except Exception as e:
            print(f"[binance_utils] Failed to fetch {interval_tag} for {pair}: {e}")
            raw = []

        if raw:
            new_df = _parse_to_df(raw)
            if existing is not None and not existing.empty:
                combined = (
                    pd.concat([existing, new_df])
                    .drop_duplicates("open_time")
                    .sort_values("open_time")
                    .reset_index(drop=True)
                )
            else:
                combined = new_df
            combined.to_csv(master_file, index=False)
            existing = combined

    if existing is None or existing.empty:
        return None

    # Return the requested date slice
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    mask = (existing["open_time"] >= start_dt) & (
        existing["open_time"] < end_dt + timedelta(days=1)
    )
    result = existing[mask].reset_index(drop=True)
    return result if not result.empty else None


# ── Public fetch helpers ──────────────────────────────────────────────────────

def fetch_klines(symbol: str, start_date: str, end_date: str,
                 cache_dir: str = "./data/binance_cache") -> Optional[pd.DataFrame]:
    """
    Fetch 5m OHLCV klines using an incremental master cache.
    Only new candles (since the last cached timestamp) are downloaded.
    """
    return _fetch_master(symbol, start_date, end_date, cache_dir,
                         _INTERVAL_5M, "5m", default_lookback_days=30)


def fetch_4h_klines(symbol: str, start_date: str, end_date: str,
                    cache_dir: str = "./data/binance_cache") -> Optional[pd.DataFrame]:
    """
    Fetch 4h OHLCV klines using an incremental master cache.
    Only new candles (since the last cached timestamp) are downloaded.
    """
    return _fetch_master(symbol, start_date, end_date, cache_dir,
                         _INTERVAL_4H, "4h", default_lookback_days=730)


# ── 5-minute analysis (short windows) ────────────────────────────────────────

def get_binance_price_history(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """Return daily OHLCV summary aggregated from 5m Binance klines."""
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return f"No Binance data found for {pair} ({start.strftime('%Y-%m-%d')} to {curr_date})."

    df["date"] = df["open_time"].dt.date
    daily = df.groupby("date").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), trades=("trades", "sum"),
    ).reset_index()

    header = (
        f"## {symbol.upper()} Price History ({look_back_days}d) — Binance 5m candles\n"
        f"Pair: {pair}\n\n"
        f"{'Date':<12} {'Open':>12} {'High':>12} {'Low':>12} {'Close':>12} {'Volume':>18}\n"
        + "-" * 80 + "\n"
    )
    rows = "".join(
        f"{str(r['date']):<12} {r['open']:>12.2f} {r['high']:>12.2f} "
        f"{r['low']:>12.2f} {r['close']:>12.2f} {r['volume']:>18.4f}\n"
        for _, r in daily.iterrows()
    )
    summary = (
        f"\n**Summary:**\n"
        f"- Period High:      ${daily['high'].max():,.2f}\n"
        f"- Period Low:       ${daily['low'].min():,.2f}\n"
        f"- Latest Close:     ${daily['close'].iloc[-1]:,.2f}\n"
        f"- Avg Daily Volume: {daily['volume'].mean():,.4f} {symbol.upper()}\n"
        f"- Total 5m Candles: {len(df):,}\n"
    )
    return header + rows + summary


def get_binance_technical_analysis(
    symbol: str,
    curr_date: str,
    look_back_days: int = 7,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """
    Compute short-window technical indicators from 5m Binance klines.
    RSI(9), EMA(9/21), Bollinger Bands(10,2σ), ATR(5), VWAP(4h).
    Default lookback shortened to 7 days for intraday granularity.
    """
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return f"No Binance data found for {pair} ({start.strftime('%Y-%m-%d')} to {curr_date})."

    closes = df["close"]
    current_price = closes.iloc[-1]

    if _TA_AVAILABLE:
        rsi_val = _ta.momentum.RSIIndicator(close=closes, window=9).rsi().iloc[-1]
        ema9  = _ta.trend.EMAIndicator(close=closes, window=9).ema_indicator().iloc[-1]
        ema21 = _ta.trend.EMAIndicator(close=closes, window=21).ema_indicator().iloc[-1]
        bb    = _ta.volatility.BollingerBands(close=closes, window=10, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        atr_val = _ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=closes, window=5
        ).average_true_range().iloc[-1]
    else:
        # Manual fallback
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(9).mean()
        loss = (-delta.clip(upper=0)).rolling(9).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi_val = (100 - 100 / (1 + rs)).iloc[-1]
        ema9  = closes.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21 = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        sma10 = closes.rolling(10).mean()
        std10 = closes.rolling(10).std()
        bb_upper = (sma10 + 2 * std10).iloc[-1]
        bb_lower = (sma10 - 2 * std10).iloc[-1]
        atr_val = float("nan")

    # VWAP over last 4h of candles
    last_4h = df[df["open_time"] >= df["open_time"].iloc[-1] - timedelta(hours=4)]
    if not last_4h.empty and last_4h["volume"].sum() > 0:
        tp = (last_4h["high"] + last_4h["low"] + last_4h["close"]) / 3
        vwap = (tp * last_4h["volume"]).sum() / last_4h["volume"].sum()
    else:
        vwap = current_price

    # Support / resistance from last 24h
    last_24h = df[df["open_time"] >= df["open_time"].iloc[-1] - timedelta(hours=24)]
    support    = last_24h["low"].min()
    resistance = last_24h["high"].max()

    trend  = "Bullish" if ema9 > ema21 else "Bearish"
    rsi_lbl = "Overbought" if rsi_val > 70 else ("Oversold" if rsi_val < 30 else "Neutral")
    avg_vol_4h  = last_4h["volume"].mean() if not last_4h.empty else 0
    avg_vol_all = df["volume"].mean()
    vol_signal  = "Above average" if avg_vol_4h > avg_vol_all else "Below average"

    atr_str = f"${atr_val:.4f}" if atr_val == atr_val else "N/A"

    base = (
        f"## {symbol.upper()} Short-Term Technical Analysis — 5m Candles\n"
        f"Pair: {pair} | Lookback: {look_back_days}d\n\n"
        f"**Current Price:** ${current_price:,.2f}\n\n"
        f"**Trend (EMA9 vs EMA21):** {trend}\n"
        f"- EMA9:  ${ema9:,.2f}\n"
        f"- EMA21: ${ema21:,.2f}\n\n"
        f"**RSI(9):** {rsi_val:.1f} — {rsi_lbl}\n\n"
        f"**Bollinger Bands (10, 2\u03c3):**\n"
        f"- Upper: ${bb_upper:,.2f}\n"
        f"- Lower: ${bb_lower:,.2f}\n\n"
        f"**ATR(5):** {atr_str}\n\n"
        f"**VWAP (4h):** ${vwap:,.2f}\n\n"
        f"**Recent Levels (24h):**\n"
        f"- Resistance: ${resistance:,.2f}\n"
        f"- Support:    ${support:,.2f}\n\n"
        f"**Volume (5m candles):**\n"
        f"- 4h Average:    {avg_vol_4h:,.4f} {symbol.upper()}\n"
        f"- Period Average: {avg_vol_all:,.4f} {symbol.upper()}\n"
        f"- Signal: {vol_signal}\n"
    )
    adv = format_advanced_indicators(
        df, include_td=False, include_ichimoku=False, include_candles=True
    )
    return base + adv


# ── 4-hour analysis (standard windows, 2-year lookback) ──────────────────────

def get_binance_4h_price_history(
    symbol: str,
    curr_date: str,
    look_back_days: int = 730,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """Return 4h OHLCV bars (monthly summary) for the past 2 years."""
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_4h_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return f"No Binance 4h data found for {pair} ({start.strftime('%Y-%m-%d')} to {curr_date})."

    # Aggregate to monthly for compact display
    df["month"] = df["open_time"].dt.to_period("M")
    monthly = df.groupby("month").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()

    header = (
        f"## {symbol.upper()} 4h Price History ({look_back_days}d) — Binance 4h candles\n"
        f"Pair: {pair}\n\n"
        f"{'Month':<10} {'Open':>12} {'High':>12} {'Low':>12} {'Close':>12} {'Volume':>18}\n"
        + "-" * 80 + "\n"
    )
    rows = "".join(
        f"{str(r['month']):<10} {r['open']:>12.2f} {r['high']:>12.2f} "
        f"{r['low']:>12.2f} {r['close']:>12.2f} {r['volume']:>18.4f}\n"
        for _, r in monthly.iterrows()
    )
    summary = (
        f"\n**Summary ({look_back_days}d):**\n"
        f"- Period High:    ${df['high'].max():,.2f}\n"
        f"- Period Low:     ${df['low'].min():,.2f}\n"
        f"- Latest Close:   ${df['close'].iloc[-1]:,.2f}\n"
        f"- Avg 4h Volume:  {df['volume'].mean():,.4f} {symbol.upper()}\n"
        f"- Total 4h Bars:  {len(df):,}\n"
    )
    return header + rows + summary


def get_binance_4h_technical_analysis(
    symbol: str,
    curr_date: str,
    look_back_days: int = 730,
    cache_dir: str = "./data/binance_cache",
) -> str:
    """
    Compute medium/long-term technical indicators from 4h Binance klines.
    RSI(14), EMA(50/200), MACD(12/26/9), Bollinger Bands(20,2σ),
    ATR(14), Stochastic(14,3), Volume SMA(20).
    Default lookback is 730 days (2 years).
    """
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    pair = _normalize_pair(symbol)

    df = fetch_4h_klines(symbol, start.strftime("%Y-%m-%d"), curr_date, cache_dir)
    if df is None or df.empty:
        return f"No Binance 4h data found for {pair} ({start.strftime('%Y-%m-%d')} to {curr_date})."

    closes = df["close"]
    current_price = closes.iloc[-1]

    if _TA_AVAILABLE:
        rsi_val   = _ta.momentum.RSIIndicator(close=closes, window=14).rsi().iloc[-1]
        ema50     = _ta.trend.EMAIndicator(close=closes, window=50).ema_indicator().iloc[-1]
        ema200    = _ta.trend.EMAIndicator(close=closes, window=200).ema_indicator().iloc[-1]
        macd_obj  = _ta.trend.MACD(close=closes, window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_obj.macd().iloc[-1]
        macd_sig  = macd_obj.macd_signal().iloc[-1]
        macd_hist = macd_obj.macd_diff().iloc[-1]
        bb        = _ta.volatility.BollingerBands(close=closes, window=20, window_dev=2)
        bb_upper  = bb.bollinger_hband().iloc[-1]
        bb_lower  = bb.bollinger_lband().iloc[-1]
        bb_mid    = bb.bollinger_mavg().iloc[-1]
        atr_val   = _ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=closes, window=14
        ).average_true_range().iloc[-1]
        stoch_obj = _ta.momentum.StochasticOscillator(
            high=df["high"], low=df["low"], close=closes, window=14, smooth_window=3
        )
        stoch_k = stoch_obj.stoch().iloc[-1]
        stoch_d = stoch_obj.stoch_signal().iloc[-1]
    else:
        # Manual fallback
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi_val = (100 - 100 / (1 + rs)).iloc[-1]
        ema50  = closes.ewm(span=50,  adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]
        ema12  = closes.ewm(span=12,  adjust=False).mean()
        ema26  = closes.ewm(span=26,  adjust=False).mean()
        macd_line = (ema12 - ema26).iloc[-1]
        macd_sig  = (ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1]
        macd_hist = macd_line - macd_sig
        sma20 = closes.rolling(20).mean()
        std20 = closes.rolling(20).std()
        bb_upper = (sma20 + 2 * std20).iloc[-1]
        bb_lower = (sma20 - 2 * std20).iloc[-1]
        bb_mid   = sma20.iloc[-1]
        atr_val = stoch_k = stoch_d = float("nan")

    # Volume SMA(20)
    vol_sma20 = df["volume"].rolling(20).mean().iloc[-1]
    current_vol = df["volume"].iloc[-1]
    vol_signal = "Above SMA20" if current_vol > vol_sma20 else "Below SMA20"

    # Support / resistance from last 30 4h bars (~5 days)
    last_30 = df.tail(30)
    support    = last_30["low"].min()
    resistance = last_30["high"].max()

    # Trend classification
    if ema50 > ema200:
        trend_long = "Bullish (Golden Cross)"
    else:
        trend_long = "Bearish (Death Cross)"
    trend_short = "Bullish" if current_price > ema50 else "Bearish"

    rsi_lbl = "Overbought" if rsi_val > 70 else ("Oversold" if rsi_val < 30 else "Neutral")
    macd_sig_str = "Bullish" if macd_hist > 0 else "Bearish"

    def _fmt(v): return f"${v:,.2f}" if v == v else "N/A"

    base = (
        f"## {symbol.upper()} 4h Technical Analysis — Binance 4h Candles\n"
        f"Pair: {pair} | Lookback: {look_back_days}d (~{len(df)} bars)\n\n"
        f"**Current Price:** ${current_price:,.2f}\n\n"
        f"**Long-Term Trend (EMA50 vs EMA200):** {trend_long}\n"
        f"- EMA50:  ${ema50:,.2f}\n"
        f"- EMA200: {_fmt(ema200)}\n\n"
        f"**Short-Term Trend (Price vs EMA50):** {trend_short}\n\n"
        f"**RSI(14):** {rsi_val:.1f} — {rsi_lbl}\n\n"
        f"**MACD(12,26,9):** {macd_sig_str}\n"
        f"- MACD Line:   {macd_line:+.4f}\n"
        f"- Signal Line: {macd_sig:+.4f}\n"
        f"- Histogram:   {macd_hist:+.4f}\n\n"
        f"**Bollinger Bands (20, 2\u03c3):**\n"
        f"- Upper: ${bb_upper:,.2f}\n"
        f"- Mid:   ${bb_mid:,.2f}\n"
        f"- Lower: ${bb_lower:,.2f}\n\n"
        f"**ATR(14):** {_fmt(atr_val)}\n\n"
        f"**Stochastic(14,3):**\n"
        f"- %K: {_fmt(stoch_k)}\n"
        f"- %D: {_fmt(stoch_d)}\n\n"
        f"**Recent Levels (last 30 bars, ~5 days):**\n"
        f"- Resistance: ${resistance:,.2f}\n"
        f"- Support:    ${support:,.2f}\n\n"
        f"**Volume:**\n"
        f"- Current 4h bar: {current_vol:,.4f} {symbol.upper()}\n"
        f"- SMA20:          {vol_sma20:,.4f} {symbol.upper()}\n"
        f"- Signal: {vol_signal}\n"
    )
    adv = format_advanced_indicators(df)
    return base + adv
