from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json

# Reuse the crypto symbol detector from the news analyst
from tradingagents.dataflows.tradfi_utils import classify_symbol, get_instrument_info


def create_social_media_analyst(llm, toolkit):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        if instrument_type == "tradfi":
            info  = get_instrument_info(ticker)
            tools = [toolkit.get_treeofalpha_sentiment]
            if toolkit.config["online_tools"]:
                tools = [toolkit.get_global_news_openai]
            system_message = (
                f"You are a TradFi market sentiment analyst covering {info['name']} ({ticker.upper()}), "
                f"a {info['type'].replace('_',' ')} that trades as a perpetual future on "
                f"{info.get('perps','Binance / Hyperliquid')}. "
                "Analyse recent social media posts, news sentiment, and market commentary relevant to "
                "this instrument over the past week. Cover: trader positioning, retail/institutional "
                "sentiment, key narratives driving price, contrarian signals, and any social catalysts. "
                "Do not state trends are mixed without evidence. "
                "Append a concise Markdown table. Be concise. Keep under 4096 characters."
            )
        elif instrument_type == "crypto":
            # Crypto: use Tree of Alpha for real social sentiment data
            tools = [toolkit.get_treeofalpha_sentiment]
            system_message = (
                "You are a cryptocurrency social media analyst tasked with analysing "
                "social media posts, community sentiment, and crypto news for a specific "
                "cryptocurrency over the past week. Use the Tree of Alpha sentiment tool "
                "to retrieve real social and news data. Write a concise report covering "
                "overall market sentiment, key narratives, bullish/bearish signals from "
                "the community, and any notable news events. Do not state trends are mixed "
                "without evidence — provide specific insights that help crypto traders. "
                "Append a concise Markdown table summarising key sentiment points. "
                "If the data tool returns a message starting with NA, report NA and the reason. Do not fabricate a neutral or 50/50 signal when data is absent. Be concise and direct. Keep your response under 4096 characters."
            )
        elif toolkit.config["online_tools"]:
            tools = [toolkit.get_stock_news_openai]
            system_message = (
                "You are a social media and company specific news researcher/analyst tasked with analyzing social media posts, recent company news, and public sentiment for a specific company over the past week. You will be given a company's name your objective is to write a report detailing your analysis, insights, and implications for traders and investors on this company's current state after looking at social media and what people are saying about that company, analyzing sentiment data of what people feel each day about the company, and looking at recent company news. Try to look at all sources possible from social media to sentiment to news. Do not simply state the trends are mixed, provide detailed and fine-grained analysis and insights that may help traders make decisions."
                + " Append a concise Markdown table summarising key points. Be concise and direct. Keep your response under 4096 characters."
            )
        else:
            tools = [toolkit.get_reddit_stock_info]
            system_message = (
                "You are a social media and company specific news researcher/analyst tasked with analyzing social media posts, recent company news, and public sentiment for a specific company over the past week. You will be given a company's name your objective is to write a report detailing your analysis, insights, and implications for traders and investors on this company's current state after looking at social media and what people are saying about that company, analyzing sentiment data of what people feel each day about the company, and looking at recent company news. Try to look at all sources possible from social media to sentiment to news. Do not simply state the trends are mixed, provide detailed and fine-grained analysis and insights that may help traders make decisions."
                + " Append a concise Markdown table summarising key points. Be concise and direct. Keep your response under 4096 characters."
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
                    "For your reference, the current date is {current_date}. The current company we want to analyze is {ticker}",
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
            "sentiment_report": report,
        }

    return social_media_analyst_node
