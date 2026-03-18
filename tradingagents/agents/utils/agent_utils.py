from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
from typing import List
from typing import Annotated
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import RemoveMessage
from langchain_core.tools import tool
from datetime import date, timedelta, datetime
import functools
import pandas as pd
import os
from dateutil.relativedelta import relativedelta
from langchain_openai import ChatOpenAI
import tradingagents.dataflows.interface as interface
from tradingagents.default_config import DEFAULT_CONFIG
from langchain_core.messages import HumanMessage


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]
        
        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        
        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")
        
        return {"messages": removal_operations + [placeholder]}
    
    return delete_messages


class Toolkit:
    _config = DEFAULT_CONFIG.copy()

    @classmethod
    def update_config(cls, config):
        """Update the class-level configuration."""
        cls._config.update(config)

    @property
    def config(self):
        """Access the configuration."""
        return self._config

    def __init__(self, config=None):
        if config:
            self.update_config(config)

    @staticmethod
    @tool
    def get_reddit_news(
        curr_date: Annotated[str, "Date you want to get news for in yyyy-mm-dd format"],
    ) -> str:
        """
        Retrieve global news from Reddit within a specified time frame.
        Args:
            curr_date (str): Date you want to get news for in yyyy-mm-dd format
        Returns:
            str: A formatted dataframe containing the latest global news from Reddit in the specified time frame.
        """
        if not curr_date or curr_date.strip() == "":
            return "Reddit global news unavailable: no date provided."
        try:
            global_news_result = interface.get_reddit_global_news(curr_date, 7, 5)
            return global_news_result or "No Reddit global news found for this date."
        except Exception as e:
            return f"Reddit global news unavailable: {type(e).__name__}. Continuing analysis without it."

    @staticmethod
    @tool
    def get_finnhub_news(
        ticker: Annotated[
            str,
            "Search query of a company, e.g. 'AAPL, TSM, etc.",
        ],
        start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
        end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    ):
        """
        Retrieve the latest news about a given stock from Finnhub within a date range
        Args:
            ticker (str): Ticker of a company. e.g. AAPL, TSM
            start_date (str): Start date in yyyy-mm-dd format
            end_date (str): End date in yyyy-mm-dd format
        Returns:
            str: A formatted dataframe containing news about the company within the date range from start_date to end_date
        """
        if not ticker or not start_date or not end_date:
            return "Finnhub news unavailable: missing ticker or date arguments."
        try:
            end_date_str = end_date
            end_dt   = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            look_back_days = (end_dt - start_dt).days
            finnhub_news_result = interface.get_finnhub_news(
                ticker, end_date_str, look_back_days
            )
            return finnhub_news_result or f"No Finnhub news found for {ticker}."
        except Exception as e:
            return f"Finnhub news unavailable for {ticker}: {type(e).__name__}. Continuing analysis without it."

    @staticmethod
    @tool
    def get_reddit_stock_info(
        ticker: Annotated[str, "Ticker of a company. e.g. AAPL, TSM"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    ) -> str:
        """
        Retrieve the latest news about a given stock from Reddit, given the current date.
        Args:
            ticker (str): Ticker of a company. e.g. AAPL, TSM
            curr_date (str): current date in yyyy-mm-dd format to get news for
        Returns:
            str: A formatted dataframe containing the latest news about the company on the given date
        """
        if not ticker or ticker.strip() == "":
            return "Reddit stock info unavailable: ticker symbol is required."
        if not curr_date or curr_date.strip() == "":
            return "Reddit stock info unavailable: date is required."
        try:
            stock_news_results = interface.get_reddit_company_news(
                ticker.strip().upper(), curr_date.strip(), 7, 5
            )
            return stock_news_results or f"No Reddit data found for {ticker} on {curr_date}."
        except Exception as e:
            return f"Reddit data unavailable for {ticker}: {type(e).__name__}. Continuing analysis without it."

    @staticmethod
    @tool
    def get_YFin_data(
        symbol: Annotated[str, "ticker symbol of the company"],
        start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
        end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    ) -> str:
        """
        Retrieve the stock price data for a given ticker symbol from Yahoo Finance.
        Args:
            symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
            start_date (str): Start date in yyyy-mm-dd format
            end_date (str): End date in yyyy-mm-dd format
        Returns:
            str: A formatted dataframe containing the stock price data for the specified ticker symbol in the specified date range.
        """

        result_data = interface.get_YFin_data(symbol, start_date, end_date)

        return result_data

    @staticmethod
    @tool
    def get_YFin_data_online(
        symbol: Annotated[str, "ticker symbol of the company"],
        start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
        end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    ) -> str:
        """
        Retrieve the stock price data for a given ticker symbol from Yahoo Finance.
        Args:
            symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
            start_date (str): Start date in yyyy-mm-dd format
            end_date (str): End date in yyyy-mm-dd format
        Returns:
            str: A formatted dataframe containing the stock price data for the specified ticker symbol in the specified date range.
        """

        result_data = interface.get_YFin_data_online(symbol, start_date, end_date)

        return result_data

    @staticmethod
    @tool
    def get_stockstats_indicators_report(
        symbol: Annotated[str, "ticker symbol of the company"],
        indicator: Annotated[
            str, "technical indicator to get the analysis and report of"
        ],
        curr_date: Annotated[
            str, "The current trading date you are trading on, YYYY-mm-dd"
        ],
        look_back_days: Annotated[int, "how many days to look back"] = 30,
    ) -> str:
        """
        Retrieve stock stats indicators for a given ticker symbol and indicator.
        Args:
            symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
            indicator (str): Technical indicator to get the analysis and report of
            curr_date (str): The current trading date you are trading on, YYYY-mm-dd
            look_back_days (int): How many days to look back, default is 30
        Returns:
            str: A formatted dataframe containing the stock stats indicators for the specified ticker symbol and indicator.
        """

        result_stockstats = interface.get_stock_stats_indicators_window(
            symbol, indicator, curr_date, look_back_days, False
        )

        return result_stockstats

    @staticmethod
    @tool
    def get_stockstats_indicators_report_online(
        symbol: Annotated[str, "ticker symbol of the company"],
        indicator: Annotated[
            str, "technical indicator to get the analysis and report of"
        ],
        curr_date: Annotated[
            str, "The current trading date you are trading on, YYYY-mm-dd"
        ],
        look_back_days: Annotated[int, "how many days to look back"] = 30,
    ) -> str:
        """
        Retrieve stock stats indicators for a given ticker symbol and indicator.
        Args:
            symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
            indicator (str): Technical indicator to get the analysis and report of
            curr_date (str): The current trading date you are trading on, YYYY-mm-dd
            look_back_days (int): How many days to look back, default is 30
        Returns:
            str: A formatted dataframe containing the stock stats indicators for the specified ticker symbol and indicator.
        """

        result_stockstats = interface.get_stock_stats_indicators_window(
            symbol, indicator, curr_date, look_back_days, True
        )

        return result_stockstats

    @staticmethod
    @tool
    def get_finnhub_company_insider_sentiment(
        ticker: Annotated[str, "ticker symbol for the company"],
        curr_date: Annotated[
            str,
            "current date of you are trading at, yyyy-mm-dd",
        ],
    ):
        """
        Retrieve insider sentiment information about a company (retrieved from public SEC information) for the past 30 days
        Args:
            ticker (str): ticker symbol of the company
            curr_date (str): current date you are trading at, yyyy-mm-dd
        Returns:
            str: a report of the sentiment in the past 30 days starting at curr_date
        """

        data_sentiment = interface.get_finnhub_company_insider_sentiment(
            ticker, curr_date, 30
        )

        return data_sentiment

    @staticmethod
    @tool
    def get_finnhub_company_insider_transactions(
        ticker: Annotated[str, "ticker symbol"],
        curr_date: Annotated[
            str,
            "current date you are trading at, yyyy-mm-dd",
        ],
    ):
        """
        Retrieve insider transaction information about a company (retrieved from public SEC information) for the past 30 days
        Args:
            ticker (str): ticker symbol of the company
            curr_date (str): current date you are trading at, yyyy-mm-dd
        Returns:
            str: a report of the company's insider transactions/trading information in the past 30 days
        """

        data_trans = interface.get_finnhub_company_insider_transactions(
            ticker, curr_date, 30
        )

        return data_trans

    @staticmethod
    @tool
    def get_simfin_balance_sheet(
        ticker: Annotated[str, "ticker symbol"],
        freq: Annotated[
            str,
            "reporting frequency of the company's financial history: annual/quarterly",
        ],
        curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
    ):
        """
        Retrieve the most recent balance sheet of a company
        Args:
            ticker (str): ticker symbol of the company
            freq (str): reporting frequency of the company's financial history: annual / quarterly
            curr_date (str): current date you are trading at, yyyy-mm-dd
        Returns:
            str: a report of the company's most recent balance sheet
        """

        data_balance_sheet = interface.get_simfin_balance_sheet(ticker, freq, curr_date)

        return data_balance_sheet

    @staticmethod
    @tool
    def get_simfin_cashflow(
        ticker: Annotated[str, "ticker symbol"],
        freq: Annotated[
            str,
            "reporting frequency of the company's financial history: annual/quarterly",
        ],
        curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
    ):
        """
        Retrieve the most recent cash flow statement of a company
        Args:
            ticker (str): ticker symbol of the company
            freq (str): reporting frequency of the company's financial history: annual / quarterly
            curr_date (str): current date you are trading at, yyyy-mm-dd
        Returns:
                str: a report of the company's most recent cash flow statement
        """

        data_cashflow = interface.get_simfin_cashflow(ticker, freq, curr_date)

        return data_cashflow

    @staticmethod
    @tool
    def get_simfin_income_stmt(
        ticker: Annotated[str, "ticker symbol"],
        freq: Annotated[
            str,
            "reporting frequency of the company's financial history: annual/quarterly",
        ],
        curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
    ):
        """
        Retrieve the most recent income statement of a company
        Args:
            ticker (str): ticker symbol of the company
            freq (str): reporting frequency of the company's financial history: annual / quarterly
            curr_date (str): current date you are trading at, yyyy-mm-dd
        Returns:
                str: a report of the company's most recent income statement
        """

        data_income_stmt = interface.get_simfin_income_statements(
            ticker, freq, curr_date
        )

        return data_income_stmt

    @staticmethod
    @tool
    def get_stock_news_openai(
        ticker: Annotated[str, "the company's ticker"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    ):
        """
        Retrieve the latest news about a given stock by using OpenAI's news API.
        Args:
            ticker (str): Ticker of a company. e.g. AAPL, TSM
            curr_date (str): Current date in yyyy-mm-dd format
        Returns:
            str: A formatted string containing the latest news about the company on the given date.
        """

        openai_news_results = interface.get_stock_news_openai(ticker, curr_date)

        return openai_news_results

    @staticmethod
    @tool
    def get_global_news_openai(
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    ):
        """
        Retrieve the latest macroeconomics news on a given date using OpenAI's macroeconomics news API.
        Args:
            curr_date (str): Current date in yyyy-mm-dd format
        Returns:
            str: A formatted string containing the latest macroeconomic news on the given date.
        """

        openai_news_results = interface.get_global_news_openai(curr_date)

        return openai_news_results

    @staticmethod
    @tool
    def get_fundamentals_openai(
        ticker: Annotated[str, "the company's ticker"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    ):
        """
        Retrieve the latest fundamental information about a given stock on a given date by using OpenAI's news API.
        Args:
            ticker (str): Ticker of a company. e.g. AAPL, TSM
            curr_date (str): Current date in yyyy-mm-dd format
        Returns:
            str: A formatted string containing the latest fundamental information about the company on the given date.
        """

        openai_fundamentals_results = interface.get_fundamentals_openai(
            ticker, curr_date
        )

        return openai_fundamentals_results

    # ===== CRYPTO TRADING TOOLS =====

    @staticmethod
    @tool
    def get_crypto_market_analysis(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    ) -> str:
        """
        Get comprehensive market analysis for a cryptocurrency including current price, market cap, volume, and key metrics.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
        Returns:
            str: Comprehensive market data and analysis for the cryptocurrency
        """
        return interface.get_crypto_market_analysis(symbol, curr_date)

    @staticmethod
    @tool
    def get_crypto_price_history(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
        look_back_days: Annotated[int, "How many days to look back"] = 30,
    ) -> str:
        """
        Get historical price data for a cryptocurrency over a specified time period.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
            look_back_days (int): Number of days to look back, default is 30
        Returns:
            str: Historical price, volume, and market cap data
        """
        return interface.get_crypto_price_history(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_crypto_technical_analysis(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
        look_back_days: Annotated[int, "How many days to look back"] = 7,
    ) -> str:
        """
        Get technical analysis for a cryptocurrency including trends, support/resistance levels, and momentum indicators.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
            look_back_days (int): Number of days to analyze, default is 30
        Returns:
            str: Technical analysis including price trends, volume analysis, and key levels
        """
        return interface.get_crypto_technical_analysis(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_crypto_4h_price_history(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
        look_back_days: Annotated[int, "How many days to look back"] = 730,
    ) -> str:
        """
        Get 4-hour OHLCV price history for a cryptocurrency (default 2 years / 730 days).
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
            look_back_days (int): Number of days to look back, default 730 (2 years)
        Returns:
            str: Monthly-aggregated OHLCV table derived from 4h bars
        """
        return interface.get_crypto_4h_price_history(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_crypto_4h_technical_analysis(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
        look_back_days: Annotated[int, "How many days to look back"] = 730,
    ) -> str:
        """
        Get 4-hour technical analysis: RSI(14), EMA50/200, MACD(12/26/9),
        Bollinger Bands(20,2σ), ATR(14), Stochastic(14,3), Volume SMA(20).
        Uses 4h bars for medium/long-term trend analysis.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
            look_back_days (int): Number of days, default 730 (2 years)
        Returns:
            str: Technical analysis report from 4h Binance candles
        """
        return interface.get_crypto_4h_technical_analysis(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_tradfi_price_history(
        symbol: Annotated[str, "TradFi perp symbol e.g. GOLD, EWY, SPX, OIL, TLT"],
        start_date: Annotated[str, "Start date in YYYY-MM-DD format"],
        end_date: Annotated[str, "End date in YYYY-MM-DD format"],
    ) -> str:
        """
        Get daily OHLCV price history for a TradFi instrument (commodities, indices,
        country ETFs, sector ETFs, fixed income, FX) via Yahoo Finance underlying data.
        These instruments trade as perpetual futures on Binance and/or Hyperliquid.
        Args:
            symbol: perp ticker (e.g. 'GOLD', 'EWY', 'SPX', 'OIL', 'TLT')
        """
        return interface.get_tradfi_price_history(symbol, start_date, end_date)

    @staticmethod
    @tool
    def get_tradfi_technical_analysis(
        symbol: Annotated[str, "TradFi perp symbol e.g. GOLD, EWY, SPX, OIL, TLT"],
        curr_date: Annotated[str, "Current date in YYYY-MM-DD format"],
        look_back_days: Annotated[int, "Calendar days of history to analyse"] = 365,
    ) -> str:
        """
        Compute RSI(14), EMA(20/50/200), MACD(12/26/9), Bollinger Bands,
        ATR(14), and Stochastic(14,3) from Yahoo Finance daily data for a
        TradFi instrument (commodity, index, ETF, or FX pair).
        Args:
            symbol: perp ticker (e.g. 'GOLD', 'EWY', 'SPX', 'OIL')
        """
        return interface.get_tradfi_technical_analysis(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_crypto_news_analysis(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
        look_back_days: Annotated[int, "How many days to look back"] = 7,
    ) -> str:
        """
        Get recent news and market trends affecting cryptocurrency markets.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
            look_back_days (int): Number of days to look back, default is 7
        Returns:
            str: News analysis and market trends for cryptocurrency
        """
        return interface.get_crypto_news_analysis(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_treeofalpha_sentiment(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
        look_back_days: Annotated[int, "How many days to look back"] = 7,
    ) -> str:
        """
        Get social sentiment for a cryptocurrency from Tree of Alpha,
        including aggregated news and social media posts.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
            look_back_days (int): Number of days to look back, default is 7
        Returns:
            str: Social sentiment report with news and social posts
        """
        return interface.get_social_sentiment_treeofalpha(symbol, curr_date, look_back_days)

    @staticmethod
    @tool
    def get_crypto_fundamentals_analysis(
        symbol: Annotated[str, "Cryptocurrency symbol like BTC, ETH, ADA"],
        curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    ) -> str:
        """
        Get fundamental analysis for a cryptocurrency including market cap, supply metrics, and tokenomics.
        Args:
            symbol (str): Crypto symbol (e.g., 'BTC', 'ETH', 'ADA')
            curr_date (str): Current date in yyyy-mm-dd format
        Returns:
            str: Fundamental analysis including market metrics, supply data, and crypto-specific fundamentals
        """
        return interface.get_crypto_fundamentals_analysis(symbol, curr_date)
