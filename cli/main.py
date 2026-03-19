from typing import Optional
import datetime
import typer
from pathlib import Path
from functools import wraps
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.columns import Columns
from rich.markdown import Markdown
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich.table import Table
from collections import deque
import time
from rich.tree import Tree
from rich import box
from rich.align import Align
from rich.rule import Rule

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from cli.models import AnalystType
from cli.utils import *

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
)


# Create a deque to store recent messages with a maximum length
class MessageBuffer:
    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None  # Store the complete final report
        self.agent_status = {
            # Analyst Team
            "FRED Macro Analyst": "pending",
            "Polymarket Analyst": "pending",
            "Market Analyst (5m)": "pending",
            "Market Analyst (4h)": "pending",
            "Social Analyst": "pending",
            "News Analyst": "pending",
            "Fundamentals Analyst": "pending",
            # Research Team
            "Bull Researcher": "pending",
            "Bear Researcher": "pending",
            "CTA Researcher": "pending",
            "Contrarian Researcher": "pending",
            "Retail Researcher": "pending",
            "Research Manager": "pending",
            # Trading Team
            "Trader": "pending",
            # Risk Management Team
            "Risky Analyst": "pending",
            "Neutral Analyst": "pending",
            "Safe Analyst": "pending",
            # Portfolio Management Team
            "Portfolio Manager": "pending",
        }
        self.current_agent = None
        self.report_sections = {
            "fred_report": None,
            "polymarket_report": None,
            "market_report": None,
            "market_4h_report": None,
            "sentiment_report": None,
            "news_report": None,
            "fundamentals_report": None,
            "investment_plan": None,
            "trader_investment_plan": None,
            "final_trade_decision": None,
        }

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        # For the panel display, only show the most recently updated section
        latest_section = None
        latest_content = None

        # Find the most recently updated section
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content
               
        if latest_section and latest_content:
            # Format the current section for display
            section_titles = {
                "polymarket_report":     "Polymarket Signals",
                "market_report":         "Market Analysis (5m)",
                "market_4h_report":      "Market Analysis (4h)",
                "sentiment_report":      "Social Sentiment",
                "news_report":           "News Analysis",
                "fundamentals_report":   "Fundamentals Analysis",
                "investment_plan":       "Research Team Decision",
                "trader_investment_plan":"Trading Plan",
                "final_trade_decision":  "Final Trade Decision",
            }
            self.current_report = (
                f"### {section_titles.get(latest_section, latest_section)}\n{latest_content}"
            )

        # Update the final complete report
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        # Analyst Team Reports
        analyst_sections = [
            "polymarket_report", "market_report", "market_4h_report",
            "sentiment_report", "news_report", "fundamentals_report",
        ]
        analyst_labels = {
            "polymarket_report":  "Polymarket Prediction Market Signals",
            "market_report":      "Market Analysis (5m)",
            "market_4h_report":   "Market Analysis (4h)",
            "sentiment_report":   "Social Sentiment",
            "news_report":        "News Analysis",
            "fundamentals_report":"Fundamentals Analysis",
        }
        if any(self.report_sections.get(s) for s in analyst_sections):
            report_parts.append("## Analyst Team Reports")
            for sec in analyst_sections:
                if self.report_sections.get(sec):
                    report_parts.append(
                        f"### {analyst_labels[sec]}\n{self.report_sections[sec]}"
                    )

        # Research Team Reports
        if self.report_sections["investment_plan"]:
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")

        # Trading Team Reports
        if self.report_sections["trader_investment_plan"]:
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")

        # Portfolio Management Decision
        if self.report_sections["final_trade_decision"]:
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")

        self.final_report = "\n\n".join(report_parts) if report_parts else None


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", ratio=3), Layout(name="analysis", ratio=5)
    )
    layout["upper"].split_row(
        Layout(name="progress", ratio=2), Layout(name="messages", ratio=3)
    )
    return layout


def update_display(layout, spinner_text=None):
    # Header with welcome message
    layout["header"].update(
        Panel(
            "[bold green]Welcome to TradingAgents CLI[/bold green]\n"
            "[dim]Built by [chaincubator](https://github.com/chaincubator) · Based on [Tauric Research](https://github.com/TauricResearch/TradingAgents)[/dim]",
            title="Welcome to TradingAgents",
            border_style="green",
            padding=(1, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("Agent", style="green", justify="center", width=20)
    progress_table.add_column("Status", style="yellow", justify="center", width=20)

    # Group agents by team
    teams = {
        "Analyst Team": [
            "Market Analyst",
            "Social Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Risky Analyst", "Neutral Analyst", "Safe Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status[first_agent]
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]in_progress[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{status}[/{status_color}]"
        progress_table.add_row(team, first_agent, status_cell)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status[agent]
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]in_progress[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{status}[/{status_color}]"
            progress_table.add_row("", agent, status_cell)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("Time", style="cyan", width=8, justify="center")
    messages_table.add_column("Type", style="green", width=10, justify="center")
    messages_table.add_column(
        "Content", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    for timestamp, tool_name, args in message_buffer.tool_calls:
        # Truncate tool call args if too long
        if isinstance(args, str) and len(args) > 100:
            args = args[:97] + "..."
        all_messages.append((timestamp, "Tool", f"{tool_name}: {args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        # Convert content to string if it's not already
        content_str = content
        if isinstance(content, list):
            # Handle list of content blocks (Anthropic format)
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                    elif item.get('type') == 'tool_use':
                        text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
                else:
                    text_parts.append(str(item))
            content_str = ' '.join(text_parts)
        elif not isinstance(content_str, str):
            content_str = str(content)
            
        # Truncate message content if too long
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, msg_type, content_str))

    # Sort by timestamp
    all_messages.sort(key=lambda x: x[0])

    # Calculate how many messages we can show based on available space
    # Start with a reasonable number and adjust based on content length
    max_messages = 12  # Increased from 8 to better fill the space

    # Get the last N messages that will fit in the panel
    recent_messages = all_messages[-max_messages:]

    # Add messages to table
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    if spinner_text:
        messages_table.add_row("", "Spinner", spinner_text)

    # Add a footer to indicate if messages were truncated
    if len(all_messages) > max_messages:
        messages_table.footer = (
            f"[dim]Showing last {max_messages} of {len(all_messages)} messages[/dim]"
        )

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel showing current report
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]Waiting for analysis report...[/italic]",
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )

    # Footer with statistics
    tool_calls_count = len(message_buffer.tool_calls)
    llm_calls_count = sum(
        1 for _, msg_type, _ in message_buffer.messages if msg_type == "Reasoning"
    )
    reports_count = sum(
        1 for content in message_buffer.report_sections.values() if content is not None
    )

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(
        f"Tool Calls: {tool_calls_count} | LLM Calls: {llm_calls_count} | Generated Reports: {reports_count}"
    )

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections():
    """Get all user selections before starting the analysis display."""
    # Display ASCII art welcome message
    with open("./cli/static/welcome.txt", "r") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]TradingAgents: Multi-Agents LLM Financial Trading Framework - CLI[/bold green]\n\n"
    welcome_content += "[bold]Workflow Steps:[/bold]\n"
    welcome_content += "I. Analyst Team → II. Research Team → III. Trader → IV. Risk Management → V. Portfolio Management\n\n"
    welcome_content += (
        "[dim]Built by [chaincubator](https://github.com/chaincubator) · Based on [Tauric Research](https://github.com/TauricResearch/TradingAgents)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="Welcome to TradingAgents",
        subtitle="Multi-Agents LLM Financial Trading Framework",
    )
    console.print(Align.center(welcome_box))
    console.print()  # Add a blank line after the welcome box

    # Create a boxed questionnaire for each step
    def create_question_box(title, prompt, default=None):
        box_content = f"[bold]{title}[/bold]\n"
        box_content += f"[dim]{prompt}[/dim]"
        if default:
            box_content += f"\n[dim]Default: {default}[/dim]"
        return Panel(box_content, border_style="blue", padding=(1, 2))

    # Step 1: Ticker symbol(s)
    console.print(
        create_question_box(
            "Step 1: Ticker Symbol(s)",
            "Enter one or more symbols (comma or space separated) — e.g. BTC ETH SOL",
            "BTC",
        )
    )
    selected_tickers = get_ticker()

    # Step 2: Analysis date
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        create_question_box(
            "Step 2: Analysis Date",
            "Enter the analysis date (YYYY-MM-DD)",
            default_date,
        )
    )
    analysis_date = get_analysis_date()

    # Step 3: Select analysts
    console.print(
        create_question_box(
            "Step 3: Analysts Team", "Select your LLM analyst agents for the analysis"
        )
    )
    selected_analysts = select_analysts()
    console.print(
        f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 4: Research depth
    console.print(
        create_question_box(
            "Step 4: Research Depth", "Select your research depth level"
        )
    )
    selected_research_depth = select_research_depth()

    # Step 5: OpenAI backend
    console.print(
        create_question_box(
            "Step 5: OpenAI backend", "Select which service to talk to"
        )
    )
    selected_llm_provider, backend_url = select_llm_provider()
    
    # Step 6: Thinking agents
    console.print(
        create_question_box(
            "Step 6: Thinking Agents", "Select your thinking agents for analysis"
        )
    )
    selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
    selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)

    return {
        "tickers": selected_tickers,
        "analysis_date": analysis_date,
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "llm_provider": selected_llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
    }


def get_ticker() -> List[str]:
    """Get one or more ticker symbols from user input (comma or space separated)."""
    import re
    raw = typer.prompt("", default="BTC")
    symbols = [s.upper() for s in re.split(r'[,\s]+', raw.strip()) if s]
    return symbols if symbols else ["BTC"]


def get_analysis_date():
    """Get the analysis date from user input."""
    while True:
        date_str = typer.prompt(
            "", default=datetime.datetime.now().strftime("%Y-%m-%d")
        )
        try:
            # Validate date format and ensure it's not in the future
            analysis_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if analysis_date.date() > datetime.datetime.now().date():
                console.print("[red]Error: Analysis date cannot be in the future[/red]")
                continue
            return date_str
        except ValueError:
            console.print(
                "[red]Error: Invalid date format. Please use YYYY-MM-DD[/red]"
            )


def display_complete_report(final_state):
    """Display the complete analysis report with team-based panels."""
    console.print("\n[bold green]Complete Analysis Report[/bold green]\n")

    # I. Analyst Team Reports
    analyst_reports = []

    # Market Analyst Report
    if final_state.get("market_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["market_report"]),
                title="Market Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # Social Analyst Report
    if final_state.get("sentiment_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["sentiment_report"]),
                title="Social Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # News Analyst Report
    if final_state.get("news_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["news_report"]),
                title="News Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    # Fundamentals Analyst Report
    if final_state.get("fundamentals_report"):
        analyst_reports.append(
            Panel(
                Markdown(final_state["fundamentals_report"]),
                title="Fundamentals Analyst",
                border_style="blue",
                padding=(1, 2),
            )
        )

    if analyst_reports:
        console.print(
            Panel(
                Columns(analyst_reports, equal=True, expand=True),
                title="I. Analyst Team Reports",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    # II. Research Team Reports
    if final_state.get("investment_debate_state"):
        research_reports = []
        debate_state = final_state["investment_debate_state"]

        # Bull Researcher Analysis
        if debate_state.get("bull_history"):
            research_reports.append(
                Panel(
                    Markdown(debate_state["bull_history"]),
                    title="Bull Researcher",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Bear Researcher Analysis
        if debate_state.get("bear_history"):
            research_reports.append(
                Panel(
                    Markdown(debate_state["bear_history"]),
                    title="Bear Researcher",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Research Manager Decision
        if debate_state.get("judge_decision"):
            research_reports.append(
                Panel(
                    Markdown(debate_state["judge_decision"]),
                    title="Research Manager",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        if research_reports:
            console.print(
                Panel(
                    Columns(research_reports, equal=True, expand=True),
                    title="II. Research Team Decision",
                    border_style="magenta",
                    padding=(1, 2),
                )
            )

    # III. Trading Team Reports
    if final_state.get("trader_investment_plan"):
        console.print(
            Panel(
                Panel(
                    Markdown(final_state["trader_investment_plan"]),
                    title="Trader",
                    border_style="blue",
                    padding=(1, 2),
                ),
                title="III. Trading Team Plan",
                border_style="yellow",
                padding=(1, 2),
            )
        )

    # IV. Risk Management Team Reports
    if final_state.get("risk_debate_state"):
        risk_reports = []
        risk_state = final_state["risk_debate_state"]

        # Aggressive (Risky) Analyst Analysis
        if risk_state.get("risky_history"):
            risk_reports.append(
                Panel(
                    Markdown(risk_state["risky_history"]),
                    title="Aggressive Analyst",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Conservative (Safe) Analyst Analysis
        if risk_state.get("safe_history"):
            risk_reports.append(
                Panel(
                    Markdown(risk_state["safe_history"]),
                    title="Conservative Analyst",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        # Neutral Analyst Analysis
        if risk_state.get("neutral_history"):
            risk_reports.append(
                Panel(
                    Markdown(risk_state["neutral_history"]),
                    title="Neutral Analyst",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

        if risk_reports:
            console.print(
                Panel(
                    Columns(risk_reports, equal=True, expand=True),
                    title="IV. Risk Management Team Decision",
                    border_style="red",
                    padding=(1, 2),
                )
            )

        # V. Portfolio Manager Decision
        if risk_state.get("judge_decision"):
            console.print(
                Panel(
                    Panel(
                        Markdown(risk_state["judge_decision"]),
                        title="Portfolio Manager",
                        border_style="blue",
                        padding=(1, 2),
                    ),
                    title="V. Portfolio Manager Decision",
                    border_style="green",
                    padding=(1, 2),
                )
            )


def update_research_team_status(status):
    """Update status for all research team members and trader."""
    research_team = [
        "Bull Researcher", "Bear Researcher",
        "CTA Researcher", "Contrarian Researcher", "Retail Researcher",
        "Research Manager", "Trader",
    ]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)

def extract_content_string(content):
    """Extract string content from various message formats."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Handle Anthropic's list format
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') == 'text':
                    text_parts.append(item.get('text', ''))
                elif item.get('type') == 'tool_use':
                    text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
            else:
                text_parts.append(str(item))
        return ' '.join(text_parts)
    else:
        return str(content)

_SECTION_HEADINGS = {
    "fred_report":          "## FRED Macro Snapshot (Growth/Labor/Liquidity)",
    "polymarket_report":    "## Polymarket Prediction Market Signals",
    "market_report":        "## Market Analysis (5m)",
    "market_4h_report":     "## Market Analysis (4h)",
    "sentiment_report":     "## Social Sentiment",
    "news_report":          "## News Analysis",
    "fundamentals_report":  "## Fundamentals Analysis",
    "investment_plan":      "## Research Team Decision",
    "trader_investment_plan": "## Trading Plan",
    "final_trade_decision": "## Final Trade Decision",
}


def _save_combined_report(ticker: str, analysis_date: str,
                          final_state: dict, results_dir: Path) -> None:
    """Write results/{ticker}/{date}/full_report.md combining all sections."""
    parts = [f"# {ticker} — Full Analysis Report\n**Date:** {analysis_date}\n\n---\n"]
    for key, heading in _SECTION_HEADINGS.items():
        content = final_state.get(key, "")
        if content:
            parts.append(f"{heading}\n\n{content}\n\n---\n")
    (results_dir / "full_report.md").write_text("\n".join(parts), encoding="utf-8")


def _patch_message_buffer(log_file: Path, report_dir: Path):
    """Re-patch message_buffer instance methods to write to per-ticker files.

    Always wraps the original class methods (not already-patched instances)
    so repeated calls for successive tickers do not chain wrappers.
    """
    def _msg(message_type, content):
        MessageBuffer.add_message(message_buffer, message_type, content)
        ts, mt, c = message_buffer.messages[-1]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{ts} [{mt}] {c.replace(chr(10), ' ')}\n")

    def _tool(tool_name, tool_args):
        MessageBuffer.add_tool_call(message_buffer, tool_name, tool_args)
        ts, tn, a = message_buffer.tool_calls[-1]
        args_str = ", ".join(f"{k}={v}" for k, v in a.items())
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{ts} [Tool Call] {tn}({args_str})\n")

    def _report(section_name, content):
        MessageBuffer.update_report_section(message_buffer, section_name, content)
        if message_buffer.report_sections.get(section_name):
            with open(report_dir / f"{section_name}.md", "w", encoding="utf-8") as f:
                f.write(message_buffer.report_sections[section_name])

    message_buffer.add_message = _msg
    message_buffer.add_tool_call = _tool
    message_buffer.update_report_section = _report


def _run_ticker_analysis(ticker: str, analysis_date: str, selections, graph, layout,
                         fred_report: str = "") -> dict:
    """Run the full agent pipeline for a single ticker and return final_state."""
    update_display(layout)

    message_buffer.add_message("System", f"Selected ticker: {ticker}")
    message_buffer.add_message("System", f"Analysis date: {analysis_date}")
    message_buffer.add_message(
        "System",
        f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
    )
    update_display(layout)

    for agent in message_buffer.agent_status:
        message_buffer.update_agent_status(agent, "pending")
    for section in message_buffer.report_sections:
        message_buffer.report_sections[section] = None
    message_buffer.current_report = None
    message_buffer.final_report = None

    first_analyst = f"{selections['analysts'][0].value.capitalize()} Analyst"
    message_buffer.update_agent_status(first_analyst, "in_progress")
    update_display(layout)

    update_display(layout, f"Analyzing {ticker} on {analysis_date}...")

    init_agent_state = graph.propagator.create_initial_state(
        ticker, analysis_date, past_context, fred_report
    )
    args = graph.propagator.get_graph_args()

    # Stream the analysis
    trace = []
    for chunk in graph.graph.stream(init_agent_state, **args):
        if len(chunk["messages"]) > 0:
            last_message = chunk["messages"][-1]
            if hasattr(last_message, "content"):
                content = extract_content_string(last_message.content)
                msg_type = "Reasoning"
            else:
                content = str(last_message)
                msg_type = "System"
            message_buffer.add_message(msg_type, content)
            if hasattr(last_message, "tool_calls"):
                for tool_call in last_message.tool_calls:
                    if isinstance(tool_call, dict):
                        message_buffer.add_tool_call(tool_call["name"], tool_call["args"])
                    else:
                        message_buffer.add_tool_call(tool_call.name, tool_call.args)
            if "fred_report" in chunk and chunk["fred_report"]:
                message_buffer.update_report_section("fred_report", chunk["fred_report"])
                message_buffer.update_agent_status("FRED Macro Analyst", "completed")
            if "polymarket_report" in chunk and chunk["polymarket_report"]:
                message_buffer.update_report_section("polymarket_report", chunk["polymarket_report"])
                message_buffer.update_agent_status("Polymarket Analyst", "completed")
            if "market_4h_report" in chunk and chunk["market_4h_report"]:
                message_buffer.update_report_section("market_4h_report", chunk["market_4h_report"])
                message_buffer.update_agent_status("Market Analyst (4h)", "completed")
            if "market_report" in chunk and chunk["market_report"]:
                message_buffer.update_report_section("market_report", chunk["market_report"])
                message_buffer.update_agent_status("Market Analyst (5m)", "completed")
                if "social" in [a.value for a in selections["analysts"]]:
                    message_buffer.update_agent_status("Social Analyst", "in_progress")
            if "sentiment_report" in chunk and chunk["sentiment_report"]:
                message_buffer.update_report_section("sentiment_report", chunk["sentiment_report"])
                message_buffer.update_agent_status("Social Analyst", "completed")
                if "news" in [a.value for a in selections["analysts"]]:
                    message_buffer.update_agent_status("News Analyst", "in_progress")
            if "news_report" in chunk and chunk["news_report"]:
                message_buffer.update_report_section("news_report", chunk["news_report"])
                message_buffer.update_agent_status("News Analyst", "completed")
                if "fundamentals" in [a.value for a in selections["analysts"]]:
                    message_buffer.update_agent_status("Fundamentals Analyst", "in_progress")
            if "fundamentals_report" in chunk and chunk["fundamentals_report"]:
                message_buffer.update_report_section("fundamentals_report", chunk["fundamentals_report"])
                message_buffer.update_agent_status("Fundamentals Analyst", "completed")
                update_research_team_status("in_progress")
            if "investment_debate_state" in chunk and chunk["investment_debate_state"]:
                debate_state = chunk["investment_debate_state"]
                if "bull_history" in debate_state and debate_state["bull_history"]:
                    update_research_team_status("in_progress")
                    bull_responses = debate_state["bull_history"].split("\n")
                    latest_bull = bull_responses[-1] if bull_responses else ""
                    if latest_bull:
                        message_buffer.add_message("Reasoning", latest_bull)
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bull Researcher Analysis\n{latest_bull}"
                        )
                if "bear_history" in debate_state and debate_state["bear_history"]:
                    update_research_team_status("in_progress")
                    bear_responses = debate_state["bear_history"].split("\n")
                    latest_bear = bear_responses[-1] if bear_responses else ""
                    if latest_bear:
                        message_buffer.add_message("Reasoning", latest_bear)
                        message_buffer.update_report_section(
                            "investment_plan",
                            f"{message_buffer.report_sections['investment_plan']}\n\n### Bear Researcher Analysis\n{latest_bear}",
                        )
                if "cta_perspective" in debate_state and debate_state["cta_perspective"]:
                    message_buffer.update_agent_status("CTA Researcher", "in_progress")
                    latest = debate_state["cta_perspective"].split("\n")[-1]
                    if latest.strip():
                        message_buffer.add_message("Reasoning", latest)
                if "contrarian_perspective" in debate_state and debate_state["contrarian_perspective"]:
                    message_buffer.update_agent_status("CTA Researcher", "completed")
                    message_buffer.update_agent_status("Contrarian Researcher", "in_progress")
                    latest = debate_state["contrarian_perspective"].split("\n")[-1]
                    if latest.strip():
                        message_buffer.add_message("Reasoning", latest)
                if "retail_perspective" in debate_state and debate_state["retail_perspective"]:
                    message_buffer.update_agent_status("Contrarian Researcher", "completed")
                    message_buffer.update_agent_status("Retail Researcher", "in_progress")
                    latest = debate_state["retail_perspective"].split("\n")[-1]
                    if latest.strip():
                        message_buffer.add_message("Reasoning", latest)
                if "judge_decision" in debate_state and debate_state["judge_decision"]:
                    update_research_team_status("in_progress")
                    message_buffer.add_message("Reasoning", f"Research Manager: {debate_state['judge_decision']}")
                    message_buffer.update_report_section(
                        "investment_plan",
                        f"{message_buffer.report_sections['investment_plan']}\n\n### Research Manager Decision\n{debate_state['judge_decision']}",
                    )
                    update_research_team_status("completed")
                    message_buffer.update_agent_status("Risky Analyst", "in_progress")
            if "trader_investment_plan" in chunk and chunk["trader_investment_plan"]:
                message_buffer.update_report_section("trader_investment_plan", chunk["trader_investment_plan"])
                message_buffer.update_agent_status("Risky Analyst", "in_progress")
            if "risk_debate_state" in chunk and chunk["risk_debate_state"]:
                risk_state = chunk["risk_debate_state"]
                if "current_risky_response" in risk_state and risk_state["current_risky_response"]:
                    message_buffer.update_agent_status("Risky Analyst", "in_progress")
                    message_buffer.add_message("Reasoning", f"Risky Analyst: {risk_state['current_risky_response']}")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Risky Analyst Analysis\n{risk_state['current_risky_response']}"
                    )
                if "current_safe_response" in risk_state and risk_state["current_safe_response"]:
                    message_buffer.update_agent_status("Safe Analyst", "in_progress")
                    message_buffer.add_message("Reasoning", f"Safe Analyst: {risk_state['current_safe_response']}")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Safe Analyst Analysis\n{risk_state['current_safe_response']}"
                    )
                if "current_neutral_response" in risk_state and risk_state["current_neutral_response"]:
                    message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                    message_buffer.add_message("Reasoning", f"Neutral Analyst: {risk_state['current_neutral_response']}")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Neutral Analyst Analysis\n{risk_state['current_neutral_response']}"
                    )
                if "judge_decision" in risk_state and risk_state["judge_decision"]:
                    message_buffer.update_agent_status("Portfolio Manager", "in_progress")
                    message_buffer.add_message("Reasoning", f"Portfolio Manager: {risk_state['judge_decision']}")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Portfolio Manager Decision\n{risk_state['judge_decision']}"
                    )
                    message_buffer.update_agent_status("Risky Analyst", "completed")
                    message_buffer.update_agent_status("Safe Analyst", "completed")
                    message_buffer.update_agent_status("Neutral Analyst", "completed")
                    message_buffer.update_agent_status("Portfolio Manager", "completed")
            update_display(layout)
        trace.append(chunk)

    final_state = trace[-1]
    graph.process_signal(final_state["final_trade_decision"])

    for agent in message_buffer.agent_status:
        message_buffer.update_agent_status(agent, "completed")
    message_buffer.add_message("Analysis", f"Completed analysis for {ticker} on {analysis_date}")

    for section in message_buffer.report_sections.keys():
        if section in final_state:
            message_buffer.update_report_section(section, final_state[section])

    display_complete_report(final_state)
    update_display(layout)
    return final_state


def run_analysis():
    # First get all user selections
    selections = get_user_selections()
    tickers = selections["tickers"]
    analysis_date = selections["analysis_date"]

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()

    # FRED is macro-level — fetch once and share across all tokens
    all_analyst_values = [a.value for a in selections["analysts"]]
    prefetched_fred = ""
    if "fred" in all_analyst_values:
        console.print("[dim]Fetching FRED macro data (runs once for all tokens)…[/dim]")
        try:
            import tradingagents.dataflows.interface as _iface
            prefetched_fred = _iface.get_fred_macro_data(analysis_date)
            message_buffer.update_agent_status("FRED Macro Analyst", "completed")
        except Exception as _e:
            prefetched_fred = f"FRED data unavailable: {_e}"

    # Build graph WITHOUT the fred analyst (its data is pre-populated)
    graph_analysts = [v for v in all_analyst_values if v != "fred"]

    # Graph is ticker-agnostic — initialise once for all tickers
    graph = TradingAgentsGraph(graph_analysts, config=config, debug=True)

    layout = create_layout()
    symbol_results = {}

    with Live(layout, refresh_per_second=4) as live:
        message_buffer.add_message("System", f"Tickers: {', '.join(tickers)}")
        message_buffer.add_message("System", f"Analysis date: {analysis_date}")
        update_display(layout)

        for ticker in tickers:
            # Per-ticker results directory and log file
            results_dir = Path(config["results_dir"]) / ticker / analysis_date
            results_dir.mkdir(parents=True, exist_ok=True)
            report_dir = results_dir / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            log_file = results_dir / "message_tool.log"
            log_file.touch(exist_ok=True)

            # Patch buffer with fresh per-ticker logging closures
            _patch_message_buffer(log_file, report_dir)

            # Reset buffer state for this ticker
            message_buffer.messages.clear()
            message_buffer.tool_calls.clear()
            for agent in message_buffer.agent_status:
                message_buffer.agent_status[agent] = "pending"
            for sec in message_buffer.report_sections:
                message_buffer.report_sections[sec] = None
            message_buffer.current_report = None
            message_buffer.final_report = None

            final_state = _run_ticker_analysis(
                ticker, analysis_date, selections, graph, layout, prefetched_fred
            )
            symbol_results[ticker] = final_state

            # Save combined full_report.md for this ticker
            _save_combined_report(ticker, analysis_date, final_state, results_dir)
            message_buffer.add_message(
                "System", f"[{ticker}] Full report saved → {results_dir}/full_report.md"
            )

        # Portfolio MVO — only when multiple tickers were analysed
        portfolio_report = None
        if len(tickers) > 1 and len(symbol_results) > 1:
            from tradingagents.agents.portfolio.mvo import run_portfolio_mvo
            message_buffer.add_message("System", "Running portfolio optimisation (MVO)...")
            update_display(layout)
            portfolio_report = run_portfolio_mvo(
                {t: {
                    "final_trade_decision":  symbol_results[t].get("final_trade_decision", ""),
                    "trader_investment_plan": symbol_results[t].get("trader_investment_plan", ""),
                 } for t in symbol_results},
                analysis_date,
            )
            portfolio_dir = Path(config["results_dir"]) / "_portfolio" / analysis_date
            portfolio_dir.mkdir(parents=True, exist_ok=True)
            (portfolio_dir / "portfolio_mvo.md").write_text(portfolio_report, encoding="utf-8")

            # Save combined multi-ticker report: portfolio first, then per-ticker sections
            combined_parts = [portfolio_report, "\n\n---\n\n# Individual Token Reports\n"]
            for t in symbol_results:
                tok_dir = Path(config["results_dir"]) / t / analysis_date
                full_report_path = tok_dir / "full_report.md"
                if full_report_path.exists():
                    combined_parts.append(full_report_path.read_text(encoding="utf-8"))
            (portfolio_dir / "full_portfolio_report.md").write_text(
                "\n\n".join(combined_parts), encoding="utf-8"
            )
            message_buffer.add_message("System", f"Portfolio saved → {portfolio_dir}/portfolio_mvo.md")
            update_display(layout)

    # Print portfolio report to console after the Live display exits
    if portfolio_report:
        from rich.markdown import Markdown as RichMarkdown
        console.print("\n")
        console.print(RichMarkdown(portfolio_report))


@app.command()
def analyze():
    run_analysis()


if __name__ == "__main__":
    app()
