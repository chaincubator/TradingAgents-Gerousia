# Agents Evo - External Prompt Management System

## Overview

Agents Evo is a restructured prompt management system for TradingAgents that externalizes all agent prompts from the codebase into modular, configurable files. This enables:

- **Multiple Prompt Variants**: Different biases and specialties for each agent role
- **A/B Testing**: Compete different prompt versions against each other
- **Easy Iteration**: Update prompts without code changes
- **Bias Specialization**: Run aggressive vs conservative variants of the same agent
- **Cleaner Code**: Separation of concerns between logic and prompts

## Naming Convention

**Format:** `{agent_name}.{bias_specialty}.{variant_id}.prompt.md`

### Components

| Component | Description | Examples |
|-----------|-------------|----------|
| `agent_name` | The agent role identifier | `market_analyst`, `bull_researcher`, `trader` |
| `bias_specialty` | The bias or specialty focus | `default`, `aggressive`, `conservative`, `technical`, `momentum` |
| `variant_id` | Version identifier for A/B testing | `v1`, `v2`, `v3` |

### Examples

```
market_analyst.default.v1.prompt.md      # Default market analyst prompt
market_analyst.technical.v1.prompt.md    # Technical-focused variant
bull_researcher.aggressive.v1.prompt.md  # Aggressive bull variant
trader.momentum.v1.prompt.md             # Momentum trading variant
```

## Directory Structure

```
tradingagents/agents_evo/
├── __init__.py                    # Package exports
├── prompt_loader.py               # Core prompt loading utility
├── README.md                      # This file
├── analysts/                      # Analyst agent prompts
│   ├── market_analyst.default.v1.prompt.md
│   ├── market_analyst.technical.v1.prompt.md
│   ├── social_analyst.default.v1.prompt.md
│   ├── news_analyst.default.v1.prompt.md
│   ├── fundamentals_analyst.default.v1.prompt.md
│   ├── fred_analyst.default.v1.prompt.md
│   └── polymarket_analyst.default.v1.prompt.md
├── researchers/                   # Research team prompts
│   ├── bull_researcher.default.v1.prompt.md
│   ├── bull_researcher.aggressive.v1.prompt.md
│   ├── bear_researcher.default.v1.prompt.md
│   ├── bear_researcher.conservative.v1.prompt.md
│   └── research_manager.default.v1.prompt.md
├── trader/                        # Trader agent prompts
│   ├── trader.default.v1.prompt.md
│   └── trader.momentum.v1.prompt.md
├── risk_mgmt/                     # Risk management prompts
│   ├── risky_debator.default.v1.prompt.md
│   ├── safe_debator.default.v1.prompt.md
│   ├── neutral_debator.default.v1.prompt.md
│   └── risk_manager.default.v1.prompt.md
└── portfolio/                     # Portfolio manager prompts
    └── portfolio_manager.default.v1.prompt.md
```

## Usage

### Basic Usage

```python
from tradingagents.agents_evo import load_agent_prompt

# Load default prompt for an agent
prompt = load_agent_prompt('market_analyst')
print(prompt)  # Contains the full prompt text

# Load specific variant
prompt = load_agent_prompt('bull_researcher', bias='aggressive', variant='v1')
```

### Advanced Usage

```python
from tradingagents.agents_evo import get_prompt_loader

loader = get_prompt_loader()

# List all available prompts
all_prompts = loader.list_available_prompts()
for p in all_prompts:
    print(f"{p['agent_name']}.{p['bias']}.{p['variant']}")

# List variants for a specific agent
variants = loader.get_prompt_variants('market_analyst')
for bias, prompts in variants.items():
    print(f"Bias: {bias}")
    for prompt in prompts:
        print(f"  - {prompt['variant']}: {prompt['filepath']}")

# Load by specific path
prompt = loader.load_prompt_by_path('agents_evo/analysts/market_analyst.technical.v1.prompt.md')

# Clear cache (useful when editing prompts during development)
loader.clear_cache()

# Reload all prompts from disk
loader.reload_all_prompts()
```

### In Agent Code

```python
from tradingagents.agents_evo import load_agent_prompt
from langchain_core.prompts import ChatPromptTemplate

def create_market_analyst(llm, toolkit):
    # Load the prompt template
    prompt_text = load_agent_prompt('market_analyst', bias='technical', variant='v1')
    
    def market_analyst_node(state):
        # Format the prompt with state variables
        formatted_prompt = prompt_text.format(
            tool_names=", ".join([tool.name for tool in tools]),
            current_date=state["trade_date"],
            ticker=state["company_of_interest"],
            # ... other variables
        )
        
        # Create LangChain prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", formatted_prompt),
        ])
        
        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])
        
        return {"messages": [result], "market_report": result.content}
    
    return market_analyst_node
```

## Available Agents and Variants

### Analysts

| Agent | Variants | Description |
|-------|----------|-------------|
| `market_analyst` | `default`, `technical` | Technical analysis and market trends |
| `social_analyst` | `default` | Social media and sentiment analysis |
| `news_analyst` | `default` | News research and macro analysis |
| `fundamentals_analyst` | `default` | Fundamental analysis |
| `fred_analyst` | `default` | FRED macroeconomic data analysis |
| `polymarket_analyst` | `default` | Prediction market analysis |

### Researchers

| Agent | Variants | Description |
|-------|----------|-------------|
| `bull_researcher` | `default`, `aggressive` | Bull case advocate |
| `bear_researcher` | `default`, `conservative` | Bear case advocate |
| `research_manager` | `default` | Synthesizes research panel |

### Trader

| Agent | Variants | Description |
|-------|----------|-------------|
| `trader` | `default`, `momentum` | Trading decision maker |

### Risk Management

| Agent | Variants | Description |
|-------|----------|-------------|
| `risky_debator` | `default` | High-risk advocate |
| `safe_debator` | `default` | Conservative advocate |
| `neutral_debator` | `default` | Balanced perspective |
| `risk_manager` | `default` | Risk debate judge |

## Creating New Prompt Variants

### Step 1: Copy Existing Prompt

```bash
cp agents_evo/analysts/market_analyst.default.v1.prompt.md \
   agents_evo/analysts/market_analyst.momentum.v1.prompt.md
```

### Step 2: Modify the Prompt

Edit the new file with your desired changes. For example, to create a momentum-focused market analyst:

```markdown
# Market Analyst - Momentum v1

## Role Definition

You are a **Momentum Market Analyst** specializing in identifying and analyzing price momentum, trend continuation patterns, and breakout setups...

[Rest of your custom prompt]
```

### Step 3: Use in Your Agent

```python
# In your agent creation code
prompt = load_agent_prompt('market_analyst', bias='momentum', variant='v1')
```

## A/B Testing Prompt Variants

To test which prompt variant performs better:

```python
import random

def get_agent_prompt(agent_name, context):
    """Select prompt variant based on context or A/B test."""
    
    # A/B test: randomly select variant
    if agent_name == 'bull_researcher':
        variants = ['default', 'aggressive']
        selected_bias = random.choice(variants)
        return load_agent_prompt(agent_name, bias=selected_bias)
    
    # Context-aware selection
    if context.get('market_regime') == 'bull_market':
        return load_agent_prompt(agent_name, bias='aggressive')
    else:
        return load_agent_prompt(agent_name, bias='conservative')
```

## Prompt Template Variables

Prompts can use the following template variables (formatted at runtime):

| Variable | Description |
|----------|-------------|
| `{tool_names}` | Comma-separated list of available tools |
| `{current_date}` | Current trading date (YYYY-MM-DD) |
| `{ticker}` | Company/asset symbol |
| `{company_name}` | Company/asset name |
| `{history}` | Conversation/debate history |
| `{past_analysis}` | Scored history from prior runs |
| `{past_memory_str}` | Lessons from similar situations |
| `{market_research_report}` | 5m market analysis |
| `{market_4h_report}` | 4h market analysis |
| `{sentiment_report}` | Social sentiment analysis |
| `{news_report}` | News analysis |
| `{fundamentals_report}` | Fundamental analysis |
| `{fred_report}` | FRED macro snapshot |
| `{polymarket_report}` | Prediction market signals |
| `{polymarket_price_levels}` | Price range probabilities |
| `{trader_decision}` | Trader's proposed plan |
| `{current_response}` | Last response from debate partner |

## Best Practices

### 1. Keep Prompts Modular
Each prompt file should be self-contained and focused on a specific role.

### 2. Use Clear Variant Names
Name variants descriptively: `aggressive`, `conservative`, `technical`, `momentum`.

### 3. Document Changes
When creating new variants, note what's different in the prompt header.

### 4. Test Variants Systematically
Run A/B tests to determine which variants perform better.

### 5. Version Control
Use v1, v2, v3 for iterations of the same bias type.

### 6. Cache Management
Clear cache during development when editing prompts:
```python
loader.clear_cache()
```

## Migration Guide

To migrate existing agents to use external prompts:

1. **Extract the prompt** from the agent code into a `.prompt.md` file
2. **Replace hardcoded strings** with `load_agent_prompt()` calls
3. **Test thoroughly** to ensure behavior is unchanged
4. **Create variants** to leverage the new system's flexibility

## Future Enhancements

Planned improvements:
- [ ] Prompt templating engine with Jinja2
- [ ] Prompt versioning and diff tools
- [ ] Performance tracking per prompt variant
- [ ] Auto-generated prompt variants via LLM
- [ ] Prompt optimization based on outcomes
