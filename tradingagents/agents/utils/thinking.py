"""Utilities for handling thinking-model output tokens.

Qwen3, Qwen3.5, and QwQ models can produce thinking tokens in the format
    <think>...reasoning...</think>
    ...actual answer...

These should be stripped before storing or forwarding agent responses.
strip_thinking() is a safe no-op when no thinking tokens are present.
"""

import re


def strip_thinking(text: str) -> str:
    """
    Remove <think>...</think> reasoning blocks from LLM output.

    Safe to call on any text — returns the original string unchanged
    when no thinking tokens are present.  Falls back to the original
    if stripping would produce an empty string (e.g. the model ONLY
    produced thinking tokens and no final answer).
    """
    stripped = re.sub(r"<think>[\s\S]*?</think>\s*", "", text, flags=re.DOTALL).strip()
    return stripped if stripped else text
