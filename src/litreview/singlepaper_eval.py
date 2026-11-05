"""Narrow extension of the native pilot harness for one R0001 writing cycle.

No new scheduler or provider implementation. Native jobs, request admission,
financial authorization, reservations, receipts and checkpoints remain in force.
"""
from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from . import checkpoints, pilot_authorization as pilot, bridge
from .orchestrator import Run, Pause
from .budget import BudgetExceeded
from .agents.base import AgentError

VERSION = "r0001-native-writing-v1"
AGENTS = {"synthesize": "A07-SYN", "outline": "A08-OL", "write_once": "A09-WRI",
          "verify_once": "A10-RV", "critique_once": "A11-RC", "edit_once": "A12-EDI"}


def policy(run):
    path = run.dir / "input/r0001_writing_evaluation.json"
    if not path.exists():
        return None
    p = json.loads(path.read_text(encoding="utf-8"))
    if (p.get("version") != VERSION or p.get("run_id") != run.id
            or p.get("record_ids") != ["R0001"] or p.get("pmids") != ["34638842"]
            or p.get("sub_cap_usd") != 15 or p.get("parent_cap_usd") != 35
            or p.get("review_usd") != 25 or p.get("margin") != .30
            or p.get("researcher_authorized") is not True
            or not p.get("parent_run_id") or not p.get("authority_sha256")
            or not p.get("parent_files")):
        raise pilot.AuthorizationRequired("Invalid R0001-only evaluation authority")
    baseline = Decimal(str(p.get("baseline_cumulative_usd")))
    if not baseline.is_finite() or not 0 <= baseline < 35:
        raise pilot.AuthorizationRequired("Invalid cumulative baseline")
    # Copied accepted inputs are immutable; downstream artifacts are NOT in this list.
    for relative, digest in p["parent_files"].items():
        target = (run.dir / relative).resolve()
        if not target.is_relative_to(run.dir.resolve()) or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise pilot.AuthorizationRequired("Accepted parent evidence changed: " + relative)
    return p


class WritingRun(Run):
    def __init__(self, run_id):
        super().__init__(run_id)
        self.evaluation = policy(self)
        if not self.evaluation:
            raise Pause("Explicit single-paper evaluation authority required")
        if self.cfg["loops"]["max_redrafts"] != 0 or self.cfg["loops"]["max_critique_cycles"] != 1:
            raise Pause("Native one-cycle configuration must be 0 redrafts / 1 critique")
        # A stricter operational ceiling on the EXISTING native cumulative ledger.
        # The recorded parent authority/config remains $35. Every post-baseline
        # call, including failures, consumes this same fixed $15 envelope.
        self.baseline = Decimal(str(self.evaluation["baseline_cumulative_usd"]))
        self.budget.operational_ceiling = float(min(Decimal(35), self.baseline + Decimal(15)))
        self.dry_cap = None

    def _reserve(self, key, usd, agent_id, note="", steps=()):
        floor = getattr(self, "_cache_reservation_floor", None)
        if floor and floor[0] == agent_id:
            usd = max(usd, floor[1])
        spend = Decimal(str(self.budget.spent()))
        held = Decimal(str(self.budget.reserved()))
        cap = Decimal(str(self.dry_cap if self.dry_cap is not None else 15))
        # Margin applies to future cost, not previously paid amounts.
        if spend - self.baseline + held + Decimal(str(usd)) * Decimal("1.30") > cap:
            self.save("evaluation_admission_refusal.json", {"agent": agent_id, "key": key,
                      "worst_case_usd": usd, "sub_cap_usd": float(cap), "provider_dispatched": False})
            raise BudgetExceeded("R0001 evaluation sub-cap admission refused before provider dispatch")
        return super()._reserve(key, usd, agent_id, note, steps)

    def _admitted(self, agent_id, payload, step, schema_file=None,
                  exclude=frozenset(), limit=None):
        # Reuse native admission/dispatch, but cold-price all Anthropic input at
        # the 1h-write rate so cache creation cannot exceed a plain-input quote.
        import dataclasses
        from . import admission
        m = self.route(agent_id, exclude)
        if limit:
            m = dataclasses.replace(m, max_tokens=int(self._bridge_cfg()["output_limits"][limit]))
        a = admission.assess(agent_id, payload, m, self.cfg.get("admission") or {}, self.budget.prices)
        floor = None
        if m.provider == "anthropic":
            floor = self.budget.cost(m.model, 0, a["output_reserve"], 0, 0, a["input_bound"])
            if floor is None: raise Pause("Unpriced cache-write reservation")
        self._cache_reservation_floor = (agent_id, floor) if floor is not None else None
        try:
            return super()._admitted(agent_id, payload, step, schema_file, exclude, limit)
        finally:
            self._cache_reservation_floor = None

    def agent(self, agent_id, payload, step, **kwargs):
        st = self.state()
        expected = AGENTS.get(st.get("evaluation_phase") or st["stage"])
        if agent_id != expected:
            raise Pause("R0001 harness refuses other agents, papers and repeated cycles")
        self._only_r0001(payload)
        kwargs["repair_limit"] = 0  # Every new paid attempt needs separate admission.
        return super().agent(agent_id, payload, step, **kwargs)

    @staticmethod
    def _only_r0001(value):
        if isinstance(value, dict):
            rid = value.get("record_id")
            if rid is not None and rid != "R0001":
                raise Pause("Out-of-scope record in writing request")
            fid = value.get("finding_id")
            if isinstance(fid, str) and fid.startswith("R") and not fid.startswith("R0001:"):
                raise Pause("Out-of-scope finding in writing request")
            for key, child in value.items():
                WritingRun._only_r0001(key)
                WritingRun._only_r0001(child)
        elif isinstance(value, list):
            for child in value: WritingRun._only_r0001(child)
        elif isinstance(value, str):
            import re
            if any(rid != "R0001" for rid in re.findall(r"\bR\d{4}\b", value)):
                raise Pause("Out-of-scope record identifier in writing request")

    def stage_synthesize(self, st):
        nxt = super().stage_synthesize(st)
        pkg = self.load("synthesis_package.json")
        pkg["demonstration_scope"] = {"label":"R0001 SINGLE-PAPER DEMONSTRATION",
                "record_ids":["R0001"], "not_completed_parent_review":True}
        self.save("synthesis_package.json", pkg)
        return nxt

    def _draft_once(self, st):
        self._reproject("draft")
        ps = self._plan_state()  # Retains CP_LEDGER and native evidence binding.
        sections = self._write_sections(ps, "draft1")
        draft = self._assemble(ps, sections, "draft1")
        self._save_manuscript(draft, "m01_single_paper_draft")
        self.save_state({**self.state(), "evaluation_phase":"verify_once"})
        return "draft"  # Native stage name; no pre-verification editing or redrafts.

    def _verify_once(self, st):
        ps = self._plan_state()
        m = self._current()
        rv = self._stamp(self._verify(m, "DRAFT", "A10-RV_single_cycle"), m, ps)
        self.save("rv_latest.json", rv)
        self.save_state({**self.state(), "evaluation_phase":"critique_once"})
        return "review_loop"

    def _critique_once(self, st):
        self._reproject("review_loop")
        ps = self._plan_state()
        m, rv = self._current(), self.load("rv_latest.json")
        self._require_current(rv, m, ps, "A11-RC")
        summary = {k:v for k,v in rv.items() if k not in ("occurrence_inventory", "verdicts",
                   "global_index_ids_reviewed", "request_metrics", "correction_trace")}
        payload = bridge.critique_payload(m, ps["amap"], ps["ledger"], summary, ps["journal"], None)
        rc = self._admitted("A11-RC", payload, "A11-RC_single_cycle", exclude=self._prose_vendors("A11-RC"))
        rc["bridge_fingerprint"] = self._bridge_fingerprint(m, ps)
        self.save("rc_latest.json", rc)
        if rc["decision"] == "HOLD_FOR_UPSTREAM_REVIEW":
            raise Pause("A11 requests upstream scientific review")
        if rc["decision"] == "ACCEPT" and any(f.get("severity") == "BLOCKING" for f in rv.get("findings", [])):
            raise Pause("A11 ACCEPT cannot override blocking verification findings")
        self.save_state({**self.state(), "evaluation_phase":"edit_once"})
        return "review_loop"

    def _edit_once(self, st):
        ps = self._plan_state()
        m, rv, rc = self._current(), self.load("rv_latest.json"), self.load("rc_latest.json")
        self._require_current(rv, m, ps, "A12-EDI")
        if rc.get("bridge_fingerprint") != self._bridge_fingerprint(m, ps):
            raise Pause("Critique is stale")
        ed = self._edit("REVISION", m, ps, "A12-EDI_single_cycle", critique=rc,
                        verification_findings=rv.get("findings"))
        self._binding_gate(ed, ps, "single_cycle")
        self._save_manuscript(ed, "m02_single_paper_demonstration")
        self.save("evaluation_completion.json", {"label":"SINGLE-PAPER DEMONSTRATION ? NOT A THREE-PAPER REVIEW",
                  "post_edit_verified":False, "outstanding_verification_findings":rv.get("findings", []),
                  "automatic_second_cycle":False, "publication_release":False})
        return "evaluation_done"  # Never native finish_edit/finalize.

    def continue_evaluation(self):
        handlers = {"synthesize":self.stage_synthesize, "cp3":self.stage_cp3,
                    "outline":self.stage_outline, "write_once":self._draft_once,
                    "verify_once":self._verify_once, "critique_once":self._critique_once,
                    "edit_once":self._edit_once}
        # A process-wide exclusive lock prevents overlapping evaluation commands.
        lock = self.dir / "r0001_writing.lock"
        import os
        try: fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError: raise Pause("Evaluation already running or interrupted; reconcile its lock")
        try:
            while True:
                st = self.state()
                stage = st["stage"]
                if stage == "evaluation_done":
                    print("STOPPED: single evaluation cycle finished; no post-edit verification claimed")
                    return
                phase = st.get("evaluation_phase") or stage
                if stage == "draft" and not st.get("evaluation_phase"): phase = "write_once"
                if phase not in handlers: raise Pause("Unsupported writing evaluation stage")
                # The native financial stage is derived from the agent, while
                # custom single-cycle state names must not bypass stage policy.
                nxt = handlers[phase](st)
                updated = {**self.state(), "stage":nxt, "status":"READY"}
                if nxt == "draft" and stage == "outline": updated["evaluation_phase"] = "write_once"
                self.save_state(updated)
                if nxt == "cp3":
                    # Always materialize CP3, then stop; never approve it here.
                    self.stage_cp3(self.state())
                    raise Pause("Review CP3 before manuscript execution")
        except (Pause, BudgetExceeded, AgentError, pilot.AuthorizationRequired) as exc:
            self.save_state({**self.state(), "status":"PAUSED: "+str(exc)})
            print("PAUSED: "+str(exc))
        finally:
            os.close(fd)
            lock.unlink(missing_ok=True)


def disable_sdk_retries():
    """Called only inside the account-bound paid launcher; creates no requests."""
    from .llm import anthropic_client, openai_compatible
    anthropic_client._client = anthropic_client._get_client().with_options(max_retries=0)
    for provider in ("openai", "kimi"):
        openai_compatible._clients[provider] = openai_compatible._get_client(provider).with_options(max_retries=0)
