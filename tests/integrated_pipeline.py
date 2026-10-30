"""Integrated offline simulation of the merged pipeline, from A07 to final release. Evaluation-only.

    python -B tests/integrated_pipeline.py [papers]      # default 120; writes docs/integration_validation/simulation_<n>.json

Real code throughout: the bounded A07 job (RegistrySynthesisJob), CP3 approval bound to the package fingerprint
(Task 1), the bridge's outline, CP_LEDGER, sequential writing with its gates, integration, critique and editing
stages (Task 2), the bounded A10 job through the orchestrator (VerificationJob), and final-release enforcement.
Spend controls stay live (projection, admission, long-context check, runtime gate, reservations) with simulation
limits, since nothing is spent. Only model outputs are scripted: FixtureModel (A07; mechanical, not synthesis),
ScriptedVerifier (A10; supplied verdicts, never discoveries) and scripted A08/A09/A11/A12. No network, no paid
call; final export renders nothing (the export functions are stubbed). Not a manuscript and not scientific evidence.

The corpus is the reference run's 28 papers (tests/fixtures/bridge_profile.json.gz) replicated to n with new
record IDs; replicated theme records are kept only when every paper they name is selected (the audit's
partial-cycle fixture flaw). One SUPPORTED finding is given a failed Gate 1 record, so it must stay held.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from litreview import bridge, checkpoints, config, orchestrator as orch               # noqa: E402
from litreview.agents import AgentError                                              # noqa: E402
from litreview.agents.base import validate                                           # noqa: E402
from litreview.evidence import role_allowed, status_of                               # noqa: E402
from litreview.synthesis_bounded import RegistrySynthesisJob                         # noqa: E402
from litreview.synthesis_input import build_corpus, build_manifest                   # noqa: E402
from litreview.synthesis_registry import EvidenceRegistry, fingerprint, offline_tokens  # noqa: E402
from bridge_fixtures import fixture_plan, profile, tagged_text                       # noqa: E402
from test_synthesis_bounded import FixtureModel, header                              # noqa: E402
from test_verification_job import ScriptedVerifier                                   # noqa: E402

HELD = "held by a failed Gate 1"


def _remap(value, mapping):
    if isinstance(value, str):
        return re.sub(r"\bR\d{4}\b", lambda m: mapping.get(m[0], m[0]), value)
    if isinstance(value, list):
        return [_remap(x, mapping) for x in value]
    if isinstance(value, dict):
        return {_remap(k, mapping): _remap(v, mapping) for k, v in value.items()}
    return value


def workload(n: int) -> tuple[dict, list[dict], str]:
    """(frozen A07 corpus, findings with contexts, the Gate 1-held finding ID)."""
    prof = profile()
    base = prof["corpus"]
    by_record = defaultdict(list)
    for f in prof["findings"]:
        by_record[f["record_id"]].append(f)
    selected, findings = [], []
    for i in range(n):
        original = base[i % len(base)]
        cycle = i // len(base)
        mapping = {r["record_id"]: f"R{cycle * len(base) + j + 1:04d}" for j, r in enumerate(base)}
        rec = _remap(copy.deepcopy(original), mapping)
        rec["themes"] = [f"T{i % 8 + 1}"]
        selected.append(rec)
        for old in by_record[original["record_id"]]:
            f = _remap(copy.deepcopy(old), mapping)
            f["subthemes"] = f.get("themes", [])
            f["themes"] = rec["themes"]
            f["primary_theme_id"] = rec["themes"][0]
            findings.append(f)
    present = {r["record_id"] for r in selected}
    themes = {}
    for cycle in range((n + len(base) - 1) // len(base)):
        mapping = {r["record_id"]: f"R{cycle * len(base) + j + 1:04d}" for j, r in enumerate(base)}
        for name, source in prof["theme_records"].items():
            rec = _remap(copy.deepcopy(source), mapping)
            if set(re.findall(r"\bR\d{4}\b", json.dumps(rec))) <= present:
                themes[f"replica{cycle}:{name}"] = rec
    held = next(f for f in findings if status_of(f) == "SUPPORTING" and f["disposition"] == "SUPPORTED")
    held["provenance_gate1"] = {"passed": False, "source_fingerprint": "simulated", "finding_fingerprint": "simulated"}
    assert status_of(held) == "HELD_FOR_CORRECTION"
    fw = {"version": 1, "primary_themes": [{"theme_id": f"T{i}", "name": f"Simulation theme {i}"} for i in range(1, 9)]}
    corpus = build_corpus(prof["spec_approved"], selected, findings, themes, build_manifest(selected, themes, []), fw)
    corpus["validated_findings"] = [{k: v for k, v in f.items() if k != "context"} for f in findings]
    corpus["selected_corpus"] = selected
    corpus["source_entities"] = {}
    return corpus, findings, held["finding_id"]


class SimModel(FixtureModel):
    """FixtureModel plus one global reconciliation issue across themes on the first RECONCILE page (after a
    retrieval round), so cross-theme contradictions travel through the bridge."""

    def __call__(self, mode, payload, turn):
        out = super().__call__(mode, payload, turn)
        if mode != "RECONCILE" or not turn.startswith("RECONCILE_0001"):
            return out
        focus = payload["focus"][0]
        other = next(p for p in payload["global_proposition_index"]
                     if p.get("primary_theme_id") != focus.get("primary_theme_id") and p["supporting_finding_ids"])
        anchors = [focus["supporting_finding_ids"][0], other["supporting_finding_ids"][0]]
        if not payload["retrieved_evidence"]["findings"]:
            return {**header(mode), "status": "NEEDS_EVIDENCE", "reviews": [], "issues": [],
                    "retrieval_requests": [{"finding_ids": anchors}]}
        ids = [focus["proposition_id"], other["proposition_id"]]
        out["issues"] = [{"kind": "UNRESOLVED_CONTRADICTION", "proposition_ids": ids, "finding_ids": anchors,
                          "limitation": "Simulated cross-theme contradiction; unresolved"}]
        for review in out["reviews"]:
            if review["proposition_id"] in ids:
                review["outcome"] = "ISSUES_IDENTIFIED"
        return out


class Agents:
    """Scripted A08-A12 dispatch with schema validation; A10 through ScriptedVerifier. `fail` maps a step prefix to
    the number of times it fails first (an interrupted call, billing unknown)."""

    def __init__(self, run, fail=None):
        self.run, self.fail, self.calls = run, dict(fail or {}), []
        self.verifier, self.table = ScriptedVerifier(), None

    def __call__(self, agent_id, payload, step, schema_file=None, reservation_key=None, **kw):
        assert reservation_key in self.run.budget.reservations(), f"{step}: dispatched without a reservation"
        for prefix, n in self.fail.items():
            if step.startswith(prefix) and n:
                self.fail[prefix] -= 1
                raise AgentError(f"{step}: simulated interruption (provider billing unknown)")
        self.calls.append((agent_id, step))
        if agent_id == "A10-RV":
            out = self.verifier(payload["mode"], payload, step)
        else:
            out = self.output(agent_id, payload, step)
        validate(agent_id, out, schema_file)
        return copy.deepcopy(out)

    def output(self, agent_id, payload, step):
        head = {"agent_id": agent_id, "prompt_version": "sim", "status": "COMPLETE", "warnings": [], "limitations": []}
        if agent_id == "A08-OL":
            pkg = self.run.load("synthesis_approved.json")
            plan, ledger = fixture_plan(pkg, self.run.load("selected_corpus.json"), self.table)
            return {**plan, "allocation_ledger": ledger}
        if agent_id == "A09-WRI" and payload["mode"] == "SECTION":
            p = payload["section_packet"]
            text = tagged_text(p)
            return {**head, "mode": "SECTION", "retrieval_requests": [], "plan_gaps": [], "ceiling_unclear": [],
                    "section": {"section_id": p["section_id"], "heading": p["heading"], "text_markdown": text,
                                "word_count": len(text.split())}}
        if agent_id == "A09-WRI":
            ids = payload["outline"]["abstract_plan"]["ordered_proposition_ids"]
            return {**head, "mode": "FRONT_MATTER", "title": payload["outline"]["title"]["text"],
                    "abstract": " ".join(f"Simulation abstract sentence. ⟦{i}⟧" for i in ids), "keywords": ["simulation"],
                    "table_captions": [{"display_id": "T1", "caption": "Simulation caption of the comparison. ⟦ORG⟧"}]}
        if agent_id == "A11-RC":
            decision = "MINOR_REVISION" if step.endswith("cycle1") else "ACCEPT"
            return {**head, "manuscript_version": "sim", "reader_passes": {}, "strengths": [], "concerns": [],
                    "decision": decision, "decision_rationale": "Scripted simulation critique"}
        m = copy.deepcopy(payload["manuscript"])
        if payload["mode"] == "INTEGRATION":     # an organizational transition edited: non-substantive
            for s in m.get("sections") or []:
                s["text_markdown"] = s["text_markdown"].replace("This section is organized by evidence system.",
                                                                "This section compares evidence across systems.", 1)
        out = {**head, "mode": payload["mode"], "output_manuscript_version": "edited", "change_log": [], "queries": [],
               "escalations": [], **{k: m[k] for k in ("title", "abstract", "sections") if k in m}}
        if "unit" in payload:
            out["unit"] = payload["unit"]
        return out


def _approve(run, cp, **fields):
    d = checkpoints.cp_dir(run.dir)
    decision = json.loads((d / f"{cp}_decision.json").read_text(encoding="utf-8"))
    decision.update(fields)
    (d / f"{cp}_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    checkpoints.approve(run.dir, cp, run.prov)


def _resume(run, stage, agents):
    """Run a stage; on a simulated interruption, reconcile (release the unsettled reservation, as after confirming
    no provider billing) and run it again. Returns (next stage, interruptions)."""
    interruptions = 0
    while True:
        try:
            return getattr(run, f"stage_{stage}")(run.state()), interruptions
        except (AgentError, orch.Pause) as exc:
            unsettled = [k for k in run.budget.reservations()]
            if not unsettled and not isinstance(exc, AgentError) and "verification incomplete" not in str(exc):
                raise
            for k in unsettled:
                run.budget.release(k)
            interruptions += 1
            if interruptions > 5:
                raise


def simulate(n: int, root: Path, fail: dict | None = None) -> dict:
    orch.RUNS_DIR = root
    run = orch.Run(f"sim-{n}")
    corpus, findings, held = workload(n)
    run.cfg = {**run.cfg, "batch": {**run.cfg["batch"], "gate_usd": 1e6}}   # nothing is spent; controls stay live
    run.budget.cap = 1e6
    run.save("selected_corpus.json", corpus["selected_corpus"])
    run.save("validated_findings.json", findings)
    run._findings = lambda: run.load("validated_findings.json")                # Task 1 projection tested separately
    run._prose_vendors = lambda reader: frozenset({"anthropic"})
    from litreview.tools import manuscript_export, references
    references.crossref_lookup = lambda *a, **k: None
    exported = []
    manuscript_export.render_markdown = lambda doc: exported.append(doc) or ""
    manuscript_export.render_docx = lambda doc, path: None
    agents = Agents(run, fail)
    run.agent = agents
    # --- A07 (real bounded job, scripted model) and CP3 (Task 1: approval bound to the package fingerprint)
    registry = EvidenceRegistry(corpus)
    job = RegistrySynthesisJob(run.data("synthesis_job_sim"), registry, SimModel(registry), offline_tokens,
                               run.cfg["synthesis"], {"simulation": True}, lambda *_: True)
    pkg = job.run()
    run.save("synthesis_package.json", pkg)
    run.save_state({"stage": "cp3", "status": "READY", "counters": {}})
    try:
        run.stage_cp3(run.state())
    except orch.Pause:
        pass
    _approve(run, "CP3", selected_thesis=pkg["thesis_options"][0]["option_id"])
    stage = run.stage_cp3(run.state())
    # --- bridge, writing, verification, critique, editing, release
    run.save_state({**run.state(), "stage": stage})
    agents.table = bridge.comparative_table(run.load("synthesis_approved.json"), findings, corpus["selected_corpus"])
    try:
        run.stage_outline(run.state())
    except orch.Pause:
        pass
    _approve(run, "CP_LEDGER", approve_ledger=True)
    interrupts = {}
    for stage in ("outline", "draft", "review_loop", "finish_edit", "finalize"):
        run.save_state({**run.state(), "stage": stage})
        nxt, interrupts[stage] = _resume(run, stage, agents)
    return report(run, agents, pkg, findings, held, interrupts, exported)


def report(run, agents, pkg, findings, held, interrupts, exported) -> dict:
    plan, ledger = run.load("manuscript_plan.json"), run.load("allocation_ledger.json")
    packets = bridge.section_packets(plan, ledger, run.load("synthesis_approved.json"), findings,
                                     run.load("selected_corpus.json"))
    fby = {f["finding_id"]: f for f in findings}
    in_packets = {f for p in packets.values() for f in p["findings"]}
    final = run.load("rv_final.json")
    m = run._current()
    tags_used = {i for s in m["sections"] for _, ids in bridge._sentences(s["text_markdown"]) for i in ids} - {"ORG"}
    els = bridge.elements(run.load("synthesis_approved.json"))
    bad_roles = [(e, x["finding_id"]) for e in tags_used if e in els for x in bridge._links(els[e]["record"])
                 if not role_allowed(fby.get(x["finding_id"]), x.get("role"))]
    written = {x["item_id"] for x in ledger if x["outcome"] in bridge.WRITTEN}
    table = run.load("display_items.json")[0]
    issue = (run.load("synthesis_approved.json").get("reconciliation") or [None])[0]
    placed = {it["item_id"]: s["section_id"] for s in plan["sections"] for it in s["ordered_items"]}
    admissions = [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "admission"]
    by_agent = defaultdict(lambda: {"requests": 0, "max_input_bound": 0, "all_fit": True})
    for a in admissions:
        x = by_agent[a["agent"]]
        x["requests"] += 1
        x["max_input_bound"] = max(x["max_input_bound"], a["input_bound"])
        x["all_fit"] &= a["fits"]
        x["window"] = a["window"]
    stamps = run.load("bridge/verification_stamps.json", {})
    return {
        "papers": len(run.load("selected_corpus.json")), "findings": len(findings),
        "a07": {"status": pkg["status"], "propositions": len(pkg["propositions"]), "gaps": len(pkg["knowledge_gaps"]),
                "reconciliation_issues": len(pkg["reconciliation"]), "findings_unaccounted": len(pkg["findings_unaccounted"]),
                "coverage_incomplete": len(pkg["coverage_incomplete_item_ids"])},
        "held_finding": {"id": held, "status": status_of(fby[held]), "in_any_packet": held in in_packets,
                         "in_table": held in (run.load("display_items.json")[0].get("row_finding_ids") or []),
                         "used_by_any_proposition": any(held == x["finding_id"] for p in pkg["propositions"]
                                                        for x in p["evidence"])},
        "ineligible_findings_in_packets": sorted(f for f in in_packets if status_of(fby[f]) not in ("SUPPORTING", "NOT_ESTABLISHED")),
        "manuscript_tags_with_ineligible_roles": bad_roles,
        "ledger": {o: sum(x["outcome"] == o for x in ledger) for o in bridge.OUTCOMES} | {"elements": len(els)},
        "written_elements_rendered": len(written & tags_used), "written_elements": len(written),
        "mandatory_not_written": sorted(e for e, why in bridge.mandatory_reasons(run.load("synthesis_approved.json"),
                                                                                 run.load("selected_corpus.json")).items()
                                        if why and e not in written),
        "cross_theme_issue": None if not issue else {
            "propositions": issue["proposition_ids"], "sections": sorted({placed.get(p) for p in issue["proposition_ids"]} - {None}),
            "in_each_sections_packet": all(issue["issue_id"] in {i["issue_id"] for i in packets[placed[p]]["reconciliation_issues"]}
                                           for p in issue["proposition_ids"] if p in placed)},
        "a10_final": {"execution": final.get("verification_execution"), "release": final.get("release_disposition"),
                      "coverage": final.get("coverage"), "current_for_final_manuscript": run._verification_current(final, m),
                      "stamp_matches": stamps.get(final.get("verification_fingerprint")) == run._bridge_fingerprint(m),
                      "table_occurrences": sum(o["path"][0] == "built_tables" for o in final.get("occurrence_inventory", []))},
        "table": {"rows": len(table["rows"]), "notes": table["notes"], "columns": table["columns"]},
        "contrary_release": {k: (run.load("bridge/contrary_release.json") or {}).get(k)
                             for k in ("counts", "unaddressed", "table_conceals", "release_blocked")},
        "calls": dict(sorted({a: sum(1 for x, _ in agents.calls if x == a) for a, _ in agents.calls}.items())),
        "successful_section_calls": dict(sorted(__import__("collections").Counter(
            re.search(r"_(S\d+)_r\d", s).group(1) for a, s in agents.calls
            if a == "A09-WRI" and re.search(r"_S\d+_r\d", s)).items())),
        "front_matter_calls": sum(1 for a, s in agents.calls if a == "A09-WRI" and s.endswith("_front")),
        "integration_calls": sum(1 for a, s in agents.calls if a == "A12-EDI" and "integration" in s),
        "admissions_by_agent": dict(by_agent), "interruptions": interrupts,
        "final_state": run.state().get("stage"), "exported_tables": len(exported[-1]["tables"]) if exported else 0,
        "projection": {x["stage"]: {k: x.get(k) for k in ("basis", "calls", "usd", "baseline_usd", "adverse_usd")}
                       for x in run.load("cost_projection.json")["lines"]},
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    with tempfile.TemporaryDirectory(prefix="integrated-sim-") as tmp:
        result = simulate(n, Path(tmp), fail={"A09-WRI_draft1_S3": 1, "A10-RV_draft1": 1})
    out = ROOT / "docs" / "integration_validation" / f"simulation_{n}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "projection"}, indent=1))
