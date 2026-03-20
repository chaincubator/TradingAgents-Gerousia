from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.dataflows.tradfi_utils import classify_symbol, get_instrument_info


def create_market_analyst(llm, toolkit):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        if instrument_type == "tradfi":
            # TradFi instruments: commodity, index, ETF, FX — use underlying yfinance data
            info = get_instrument_info(ticker)
            tools = [toolkit.get_tradfi_price_history, toolkit.get_tradfi_technical_analysis]
            system_message = (
                f"You are a TradFi market analyst specialising in {info['type'].replace('_',' ')} instruments. "
                f"You are analysing {info['name']} ({ticker.upper()}), which trades as a perpetual future on "
                f"{info.get('perps', 'Binance / Hyperliquid')}. "
                "Use the underlying Yahoo Finance price series for analysis — this gives you accurate spot/futures "
                "prices free from funding-rate and basis distortions. "
                "Compute and interpret: trend direction (EMA 20/50/200), momentum (RSI, MACD), volatility "
                "(Bollinger Bands, ATR), and key support/resistance levels. "
                "The data also includes Advanced Technical Indicators — interpret each of the following:\n"
                "- TD Sequential: report the current setup count (1-9), whether a setup-9 was recently completed "
                "(and if it was perfected), and the countdown progress (X/13).\n"
                "- TD Combo: report active combo countdown and any completed 13 signal.\n"
                "- Ichimoku Cloud: report price vs cloud (above/inside/below), cloud colour, TK cross status, "
                "Chikou span signal, and future cloud colour.\n"
                "- Candlestick Patterns: name each detected pattern, its signal (bullish/bearish/neutral), "
                "and trading implication.\n"
                "Consider macro drivers relevant to this asset class (e.g. USD strength, rates, commodity cycles, "
                "geopolitics for country ETFs). Append a concise Markdown table. "
                "Be concise and direct. Keep your response under 4096 characters."
            )
        elif instrument_type == "crypto":
            # Use crypto-specific tools
            tools = [toolkit.get_crypto_price_history, toolkit.get_crypto_technical_analysis]
            system_message = (
                "You are a cryptocurrency short-term technical analyst (5-minute bars). "
                "Provide comprehensive technical analysis for cryptocurrency trading.\n\n"
                "Key areas to analyse:\n"
                "- Price action and trend direction (EMA9 vs EMA21)\n"
                "- RSI(9) momentum and overbought/oversold signals\n"
                "- Bollinger Band position and width\n"
                "- ATR volatility and VWAP relationship\n"
                "- Volume patterns relative to 4h average\n"
                "- Support and resistance from last 24h\n"
                "- Candlestick Patterns (Advanced Indicators section): name each detected "
                "pattern, its signal, and the trading implication.\n\n"
                "Do not simply state the trends are mixed — provide specific, actionable insights. "
                "Consider 24/7 trading, higher volatility, and sentiment-driven moves unique to crypto. "
                "Append a concise Markdown table at the end. Be concise and direct. "
                "Keep your response under 4096 characters."
            )
        else:
            # Stock — use existing yfinance / stockstats tools
            if toolkit.config["online_tools"]:
                tools = [
                    toolkit.get_YFin_data_online,
                    toolkit.get_stockstats_indicators_report_online,
                ]
            else:
                tools = [
                    toolkit.get_YFin_data,
                    toolkit.get_stockstats_indicators_report,
                ]

            system_message = (
                """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_YFin_data first to retrieve the CSV that is needed to generate indicators. Write a very detailed and nuanced report of the trends you observe. Do not simply state the trends are mixed, provide detailed and finegrained analysis and insights that may help traders make decisions."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. The company we want to look at is {ticker}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content
       
        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node


def create_market_4h_analyst(llm, toolkit):
    """4-hour bar market analyst for medium/long-term trend analysis."""

    def market_4h_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        if instrument_type == "tradfi":
            info  = get_instrument_info(ticker)
            tools = [toolkit.get_tradfi_price_history, toolkit.get_tradfi_technical_analysis]
            system_message = (
                f"You are a TradFi medium/long-term analyst specialising in "
                f"{info['type'].replace('_',' ')} instruments. "
                f"Analysing {info['name']} ({ticker.upper()}) — perp markets: "
                f"{info.get('perps','Binance / Hyperliquid')}. "
                "Use the underlying Yahoo Finance daily price series (1+ years of data) to identify "
                "dominant trends, Golden/Death crosses, MACD signals, RSI regimes, "
                "Bollinger Band conditions, and key multi-month support/resistance. "
                "The data also includes Advanced Technical Indicators — interpret all of:\n"
                "- TD Sequential: current setup count (1-9), perfected setup flag, countdown (X/13); "
                "a completed 9 or 13 is a potential reversal signal.\n"
                "- TD Combo: active combo countdown and completed 13 signal.\n"
                "- Ichimoku Cloud (9/26/52): price above/inside/below cloud, cloud colour (bullish/bearish kumo), "
                "Tenkan/Kijun cross status, Chikou span vs price, future cloud colour.\n"
                "- Candlestick Patterns: name each detected pattern, signal (bullish/bearish/neutral), "
                "and how it confirms or contradicts the higher-timeframe trend.\n"
                "Highlight macro drivers specific to this asset type. "
                "Append a concise Markdown table. Be concise. Keep under 4096 characters."
            )
        elif instrument_type == "crypto":
            tools = [
                toolkit.get_crypto_4h_price_history,
                toolkit.get_crypto_4h_technical_analysis,
            ]
            system_message = (
                "You are a cryptocurrency 4-hour chart analyst specialising in "
                "medium and long-term trend analysis. Interpret 2 years of 4-hour OHLCV "
                "bars and all technical indicators to identify the dominant trend, key "
                "structural levels, and cyclical patterns for swing and position traders.\n\n"
                "Standard indicators to cover:\n"
                "- Long-term trend direction (EMA50 vs EMA200, Golden/Death Cross)\n"
                "- MACD crossovers and divergences on the 4h timeframe\n"
                "- RSI(14) overbought/oversold across the 2-year range\n"
                "- Bollinger Band squeezes and expansions\n"
                "- ATR-based volatility regimes and Stochastic momentum\n"
                "- Multi-month support and resistance clusters\n"
                "- Volume patterns and accumulation/distribution\n\n"
                "Advanced Technical Indicators (included in the data) — interpret all of:\n"
                "- TD Sequential: current setup count (1-9), whether a setup-9 was recently "
                "completed (perfected or not), and countdown progress (X/13); a completed 13 "
                "signals a high-probability reversal zone.\n"
                "- TD Combo: active combo countdown and any completed 13 signal.\n"
                "- Ichimoku Cloud (9/26/52): price above/inside/below cloud, cloud colour "
                "(bullish green / bearish red kumo), Tenkan/Kijun cross, Chikou span vs price "
                "26 bars ago, and future cloud colour projection.\n"
                "- Candlestick Patterns: identify each detected pattern by name, signal "
                "(bullish/bearish/neutral), and how it aligns with or contradicts the 4h trend.\n\n"
                "Cross-reference with short-term 5m analysis for timeframe confluence. "
                "Append a concise Markdown table summarising all key indicator values. "
                "Be concise and direct. Keep your response under 4096 characters."
            )
        else:
            # Stock — fall back to daily yfinance data
            if toolkit.config["online_tools"]:
                tools = [
                    toolkit.get_YFin_data_online,
                    toolkit.get_stockstats_indicators_report_online,
                ]
            else:
                tools = [
                    toolkit.get_YFin_data,
                    toolkit.get_stockstats_indicators_report,
                ]
            system_message = (
                "You are a medium-term market analyst tasked with identifying trends "
                "over the past 2 years using daily stock data. Analyse trend direction, "
                "key moving averages, momentum indicators, and support/resistance. "
                "Append a concise Markdown table. Be concise. Keep under 4096 characters."
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with"
                    " different tools will help where you left off."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    " The current date is {current_date}. Analyse: {ticker}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([t.name for t in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "market_4h_report": report,
        }

    return market_4h_analyst_node
