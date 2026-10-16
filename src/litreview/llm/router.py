"""Route a completion to the configured provider."""
from __future__ import annotations

from . import anthropic_client, openai_client
from .base import LLMResponse

_PROVIDERS = {"anthropic": anthropic_client.complete, "openai": openai_client.complete}


def complete(provider: str, **kwargs) -> LLMResponse:
    try:
        fn = _PROVIDERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic' or 'openai'.") from exc
    return fn(**kwargs)
