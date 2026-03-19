"""
Market Analyst - Evo Variant

This module provides market analyst functionality using external prompts.
Supports multiple bias variants for A/B testing and specialized analysis styles.

Available Variants:
- default.v1: Standard market analysis
- technical.v1: Technical analysis focused
- momentum.v1: Momentum and trend focused (coming soon)
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from typing import Any, Dict
from tradingagents.agents_evo import load_agent_prompt
from tradingagents.dataflows.tradfi_utils import classify_symbol, get_instrument_info


def create_market_analyst_evo(llm, toolkit, bias: str = 'default', variant: str = 'v1'):
    """
    Create a market analyst node using external prompts.
    
    Args:
        llm: The language model to use
        toolkit: The toolkit with available functions
        bias: Prompt bias variant ('default', 'technical', 'momentum', etc.)
        variant: Prompt version ('v1', 'v2', etc.)
    
    Returns:
        A market analyst node function for use in LangGraph
    """
    
    # Load the prompt template
    prompt_template = load_agent_prompt('market_analyst', bias=bias, variant=variant)
    
    def market_analyst_node(state: Dict[str, Any]) -> Dict[str, Any]:
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        # Select tools based on instrument type
        if instrument_type == "tradfi":
            info = get_instrument_info(ticker)
            tools = [toolkit.get_tradfi_price_history, toolkit.get_tradfi_technical_analysis]
        elif instrument_type == "crypto":
            tools = [toolkit.get_crypto_price_history, toolkit.get_crypto_technical_analysis]
        else:
            # Stock
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

        # Build the prompt
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    prompt_template
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        # Partial the prompt with variables
        prompt = prompt.partial(
            tool_names=", ".join([tool.name for tool in tools]),
            current_date=current_date,
            ticker=ticker
        )

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


def create_market_4h_analyst_evo(llm, toolkit, bias: str = 'default', variant: str = 'v1'):
    """
    Create a 4-hour market analyst node using external prompts.
    
    Args:
        llm: The language model to use
        toolkit: The toolkit with available functions
        bias: Prompt bias variant
        variant: Prompt version
    
    Returns:
        A 4-hour market analyst node function
    """
    
    # For now, use the same prompt but could have dedicated 4h variants
    prompt_template = load_agent_prompt('market_analyst', bias=bias, variant=variant)
    
    def market_4h_analyst_node(state: Dict[str, Any]) -> Dict[str, Any]:
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        instrument_type = classify_symbol(ticker)

        if instrument_type == "tradfi":
            info = get_instrument_info(ticker)
            tools = [toolkit.get_tradfi_price_history, toolkit.get_tradfi_technical_analysis]
        elif instrument_type == "crypto":
            tools = [
                toolkit.get_crypto_4h_price_history,
                toolkit.get_crypto_4h_technical_analysis,
            ]
        else:
            # Stock - fall back to daily data
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

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    prompt_template
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(
            tool_names=", ".join([t.name for t in tools]),
            current_date=current_date,
            ticker=ticker
        )

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
