import time
import json
from tradingagents.agents.utils.thinking import strip_thinking


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        market_4h_report = state.get("market_4h_report", "")
        past_analysis     = state.get("past_analysis", "")
        polymarket_report = state.get("polymarket_report", "")
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        investment_debate_state = state["investment_debate_state"]

        curr_situation = f"{market_research_report}\n\n{market_4h_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        cta_perspective        = investment_debate_state.get("cta_perspective", "")
        contrarian_perspective = investment_debate_state.get("contrarian_perspective", "")
        retail_perspective     = investment_debate_state.get("retail_perspective", "")

        prompt = f"""You are the Research Manager — the senior portfolio decision-maker who synthesises input from a five-strong research panel before issuing a definitive investment recommendation.

## Your research panel
1. **Bull Analyst** — fundamental / growth case for the asset
2. **Bear Analyst** — fundamental / risk case against the asset
3. **CTA Researcher** — systematic trend-following, momentum, and price-action view
4. **Contrarian Researcher** — asymmetric / low-delta view; fades consensus extremes; seeks high-payout setups
5. **Retail Researcher** — FOMO dynamics, retail participation, social sentiment, short/gamma squeeze signals

## Your mandate
Weigh all five perspectives and make ONE clear, actionable recommendation: **Buy, Sell, or Hold**.
- Do not default to Hold simply because views conflict. Make a decision.
- Identify which 1–2 perspectives carry the most weight given current market conditions and explain why.
- Note where perspectives converge (high-conviction signal) and where they diverge (uncertainty / smaller size).
- Produce a concrete investment plan for the Trader including rationale and strategic actions.

## Inputs

**Past reflections on similar situations:**
{past_memory_str}

**Iterative context (scored history from prior runs):**
{past_analysis}

**Polymarket prediction market signals:**
{polymarket_report}

**Full debate history (Bull + Bear):**
{history}

**CTA Researcher perspective:**
{cta_perspective}

**Contrarian Researcher perspective:**
{contrarian_perspective}

**Retail Researcher perspective:**
{retail_perspective}

Present your analysis conversationally, without special formatting. Be concise and direct. Keep your response under 4096 characters."""
        response = llm.invoke(prompt)
        content = strip_thinking(response.content)[:4096]

        new_investment_debate_state = {
            "judge_decision":         content,
            "history":                investment_debate_state.get("history", ""),
            "bear_history":           investment_debate_state.get("bear_history", ""),
            "bull_history":           investment_debate_state.get("bull_history", ""),
            "current_response":       content,
            "count":                  investment_debate_state["count"],
            "cta_perspective":        investment_debate_state.get("cta_perspective", ""),
            "contrarian_perspective": investment_debate_state.get("contrarian_perspective", ""),
            "retail_perspective":     investment_debate_state.get("retail_perspective", ""),
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": response.content,
        }

    return research_manager_node
