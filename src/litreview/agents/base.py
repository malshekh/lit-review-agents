"""Run one agent call: build the prompt, call the model, parse and validate JSON, log cost and provenance.

System prompt = prompts/shared/core_rules.md
              + prompts/shared/language_policy.md   (writing-side agents only)
              + prompts/agents/<agent>.md
User message  = the task payload as JSON.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import jsonschema

from .. import config
from ..budget import BudgetTracker
from ..llm import complete
from ..paths import AGENT_PROMPTS_DIR, SCHEMAS_DIR, SHARED_PROMPTS_DIR
from ..provenance import ProvenanceLog
from .registry import AGENTS


class AgentError(RuntimeError):
    pass


class RefusalError(AgentError):
    """The model declined for policy reasons. Never retried; the orchestrator records it and reroutes."""

    def __init__(self, message: str, model: str, category: str | None):
        super().__init__(message)
        self.model, self.category = model, category


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def prompt_version(agent_id: str) -> str:
    text = _read(AGENT_PROMPTS_DIR / AGENTS[agent_id].prompt_file)
    m = re.search(r"Version:\s*([0-9.]+)", text)
    return m.group(1) if m else "unknown"


def build_system_prompt(agent_id: str) -> str:
    spec = AGENTS[agent_id]
    parts = [_read(SHARED_PROMPTS_DIR / "core_rules.md")]
    if spec.uses_language_policy:
        parts.append(_read(SHARED_PROMPTS_DIR / "language_policy.md"))
    parts.append(_read(AGENT_PROMPTS_DIR / spec.prompt_file))
    return "\n\n---\n\n".join(parts)


def parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating Markdown fences or stray text around it."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def validate(agent_id: str, output: dict, schema_file: str | None = None) -> None:
    schema_path = SCHEMAS_DIR / (schema_file or AGENTS[agent_id].schema_file)
    schema = json.loads(_read(schema_path))
    jsonschema.validate(output, schema)


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))   # compact: large payloads near context limits


def user_parts(payload: dict, cache_keys: tuple[str, ...] = ()) -> list[dict]:
    """The user message as text blocks. With cache_keys, those payload keys go first in their own
    cacheable block (e.g. the paper, reread by a repair call) and the rest follow uncached."""
    if '_a06_shared_prefix' in payload:
        from ..a06_request import parts
        return parts(payload)
    head = {k: payload[k] for k in cache_keys if k in payload}
    if not head:
        return [{"text": _json(payload), "cache": False}]
    rest = {k: v for k, v in payload.items() if k not in head}
    return [{"text": "Task inputs, part 1 of 2 (JSON):\n" + _json(head), "cache": True},
            {"text": "Task inputs, part 2 of 2 (JSON):\n" + _json(rest), "cache": False}]


REPAIR_SYSTEM = (
    "You repair the FORMAT of a JSON document. You are given a JSON Schema, a document that failed it, and the "
    "validator's error. Return the same document, corrected only as far as the schema requires: fix structure, "
    "types, missing required keys whose value is already determined by the document, enumerations, and length or "
    "count limits. Do not add, remove, reword or reinterpret any scientific content, identifier, number or "
    "citation. If a limit forces you to shorten a text, keep its meaning and every identifier in it. If a required "
    "value cannot be determined from the document itself, set the document's `status` to the schema's failure or "
    "needs-review value if one exists; never invent content. Return only the corrected JSON object.")


def changed_paths(before, after, path: str = "$", limit: int = 200) -> list[str]:
    """JSON paths whose value differs between two documents (for the repair audit; stops at `limit`)."""
    out: list[str] = []

    def walk(a, b, at):
        if len(out) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a or k not in b:
                    out.append(f"{at}.{k} ({'added' if k not in a else 'removed'})")
                else:
                    walk(a[k], b[k], f"{at}.{k}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.append(f"{at} (length {len(a)} -> {len(b)})")
            for n, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{at}[{n}]")
        elif a != b:
            out.append(at)
    walk(before, after, path)
    return out


ID_RE = re.compile(r"\b[A-Z]{1,4}\d+(?::[A-Z]{1,3}\d+)?\b|\[@[^\]]+\]")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.])\d+(?:[.,]\d+)*(?:\s?%)?")


def _tokens(obj) -> tuple[set[str], set[str]]:
    """(identifiers, numbers) found in every string of a JSON document, keys included."""
    ids: set[str] = set()
    numbers: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(str(k))
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            ids.update(ID_RE.findall(x))
            numbers.update(n.replace(" ", "") for n in NUMBER_RE.findall(ID_RE.sub(" ", x)))
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            numbers.add(str(x))
    walk(obj)
    return ids, numbers


def preservation_problems(before, after) -> list[str]:
    """What a format repair lost. A repair may change structure, never evidence: every identifier (finding,
    record, proposition, section, citation) and every number of the original must still be present. A repair
    that drops one is rejected: the task was too large for its limits and must be resized, not shortened."""
    ids_before, numbers_before = _tokens(before)
    ids_after, numbers_after = _tokens(after)
    problems = []
    lost = sorted(ids_before - ids_after)
    if lost:
        problems.append(f"{len(lost)} identifier(s) dropped: {', '.join(lost[:12])}")
    gone = sorted(numbers_before - numbers_after)
    if gone:
        problems.append(f"{len(gone)} numeric value(s) dropped or altered: {', '.join(gone[:12])}")
    invented = sorted(ids_after - ids_before)
    if invented:
        problems.append(f"{len(invented)} identifier(s) not in the original: {', '.join(invented[:12])}")
    return problems


def _not_sent(exc: Exception) -> bool:
    """True when the provider definitely rejected the request before running it (HTTP 4xx other than a timeout):
    nothing was generated and nothing billed. Anything else (timeout, dropped connection, 5xx) is ambiguous."""
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status != 408


def _schema_text(agent_id: str, schema_file: str | None) -> str:
    return _read(SCHEMAS_DIR / (schema_file or AGENTS[agent_id].schema_file))


def repair_message(agent_id: str, schema_file: str | None, bad_text: str, error: str) -> list[dict]:
    """The repair request: the schema, the saved invalid reply and the validator error. The original task input
    (papers, findings, packets) is not resent: a schema failure is a format defect, and resending the input paid
    for the whole call again and invited a fresh, different answer."""
    return [{"text": "JSON Schema:\n" + _schema_text(agent_id, schema_file), "cache": False},
            {"text": "Document that failed the schema:\n" + bad_text, "cache": False},
            {"text": "Validator error:\n" + error + "\nReturn only the corrected JSON object.", "cache": False}]


def _repair_effort(m: config.AgentModel) -> str | None:
    """The lowest effort the provider accepts (pipeline.yaml -> providers.<p>.reasoning_effort.allowed)."""
    if m.provider == "anthropic":
        return "low"
    allowed = ((config.load("pipeline")["providers"].get(m.provider) or {}).get("reasoning_effort") or {}).get("allowed")
    return allowed[0] if allowed else m.effort


def run_agent(agent_id: str, payload: dict, run_dir: Path, step: str,
              budget: BudgetTracker, provenance: ProvenanceLog, model: config.AgentModel | None = None,
              schema_file: str | None = None, reservation_key: str | None = None,
              repair_limit: int | None = None, dispatch_guard=None,
              truncation_retries: int | None = None, repair_from: tuple[str, str] | None = None,
              ledger=None, request_id: str | None = None, loops: dict | None = None) -> dict:
    """Call an agent and return its validated JSON output. Output is saved to runs/<id>/outputs/.
    `model` overrides the agent's configured model (refusal routing, per-call limits); `schema_file`
    overrides its output schema (A07 job turns).

    Every provider reply is saved before it is judged (`<step>.raw<N>.txt`), so nothing paid for is lost.
    Truncation: the partial reply is kept and the same request is sent once more with a larger output cap
    (loops.max_truncation_retries, truncation_retry_factor, max_output_tokens_ceiling). Schema failure: the saved
    reply is repaired from itself (repair_message), not by resending the task input. `dispatch_guard(attempt,
    system, message, model)` runs before every send, the retry and the repair included, and returns the
    reservation that send is held under. `repair_from=(saved reply, validator error)`: skip the primary call
    and repair that saved reply (a batch item that came back invalid; `litreview repair-import --model`)."""
    if agent_id not in AGENTS:
        raise AgentError(f"Unknown agent {agent_id}")
    m = model or config.agent_model(agent_id)
    budget.check_priced(m.model)
    loops = loops if loops is not None else config.load("pipeline")["loops"]   # the run's own limits when given
    max_repairs = int(loops.get("max_json_repair_attempts", 1)) if repair_limit is None else int(repair_limit)
    truncations_left = (int(loops.get("max_truncation_retries", 0)) if truncation_retries is None
                        else int(truncation_retries))
    factor = float(loops.get("truncation_retry_factor", 1.5))
    ceiling = int(loops.get("max_output_tokens_ceiling", 64000))

    system = build_system_prompt(agent_id)
    user = user_parts(payload, m.cache_payload)
    out_dir = Path(run_dir) / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{step}.json"
    version = prompt_version(agent_id)

    call_system, message, call_model = system, user, m
    repairing: dict | None = None   # set once the call is a repair of a saved reply
    last_error = ""
    attempt = 0
    if repair_from is not None:
        bad_text, last_error = repair_from
        try:
            before = parse_json(bad_text)
        except json.JSONDecodeError:
            before = None
        repairing = {"error": last_error, "before": before, "source": "saved reply"}
        call_system, message = REPAIR_SYSTEM, repair_message(agent_id, schema_file, bad_text, last_error)
        call_model = dataclasses.replace(m, max_tokens=min(int(m.max_tokens), len(bad_text.encode("utf-8")) // 2 + 4000),
                                         cache_system=False, effort=_repair_effort(m))
        max_repairs = 0   # this call is the repair
        attempt = 1       # raw0 is the saved reply
    # A restart: was a call of this step in flight, or answered but not yet accounted? (job_ledger.py)
    recovered = None
    if ledger is not None and repair_from is None:
        from ..job_ledger import AmbiguousDispatch
        kind, event = ledger.recovery(step)
        if kind == "AMBIGUOUS":
            raise AmbiguousDispatch(
                f"{agent_id} ({step}): a request was sent at {event['time']} and no reply was saved. It may have "
                "completed and been billed. It is not resent: check the provider's usage page, then run "
                f"`litreview resolve-dispatch {Path(run_dir).name} {step} --billed|--not-billed --by NAME --note TEXT`.")
        if kind in ("RESUME_SAVED", "RESUME_ACCOUNTED"):
            saved = ledger.load_response(step, event["attempt"])
            request = saved.get("request") or {}
            usable = request.get("kind") != "REPAIR" and request.get("request_id") == request_id and request_id is not None
            if kind == "RESUME_SAVED" and not usable:
                # paid for, but it answers a different request (or was a repair): log its cost, do not use it
                budget.record(agent_id, saved["provider"], saved["model"], saved["input_tokens"], saved["output_tokens"],
                              step=step, cached_input_tokens=saved["cached_input_tokens"],
                              cache_write_tokens=saved["cache_write_tokens"],
                              cache_write_1h_tokens=saved["cache_write_1h_tokens"],
                              **({"reservation_key": request["reservation"]}
                                 if request.get("reservation") in budget.reservations() else {}))
                if request.get("reservation") and request["reservation"] != reservation_key:
                    budget.release(request["reservation"])
                ledger.record(step, event["attempt"], "ACCOUNTED", note="recovered; reply not reusable for this request")
            elif usable:
                recovered, attempt = {**saved, "accounted": kind == "RESUME_ACCOUNTED"}, event["attempt"]
                call_model = dataclasses.replace(m, max_tokens=int(request.get("max_tokens") or m.max_tokens))
    while True:
        if recovered is not None:
            from ..llm.base import LLMResponse
            resp = LLMResponse(**{k: recovered[k] for k in ("text", "provider", "model", "input_tokens", "output_tokens",
                                                            "stop_reason", "refusal_category", "cached_input_tokens",
                                                            "cache_write_tokens", "cache_write_1h_tokens")})
            started, held = None, recovered["request"].get("reservation") or reservation_key
            guarded = held != reservation_key and held in budget.reservations()
            already_accounted = recovered["accounted"]
            provenance.tool_run("recovered_saved_response", step, {"attempt": attempt, "resent": False,
                                                                   "already_accounted": already_accounted})
            recovered = None
        else:
            if reservation_key:
                budget.ensure_headroom(reservation_key)
            else:
                budget.ensure_headroom()
            started = time.time()
            already_accounted = False
            if ledger is not None:
                ledger.record(step, attempt, "PREPARED", model=call_model.model, max_tokens=call_model.max_tokens,
                              kind="REPAIR" if repairing is not None else "PRIMARY", request_id=request_id)
            held = dispatch_guard(attempt, call_system, message, call_model) if dispatch_guard else reservation_key
            guarded = bool(dispatch_guard) and held != reservation_key
            if ledger is not None:
                ledger.record(step, attempt, "RESERVED", reservation=held)
                ledger.record(step, attempt, "DISPATCHED", reservation=held)   # before the send: a crash here is ambiguous
            from .. import structured
            shape = structured.response_schema(agent_id, schema_file, call_model.provider, call_model.model)
            try:
                resp = complete(call_model.provider, system=call_system, user=message, model=call_model.model,
                                max_tokens=call_model.max_tokens, temperature=call_model.temperature,
                                effort=call_model.effort, cache_system=call_model.cache_system,
                                cache_ttl=call_model.cache_ttl, **({"response_schema": shape} if shape else {}),
                                trace={"agent": agent_id, "step": step, "run_id": Path(run_dir).name,
                                       "attempt": attempt, "prompt_version": version})
            except Exception as exc:  # noqa: BLE001 — provider SDKs raise unrelated families; all end the call with a status
                provenance.agent_call(agent_id, step, call_model.model, version, "", "FAILED")
                if _not_sent(exc):   # rejected before it ran: nothing billed, so the hold is given back
                    if ledger is not None:
                        ledger.record(step, attempt, "API_ERROR", error=f"{type(exc).__name__}: {str(exc)[:200]}")
                    if guarded:
                        budget.release(held)
                # otherwise the ledger stays at DISPATCHED: completion is unknown and the hold stays
                raise AgentError(f"{agent_id} ({step}): API error: {type(exc).__name__}: {str(exc)[:400]}") from exc
            if ledger is not None:   # the reply is on disk before anything else can fail
                ledger.save_response(step, attempt, resp, {"kind": "REPAIR" if repairing is not None else "PRIMARY",
                                                           "max_tokens": call_model.max_tokens, "reservation": held,
                                                           "request_id": request_id})
        if not already_accounted:
            budget.record(agent_id, resp.provider, resp.model, resp.input_tokens, resp.output_tokens, step=step,
                          cached_input_tokens=resp.cached_input_tokens, cache_write_tokens=resp.cache_write_tokens,
                          cache_write_1h_tokens=resp.cache_write_1h_tokens, started_at=started,
                          cache_requested=call_model.provider == "anthropic" and (
                              call_model.cache_system or any(p["cache"] for p in message)),
                          prompt_chars=len(call_system) + sum(len(p["text"]) for p in message),
                          **({"reservation_key": held} if (dispatch_guard or guarded) and held else {}))
        if guarded:
            budget.release(held)
        if ledger is not None and not already_accounted:
            ledger.record(step, attempt, "ACCOUNTED")
        if getattr(resp, "provider_response_metadata", None) is not None:
            receipt = {**resp.provider_response_metadata, "private_raw_response_path": resp.raw_provider_response_path}
            (out_dir / f"{step}.provider.receipt{attempt}.json").write_text(json.dumps(receipt, indent=2),
                                                                            encoding="utf-8")
        (out_dir / f"{step}.raw{attempt}.txt").write_text(resp.text, encoding="utf-8")
        if resp.stop_reason == "refusal":
            # a policy decline, not a formatting error: never retried (same model, same request, same answer)
            provenance.agent_call(agent_id, step, resp.model, version, "", "REFUSED")
            if ledger is not None:
                ledger.record(step, attempt, "REFUSED", category=resp.refusal_category)
            raise RefusalError(
                f"{agent_id} ({step}): {resp.model} declined the request (category: "
                f"{resp.refusal_category or 'unspecified'}). Recorded for this topic family; the next run "
                "routes this agent to an alternate in pipeline.yaml -> routing, if one is configured.",
                resp.model, resp.refusal_category)
        if resp.stop_reason in ("max_tokens", "length"):
            cap = int(call_model.max_tokens)
            (out_dir / f"{step}.truncated{attempt}.json").write_text(json.dumps(
                {"attempt": attempt, "max_tokens": cap, "output_tokens": resp.output_tokens,
                 "partial_output": f"{step}.raw{attempt}.txt", "partial_chars": len(resp.text)}, indent=2),
                encoding="utf-8")
            larger = min(int(cap * factor + 0.999), ceiling)
            if ledger is not None:
                ledger.record(step, attempt, "TRUNCATED", max_tokens=cap)
            if truncations_left > 0 and larger > cap:
                truncations_left -= 1
                provenance.tool_run("truncation_retry", step, {"attempt": attempt, "max_tokens": cap,
                                                               "retry_max_tokens": larger})
                call_model = dataclasses.replace(call_model, max_tokens=larger)
                attempt += 1
                continue
            last_error = (f"Output was truncated at max_tokens ({cap}). The partial output is saved as "
                          f"outputs/{step}.raw{attempt}.txt. Increase max_tokens for this call in config/pipeline.yaml.")
            break
        try:
            output = parse_json(resp.text)
            validate(agent_id, output, schema_file)
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            last_error = str(exc)[:2000]
            if ledger is not None:
                ledger.record(step, attempt, "INVALID", error=last_error[:300])
            if max_repairs <= 0:
                break
            max_repairs -= 1
            try:
                before = parse_json(resp.text)
            except json.JSONDecodeError:
                before = None
            repairing = {"error": last_error, "before": before, "source": f"{step}.raw{attempt}.txt"}
            call_system = REPAIR_SYSTEM
            message = repair_message(agent_id, schema_file, resp.text, last_error)
            # a repair rewrites what is already there: room for the document itself, no deep reasoning
            room = min(int(m.max_tokens), len(resp.text.encode("utf-8")) // 2 + 4000)
            call_model = dataclasses.replace(m, max_tokens=room, cache_system=False, effort=_repair_effort(m))
            attempt += 1
            continue
        if repairing is not None and repairing["before"] is not None:
            lost = preservation_problems(repairing["before"], output)
            if lost:   # a repair that loses evidence is not a repair
                (out_dir / f"{step}.repair.rejected.json").write_text(json.dumps(
                    {"problems": lost, "repair_reply": f"{step}.raw{attempt}.txt", "original": repairing["source"]},
                    indent=2), encoding="utf-8")
                if ledger is not None:
                    ledger.record(step, attempt, "REPAIR_REJECTED", problems=lost)
                last_error = ("the format repair was rejected because it did not preserve the original's content ("
                              + "; ".join(lost) + "). The original reply is kept. The task is too large for its "
                              "output limits: resize it (smaller packets) or repair it by hand with `litreview repair-import`.")
                break
        if repairing is not None:
            audit = {"repaired_from": repairing["source"], "validator_error": repairing["error"],
                     "changed_paths": (changed_paths(repairing["before"], output)
                                       if repairing["before"] is not None else ["(original was not parseable JSON)"]),
                     "note": "format repair from the saved reply; the task input was not resent"}
            (out_dir / f"{step}.repair.audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                                                               encoding="utf-8")
            provenance.tool_run("json_repair", step, {"changed_paths": len(audit["changed_paths"]),
                                                      "audit": f"outputs/{step}.repair.audit.json"})
        if ledger is not None:
            ledger.record(step, attempt, "VALIDATED")
        tmp = out_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, out_file)   # atomic: an accepted output is whole or absent
        provenance.agent_call(agent_id, step, m.model, version,
                              str(out_file.relative_to(run_dir)), output.get("status", "UNKNOWN"))
        if ledger is not None:
            ledger.record(step, attempt, "COMMITTED")
        return output

    provenance.agent_call(agent_id, step, m.model, version, "", "FAILED")
    raise AgentError(f"{agent_id} ({step}) failed: {last_error}")
