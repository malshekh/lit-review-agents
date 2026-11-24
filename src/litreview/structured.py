"""Provider structured outputs, used only for combinations a live smoke test has confirmed.

Structured output makes the provider return JSON of the right shape: required keys, types and enumerations. It
does not enforce length or count limits, patterns or conditionals, and it does not apply when the model refuses
or the reply is cut at the token limit. So it complements the local validator and never replaces it: every reply
is still validated against the complete schema, and scientific validation is untouched.

A schema a provider rejects fails the request. That cannot be found out offline, so nothing here is switched on
by configuration alone: a (provider, model, schema) combination is used only after `litreview smoke-test` has
sent one tiny request with exactly that schema and recorded that the provider accepted it
(records/structured_output.json). Until then the call is made as before (JSON mode plus the local validator).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import config
from .paths import RECORDS_DIR, SCHEMAS_DIR
from .tools import contract

RECORD = RECORDS_DIR / "structured_output.json"
MODE_SCHEMAS = {
    "A07-SYN": ["A07-SYN.bounded-plan.schema.json", "A07-SYN.bounded-group.schema.json",
                "A07-SYN.bounded-reconcile.schema.json", "A07-SYN.bounded-final.schema.json"],
    "A09-WRI": ["A09-WRI.section.schema.json", "A09-WRI.front.schema.json"],
    "A10-RV": ["A10-RV.bounded.schema.json"],
    "A12-EDI": ["A12-EDI.schema.json", "A12-EDI.unit.schema.json"],
}


def schema_files(agent_id: str) -> list[str]:
    from .agents.registry import AGENTS
    return MODE_SCHEMAS.get(agent_id) or [AGENTS[agent_id].schema_file]


def slim(schema_file: str) -> tuple[dict, str]:
    """(the schema in structured-output form, its SHA-256)."""
    schema = json.loads((SCHEMAS_DIR / schema_file).read_text(encoding="utf-8"))
    out, _ = contract.for_structured_output(schema)
    return out, hashlib.sha256(json.dumps(out, sort_keys=True).encode("utf-8")).hexdigest()


def _key(provider: str, model: str, sha: str) -> str:
    return f"{provider}|{model}|{sha}"


def verified(path: Path | None = None) -> dict:
    p = path or RECORD
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def enabled(provider: str) -> bool:
    return (config.load("pipeline")["providers"].get(provider) or {}).get("structured_output") == "json_schema"


def response_schema(agent_id: str, schema_file: str | None, provider: str, model: str) -> dict | None:
    """{"name", "schema"} when this exact combination has passed the smoke test; otherwise None."""
    from .agents.registry import AGENTS
    if not enabled(provider):
        return None
    name = schema_file or AGENTS[agent_id].schema_file
    schema, sha = slim(name)
    entry = verified().get(_key(provider, model, sha))
    if not entry or not entry.get("accepted"):
        return None
    return {"name": name.replace(".schema.json", "").replace(".", "_").replace("-", "_")[:60], "schema": schema}


def targets() -> list[dict]:
    """Every (agent, schema) the configured primary models would use, for the smoke test."""
    from .agents.registry import AGENTS
    out, seen = [], set()
    for agent in AGENTS:
        m = config.agent_model(agent)
        if not enabled(m.provider):
            continue
        for name in schema_files(agent):
            schema, sha = slim(name)
            if (m.provider, m.model, sha) in seen:
                continue
            seen.add((m.provider, m.model, sha))
            out.append({"agent": agent, "provider": m.provider, "model": m.model, "effort": m.effort,
                        "schema_file": name, "schema": schema, "schema_sha256": sha,
                        "already_verified": bool(verified().get(_key(m.provider, m.model, sha), {}).get("accepted"))})
    return out


def record(provider: str, model: str, sha: str, accepted: bool, detail: str, path: Path | None = None) -> None:
    p = path or RECORD
    table = verified(p)
    table[_key(provider, model, sha)] = {"accepted": accepted, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                         "detail": detail[:300]}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")


SMOKE_SYSTEM = ("This is a connectivity check. Return the smallest JSON object that fits the required output format: "
                "empty arrays where allowed, one-word strings, zero for numbers. No scientific content.")
SMOKE_MAX_TOKENS = 1500


def smoke_estimate(budget) -> tuple[float, list[dict]]:
    """(worst-case USD of the smoke test, the targets still to verify). Input counted as bytes; output at the cap."""
    todo = [t for t in targets() if not t["already_verified"]]
    usd = 0.0
    for t in todo:
        tokens = len(SMOKE_SYSTEM.encode()) + len(json.dumps(t["schema"]).encode()) + 200
        usd += budget.cost(t["model"], tokens, SMOKE_MAX_TOKENS) or 0.0
    return usd, todo


def recover_smoke_receipts(budget) -> None:
    """Settle received calls exactly once; an uncertain dispatch retains its reservation and stops."""
    for p in sorted((budget.log_path.parent / "smoke_receipts").glob("*.json")):
        receipt = json.loads(p.read_text(encoding="utf-8"))
        key = receipt["reservation"]
        if receipt["state"] != "RECEIVED":
            continue
        if not any(e["step"] == key for e in budget.entries()):
            budget.record("smoke-test", receipt["provider"], receipt["model"],
                          receipt["input_tokens"], receipt["output_tokens"], step=key, reservation_key=key)
        try:
            accepted = isinstance(json.loads(receipt["text"]), dict)
        except (ValueError, TypeError):
            accepted = False
        record(receipt["provider"], receipt["model"], receipt["schema_sha256"], accepted, "recovered persisted receipt")
        budget.release(key)


def smoke_test(budget, approve_usd: float, by: str, log_path: Path | None = None) -> dict:
    """One tiny live request per unverified combination. Refused unless its worst case fits the approved amount.
    Records what each provider accepted; a rejected schema is recorded too, so it is never tried in a paid stage."""
    from .llm import complete
    recover_smoke_receipts(budget)
    if any(k.startswith("smoke-") for k in budget.reservations()):
        raise ValueError("unsettled smoke receipt: reconcile smoke_receipts and reservations before retrying; no call sent")
    usd, todo = smoke_estimate(budget)
    if not (by or "").strip():
        raise ValueError("a live smoke test needs the name of the person who approved it")
    if usd > approve_usd:
        raise ValueError(f"the smoke test's worst case is ${usd:.2f}, over the approved ${approve_usd:.2f}")
    results = []
    log = log_path or budget.log_path.parent / "smoke_tests.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    for t in todo:
        import uuid
        budget.check_priced(t["model"])
        worst_input = len(SMOKE_SYSTEM.encode()) + len(json.dumps(t["schema"]).encode()) + 200
        worst = budget.cost(t["model"], worst_input, SMOKE_MAX_TOKENS)
        key = "smoke-" + uuid.uuid4().hex
        ok, room = budget.reserve(key, worst, "smoke-test", "live schema check; uncertain calls retain reservation")
        if not ok:
            raise ValueError(f"smoke test exceeds combined run allowance (${room:.4f} available)")
        receipt = budget.log_path.parent / "smoke_receipts" / (key + ".json")
        receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps({"state": "DISPATCHED", "reservation": key, "target": t["schema_file"]}))
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "approved_by": by.strip(),
               **{k: t[k] for k in ("agent", "provider", "model", "schema_file", "schema_sha256")}}
        try:
            resp = complete(t["provider"], system=SMOKE_SYSTEM, user="Return the object now.", model=t["model"],
                            max_tokens=SMOKE_MAX_TOKENS, temperature=0.0, effort=t["effort"],
                            response_schema={"name": "smoke", "schema": t["schema"]},
                            trace={"agent": "smoke-test", "step": t["schema_file"]})
            receipt.write_text(json.dumps({"state": "RECEIVED", "reservation": key,
                "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                "provider": t["provider"], "model": t["model"], "schema_sha256": t["schema_sha256"], "text": resp.text}))
            budget.record("smoke-test", t["provider"], t["model"], resp.input_tokens, resp.output_tokens,
                          step=key, reservation_key=key)
            row.update(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                       cost_usd=budget.cost(t["model"], resp.input_tokens, resp.output_tokens))
            parsed = isinstance(json.loads(resp.text), dict)
            row.update(accepted=parsed, stop_reason=resp.stop_reason, input_tokens=resp.input_tokens,
                       output_tokens=resp.output_tokens,
                       cost_usd=budget.cost(t["model"], resp.input_tokens, resp.output_tokens))
            record(t["provider"], t["model"], t["schema_sha256"], parsed, f"stop_reason {resp.stop_reason}")
        except Exception as exc:   # noqa: BLE001 — the point of the test is to learn what each provider does with the schema
            row.update(accepted=False, error=f"{type(exc).__name__}: {str(exc)[:300]}")
            record(t["provider"], t["model"], t["schema_sha256"], False, row["error"])
        if any(e["step"] == key for e in budget.entries()):
            budget.release(key)
        results.append(row)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    return {"tested": len(results), "accepted": sum(r["accepted"] for r in results),
            "spent_usd": round(sum(r.get("cost_usd") or 0 for r in results), 4), "results": results}
