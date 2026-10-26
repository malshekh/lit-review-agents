"""OpenAI Chat Completions, also used for Kimi (Moonshot exposes an OpenAI-compatible API).

Docs: https://developers.openai.com/api/reference  ·  Kimi: https://platform.kimi.ai/docs
Per-provider settings (base_url, key, whether to send temperature, JSON mode) come from
config/pipeline.yaml -> providers.
"""
from __future__ import annotations

import os

from .. import config
from .base import LLMResponse, as_parts

_clients: dict[str, object] = {}


def _get_client(provider: str):
    if provider not in _clients:
        from openai import OpenAI
        p = config.load("pipeline")["providers"][provider]
        _clients[provider] = OpenAI(api_key=os.environ.get(p["key_env"]), base_url=p.get("base_url") or None)
    return _clients[provider]


def complete(system: str, user, model: str, max_tokens: int, temperature: float,
             provider: str = "openai", effort: str | None = None, cache_system: bool = False) -> LLMResponse:
    # `effort` and `cache_system` are Claude settings; OpenAI and Kimi cache repeated prompt prefixes
    # automatically, so blocks are simply joined in order (the stable prefix stays first).
    p = config.load("pipeline")["providers"][provider]
    kwargs: dict = {
        "model": model,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": "\n\n".join(x["text"] for x in as_parts(user))}],
    }
    if p.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if p.get("json_mode", True):
        kwargs["response_format"] = {"type": "json_object"}
    resp = _get_client(provider).chat.completions.create(**kwargs)
    choice = resp.choices[0]
    u = resp.usage
    details = getattr(u, "prompt_tokens_details", None)
    # prompt_tokens includes cached reads and cache writes; Kimi may report cached_tokens on usage itself
    cached = (getattr(details, "cached_tokens", None) or getattr(u, "cached_tokens", None) or 0)
    written = getattr(details, "cache_write_tokens", None) or 0
    refusal = getattr(choice.message, "refusal", None)
    refused = bool(refusal) or choice.finish_reason == "content_filter"
    return LLMResponse(
        text=choice.message.content or "",
        provider=provider,
        model=model,
        input_tokens=max(u.prompt_tokens - cached - written, 0),
        output_tokens=u.completion_tokens,   # includes reasoning tokens, which are billed
        stop_reason="refusal" if refused else choice.finish_reason,
        refusal_category=(refusal or "content_filter")[:200] if refused else None,
        cached_input_tokens=cached,
        cache_write_tokens=written,
    )
