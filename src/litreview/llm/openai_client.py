"""OpenAI Chat Completions wrapper (JSON mode). Docs: https://platform.openai.com/docs/api-reference/chat

Note: some OpenAI reasoning models reject a non-default `temperature`;
remove it below if your chosen model requires that.
"""
from __future__ import annotations

import os

from .base import LLMResponse

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def complete(system: str, user: str, model: str, max_tokens: int, temperature: float) -> LLMResponse:
    resp = _get_client().chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    choice = resp.choices[0]
    return LLMResponse(
        text=choice.message.content or "",
        provider="openai",
        model=model,
        input_tokens=resp.usage.prompt_tokens,
        output_tokens=resp.usage.completion_tokens,
        stop_reason=choice.finish_reason,
    )
