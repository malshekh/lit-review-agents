"""Run one stage's independent agent calls (A05 per paper, A06 per paper) through a vendor batch.

Order of operations, each step there for a failure it prevents:
1. Reattach. An earlier batch for this agent that was submitted but not ingested is polled and ingested,
   never resubmitted. One whose ID was never saved (a crash or timeout between creating it and recording it)
   is resolved by identity, not by resemblance (see _recover). A batch that cannot be conclusively identified
   stays UNRESOLVED and the run pauses: a replacement is never submitted automatically, because local
   deduplication prevents double-counting but not double-billing.
2. Route, per item. Each item routes on its own: refusal routing, the alternate cost check, and the vendor
   rule (`exclude`: an auditor never runs on the vendor that produced the work it audits, so A06 routes per
   paper on the provider that actually produced that paper's extraction). Items are grouped by model, and
   each group is its own batch on its own provider. The rule is checked again before anything is uploaded.
3. Probe. One real item per model goes interactively first. A refusal costs one paper's input, not the
   batch's, and stops the stage before anything is submitted; its output is kept like any other.
4. Chunks and reservations. A batch commits its whole cost at submission and cannot be stopped. Items are
   submitted in chunks (batch.chunk_size, each a batch with its own fingerprint and reservation). A chunk's
   worst-case cost (every item at the configured max_tokens, the same as an interactive call: batching
   never changes what a call may produce) is reserved under the budget lock before submission and held
   until the chunk settles, when its actual cost has replaced the reservation and frees room for the next.
   At most batch.max_chunks_in_flight chunks are outstanding. A chunk that does not fit waits for an
   outstanding one to settle; one that does not fit with nothing outstanding stops the stage
   (BudgetExceeded). Refused, not asked.
5. Fingerprint, intent, create. The fingerprint (run ID, stage, submission ID, custom_ids, SHA-256 of the
   frozen request manifest) and the intent record are written before the batch is created; then the ID.
6. Ingest. Each result is logged at batch rates, validated, and saved as it is read; ingested items are
   recorded so an interrupted ingestion never logs a cost twice. Invalid JSON, truncation and invalid
   requests go to the interactive path (which has its own JSON repair). Expired, canceled and server-error
   items go back into the pool. Refused items are recorded in the model record and go back into the pool,
   so the next round routes them to the alternate through the cost check (the stage is then mixed-model,
   which provenance reports). The reservation is released once every result is logged.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from typing import TYPE_CHECKING, Callable

from . import model_record
from .agents.base import (AgentError, build_system_prompt, parse_json, prompt_version, user_parts,
                          validate)
from .budget import BudgetExceeded
from .llm import batch

if TYPE_CHECKING:
    from .orchestrator import Run

OnOutput = Callable[[str, dict], None]
Exclude = Callable[[str], frozenset]
CUSTOM_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")   # Anthropic's rule; OpenAI accepts it too
CREATE_WINDOW = 900   # seconds after the intent within which a create can have landed (create timeout 600)


class VendorSeparationError(AgentError):
    pass


class ReservationRefused(BudgetExceeded):
    """A chunk's worst case does not fit under the cap right now. Nothing was uploaded or created."""


class BatchStage:
    def __init__(self, run: "Run", agent_id: str, items: list[tuple[str, dict]], on_output: OnOutput,
                 exclude: Exclude | None = None):
        self.run, self.agent_id, self.on_output = run, agent_id, on_output
        self.exclude = exclude or (lambda step: frozenset())
        self.payloads = dict(items)
        self.order = [s for s, _ in items]
        self.cfg = run.cfg.get("batch") or {}
        self.state_path = run.data(f"batches/{agent_id}.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    # --- state ----------------------------------------------------------
    def _records(self) -> list[dict]:
        return json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else []

    def _save(self, records: list[dict]) -> None:
        self.state_path.write_text(json.dumps(records, indent=1), encoding="utf-8")

    def _update(self, rec: dict) -> None:
        records = self._records()
        self._save([rec if r["intent_at"] == rec["intent_at"] else r for r in records])

    def _done(self, step: str) -> bool:
        return (self.run.dir / "outputs" / f"{step}.json").exists()

    def _pending(self) -> list[str]:
        return [s for s in self.order if not self._done(s)]

    # --- the stage --------------------------------------------------------
    def run_all(self) -> None:
        for rec in self._records():
            if rec["status"] in ("SUBMITTED", "INTENT", "UNRESOLVED"):
                self._finish(rec)
        self._release_settled()
        for _ in range(3):   # rounds: refused or expired items come back for the next round
            pending = self._pending()
            if not pending:
                return
            groups: dict[str, tuple] = {}
            routed: dict[frozenset, object] = {}
            for step in pending:
                ex = frozenset(self.exclude(step))
                if ex not in routed:
                    routed[ex] = self.run.route(self.agent_id, ex)
                m = routed[ex]
                groups.setdefault(m.model, (m, []))[1].append(step)
            submitted = False
            for m, steps in groups.values():
                if m.provider not in batch.PROVIDERS:
                    continue   # runs interactively below
                proven = any(e["run_id"] == self.run.id and e["agent"] == self.agent_id and e["model"] == m.model
                             and e["outcome"] == "COMPLETED" for e in model_record.entries())
                if not proven:   # probe: one real item, interactively, before anything is submitted
                    self._interactive([steps[0]])
                    steps = steps[1:]
                if len(steps) < int(self.cfg.get("min_items", 3)):
                    continue
                self._run_chunks(m, steps)
                submitted = True
            if not submitted:
                break
        self._interactive(self._pending())

    def _run_chunks(self, m, steps: list[str]) -> None:
        size = max(1, int(self.cfg.get("chunk_size", 20)))
        in_flight = max(1, int(self.cfg.get("max_chunks_in_flight", 1)))
        queue = [steps[i:i + size] for i in range(0, len(steps), size)]
        outstanding: list[dict] = []
        while queue or outstanding:
            if queue and len(outstanding) < in_flight:
                try:
                    outstanding.append(self._submit(m, queue[0]))
                    queue.pop(0)
                    continue
                except ReservationRefused:
                    if not outstanding:
                        raise
            self._finish(outstanding.pop(0))   # settles: its actual cost replaces its reservation

    def _interactive(self, steps: list[str]) -> None:
        for step in steps:
            if not self._done(step):
                self.on_output(step, self.run.agent(self.agent_id, self.payloads[step], step,
                                                    exclude_providers=frozenset(self.exclude(step))))

    # --- submission -------------------------------------------------------
    def _requests(self, m, ids: dict[str, str]) -> tuple[list[dict], dict]:
        system = build_system_prompt(self.agent_id)
        ttl = self.cfg.get("cache_ttl", m.cache_ttl)
        reqs, chars = [], {}
        for cid, step in ids.items():
            parts = user_parts(self.payloads[step], m.cache_payload)
            reqs.append(batch.request(m.provider, cid, system, parts, m.model, m.max_tokens, m.temperature,
                                      m.effort, m.cache_system, ttl))
            chars[step] = len(system) + sum(len(p["text"]) for p in parts)
        return reqs, {"chars": chars, "system_chars": len(system), "ttl": ttl}

    def project(self, m, steps: list[str], shape: dict) -> dict:
        """Worst-case cost of the batch. Output: every item at the configured max_tokens, not at what the
        model happened to produce before (a financial control cannot rest on past behaviour; expect it to
        refuse batches that would have fit). Input: this run's own tokens-per-character ratio for this agent
        and model (+10%), and on Anthropic every item paying a cache write and none reading. Long-context
        and batch tables apply per item."""
        b = self.run.budget
        seen = [e for e in b.entries() if e["agent"] == self.agent_id and e["model"] == m.model and e.get("prompt_chars")]
        ratio = (sum(e["input_tokens"] + e.get("cached_input_tokens", 0) + e.get("cache_write_tokens", 0)
                     + e.get("cache_write_1h_tokens", 0) for e in seen) / sum(e["prompt_chars"] for e in seen)
                 if seen else 1 / 2.5)
        out = m.max_tokens
        total = 0.0
        for step in steps:
            tokens = int(shape["chars"][step] * ratio * 1.1)
            sys_tokens = int(shape["system_chars"] * ratio * 1.1) if (m.provider == "anthropic" and m.cache_system) else 0
            w5, w1 = (sys_tokens, 0) if shape["ttl"] == "5m" else (0, sys_tokens)
            total += b.cost(m.model, tokens - sys_tokens, out, 0, w5, w1, batch=True) or 0.0
        return {"projected_usd": round(total, 4), "items": len(steps), "tokens_per_char": round(ratio, 4),
                "output_tokens_per_item": out, "basis": "configured max_tokens per item (worst case)"}

    def _submit(self, m, steps: list[str]) -> dict:
        crossed = [s for s in steps if m.provider in self.exclude(s)]
        if crossed:   # routing already prevents this; checked again here because nothing after it can be undone
            raise VendorSeparationError(
                f"{self.agent_id}: not submitted: {len(crossed)} item(s) would be audited on {m.provider}, the "
                f"vendor that produced the work they audit ({', '.join(crossed[:5])})")
        nonce = secrets.token_hex(5)
        sub_id = f"{self.agent_id}-{nonce}"
        ids = {f"{step}__{nonce}": step for step in steps}   # deterministic from the submission record
        bad = [c for c in ids if not CUSTOM_ID.match(c)]
        if bad:
            raise ValueError(f"{self.agent_id}: invalid batch custom_id(s): {bad[:3]}")
        reqs, shape = self._requests(m, ids)
        data = batch.manifest(reqs)
        digest = batch.sha256(data)
        est = self.project(m, steps, shape)
        self.run._batch_gate(self.agent_id, steps, est["projected_usd"])   # raises BatchGateRefused: stop
        b = self.run.budget
        ok, available = b.reserve(sub_id, est["projected_usd"], self.agent_id,
                                  note=f"{len(steps)} items on {m.model}")
        est["available_usd"] = round(available, 4)
        if not ok:
            raise ReservationRefused(
                f"{self.agent_id}: batch chunk of {len(steps)} not submitted: projected ${est['projected_usd']:.2f} "
                f"(every item at max_tokens {m.max_tokens}) exceeds the ${available:.2f} available under the cap "
                "after spend and reservations held by unsettled batches (a submitted batch cannot be stopped). "
                "Raise run.spend_cap_usd, or lower batch.chunk_size, to continue.")
        manifest_file = self.state_path.parent / "manifests" / f"{sub_id}.jsonl"
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_bytes(data)
        try:
            file_id = batch.upload(m.provider, data)   # OpenAI only; creates no batch
        except Exception:
            b.release(sub_id)   # nothing can have been created
            raise
        fingerprint = {"run_id": self.run.id, "stage": self.agent_id, "submission_id": sub_id,
                       "custom_ids": sorted(ids), "manifest_sha256": digest,
                       "manifest_file": str(manifest_file.relative_to(self.run.dir))}
        rec = {"intent_at": time.time(), "status": "INTENT", "submission_id": sub_id, "provider": m.provider,
               "model": m.model, "steps": steps, "custom_ids": ids, "count": len(steps), "input_file_id": file_id,
               "batch_id": None, "fingerprint": fingerprint, "estimate": est, "prompt_chars": shape["chars"],
               "ingested": [], "cache_requested": m.provider == "anthropic" and (m.cache_system or bool(m.cache_payload))}
        self._save(self._records() + [rec])           # intent first: a crash after create stays recoverable
        rec["batch_id"] = batch.create(m.provider, reqs, file_id, metadata={
            "run_id": self.run.id, "stage": self.agent_id, "submission_id": sub_id, "manifest_sha256": digest})
        rec["status"] = "SUBMITTED"
        self._update(rec)
        b.attach_reservation(sub_id, rec["batch_id"])
        self.run.prov.tool_run("batch_submitted", self.agent_id, {k: rec[k] for k in (
            "batch_id", "submission_id", "provider", "model", "count", "estimate")} | {"manifest_sha256": digest})
        return rec

    # --- recovery ------------------------------------------------------------
    def _confirm(self, rec: dict, cand: dict) -> bool | None:
        """Is `cand` the batch this intent created? True when proven; False when proven to be another batch;
        None when it cannot be told (yet), which never permits adoption or a replacement."""
        fp = rec.get("fingerprint")
        if not fp:
            return None   # recorded before fingerprints existed: never adopted automatically
        if rec["provider"] == "openai":
            # nominated by this submission's own input file or submission ID, so a mismatch is an anomaly to
            # look at, not proof that the batch is someone else's
            ok = bool(cand.get("input_file_id")) and batch.input_sha256(cand["input_file_id"]) == fp["manifest_sha256"]
            return True if ok else None
        got = batch.result_ids(rec["provider"], cand["id"])
        if got is None:
            return None   # still processing: its custom_ids cannot be read until it ends
        return sorted(got) == fp["custom_ids"]

    def _recover(self, rec: dict) -> tuple[str, object]:
        """Resolve an intent whose batch ID was never saved. Time, item count, input file and metadata only
        nominate candidates; a candidate is adopted only when its identity is confirmed against the frozen
        manifest (OpenAI: the SHA-256 of its input file; Anthropic: its custom_ids, which carry this
        submission's nonce, once it has ended). Returns ("ADOPT", batch_id); ("NOT_CREATED", None) when a
        complete listing of the closed creation window holds no candidate, or only candidates proven to be
        other batches; otherwise ("UNRESOLVED", the candidates and what is known of each)."""
        since = rec["intent_at"] - 120
        rows, covered = batch.recent(rec["provider"], since)
        known = {r["batch_id"] for r in self._records() if r.get("batch_id")}
        window = [b for b in rows if b["id"] not in known and since <= b["created_at"] <= rec["intent_at"] + CREATE_WINDOW]
        sub = (rec.get("fingerprint") or {}).get("submission_id")
        if rec["provider"] == "openai":
            cands = [b for b in window if b["input_file_id"] == rec["input_file_id"]
                     or (sub and (b.get("metadata") or {}).get("submission_id") == sub)]
        else:
            cands = [b for b in window if b["total"] == rec["count"]]
        verdicts = {b["id"]: self._confirm(rec, b) for b in cands}
        confirmed = [i for i, v in verdicts.items() if v]
        if len(confirmed) == 1:
            return "ADOPT", confirmed[0]
        if all(v is False for v in verdicts.values()) and covered and time.time() > rec["intent_at"] + CREATE_WINDOW:
            return "NOT_CREATED", None
        return "UNRESOLVED", {"confirmed": confirmed, "unverified": [i for i, v in verdicts.items() if v is None],
                              "rejected": [i for i, v in verdicts.items() if v is False], "listing_complete": covered}

    def _unresolved(self, rec: dict, detail: dict) -> None:
        from .orchestrator import Pause
        rec.update(status="UNRESOLVED", candidates=detail, checked_at=time.time())
        self._update(rec)
        if len(detail["confirmed"]) > 1:
            why = (f"more than one batch matches this submission's manifest ({', '.join(detail['confirmed'])}): "
                   "it was created twice. Cancel the extra one in the vendor console")
        elif detail["unverified"]:
            why = (f"candidate batch(es) {', '.join(detail['unverified'])} cannot be confirmed yet"
                   + (" (an Anthropic batch's custom_ids are readable once it ends, within 24 hours)"
                      if rec["provider"] == "anthropic" else ""))
        elif not detail["listing_complete"]:
            why = "the vendor listing did not reach back to the submission time"
        else:
            why = (f"the create call may still have been in flight; absence is conclusive after "
                   f"{time.strftime('%H:%M', time.localtime(rec['intent_at'] + CREATE_WINDOW))}")
        self.run.prov.tool_run("batch_unresolved", self.agent_id, {"submission_id": rec.get("submission_id"), **detail})
        raise Pause(f"{self.agent_id}: submission {rec.get('submission_id')} is unresolved: {why}. Nothing was "
                    "resubmitted. Rerun `litreview run` to check again, or, having checked the vendor console, set "
                    f"batch_id (or status NOT_CREATED) on that record in {self.state_path} and rerun.")

    def _release_settled(self) -> None:
        """Release reservations whose submission has settled, or that never reached an intent record within
        an hour (a crash between reserving and recording: create comes after the intent, so nothing was
        created). A younger orphan may belong to another process that is still uploading: it is kept."""
        b, records = self.run.budget, {r.get("submission_id"): r for r in self._records()}
        for key, res in b.reservations().items():
            if res.get("agent") != self.agent_id:
                continue
            rec = records.get(key)
            if (rec is not None and rec["status"] in ("INGESTED", "NOT_CREATED")) or (
                    rec is None and time.time() - res.get("reserved_epoch", 0) > 3600):
                b.release(key)

    # --- waiting and ingesting ---------------------------------------------------
    def _finish(self, rec: dict) -> None:
        if rec["status"] in ("INTENT", "UNRESOLVED"):
            if rec.get("batch_id"):   # identified by the researcher
                outcome, found = "ADOPT", rec["batch_id"]
            else:
                outcome, found = self._recover(rec)
            if outcome == "UNRESOLVED":
                self._unresolved(rec, found)
            if outcome == "NOT_CREATED":
                rec["status"] = "NOT_CREATED"
                self._update(rec)
                self.run.budget.release(rec.get("submission_id", ""))
                return
            rec.update(batch_id=found, status="SUBMITTED")
            self._update(rec)
            if rec.get("submission_id"):
                self.run.budget.attach_reservation(rec["submission_id"], found)
            self.run.prov.tool_run("batch_recovered", self.agent_id, {"submission_id": rec.get("submission_id"),
                                                                      "batch_id": found})
        elif rec["status"] == "NOT_CREATED":
            return
        poll = float(self.cfg.get("poll_seconds", 60))
        deadline = rec["intent_at"] + float(self.cfg.get("max_wait_hours", 24.5)) * 3600
        while True:
            s = batch.status(rec["provider"], rec["batch_id"])
            if s["done"]:
                break
            if time.time() > deadline:
                from .orchestrator import Pause
                raise Pause(f"{self.agent_id}: batch {rec['batch_id']} still {s['status']} after the wait limit. "
                            "`litreview run` reattaches to it.")
            time.sleep(poll)
        self._ingest(rec, s)

    def _ingest(self, rec: dict, s: dict) -> None:
        run, ingested = self.run, set(rec.get("ingested", []))
        ids = rec.get("custom_ids") or {}
        repair: list[str] = []
        counts = {"succeeded": 0, "refused": 0, "repair": 0, "resubmit": 0}
        for it in batch.results(rec["provider"], rec["batch_id"], rec["model"]):
            step = ids.get(it.custom_id, it.custom_id if not ids else None)
            if step is None or step in ingested or step not in self.payloads:
                continue
            if it.status != "succeeded":
                counts["resubmit" if it.retryable else "repair"] += 1
                if not it.retryable:
                    repair.append(step)
            else:
                self._ingest_one(rec, step, it.response, repair, counts)
            ingested.add(step)
            rec["ingested"] = sorted(ingested)
            self._update(rec)
        rec.update(status="INGESTED", vendor_status=s["status"], succeeded=counts["succeeded"], outcome=counts)
        self._update(rec)
        if rec.get("submission_id"):
            run.budget.release(rec["submission_id"])   # settled: every result's actual cost is logged
        run.prov.tool_run("batch_ingested", self.agent_id, {"batch_id": rec["batch_id"], **counts})
        if run.budget.should_warn():
            from . import notify
            notify.send("budget_warning", f"Run {run.id}: 80% of budget used", run.budget.summary_text())
        self._interactive(repair)   # invalid JSON, truncation, invalid request: interactive, with JSON repair

    def _ingest_one(self, rec: dict, step: str, resp, repair: list[str], counts: dict) -> None:
        run = self.run
        if not any(e["step"] == step and e.get("batch_id") == rec["batch_id"] for e in run.budget.entries()):
            run.budget.record(self.agent_id, resp.provider, resp.model, resp.input_tokens, resp.output_tokens,
                              step=step, cached_input_tokens=resp.cached_input_tokens,
                              cache_write_tokens=resp.cache_write_tokens,
                              cache_write_1h_tokens=resp.cache_write_1h_tokens, batch_id=rec["batch_id"],
                              cache_requested=rec["cache_requested"], prompt_chars=rec["prompt_chars"].get(step))
        (run.dir / "outputs" / f"{step}.raw0.txt").write_text(resp.text, encoding="utf-8")
        version = prompt_version(self.agent_id)
        if resp.stop_reason == "refusal":
            counts["refused"] += 1
            run.prov.agent_call(self.agent_id, step, resp.model, version, "", "REFUSED")
            model_record.add(resp.model, self.agent_id, run.family(), "REFUSED", run.id, step, resp.refusal_category,
                             note=f"in batch {rec['batch_id']}")
            return   # back into the pool: the next round routes to the alternate
        if resp.stop_reason in ("max_tokens", "length"):
            counts["repair"] += 1
            repair.append(step)
            return
        try:
            out = parse_json(resp.text)
            validate(self.agent_id, out)
        except Exception:  # noqa: BLE001 — JSON or schema failure: the interactive path repairs it
            counts["repair"] += 1
            repair.append(step)
            return
        out_file = run.dir / "outputs" / f"{step}.json"
        out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        run.prov.agent_call(self.agent_id, step, resp.model, version, str(out_file.relative_to(run.dir)),
                            out.get("status", "UNKNOWN"))
        model_record.add(resp.model, self.agent_id, run.family(), "COMPLETED", run.id, step)
        counts["succeeded"] += 1
        self.on_output(step, out)
