"""OpenAI Chat Completions, also used for Kimi (Moonshot exposes an OpenAI-compatible API).

Docs: https://developers.openai.com/api/reference  ·  Kimi: https://platform.kimi.ai/docs
Per-provider settings (base_url, key, whether to send temperature, JSON mode) come from
config/pipeline.yaml -> providers.
"""
from __future__ import annotations

import os

from .. import config
from .base import LLMResponse

_clients: dict[str, object] = {}


def _get_client(provider: str):
    if provider not in _clients:
        from openai import OpenAI
        p = config.load("pipeline")["providers"][provider]
        _clients[provider] = OpenAI(api_key=os.environ.get(p["key_env"]), base_url=p.get("base_url") or None)
    return _clients[provider]


def complete(system: str, user: str, model: str, max_tokens: int, temperature: float,
             provider: str = "openai") -> LLMResponse:
    p = config.load("pipeline")["providers"][provider]
    kwargs: dict = {
        "model": model,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if p.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if p.get("json_mode", True):
        kwargs["response_format"] = {"type": "json_object"}
    resp = _get_client(provider).chat.completions.create(**kwargs)
    choice = resp.choices[0]
    return LLMResponse(
        text=choice.message.content or "",
        provider=provider,
        model=model,
        input_tokens=resp.usage.prompt_tokens,
        output_tokens=resp.usage.completion_tokens,   # includes reasoning tokens, which are billed
        stop_reason=choice.finish_reason,
    )
