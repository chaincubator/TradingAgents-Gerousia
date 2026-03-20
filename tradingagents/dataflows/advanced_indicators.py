"""Advanced technical indicators.

Implements:
  - TD Sequential (DeMark): setup phase (1-9) with perfection check + countdown to 13
  - TD Combo (DeMark): stricter alternative countdown to 13
  - Ichimoku Cloud: Tenkan/Kijun/Senkou A & B/Chikou with signal interpretation
  - Japanese Candlestick Pattern recognition (23 patterns, 1-3 bar)

All public functions accept a pd.DataFrame plus explicit column-name kwargs so
they work with both Binance data (lowercase: open/high/low/close) and yfinance
data (TitleCase: Open/High/Low/Close).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Optional


# ── TD Sequential helpers ─────────────────────────────────────────────────────

def _setup_arrays(closes: pd.Series):
    """
    Bar-by-bar TD setup counts (1-9, resets to 0 after reaching 9).

    A buy setup bar: close < close[i-4].
    A sell setup bar: close > close[i-4].
    Count resets immediately when the condition is broken OR when 9 is reached,
    so each completed 9 is marked at exactly one bar.
    """
    n = len(closes)
    buy  = np.zeros(n, dtype=int)
    sell = np.zeros(n, dtype=int)
    bc = sc = 0
    for i in range(n):
        if i >= 4:
            if closes.iloc[i] < closes.iloc[i - 4]:
                bc += 1; sc = 0
            elif closes.iloc[i] > closes.iloc[i - 4]:
                sc += 1; bc = 0
            else:
                bc = sc = 0
        buy[i]  = min(bc, 9)
        sell[i] = min(sc, 9)
        if bc >= 9: bc = 0   # reset so next 9 is detectable
        if sc >= 9: sc = 0
    return buy, sell


def _find_last_9(arr: np.ndarray, lookback: int = 200) -> Optional[int]:
    """Return the index of the most recent bar where arr == 9."""
    n = len(arr)
    for i in range(n - 1, max(n - lookback - 1, -1), -1):
        if arr[i] == 9:
            return i
    return None


def _seq_countdown(
    closes: pd.Series, lows: pd.Series, highs: pd.Series,
    setup_end: int, direction: str,
) -> int:
    """
    TD Sequential countdown from setup_end+1.
    Buy:  count bars where close <= low[i-2].
    Sell: count bars where close >= high[i-2].
    Returns count (max 13).
    """
    n = len(closes)
    count = 0
    for i in range(setup_end + 1, n):
        if i < 2:
            continue
        if direction == "buy" and closes.iloc[i] <= lows.iloc[i - 2]:
            count += 1
        elif direction == "sell" and closes.iloc[i] >= highs.iloc[i - 2]:
            count += 1
        if count >= 13:
            break
    return count


def _combo_countdown(
    closes: pd.Series, lows: pd.Series, highs: pd.Series,
    setup_end: int, direction: str,
) -> int:
    """
    TD Combo countdown — stricter than Sequential.
    Buy:  close <= low[i-2] AND close <= close[i-1].
    Sell: close >= high[i-2] AND close >= close[i-1].
    Returns count (max 13).
    """
    n = len(closes)
    count = 0
    for i in range(setup_end + 1, n):
        if i < 2:
            continue
        if direction == "buy":
            if closes.iloc[i] <= lows.iloc[i - 2] and closes.iloc[i] <= closes.iloc[i - 1]:
                count += 1
        else:
            if closes.iloc[i] >= highs.iloc[i - 2] and closes.iloc[i] >= closes.iloc[i - 1]:
                count += 1
        if count >= 13:
            break
    return count


def _perfected_buy(lows: pd.Series, idx: int) -> bool:
    """Perfected buy: bar 8 or bar 9 low <= min(bar 6 low, bar 7 low)."""
    try:
        ref = min(float(lows.iloc[idx - 3]), float(lows.iloc[idx - 2]))
        return float(lows.iloc[idx - 1]) <= ref or float(lows.iloc[idx]) <= ref
    except (IndexError, ValueError):
        return False


def _perfected_sell(highs: pd.Series, idx: int) -> bool:
    """Perfected sell: bar 8 or bar 9 high >= max(bar 6 high, bar 7 high)."""
    try:
        ref = max(float(highs.iloc[idx - 3]), float(highs.iloc[idx - 2]))
        return float(highs.iloc[idx - 1]) >= ref or float(highs.iloc[idx]) >= ref
    except (IndexError, ValueError):
        return False


# ── TD Sequential ─────────────────────────────────────────────────────────────

def compute_td_sequential(
    df: pd.DataFrame,
    close_col: str = "close",
    high_col:  str = "high",
    low_col:   str = "low",
) -> dict:
    """
    Compute TD Sequential (DeMark) setup + countdown.

    Returns:
        current_buy_count    active buy-setup bar count (0 = not in a buy setup)
        current_sell_count   active sell-setup bar count
        current_direction    "BUY_SETUP" | "SELL_SETUP" | "NONE"
        last_buy9_bars_ago   bars since most recent completed buy-9  (None = not found)
        last_sell9_bars_ago  bars since most recent completed sell-9
        last_buy9_perfected  bool — perfected buy setup
        last_sell9_perfected bool — perfected sell setup
        buy_countdown        Sequential countdown count from last buy-9 (0-13)
        sell_countdown       Sequential countdown count from last sell-9 (0-13)
    """
    closes = df[close_col]
    highs  = df[high_col]
    lows   = df[low_col]
    n      = len(closes)

    buy_arr, sell_arr = _setup_arrays(closes)

    cur_buy  = int(buy_arr[-1])
    cur_sell = int(sell_arr[-1])
    direction = ("BUY_SETUP"  if cur_buy  > 0 else
                 "SELL_SETUP" if cur_sell > 0 else "NONE")

    last_buy9  = _find_last_9(buy_arr)
    last_sell9 = _find_last_9(sell_arr)

    buy_cd  = _seq_countdown(closes, lows, highs, last_buy9,  "buy")  if last_buy9  is not None else 0
    sell_cd = _seq_countdown(closes, lows, highs, last_sell9, "sell") if last_sell9 is not None else 0

    return {
        "current_buy_count":    cur_buy,
        "current_sell_count":   cur_sell,
        "current_direction":    direction,
        "last_buy9_bars_ago":   (n - 1 - last_buy9)  if last_buy9  is not None else None,
        "last_sell9_bars_ago":  (n - 1 - last_sell9) if last_sell9 is not None else None,
        "last_buy9_perfected":  _perfected_buy(lows,   last_buy9)  if last_buy9  is not None else False,
        "last_sell9_perfected": _perfected_sell(highs, last_sell9) if last_sell9 is not None else False,
        "buy_countdown":        buy_cd,
        "sell_countdown":       sell_cd,
    }


# ── TD Combo ──────────────────────────────────────────────────────────────────

def compute_td_combo(
    df: pd.DataFrame,
    close_col: str = "close",
    high_col:  str = "high",
    low_col:   str = "low",
) -> dict:
    """
    Compute TD Combo countdown (alternative DeMark countdown with stricter bars).

    Returns:
        buy_count   combo countdown from last buy-9 (0-13)
        sell_count  combo countdown from last sell-9 (0-13)
        last_signal "BUY_13" | "SELL_13" | "BUY_COMBO_N" | "SELL_COMBO_N" | "NONE"
        last_buy9_bars_ago / last_sell9_bars_ago
    """
    closes = df[close_col]
    highs  = df[high_col]
    lows   = df[low_col]
    n      = len(closes)

    buy_arr, sell_arr = _setup_arrays(closes)
    last_buy9  = _find_last_9(buy_arr)
    last_sell9 = _find_last_9(sell_arr)

    buy_cd  = _combo_countdown(closes, lows, highs, last_buy9,  "buy")  if last_buy9  is not None else 0
    sell_cd = _combo_countdown(closes, lows, highs, last_sell9, "sell") if last_sell9 is not None else 0

    if buy_cd >= 13:
        last_signal = "BUY_13"
    elif sell_cd >= 13:
        last_signal = "SELL_13"
    elif buy_cd > 0 or sell_cd > 0:
        dominant    = "BUY" if buy_cd >= sell_cd else "SELL"
        last_signal = f"{dominant}_COMBO_{max(buy_cd, sell_cd)}"
    else:
        last_signal = "NONE"

    return {
        "buy_count":           buy_cd,
        "sell_count":          sell_cd,
        "last_signal":         last_signal,
        "last_buy9_bars_ago":  (n - 1 - last_buy9)  if last_buy9  is not None else None,
        "last_sell9_bars_ago": (n - 1 - last_sell9) if last_sell9 is not None else None,
    }


# ── Ichimoku Cloud ────────────────────────────────────────────────────────────

def compute_ichimoku(
    df: pd.DataFrame,
    high_col:        str = "high",
    low_col:         str = "low",
    close_col:       str = "close",
    tenkan_period:   int = 9,
    kijun_period:    int = 26,
    senkou_b_period: int = 52,
    displacement:    int = 26,
) -> dict:
    """
    Compute all five Ichimoku lines and interpret signals.

    Cloud at the current bar = Senkou A/B values that were calculated
    `displacement` bars ago and projected forward.

    Returns a dict of current values and signal strings.
    Returns {"error": "..."} if insufficient bars.
    """
    highs  = df[high_col]
    lows   = df[low_col]
    closes = df[close_col]
    n = len(closes)

    min_bars = senkou_b_period + displacement
    if n < min_bars:
        return {"error": f"Need >= {min_bars} bars for Ichimoku (have {n})"}

    tenkan = (highs.rolling(tenkan_period).max()  + lows.rolling(tenkan_period).min())  / 2
    kijun  = (highs.rolling(kijun_period).max()   + lows.rolling(kijun_period).min())   / 2
    senku_b_raw = (highs.rolling(senkou_b_period).max() + lows.rolling(senkou_b_period).min()) / 2

    # Cloud values at the current bar (shifted forward from displacement bars ago)
    senkou_a_s = ((tenkan + kijun) / 2).shift(displacement)
    senkou_b_s = senku_b_raw.shift(displacement)

    cur_tenkan = float(tenkan.iloc[-1])
    cur_kijun  = float(kijun.iloc[-1])

    raw_spa = senkou_a_s.iloc[-1]
    raw_spb = senkou_b_s.iloc[-1]
    cur_spa = float(raw_spa) if not pd.isna(raw_spa) else float("nan")
    cur_spb = float(raw_spb) if not pd.isna(raw_spb) else float("nan")

    # Future cloud 26 bars ahead (current unshifted Senkou values)
    fut_spa = float((cur_tenkan + cur_kijun) / 2)
    fut_spb = float(senku_b_raw.iloc[-1])

    cur_close = float(closes.iloc[-1])

    # Cloud boundaries at current bar
    if not (pd.isna(cur_spa) or pd.isna(cur_spb)):
        cloud_top    = max(cur_spa, cur_spb)
        cloud_bottom = min(cur_spa, cur_spb)
        cloud_color  = "Bullish (Green)" if cur_spa > cur_spb else "Bearish (Red)"
        if cur_close > cloud_top:
            price_vs_cloud = "Above Cloud — Bullish"
        elif cur_close < cloud_bottom:
            price_vs_cloud = "Below Cloud — Bearish"
        else:
            price_vs_cloud = "Inside Cloud — Neutral/Consolidation"
    else:
        cloud_top = cloud_bottom = float("nan")
        cloud_color = "N/A"
        price_vs_cloud = "N/A"

    # Tenkan / Kijun cross (compare last two bars)
    tk_cross = "None"
    if n >= 2:
        prev_t = tenkan.iloc[-2]
        prev_k = kijun.iloc[-2]
        if not any(pd.isna(v) for v in [prev_t, prev_k]):
            if float(prev_t) <= float(prev_k) and cur_tenkan > cur_kijun:
                tk_cross = "Bullish TK Cross (Tenkan crossed above Kijun)"
            elif float(prev_t) >= float(prev_k) and cur_tenkan < cur_kijun:
                tk_cross = "Bearish TK Cross (Tenkan crossed below Kijun)"

    # TK relative position
    if cur_tenkan > cur_kijun:
        tk_position = "Tenkan above Kijun — Bullish bias"
    elif cur_tenkan < cur_kijun:
        tk_position = "Tenkan below Kijun — Bearish bias"
    else:
        tk_position = "Tenkan == Kijun — Neutral"

    # Chikou Span: current close vs price displacement bars ago
    chikou_signal = "N/A"
    if n > displacement + 1:
        price_d_ago = float(closes.iloc[-displacement - 1])
        if cur_close > price_d_ago:
            chikou_signal = f"Bullish (close {cur_close:.4g} > price {displacement}d ago {price_d_ago:.4g})"
        elif cur_close < price_d_ago:
            chikou_signal = f"Bearish (close {cur_close:.4g} < price {displacement}d ago {price_d_ago:.4g})"
        else:
            chikou_signal = "Neutral"

    fut_cloud_color = ("Bullish (Green)" if fut_spa > fut_spb else
                       "Bearish (Red)"   if fut_spa < fut_spb else "Neutral")

    return {
        "tenkan_sen":      cur_tenkan,
        "kijun_sen":       cur_kijun,
        "cloud_top":       cloud_top,
        "cloud_bottom":    cloud_bottom,
        "cloud_color":     cloud_color,
        "future_cloud":    fut_cloud_color,
        "future_senkou_a": fut_spa,
        "future_senkou_b": fut_spb,
        "price_vs_cloud":  price_vs_cloud,
        "tk_cross":        tk_cross,
        "tk_position":     tk_position,
        "chikou_signal":   chikou_signal,
        "current_close":   cur_close,
    }


# ── Japanese Candlestick Patterns ─────────────────────────────────────────────

def detect_candlestick_patterns(
    df: pd.DataFrame,
    open_col:  str = "open",
    high_col:  str = "high",
    low_col:   str = "low",
    close_col: str = "close",
    lookback:  int = 5,
) -> List[dict]:
    """
    Detect Japanese candlestick patterns in the most recent `lookback` bars.

    Recognised patterns (23 total):
      Single-bar:  Doji, Gravestone Doji, Dragonfly Doji, Long-Legged Doji,
                   Bullish/Bearish Marubozu, Hammer, Hanging Man,
                   Shooting Star, Inverted Hammer, Spinning Top
      Two-bar:     Bullish/Bearish Engulfing, Bullish/Bearish Harami,
                   Tweezer Bottom/Top, Dark Cloud Cover, Piercing Pattern
      Three-bar:   Morning Star, Evening Star,
                   Three White Soldiers, Three Black Crows

    Returns list of dicts sorted by recency (bar=0 is current bar).
    """
    n   = len(df)
    # Include 2 extra bars so three-bar patterns can reference i-2
    start = max(0, n - lookback - 2)
    sub   = df.iloc[start:n]
    m     = len(sub)
    if m < 1:
        return []

    o_arr = sub[open_col].values.astype(float)
    h_arr = sub[high_col].values.astype(float)
    l_arr = sub[low_col].values.astype(float)
    c_arr = sub[close_col].values.astype(float)

    detected: List[dict] = []

    def add(i: int, name: str, signal: str, desc: str):
        detected.append({"name": name, "signal": signal, "bar": (m - 1) - i, "desc": desc})

    # Iterate most-recent bars first (but we iterate forward then sort)
    start_i = max(0, m - lookback - 1)
    for i in range(start_i, m):
        o, h, l, c = o_arr[i], h_arr[i], l_arr[i], c_arr[i]
        rng  = h - l
        if rng < 1e-10:
            continue
        body    = abs(c - o)
        uw      = h - max(o, c)    # upper wick
        lw      = min(o, c) - l    # lower wick
        body_pct = body / rng
        bull     = c > o

        # ── Single-bar patterns ─────────────────────────────────────────────
        if body_pct < 0.10:
            # Doji family
            if uw > rng * 0.30 and lw < rng * 0.05:
                add(i, "Gravestone Doji", "BEARISH",
                    "Open~Close~Low, long upper shadow — bearish reversal signal")
            elif lw > rng * 0.30 and uw < rng * 0.05:
                add(i, "Dragonfly Doji", "BULLISH",
                    "Open~Close~High, long lower shadow — bullish reversal signal")
            elif uw > rng * 0.30 and lw > rng * 0.30:
                add(i, "Long-Legged Doji", "NEUTRAL",
                    "Long wicks both sides — indecision, watch for breakout direction")
            else:
                add(i, "Doji", "NEUTRAL",
                    "Open~Close — market indecision, potential reversal or continuation")
        elif body_pct > 0.92 and uw < rng * 0.04 and lw < rng * 0.04:
            add(i, "Bullish Marubozu" if bull else "Bearish Marubozu",
                "BULLISH" if bull else "BEARISH",
                "Full-bodied candle, no wicks — strong directional pressure")
        elif body_pct < 0.40 and lw >= 2.0 * body and uw <= 0.10 * rng:
            add(i, "Hammer" if bull else "Hanging Man",
                "BULLISH" if bull else "BEARISH",
                "Small body at top, long lower shadow — " +
                ("bullish reversal after downtrend" if bull else "bearish reversal after uptrend"))
        elif body_pct < 0.40 and uw >= 2.0 * body and lw <= 0.10 * rng:
            add(i, "Inverted Hammer" if bull else "Shooting Star",
                "BULLISH" if bull else "BEARISH",
                "Small body at bottom, long upper shadow — " +
                ("potential bullish reversal" if bull else "bearish reversal after uptrend"))
        elif body_pct < 0.40 and uw > body * 0.50 and lw > body * 0.50:
            add(i, "Spinning Top", "NEUTRAL",
                "Small body with wicks both sides — indecision")

        # ── Two-bar patterns ────────────────────────────────────────────────
        if i >= 1:
            po, ph, pl, pc = o_arr[i-1], h_arr[i-1], l_arr[i-1], c_arr[i-1]
            prev_body = abs(pc - po)
            prev_bull = pc > po

            if (not prev_bull and bull and
                    body >= prev_body * 0.90 and o <= pc and c >= po):
                add(i, "Bullish Engulfing", "BULLISH",
                    "Current bullish bar fully engulfs prior bearish bar — strong reversal")
            elif (prev_bull and not bull and
                    body >= prev_body * 0.90 and o >= pc and c <= po):
                add(i, "Bearish Engulfing", "BEARISH",
                    "Current bearish bar fully engulfs prior bullish bar — strong reversal")
            elif (not prev_bull and bull and
                    o > pc and c < po and body < prev_body * 0.60):
                add(i, "Bullish Harami", "BULLISH",
                    "Small bullish bar inside larger bearish bar — potential reversal")
            elif (prev_bull and not bull and
                    o < pc and c > po and body < prev_body * 0.60):
                add(i, "Bearish Harami", "BEARISH",
                    "Small bearish bar inside larger bullish bar — potential reversal")
            elif abs(l - pl) / rng < 0.03 and bull and not prev_bull:
                add(i, "Tweezer Bottom", "BULLISH",
                    "Matching lows — strong support rejection, potential upward reversal")
            elif abs(h - ph) / rng < 0.03 and not bull and prev_bull:
                add(i, "Tweezer Top", "BEARISH",
                    "Matching highs — strong resistance rejection, potential downward reversal")
            elif (prev_bull and not bull and
                    o > ph and c < (po + pc) / 2 and c > po):
                add(i, "Dark Cloud Cover", "BEARISH",
                    "Opens above prior high, closes deep into prior body — bearish reversal")
            elif (not prev_bull and bull and
                    o < pl and c > (po + pc) / 2 and c < po):
                add(i, "Piercing Pattern", "BULLISH",
                    "Opens below prior low, closes deep into prior body — bullish reversal")

        # ── Three-bar patterns ──────────────────────────────────────────────
        if i >= 2:
            p2o, p2h, p2l, p2c = o_arr[i-2], h_arr[i-2], l_arr[i-2], c_arr[i-2]
            p1o, p1h, p1l, p1c = o_arr[i-1], h_arr[i-1], l_arr[i-1], c_arr[i-1]
            p2_bull  = p2c > p2o
            p1_rng   = p1h - p1l
            p1_body  = abs(p1c - p1o)
            p1_small = (p1_body / p1_rng < 0.35) if p1_rng > 1e-10 else True

            if not p2_bull and p1_small and bull and c > (p2o + p2c) / 2:
                add(i, "Morning Star", "BULLISH",
                    "Bearish + small body + bullish above midpoint — strong bullish reversal")
            elif p2_bull and p1_small and not bull and c < (p2o + p2c) / 2:
                add(i, "Evening Star", "BEARISH",
                    "Bullish + small body + bearish below midpoint — strong bearish reversal")
            else:
                # Three White Soldiers / Three Black Crows (checked separately)
                p2_rng  = p2h - p2l
                p2_body = abs(p2c - p2o)
                p1_rng2 = p1h - p1l
                p1_body2 = abs(p1c - p1o)
                strong_p2 = (p2_body / p2_rng > 0.60) if p2_rng > 1e-10 else False
                strong_p1 = (p1_body2 / p1_rng2 > 0.60) if p1_rng2 > 1e-10 else False

                if (p2c > p2o and p1c > p1o and bull and
                        p1c > p2c and c > p1c and strong_p2 and strong_p1):
                    add(i, "Three White Soldiers", "BULLISH",
                        "Three consecutive strong bullish bars — strong bullish continuation")
                elif (p2c < p2o and p1c < p1o and not bull and
                        p1c < p2c and c < p1c and strong_p2 and strong_p1):
                    add(i, "Three Black Crows", "BEARISH",
                        "Three consecutive strong bearish bars — strong bearish continuation")

    detected.sort(key=lambda x: x["bar"])
    return detected


# ── Formatters ────────────────────────────────────────────────────────────────

def _fv(v, fmt=",.2f") -> str:
    """Format a numeric value; returns 'N/A' for NaN or errors."""
    try:
        fv = float(v)
        return format(fv, fmt) if fv == fv else "N/A"
    except (TypeError, ValueError):
        return "N/A"


def _format_td_sequential(td: dict) -> str:
    if "error" in td:
        return f"**TD Sequential:** {td['error']}"
    lines = ["**TD Sequential (DeMark):**"]
    d = td["current_direction"]
    if d == "BUY_SETUP":
        cnt    = td["current_buy_count"]
        suffix = " <- SETUP COMPLETE" if cnt == 9 else ""
        lines.append(f"- Active Buy Setup: {cnt}/9{suffix}")
    elif d == "SELL_SETUP":
        cnt    = td["current_sell_count"]
        suffix = " <- SETUP COMPLETE" if cnt == 9 else ""
        lines.append(f"- Active Sell Setup: {cnt}/9{suffix}")
    else:
        lines.append("- No active setup in progress")

    if td["last_buy9_bars_ago"] is not None:
        pf  = " (Perfected)" if td["last_buy9_perfected"] else ""
        cd  = td["buy_countdown"]
        sfx = " <- COUNTDOWN COMPLETE" if cd >= 13 else ""
        lines.append(f"- Last Buy-9{pf}: {td['last_buy9_bars_ago']} bars ago | "
                     f"Countdown: {cd}/13{sfx}")
    if td["last_sell9_bars_ago"] is not None:
        pf  = " (Perfected)" if td["last_sell9_perfected"] else ""
        cd  = td["sell_countdown"]
        sfx = " <- COUNTDOWN COMPLETE" if cd >= 13 else ""
        lines.append(f"- Last Sell-9{pf}: {td['last_sell9_bars_ago']} bars ago | "
                     f"Countdown: {cd}/13{sfx}")
    return "\n".join(lines)


def _format_td_combo(tc: dict) -> str:
    if "error" in tc:
        return f"**TD Combo:** {tc['error']}"
    lines = ["**TD Combo (DeMark):**"]
    sig = tc["last_signal"]
    if sig == "NONE":
        lines.append("- No active TD Combo signal")
    elif sig == "BUY_13":
        lines.append("- BUY COMBO 13 COMPLETE <- potential bullish reversal")
    elif sig == "SELL_13":
        lines.append("- SELL COMBO 13 COMPLETE <- potential bearish reversal")
    else:
        lines.append(f"- Active signal: {sig}")
    if tc["last_buy9_bars_ago"] is not None:
        lines.append(f"- Buy setup-9 was {tc['last_buy9_bars_ago']} bars ago | "
                     f"Combo count: {tc['buy_count']}/13")
    if tc["last_sell9_bars_ago"] is not None:
        lines.append(f"- Sell setup-9 was {tc['last_sell9_bars_ago']} bars ago | "
                     f"Combo count: {tc['sell_count']}/13")
    return "\n".join(lines)


def _format_ichimoku(ic: dict) -> str:
    if "error" in ic:
        return f"**Ichimoku Cloud:** {ic['error']}"
    lines = [
        "**Ichimoku Cloud (9/26/52 | displacement 26):**",
        f"- Tenkan-sen (9):        {_fv(ic['tenkan_sen'])}",
        f"- Kijun-sen (26):        {_fv(ic['kijun_sen'])}",
        f"- Senkou Span A (cloud): {_fv(ic['cloud_top'])} / {_fv(ic['cloud_bottom'])}  [{ic['cloud_color']}]",
        f"- Future Cloud (26 bars): Senkou A={_fv(ic['future_senkou_a'])}  "
        f"Senkou B={_fv(ic['future_senkou_b'])}  [{ic['future_cloud']}]",
        f"- Price vs Cloud:        {ic['price_vs_cloud']}",
        f"- Tenkan/Kijun:          {ic['tk_position']}",
        f"- TK Cross:              {ic['tk_cross']}",
        f"- Chikou Span:           {ic['chikou_signal']}",
    ]
    return "\n".join(lines)


def _format_patterns(patterns: List[dict]) -> str:
    if not patterns:
        return "**Candlestick Patterns:** No significant patterns detected in recent bars."
    tag = {"BULLISH": "[BULL]", "BEARISH": "[BEAR]", "NEUTRAL": "[NEUT]"}
    lines = ["**Candlestick Patterns (last 5 bars):**"]
    for p in patterns:
        bar_str = "Current bar" if p["bar"] == 0 else f"{p['bar']} bar(s) ago"
        lines.append(f"- {tag.get(p['signal'], '')} {p['name']} ({bar_str}): {p['desc']}")
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def format_advanced_indicators(
    df: pd.DataFrame,
    open_col:         str  = "open",
    high_col:         str  = "high",
    low_col:          str  = "low",
    close_col:        str  = "close",
    include_td:       bool = True,
    include_ichimoku: bool = True,
    include_candles:  bool = True,
) -> str:
    """
    Compute and format all advanced indicators as a Markdown section.

    Appended to the main analysis report string.  Silently skips any
    indicator where there is insufficient data.

    Args:
        df               OHLCV DataFrame (Binance lowercase or yfinance TitleCase).
        open/high/low/close_col  Column name overrides for non-default schemas.
        include_td       Run TD Sequential + TD Combo (needs >= 13 bars).
        include_ichimoku Run Ichimoku Cloud (needs >= 78 bars).
        include_candles  Detect candlestick patterns in last 5 bars.
    """
    if df is None or len(df) < 5:
        return ""

    parts = ["\n---\n### Advanced Technical Indicators\n"]

    if include_td and len(df) >= 13:
        try:
            td = compute_td_sequential(df, close_col, high_col, low_col)
            parts.append(_format_td_sequential(td))
        except Exception as e:
            parts.append(f"**TD Sequential:** Error — {e}")
        parts.append("")
        try:
            tc = compute_td_combo(df, close_col, high_col, low_col)
            parts.append(_format_td_combo(tc))
        except Exception as e:
            parts.append(f"**TD Combo:** Error — {e}")
        parts.append("")

    if include_ichimoku:
        min_bars = 52 + 26   # senkou_b_period + displacement
        if len(df) >= min_bars:
            try:
                ic = compute_ichimoku(df, high_col, low_col, close_col)
                parts.append(_format_ichimoku(ic))
            except Exception as e:
                parts.append(f"**Ichimoku Cloud:** Error — {e}")
        else:
            parts.append(f"**Ichimoku Cloud:** Need >= {min_bars} bars (have {len(df)})")
        parts.append("")

    if include_candles:
        try:
            pats = detect_candlestick_patterns(
                df, open_col, high_col, low_col, close_col, lookback=5
            )
            parts.append(_format_patterns(pats))
        except Exception as e:
            parts.append(f"**Candlestick Patterns:** Error — {e}")

    return "\n".join(parts) + "\n"
