"""Anthropic Messages API wrapper. Docs: https://platform.claude.com/docs/en/api/messages

Safety classifiers on some Claude models can decline a request (HTTP 200, stop_reason "refusal");
biomedical topics can trigger the "bio" category by mistake. A refusal is returned as such and never
retried: re-sending an identical request to the same model usually refuses again, and on a large
payload costs a full input pass. The orchestrator records it per model and topic family and routes
later stages elsewhere (pipeline.yaml -> routing).
"""
from __future__ import annotations

import os

from .. import config
from .base import LLMResponse, as_parts

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so tests run without the SDK configured
        key_env = config.load("pipeline")["providers"]["anthropic"]["key_env"]
        _client = anthropic.Anthropic(api_key=os.environ.get(key_env))
    return _client


CACHE = {"type": "ephemeral"}   # 5-minute prompt cache; a write costs 1.25x input, a read about 0.1x


def complete(system: str, user, model: str, max_tokens: int, temperature: float,
             provider: str = "anthropic", effort: str | None = None, cache_system: bool = False) -> LLMResponse:
    """Streams the request (so large max_tokens never hits the SDK's non-streaming timeout) and
    returns the final message. Thinking counts toward max_tokens; `effort` (per agent in
    pipeline.yaml) controls how much of it is spent. Prompt caching: `cache_system` marks the system
    prompt, and user blocks with "cache": True are marked too (the prefix up to each mark is cached)."""
    pcfg = config.load("pipeline")["providers"]["anthropic"]
    content = [{"type": "text", "text": p["text"], **({"cache_control": CACHE} if p.get("cache") else {})}
               for p in as_parts(user)]
    kwargs: dict = {"model": model, "max_tokens": max_tokens,
                    "system": [{"type": "text", "text": system, "cache_control": CACHE}] if cache_system else system,
                    "messages": [{"role": "user", "content": content}]}
    if pcfg.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if effort:
        kwargs["output_config"] = {"effort": effort}
    with _get_client().messages.stream(**kwargs) as s:
        resp = s.get_final_message()
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    details = getattr(resp, "stop_details", None)
    u = resp.usage
    written = getattr(u, "cache_creation_input_tokens", None) or 0
    written_1h = getattr(getattr(u, "cache_creation", None), "ephemeral_1h_input_tokens", None) or 0
    return LLMResponse(
        text=text,
        provider="anthropic",
        model=model,
        input_tokens=u.input_tokens,   # Anthropic reports cache reads and writes separately
        output_tokens=u.output_tokens,
        stop_reason=resp.stop_reason,
        refusal_category=getattr(details, "category", None) if resp.stop_reason == "refusal" else None,
        cached_input_tokens=getattr(u, "cache_read_input_tokens", None) or 0,
        cache_write_tokens=written - written_1h,   # the total includes 1-hour writes; split them out
        cache_write_1h_tokens=written_1h,
    )
