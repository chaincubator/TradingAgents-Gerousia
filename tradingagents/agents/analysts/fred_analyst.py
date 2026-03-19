"""FRED Quantitative Macro Analyst.

Interprets Federal Reserve Bank of St. Louis FRED database indicators
across Growth, Labor, and Liquidity dimensions to derive a macro regime
assessment and its implications for the asset under analysis.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.dataflows.tradfi_utils import classify_symbol, get_instrument_info


def create_fred_analyst(llm, toolkit):
    def fred_analyst_node(state):
        current_date = state["trade_date"]
        ticker       = state["company_of_interest"]

        tools = [toolkit.get_fred_macro_data]

        instrument_type = classify_symbol(ticker)
        if instrument_type == "tradfi":
            info       = get_instrument_info(ticker)
            asset_desc = f"{info['name']} ({ticker.upper()})"
            asset_type = info["type"].replace("_", " ")
        elif instrument_type == "crypto":
            asset_desc = f"{ticker.upper()} cryptocurrency"
            asset_type = "cryptocurrency"
        else:
            asset_desc = f"{ticker.upper()} equity"
            asset_type = "equity"

        system_message = (
            f"You are a Quantitative Macro Analyst using FRED (Federal Reserve Bank of "
            f"St. Louis) economic database data to derive a macro regime assessment "
            f"and its implications for {asset_desc}.\n\n"
            "## Your framework\n\n"
            "**Growth dimension**\n"
            "- Is the economy expanding or contracting? (Real GDP growth, industrial "
            "production, consumer spending)\n"
            "- Is inflation above or below the Fed's 2% target? (Core CPI)\n"
            "- Is consumer confidence supportive of spending? (Michigan Sentiment, Retail Sales)\n\n"
            "**Labor dimension**\n"
            "- Is the labor market tight or loosening? (Unemployment rate, payrolls, "
            "initial claims trend)\n"
            "- Is wage growth creating inflation pressure? (Avg Hourly Earnings YoY)\n"
            "- Are job openings still elevated vs unemployed? (JOLTS)\n\n"
            "**Liquidity dimension**\n"
            "- Is financial liquidity expanding or contracting? (M2, Fed balance sheet)\n"
            "- What is the current rate regime? (Effective Fed Funds Rate)\n"
            "- Is the yield curve normal or inverted? (10Y-2Y spread)\n"
            "- Are credit conditions stressed? (High-Yield OAS spread)\n"
            "- Is the USD strengthening or weakening? (USD/EUR)\n\n"
            "## Asset-specific macro impact\n"
            f"For a {asset_type}:\n"
            "- Crypto/risk assets: thrive in easy liquidity + expansion; suffer in "
            "tight liquidity + contraction\n"
            "- Precious metals: benefit from high inflation, weak USD, financial stress\n"
            "- Equity indices: sensitive to growth and earnings; hurt by rising rates\n"
            "- Fixed income ETFs (TLT etc.): inversely related to rate expectations\n"
            "- Country ETFs: affected by USD strength, global risk appetite, local "
            "economic conditions vs US\n\n"
            "## Output\n"
            "1. Macro regime classification: Growth × Labor × Liquidity\n"
            "2. Specific bullish/bearish macro implications for this asset\n"
            "3. Key inflection points to watch (next Fed meeting, jobs report, CPI)\n"
            "4. Append a concise Markdown summary table.\n"
            "Be concise and direct. Keep your response under 4096 characters."
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a helpful AI assistant collaborating with other analysts. "
                "Use the provided tools to fetch FRED macro data. "
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

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages":   [result],
            "fred_report": report,
        }

    return fred_analyst_node
