from tradingagents.agents.utils.thinking import strip_thinking
"""Contrarian Researcher — low-delta / high-payout asymmetric perspective.

Trait profile drawn from public-domain knowledge of contrarian and
options-style thinking:
  - "Low delta" = low-probability trade, but payoff is large if correct
    (akin to buying out-of-the-money options for defined risk / unlimited reward)
  - Mean reversion: overextended moves tend to snap back violently
  - Sentiment extremes are the best contrarian signal (Buffett: "Be fearful
    when others are greedy and greedy when others are fearful")
  - Crowded trades are fragile — when everyone is positioned the same way,
    the reversal is violent and fast (crowding = tail risk for consensus)
  - Asymmetric risk/reward: risk is well-defined/small; potential reward is
    multiples larger ("the bet costs little, the prize is big")
  - Technical exhaustion: parabolic moves, RSI divergences, climactic volume,
    exhaustion gaps, reversal candle patterns (doji, hammer, shooting star)
  - COT reports: commercial hedgers vs speculative positioning divergences
  - Catalyst-driven reversals: earnings surprises, macro announcements,
    forced liquidations, squeeze dynamics
  - "Sell the known, buy the unknown" — consensus trades get front-run to death
  - David Dreman, Howard Marks, Michael Burry — contrarian investors who
    deliberately sought what the crowd was ignoring or fleeing
"""


def create_contrarian_researcher(llm):
    def contrarian_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history           = investment_debate_state.get("history", "")
        cta_perspective   = investment_debate_state.get("cta_perspective", "")
        bull_history      = investment_debate_state.get("bull_history", "")
        bear_history      = investment_debate_state.get("bear_history", "")

        market_5m_report    = state["market_report"]
        market_4h_report    = state.get("market_4h_report", "")
        sentiment_report    = state["sentiment_report"]
        news_report         = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        past_analysis       = state.get("past_analysis", "")
        polymarket_price_levels = state.get("polymarket_price_levels", "")

        prompt = f"""You are a Contrarian Researcher who specialises in **asymmetric, low-probability / high-payout setups** — the financial equivalent of buying out-of-the-money options. You actively seek opportunities the consensus is ignoring or has priced incorrectly.

## Your analytical framework

**Sentiment extremes (contrarian entry signals)**
- Is there extreme bullishness or bearishness in the social sentiment, news, or analyst community?
- Extreme greed → fade the crowd and look for a short opportunity.
- Extreme fear / capitulation → the low-delta long trade: limited additional downside, explosive upside if sentiment turns.
- RSI above 80 or below 20 on the 4h timeframe: historically exhausted moves.

**Crowding analysis**
- What trade does everyone appear to be in right now based on the debate and sentiment?
- Crowded longs are vulnerable to stop-cascades and forced liquidations when the move stalls.
- Crowded shorts are vulnerable to short squeezes, especially if a positive catalyst arrives.
- The contrarian asks: *what happens to price if the consensus is forced to exit?*

**Asymmetric risk/reward (the "low delta" lens)**
- From the current price, how much further can the consensus trade realistically push?
- How far is the reversal target if the crowded position unwinds?
- A good contrarian setup: risk = 2–5%, potential reward = 15–40%+ (ratio 1:5 or better).
- The bet may be low probability — that is by design. The edge is in the payoff skew.

**Technical exhaustion signals**
- Is there a bearish or bullish divergence between price and RSI/MACD?
- Parabolic / near-vertical price action on low volume = distribution signal.
- Climactic volume spike followed by failure to make new highs = exhaustion.
- Reversal candlestick patterns at key levels (Bollinger Band extremes, multi-month S/R).

**Catalyst for reversal**
- Is there a known upcoming event (earnings, macro data, regulatory decision) that could force a violent move against the consensus?
- Are there structural imbalances (funding rates, open interest, margin calls) that could accelerate a reversal?

**Margin of safety (Howard Marks)**
- How much cushion does the contrarian entry give?
- What is the narrative the crowd is using — and how much of that narrative is already priced in?

## Your task
1. Identify whether sentiment, positioning, or price action has reached an extreme.
2. Assess whether the current move is overextended or still has genuine room.
3. Define the asymmetric setup: what is the low-delta contrarian play, and why does it offer a favourable payoff?
4. State your recommendation: is this a contrarian long or short? What is the trigger, entry, and protective stop?
5. Address the CTA trend-following view — when does a strong trend become a contrarian fade?

## Resources
Past analysis & scored recommendations: {past_analysis}
Market technical report (5m): {market_5m_report}
Market technical report (4h): {market_4h_report}
Social sentiment: {sentiment_report}
News: {news_report}
Fundamentals: {fundamentals_report}
Full debate history (including CTA view): {history}
Polymarket price range (50%/90% CI vs current price): {polymarket_price_levels}
CTA researcher's perspective: {cta_perspective}

Speak conversationally. Be specific about the asymmetric setup you see. If no genuine contrarian opportunity exists, say so honestly. Be concise and direct. Keep your response under 4096 characters.
"""

        response = llm.invoke(prompt)
        content  = strip_thinking(response.content)[:4096]
        argument = f"Contrarian Researcher: {content}"

        new_state = {**investment_debate_state}
        new_state["history"]                  = history + "\n" + argument
        new_state["contrarian_perspective"]   = argument
        new_state["cta_perspective"]          = cta_perspective
        new_state["bull_history"]             = bull_history
        new_state["bear_history"]             = bear_history

        return {"investment_debate_state": new_state}

    return contrarian_node
