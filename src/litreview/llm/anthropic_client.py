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


def _cache(ttl: str) -> dict:
    """5m: write 1.25x input. 1h: write 2x input. Reads are the same price for both."""
    return {"type": "ephemeral"} if ttl == "5m" else {"type": "ephemeral", "ttl": ttl}


def request_body(system: str, user, cache_system: bool = False, cache_ttl: str = "5m") -> dict:
    """System and messages with cache marks (shared by complete() and the token counter)."""
    mark = _cache(cache_ttl)
    content = [{"type": "text", "text": p["text"], **({"cache_control": mark} if p.get("cache") else {})}
               for p in as_parts(user)]
    return {"system": [{"type": "text", "text": system, "cache_control": mark}] if cache_system else system,
            "messages": [{"role": "user", "content": content}]}


def count_tokens(system: str, user, model: str, cache_system: bool = False, cache_ttl: str = "5m") -> int:
    """Input tokens for a request, from the token-counting API (free). Used to gate long jobs."""
    return _get_client().messages.count_tokens(model=model, **request_body(system, user, cache_system,
                                                                           cache_ttl)).input_tokens


def message_params(system: str, user, model: str, max_tokens: int, temperature: float,
                   effort: str | None = None, cache_system: bool = False, cache_ttl: str = "5m") -> dict:
    """The Messages request, shared by complete() and a batch item's `params` (identical by construction)."""
    pcfg = config.load("pipeline")["providers"]["anthropic"]
    kwargs: dict = {"model": model, "max_tokens": max_tokens, **request_body(system, user, cache_system, cache_ttl)}
    if pcfg.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if effort:
        kwargs["output_config"] = {"effort": effort}
    return kwargs


def complete(system: str, user, model: str, max_tokens: int, temperature: float,
             provider: str = "anthropic", effort: str | None = None, cache_system: bool = False,
             cache_ttl: str = "5m") -> LLMResponse:
    """Streams the request (so large max_tokens never hits the SDK's non-streaming timeout) and
    returns the final message. Thinking counts toward max_tokens; `effort` (per agent in
    pipeline.yaml) controls how much of it is spent. Prompt caching: `cache_system` marks the system
    prompt, and user blocks with "cache": True are marked too (the prefix up to each mark is cached)."""
    kwargs = message_params(system, user, model, max_tokens, temperature, effort, cache_system, cache_ttl)
    with _get_client().messages.stream(**kwargs) as s:
        resp = s.get_final_message()
    return parse_message(resp, model)


def parse_message(resp, model: str) -> LLMResponse:
    """A Message (streamed, or a batch item's `result.message`) as an LLMResponse."""
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
