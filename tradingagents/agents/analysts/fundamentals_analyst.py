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


def create_fundamentals_analyst(llm, toolkit):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        if instrument_type == "tradfi":
            info  = get_instrument_info(ticker)
            tools = [toolkit.get_fundamentals_openai] if toolkit.config["online_tools"] else [toolkit.get_tradfi_technical_analysis]
            system_message = (
                f"You are a TradFi fundamentals analyst specialising in {info['type'].replace('_',' ')} instruments. "
                f"Analysing {info['name']} ({ticker.upper()}), which trades as a perpetual future on "
                f"{info.get('perps','Binance / Hyperliquid')}. "
                "Research and report on the fundamental drivers most relevant to this asset: "
                "For commodities — supply/demand balance, inventory levels, production data, seasonal factors, "
                "currency effects, geopolitical risks, and central bank holdings. "
                "For equity indices and ETFs — macro environment, earnings cycle, valuations (P/E, P/B), "
                "sector weightings, flows, and regional economic indicators. "
                "For fixed income — yield levels, duration risk, credit spreads, central bank policy. "
                "Focus on what drives the perpetual contract price. Append a concise Markdown table. "
                "Be concise. Keep under 4096 characters.",
            )
        elif instrument_type == "crypto":
            tools = [toolkit.get_crypto_fundamentals_analysis, toolkit.get_crypto_market_analysis]
            system_message = (
                "You are a cryptocurrency fundamental analyst tasked with analyzing fundamental information about a cryptocurrency. Please write a comprehensive report of the cryptocurrency's fundamental information such as market capitalization, supply mechanics, token economics, network metrics, adoption indicators, and market positioning to gain a full view of the cryptocurrency's fundamental value proposition to inform traders. "
                "Focus on crypto-specific metrics like: market cap rank, circulating vs total supply, trading volume patterns, network activity, developer ecosystem, regulatory environment, community strength, and technology fundamentals. "
                "Make sure to include as much detail as possible. Do not simply state the trends are mixed, provide detailed and fine-grained analysis and insights that may help crypto traders make decisions."
                + " Make sure to append a concise Markdown table at the end. Be concise and direct. Keep your response under 4096 characters.",
            )
        else:
            # Stock
            if toolkit.config["online_tools"]:
                tools = [toolkit.get_fundamentals_openai]
            else:
                tools = [
                    toolkit.get_finnhub_company_insider_sentiment,
                    toolkit.get_finnhub_company_insider_transactions,
                    toolkit.get_simfin_balance_sheet,
                    toolkit.get_simfin_cashflow,
                    toolkit.get_simfin_income_stmt,
                ]
            system_message = (
                "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, company financial history, insider sentiment and insider transactions to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Do not simply state the trends are mixed, provide detailed and finegrained analysis and insights that may help traders make decisions."
                + " Make sure to append a concise Markdown table at the end. Be concise and direct. Keep your response under 4096 characters.",
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
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
