# Agents Evo - Usage Guide

## Quick Start

### 1. Enable Evo Mode

```python
from tradingagents.graph.trading_graph_evo import TradingAgentsGraphEvo
from tradingagents.default_config import DEFAULT_CONFIG

# Basic evo configuration
config = DEFAULT_CONFIG.copy()
config["evo_enabled"] = True

# Create evo-enabled graph
ta = TradingAgentsGraphEvo(config=config)

# Use as normal
_, decision = ta.propagate("BTC", "2024-05-10")
```

### 2. Select Prompt Variants

```python
config["evo_variants"] = {
    "market_analyst": {"bias": "technical", "variant": "v1"},
    "bull_researcher": {"bias": "aggressive", "variant": "v1"},
    "bear_researcher": {"bias": "conservative", "variant": "v1"},
    "trader": {"bias": "momentum", "variant": "v1"},
}
```

### 3. Run Analysis

```python
ta = TradingAgentsGraphEvo(
    selected_analysts=["market", "social", "news", "fundamentals"],
    debug=True,
    config=config
)

_, decision = ta.propagate("BTC", "2024-05-10")
print(decision)
```

## Available Prompt Variants

| Agent | Variants | Description |
|-------|----------|-------------|
| market_analyst | default, technical | General vs technical-focused |
| bull_researcher | default, aggressive | Standard vs aggressive bull |
| bear_researcher | default, conservative | Standard vs conservative bear |
| trader | default, momentum | General vs momentum trading |

## Configuration Presets

See `evo_config_examples.py` for ready-to-use configurations:

- `basic_evo_config()` - Default variants
- `custom_variants_config()` - Specific variant selection
- `ab_testing_config()` - Random variant selection
- `aggressive_growth_config()` - Growth-focused
- `conservative_config()` - Risk-aware
- `technical_analysis_config()` - Chart-focused

## A/B Testing

```python
import random

# Run multiple analyses with different variants
for i in range(10):
    config = DEFAULT_CONFIG.copy()
    config["evo_enabled"] = True
    config["evo_variants"] = {
        "bull_researcher": {
            "bias": random.choice(["default", "aggressive"]),
            "variant": "v1"
        },
    }
    
    ta = TradingAgentsGraphEvo(config=config)
    _, decision = ta.propagate("BTC", "2024-05-10")
    
    # Track results to determine best variant
```

## Creating New Variants

1. Copy existing prompt:
```bash
cp agents_evo/analysts/market_analyst.default.v1.prompt.md \
   agents_evo/analysts/market_analyst.momentum.v1.prompt.md
```

2. Edit the new prompt file with your custom instructions

3. Use in config:
```python
config["evo_variants"] = {
    "market_analyst": {"bias": "momentum", "variant": "v1"},
}
```

## API Reference

### TradingAgentsGraphEvo

```python
TradingAgentsGraphEvo(
    selected_analysts=["market", "social", "news", "fundamentals"],
    debug=False,
    config=None
)
```

**Parameters:**
- `selected_analysts`: List of analyst types to include
- `debug`: Enable debug mode with detailed output
- `config`: Configuration dictionary

**Config Options:**
- `evo_enabled`: bool - Enable evo system (default: True)
- `evo_variants`: dict - Prompt variant selections per agent

### Methods

- `propagate(company_name, trade_date)` - Run analysis
- `reflect_and_remember(returns_losses)` - Update memory
- `process_signal(full_signal)` - Extract decision

## Troubleshooting

### Prompt Not Found Error

```
FileNotFoundError: Prompt not found: market_analyst.momentum.v1.prompt.md
```

**Solution:** Check that the prompt file exists in `agents_evo/analysts/`

### Variant Not Available

```
Available variants for market_analyst:
  - default.v1
  - technical.v1
```

**Solution:** Use one of the listed variants or create a new one

## Next Steps

1. Review available variants: `python examples/evo_config_examples.py`
2. Try a configuration preset
3. Create custom variants for your strategy
4. Run A/B tests to optimize performance
