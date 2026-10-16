"""Route a completion to the configured provider: anthropic, openai or kimi."""
from __future__ import annotations

from . import anthropic_client, openai_compatible, tracing
from .base import LLMResponse

_PROVIDERS = {
    "anthropic": anthropic_client.complete,
    "openai": openai_compatible.complete,
    "kimi": openai_compatible.complete,
}


def complete(provider: str, trace: dict | None = None, **kwargs) -> LLMResponse:
    try:
        fn = _PROVIDERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unknown provider '{provider}'. Use anthropic, openai or kimi.") from exc
    trace = trace or {}
    return tracing.traced_call(lambda: fn(provider=provider, **kwargs),
                               name=f"{trace.get('agent', 'llm')} · {kwargs.get('model')}",
                               provider=provider, model=kwargs.get("model", ""), metadata=trace)
