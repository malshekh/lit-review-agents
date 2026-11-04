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


def chat_params(system: str, user, model: str, max_tokens: int, temperature: float, provider: str = "openai") -> dict:
    """The Chat Completions request body, shared by complete() and a batch line's `body`."""
    # `effort` and `cache_system` are Claude settings. Ordinary OpenAI/Kimi calls
    # preserve their existing implicit caching; marked A06 work units use an explicit shared boundary.
    p = config.load("pipeline")["providers"][provider]
    kwargs: dict = {
        "model": model,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": "\n\n".join(x["text"] for x in as_parts(user))}],
    }
    blocks=as_parts(user)
    if provider=='openai' and any(x.get('a06_shared_prefix') for x in blocks):
        # Current Chat Completions supports a 30m request TTL. Do not send Anthropic TTLs.
        settings=p.get('a06_cache',{'mode':'explicit','ttl':'30m'})
        mode=settings.get('mode','explicit');ttl=settings.get('ttl','30m')
        if mode not in ('explicit','off','implicit') or ttl!='30m':
            raise ValueError('A06 Chat Completions caching supports explicit/off/implicit with 30m TTL only')
        if not (model.startswith('gpt-6') or model.startswith('gpt-5.6')):
            raise ValueError('Explicit A06 cache settings require a supported OpenAI model')
        content=[]
        for block in blocks:
            item={'type':'text','text':block['text']}
            if mode=='explicit' and block.get('a06_shared_prefix'):
                item['prompt_cache_breakpoint']={'mode':'explicit'}
            content.append(item)
        kwargs['messages'][1]['content']=content
        kwargs['prompt_cache_options']={'mode':'explicit' if mode=='off' else mode,'ttl':ttl}
        # No explicit breakpoint + explicit-only mode disables caching for the control.
    if p.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if p.get("json_mode", True):
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def complete(system: str, user, model: str, max_tokens: int, temperature: float,
             provider: str = "openai", effort: str | None = None, cache_system: bool = False,
             cache_ttl: str = "5m") -> LLMResponse:
    resp = _get_client(provider).chat.completions.create(**chat_params(system, user, model, max_tokens,
                                                                       temperature, provider))
    return parse_completion(resp, provider, model)


def parse_completion(resp, provider: str, model: str) -> LLMResponse:
    """A ChatCompletion (or a batch output line's `response.body`, as a dict) as an LLMResponse."""
    if isinstance(resp, dict):
        from openai.types.chat import ChatCompletion
        resp = ChatCompletion.model_validate(resp)
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
