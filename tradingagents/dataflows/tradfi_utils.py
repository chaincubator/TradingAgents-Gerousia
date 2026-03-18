"""TradFi instrument utilities.

Covers commodities (Gold, Silver, Oil), equity indices (S&P 500, NASDAQ 100),
country ETFs (EWY, EWZ, EWJ …), sector ETFs, fixed income ETFs, and FX pairs
— all of which trade as perpetual futures on Binance and/or Hyperliquid.xyz.

For analysis the *underlying* TradFi price series is fetched from Yahoo Finance
rather than the perp itself, giving accurate spot/futures prices free from
funding-rate or basis distortions.

Key public API
--------------
classify_symbol(ticker) → "crypto" | "tradfi" | "stock"
get_tradfi_price_history(symbol, start_date, end_date) → str
get_tradfi_technical_analysis(symbol, curr_date, look_back_days) → str
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

# ── Symbol registry ──────────────────────────────────────────────────────────
# Maps the perp ticker (Binance/Hyperliquid) to the underlying Yahoo Finance
# ticker used for price data.

TRADFI_SYMBOLS: dict = {
    # ── Precious Metals ───────────────────────────────────────────────────
    "GOLD":     "GC=F",    # CME Gold Futures
    "XAUUSD":   "GC=F",
    "GLD":      "GLD",     # SPDR Gold ETF
    "IAU":      "IAU",     # iShares Gold ETF
    "SILVER":   "SI=F",    # CME Silver Futures
    "XAGUSD":   "SI=F",
    "SLV":      "SLV",     # iShares Silver ETF
    "PLATINUM": "PL=F",
    "PALLADIUM":"PA=F",

    # ── Energy ────────────────────────────────────────────────────────────
    "OIL":      "CL=F",    # WTI Crude Futures
    "CRUDE":    "CL=F",
    "WTI":      "CL=F",
    "BRENT":    "BZ=F",
    "NATGAS":   "NG=F",    # Natural Gas
    "NG":       "NG=F",
    "USO":      "USO",     # US Oil Fund ETF
    "UNG":      "UNG",     # US Natural Gas ETF

    # ── Base Metals ───────────────────────────────────────────────────────
    "COPPER":   "HG=F",
    "ALUMINUM": "ALI=F",

    # ── Agricultural ─────────────────────────────────────────────────────
    "WHEAT":    "ZW=F",
    "CORN":     "ZC=F",
    "SOYBEAN":  "ZS=F",

    # ── US Equity Indices ─────────────────────────────────────────────────
    "SPX":      "^GSPC",   # S&P 500
    "ES":       "^GSPC",   # S&P 500 E-mini
    "SPY":      "SPY",
    "VOO":      "VOO",
    "NDX":      "^NDX",    # NASDAQ 100
    "NQ":       "QQQ",     # NASDAQ 100 E-mini
    "QQQ":      "QQQ",
    "DJI":      "^DJI",    # Dow Jones
    "YM":       "^DJI",
    "DIA":      "DIA",
    "RUT":      "^RUT",    # Russell 2000
    "RTY":      "^RUT",
    "IWM":      "IWM",
    "VIX":      "^VIX",    # CBOE Volatility Index

    # ── International Country ETFs ────────────────────────────────────────
    "EWY":      "EWY",     # South Korea
    "EWZ":      "EWZ",     # Brazil
    "EWJ":      "EWJ",     # Japan
    "EWG":      "EWG",     # Germany
    "EWU":      "EWU",     # United Kingdom
    "EWA":      "EWA",     # Australia
    "EWC":      "EWC",     # Canada
    "EWT":      "EWT",     # Taiwan
    "EWH":      "EWH",     # Hong Kong
    "FXI":      "FXI",     # China Large-Cap
    "MCHI":     "MCHI",    # MSCI China
    "EEM":      "EEM",     # MSCI Emerging Markets
    "VWO":      "VWO",     # Vanguard Emerging Markets
    "EFA":      "EFA",     # MSCI EAFE (Developed ex-US)

    # ── US Sector ETFs ────────────────────────────────────────────────────
    "XLE":      "XLE",     # Energy
    "XLF":      "XLF",     # Financials
    "XLK":      "XLK",     # Technology
    "XLV":      "XLV",     # Healthcare
    "XLI":      "XLI",     # Industrials
    "XLU":      "XLU",     # Utilities
    "XLP":      "XLP",     # Consumer Staples
    "XLY":      "XLY",     # Consumer Discretionary
    "XLB":      "XLB",     # Materials
    "XLRE":     "XLRE",    # Real Estate
    "GDX":      "GDX",     # Gold Miners
    "GDXJ":     "GDXJ",    # Junior Gold Miners
    "KRE":      "KRE",     # Regional Banks
    "SMH":      "SMH",     # Semiconductors

    # ── Fixed Income ──────────────────────────────────────────────────────
    "TLT":      "TLT",     # 20+ Year Treasury
    "IEF":      "IEF",     # 7-10 Year Treasury
    "SHY":      "SHY",     # 1-3 Year Treasury
    "HYG":      "HYG",     # High-Yield Corporate
    "LQD":      "LQD",     # Investment-Grade Corporate
    "EMB":      "EMB",     # EM Bonds

    # ── FX (vs USD) ───────────────────────────────────────────────────────
    "EUR":      "EURUSD=X",
    "GBP":      "GBPUSD=X",
    "JPY":      "JPY=X",
    "AUD":      "AUDUSD=X",
    "CHF":      "CHF=X",
    "CAD":      "CADUSD=X",
    "CNH":      "CNHUSD=X",

    # ── Broad Commodity ───────────────────────────────────────────────────
    "DBC":      "DBC",     # Invesco DB Commodity Index
    "PDBC":     "PDBC",    # Optimum Yield Diversified Commodity
}

# Human-readable metadata used in analyst system prompts
INSTRUMENT_INFO: dict = {
    "GOLD":    {"type": "precious_metal",  "name": "Gold",          "perps": "Binance GOLDUSDT, Hyperliquid GOLD"},
    "SILVER":  {"type": "precious_metal",  "name": "Silver",        "perps": "Hyperliquid SILVER"},
    "OIL":     {"type": "energy",          "name": "WTI Crude Oil", "perps": "Binance OILUSDT, Hyperliquid OIL"},
    "WTI":     {"type": "energy",          "name": "WTI Crude Oil", "perps": "Binance OILUSDT, Hyperliquid OIL"},
    "NATGAS":  {"type": "energy",          "name": "Natural Gas",   "perps": "Hyperliquid NATGAS"},
    "COPPER":  {"type": "base_metal",      "name": "Copper",        "perps": "Hyperliquid COPPER"},
    "SPX":     {"type": "equity_index",    "name": "S&P 500",       "perps": "Hyperliquid SPX"},
    "NDX":     {"type": "equity_index",    "name": "NASDAQ 100",    "perps": "Hyperliquid NDX"},
    "RUT":     {"type": "equity_index",    "name": "Russell 2000",  "perps": "Hyperliquid RUT"},
    "SPY":     {"type": "etf",             "name": "SPDR S&P 500 ETF",   "perps": "Hyperliquid SPY"},
    "QQQ":     {"type": "etf",             "name": "Invesco QQQ ETF",    "perps": "Hyperliquid QQQ"},
    "IWM":     {"type": "etf",             "name": "iShares Russell 2000 ETF", "perps": "Hyperliquid IWM"},
    "EWY":     {"type": "country_etf",     "name": "iShares MSCI South Korea ETF", "perps": "Hyperliquid EWY"},
    "EWZ":     {"type": "country_etf",     "name": "iShares MSCI Brazil ETF",      "perps": "Hyperliquid EWZ"},
    "EWJ":     {"type": "country_etf",     "name": "iShares MSCI Japan ETF",       "perps": "Hyperliquid EWJ"},
    "FXI":     {"type": "country_etf",     "name": "iShares China Large-Cap ETF",  "perps": "Hyperliquid FXI"},
    "EEM":     {"type": "country_etf",     "name": "iShares MSCI EM ETF",          "perps": "Hyperliquid EEM"},
    "TLT":     {"type": "fixed_income",    "name": "iShares 20+ Year Treasury ETF", "perps": "Hyperliquid TLT"},
    "GLD":     {"type": "precious_metal",  "name": "SPDR Gold ETF", "perps": "Hyperliquid GLD"},
    "GDX":     {"type": "sector_etf",      "name": "VanEck Gold Miners ETF", "perps": "Hyperliquid GDX"},
    "XLE":     {"type": "sector_etf",      "name": "Energy Select Sector SPDR", "perps": "Hyperliquid XLE"},
}

# Known crypto symbols — these take priority if matched before the TradFi list
_CRYPTO_SYMBOLS = {
    'BTC', 'ETH', 'ADA', 'SOL', 'DOT', 'AVAX', 'MATIC', 'LINK', 'UNI', 'AAVE',
    'XRP', 'LTC', 'BCH', 'EOS', 'TRX', 'XLM', 'VET', 'ALGO', 'ATOM', 'LUNA',
    'NEAR', 'FTM', 'CRO', 'SAND', 'MANA', 'AXS', 'GALA', 'ENJ', 'CHZ', 'BAT',
    'ZEC', 'DASH', 'XMR', 'DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BNB', 'USDT', 'USDC',
    'TON', 'ICP', 'HBAR', 'THETA', 'FIL', 'ETC', 'MKR', 'APT', 'LDO', 'OP',
    'IMX', 'GRT', 'RUNE', 'FLOW', 'EGLD', 'XTZ', 'MINA', 'ROSE', 'KAVA',
    'SUI', 'SEI', 'ARB', 'BLUR', 'WLD', 'STX', 'INJ', 'TIA', 'PYTH', 'JUP',
}

# Known individual stock symbols — these fall through to stock routing
_STOCK_SYMBOLS = {
    'AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'NFLX', 'DIS', 'AMD',
    'INTC', 'CRM', 'ORCL', 'ADBE', 'CSCO', 'PEP', 'KO', 'WMT', 'JNJ', 'PFE',
    'V', 'MA', 'HD', 'UNH', 'BAC', 'XOM', 'CVX', 'LLY', 'ABBV', 'COST',
    'AVGO', 'TMO', 'ACN', 'DHR', 'TXN', 'LOW', 'QCOM', 'HON', 'UPS', 'MDT',
}


def classify_symbol(symbol: str) -> str:
    """
    Return the instrument class for routing decisions.

    Returns one of:
      "crypto"  — cryptocurrency (uses Binance kline data)
      "tradfi"  — TradFi instrument with perp futures on Binance/Hyperliquid
                  (uses Yahoo Finance underlying price data)
      "stock"   — individual equity (uses yfinance / Finnhub data)
    """
    s = symbol.upper().strip()
    if s in _CRYPTO_SYMBOLS:
        return "crypto"
    if s in TRADFI_SYMBOLS:
        return "tradfi"
    if s in _STOCK_SYMBOLS:
        return "stock"
    # Heuristic fall-through: short unknown symbols treated as crypto,
    # longer ones as stock
    if len(s) <= 4 and s.isalpha():
        return "crypto"
    return "stock"


def get_yf_ticker(symbol: str) -> str:
    """Return the Yahoo Finance ticker for a TradFi perp symbol."""
    return TRADFI_SYMBOLS.get(symbol.upper(), symbol)


def get_instrument_info(symbol: str) -> dict:
    """Return metadata dict; falls back to a generic entry."""
    s = symbol.upper()
    if s in INSTRUMENT_INFO:
        return INSTRUMENT_INFO[s]
    yf = TRADFI_SYMBOLS.get(s, s)
    return {"type": "tradfi", "name": s, "perps": "Hyperliquid / Binance", "yf_ticker": yf}


# ── Price history ─────────────────────────────────────────────────────────────

def get_tradfi_price_history(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> str:
    """
    Fetch OHLCV price history for a TradFi instrument via Yahoo Finance.

    Args:
        symbol:     Perp ticker (e.g. "GOLD", "EWY", "SPX")
        start_date: "YYYY-MM-DD"
        end_date:   "YYYY-MM-DD"
        interval:   yfinance interval string (default "1d")

    Returns:
        Formatted Markdown table of daily OHLCV + summary statistics.
    """
    yf_tick = get_yf_ticker(symbol)
    info    = get_instrument_info(symbol)
    try:
        df = yf.Ticker(yf_tick).history(
            start=start_date, end=end_date, interval=interval
        )
    except Exception as e:
        return f"Error fetching {symbol} ({yf_tick}): {e}"

    if df is None or df.empty:
        return f"No data found for {symbol} ({yf_tick}) from {start_date} to {end_date}."

    header = (
        f"## {symbol.upper()} Price History\n"
        f"**Instrument:** {info['name']}  |  **Type:** {info['type']}  |  "
        f"**Perp markets:** {info.get('perps', 'N/A')}\n"
        f"**Underlying source:** Yahoo Finance ({yf_tick})\n\n"
        f"{'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>14}\n"
        + "-" * 68 + "\n"
    )
    rows = "".join(
        f"{str(d.date()):<12} {r['Open']:>10.2f} {r['High']:>10.2f} "
        f"{r['Low']:>10.2f} {r['Close']:>10.2f} {r.get('Volume', 0):>14,.0f}\n"
        for d, r in df.iterrows()
    )
    summary = (
        f"\n**Summary:**\n"
        f"- Period High:  {df['High'].max():.4f}\n"
        f"- Period Low:   {df['Low'].min():.4f}\n"
        f"- Latest Close: {df['Close'].iloc[-1]:.4f}\n"
        f"- Trading days: {len(df)}\n"
    )
    return header + rows + summary


# ── Technical analysis ────────────────────────────────────────────────────────

def get_tradfi_technical_analysis(
    symbol: str,
    curr_date: str,
    look_back_days: int = 365,
) -> str:
    """
    Compute technical indicators from Yahoo Finance daily data.

    Indicators: RSI(14), EMA(20/50/200), MACD(12/26/9),
    Bollinger Bands(20,2σ), ATR(14), Stochastic(14,3).
    """
    yf_tick = get_yf_ticker(symbol)
    info    = get_instrument_info(symbol)
    end     = datetime.strptime(curr_date, "%Y-%m-%d")
    start   = end - timedelta(days=look_back_days + 60)   # warmup buffer

    try:
        df = yf.Ticker(yf_tick).history(
            start=start.strftime("%Y-%m-%d"),
            end=curr_date, interval="1d"
        )
    except Exception as e:
        return f"Error fetching {symbol} ({yf_tick}): {e}"

    if df is None or df.empty or len(df) < 20:
        return f"Insufficient data for {symbol} ({yf_tick})."

    closes = df["Close"]
    current_price = closes.iloc[-1]

    try:
        import ta as _ta
        rsi_val  = _ta.momentum.RSIIndicator(close=closes, window=14).rsi().iloc[-1]
        ema20    = _ta.trend.EMAIndicator(close=closes, window=20).ema_indicator().iloc[-1]
        ema50    = _ta.trend.EMAIndicator(close=closes, window=50).ema_indicator().iloc[-1]
        ema200   = _ta.trend.EMAIndicator(close=closes, window=200).ema_indicator().iloc[-1] \
                   if len(closes) >= 200 else float("nan")
        macd_obj = _ta.trend.MACD(close=closes, window_slow=26, window_fast=12, window_sign=9)
        macd_l   = macd_obj.macd().iloc[-1]
        macd_h   = macd_obj.macd_diff().iloc[-1]
        macd_s   = macd_obj.macd_signal().iloc[-1]
        bb       = _ta.volatility.BollingerBands(close=closes, window=20, window_dev=2)
        bb_u     = bb.bollinger_hband().iloc[-1]
        bb_l     = bb.bollinger_lband().iloc[-1]
        atr_val  = _ta.volatility.AverageTrueRange(
            high=df["High"], low=df["Low"], close=closes, window=14
        ).average_true_range().iloc[-1]
        stoch_obj = _ta.momentum.StochasticOscillator(
            high=df["High"], low=df["Low"], close=closes, window=14, smooth_window=3
        )
        stoch_k  = stoch_obj.stoch().iloc[-1]
        stoch_d  = stoch_obj.stoch_signal().iloc[-1]
    except ImportError:
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi_val = (100 - 100 / (1 + rs)).iloc[-1]
        ema20   = closes.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50   = closes.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200  = closes.ewm(span=200, adjust=False).mean().iloc[-1] if len(closes) >= 200 else float("nan")
        ema12   = closes.ewm(span=12, adjust=False).mean()
        ema26   = closes.ewm(span=26, adjust=False).mean()
        macd_l  = (ema12 - ema26).iloc[-1]
        macd_s  = (ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1]
        macd_h  = macd_l - macd_s
        sma20   = closes.rolling(20).mean()
        std20   = closes.rolling(20).std()
        bb_u    = (sma20 + 2 * std20).iloc[-1]
        bb_l    = (sma20 - 2 * std20).iloc[-1]
        atr_val = stoch_k = stoch_d = float("nan")

    # Support / resistance from last 60 trading days
    recent     = df.tail(60)
    support    = recent["Low"].min()
    resistance = recent["High"].max()

    # Volume trend
    avg_vol    = df["Volume"].tail(20).mean()
    last_vol   = df["Volume"].iloc[-1]
    vol_signal = "Above 20-day average" if last_vol > avg_vol else "Below 20-day average"

    def _f(v): return f"{v:.4f}" if v == v else "N/A"

    # Trend classifications
    if current_price > ema20 > ema50:
        short_trend = "Strong Bullish"
    elif current_price > ema50:
        short_trend = "Bullish"
    elif current_price < ema20 < ema50:
        short_trend = "Strong Bearish"
    else:
        short_trend = "Bearish"

    long_trend = ("Bullish (Golden Cross)" if ema50 > ema200 else "Bearish (Death Cross)") \
                 if ema200 == ema200 else "N/A (< 200 bars)"

    rsi_lbl   = "Overbought" if rsi_val > 70 else ("Oversold" if rsi_val < 30 else "Neutral")
    macd_sig  = "Bullish" if macd_h > 0 else "Bearish"

    return (
        f"## {symbol.upper()} Technical Analysis — Daily Underlying Data\n"
        f"**Instrument:** {info['name']}  |  **Perp markets:** {info.get('perps','N/A')}\n"
        f"**Source:** Yahoo Finance ({yf_tick})  |  Lookback: {look_back_days}d\n\n"
        f"**Current Price:** {current_price:.4f}\n\n"
        f"**Short-Term Trend (EMA20/50):** {short_trend}\n"
        f"- EMA20:  {_f(ema20)}\n"
        f"- EMA50:  {_f(ema50)}\n"
        f"- EMA200: {_f(ema200)}\n"
        f"**Long-Term Trend:** {long_trend}\n\n"
        f"**RSI(14):** {rsi_val:.1f} — {rsi_lbl}\n\n"
        f"**MACD(12,26,9):** {macd_sig}\n"
        f"- Line:      {_f(macd_l)}\n"
        f"- Signal:    {_f(macd_s)}\n"
        f"- Histogram: {_f(macd_h)}\n\n"
        f"**Bollinger Bands (20, 2\u03c3):**\n"
        f"- Upper: {_f(bb_u)}\n"
        f"- Lower: {_f(bb_l)}\n\n"
        f"**ATR(14):** {_f(atr_val)}\n\n"
        f"**Stochastic(14,3):** %K={_f(stoch_k)} | %D={_f(stoch_d)}\n\n"
        f"**Recent Levels (60d):**\n"
        f"- Resistance: {_f(resistance)}\n"
        f"- Support:    {_f(support)}\n\n"
        f"**Volume:** {vol_signal}\n"
    )
