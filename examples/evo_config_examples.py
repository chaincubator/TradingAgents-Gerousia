#!/usr/bin/env python3
"""
Example configuration and usage of TradingAgents Graph Evo

This script demonstrates how to configure and use the evo-enabled
TradingAgentsGraph with external prompts and variant selection.
"""

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph_evo import TradingAgentsGraphEvo


# =============================================================================
# Configuration Example 1: Basic Evo Setup
# =============================================================================

def basic_evo_config():
    """
    Basic evo configuration with default variants.
    """
    config = DEFAULT_CONFIG.copy()
    
    # Enable evo system
    config["evo_enabled"] = True
    
    # Use default prompt variants for all agents
    # (no need to specify evo_variants for defaults)
    
    return config


# =============================================================================
# Configuration Example 2: Custom Prompt Variants
# =============================================================================

def custom_variants_config():
    """
    Configure specific prompt variants for each agent.
    """
    config = DEFAULT_CONFIG.copy()
    
    config["evo_enabled"] = True
    
    # Select specific prompt variants for each agent
    config["evo_variants"] = {
        # Technical analysis focused market analyst
        "market_analyst": {
            "bias": "technical",
            "variant": "v1"
        },
        # Aggressive bull researcher for strong conviction
        "bull_researcher": {
            "bias": "aggressive",
            "variant": "v1"
        },
        # Conservative bear researcher for risk awareness
        "bear_researcher": {
            "bias": "conservative",
            "variant": "v1"
        },
        # Momentum-focused trader
        "trader": {
            "bias": "momentum",
            "variant": "v1"
        },
        # Default variants for risk management
        "risky_debator": {
            "bias": "default",
            "variant": "v1"
        },
        "safe_debator": {
            "bias": "default",
            "variant": "v1"
        },
        "neutral_debator": {
            "bias": "default",
            "variant": "v1"
        },
        "risk_manager": {
            "bias": "default",
            "variant": "v1"
        },
    }
    
    return config


# =============================================================================
# Configuration Example 3: A/B Testing Setup
# =============================================================================

import random

def ab_testing_config():
    """
    Randomly select prompt variants for A/B testing.
    
    Run multiple analyses with different variants to see which performs better.
    """
    config = DEFAULT_CONFIG.copy()
    config["evo_enabled"] = True
    
    # Randomly select bull researcher variant
    bull_variants = ["default", "aggressive"]
    selected_bull = random.choice(bull_variants)
    
    # Randomly select bear researcher variant
    bear_variants = ["default", "conservative"]
    selected_bear = random.choice(bear_variants)
    
    config["evo_variants"] = {
        "bull_researcher": {
            "bias": selected_bull,
            "variant": "v1"
        },
        "bear_researcher": {
            "bias": selected_bear,
            "variant": "v1"
        },
    }
    
    print(f"A/B Test Config: Bull={selected_bull}, Bear={selected_bear}")
    
    return config


# =============================================================================
# Configuration Example 4: Aggressive Growth Strategy
# =============================================================================

def aggressive_growth_config():
    """
    Configuration for aggressive growth-focused analysis.
    
    Uses aggressive bull, standard bear, and momentum trader.
    """
    config = DEFAULT_CONFIG.copy()
    config["evo_enabled"] = True
    
    config["evo_variants"] = {
        # Standard market analysis
        "market_analyst": {
            "bias": "default",
            "variant": "v1"
        },
        # Strong bull case advocate
        "bull_researcher": {
            "bias": "aggressive",
            "variant": "v1"
        },
        # Standard bear for balance
        "bear_researcher": {
            "bias": "default",
            "variant": "v1"
        },
        # Momentum-focused trader
        "trader": {
            "bias": "momentum",
            "variant": "v1"
        },
    }
    
    # Increase debate rounds for thorough analysis
    config["max_debate_rounds"] = 3
    
    return config


# =============================================================================
# Configuration Example 5: Conservative Risk Management
# =============================================================================

def conservative_config():
    """
    Configuration for conservative, risk-aware analysis.
    
    Uses conservative bear and standard risk management.
    """
    config = DEFAULT_CONFIG.copy()
    config["evo_enabled"] = True
    
    config["evo_variants"] = {
        # Standard market analysis
        "market_analyst": {
            "bias": "default",
            "variant": "v1"
        },
        # Standard bull for balance
        "bull_researcher": {
            "bias": "default",
            "variant": "v1"
        },
        # Conservative bear emphasizes risks
        "bear_researcher": {
            "bias": "conservative",
            "variant": "v1"
        },
        # Standard trader
        "trader": {
            "bias": "default",
            "variant": "v1"
        },
    }
    
    # Standard debate rounds
    config["max_debate_rounds"] = 1
    
    return config


# =============================================================================
# Configuration Example 6: Technical Analysis Focus
# =============================================================================

def technical_analysis_config():
    """
    Configuration emphasizing technical analysis.
    
    Uses technical market analyst for chart-focused insights.
    """
    config = DEFAULT_CONFIG.copy()
    config["evo_enabled"] = True
    
    config["evo_variants"] = {
        # Technical analysis specialist
        "market_analyst": {
            "bias": "technical",
            "variant": "v1"
        },
        # Standard researchers
        "bull_researcher": {
            "bias": "default",
            "variant": "v1"
        },
        "bear_researcher": {
            "bias": "default",
            "variant": "v1"
        },
        # Standard trader
        "trader": {
            "bias": "default",
            "variant": "v1"
        },
    }
    
    return config


# =============================================================================
# Usage Examples
# =============================================================================

def example_basic_usage():
    """
    Basic usage example with evo configuration.
    """
    print("=" * 60)
    print("Basic Evo Usage Example")
    print("=" * 60)
    
    # Get configuration
    config = custom_variants_config()
    
    # Create evo-enabled trading graph
    ta = TradingAgentsGraphEvo(
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=True,
        config=config
    )
    
    # Run analysis
    print("\nRunning analysis for BTC...")
    final_state, decision = ta.propagate("BTC", "2024-05-10")
    
    print(f"\nDecision: {decision}")
    
    return ta, final_state, decision


def test_available_variants():
    """
    Test and display all available prompt variants.
    """
    print("=" * 60)
    print("Available Prompt Variants")
    print("=" * 60)
    
    from tradingagents.agents_evo import get_prompt_loader
    
    loader = get_prompt_loader()
    
    # List all prompts
    all_prompts = loader.list_available_prompts()
    
    # Group by agent
    agents = {}
    for prompt in all_prompts:
        agent = prompt['agent_name']
        if agent not in agents:
            agents[agent] = []
        agents[agent].append(f"{prompt['bias']}.{prompt['variant']}")
    
    # Display
    for agent, variants in sorted(agents.items()):
        print(f"\n{agent}:")
        for variant in variants:
            print(f"  - {variant}")
    
    print(f"\nTotal: {len(all_prompts)} prompt variants")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("TRADINGAGENTS EVO - CONFIGURATION EXAMPLES")
    print("=" * 60)
    
    # Test available variants
    test_available_variants()
    
    print("\n" + "=" * 60)
    print("Configuration Presets Available:")
    print("=" * 60)
    print("""
1. basic_evo_config()
   - Default variants for all agents
   - Good starting point

2. custom_variants_config()
   - Specify exact variant for each agent
   - Maximum control

3. ab_testing_config()
   - Random variant selection
   - For performance testing

4. aggressive_growth_config()
   - Aggressive bull + momentum trader
   - Growth-focused strategy

5. conservative_config()
   - Conservative bear researcher
   - Risk-aware strategy

6. technical_analysis_config()
   - Technical market analyst
   - Chart-focused analysis
""")
    
    print("=" * 60)
    print("Usage Example:")
    print("=" * 60)
    print("""
from tradingagents.graph.trading_graph_evo import TradingAgentsGraphEvo
from tradingagents.default_config import DEFAULT_CONFIG

# Configure evo
config = DEFAULT_CONFIG.copy()
config["evo_enabled"] = True
config["evo_variants"] = {
    "market_analyst": {"bias": "technical", "variant": "v1"},
    "bull_researcher": {"bias": "aggressive", "variant": "v1"},
}

# Create graph
ta = TradingAgentsGraphEvo(config=config)

# Run analysis
_, decision = ta.propagate("BTC", "2024-05-10")
print(decision)
""")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
