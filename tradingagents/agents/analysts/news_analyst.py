from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.dataflows.tradfi_utils import classify_symbol, get_instrument_info


def _is_crypto_symbol(symbol: str) -> bool:
    """
    Detect if a symbol is likely a cryptocurrency
    Uses a whitelist approach for known crypto symbols and excludes known stock patterns
    """
    # Known crypto symbols (most common ones)
    crypto_symbols = {
        'BTC', 'ETH', 'ADA', 'SOL', 'DOT', 'AVAX', 'MATIC', 'LINK', 'UNI', 'AAVE',
        'XRP', 'LTC', 'BCH', 'EOS', 'TRX', 'XLM', 'VET', 'ALGO', 'ATOM', 'LUNA',
        'NEAR', 'FTM', 'CRO', 'SAND', 'MANA', 'AXS', 'GALA', 'ENJ', 'CHZ', 'BAT',
        'ZEC', 'DASH', 'XMR', 'DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BNB', 'USDT', 'USDC',
        'TON', 'ICP', 'HBAR', 'THETA', 'FIL', 'ETC', 'MKR', 'APT', 'LDO', 'OP',
        'IMX', 'GRT', 'RUNE', 'FLOW', 'EGLD', 'XTZ', 'MINA', 'ROSE', 'KAVA'
    }
    
    # Known stock symbols (to avoid false positives)
    stock_symbols = {
        'AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'NFLX', 'DIS', 'AMD',
        'INTC', 'CRM', 'ORCL', 'ADBE', 'CSCO', 'PEP', 'KO', 'WMT', 'JNJ', 'PFE',
        'V', 'MA', 'HD', 'UNH', 'BAC', 'XOM', 'CVX', 'LLY', 'ABBV', 'COST',
        'AVGO', 'TMO', 'ACN', 'DHR', 'TXN', 'LOW', 'QCOM', 'HON', 'UPS', 'MDT'
    }
    
    symbol_upper = symbol.upper()
    
    # If it's a known stock symbol, it's definitely not crypto
    if symbol_upper in stock_symbols:
        return False
    
    # If it's a known crypto symbol, it's definitely crypto
    if symbol_upper in crypto_symbols:
        return True
    
    # For unknown symbols, be conservative and assume it's a stock
    # unless it has typical crypto characteristics
    if len(symbol) >= 5:  # Most stocks are 4+ characters
        return False
    
    # Short symbols (2-4 chars) could be crypto if they don't look like stocks
    if len(symbol) <= 4 and symbol.isalnum() and not any(c in symbol for c in ['.', '-', '_']):
        # Additional heuristic: crypto symbols often have certain patterns
        return True
    
    return False


def create_news_analyst(llm, toolkit):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        if instrument_type == "tradfi":
            info  = get_instrument_info(ticker)
            tools = [toolkit.get_google_news]
            if toolkit.config["online_tools"]:
                tools = [toolkit.get_global_news_openai, toolkit.get_google_news]
            system_message = (
                f"You are a macro and TradFi news researcher analysing {info['name']} ({ticker.upper()}), "
                f"a {info['type'].replace('_',' ')} instrument that trades as a perpetual future on "
                f"{info.get('perps','Binance / Hyperliquid')}. "
                "Search for news and macro developments over the past week that are most relevant to this "
                "asset: central bank decisions, geopolitical events, supply/demand drivers, sector news, "
                "currency moves, and any regulatory developments. "
                "Do not state trends are mixed without evidence. Provide specific, actionable insights. "
                "Append a concise Markdown table. Be concise. Keep under 4096 characters."
            )
        elif instrument_type == "crypto":
            tools = [toolkit.get_crypto_news_analysis, toolkit.get_google_news]
            system_message = (
                "You are a cryptocurrency news researcher tasked with analyzing recent news and trends over the past week that affect cryptocurrency markets. Please write a comprehensive report of the current state of the crypto world and broader macroeconomic factors that are relevant for cryptocurrency trading. "
                "Focus on crypto-specific news including: regulatory developments, institutional adoption, technology updates, market sentiment, DeFi trends, NFT markets, blockchain developments, and major crypto exchange news. "
                "Also consider traditional macroeconomic factors that impact crypto markets such as inflation, monetary policy, global economic uncertainty, and traditional market trends. "
                "Do not simply state the trends are mixed, provide detailed and fine-grained analysis and insights that may help crypto traders make decisions."
                + " Make sure to append a concise Markdown table at the end. Be concise and direct. Keep your response under 4096 characters."
            )
        else:
            # Stock
            if toolkit.config["online_tools"]:
                tools = [toolkit.get_global_news_openai, toolkit.get_google_news]
            else:
                tools = [
                    toolkit.get_finnhub_news,
                    toolkit.get_reddit_news,
                    toolkit.get_google_news,
                ]
            system_message = (
                "You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Look at news from EODHD, and finnhub to be comprehensive. Do not simply state the trends are mixed, provide detailed and finegrained analysis and insights that may help traders make decisions."
                + " Make sure to append a concise Markdown table at the end. Be concise and direct. Keep your response under 4096 characters."
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
                    "For your reference, the current date is {current_date}. We are looking at the company {ticker}",
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
            "news_report": report,
        }

    return news_analyst_node
