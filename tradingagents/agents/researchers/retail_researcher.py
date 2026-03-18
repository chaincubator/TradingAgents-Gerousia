from tradingagents.agents.utils.thinking import strip_thinking
"""Retail Madness Researcher — FOMO-driven retail investor behaviour perspective.

Trait profile drawn from public-domain behavioural finance literature:
  - FOMO (Fear of Missing Out): retail piles in after a move is already mature,
    chasing momentum rather than anticipating it (Barber & Odean, 2000)
  - Recency bias: extrapolates recent price action indefinitely;
    last week's 20% gain → expectation of next 20% gain
  - Herding: follows what is trending on social media, Reddit, Twitter/X,
    and financial news; meme stocks, trending hashtags, influencer calls
  - Attention-driven buying: retail predominantly buys assets in the news
    (high-volume, large-move assets attract disproportionate retail attention)
  - Disposition effect: sells winners too early, holds losers too long
    (opposite of "cut losses short, let profits run")
  - Overconfidence after a winning streak: retail increases position size
    and concentration after recent gains, setting up large drawdowns
  - Short squeeze dynamics: coordinated retail buying in heavily-shorted
    assets (GME, AMC model) can force violent short squeezes
  - Gamma dynamics: when retail buys near-term call options en masse,
    market makers delta-hedge by buying the underlying, accelerating the move
  - Retail as a contrarian signal at extremes: retail max-bullishness has
    historically correlated with near-term tops; retail max-fear with bottoms
  - But in strong trends, retail momentum can sustain and amplify moves
    beyond what fundamentals alone justify — the "greater fool" dynamic
  - Key data proxies: social media search volume, app store rankings,
    options put/call ratios, retail brokerage flow data
"""


def create_retail_researcher(llm):
    def retail_node(state) -> dict:
        investment_debate_state   = state["investment_debate_state"]
        history                   = investment_debate_state.get("history", "")
        cta_perspective           = investment_debate_state.get("cta_perspective", "")
        contrarian_perspective    = investment_debate_state.get("contrarian_perspective", "")
        bull_history              = investment_debate_state.get("bull_history", "")
        bear_history              = investment_debate_state.get("bear_history", "")

        market_5m_report    = state["market_report"]
        market_4h_report    = state.get("market_4h_report", "")
        sentiment_report    = state["sentiment_report"]
        news_report         = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        past_analysis       = state.get("past_analysis", "")

        prompt = f"""You are the Retail Madness Researcher. Your job is to channel the collective psychology of retail investors — the FOMO-driven, social-media-influenced, recency-biased crowd. You are **not** being asked to behave irrationally; you are asked to *analyse* how retail behaviour is likely influencing price right now and what it implies for the trade.

## Your analytical framework

**FOMO gauge — is retail currently chasing this asset?**
- Has this asset recently made a large move (e.g., +10% in a week, new all-time high, trending on social media)?
- Large recent gains attract retail attention like moths to a flame. If it's in the news and up big, retail is probably already piling in or about to.
- Signs of active retail FOMO: spike in social media mentions, search trends, options call volume surge, retail broker "most-bought" lists.

**Recency bias amplifier**
- What has the trend been over the last 1–2 weeks? Retail will extrapolate this trend indefinitely.
- If the asset is up 30% in two weeks, retail's mental model is "it'll be up 30% more."
- This creates momentum fuel — the self-fulfilling prophecy — until it doesn't.

**Herding and social media dynamics**
- Is the asset trending on Reddit, Twitter/X, Discord, or financial news?
- Are there prominent influencers or viral posts driving attention?
- Meme-driven assets detach from fundamentals; social momentum IS the trade in the short run.

**Short squeeze / gamma squeeze potential**
- Is this a heavily shorted asset? Retail coordinated buying can force painful short squeezes (reduced float, high short interest, growing call volume).
- Is there a gamma squeeze in motion? Large retail call buying → market maker delta hedging → price acceleration.

**Retail as a contrarian signal (when to FADE the retail herd)**
- At extremes, retail is famously wrong. Record retail bullishness in an asset usually marks a near-term top.
- Signs of retail excess: parabolic move on high volume, mainstream media coverage, "my taxi driver is buying crypto" phenomenon.
- If retail FOMO is fully priced in, who is left to buy?

**Retail panic / capitulation (when retail is the BUY signal)**
- Retail panic-sells near bottoms after seeing large losses — just as smart money accumulates.
- Heavy retail selling (low prices, negative social sentiment, panic posts) can mark a capitulation bottom.
- "When there's blood in the streets, buy property" — the retail panic floor.

**Market microstructure implications**
- Retail order flow is predominantly market orders (no price discipline).
- Large retail buying pressure moves the ask and creates upward price pressure.
- Retail exit is also disorderly — price can gap down when they hit sell at the same time.

## Your task
1. Assess the current level of retail FOMO, participation, and sentiment for this asset.
2. Identify whether retail behaviour is adding fuel to the existing trend (momentum amplifier) or setting up a reversal (contrarian signal).
3. Evaluate any short squeeze or gamma squeeze dynamics.
4. State whether the retail crowd is currently a tailwind or a headwind for the trade.
5. Give your recommendation: buy into / alongside the retail momentum, or fade it as a contrarian signal?
6. Respond to the CTA and Contrarian perspectives — does the retail behaviour confirm or undermine their views?

## Resources
Past analysis & scored recommendations: {past_analysis}
Market technical report (5m): {market_5m_report}
Market technical report (4h): {market_4h_report}
Social sentiment (key input): {sentiment_report}
News (key input): {news_report}
Fundamentals (context): {fundamentals_report}
Full debate history: {history}
CTA researcher's perspective: {cta_perspective}
Contrarian researcher's perspective: {contrarian_perspective}

Speak with the energy and enthusiasm of someone who truly understands retail psychology. Be specific about what retail is likely doing right now and why it matters. Be concise and direct. Keep your response under 4096 characters.
"""

        response = llm.invoke(prompt)
        content  = strip_thinking(response.content)[:4096]
        argument = f"Retail Researcher: {content}"

        new_state = {**investment_debate_state}
        new_state["history"]               = history + "\n" + argument
        new_state["retail_perspective"]    = argument
        new_state["cta_perspective"]       = cta_perspective
        new_state["contrarian_perspective"] = contrarian_perspective
        new_state["bull_history"]          = bull_history
        new_state["bear_history"]          = bear_history

        return {"investment_debate_state": new_state}

    return retail_node
