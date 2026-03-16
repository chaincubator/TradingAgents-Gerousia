from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import datetime
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
import uuid
import os
import secrets

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from cli.models import AnalystType

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Global storage for analysis sessions
analysis_sessions = {}

class SimpleMessageBuffer:
    def __init__(self, session_id):
        self.session_id = session_id
        self.messages = []
        self.agent_status = {
            "Market Analyst": "pending",
            "Social Analyst": "pending", 
            "News Analyst": "pending",
            "Fundamentals Analyst": "pending",
            "Bull Researcher": "pending",
            "Bear Researcher": "pending",
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
            "fundamentals_report": None,
            "investment_plan": None,
            "trader_investment_plan": None,
            "final_trade_decision": None,
        }
        self.current_step = "waiting"
        self.progress = 0
        self.status = "pending"

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        message = {"timestamp": timestamp, "type": message_type, "content": content}
        self.messages.append(message)

    def update_agent_status(self, agent, status):
        self.agent_status[agent] = status

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content

    def update_progress(self, progress, step):
        self.progress = progress
        self.current_step = step

@app.route('/')
def index():
    return render_template('simple_index.html')

@app.route('/analysis/<session_id>')
def analysis_page(session_id):
    if session_id not in analysis_sessions:
        return redirect(url_for('index'))
    return render_template('simple_analysis.html', session_id=session_id)

@app.route('/api/start_analysis', methods=['POST'])
def start_analysis():
    data = request.json
    session_id = str(uuid.uuid4())
    
    # Store analysis configuration
    analysis_sessions[session_id] = {
        'config': data,
        'buffer': SimpleMessageBuffer(session_id),
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

@app.route('/api/status/<session_id>')
def get_status(session_id):
    if session_id not in analysis_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    buffer = analysis_sessions[session_id]['buffer']
    return jsonify({
        'messages': buffer.messages[-10:],  # Last 10 messages
        'agent_status': buffer.agent_status,
        'report_sections': buffer.report_sections,
        'progress': buffer.progress,
        'current_step': buffer.current_step,
        'status': analysis_sessions[session_id]['status']
    })

def run_analysis_background(session_id: str, config: Dict):
    """Run the trading analysis in background thread"""
    try:
        buffer = analysis_sessions[session_id]['buffer']
        
        # Initialize the graph
        graph = TradingAgentsGraph(DEFAULT_CONFIG)
        
        # Update configuration based on user selections
        updated_config = DEFAULT_CONFIG.copy()
        updated_config.update({
            'llm_provider': config['llm_provider'],
            'backend_url': config['backend_url'],
            'shallow_thinker': config['shallow_thinker'],
            'deep_thinker': config['deep_thinker'],
            'research_depth': config['research_depth']
        })
        
        # Create initial state
        init_state = graph.propagator.create_initial_state(
            config['ticker'], 
            config['analysis_date']
        )
        
        buffer.add_message("System", f"Starting analysis for {config['ticker']} on {config['analysis_date']}")
        buffer.update_progress(10, "Initializing analysis...")
        
        # Get graph args
        args = graph.propagator.get_graph_args()
        
        # Stream the analysis
        step_count = 0
        total_steps = len(config['analysts']) * 2 + 5
        
        for chunk in graph.graph.stream(init_state, **args):
            step_count += 1
            progress = min(90, (step_count / total_steps) * 80 + 10)
            
            if len(chunk.get("messages", [])) > 0:
                last_message = chunk["messages"][-1]
                
                if hasattr(last_message, "content"):
                    content = str(last_message.content)
                    if len(content) > 500:
                        content = content[:500] + "..."
                    buffer.add_message("Analysis", content)
                
                # Update agent statuses and reports (same logic as before)
                if "market_report" in chunk and chunk["market_report"]:
                    buffer.update_report_section("market_report", chunk["market_report"])
                    buffer.update_agent_status("Market Analyst", "completed")
                    buffer.update_progress(progress, "Market analysis completed")
                
                if "sentiment_report" in chunk and chunk["sentiment_report"]:
                    buffer.update_report_section("sentiment_report", chunk["sentiment_report"])
                    buffer.update_agent_status("Social Analyst", "completed")
                    buffer.update_progress(progress, "Social sentiment analysis completed")
                
                if "news_report" in chunk and chunk["news_report"]:
                    buffer.update_report_section("news_report", chunk["news_report"])
                    buffer.update_agent_status("News Analyst", "completed")
                    buffer.update_progress(progress, "News analysis completed")
                
                if "fundamentals_report" in chunk and chunk["fundamentals_report"]:
                    buffer.update_report_section("fundamentals_report", chunk["fundamentals_report"])
                    buffer.update_agent_status("Fundamentals Analyst", "completed")
                    buffer.update_progress(progress, "Fundamentals analysis completed")
                
                if "investment_debate_state" in chunk and chunk["investment_debate_state"]:
                    debate_state = chunk["investment_debate_state"]
                    
                    if "judge_decision" in debate_state and debate_state["judge_decision"]:
                        buffer.update_report_section("investment_plan", debate_state["judge_decision"])
                        buffer.update_agent_status("Research Manager", "completed")
                        buffer.update_progress(progress, "Research team decision completed")
                
                if "trader_investment_plan" in chunk and chunk["trader_investment_plan"]:
                    buffer.update_report_section("trader_investment_plan", chunk["trader_investment_plan"])
                    buffer.update_agent_status("Trader", "completed")
                    buffer.update_progress(progress, "Trading plan completed")
                
                if "final_trade_decision" in chunk and chunk["final_trade_decision"]:
                    buffer.update_report_section("final_trade_decision", chunk["final_trade_decision"])
                    buffer.update_agent_status("Portfolio Manager", "completed")
                    buffer.update_progress(100, "Analysis completed!")
        
        buffer.update_progress(100, "Analysis completed successfully!")
        analysis_sessions[session_id]['status'] = 'completed'
        
    except Exception as e:
        buffer.add_message("Error", f"Analysis failed: {str(e)}")
        buffer.update_progress(0, "Analysis failed")
        analysis_sessions[session_id]['status'] = 'failed'

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    Path('templates').mkdir(exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000) 