"""Anthropic Messages API wrapper. Docs: https://platform.claude.com/docs/en/api/messages

Claude Opus 5.5 / Sonnet 5.5 run safety classifiers that can decline a request (HTTP 200,
stop_reason "refusal"). Biomedical topics such as drug repurposing for cancer can trigger the `bio`
category by mistake, so requests opt into server-side fallback: a declined request is retried on
the model's default fallback model. Configure in config/pipeline.yaml (providers.anthropic.fallbacks;
null turns it off). A fallback-served reply is billed per model, so usage is returned per model.
Docs: https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback
"""
from __future__ import annotations

import os

from .. import config
from .base import LLMResponse

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so tests run without the SDK configured
        key_env = config.load("pipeline")["providers"]["anthropic"]["key_env"]
        _client = anthropic.Anthropic(api_key=os.environ.get(key_env))
    return _client


def _usage_parts(resp, requested: str) -> list[tuple[str, int, int]]:
    """Tokens per model. With a fallback, the declined hop and the serving model bill separately."""
    iters = getattr(resp.usage, "iterations", None) or []
    parts = [(getattr(it, "model", None) or requested, it.input_tokens, it.output_tokens)
             for it in iters if getattr(it, "type", "") in ("message", "fallback_message")]
    return parts or [(requested, resp.usage.input_tokens, resp.usage.output_tokens)]


def complete(system: str, user: str, model: str, max_tokens: int, temperature: float,
             provider: str = "anthropic", effort: str | None = None) -> LLMResponse:
    """Streams the request (so large max_tokens never hits the SDK's non-streaming timeout) and
    returns the final message. Thinking is always on for Claude 5.5 models and counts toward
    max_tokens; `effort` (per agent in pipeline.yaml) controls how much of it is spent."""
    pcfg = config.load("pipeline")["providers"]["anthropic"]
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]}
    if pcfg.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if effort:
        kwargs["output_config"] = {"effort": effort}
    fallbacks = pcfg.get("fallbacks", "default")
    if fallbacks:
        stream = _get_client().beta.messages.stream(betas=[FALLBACK_BETA], fallbacks=fallbacks, **kwargs)
    else:
        stream = _get_client().messages.stream(**kwargs)
    with stream as s:
        resp = s.get_final_message()
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    parts = _usage_parts(resp, model)
    served = next((getattr(it, "model", None) for it in getattr(resp.usage, "iterations", None) or []
                   if getattr(it, "type", "") == "fallback_message"), None) or model
    details = getattr(resp, "stop_details", None)
    return LLMResponse(
        text=text,
        provider="anthropic",
        model=served,
        input_tokens=sum(p[1] for p in parts),
        output_tokens=sum(p[2] for p in parts),
        stop_reason=resp.stop_reason,
        refusal_category=getattr(details, "category", None) if resp.stop_reason == "refusal" else None,
        usage_parts=parts,
    )
