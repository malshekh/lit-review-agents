"""Run one stage's independent agent calls (A05 per paper, A06 per paper) through a vendor batch.

Order of operations, each step there for a failure it prevents:
1. Reattach. An earlier batch for this agent that was submitted but not ingested is polled and ingested,
   never resubmitted. One whose ID was never saved (a crash between creating it and recording it) is
   recovered from the intent record: by input file on OpenAI, by creation time and item count on Anthropic.
2. Route. The agent's model comes from refusal routing and the alternate cost check, as for any call.
3. Probe. One real item goes interactively first. A refusal costs one paper's input, not the batch's, and
   stops the stage before anything is submitted; its output is kept like any other.
4. Projected cost. A batch commits the whole stage's spend at once and cannot be unwound, so if the
   projected cost exceeds what is left under the cap, the batch is not submitted (BudgetExceeded).
5. Intent record, then create, then the batch ID: each written before the next step.
6. Ingest. Each result is logged at batch rates, validated, and saved as it is read; ingested IDs are
   recorded so an interrupted ingestion never logs a cost twice. Invalid JSON, truncation and invalid
   requests go to the interactive path (which has its own JSON repair). Expired, canceled and server-error
   items go back into the pool. Refused items are recorded in the model record and go back into the pool,
   so the next round routes them to the alternate through the cost check (the stage is then mixed-model,
   which provenance reports).
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Callable

from . import model_record
from .agents.base import (build_system_prompt, parse_json, prompt_version, user_parts,
                          validate)
from .budget import BudgetExceeded
from .llm import batch

if TYPE_CHECKING:
    from .orchestrator import Run

OnOutput = Callable[[str, dict], None]


class BatchStage:
    def __init__(self, run: "Run", agent_id: str, items: list[tuple[str, dict]], on_output: OnOutput):
        self.run, self.agent_id, self.on_output = run, agent_id, on_output
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
            if rec["status"] in ("SUBMITTED", "INTENT"):
                self._finish(rec)
        for _ in range(3):   # rounds: refused or expired items come back for the next round
            pending = self._pending()
            if not pending:
                return
            m = self.run.route(self.agent_id)
            if m.provider not in batch.PROVIDERS:
                break
            proven = any(e["run_id"] == self.run.id and e["agent"] == self.agent_id and e["model"] == m.model
                         and e["outcome"] == "COMPLETED" for e in model_record.entries())
            if not proven:   # probe: one real item, interactively, before anything is submitted
                self._interactive([pending[0]])
                pending = pending[1:]
            if len(pending) < int(self.cfg.get("min_items", 3)):
                break
            self._finish(self._submit(m, pending))
        self._interactive(self._pending())

    def _interactive(self, steps: list[str]) -> None:
        for step in steps:
            if not self._done(step):
                self.on_output(step, self.run.agent(self.agent_id, self.payloads[step], step))

    # --- submission -------------------------------------------------------
    def _requests(self, m, steps: list[str]) -> tuple[list[dict], dict]:
        system = build_system_prompt(self.agent_id)
        ttl = self.cfg.get("cache_ttl", m.cache_ttl)
        reqs, chars = [], {}
        for step in steps:
            parts = user_parts(self.payloads[step], m.cache_payload)
            reqs.append(batch.request(m.provider, step, system, parts, m.model, m.max_tokens, m.temperature,
                                      m.effort, m.cache_system, ttl))
            chars[step] = len(system) + sum(len(p["text"]) for p in parts)
        return reqs, {"chars": chars, "system_chars": len(system), "ttl": ttl}

    def project(self, m, steps: list[str], shape: dict) -> dict:
        """Projected cost of the batch, from this run's own calls by this agent and model: input tokens per
        item from their tokens-per-character ratio (+10%), output per item at the largest output seen (or
        max_tokens), and on Anthropic every item paying a cache write and none reading (worst case)."""
        b = self.run.budget
        calls = [e for e in b.entries() if e["agent"] == self.agent_id and e["model"] == m.model]
        seen = [e for e in calls if e.get("prompt_chars")]
        ratio = (sum(e["input_tokens"] + e.get("cached_input_tokens", 0) + e.get("cache_write_tokens", 0)
                     + e.get("cache_write_1h_tokens", 0) for e in seen) / sum(e["prompt_chars"] for e in seen)
                 if seen else 1 / 2.5)
        out = max([e["output_tokens"] for e in calls] or [m.max_tokens])
        total = 0.0
        for step in steps:
            tokens = int(shape["chars"][step] * ratio * 1.1)
            sys_tokens = int(shape["system_chars"] * ratio * 1.1) if (m.provider == "anthropic" and m.cache_system) else 0
            w5, w1 = (sys_tokens, 0) if shape["ttl"] == "5m" else (0, sys_tokens)
            total += b.cost(m.model, tokens - sys_tokens, out, 0, w5, w1, batch=True) or 0.0
        return {"projected_usd": round(total, 4), "items": len(steps), "tokens_per_char": round(ratio, 4),
                "output_tokens_per_item": out, "remaining_usd": round(b.cap - b.spent(), 4)}

    def _submit(self, m, steps: list[str]) -> dict:
        reqs, shape = self._requests(m, steps)
        est = self.project(m, steps, shape)
        if est["projected_usd"] > est["remaining_usd"]:
            raise BudgetExceeded(
                f"{self.agent_id}: batch of {len(steps)} not submitted: projected ${est['projected_usd']:.2f} exceeds "
                f"the ${est['remaining_usd']:.2f} left under the cap (a submitted batch cannot be stopped). "
                "Raise run.spend_cap_usd to continue.")
        file_id = batch.upload(m.provider, reqs)   # OpenAI only; creates no batch
        rec = {"intent_at": time.time(), "status": "INTENT", "provider": m.provider, "model": m.model,
               "steps": steps, "count": len(steps), "input_file_id": file_id, "batch_id": None,
               "estimate": est, "prompt_chars": shape["chars"], "ingested": [],
               "cache_requested": m.provider == "anthropic" and (m.cache_system or bool(m.cache_payload))}
        self._save(self._records() + [rec])           # intent first: a crash after create stays recoverable
        rec["batch_id"] = batch.create(m.provider, reqs, file_id)
        rec["status"] = "SUBMITTED"
        self._update(rec)
        self.run.prov.tool_run("batch_submitted", self.agent_id, {k: rec[k] for k in
                                                                 ("batch_id", "provider", "model", "count", "estimate")})
        return rec

    def _recover(self, rec: dict) -> str | None:
        """The batch an INTENT record created, if any: OpenAI by its unique input file, Anthropic by
        creation time (within 15 minutes of the intent) and item count. Ambiguity stops the run."""
        known = {r["batch_id"] for r in self._records() if r.get("batch_id")}
        found = [b for b in batch.recent(rec["provider"], 50) if b["id"] not in known and (
            b["input_file_id"] == rec["input_file_id"] if rec["provider"] == "openai" else
            rec["intent_at"] - 120 <= b["created_at"] <= rec["intent_at"] + 900 and b["total"] == rec["count"])]
        if len(found) > 1:
            from .orchestrator import Pause
            raise Pause(f"{self.agent_id}: cannot tell which batch the interrupted submission created "
                        f"({', '.join(b['id'] for b in found)}). Check them in the vendor console, then set "
                        f"batch_id in {self.state_path} and rerun.")
        return found[0]["id"] if found else None

    # --- waiting and ingesting ---------------------------------------------------
    def _finish(self, rec: dict) -> None:
        if rec["status"] == "INTENT":
            rec["batch_id"] = self._recover(rec)
            rec["status"] = "SUBMITTED" if rec["batch_id"] else "NOT_CREATED"
            self._update(rec)
            if not rec["batch_id"]:
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
        repair: list[str] = []
        counts = {"succeeded": 0, "refused": 0, "repair": 0, "resubmit": 0}
        for it in batch.results(rec["provider"], rec["batch_id"], rec["model"]):
            step = it.custom_id
            if step in ingested or step not in self.payloads:
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
