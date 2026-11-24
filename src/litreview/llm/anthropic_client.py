"""Anthropic Messages API wrapper. Docs: https://platform.claude.com/docs/en/api/messages

Safety classifiers on some Claude models can decline a request (HTTP 200, stop_reason "refusal");
biomedical topics can trigger the "bio" category by mistake. A refusal is returned as such and never
retried: re-sending an identical request to the same model usually refuses again, and on a large
payload costs a full input pass. The orchestrator records it per model and topic family and routes
later stages elsewhere (pipeline.yaml -> routing).
"""
from __future__ import annotations

import os
import json
import hashlib
import re
from pathlib import Path

from .. import config
from .base import LLMResponse, as_parts

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported lazily so tests run without the SDK configured
        from ..preflight import require_clean_endpoints
        require_clean_endpoints()   # never build a client that the environment could point at another vendor
        pcfg = config.load("pipeline")["providers"]["anthropic"]
        _client = anthropic.Anthropic(max_retries=0, api_key=os.environ.get(pcfg["key_env"]),
                                      base_url=pcfg.get("base_url") or "https://api.anthropic.com")
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
                   effort: str | None = None, cache_system: bool = False, cache_ttl: str = "5m", trace: dict | None = None,
                   response_schema: dict | None = None) -> dict:
    """The Messages request, shared by complete() and a batch item's `params` (identical by construction)."""
    pcfg = config.load("pipeline")["providers"]["anthropic"]
    kwargs: dict = {"model": model, "max_tokens": max_tokens, **request_body(system, user, cache_system, cache_ttl)}
    if pcfg.get("send_temperature", False):
        kwargs["temperature"] = temperature
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if (trace or {}).get("agent") == "A07-SYN" and str((trace or {}).get("step", "")).endswith("_PLAN"):
        opts = config.load("pipeline")["synthesis"]["plan_request"]
        if opts.get("thinking") != {"type":"adaptive"} or opts.get("effort") != "medium":
            raise ValueError("Controlled PLAN requires adaptive thinking, medium effort and no manual budget")
        kwargs["thinking"] = {"type":"adaptive"}
        kwargs["output_config"] = {"effort":"medium"}
    if response_schema:   # structured output: shape, types, required keys and enumerations (structured.py)
        kwargs.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": response_schema["schema"]}
    return kwargs


def _preserve_plan_response(resp, trace):
    from ..paths import REPO_ROOT
    pcfg = config.load("pipeline")["providers"]["anthropic"]
    folder = Path(pcfg.get("writing_response_audit_dir") or pcfg["plan_response_audit_dir"]).resolve()
    if not folder.is_dir() or folder.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("PLAN raw response requires a private audit directory outside runtime/retrieval paths")
    names = [str(trace.get(k, "")) for k in ("run_id", "step")]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in names):
        raise ValueError("Unsafe PLAN audit identity")
    target = folder / ("__".join(names)+"__attempt"+str(int(trace.get("attempt",0)))+".provider.json")
    if target.exists(): raise ValueError("PLAN raw audit response already exists; refusing overwrite")
    temporary = target.with_suffix(".pending")
    raw = resp.model_dump(mode="json")
    with temporary.open("x",encoding="utf-8") as stream:
        json.dump(raw,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,target)
    return str(target), {"id":raw.get("id"),"stop_reason":raw.get("stop_reason"),"usage":raw.get("usage"),
            "content_block_types":[b.get("type") for b in raw.get("content",[])],
            "raw_response_sha256":hashlib.sha256(target.read_bytes()).hexdigest()}


def complete(system: str, user, model: str, max_tokens: int, temperature: float,
             provider: str = "anthropic", effort: str | None = None, cache_system: bool = False,
             cache_ttl: str = "5m", trace: dict | None = None, response_schema: dict | None = None) -> LLMResponse:
    """Streams the request (so large max_tokens never hits the SDK's non-streaming timeout) and
    returns the final message. Thinking counts toward max_tokens; `effort` (per agent in
    pipeline.yaml) controls how much of it is spent. Prompt caching: `cache_system` marks the system
    prompt, and user blocks with "cache": True are marked too (the prefix up to each mark is cached)."""
    kwargs = message_params(system, user, model, max_tokens, temperature, effort, cache_system, cache_ttl, trace,
                            response_schema)
    with _get_client().messages.stream(**kwargs) as s:
        resp = s.get_final_message()
    private_path = metadata = None
    if ((trace or {}).get("agent") == "A07-SYN" and str((trace or {}).get("step", "")).endswith("_PLAN")) or (
            (config.load("pipeline")["providers"]["anthropic"].get("writing_response_audit_dir")
             or config.load("pipeline")["providers"]["anthropic"].get("plan_response_audit_dir"))
            and (trace or {}).get("agent") in {"A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI"}):
        private_path, metadata = _preserve_plan_response(resp, trace)
    result = parse_message(resp, model)
    result.raw_provider_response_path = private_path
    result.provider_response_metadata = metadata
    return result


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
