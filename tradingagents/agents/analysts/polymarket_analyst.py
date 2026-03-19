"""Polymarket Prediction Market Analyst.

Interprets live Polymarket prediction-market data to derive crowd-sourced,
capital-weighted probability estimates for outcomes causally related to the
asset under analysis.  Cross-references the implied bull/bear probabilities
against price-action and sentiment data to identify conviction or divergence.
"""

import os
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.dataflows.tradfi_utils import classify_symbol, get_instrument_info
from tradingagents.dataflows.polymarket_utils import read_price_levels_cache


def create_polymarket_analyst(llm, toolkit):
    def polymarket_analyst_node(state):
        current_date = state["trade_date"]
        ticker       = state["company_of_interest"]

        tools = [toolkit.get_polymarket_data]

        instrument_type = classify_symbol(ticker)
        if instrument_type == "tradfi":
            info = get_instrument_info(ticker)
            asset_desc = f"{info['name']} ({ticker.upper()}), a {info['type'].replace('_',' ')} instrument"
        elif instrument_type == "crypto":
            asset_desc = f"{ticker.upper()} cryptocurrency"
        else:
            asset_desc = f"{ticker.upper()} equity"

        system_message = (
            f"You are a Prediction Market Analyst specialising in extracting crowd-wisdom "
            f"signals from Polymarket's live prediction markets for {asset_desc}.\n\n"
            "## Your framework\n\n"
            "**Market selection and filtering**\n"
            "- Only use markets with a clear *causal* relationship to the asset. "
            "Direct price markets (e.g. 'Will BTC reach $X?') are highest priority. "
            "Macro markets (Fed rate decisions, recession probabilities, regulatory events) "
            "are included when they demonstrably affect this asset class.\n"
            "- Ignore markets about unrelated assets or events with no plausible causal path.\n\n"
            "**Probability interpretation**\n"
            "- Polymarket prices ARE probabilities: a market trading at 0.65 means the "
            "crowd assigns 65% chance to that outcome.\n"
            "- Order-book weighted prices (when available) are more accurate than last-trade.\n"
            "- Aggregate multiple markets into a bull/bear score with a time horizon.\n\n"
            "**Signal synthesis**\n"
            "- What is the market-implied directional bias (bullish / bearish / neutral)?\n"
            "- What is the consensus time horizon (intraday / days / weeks / months)?\n"
            "- Are there high-volume conviction markets that dominate the signal?\n"
            "- Are there any surprising or asymmetric bets that contrarians should note?\n"
            "- Does the prediction market signal confirm or diverge from technical and "
            "fundamental analysis?\n\n"
            "Produce a concise, actionable report. Append a summary Markdown table. "
            "If the data tool returns a message starting with NA, report NA and the reason. Do not fabricate a neutral or 50/50 signal when data is absent. Be concise and direct. Keep your response under 4096 characters."
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a helpful AI assistant, collaborating with other analysts. "
                "Use the provided tools to fetch and interpret Polymarket prediction data. "
                "You have access to: {tool_names}.\n{system_message} "
                "Current date: {current_date}. Asset: {ticker}",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ])

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([t.name for t in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain  = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report       = ""
        price_levels = ""
        if len(result.tool_calls) == 0:
            report = result.content
            # Read the probability-surface price ranges that were cached
            # by get_polymarket_data() when the tool was called
            try:
                config    = toolkit.config
                cache_dir = os.path.join(
                    config.get("data_cache_dir", "./data"), "polymarket_cache"
                )
                price_levels = read_price_levels_cache(ticker, cache_dir)
            except Exception:
                price_levels = ""

        return {
            "messages":              [result],
            "polymarket_report":     report,
            "polymarket_price_levels": price_levels,
        }

    return polymarket_analyst_node
