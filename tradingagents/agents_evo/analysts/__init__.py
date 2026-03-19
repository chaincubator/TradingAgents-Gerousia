"""
Analysts Evo - External Prompt Based Analyst Agents

This package provides analyst agents using external prompts, enabling:
- Multiple bias variants per analyst
- A/B testing of different prompt strategies
- Easy prompt iteration without code changes
"""

from .market_analyst_evo import (
    create_market_analyst_evo,
    create_market_4h_analyst_evo,
)

__all__ = [
    'create_market_analyst_evo',
    'create_market_4h_analyst_evo',
]
