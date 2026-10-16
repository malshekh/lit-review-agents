"""Anthropic Messages API wrapper. Docs: https://platform.claude.com/docs/en/api/messages"""
from __future__ import annotations

import os

from .. import config
from .base import LLMResponse

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so tests run without the SDK configured
        key_env = config.load("pipeline")["providers"]["anthropic"]["key_env"]
        _client = anthropic.Anthropic(api_key=os.environ.get(key_env))
    return _client


def complete(system: str, user: str, model: str, max_tokens: int, temperature: float,
             provider: str = "anthropic") -> LLMResponse:
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]}
    if config.load("pipeline")["providers"]["anthropic"].get("send_temperature", True):
        kwargs["temperature"] = temperature
    resp = _get_client().messages.create(**kwargs)
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return LLMResponse(
        text=text,
        provider="anthropic",
        model=model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        stop_reason=resp.stop_reason,
    )
