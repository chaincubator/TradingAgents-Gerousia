"""
TradingAgents Graph - Evo Variant

This module provides an evo-enabled version of TradingAgentsGraph that uses
external prompts from the agents_evo system instead of hardcoded prompts.

Key Features:
- Load prompts from external files
- Select prompt variants via configuration
- A/B testing support for prompt variants
- Backward compatible with original system

Usage:
    from tradingagents.graph.trading_graph_evo import TradingAgentsGraphEvo
    
    config = DEFAULT_CONFIG.copy()
    config["evo_enabled"] = True
    config["evo_variants"] = {
        "market_analyst": {"bias": "technical", "variant": "v1"},
        "bull_researcher": {"bias": "aggressive", "variant": "v1"},
    }
    
    ta = TradingAgentsGraphEvo(config=config)
"""

import os
from typing import Dict, Any, Optional

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.agents.utils.agent_utils import Toolkit
from tradingagents.dataflows.interface import set_config

# Import evo components
from tradingagents.agents_evo import load_agent_prompt
from tradingagents.agents_evo.analysts import (
    create_market_analyst_evo,
    create_market_4h_analyst_evo,
)
from tradingagents.agents_evo.researchers import (
    create_bull_researcher_evo,
    create_bear_researcher_evo,
)
from tradingagents.agents_evo.trader import (
    create_trader_evo,
    create_risky_debator_evo,
    create_safe_debator_evo,
    create_neutral_debator_evo,
    create_risk_manager_evo,
)

# Import original components for fallback
from tradingagents.graph.trading_graph import (
    _QwenCompletionsProxy,
    _QwenAsyncCompletionsProxy,
    _make_qwen_llm,
)
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.reflection import Reflector
from tradingagents.graph.signal_processing import SignalProcessor


class TradingAgentsGraphEvo:
    """
    Evo-enabled version of TradingAgentsGraph.
    
    Uses external prompts from the agents_evo system, enabling:
    - Multiple prompt variants per agent
    - A/B testing of different prompt strategies
    - Easy prompt iteration without code changes
    - Competing agent biases within functional areas
    """
    
    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
    ):
        """
        Initialize the evo-enabled trading agents graph.
        
        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            
        Config Options for Evo:
            evo_enabled: bool - Enable evo system (default: True)
            evo_variants: dict - Prompt variant selections per agent
                Example: {
                    "market_analyst": {"bias": "technical", "variant": "v1"},
                    "bull_researcher": {"bias": "aggressive", "variant": "v1"},
                    "bear_researcher": {"bias": "conservative", "variant": "v1"},
                    "trader": {"bias": "momentum", "variant": "v1"},
                }
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG.copy()
        
        # Evo configuration
        self.evo_enabled = self.config.get("evo_enabled", True)
        self.evo_variants = self.config.get("evo_variants", {})
        
        if not self.evo_enabled:
            # Fall back to original TradingAgentsGraph
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            self._original_graph = TradingAgentsGraph(
                selected_analysts=selected_analysts,
                debug=debug,
                config=config
            )
            # Proxy all methods to original
            self.__dict__ = self._original_graph.__dict__
            return
        
        # Update the interface's config
        set_config(self.config)
        
        # Create necessary directories
        os.makedirs(
            os.path.join(self.config["project_dir"], "dataflows/data_cache"),
            exist_ok=True,
        )
        
        # Initialize LLMs
        self._init_llms()
        
        self.toolkit = Toolkit(config=self.config)
        
        # Initialize memories
        self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
        self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
        self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", self.config)
        
        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config.get("max_debate_rounds", 1),
            max_risk_discuss_rounds=self.config.get("max_risk_discuss_rounds", 1),
        )
        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)
        
        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}
        
        # Build the graph
        self.graph = self._setup_evo_graph(selected_analysts)
    
    def _init_llms(self):
        """Initialize language models based on provider configuration."""
        provider = self.config["llm_provider"].lower()
        
        if provider in ["openai", "ollama", "openrouter"]:
            self.deep_thinking_llm = ChatOpenAI(
                model=self.config["deep_think_llm"],
                base_url=self.config["backend_url"],
                api_key=self.config["api_key"]
            )
            self.quick_thinking_llm = ChatOpenAI(
                model=self.config["quick_think_llm"],
                base_url=self.config["backend_url"],
                api_key=self.config["api_key"]
            )
        elif provider == "anthropic":
            self.deep_thinking_llm = ChatAnthropic(
                model=self.config["deep_think_llm"],
                base_url=self.config["backend_url"],
                api_key=self.config["api_key"]
            )
            self.quick_thinking_llm = ChatAnthropic(
                model=self.config["quick_think_llm"],
                base_url=self.config["backend_url"],
                api_key=self.config["api_key"]
            )
        elif provider == "google":
            self.deep_thinking_llm = ChatGoogleGenerativeAI(
                model=self.config["deep_think_llm"],
                google_api_key=self.config["api_key"]
            )
            self.quick_thinking_llm = ChatGoogleGenerativeAI(
                model=self.config["quick_think_llm"],
                google_api_key=self.config["api_key"]
            )
        elif provider == "qwen":
            self.deep_thinking_llm = _make_qwen_llm(
                self.config["deep_think_llm"],
                self.config["backend_url"],
                self.config["api_key"],
            )
            self.quick_thinking_llm = _make_qwen_llm(
                self.config["quick_think_llm"],
                self.config["backend_url"],
                self.config["api_key"],
            )
        elif provider in ["kimi", "minimax"]:
            self.deep_thinking_llm = ChatOpenAI(
                model=self.config["deep_think_llm"],
                base_url=self.config["backend_url"],
                api_key=self.config["api_key"]
            )
            self.quick_thinking_llm = ChatOpenAI(
                model=self.config["quick_think_llm"],
                base_url=self.config["backend_url"],
                api_key=self.config["api_key"]
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.config['llm_provider']}")
    
    def _get_evo_variant(self, agent_name: str) -> Dict[str, str]:
        """
        Get the prompt variant configuration for an agent.
        
        Args:
            agent_name: Name of the agent (e.g., 'market_analyst')
            
        Returns:
            Dict with 'bias' and 'variant' keys
        """
        # Check user-provided config first
        if agent_name in self.evo_variants:
            return self.evo_variants[agent_name]
        
        # Default variants
        defaults = {
            'market_analyst': {'bias': 'default', 'variant': 'v1'},
            'bull_researcher': {'bias': 'default', 'variant': 'v1'},
            'bear_researcher': {'bias': 'default', 'variant': 'v1'},
            'trader': {'bias': 'default', 'variant': 'v1'},
            'risky_debator': {'bias': 'default', 'variant': 'v1'},
            'safe_debator': {'bias': 'default', 'variant': 'v1'},
            'neutral_debator': {'bias': 'default', 'variant': 'v1'},
            'risk_manager': {'bias': 'default', 'variant': 'v1'},
        }
        
        return defaults.get(agent_name, {'bias': 'default', 'variant': 'v1'})
    
    def _setup_evo_graph(self, selected_analysts):
        """
        Set up the agent workflow graph using evo agents.
        
        Args:
            selected_analysts: List of analyst types to include
            
        Returns:
            Compiled LangGraph workflow
        """
        from langgraph.graph import END, START, StateGraph
        from tradingagents.agents.utils.agent_states import AgentState
        from tradingagents.agents.utils.agent_utils import create_msg_delete
        
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")
        
        # Create analyst nodes using evo variants
        analyst_nodes = {}
        delete_nodes = {}
        
        # Note: For now, we use the original analyst creators for most analysts
        # since evo wrappers are primarily for market analyst
        # This can be extended as more evo wrappers are created
        from tradingagents.agents import (
            create_market_analyst,
            create_market_4h_analyst,
            create_social_media_analyst,
            create_news_analyst,
            create_fred_analyst,
            create_polymarket_analyst,
            create_fundamentals_analyst,
            create_cta_researcher,
            create_contrarian_researcher,
            create_retail_researcher,
            create_research_manager,
            create_trader,
            create_risky_debator,
            create_neutral_debator,
            create_safe_debator,
            create_risk_manager,
        )
        
        # Use evo market analyst if configured
        if "market" in selected_analysts:
            market_variant = self._get_evo_variant('market_analyst')
            analyst_nodes["market"] = create_market_analyst_evo(
                self.quick_thinking_llm,
                self.toolkit,
                bias=market_variant['bias'],
                variant=market_variant['variant']
            )
            delete_nodes["market"] = create_msg_delete()
        
        if "market_4h" in selected_analysts:
            market_variant = self._get_evo_variant('market_analyst')
            analyst_nodes["market_4h"] = create_market_4h_analyst_evo(
                self.quick_thinking_llm,
                self.toolkit,
                bias=market_variant['bias'],
                variant=market_variant['variant']
            )
            delete_nodes["market_4h"] = create_msg_delete()
        
        # Use original creators for other analysts (can be migrated to evo later)
        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(
                self.quick_thinking_llm, self.toolkit
            )
            delete_nodes["social"] = create_msg_delete()
        
        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.quick_thinking_llm, self.toolkit
            )
            delete_nodes["news"] = create_msg_delete()
        
        if "fred" in selected_analysts:
            analyst_nodes["fred"] = create_fred_analyst(
                self.quick_thinking_llm, self.toolkit
            )
            delete_nodes["fred"] = create_msg_delete()
        
        if "polymarket" in selected_analysts:
            analyst_nodes["polymarket"] = create_polymarket_analyst(
                self.quick_thinking_llm, self.toolkit
            )
            delete_nodes["polymarket"] = create_msg_delete()
        
        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.quick_thinking_llm, self.toolkit
            )
            delete_nodes["fundamentals"] = create_msg_delete()
        
        # Create researcher and manager nodes using evo variants
        bull_variant = self._get_evo_variant('bull_researcher')
        bear_variant = self._get_evo_variant('bear_researcher')
        trader_variant = self._get_evo_variant('trader')
        
        bull_researcher_node = create_bull_researcher_evo(
            self.quick_thinking_llm,
            self.bull_memory,
            bias=bull_variant['bias'],
            variant=bull_variant['variant']
        )
        bear_researcher_node = create_bear_researcher_evo(
            self.quick_thinking_llm,
            self.bear_memory,
            bias=bear_variant['bias'],
            variant=bear_variant['variant']
        )
        cta_researcher_node = create_cta_researcher(self.quick_thinking_llm)
        contrarian_researcher_node = create_contrarian_researcher(self.quick_thinking_llm)
        retail_researcher_node = create_retail_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )
        trader_node = create_trader_evo(
            self.quick_thinking_llm,
            self.trader_memory,
            bias=trader_variant['bias'],
            variant=trader_variant['variant']
        )
        
        # Create risk analysis nodes using evo variants
        risky_variant = self._get_evo_variant('risky_debator')
        safe_variant = self._get_evo_variant('safe_debator')
        neutral_variant = self._get_evo_variant('neutral_debator')
        risk_manager_variant = self._get_evo_variant('risk_manager')
        
        risky_analyst = create_risky_debator_evo(
            self.quick_thinking_llm,
            bias=risky_variant['bias'],
            variant=risky_variant['variant']
        )
        neutral_analyst = create_neutral_debator_evo(
            self.quick_thinking_llm,
            bias=neutral_variant['bias'],
            variant=neutral_variant['variant']
        )
        safe_analyst = create_safe_debator_evo(
            self.quick_thinking_llm,
            bias=safe_variant['bias'],
            variant=safe_variant['variant']
        )
        risk_manager_node = create_risk_manager_evo(
            self.deep_thinking_llm,
            self.risk_manager_memory,
            bias=risk_manager_variant['bias'],
            variant=risk_manager_variant['variant']
        )
        
        # Human-readable analyst display names
        _analyst_display = {
            "market": "Market",
            "market_4h": "Market 4H",
            "fred": "FRED Macro",
            "polymarket": "Polymarket",
            "social": "Social",
            "news": "News",
            "fundamentals": "Fundamentals",
        }
        
        def _display(t):
            return _analyst_display.get(t, t.replace("_", " ").capitalize())
        
        # Create workflow
        workflow = StateGraph(AgentState)
        
        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{_display(analyst_type)} Analyst", node)
            workflow.add_node(
                f"Msg Clear {_display(analyst_type)}", delete_nodes[analyst_type]
            )
        
        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("CTA Researcher", cta_researcher_node)
        workflow.add_node("Contrarian Researcher", contrarian_researcher_node)
        workflow.add_node("Retail Researcher", retail_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Risky Analyst", risky_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Safe Analyst", safe_analyst)
        workflow.add_node("Risk Judge", risk_manager_node)
        
        # Define edges
        # Start with the first analyst
        first_analyst = selected_analysts[0]
        workflow.add_edge(START, f"{_display(first_analyst)} Analyst")
        
        # Connect analysts in sequence (simplified - full implementation would
        # mirror the original setup.py conditional logic)
        for i, analyst_type in enumerate(selected_analysts):
            current_analyst = f"{_display(analyst_type)} Analyst"
            current_clear = f"Msg Clear {_display(analyst_type)}"
            
            # Connect to next analyst or to Bull Researcher if last
            if i < len(selected_analysts) - 1:
                next_analyst = f"{_display(selected_analysts[i+1])} Analyst"
                workflow.add_edge(current_analyst, current_clear)
                workflow.add_edge(current_clear, next_analyst)
            else:
                workflow.add_edge(current_analyst, "Bull Researcher")
        
        # Add researcher debate flow
        workflow.add_edge("Bull Researcher", "Bear Researcher")
        workflow.add_edge("Bear Researcher", "Bull Researcher")
        
        # Add research manager after debate rounds
        workflow.add_edge("Bull Researcher", "Research Manager")
        
        # Add trader
        workflow.add_edge("Research Manager", "Trader")
        
        # Add risk debate flow
        workflow.add_edge("Trader", "Risky Analyst")
        workflow.add_edge("Risky Analyst", "Neutral Analyst")
        workflow.add_edge("Neutral Analyst", "Safe Analyst")
        workflow.add_edge("Safe Analyst", "Risk Judge")
        
        # End at Risk Judge
        workflow.add_edge("Risk Judge", END)
        
        # Compile the graph
        return workflow.compile()
    
    def propagate(self, company_name, trade_date):
        """
        Run the trading agents graph for a company on a specific date.
        
        Args:
            company_name: Company/asset symbol
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Tuple of (final_state, processed_signal)
        """
        if not self.evo_enabled:
            return self._original_graph.propagate(company_name, trade_date)
        
        from tradingagents.dataflows.analysis_cache import AnalysisCache
        from tradingagents.agents.portfolio.mvo import _parse_tp_sl, _extract_signal
        
        self.ticker = company_name
        cache_dir = self.config.get("data_cache_dir", "./data")
        binance_cache = os.path.join(cache_dir, "binance_cache")
        
        # Load persistent analysis cache
        cache = AnalysisCache(company_name, cache_dir)
        
        # Score any past recommendations whose validity has elapsed
        n_scored = cache.score_pending(str(trade_date), binance_cache)
        if n_scored:
            print(f"[AnalysisCache] Scored {n_scored} past recommendation(s) for {company_name}")
        
        past_context = cache.get_past_context()
        
        # Initialize state with iterative context
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, past_context
        )
        
        if self.debug:
            # Debug mode with tracing
            trace = []
            for chunk in self.graph.stream(init_agent_state):
                if len(chunk.get("messages", [])) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            
            final_state = trace[-1]
        else:
            # Standard mode
            final_state = self.graph.invoke(init_agent_state)
        
        # Store current state for reflection
        self.curr_state = final_state
        
        # Save new recommendation and reasoning to cache
        try:
            trader_plan = final_state.get("trader_investment_plan", "")
            final_dec = final_state.get("final_trade_decision", "")
            tp, sl, validity = _parse_tp_sl(trader_plan)
            signal = _extract_signal(final_dec)
            
            # Get entry price from the latest Binance 5m candle
            entry_price = None
            try:
                from tradingagents.dataflows.binance_utils import fetch_klines
                kdf = fetch_klines(company_name, str(trade_date), str(trade_date), binance_cache)
                if kdf is not None and not kdf.empty:
                    entry_price = float(kdf["close"].iloc[-1])
            except Exception:
                pass
            
            cache.record_recommendation(
                analysis_date=str(trade_date),
                signal=signal,
                take_profit=tp,
                stop_loss=sl,
                validity=validity,
                entry_price=entry_price,
                investment_plan=final_state.get("investment_plan", ""),
                final_decision=final_dec,
            )
            cache.update_from_final_state(final_state, str(trade_date))
            cache.save()
        except Exception as e:
            print(f"[AnalysisCache] Warning: could not save cache for {company_name}: {e}")
        
        # Log state
        self._log_state(trade_date, final_state)
        
        # Return decision and processed signal
        return final_state, self.signal_processor.process_signal(final_state["final_trade_decision"])
    
    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        import json
        
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "judge_decision": final_state["investment_debate_state"]["judge_decision"],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }
        
        # Save to file
        from pathlib import Path
        safe_ticker = re.sub(r'[^A-Za-z0-9_-]', '_', str(self.ticker))
        directory = Path(f"eval_results/{safe_ticker}/TradingAgentsStrategy_logs/")
        directory.mkdir(parents=True, exist_ok=True)
        
        with open(
            f"eval_results/{safe_ticker}/TradingAgentsStrategy_logs/full_states_log_{trade_date}.json",
            "w",
        ) as f:
            json.dump(self.log_states_dict, f, indent=4)
    
    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        if not self.evo_enabled:
            return self._original_graph.reflect_and_remember(returns_losses)
        
        self.reflector.reflect_bull_researcher(
            self.curr_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            self.curr_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            self.curr_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            self.curr_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_risk_manager(
            self.curr_state, returns_losses, self.risk_manager_memory
        )
    
    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
