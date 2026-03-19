"""
Trader and Risk Management Evo - External Prompt Based Agents
"""

import functools
from langchain_core.messages import AIMessage
from typing import Any, Dict
from tradingagents.agents_evo import load_agent_prompt
from tradingagents.agents.utils.thinking import strip_thinking
from tradingagents.agents.utils.context_utils import is_na


def create_trader_evo(llm, memory, bias: str = 'default', variant: str = 'v1'):
    """
    Create a trader node using external prompts.
    
    Args:
        llm: The language model to use
        memory: Memory instance for retrieving past reflections
        bias: Prompt bias variant ('default', 'momentum', etc.)
        variant: Prompt version
    
    Returns:
        A trader node function
    """
    
    prompt_template = load_agent_prompt('trader', bias=bias, variant=variant)
    
    def trader_node(state: Dict[str, Any], name: str = "Trader"):
        company_name = state["company_of_interest"]
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        
        past_analysis = state.get("past_analysis", "")
        cta_perspective = state["investment_debate_state"].get("cta_perspective", "")
        contrarian_perspective = state["investment_debate_state"].get("contrarian_perspective", "")
        retail_perspective = state["investment_debate_state"].get("retail_perspective", "")
        
        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        
        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."
        
        # Format the prompt
        prompt = prompt_template.format(
            company_name=company_name,
            investment_plan=investment_plan,
            past_analysis=past_analysis,
            cta_perspective=cta_perspective[:600] if cta_perspective else "Not available",
            contrarian_perspective=contrarian_perspective[:600] if contrarian_perspective else "Not available",
            retail_perspective=retail_perspective[:600] if retail_perspective else "Not available",
            past_memory_str=past_memory_str
        )
        
        messages = [
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.\n\nProposed Investment Plan: {investment_plan}\n\nLeverage these insights to make an informed and strategic decision.",
            },
        ]
        
        result = llm.invoke(messages)
        trader_content = strip_thinking(result.content)[:4096]
        
        return {
            "messages": [result],
            "trader_investment_plan": trader_content,
            "sender": name,
        }
    
    return functools.partial(trader_node, name="Trader")


def create_risky_debator_evo(llm, bias: str = 'default', variant: str = 'v1'):
    """
    Create a risky debator node using external prompts.
    """
    
    prompt_template = load_agent_prompt('risky_debator', bias=bias, variant=variant)
    
    def risky_node(state: Dict[str, Any]) -> Dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        risky_history = risk_debate_state.get("risky_history", "")
        current_safe_response = risk_debate_state.get("current_safe_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")
        
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        trader_decision = state["trader_investment_plan"]
        
        # Format the prompt
        prompt = prompt_template.format(
            trader_decision=trader_decision,
            market_research_report=market_research_report,
            market_4h_report=market_4h_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            history=history,
            current_safe_response=current_safe_response,
            current_neutral_response=current_neutral_response
        )
        
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]
        argument = f"Risky Analyst: {content}"
        
        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risky_history + "\n" + argument,
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Risky",
            "current_risky_response": argument,
            "current_safe_response": risk_debate_state.get("current_safe_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "count": risk_debate_state["count"] + 1,
        }
        
        return {"risk_debate_state": new_risk_debate_state}
    
    return risky_node


def create_safe_debator_evo(llm, bias: str = 'default', variant: str = 'v1'):
    """
    Create a safe debator node using external prompts.
    """
    
    prompt_template = load_agent_prompt('safe_debator', bias=bias, variant=variant)
    
    def safe_node(state: Dict[str, Any]) -> Dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        safe_history = risk_debate_state.get("safe_history", "")
        current_risky_response = risk_debate_state.get("current_risky_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")
        
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        trader_decision = state["trader_investment_plan"]
        
        # Format the prompt
        prompt = prompt_template.format(
            trader_decision=trader_decision,
            market_research_report=market_research_report,
            market_4h_report=market_4h_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            history=history,
            current_risky_response=current_risky_response,
            current_neutral_response=current_neutral_response
        )
        
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]
        argument = f"Safe Analyst: {content}"
        
        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": safe_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Safe",
            "current_risky_response": risk_debate_state.get("current_risky_response", ""),
            "current_safe_response": argument,
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "count": risk_debate_state["count"] + 1,
        }
        
        return {"risk_debate_state": new_risk_debate_state}
    
    return safe_node


def create_neutral_debator_evo(llm, bias: str = 'default', variant: str = 'v1'):
    """
    Create a neutral debator node using external prompts.
    """
    
    prompt_template = load_agent_prompt('neutral_debator', bias=bias, variant=variant)
    
    def neutral_node(state: Dict[str, Any]) -> Dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")
        current_risky_response = risk_debate_state.get("current_risky_response", "")
        current_safe_response = risk_debate_state.get("current_safe_response", "")
        
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        trader_decision = state["trader_investment_plan"]
        
        # Format the prompt
        prompt = prompt_template.format(
            trader_decision=trader_decision,
            market_research_report=market_research_report,
            market_4h_report=market_4h_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            history=history,
            current_risky_response=current_risky_response,
            current_safe_response=current_safe_response
        )
        
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]
        argument = f"Neutral Analyst: {content}"
        
        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_risky_response": risk_debate_state.get("current_risky_response", ""),
            "current_safe_response": risk_debate_state.get("current_safe_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }
        
        return {"risk_debate_state": new_risk_debate_state}
    
    return neutral_node


def create_risk_manager_evo(llm, memory, bias: str = 'default', variant: str = 'v1'):
    """
    Create a risk manager node using external prompts.
    """
    
    prompt_template = load_agent_prompt('risk_manager', bias=bias, variant=variant)
    
    def risk_manager_node(state: Dict[str, Any]) -> Dict:
        company_name = state["company_of_interest"]
        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        news_report = state["news_report"]
        fundamentals_report = state["news_report"]
        sentiment_report = state["sentiment_report"]
        trader_plan = state["investment_plan"]
        
        curr_situation = f"{market_research_report}\n\n{market_4h_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        
        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"
        
        # Format the prompt
        prompt = prompt_template.format(
            company_name=company_name,
            history=history,
            market_research_report=market_research_report,
            market_4h_report=market_4h_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            sentiment_report=sentiment_report,
            trader_plan=trader_plan,
            past_memory_str=past_memory_str
        )
        
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]
        
        new_risk_debate_state = {
            "judge_decision": content,
            "history": risk_debate_state["history"],
            "risky_history": risk_debate_state["risky_history"],
            "safe_history": risk_debate_state["safe_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_risky_response": risk_debate_state["current_risky_response"],
            "current_safe_response": risk_debate_state["current_safe_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }
        
        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": content,
        }
    
    return risk_manager_node
