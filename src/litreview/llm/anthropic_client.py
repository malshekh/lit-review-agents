"""Anthropic Messages API wrapper. Docs: https://docs.claude.com/en/api/messages"""
from __future__ import annotations

import os

from .base import LLMResponse

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so tests run without the SDK configured
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def complete(system: str, user: str, model: str, max_tokens: int, temperature: float) -> LLMResponse:
    resp = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return LLMResponse(
        text=text,
        provider="anthropic",
        model=model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        stop_reason=resp.stop_reason,
    )
