"""Vendor batch APIs: Anthropic Message Batches and OpenAI Batch (Chat Completions).

Docs: https://platform.claude.com/docs/en/build-with-claude/batch-processing
      https://developers.openai.com/api/docs/guides/batch
Each request is built by the same function the interactive client uses (anthropic_client.message_params,
openai_compatible.chat_params) and each result parsed by the same parser, so a batched call and an
interactive call differ only in transport and price. Both vendors process within 24 hours (Anthropic: most
batches under an hour) and return partial results on expiry; unfinished items are reported, not lost.
Results are kept 29 days (Anthropic) or 30 days (OpenAI), so a stopped run can reattach by batch ID.

Batch creation is never retried by the SDK (max_retries=0): a create that timed out may still have created
the batch, and an automatic retry would create and bill a second one. A failed create leaves the caller's
intent record, which is resolved by identity (input_sha256, result_ids), never by resubmitting.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from . import anthropic_client, openai_compatible
from .base import LLMResponse

PROVIDERS = ("anthropic", "openai")   # Kimi has no batch endpoint here: its agents run interactively


@dataclass
class ItemResult:
    custom_id: str
    status: str                       # succeeded | errored | expired | canceled
    response: LLMResponse | None = None
    error: str | None = None
    retryable: bool = False           # errored for a server reason, or expired/canceled: safe to resubmit


def request(provider: str, custom_id: str, system: str, user, model: str, max_tokens: int, temperature: float,
            effort: str | None = None, cache_system: bool = False, cache_ttl: str = "5m") -> dict:
    if provider == "anthropic":
        return {"custom_id": custom_id, "params": anthropic_client.message_params(
            system, user, model, max_tokens, temperature, effort, cache_system, cache_ttl)}
    if provider == "openai":
        return {"custom_id": custom_id, "method": "POST", "url": "/v1/chat/completions",
                "body": openai_compatible.chat_params(system, user, model, max_tokens, temperature, provider)}
    raise ValueError(f"no batch support for provider '{provider}'")


def manifest(requests: list[dict]) -> bytes:
    """The frozen request manifest: the exact JSONL bytes uploaded to OpenAI, hashed for identity on both."""
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in requests).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upload(provider: str, data: bytes) -> str | None:
    """OpenAI: upload the manifest as the JSONL input file (no cost, creates no batch). Anthropic: nothing."""
    if provider != "openai":
        return None
    return openai_compatible._get_client("openai").files.create(file=("batch.jsonl", data), purpose="batch").id


def create(provider: str, requests: list[dict], input_file_id: str | None = None,
           metadata: dict | None = None) -> str:
    """Create the batch, once. OpenAI carries the submission fingerprint as batch metadata; Anthropic batches
    have no metadata, so there the fingerprint lives in the custom_ids."""
    if provider == "anthropic":
        client = anthropic_client._get_client().with_options(max_retries=0, timeout=600)
        return client.messages.batches.create(requests=requests).id
    client = openai_compatible._get_client("openai").with_options(max_retries=0, timeout=600)
    return client.batches.create(input_file_id=input_file_id, endpoint="/v1/chat/completions",
                                 completion_window="24h", metadata=metadata or {}).id


def status(provider: str, batch_id: str) -> dict:
    """{"done": bool, "status": vendor status, "counts": {...}}."""
    if provider == "anthropic":
        b = anthropic_client._get_client().messages.batches.retrieve(batch_id)
        return {"done": b.processing_status == "ended", "status": b.processing_status,
                "counts": b.request_counts.model_dump()}
    b = openai_compatible._get_client("openai").batches.retrieve(batch_id)
    return {"done": b.status in ("completed", "expired", "failed", "cancelled"), "status": b.status,
            "counts": b.request_counts.model_dump() if b.request_counts else {}}


def results(provider: str, batch_id: str, model: str) -> list[ItemResult]:
    if provider == "anthropic":
        out = []
        for r in anthropic_client._get_client().messages.batches.results(batch_id):
            t = r.result.type
            if t == "succeeded":
                out.append(ItemResult(r.custom_id, t, anthropic_client.parse_message(r.result.message, model)))
            else:
                err = getattr(getattr(getattr(r.result, "error", None), "error", None), "type", None)
                out.append(ItemResult(r.custom_id, t, error=f"{t}: {err or ''}".strip(": "),
                                      retryable=t in ("expired", "canceled") or err != "invalid_request_error"))
        return out
    client = openai_compatible._get_client("openai")
    b = client.batches.retrieve(batch_id)
    out = []
    for file_id in (b.output_file_id, b.error_file_id):
        if not file_id:
            continue
        for line in client.files.content(file_id).text.splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            resp, err = r.get("response") or {}, r.get("error") or {}
            if resp.get("status_code") == 200:
                out.append(ItemResult(r["custom_id"], "succeeded",
                                      openai_compatible.parse_completion(resp["body"], "openai", model)))
            else:
                code = err.get("code") or (resp.get("body") or {}).get("error", {}).get("code") or resp.get("status_code")
                expired = code == "batch_expired"
                out.append(ItemResult(r["custom_id"], "expired" if expired else "errored", error=str(code),
                                      retryable=expired or (isinstance(resp.get("status_code"), int)
                                                            and resp["status_code"] >= 500)))
    return out


def recent(provider: str, since: float, max_rows: int = 2000) -> tuple[list[dict], bool]:
    """Batches created at or after `since` (epoch), newest first, paging as far back as needed:
    ([{id, created_at, total, input_file_id, metadata}], covered). `covered` is True only if the listing
    reached a batch older than `since` or its end, so an empty result is proof of absence, not a short page."""
    if provider == "anthropic":
        listing = anthropic_client._get_client().messages.batches.list(limit=100)
    else:
        listing = openai_compatible._get_client("openai").batches.list(limit=100)
    rows = []
    for b in listing:   # the SDK pages automatically
        if provider == "anthropic":
            c = b.request_counts
            row = {"id": b.id, "created_at": b.created_at.timestamp(), "input_file_id": None, "metadata": None,
                   "total": c.processing + c.succeeded + c.errored + c.canceled + c.expired}
        else:
            row = {"id": b.id, "created_at": float(b.created_at), "input_file_id": b.input_file_id,
                   "metadata": dict(b.metadata or {}), "total": b.request_counts.total if b.request_counts else None}
        if row["created_at"] < since:
            return rows, True
        rows.append(row)
        if len(rows) >= max_rows:
            return rows, False
    return rows, True


def input_sha256(input_file_id: str) -> str:
    """OpenAI: the hash of a batch's input file as the vendor holds it."""
    return sha256(openai_compatible._get_client("openai").files.content(input_file_id).content)


def result_ids(provider: str, batch_id: str) -> list[str] | None:
    """Anthropic: the custom_ids a batch actually processed, available once it has ended (None before)."""
    client = anthropic_client._get_client()
    if client.messages.batches.retrieve(batch_id).processing_status != "ended":
        return None
    return [r.custom_id for r in client.messages.batches.results(batch_id)]
