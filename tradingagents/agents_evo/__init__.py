"""
Agents Evo - External Prompt System for Trading Agents

This package provides a flexible prompt management system that allows
agents to load prompts from external files, enabling:
- Multiple prompt variants per agent
- A/B testing of different prompt strategies
- Easy prompt iteration without code changes
- Competing agent biases within functional areas

Directory Structure:
    agents_evo/
    ├── analysts/
    │   ├── market_analyst.default.v1.prompt.md
    │   ├── market_analyst.technical.v1.prompt.md
    │   └── ...
    ├── researchers/
    │   ├── bull_researcher.default.v1.prompt.md
    │   ├── bull_researcher.aggressive.v1.prompt.md
    │   └── ...
    ├── trader/
    │   └── ...
    ├── risk_mgmt/
    │   └── ...
    └── portfolio/
        └── ...

Naming Convention:
    {agent_name}.{bias_specialty}.{variant_id}.prompt.md
    
Example Usage:
    from tradingagents.agents_evo import load_agent_prompt
    
    # Load default prompt
    prompt = load_agent_prompt('market_analyst')
    
    # Load specific variant
    prompt = load_agent_prompt('bull_researcher', bias='aggressive', variant='v1')
    
    # List available variants
    from tradingagents.agents_evo import get_prompt_loader
    loader = get_prompt_loader()
    variants = loader.get_prompt_variants('market_analyst')
"""

from .prompt_loader import (
    PromptLoader,
    get_prompt_loader,
    load_agent_prompt,
)

__all__ = [
    'PromptLoader',
    'get_prompt_loader',
    'load_agent_prompt',
]

__version__ = '1.0.0'
