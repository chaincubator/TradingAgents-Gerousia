from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
import datetime
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
import os
import re
import secrets

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Ordered section headings used when building combined Markdown reports
_SECTION_HEADINGS = {
    "market_report":          "## Market Analysis (5m)",
    "market_4h_report":       "## Market Analysis (4h)",
    "sentiment_report":       "## Social Sentiment",
    "news_report":            "## News Analysis",
    "fundamentals_report":    "## Fundamentals Analysis",
    "investment_plan":        "## Research Team Decision",
    "trader_investment_plan": "## Trading Plan",
    "final_trade_decision":   "## Final Trade Decision",
}


def _web_results_dir(session_id: str) -> Path:
    """Base results directory for a web session."""
    base = Path(os.getenv("TRADINGAGENTS_RESULTS_DIR", DEFAULT_CONFIG["results_dir"]))
    return base / "web" / session_id


def _save_web_ticker_run(
    session_id: str,
    ticker: str,
    analysis_date: str,
    sections: dict,
    messages: list,
) -> Path:
    """
    Persist all report sections and activity log for one ticker/session to disk.

    Directory layout:
      results/web/{session_id}/{ticker}/{date}/reports/{section}.md
      results/web/{session_id}/{ticker}/{date}/full_report.md
      results/web/{session_id}/{ticker}/{date}/message.log
    """
    ticker_dir = _web_results_dir(session_id) / ticker / analysis_date
    report_dir = ticker_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    # Individual section files
    for section, content in sections.items():
        if content:
            (report_dir / f"{section}.md").write_text(content, encoding="utf-8")

    # Combined full_report.md
    parts = [f"# {ticker} — Full Analysis Report\n**Date:** {analysis_date}\n\n---\n"]
    for key, heading in _SECTION_HEADINGS.items():
        content = sections.get(key, "")
        if content:
            parts.append(f"{heading}\n\n{content}\n\n---\n")
    (ticker_dir / "full_report.md").write_text("\n".join(parts), encoding="utf-8")

    # Activity message log
    if messages:
        with open(ticker_dir / "message.log", "w", encoding="utf-8") as f:
            for msg in messages:
                ts      = msg.get("timestamp", "")
                mt      = msg.get("type", "")
                content = msg.get("content", "").replace("\n", " ")
                f.write(f"{ts} [{mt}] {content}\n")

    return ticker_dir


def _save_web_portfolio(
    session_id: str,
    analysis_date: str,
    portfolio_report: str,
    tickers: list,
) -> Path:
    """
    Persist the MVO portfolio report and a combined multi-ticker report.

    Directory layout:
      results/web/{session_id}/_portfolio/{date}/portfolio_mvo.md
      results/web/{session_id}/_portfolio/{date}/full_portfolio_report.md
    """
    portfolio_dir = _web_results_dir(session_id) / "_portfolio" / analysis_date
    portfolio_dir.mkdir(parents=True, exist_ok=True)

    (portfolio_dir / "portfolio_mvo.md").write_text(portfolio_report, encoding="utf-8")

    # Build combined report: MVO first, then each ticker's full_report.md
    combined = [portfolio_report, "\n\n---\n\n# Individual Token Reports\n"]
    for ticker in tickers:
        path = _web_results_dir(session_id) / ticker / analysis_date / "full_report.md"
        if path.exists():
            combined.append(path.read_text(encoding="utf-8"))
    (portfolio_dir / "full_portfolio_report.md").write_text(
        "\n\n".join(combined), encoding="utf-8"
    )

    return portfolio_dir


# Security utility for safe logging
def safe_log_config(config: Dict) -> Dict:
    """Create a safe version of config for logging without sensitive information"""
    safe_config = config.copy()
    
    # Hide all potential sensitive keys
    sensitive_keys = ['api_key', 'API_KEY', 'openai_api_key', 'anthropic_api_key', 'google_api_key', 'secret_key', 'password']
    for sensitive_key in sensitive_keys:
        if sensitive_key in safe_config:
            safe_config[sensitive_key] = '***HIDDEN***'
    return safe_config

def safe_error_traceback(traceback_str: str) -> str:
    """Create a safe version of traceback without sensitive information"""
    
    # Replace potential API keys in traceback
    # Pattern for common API key formats
    patterns = [
        r'sk-proj-[a-zA-Z0-9_-]+',  # OpenAI project keys
        r'sk-[a-zA-Z0-9_-]{20,}',   # OpenAI keys
        r'AIza[a-zA-Z0-9_-]{35}',   # Google API keys
        r'ya29\.[a-zA-Z0-9_-]+',    # Google OAuth tokens
        r'xoxb-[a-zA-Z0-9-]+',      # Slack bot tokens
        r'[a-zA-Z0-9_-]{32,}',      # Generic long strings that might be keys
    ]
    
    safe_traceback = traceback_str
    for pattern in patterns:
        safe_traceback = re.sub(pattern, '***HIDDEN_API_KEY***', safe_traceback)
    
    return safe_traceback

def is_production() -> bool:
    """Check if running in production environment"""
    return os.environ.get('ENVIRONMENT', '').lower() == 'production'

# Allowlist of permitted backend URLs per provider — prevents SSRF attacks
ALLOWED_BACKEND_URLS = {
    'openai': 'https://api.openai.com/v1',
    'anthropic': 'https://api.anthropic.com/',
    'google': 'https://generativelanguage.googleapis.com/v1',
    'qwen': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
    'kimi': 'https://api.moonshot.cn/v1',
    'minimax': 'https://api.minimax.chat/v1',
}

app = Flask(__name__)
# Use environment variable for SECRET_KEY in production, fallback for development
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global storage for analysis sessions
analysis_sessions = {}

class WebMessageBuffer:
    def __init__(self, session_id):
        self.session_id = session_id
        self.messages = []
        self.tool_calls = []
        self.agent_status = {
            "Market Analyst (5m)": "pending",
            "Market Analyst (4h)": "pending",
            "Social Analyst": "pending",
            "News Analyst": "pending",
            "Fundamentals Analyst": "pending",
            "Bull Researcher": "pending",
            "Bear Researcher": "pending",
            "CTA Researcher": "pending",
            "Contrarian Researcher": "pending",
            "Retail Researcher": "pending",
            "Research Manager": "pending",
            "Trader": "pending",
            "Risky Analyst": "pending",
            "Neutral Analyst": "pending",
            "Safe Analyst": "pending",
            "Portfolio Manager": "pending",
        }
        self.report_sections = {
            "market_report": None,
            "sentiment_report": None,
            "news_report": None,
            "market_4h_report": None,
            "fundamentals_report": None,
            "investment_plan": None,
            "trader_investment_plan": None,
            "final_trade_decision": None,
        }
        self.current_step = "waiting"
        self.progress = 0

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        message = {"timestamp": timestamp, "type": message_type, "content": content}
        self.messages.append(message)
        socketio.emit('new_message', message, room=self.session_id)

    def update_agent_status(self, agent, status):
        self.agent_status[agent] = status
        socketio.emit('agent_status_update', {
            'agent': agent, 
            'status': status
        }, room=self.session_id)

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            socketio.emit('report_update', {
                'section': section_name,
                'content': content
            }, room=self.session_id)

    def update_progress(self, progress, step):
        self.progress = progress
        self.current_step = step
        socketio.emit('progress_update', {
            'progress': progress,
            'step': step
        }, room=self.session_id)

def cleanup_session_collections(session_id):
    """Clean up ChromaDB collections for a specific session to prevent memory leaks"""
    try:
        import chromadb
        from chromadb.config import Settings
        
        client = chromadb.Client(Settings(allow_reset=True))
        collections = client.list_collections()
        
        # Remove collections that belong to this session
        for collection in collections:
            if collection.name.endswith(f"_{session_id}"):
                try:
                    client.delete_collection(name=collection.name)
                    print(f"[DEBUG] Cleaned up collection: {collection.name}")
                except Exception as e:
                    print(f"[WARNING] Failed to cleanup collection {collection.name}: {e}")
    except Exception as e:
        print(f"[WARNING] Failed to cleanup collections for session {session_id}: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analysis')
def analysis_page():
    return render_template('analysis.html')

@app.route('/health')
def health_check():
    """Health check endpoint for Google Cloud Run"""
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.datetime.now().isoformat(),
        'service': 'TradingAgents Crypto'
    })

@app.route('/api/start_analysis', methods=['POST'])
def start_analysis():
    data = request.json

    # Validate backend_url against allowlist to prevent SSRF
    llm_provider = data.get('llm_provider', '').lower()
    backend_url = data.get('backend_url', '')
    allowed_url = ALLOWED_BACKEND_URLS.get(llm_provider)
    if not allowed_url or backend_url != allowed_url:
        return jsonify({'error': 'Invalid backend_url for the selected provider'}), 400

    # Generate session_id server-side — never trust client-supplied IDs
    session_id = secrets.token_urlsafe(16)

    # Store analysis configuration
    analysis_sessions[session_id] = {
        'config': data,
        'buffer': WebMessageBuffer(session_id),
        'status': 'running'
    }

    # Start analysis in background
    thread = threading.Thread(
        target=run_analysis_background,
        args=(session_id, data)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'session_id': session_id, 'status': 'started'})

def run_analysis_background(session_id: str, config: Dict):
    """Run the trading analysis in background thread"""
    import traceback
    try:
        if not is_production():
            print(f"[DEBUG] Starting analysis for session {session_id}")
            print(f"[DEBUG] Config: {safe_log_config(config)}")
            print(f"[DEBUG] Selected analysts: {config['analysts']}")
        
        import re as _re
        buffer = analysis_sessions[session_id]['buffer']

        # Parse comma/space-separated tickers
        raw_ticker = config.get('ticker', 'BTC')
        tickers = [s.upper() for s in _re.split(r'[,\s]+', raw_ticker.strip()) if s]
        if not tickers:
            tickers = ['BTC']

        # Build config
        updated_config = DEFAULT_CONFIG.copy()
        updated_config.update({
            'llm_provider': config['llm_provider'],
            'backend_url': config['backend_url'],
            'api_key': config.get('api_key', ''),
            'quick_think_llm': config['shallow_thinker'],
            'deep_think_llm': config['deep_thinker'],
            'max_debate_rounds': config['research_depth'],
            'max_risk_discuss_rounds': config['research_depth'],
            'session_id': session_id
        })

        # Clear API key from session storage
        if session_id in analysis_sessions:
            analysis_sessions[session_id]['config'].pop('api_key', None)

        if not is_production():
            print(f"[DEBUG] LLM provider: {updated_config['llm_provider']}")
            print(f"[DEBUG] Tickers: {tickers}")

        buffer.add_message("System", f"Initializing analysis for {', '.join(tickers)}...")

        # Graph is ticker-agnostic — initialise once
        graph = TradingAgentsGraph(
            selected_analysts=config['analysts'],
            debug=False,
            config=updated_config
        )
        buffer.add_message("System", "Graph initialized successfully")

        args = graph.propagator.get_graph_args()
        total_steps = len(config['analysts']) * 2 + 5
        symbol_results = {}

        for ticker_idx, ticker in enumerate(tickers):
            ticker_base_progress = int(ticker_idx * 90 / len(tickers))
            ticker_progress_range = int(90 / len(tickers))

            buffer.add_message("System", f"[{ticker_idx+1}/{len(tickers)}] Starting analysis for {ticker} on {config['analysis_date']}")
            buffer.update_progress(ticker_base_progress + 5, f"Analysing {ticker}...")

            socketio.emit('analysis_info_update', {
                'ticker': ticker,
                'analysis_date': config['analysis_date']
            }, room=session_id)

            init_state = graph.propagator.create_initial_state(ticker, config['analysis_date'])

            step_count = 0
            for chunk in graph.graph.stream(init_state, **args):
                step_count += 1
                stream_pct = min(1.0, step_count / total_steps)
                progress = ticker_base_progress + int(stream_pct * ticker_progress_range)

                if len(chunk.get("messages", [])) > 0:
                    last_message = chunk["messages"][-1]
                    if hasattr(last_message, "content"):
                        content = str(last_message.content)
                        if len(content) > 500:
                            content = content[:500] + "..."
                        buffer.add_message("Analysis", content)

                    if "market_report" in chunk and chunk["market_report"]:
                        buffer.update_report_section("market_report", chunk["market_report"])
                        buffer.update_agent_status("Market Analyst (5m)", "completed")
                        buffer.update_progress(progress, f"[{ticker}] Market 5m analysis completed")

                    if "market_4h_report" in chunk and chunk["market_4h_report"]:
                        buffer.update_report_section("market_4h_report", chunk["market_4h_report"])
                        buffer.update_agent_status("Market Analyst (4h)", "completed")
                        buffer.update_progress(progress, f"[{ticker}] Market 4h analysis completed")

                    if "sentiment_report" in chunk and chunk["sentiment_report"]:
                        buffer.update_report_section("sentiment_report", chunk["sentiment_report"])
                        buffer.update_agent_status("Social Analyst", "completed")
                        buffer.update_progress(progress, f"[{ticker}] Social sentiment completed")

                    if "news_report" in chunk and chunk["news_report"]:
                        buffer.update_report_section("news_report", chunk["news_report"])
                        buffer.update_agent_status("News Analyst", "completed")
                        buffer.update_progress(progress, f"[{ticker}] News analysis completed")

                    if "fundamentals_report" in chunk and chunk["fundamentals_report"]:
                        buffer.update_report_section("fundamentals_report", chunk["fundamentals_report"])
                        buffer.update_agent_status("Fundamentals Analyst", "completed")
                        buffer.update_progress(progress, f"[{ticker}] Fundamentals completed")

                    if "investment_debate_state" in chunk and chunk["investment_debate_state"]:
                        debate_state = chunk["investment_debate_state"]
                        if "bull_history" in debate_state and debate_state["bull_history"]:
                            buffer.update_agent_status("Bull Researcher", "in_progress")
                            latest_bull = debate_state["bull_history"].split("\n")[-1]
                            if latest_bull.strip():
                                buffer.add_message("Bull Researcher", f"Bull Analysis: {latest_bull}")
                        if "bear_history" in debate_state and debate_state["bear_history"]:
                            buffer.update_agent_status("Bear Researcher", "in_progress")
                            latest_bear = debate_state["bear_history"].split("\n")[-1]
                            if latest_bear.strip():
                                buffer.add_message("Bear Researcher", f"Bear Analysis: {latest_bear}")
                        if "judge_decision" in debate_state and debate_state["judge_decision"]:
                            buffer.update_report_section("investment_plan", debate_state["judge_decision"])
                            buffer.update_agent_status("Bull Researcher", "completed")
                            buffer.update_agent_status("Bear Researcher", "completed")
                            buffer.update_agent_status("Research Manager", "completed")
                            buffer.update_progress(progress, f"[{ticker}] Research team decision completed")

                    if "trader_investment_plan" in chunk and chunk["trader_investment_plan"]:
                        buffer.update_report_section("trader_investment_plan", chunk["trader_investment_plan"])
                        buffer.update_agent_status("Trader", "completed")
                        buffer.update_progress(progress, f"[{ticker}] Trading plan completed")
                        if ticker not in symbol_results:
                            symbol_results[ticker] = {}
                        symbol_results[ticker]["trader_investment_plan"] = chunk["trader_investment_plan"]

                    if "final_trade_decision" in chunk and chunk["final_trade_decision"]:
                        buffer.update_report_section("final_trade_decision", chunk["final_trade_decision"])
                        buffer.update_agent_status("Portfolio Manager", "completed")
                        if ticker not in symbol_results:
                            symbol_results[ticker] = {}
                        symbol_results[ticker]["final_trade_decision"] = chunk["final_trade_decision"]
                        buffer.update_progress(
                            ticker_base_progress + ticker_progress_range,
                            f"[{ticker}] Analysis completed!"
                        )

            buffer.add_message("System", f"[{ticker}] Analysis finished.")

            # Snapshot all non-null sections for this ticker and store persistently
            ticker_sections = {k: v for k, v in buffer.report_sections.items() if v}
            if 'per_ticker_reports' not in analysis_sessions[session_id]:
                analysis_sessions[session_id]['per_ticker_reports'] = {}
            analysis_sessions[session_id]['per_ticker_reports'][ticker] = ticker_sections

            # Save reports + message log to disk
            try:
                saved_dir = _save_web_ticker_run(
                    session_id, ticker, config['analysis_date'],
                    ticker_sections, buffer.messages,
                )
                buffer.add_message("System", f"[{ticker}] Reports saved → {saved_dir}")
            except Exception as save_err:
                print(f"[WARNING] Could not save web reports for {ticker}: {save_err}")

            # Emit permanent per-ticker snapshot to the frontend
            socketio.emit('ticker_complete', {
                'ticker': ticker,
                'sections': ticker_sections,
            }, room=session_id)

        # Portfolio MVO — only when multiple tickers analysed
        if len(tickers) > 1 and len(symbol_results) > 1:
            from tradingagents.agents.portfolio.mvo import run_portfolio_mvo
            buffer.add_message("System", "Running portfolio optimisation (MVO)...")
            buffer.update_progress(92, "Portfolio optimisation...")
            portfolio_report = run_portfolio_mvo(symbol_results, config['analysis_date'])
            analysis_sessions[session_id]['portfolio_report'] = portfolio_report
            socketio.emit('portfolio_update', {'report': portfolio_report}, room=session_id)
            buffer.add_message("Portfolio", portfolio_report)

            # Save portfolio + combined report to disk
            try:
                port_dir = _save_web_portfolio(
                    session_id, config['analysis_date'], portfolio_report, tickers
                )
                buffer.add_message("System", f"Portfolio report saved → {port_dir}")
            except Exception as save_err:
                print(f"[WARNING] Could not save portfolio report: {save_err}")

            buffer.update_progress(100, "Portfolio optimisation complete!")
        else:
            buffer.update_progress(100, "Analysis completed successfully!")

        analysis_sessions[session_id]['status'] = 'completed'

        # Clean up ChromaDB collections for this session after completion
        cleanup_session_collections(session_id)
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        error_message = f"Analysis failed: {type(e).__name__}: {str(e)}"
        print(f"[ERROR] {error_message}")
        print(f"[ERROR] Traceback:\n{safe_error_traceback(error_traceback)}")
        
        buffer.add_message("Error", error_message)
        buffer.update_progress(0, "Analysis failed")
        analysis_sessions[session_id]['status'] = 'failed'
        
        # Clean up ChromaDB collections even if analysis failed
        cleanup_session_collections(session_id)

@socketio.on('connect')
def handle_connect():
    emit('connected', {'status': 'Connected to TradingAgents'})

@socketio.on('join_session')
def handle_join_session(data):
    session_id = data['session_id']
    # Join the room for this session
    from flask_socketio import join_room
    join_room(session_id)
    
    # Send current state if session exists
    if session_id in analysis_sessions:
        buffer = analysis_sessions[session_id]['buffer']
        emit('session_state', {
            'messages': buffer.messages,
            'agent_status': buffer.agent_status,
            'report_sections': buffer.report_sections,
            'progress': buffer.progress,
            'current_step': buffer.current_step,
            'per_ticker_reports': analysis_sessions[session_id].get('per_ticker_reports', {}),
            'portfolio_report': analysis_sessions[session_id].get('portfolio_report'),
        })

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    Path('templates').mkdir(exist_ok=True)
    Path('static').mkdir(exist_ok=True)
    
    # Use port from environment variable for Cloud Run compatibility
    port = int(os.environ.get('PORT', 8080))
    
    socketio.run(app, debug=False, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True) 