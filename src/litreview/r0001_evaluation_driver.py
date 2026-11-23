"""Versioned R0001 evaluation controller. No CLI or live adapter is installed.

A promoted adapter must verify native approvals, exact input receipts and runtime
identity; price serialized requests conservatively; dispatch through native guards;
and log every paid outcome under the supplied reservation key. This module never
imports a provider SDK or the unrestricted orchestrator runner.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

VERSION = "r0001-writing-evaluation-v1"
STAGES = ("A07-SYN", "A08-OL", "A09-WRI", "A10-RV", "A11-RC", "A12-EDI")


class EvaluationStopped(RuntimeError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def atomic(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def amount(value):
    if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
        raise EvaluationStopped("Non-finite or negative financial value")
    return Decimal(str(value))


class EvaluationDriver:
    """Offline-testable controller; adapter binding/promotion is a separate gate.

    Budget is the EXISTING native cumulative Budget, not a new allowance. All
    controllers sharing it serialize reservations using its existing budget lock.
    Accepted results are cached here; unknown outcomes remain held for manual
    reconciliation. Failed calls are never automatically retried.
    """
    def __init__(self, directory, budget, binding, adapter):
        self.directory = Path(directory)
        self.path = self.directory / "evaluation_state.json"
        self.budget, self.binding, self.adapter = budget, binding, adapter
        if binding.get("record_ids") != ["R0001"] or binding.get("pmids") != ["34638842"]:
            raise EvaluationStopped("Single-paper R0001/34638842 evaluation only")
        required = ("evaluation_id", "runtime_manifest_sha256", "parent_run_id", "source_sha256",
                    "extraction_sha256", "validation_sha256", "adjudication_sha256",
                    "scope_sha256", "cost_authority_sha256")
        if any(not binding.get(k) for k in required):
            raise EvaluationStopped("Missing versioned provenance binding")
        if budget.cap != 35:
            raise EvaluationStopped("Unchanged native $35/$25 policy required")
        self.identity = fingerprint({"version": VERSION, "binding": binding})
        self.prefix = "r0001-eval-" + fingerprint(binding["evaluation_id"]) + "-"
        self.directory.mkdir(parents=True, exist_ok=True)
        with budget._lock():
            if not self.path.exists():
                atomic(self.path, {"identity": self.identity, "stage": 0, "calls": {},
                                  "results": {}, "label": "SINGLE-PAPER DEMONSTRATION",
                                  "post_edit_verified": False})
            self._state()

    def _state(self):
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if state["identity"] != self.identity:
            raise EvaluationStopped("Changed scope/runtime/evidence requires a new version and approval")
        return state

    def current_stage(self):
        i = self._state()["stage"]
        return STAGES[i] if i < len(STAGES) else "STOPPED_AFTER_A12"

    def _financials(self):
        entries = self.budget.entries()
        sub = sum((amount(e["cost_usd"]) for e in entries
                   if str(e.get("reservation_key", "")).startswith(self.prefix)), Decimal(0))
        held = Decimal(0)
        for key, res in self.budget.reservations().items():
            if key.startswith(self.prefix):
                paid = sum((amount(e["cost_usd"]) for e in entries
                            if e.get("reservation_key") == key), Decimal(0))
                held += max(Decimal(0), amount(res["usd"]) - paid)
        return sub, held

    def call(self, agent, step, request):
        # The adapter must revalidate account, immutable inventory, scientific
        # eligibility, current financial identity and mandatory checkpoints.
        stage = self.current_stage()
        if agent != stage or agent not in STAGES:
            raise EvaluationStopped("No other agents, stages or second verification cycle allowed")
        self.adapter.require(stage, self.binding)
        if stage != "A07-SYN":
            self.adapter.require_cp3_and_manuscript_authorization(self.binding)
        self.adapter.require_r0001_only(request, self.binding)
        request_hash = fingerprint(request)
        key = self.prefix + fingerprint({"identity": self.identity, "agent": agent, "step": step})
        with self.budget._lock():
            state = self._state()
            if self.current_stage() != stage:
                raise EvaluationStopped("Concurrent stage change")
            prior = state["calls"].get(key)
            if prior:
                if prior["request_sha256"] != request_hash:
                    raise EvaluationStopped("Changed request at existing step")
                if prior["status"] == "ACCEPTED":
                    if fingerprint(prior["output"]) != prior["output_sha256"]:
                        raise EvaluationStopped("Accepted output integrity failure")
                    return prior["output"]
                raise EvaluationStopped("Interrupted/failed call requires reconciliation; no automatic retry")
            if any(c["status"] != "ACCEPTED" for c in state["calls"].values()):
                raise EvaluationStopped("Another call is unresolved; reconciliation required")
            # Adapter prices actual serialized request, all output/thinking,
            # cache-write premiums and correct context tier; no cache-hit credit.
            worst = amount(self.adapter.worst_case_usd(agent, request))
            worst = worst.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
            spent, held = self._financials()
            parent = amount(self.budget.spent())
            parent_held = amount(self.budget.reserved())
            # 30% margin applies once to this future uncommitted request.
            if spent + held + worst * Decimal("1.30") > 15:
                raise EvaluationStopped("$15 evaluation admission refused")
            if parent + parent_held + worst * Decimal("1.30") > 35:
                raise EvaluationStopped("$35 cumulative admission refused")
            if parent + parent_held + worst >= 25:
                self.adapter.require_spending_review(self.binding)
            self.adapter.require_native_future_projection(agent, float(worst), self.binding)
            if key in self.budget.reservations():
                raise EvaluationStopped("Unresolved native reservation")
            # Write intent first. A crash between files blocks replay, never
            # invents success or permits a second call.
            state["calls"][key] = {"status": "INTENT", "agent": agent,
                                   "request_sha256": request_hash, "worst_usd": str(worst)}
            atomic(self.path, state)
            res = self.budget.reservations()
            res[key] = {"usd": float(worst), "agent": agent, "batch_id": None,
                        "note": VERSION, "reserved_epoch": __import__("time").time()}
            self.budget._write_reservations(res)
        # No exception handler releases unknown provider exposure. Native
        # adapter records unsuccessful calls too; reconciliation remains explicit.
        output = self.adapter.invoke_native(agent, request, step, key)
        self.adapter.validate_output(agent, output)
        with self.budget._lock():
            state = self._state()
            receipts = [e for e in self.budget.entries() if e.get("reservation_key") == key]
            if not receipts or sum(amount(e["cost_usd"]) for e in receipts) > worst:
                raise EvaluationStopped("Missing receipt or admitted bound exceeded; held for review")
            state["calls"][key].update(status="ACCEPTED", output=output,
                                      output_sha256=fingerprint(output))
            atomic(self.path, state)
            res = self.budget.reservations()
            res.pop(key, None)
            self.budget._write_reservations(res)
        return output

    def finish_stage(self, artifact):
        stage = self.current_stage()
        if stage == "STOPPED_AFTER_A12":
            raise EvaluationStopped("One evaluation cycle complete; no additional dispatch")
        # Native A07 adapter must preserve CP_SYN within its job; COMPLETE
        # includes coverage/accounting/eligibility and human-review gates.
        self.adapter.require_complete(stage, artifact, self.binding)
        with self.budget._lock():
            state = self._state()
            if any(c["status"] != "ACCEPTED" for c in state["calls"].values()):
                raise EvaluationStopped("Unsettled request prevents stage completion")
            if self.current_stage() != stage or not any(
                    c["agent"] == stage and c["status"] == "ACCEPTED" for c in state["calls"].values()):
                raise EvaluationStopped("No accepted current-stage request")
            state["results"][stage] = fingerprint(artifact)
            state["stage"] += 1
            atomic(self.path, state)
        # Always return to the caller at a stage boundary. CP3 is not approved
        # here. A12 output remains explicitly NOT post-edit verified.
        return self.current_stage()
