"""Immutable runtime inventory and narrowly authorized append-only model telemetry.

Run directories are mutable audit state, not immutable source. This verifier never
repairs or discards a mismatch. Its manifest must be pinned outside the runtime.
"""
import hashlib
import math
import re
import json
from pathlib import Path


class IntegrityError(ValueError):
    pass


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _only(rows, description):
    if len(rows) != 1:
        raise IntegrityError(f"Expected one {description}, found {len(rows)}")
    return rows[0]


def _standard_completion(run, event, policy, charges, jobs, seen):
    step = event["step"]
    agent = event["agent"]
    route = policy["routes"].get(agent)
    if (not route or event["outcome"] != "COMPLETED" or event["category"] is not None
            or event["family"] != policy["family"] or event["model"] != route["model"]
            or not re.fullmatch(route["step_pattern"], step) or step in seen):
        raise IntegrityError("Duplicate or unauthorized completion")
    events = [row for row in jobs if row["step"] == step]
    committed = _only([row for row in events if row["state"] == "COMMITTED"], "committed attempt")
    attempt = committed["attempt"]
    if type(attempt) is not int or attempt < 0:
        raise IntegrityError("Invalid attempt number")
    trace = [row for row in events if row["attempt"] == attempt]
    if [r["state"] for r in trace] != ["PREPARED", "RESERVED", "DISPATCHED", "RESPONSE_SAVED",
                                       "ACCOUNTED", "VALIDATED", "COMMITTED"]:
        raise IntegrityError("Incomplete or ambiguous completion trace")
    prepared, reserved, dispatch, saved = trace[:4]
    key = dispatch["reservation"]
    if not key or key != reserved["reservation"]:
        raise IntegrityError("Missing dispatch reservation")
    _only([row for row in jobs if row["state"] == "DISPATCHED" and row.get("reservation") == key], "dispatch")
    charge = _only([row for row in charges if row.get("reservation_key") == key], "ledger charge")
    outputs = run / "outputs"
    path = outputs / f"{step}.response{attempt}.json"
    if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()):
        raise IntegrityError("Receipt escaped run")
    response = json.loads(path.read_bytes())
    req = response["request"]
    if (req["reservation"] != key or not prepared["request_id"] or req["request_id"] != prepared["request_id"]
            or req["kind"] != prepared["kind"] or req["max_tokens"] != prepared["max_tokens"]
            or any(charge[k] != event[k] for k in ("model", "agent", "step"))
            or response["model"] != prepared["model"] or prepared["model"] != event["model"]
            or response["provider"] != route["provider"] or charge["provider"] != route["provider"]
            or response["refusal_category"] is not None or response["stop_reason"] not in ("stop", "end_turn")
            or saved["output_tokens"] != response["output_tokens"] or not response["text"]
            or (outputs / f"{step}.raw{attempt}.txt").read_text(encoding="utf-8") != response["text"].replace("\r\n","\n")
            or not math.isfinite(charge["cost_usd"]) or charge["cost_usd"] < 0
            or not math.isclose(sum(charge["cost_parts_usd"].values()),charge["cost_usd"],abs_tol=0.000003)
            or any(response[k] != charge[k] for k in ("input_tokens", "output_tokens", "cached_input_tokens",
                                                       "cache_write_tokens", "cache_write_1h_tokens"))):
        raise IntegrityError("Receipt and charge do not match dispatch")
    seen.add(step)

def verify(root, manifest):
    root = Path(root).resolve()
    immutable = manifest["files"]
    mutable = {"records/model_record.jsonl"}
    def safe(relative):
        p = root / relative
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise IntegrityError("Inventory path escapes runtime")
        return p
    for relative, expected in immutable.items():
        p = safe(relative)
        if not p.is_file() or sha(p) != expected:
            raise IntegrityError("Immutable file changed: " + relative)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and "runs" not in p.relative_to(root).parts[:1]}
    if actual - set(immutable) - mutable - {"frozen_runtime_manifest.json"}:
        raise IntegrityError("Unexpected runtime file")
    spec = manifest["mutable_telemetry"]
    seed = safe(spec["baseline"]).read_bytes()
    raw = safe("records/model_record.jsonl").read_bytes()
    if not raw.startswith(seed) or (raw and not raw.endswith(b"\n")):
        raise IntegrityError("Telemetry prefix changed or incomplete append")
    policy = spec.get("standard_completions")
    if policy:
        if spec["baseline"] not in immutable:
            raise IntegrityError("Standard telemetry requires an immutable baseline")
        prior = raw[:policy["inherited_bytes"]]
        if len(prior) != policy["inherited_bytes"] or hashlib.sha256(prior).hexdigest() != policy["inherited_sha256"]:
            raise IntegrityError("Inherited telemetry changed")
    seen = set()
    jobs = charges = None
    appended = []
    for line in raw[len(seed):].splitlines():
        try:
            e = json.loads(line)
            allowed = {"time", "model", "agent", "family", "outcome", "category", "run_id", "step", "note"}
            if set(e) - allowed or any(not isinstance(e.get(k), str) or not e[k] for k in ("time", "model", "agent", "family", "run_id", "step")):
                raise ValueError("Invalid telemetry fields")
            if e["outcome"] not in {"COMPLETED", "REFUSED", "NO_QUALIFIED_MODEL"}:
                raise ValueError("Invalid telemetry outcome")
            run = safe("runs/" + e["run_id"])
            if not run.is_dir() or run.parent != root / "runs":
                raise ValueError("Unknown telemetry run")
            state = json.loads((run / "state.json").read_text())
            if policy:
                if e["run_id"] != policy["run_id"]:
                    raise IntegrityError("Unexpected telemetry run")
                if state.get("execution_mode") != "STANDARD":
                    raise IntegrityError("Authorized STANDARD execution mode changed")
                if jobs is None:
                    jobs = [json.loads(s) for s in safe(f"runs/{run.name}/data/job_ledger.jsonl").read_bytes().splitlines()]
                    charges = [json.loads(s) for s in safe(f"runs/{run.name}/costs.jsonl").read_bytes().splitlines()]
                _standard_completion(run, e, policy, charges, jobs, seen)
                appended.append(e)
                continue
            if state.get("execution_mode") != "STAGED_PILOT":
                raise ValueError("Unapproved execution mode")
            ledger = [json.loads(s) for s in (run / "costs.jsonl").read_text().splitlines() if s.strip()]
            if e["outcome"] != "NO_QUALIFIED_MODEL" and not any(all(c.get(k) == e[k] for k in ("model", "agent", "step")) for c in ledger):
                raise ValueError("Telemetry requires reconciled call receipt")
        except (ValueError, KeyError, OSError, TypeError) as exc:
            raise IntegrityError("Unreconciled or unauthorized telemetry append") from exc
        appended.append(e)
    return {"immutable_files_verified": len(immutable), "telemetry_appends_verified": len(appended)}
