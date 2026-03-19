"""
Researchers Evo - External Prompt Based Research Agents

This package provides researcher agents using external prompts.
"""

from langchain_core.messages import AIMessage
from typing import Any, Dict
from tradingagents.agents_evo import load_agent_prompt
from tradingagents.agents.utils.thinking import strip_thinking
from tradingagents.agents.utils.context_utils import is_na


def create_bull_researcher_evo(llm, memory, bias: str = 'default', variant: str = 'v1'):
    """
    Create a bull researcher node using external prompts.
    
    Args:
        llm: The language model to use
        memory: Memory instance for retrieving past reflections
        bias: Prompt bias variant ('default', 'aggressive', etc.)
        variant: Prompt version
    
    Returns:
        A bull researcher node function
    """
    
    prompt_template = load_agent_prompt('bull_researcher', bias=bias, variant=variant)
    
    def bull_node(state: Dict[str, Any]) -> Dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")
        current_response = investment_debate_state.get("current_response", "")
        
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        
        past_analysis = state.get("past_analysis", "")
        polymarket_report = state.get("polymarket_report", "")
        polymarket_price_levels = state.get("polymarket_price_levels", "")
        fred_report = state.get("fred_report", "")
        
        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        
        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"
        
        # Format the prompt with all variables
        prompt = prompt_template.format(
            past_analysis=past_analysis,
            polymarket_report=polymarket_report if not is_na(polymarket_report) else "",
            polymarket_price_levels=polymarket_price_levels if not is_na(polymarket_price_levels) else "",
            fred_report=fred_report if not is_na(fred_report) else "",
            market_research_report=market_research_report,
            market_4h_report=market_4h_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            history=history,
            current_response=current_response,
            past_memory_str=past_memory_str
        )
        
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]
        argument = f"Bull Analyst: {content}"
        
        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }
        
        return {"investment_debate_state": new_investment_debate_state}
    
    return bull_node


def create_bear_researcher_evo(llm, memory, bias: str = 'default', variant: str = 'v1'):
    """
    Create a bear researcher node using external prompts.
    
    Args:
        llm: The language model to use
        memory: Memory instance for retrieving past reflections
        bias: Prompt bias variant ('default', 'conservative', etc.)
        variant: Prompt version
    
    Returns:
        A bear researcher node function
    """
    
    prompt_template = load_agent_prompt('bear_researcher', bias=bias, variant=variant)
    
    def bear_node(state: Dict[str, Any]) -> Dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")
        current_response = investment_debate_state.get("current_response", "")
        
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        
        past_analysis = state.get("past_analysis", "")
        polymarket_report = state.get("polymarket_report", "")
        polymarket_price_levels = state.get("polymarket_price_levels", "")
        fred_report = state.get("fred_report", "")
        
        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        
        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"
        
        # Format the prompt with all variables
        prompt = prompt_template.format(
            past_analysis=past_analysis,
            polymarket_report=polymarket_report if not is_na(polymarket_report) else "",
            polymarket_price_levels=polymarket_price_levels if not is_na(polymarket_price_levels) else "",
            fred_report=fred_report if not is_na(fred_report) else "",
            market_research_report=market_research_report,
            market_4h_report=market_4h_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            history=history,
            current_response=current_response,
            past_memory_str=past_memory_str
        )
        
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]
        argument = f"Bear Analyst: {content}"
        
        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }
        
        return {"investment_debate_state": new_investment_debate_state}
    
    return bear_node
