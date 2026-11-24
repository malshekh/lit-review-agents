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
import os
import time
from pathlib import Path

from . import config
from .paths import RECORDS_DIR, SCHEMAS_DIR
from .tools import contract
from . import smoke_validation

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


def slim(schema_file: str, provider: str = "anthropic") -> tuple[dict, str]:
    """(the schema in structured-output form, its SHA-256)."""
    submitted_file = "A05-KE.anthropic.schema.json" if schema_file == "A05-KE.schema.json" and provider == "anthropic" else schema_file
    schema = json.loads((SCHEMAS_DIR / submitted_file).read_text(encoding="utf-8"))
    out, _ = contract.for_structured_output(schema, provider)
    return out, hashlib.sha256(json.dumps(out, sort_keys=True).encode("utf-8")).hexdigest()


def _key(provider: str, model: str, sha: str) -> str:
    return f"{provider}|{model}|{sha}"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _error_text(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for provider in config.load("pipeline")["providers"].values():
        secret = os.environ.get(provider.get("key_env", ""))
        if secret:text = text.replace(secret, "[REDACTED]")
    return text[:1000]


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
    schema, sha = slim(name, provider)
    entry = verified().get(_key(provider, model, sha))
    if not entry or not entry.get("accepted") or entry.get("validation_version") != smoke_validation.VERSION:
        return None
    return {"name": name.replace(".schema.json", "").replace(".", "_").replace("-", "_")[:60], "schema": schema}


def schema_inventory() -> list[dict]:
    """Audit every configured strict provider schema, collecting every blocker rather than stopping at the first."""
    from .agents.registry import AGENTS
    from .tools.structured_contract import SchemaCompatibilityError
    rows = []
    for agent in AGENTS:
        model = config.agent_model(agent)
        if not enabled(model.provider):continue  # JSON-object providers receive no schema; full local validation still applies.
        for name in schema_files(agent):
            try:
                shape, digest = slim(name, model.provider)
                rows.append({"provider":model.provider,"model":model.model,"schema_file":name,"schema_sha256":digest,"problems":[]})
            except SchemaCompatibilityError as exc:
                rows.append({"provider":model.provider,"model":model.model,"schema_file":name,"problems":str(exc).split("; ")})
    return rows


def targets() -> list[dict]:
    """Every (agent, schema) the configured primary models would use, for the smoke test."""
    from .agents.registry import AGENTS
    inventory = schema_inventory()
    failures = [r for r in inventory if r["problems"]]
    if failures:
        from .tools.structured_contract import SchemaCompatibilityError
        raise SchemaCompatibilityError("configured schemas incompatible: " + "; ".join(r["schema_file"] + ": " + ", ".join(r["problems"]) for r in failures))
    out, seen = [], set()
    for agent in AGENTS:
        m = config.agent_model(agent)
        if not enabled(m.provider):
            continue
        for name in schema_files(agent):
            schema, sha = slim(name, m.provider)
            if (m.provider, m.model, sha) in seen:
                continue
            seen.add((m.provider, m.model, sha))
            out.append({"agent": agent, "provider": m.provider, "model": m.model, "effort": m.effort,
                        "schema_file": name, "schema": schema, "schema_sha256": sha,
                        "already_verified": bool(verified().get(_key(m.provider, m.model, sha), {}).get("accepted") and verified().get(_key(m.provider, m.model, sha), {}).get("validation_version") == smoke_validation.VERSION)})
    return out


def record(provider: str, model: str, sha: str, accepted: bool, detail: str, path: Path | None = None, validation: dict | None = None) -> None:
    p = path or RECORD
    table = verified(p)
    table[_key(provider, model, sha)] = {"accepted": accepted, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                         "detail": detail[:300], **(validation or {})}
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_json(p, table)


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
    accepted_receipts = set()
    for p in sorted((budget.log_path.parent / "smoke_receipts").glob("*.json")):
        receipt = json.loads(p.read_text(encoding="utf-8"))
        key = receipt["reservation"]
        if receipt["state"] != "RECEIVED":
            continue
        if not any(e["step"] == key for e in budget.entries()):
            budget.record("smoke-test", receipt["provider"], receipt["model"],
                          receipt["input_tokens"], receipt["output_tokens"], step=key, reservation_key=key)
        enrichment_path = budget.log_path.parent / "smoke_receipt_enrichment.json"
        enrichment = json.loads(enrichment_path.read_text(encoding="utf-8")) if enrichment_path.exists() else {}
        _, validation = smoke_validation.receipt_evidence(p, enrichment)
        extra = enrichment.get(validation.get("receipt_sha256"), {})
        name = receipt.get("schema_file", extra.get("schema_file"))
        if name:
            try:
                _, current_hash = slim(name, receipt["provider"])
                if current_hash != receipt["schema_sha256"]:
                    validation["accepted"] = False
                    validation["problems"].append("actual submitted schema changed; retest required")
            except (ValueError, OSError) as exc:
                validation["accepted"] = False
                validation["problems"].append("current provider contract incompatible; no approval retained")
        identity = _key(receipt["provider"], receipt["model"], receipt["schema_sha256"])
        # UUID filename order is not chronology. An invalid receipt cannot erase a separately
        # validated success for the identical current provider/model/schema.
        if validation["accepted"] or identity not in accepted_receipts:
            record(receipt["provider"], receipt["model"], receipt["schema_sha256"], validation["accepted"],
                   "reassessed persisted receipt", validation=validation)
        if validation["accepted"]:
            accepted_receipts.add(identity)
        budget.release(key)


SETTLEABLE = ("DISPATCHED", "ERROR_RESPONSE")


def unsettled_smoke_holds(budget) -> list[dict]:
    """Smoke reservations still held, each with its receipt (state, provider, request ID) when one exists."""
    out = []
    for key, res in sorted(budget.reservations().items()):
        if not key.startswith("smoke-"):
            continue
        path = budget.log_path.parent / "smoke_receipts" / f"{key}.json"
        receipt = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        out.append({"reservation": key, "held_usd": res.get("usd"), "reserved_at": res.get("reserved_at"),
                    "state": receipt.get("state", "NO_RECEIPT"),
                    **{k: receipt.get(k) for k in ("provider", "model", "target", "schema_file", "http_status",
                                                   "provider_request_id", "error") if receipt.get(k) is not None}})
    return out


def settle_smoke_hold(budget, reservation: str, billed_usd: float, evidence: str, by: str,
                      provider_request_id: str | None = None, provider: str | None = None,
                      model: str | None = None) -> dict:
    """Settle one uncertain smoke dispatch (no reply, or an HTTP error) on the researcher's attestation of what the
    provider actually billed. Nothing is assumed free: the billed amount and the evidence it rests on (for example
    the provider console's usage for that request's time window) are required and kept. The amount is logged as a
    cost entry (zero included, so the resolution is visible in the cost log), the receipt records the settlement,
    and only then is the reservation released."""
    if not (by or "").strip():
        raise ValueError("settling a hold needs the name of the person attesting the billed amount")
    if not (evidence or "").strip():
        raise ValueError("settling a hold needs the billing evidence (what shows the billed amount); nothing is assumed")
    try:
        billed = float(billed_usd)
    except (TypeError, ValueError):
        raise ValueError("the billed amount must be a number of US dollars") from None
    if billed < 0 or billed != billed:
        raise ValueError("the billed amount cannot be negative")
    held = budget.reservations().get(reservation)
    if not reservation.startswith("smoke-") or held is None:
        raise ValueError(f"{reservation} is not a held smoke reservation of this run")
    path = budget.log_path.parent / "smoke_receipts" / f"{reservation}.json"
    if not path.exists():
        raise ValueError(f"no receipt for {reservation}: reconcile it by hand before settling")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("state") not in SETTLEABLE:
        raise ValueError(f"receipt {reservation} is {receipt.get('state')}; only an uncertain dispatch "
                         f"({' or '.join(SETTLEABLE)}) is settled by attestation")
    known_id = receipt.get("provider_request_id")
    if provider_request_id and known_id and provider_request_id != known_id:
        raise ValueError(f"request ID {provider_request_id} differs from the receipt's {known_id}")
    if any(e.get("step") == reservation for e in budget.entries()):
        raise ValueError(f"{reservation} already has a cost entry; inspect costs.jsonl before settling")
    for name, given in (("provider", provider), ("model", model)):
        if given and receipt.get(name) and given != receipt[name]:
            raise ValueError(f"{name} {given} differs from the receipt's {receipt[name]}")
    provider, model = receipt.get("provider") or provider, receipt.get("model") or model
    if not provider or not model:
        raise ValueError("the receipt does not name the provider and model; give them (--provider, --model) "
                         "from the smoke log of that dispatch")
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    settlement = {"billed_usd": round(billed, 6), "held_usd": held.get("usd"), "evidence": evidence.strip(),
                  "attested_by": by.strip(), "settled_at": at, "provider": provider, "model": model,
                  "provider_request_id": provider_request_id or known_id, "previous_state": receipt.get("state")}
    entry = {"time": at, "agent": "smoke-test", "step": reservation, "started_at": None, "provider": provider,
             "model": model, "input_tokens": 0, "cached_input_tokens": 0, "cache_write_tokens": 0,
             "cache_write_1h_tokens": 0, "output_tokens": 0, "cost_usd": round(billed, 6),
             "cost_parts_usd": {"attested": round(billed, 6)}, "reservation_key": reservation,
             "attested_settlement": {k: settlement[k] for k in ("evidence", "attested_by", "provider_request_id")}}
    with open(budget.log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    _write_json(path, {**receipt, "state": "SETTLED_BY_ATTESTATION", "billing_status": "SETTLED_BY_ATTESTATION",
                       "settlement": settlement})
    with open(budget.log_path.parent / "smoke_settlements.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"reservation": reservation, **settlement}) + "\n")
    budget.release(reservation)
    return {"reservation": reservation, **settlement}


def smoke_test(budget, approve_usd: float, by: str, log_path: Path | None = None, *, retained_hold_authorization: Path | None = None) -> dict:
    """One tiny live request per unverified combination. Refused unless its worst case fits the approved amount.
    Records what each provider accepted; a rejected schema is recorded too, so it is never tried in a paid stage."""
    from .llm import complete
    recover_smoke_receipts(budget)
    from .retained_hold import blocking_holds
    if blocking_holds(budget, retained_hold_authorization):
        raise ValueError("unsettled smoke receipt: settle it on billing evidence first (litreview settle-smoke-hold "
                         "<run_id>); no call sent")
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
        _write_json(receipt, {"state": "DISPATCHED", "reservation": key, "target": t["schema_file"], "provider": t["provider"], "model": t["model"],
                                     "submitted_schema": t["schema"], "schema_sha256": t["schema_sha256"]})
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "approved_by": by.strip(),
               **{k: t[k] for k in ("agent", "provider", "model", "schema_file", "schema_sha256")}}
        try:
            resp = complete(t["provider"], system=SMOKE_SYSTEM, user="Return the object now.", model=t["model"],
                            max_tokens=SMOKE_MAX_TOKENS, temperature=0.0, effort=t["effort"],
                            response_schema={"name": "smoke", "schema": t["schema"]},
                            trace={"agent": "smoke-test", "step": t["schema_file"]})
            _write_json(receipt, {"state": "RECEIVED", "reservation": key,
                "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                "provider": t["provider"], "model": t["model"], "schema_sha256": t["schema_sha256"], "text": resp.text,
                "submitted_schema": t["schema"], "stop_reason": resp.stop_reason, "schema_file": t["schema_file"], "response_provider": resp.provider, "response_model": resp.model})
            budget.record("smoke-test", t["provider"], t["model"], resp.input_tokens, resp.output_tokens,
                          step=key, reservation_key=key)
            row.update(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                       cost_usd=budget.cost(t["model"], resp.input_tokens, resp.output_tokens))
            validation = smoke_validation.inspect_response(t["provider"], resp.text, resp.stop_reason, t["schema"], t["schema_sha256"])
            if (resp.provider, resp.model) != (t["provider"], t["model"]):
                validation["accepted"] = False
                validation["problems"].append("response provider/model differs from submitted request")
            parsed = validation["accepted"]
            row.update(accepted=parsed, stop_reason=resp.stop_reason, input_tokens=resp.input_tokens,
                       output_tokens=resp.output_tokens,
                       cost_usd=budget.cost(t["model"], resp.input_tokens, resp.output_tokens))
            record(t["provider"], t["model"], t["schema_sha256"], parsed, f"stop_reason {resp.stop_reason}", validation=validation)
        except Exception as exc:   # noqa: BLE001 — the point of the test is to learn what each provider does with the schema
            row.update(accepted=False, error=_error_text(exc))
            if getattr(exc, "status_code", None) is not None:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
                if saved["state"] == "DISPATCHED":
                    saved.update(state="ERROR_RESPONSE", http_status=exc.status_code,
                                 provider_request_id=getattr(exc, "request_id", None), error=row["error"],
                                 billing_status="UNRECONCILED; no zero-cost assumption")
                    _write_json(receipt, saved)
            record(t["provider"], t["model"], t["schema_sha256"], False, row["error"])
        if any(e["step"] == key for e in budget.entries()):
            budget.release(key)
        results.append(row)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        if not row["accepted"]:
            break  # Preserve failure evidence; no further dispatch until reviewed.
    return {"tested": len(results), "accepted": sum(r["accepted"] for r in results),
            "spent_usd": round(sum(r.get("cost_usd") or 0 for r in results), 4), "results": results}
