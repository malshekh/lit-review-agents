"""Explicit, immutable evaluation-cost authority; independent of scientific outputs.

A replacement must name the researcher-reviewed authority. No implicit fresh $35
allowance is created. Prior events live here, not duplicated in the new call ledger.
"""
import hashlib
import json
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(value):
    if (not value.get("evaluation_id") or not value.get("reviewed_by")
            or value.get("cap_usd") != 35 or value.get("review_usd") != 25
            or value.get("future_margin") != .30 or not isinstance(value.get("prior_events"), list)):
        raise ValueError("Reviewed evaluation authority with unchanged 35/25/30% policy required")
    ledgers = value.get("prior_ledgers", [])
    if not ledgers and value.get("new_independent_evaluation_approved") is not True:
        raise ValueError("Prior evaluation ledgers required; a fresh allowance needs explicit independent-evaluation approval")
    expected = []
    seen_runs = set()
    for ledger in ledgers:
        path = Path(ledger["path"])
        if path.name != "costs.jsonl" or ledger["run_id"] in seen_runs:
            raise ValueError("Ambiguous/duplicate prior evaluation ledger")
        seen_runs.add(ledger["run_id"])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ledger["sha256"]:
            raise ValueError("Prior ledger changed; reconcile before replacement")
        reservations = path.parent / "reservations.json"
        if reservations.exists() and json.loads(reservations.read_text()):
            raise ValueError("Parent commitments require reconciliation")
        expected += [{"event_id": digest(e), "run_id": ledger["run_id"], "provider": e["provider"],
                      "cost_usd": e["cost_usd"]} for e in (json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip())]
    if ledgers and sorted(expected, key=lambda e:e["event_id"]) != sorted(value["prior_events"], key=lambda e:e["event_id"]):
        raise ValueError("Prior spending omitted or altered")
    if value.get("restart_of") and value["restart_of"] not in seen_runs:
        raise ValueError("Replacement must account for its incident parent")
    ids = []
    for event in value["prior_events"]:
        amount = event.get("cost_usd")
        if (not event.get("event_id") or not event.get("provider") or not event.get("run_id")
                or type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0):
            raise ValueError("Invalid prior-cost event")
        ids.append(event["event_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Prior expenditure cannot be counted twice")
    return value


def prepare(authority_path):
    if not authority_path:
        raise ValueError("Explicit reviewed evaluation-budget authority required before creating a staged replacement")
    path = Path(authority_path).resolve()
    raw = path.read_bytes()
    value = validate(json.loads(raw))
    return {"authority_path": str(path), "authority_sha256": hashlib.sha256(raw).hexdigest(), "authority": value}


def load(run_dir):
    path = Path(run_dir) / "input/evaluation_budget.json"
    policy_path = Path(run_dir) / "input/corpus_policy.json"
    if not path.exists():
        if policy_path.exists():
            raise ValueError("Fixed pilot missing reviewed cumulative-budget authority")
        return None  # pre-existing legacy fixtures/runs never silently become replacement runs
    context = json.loads(path.read_text(encoding="utf-8"))
    source = Path(context["authority_path"])
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != context["authority_sha256"] or validate(json.loads(raw)) != context["authority"]:
        raise ValueError("Evaluation-budget authority changed; fresh review required")
    return context["authority"]


def prior(run_dir, entries):
    authority = load(run_dir)
    if authority is None:
        return 0.0
    known = {event["event_id"] for event in authority["prior_events"]}
    if any(digest(e) in known or e.get("source_event_id") in known for e in entries):
        raise ValueError("Parent expenditure duplicated in replacement call ledger")
    return sum(e["cost_usd"] for e in authority["prior_events"])
