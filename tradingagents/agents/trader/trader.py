import functools
import time
import json
from tradingagents.agents.utils.thinking import strip_thinking


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        past_analysis          = state.get("past_analysis", "")
        cta_perspective        = state["investment_debate_state"].get("cta_perspective", "")
        contrarian_perspective = state["investment_debate_state"].get("contrarian_perspective", "")
        retail_perspective     = state["investment_debate_state"].get("retail_perspective", "")
        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        context = {
            "role": "user",
            "content": f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.\n\nProposed Investment Plan: {investment_plan}\n\nLeverage these insights to make an informed and strategic decision.",
        }

        messages = [
            {
                "role": "system",
                "content": f"""You are a trading agent analyzing market data to make investment decisions. Based on your analysis, provide a specific recommendation to buy, sell, or hold.

Iterative context — scored history from previous runs on this asset:
{past_analysis}

Additional research perspectives to consider alongside the investment plan:
- CTA / Trend-following view: {cta_perspective[:600] if cta_perspective else "Not available"}
- Contrarian / Asymmetric view: {contrarian_perspective[:600] if contrarian_perspective else "Not available"}
- Retail / FOMO dynamics view: {retail_perspective[:600] if retail_perspective else "Not available"}

Do not forget to utilize lessons from past decisions. Reflections from similar situations: {past_memory_str}

You MUST end your response with ALL FOUR of the following labelled lines (no exceptions):
FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**
TAKE PROFIT: $<specific price level>
STOP LOSS: $<specific price level>
VALIDITY: <duration, e.g. "3 days", "1 week", "2 weeks">

Be concise and direct. Keep your response under 4096 characters.""",
            },
            context,
        ]

        result = llm.invoke(messages)
        trader_content = strip_thinking(result.content)[:4096]

        return {
            "messages": [result],
            "trader_investment_plan": trader_content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
