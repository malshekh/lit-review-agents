"""OpenAI Chat Completions, also used for Kimi (Moonshot exposes an OpenAI-compatible API).

Docs: https://developers.openai.com/api/reference  ·  Kimi: https://platform.kimi.ai/docs
Per-provider settings (base_url, key, whether to send temperature, JSON mode, reasoning effort) come from
config/pipeline.yaml -> providers.

Temperature: `temperature` is accepted by every function here and sent only when the provider's
`send_temperature` is true. It is false for all three providers (their reasoning models reject a non-default
value), so the per-agent temperature in pipeline.yaml is a provenance record, not a request field.

Reasoning effort: an agent's `effort` is sent as `reasoning_effort` when the provider's
`reasoning_effort.send` is true, and only if the value is in its `allowed` list. A value the provider does not
accept raises before any request is built: Kimi K3.1 Pro runs at `max` when the field is omitted, so silently
dropping it would buy the most expensive reasoning on every call.
"""
from __future__ import annotations

import os

from .. import config
from .base import LLMResponse, as_parts

_clients: dict[str, object] = {}


def _get_client(provider: str):
    if provider not in _clients:
        from openai import OpenAI
        from ..preflight import require_clean_endpoints
        require_clean_endpoints()
        p = config.load("pipeline")["providers"][provider]
        _clients[provider] = OpenAI(api_key=os.environ.get(p["key_env"]),
                                    base_url=p.get("base_url") or "https://api.openai.com/v1")
    return _clients[provider]


def reasoning_effort(provider: str, effort: str | None) -> str | None:
    """The `reasoning_effort` value to send for this provider, or None when it sends none."""
    setting = (config.load("pipeline")["providers"][provider].get("reasoning_effort") or {})
    if not setting.get("send") or not effort:
        if setting.get("send") and setting.get("required"):
            raise ValueError(f"{provider}: an effort is required on every call (providers.{provider}.reasoning_effort)")
        return None
    allowed = list(setting.get("allowed") or [])
    if effort not in allowed:
        raise ValueError(f"{provider} does not accept reasoning effort '{effort}'; allowed: {', '.join(allowed)}. "
                         "Set the agent's `effort` in config/pipeline.yaml to one of them.")
    return effort


def chat_params(system: str, user, model: str, max_tokens: int, temperature: float, provider: str = "openai",
                effort: str | None = None, response_schema: dict | None = None) -> dict:
    """The Chat Completions request body, shared by complete() and a batch line's `body`."""
    # `cache_system` is a Claude setting. Ordinary OpenAI/Kimi calls
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
    sent_effort = reasoning_effort(provider, effort)
    if sent_effort:
        kwargs["reasoning_effort"] = sent_effort
    if response_schema:   # structured output for a combination the smoke test confirmed (structured.py)
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {
            "name": response_schema["name"], "schema": response_schema["schema"], "strict": False}}
    elif p.get("json_mode", True):
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def complete(system: str, user, model: str, max_tokens: int, temperature: float,
             provider: str = "openai", effort: str | None = None, cache_system: bool = False,
             cache_ttl: str = "5m", trace: dict | None = None, response_schema: dict | None = None) -> LLMResponse:
    # `trace` identifies the agent and run for launchers that wrap this route; it is not sent to the provider.
    resp = _get_client(provider).chat.completions.create(**chat_params(system, user, model, max_tokens,
                                                                       temperature, provider, effort,
                                                                       response_schema))
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
