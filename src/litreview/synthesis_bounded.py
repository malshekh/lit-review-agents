"""Registry-backed A07. Every accepted turn is complete, bounded and journaled.

Reconciliation resolves bookkeeping/overlap, never decides scientific truth by vote.
Scientific contradictions remain explicit limitations; unsupported interpretations stop the job.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema

from .evidence import link_problems, normalized_proposition, status_of
from .paths import SCHEMAS_DIR
from .synthesis_job import JobStopped, SynthesisJob, COVERAGE_NOTE
from .synthesis_registry import canonical, fingerprint, chunks, compact_proposition


class AlignmentRequired(JobStopped):
    """The human thematic decision has not been made for these exact inputs."""


class RegistrySynthesisJob(SynthesisJob):
    def __init__(self, job_dir, registry, call, count, cfg, identity, approve,
                 served_by=lambda: None):
        self.registry, self.approve = registry, approve
        self.identity = fingerprint({"registry": registry.digest, "execution": identity, "settings": cfg})
        directory = Path(job_dir)
        directory.mkdir(parents=True, exist_ok=True)
        ipath = directory / "identity.json"
        if ipath.exists() and json.loads(ipath.read_text(encoding="utf-8"))["fingerprint"] != self.identity:
            raise JobStopped("stale synthesis identity: corpus, themes, prompt, schema or settings changed")
        if not ipath.exists() and (directory / "ledger.jsonl").exists():
            raise JobStopped("legacy synthesis cannot be adopted without an input fingerprint")
        ipath.write_text(canonical({"fingerprint": self.identity}), encoding="utf-8")
        snapshot = directory / "registry.json"
        if snapshot.exists() and fingerprint(json.loads(snapshot.read_text(encoding="utf-8"))) != registry.digest:
            raise JobStopped("registry snapshot hash mismatch")
        if not snapshot.exists():
            snapshot.write_text(canonical(registry.corpus), encoding="utf-8")
        super().__init__(directory, registry.items, list(registry.findings), registry.record_of,
                         call, count, cfg, served_by, findings=registry.findings)
        self.packets = self._packets()

    def _packets(self):
        queue = self.registry.packets(self.cfg.get("max_findings_per_group", 24), self.cfg.get("max_items_per_group", 8))
        out = []
        while queue:
            p = queue.pop(0)
            if self.count(self.registry.packet_payload(p)) + self.limit("GROUP") <= self.cfg["context_ceiling_tokens"]:
                out.append(p)
                continue
            key = "finding_ids" if len(p["finding_ids"]) > 1 else "manifest_item_ids"
            if len(p[key]) < 2:
                raise JobStopped("one evidence unit exceeds context admission; source must be inspected, never truncated")
            halves = chunks(p[key], (len(p[key]) + 1) // 2)
            for n, half in reversed(list(enumerate(halves))):
                q = {**p, key: half}
                if key == "finding_ids" and n:
                    q["manifest_item_ids"] = []
                queue.insert(0, q)
        for n, p in enumerate(out, 1):
            p["group_id"] = f"G{n:04d}"
        return out

    def limit(self, mode):
        return int(self.cfg.get("output_limits", {}).get(mode, self.cfg.get("max_tokens_per_turn", 12000)))

    def _committed(self, turn):
        out = super()._committed(turn)
        if out is not None:
            marker = next((e for e in self.ledger.events() if e["event"] == "TURN_ACCEPTED" and e["turn"] == turn), None)
            if not marker or fingerprint(out) != marker["output_sha256"]:
                raise JobStopped(f"accepted turn hash mismatch: {turn}")
        return out

    def _commit(self, turn, output, staged):
        # One commit event carries all effects. No orphaned staging effects can be replayed twice.
        path = self._turn_file(turn)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(canonical(output), encoding="utf-8")
        os.replace(tmp, path)
        self.ledger.append({"event": "TURN_ACCEPTED", "turn": turn, "model": self.served_by(),
                            "output_sha256": fingerprint(output), **staged})

    @staticmethod
    def empty():
        return {"accepted": [], "rejected": [], "satisfied": {}, "failed": [], "duplicates": 0, "finding_uses": []}

    def _run_turn(self, mode, turn, payload):
        projected = self.count(payload) + self.limit(mode)
        self.peak_projected = max(self.peak_projected, projected)
        if projected > self.cfg["context_ceiling_tokens"]:
            raise JobStopped(f"{turn}: context admission {projected} exceeds {self.cfg['context_ceiling_tokens']}")
        try:
            out = self.call(mode, payload, turn)
            schema = json.loads((SCHEMAS_DIR / f"A07-SYN.bounded-{mode.lower()}.schema.json").read_text(encoding="utf-8"))
            jsonschema.validate(out, schema)
            if out["mode"] != mode or out["status"] not in ("COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_EVIDENCE"):
                raise ValueError("incomplete or mismatched synthesis response")
            # Schema bounds also apply to mocked/offline models. Never accept an oversized response.
            from .synthesis_registry import offline_tokens
            if offline_tokens(out) > self.limit(mode):
                raise ValueError("response exceeds conservative output allowance")
            self.ledger.append({"event": "CALL_VALIDATED", "turn": turn, "mode": mode,
                                "input_upper_tokens": self.count(payload),
                                "response_upper_tokens": offline_tokens(out), "output_cap": self.limit(mode)})
            return out
        except (ValueError, jsonschema.ValidationError) as exc:
            self.ledger.append({"event": "TURN_REJECTED", "turn": turn, "reason": str(exc)[:400]})
            raise JobStopped(f"{turn}: invalid response: {str(exc)[:400]}") from exc
        except Exception as exc:
            from .agents import AgentError
            if isinstance(exc, AgentError):
                self.ledger.append({"event": "TURN_REJECTED", "turn": turn, "reason": str(exc)[:400]})
                raise JobStopped(f"{turn}: {exc}") from exc
            raise

    def plan(self):
        done = self._committed("PLAN")
        if done:
            return done
        out = self._run_turn("PLAN", "PLAN", self.registry.plan_payload(self.packets))
        if out["status"] == "NEEDS_EVIDENCE":
            raise JobStopped("PLAN must complete or explicitly stop for human review")
        for change in out["theme_change_proposals"]:
            if not change["finding_ids"] or set(change["finding_ids"]) - self.finding_ids:
                raise JobStopped("thematic proposal lacks valid evidence anchors")
        out["groups"] = self.packets
        self._commit("PLAN", out, self.empty())
        return out

    def _with_retrieval(self, mode, turn, payload):
        retrieved = set()
        for n in range(self.cfg.get("max_retrieval_rounds", 2) + 1):
            key = f"{turn}_LOOKUP{n}"
            request = {**payload, "retrieved_evidence": self.registry.details(sorted(retrieved))}
            out = self._committed(key) or self._run_turn(mode, key, request)
            if out["status"] != "NEEDS_EVIDENCE":
                return out, retrieved
            if n == self.cfg.get("max_retrieval_rounds", 2):
                raise JobStopped(f"{turn}: retrieval limit reached; evidence need remains unresolved")
            try:
                found = self.registry.retrieve(out["retrieval_requests"], self.cfg.get("retrieval_limit", 12))
            except ValueError as exc:
                raise JobStopped(str(exc)) from exc
            if not self._committed(key):
                self._commit(key, out, self.empty())
            retrieved.update(found)
        raise AssertionError("unreachable")

    def _science(self, turn, out, visible, item_ids):
        if out["status"] == "NEEDS_EVIDENCE":
            raise JobStopped("unresolved retrieval")
        props = []
        for n, raw in enumerate(out.get("propositions", []), 1):
            p = {**raw, "proposition_id": f"{turn}.P{n}"}
            if p["type"] not in ("SOURCE_GROUNDED", "CLAIM_APPRAISAL", "THEME_GROUNDED", "REPORTING_ONLY_INTEGRATION"):
                raise JobStopped("unsupported proposition type")
            problems = link_problems(p, self.records, self.record_of)
            linked = {x["finding_id"] for x in p.get("evidence", [])}
            source_ids = set(p.get("source_item_ids", []))
            if problems or linked - visible or source_ids - set(item_ids) or set(p["satisfies"]) - set(item_ids):
                raise JobStopped(f"invalid evidence or source links: {problems}")
            if p["type"] in ("THEME_GROUNDED", "REPORTING_ONLY_INTEGRATION") and not (linked or source_ids):
                raise JobStopped("unbacked thematic proposition")
            if p["type"] == "THEME_GROUNDED" and not source_ids:
                raise JobStopped("thematic proposition must name its A06 source item")
            if p["type"] == "THEME_GROUNDED" and any(self.mandatory[i]["kind"] not in ("CONFLICT", "EVIDENCE_REACH", "SYSTEM_GAP") for i in source_ids):
                raise JobStopped("thematic proposition must bind a thematic A06 record, not a publication")
            p = normalized_proposition(p)
            p["citation_record_ids"] = sorted({self.record_of[f] for f in linked})
            p["independence"] = self.registry.independence(linked)
            p["independent_source_count"] = None
            p["independent_studies"] = None
            p["papers"] = p["independence"]["papers"]
            p["constraints"] = [f"{f}: {c}" for f in sorted(linked) for c in self.records[f].get("constraints", [])]
            p["ceiling"] = {f: self.records[f].get("disposition") for f in sorted(linked)}
            p["context_qualifiers"] = {f: self.registry.contexts.get(self.records[f].get("context_id")) for f in sorted(linked)}
            p["evidence_qualifiers"] = {f: {k: self.records[f].get(k) for k in
                ("direction", "polarity", "modality", "assertion_type", "attributed_to", "context_id", "plain_language_limit")}
                for f in sorted(linked)}
            props.append(p)
        if len(props) > self.cfg.get("max_propositions_per_group", 12):
            raise JobStopped("proposition output bound exceeded")
        # Reuse evidence-role enforcement and the global coverage ledger, but reject the ENTIRE response
        # on any invalid proposition rather than silently accepting a subset.
        staged, kept, gaps = self._validate(turn, props, out.get("knowledge_gaps", []), [])
        if staged["rejected"] or staged["failed"]:
            raise JobStopped(f"atomic turn rejected: {staged['rejected'] or staged['failed']}")
        return staged, kept, gaps

    def _claims(self, element, eid, cited, items, staged, narrative, gap=False):
        source_ids = set(element.get("source_item_ids", []))
        for iid in element.get("satisfies", []):
            if iid not in self.mandatory:
                raise JobStopped("unknown mandatory item")
            item = self.mandatory[iid]
            if item["kind"] != "SELECTED_PAPER" and iid not in source_ids:
                raise JobStopped("coverage claim lacks source-item binding")
            anchors = self.registry.item_findings(iid)
            if anchors and not anchors & set(cited) and not gap:
                raise JobStopped("coverage claim does not reference its evidence")
            if item["kind"] == "SELECTED_PAPER" and gap:
                if iid not in source_ids:
                    raise JobStopped("paper gap must bind its source record")
                eligible = [f for f in self.finding_ids if self.record_of[f] == item["record_id"]
                            and status_of(self.records[f]) in ("SUPPORTING", "NOT_ESTABLISHED")]
                if eligible:
                    raise JobStopped("a paper with usable findings cannot be covered solely by an insufficient-evidence gap")
                staged["satisfied"][iid] = eid
                items[iid] = "SATISFIED"
                continue
            super()._claims(element, eid, cited, items, staged, narrative, gap)

    def group(self, packet):
        turn = f"GROUP_{packet['group_id']}"
        if self._committed(turn):
            return
        out, retrieved = self._with_retrieval("GROUP", turn, self.registry.packet_payload(packet))
        visible = set(packet["finding_ids"]) | retrieved
        for gap in out["knowledge_gaps"]:
            if (set(gap["source_item_ids"]) | set(gap["satisfies"])) - set(packet["manifest_item_ids"]):
                raise JobStopped("gap cites unknown or unseen source item")
            if not gap["source_item_ids"] and not gap["established_by"]:
                raise JobStopped("unbacked knowledge gap")
            for fid in gap["established_by"]:
                if fid not in visible or status_of(self.records.get(fid, {})) != "SUPPORTING":
                    raise JobStopped("gap uses unknown, unseen or ineligible evidence")
            gap["gap_id"] = f"{turn}.K{out['knowledge_gaps'].index(gap)+1}"
            gap["citation_record_ids"] = sorted({self.mandatory[i]["record_id"] for i in gap["source_item_ids"]
                                                  if self.mandatory[i].get("record_id")})
        staged, props, gaps = self._science(turn, out, visible, packet["manifest_item_ids"])
        for p in props:
            p["primary_theme_id"] = packet["primary_theme_id"]
        used = {x["finding_id"] for p in props for x in p["evidence"]}
        used |= {fid for g in gaps for fid in g["established_by"]}
        unused = {x["finding_id"]: x["reason"] for x in out["findings_not_used"]}
        if set(unused) - set(packet["finding_ids"]) or any(not reason.strip() for reason in unused.values()):
            raise JobStopped("invalid unused finding declaration")
        missing = {f for f in packet["finding_ids"] if status_of(self.records[f]) in ("SUPPORTING", "NOT_ESTABLISHED")} - used - set(unused)
        if missing:
            raise JobStopped(f"packet evidence unaccounted: {sorted(missing)}")
        if set(unused) & used:
            raise JobStopped("finding declared both used and unused")
        for fid in unused:
            staged["finding_uses"].append((fid, "UNUSED"))
        for fid in used:
            if not any(f == fid for f, _ in staged["finding_uses"]):
                staged["finding_uses"].append((fid, "GAP"))
        self._commit(turn, {**out, "propositions": props, "knowledge_gaps": gaps,
                            "_group_id": packet["group_id"]}, staged)

    def _all_props(self):
        return [p for t in self.ledger.state()["committed"] if t.startswith("GROUP_") and "_LOOKUP" not in t
                for p in self._committed(t).get("propositions", [])]

    def reconciliation_payloads(self):
        props = self._all_props()
        index = [compact_proposition(p) for p in props]
        for n, focus in enumerate(chunks(index, self.cfg.get("reconcile_page_size", 32)), 1):
            yield f"RECONCILE_{n:04d}", {"mode": "RECONCILE", "focus": focus, "global_proposition_index": index,
                    "global_independence": self.registry.independence(self.finding_ids),
                    "mandatory_conflict_index": [{"item_id": i, "findings": sorted(self.registry.item_findings(i))}
                                                 for i in self.mandatory if self.mandatory[i]["kind"] == "CONFLICT"],
                    "retrieval": {"available": True, "operations": ["finding_ids", "query"]}}

    def reconcile(self):
        props = {p["proposition_id"]: p for p in self._all_props()}
        for turn, payload in self.reconciliation_payloads():
            if self._committed(turn):
                continue
            out, retrieved = self._with_retrieval("RECONCILE", turn, payload)
            focus = {p["proposition_id"] for p in payload["focus"]}
            reviewed = [r["proposition_id"] for r in out["reviews"]]
            if set(reviewed) != focus or len(reviewed) != len(focus):
                raise JobStopped("global reconciliation did not review every focal proposition exactly once")
            issue_ids = set()
            for issue in out["issues"]:
                related = set(issue["proposition_ids"])
                if not related or related - set(props) or not related & focus:
                    raise JobStopped("reconciliation issue has invalid proposition references")
                anchors = set(issue["finding_ids"])
                if not anchors or anchors - retrieved:
                    raise JobStopped("reconciliation issue lacks evidence anchors")
                for pid in related:
                    linked = {e["finding_id"] for e in props[pid].get("evidence", [])}
                    if linked and not anchors & linked:
                        raise JobStopped("reconciliation issue lacks referenced proposition evidence")
                if issue["kind"] == "UNSUPPORTED_INTERPRETATION":
                    raise JobStopped("unsupported interpretation: human/upstream review required")
                issue["issue_id"] = "RC-" + fingerprint({"kind": issue["kind"], "propositions": sorted(related),
                                                        "findings": sorted(anchors), "limitation": issue["limitation"]})[:16]
                issue_ids.add(issue["issue_id"])
            if any(r["outcome"] == "ISSUES_IDENTIFIED" and not any(r["proposition_id"] in i["proposition_ids"] for i in out["issues"])
                   for r in out["reviews"]):
                raise JobStopped("reconciliation flagged an issue without recording it")
            self._commit(turn, out, self.empty())

    def final_payload(self):
        return {"mode": "FINAL", "proposition_index": [compact_proposition(p) for p in self._all_props()],
                "reconciliation": self._issues(), "coverage_pending": self._pending(),
                "theme_framework": self.registry.framework,
                "knowledge_gap_index": [{k: g[k] for k in ("gap_id", "statement", "source_item_ids", "established_by")}
                                        for g in self._gaps()]}

    def final(self):
        if self._committed("FINAL"):
            return self._committed("FINAL")
        if self._pending():
            raise JobStopped("mandatory coverage incomplete; FINAL and CP3 are blocked")
        out = self._run_turn("FINAL", "FINAL", self.final_payload())
        if out["status"] == "NEEDS_EVIDENCE":
            raise JobStopped("FINAL cannot add evidence; return to synthesis")
        ids = {p["proposition_id"] for p in self._all_props()}
        for thesis in out["thesis_options"]:
            if not thesis["proposition_ids"] or set(thesis["proposition_ids"]) - ids:
                raise JobStopped("thesis lacks valid proposition premises")
        for pi in out["proposed_interpretations"]:
            if not pi["premise_proposition_ids"] or set(pi["premise_proposition_ids"]) - ids:
                raise JobStopped("interpretation lacks valid proposition premises")
        for binding in out["beyond_prose_bindings"]:
            if not binding["proposition_ids"] or set(binding["proposition_ids"]) - ids:
                raise JobStopped("non-prose claim lacks valid proposition premises")
        self._commit("FINAL", out, self.empty())
        return out

    def _issues(self):
        issues = {}
        for t in self.ledger.state()["committed"]:
            if t.startswith("RECONCILE_") and "_LOOKUP" not in t:
                for i in self._committed(t)["issues"]:
                    issues[i["issue_id"]] = i
        return list(issues.values())

    def _gaps(self):
        return [g for t in self.ledger.state()["committed"] if t.startswith("GROUP_") and "_LOOKUP" not in t
                for g in self._committed(t).get("knowledge_gaps", [])]

    def run(self):
        plan = self.plan()
        if not self.approve(self.identity, {**self.registry.alignment(self.packets),
                                          "planning": plan, "fingerprint": self.identity}):
            raise AlignmentRequired("CP_SYN thematic alignment approval required before GROUP calls")
        for packet in self.packets:
            self.group(packet)
        self.reconcile()
        self.final()
        pkg = self.assemble()
        if pkg["status"] != "COMPLETE":
            raise JobStopped("global evidence accounting incomplete; CP3 blocked")
        return pkg

    def assemble(self):
        pkg = super().assemble()
        props = self._all_props()
        issues = self._issues()
        for p in props:
            p["reconciliation_issue_ids"] = [i["issue_id"] for i in issues if p["proposition_id"] in i["proposition_ids"]]
            p["scientific_limitations"] = [i["limitation"] for i in issues if p["proposition_id"] in i["proposition_ids"]]
            p["constraints"] += [f"Global reconciliation: {limit}" for limit in p["scientific_limitations"]]
        # Packet boundaries never become manuscript sections or newly approved primary themes.
        groups = [{"group_id": tid, "primary_theme_id": tid, "name": theme.get("name", tid),
                   "kind": "REPORTING_ONLY_THEME", "basis": "researcher-approved primary theme",
                   "proposition_ids": [p["proposition_id"] for p in props if p.get("primary_theme_id") == tid]}
                  for tid, theme in self.registry.themes.items()]
        used_sources = {i for p in props for i in p.get("source_item_ids", [])}
        used_sources |= {i for g in self._gaps() for i in g.get("source_item_ids", [])}
        pkg.update(propositions=props, knowledge_gaps=self._gaps(), reconciliation=issues,
                   groups=groups, unmapped_proposition_ids=[p["proposition_id"] for p in props if p.get("primary_theme_id") == "UNMAPPED"],
                   source_items={i: self.registry.item_source(i) for i in sorted(used_sources)},
                   theme_framework=self.registry.framework,
                   manifest_aliases={i: m["original_item_id"] for i, m in self.mandatory.items()},
                   registry_fingerprint=self.registry.digest, execution_fingerprint=self.identity,
                   global_independence=self.registry.independence(self.finding_ids), coverage_note=COVERAGE_NOTE)
        pkg["findings_not_used"] = [u for t in self.ledger.state()["committed"]
                                    if t.startswith("GROUP_") and "_LOOKUP" not in t
                                    for u in self._committed(t).get("findings_not_used", [])]
        completed = set(self.ledger.state()["committed"])
        needed = {t for t, _ in self.reconciliation_payloads()} if props else set()
        if "FINAL" not in completed or not needed <= completed:
            pkg["status"] = "INCOMPLETE"
        return pkg
