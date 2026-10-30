"""The comparative-table rule for contrary evidence (researcher's decision of 2026-10-30).

The table is a selective synthesis, not an inventory. Every displayed conclusion accounts for its material contrary
evidence (in the row's set, or linked to the prose); contrary findings left out stay mandatory and must be carried
by a written element, rendered in cited A10-verified prose, or excluded by the researcher with a recorded
justification; comparability is recorded so different systems, doses or arms are not set up as like-for-like;
A10 GLOBAL sees each contrary finding's register entry; and release is blocked until every one is accounted for.
"""
import copy
import json
import re

import pytest

from bridge_fixtures import compact_package, fixture_plan, tagged_text
from litreview import bridge, checkpoints, config, verification_job
from litreview import orchestrator as orch
from test_bridge import Agents, make_run, outline_and_approve

BCFG = config.load("pipeline")["bridge"]
JOURNAL = config.load("journal_scirev")


@pytest.fixture(scope="module")
def fx():
    data = compact_package(120)
    data["table"] = bridge.comparative_table(data["pkg"], data["findings"], data["corpus"], BCFG["table_max_rows"])
    data["plan"], data["ledger"] = fixture_plan(data["pkg"], data["corpus"], data["table"])
    data["register"] = bridge.contrary_register(data["pkg"], data["findings"], data["table"], data["plan"], data["ledger"])
    return data


# ------------------------------------------------------------------ the table
def test_every_displayed_conclusion_shows_or_links_its_contrary_evidence(fx):
    t = fx["table"]
    assert len(t["columns"]) == 7 and t["columns"][4] == "Role and contrary evidence"
    rows = dict(zip(t["row_finding_ids"], t["rows"]))
    sel = {s["finding_id"]: s for s in t["row_selection"]}
    contrary = set(t["contrary_finding_ids"])
    for e in fx["register"]:
        for c in e["challenges"]:
            if c["finding_id"] in rows:   # a supporting row is shown: its contrary finding is shown, in the same set
                assert e["in_table"], f"{c['finding_id']} shown without {e['finding_id']}"
                letter = sel[c["finding_id"]]["contrary_set"]
                assert letter and sel[e["finding_id"]]["contrary_set"] == letter
                assert f"set {letter}" in rows[c["finding_id"]][4] and f"set {letter}" in rows[e["finding_id"]][4]
    for fid, row in rows.items():
        role = row[4]
        assert ("contrary evidence" in role) and not re.search(r"\d", role)     # no numbers for A10 to chase
        if fid in contrary and not sel[fid]["contrary_set"]:
            assert "discussed in the text" in role
        if sel[fid]["further_contrary_in_text"]:
            assert "further contrary evidence is discussed in the text" in role
    assert bridge.contrary_problems(fx["register"], t) == []


def test_reader_table_says_selective_and_where_omitted_contrary_evidence_is_discussed(fx):
    t = fx["table"]
    hidden = len(t["contrary_findings_not_shown"])
    assert hidden > 0                                             # the 120-paper case: more contrary than one page
    out = bridge.reader_table(t, fx["corpus"], ["Clinical evidence", "Copper dependence"])
    assert "not a summary of every study reviewed" in out["notes"][0] and "set letter" in out["notes"][0]
    assert out["notes"][1] == (f"{hidden} further contrary findings are discussed in the text rather than shown here, "
                               "in: Clinical evidence; Copper dependence.")


# ------------------------------------------------------------------ the register and the plan
def test_register_lists_every_contrary_finding_with_carriers_and_comparability(fx):
    reg = {e["finding_id"]: e for e in fx["register"]}
    assert list(reg) == fx["table"]["contrary_finding_ids"]
    fby = {f["finding_id"]: f for f in fx["findings"]}
    omitted = [e for e in fx["register"] if not e["in_table"]]
    assert len(omitted) == len(fx["table"]["contrary_findings_not_shown"])
    for e in omitted:                     # every omitted contrary finding stays mandatory and is written somewhere
        assert e["reasons"] and e["carried_by"] and e["written_by"] and e["sections"]
    pairs = [(e, c) for e in fx["register"] for c in e["challenges"]]
    assert pairs
    for e, c in pairs:                    # comparability names exactly the context fields that differ
        a, b = fby[e["finding_id"]].get("context") or {}, fby[c["finding_id"]].get("context") or {}
        for k in c["differs"]:
            assert k in bridge.COMPARABILITY_KEYS and a.get(k) != b.get(k)
        unreported = lambda v: v in (None, "") or str(v).strip().upper() in ("NOT_REPORTED", "NOT_APPLICABLE")
        for k in bridge.COMPARABILITY_KEYS:          # anything not named is equal, or unreported in both
            if k not in c["differs"] + c["not_reported_for_one"]:
                assert a.get(k) == b.get(k) or (unreported(a.get(k)) and unreported(b.get(k)))


def test_plan_refused_when_an_omitted_contrary_finding_has_no_written_carrier(fx):
    e = next(e for e in fx["register"] if not e["in_table"])
    ledger = copy.deepcopy(fx["ledger"])
    plan = copy.deepcopy(fx["plan"])
    gone = set(e["carried_by"])
    for x in ledger:
        if x["item_id"] in gone:
            x.update(outcome="NOT_INDIVIDUALLY_DISCUSSED", reason="test", section_id=None, grouped_with=[])
    for s in plan["sections"]:
        s["ordered_items"] = [it for it in s["ordered_items"] if it["item_id"] not in gone]
    problems, report = bridge.validate_plan(plan, ledger, fx["pkg"], fx["corpus"], fx["table"], JOURNAL, BCFG,
                                            fx["findings"])
    assert any(p.startswith(f"CONTRARY_NOT_CARRIED: {e['finding_id']}") for p in problems)
    ok, report = bridge.validate_plan(fx["plan"], fx["ledger"], fx["pkg"], fx["corpus"], fx["table"], JOURNAL, BCFG,
                                      fx["findings"])
    assert ok == [] and set(report["contrary_evidence"]["not_in_table"]) == set(fx["table"]["contrary_findings_not_shown"])


def test_packets_carry_contrary_entries_with_comparability(fx):
    packets = bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], fx["findings"], fx["corpus"], fx["register"])
    seen = {c["finding_id"] for p in packets.values() for c in p["contrary_evidence"]}
    assert {e["finding_id"] for e in fx["register"] if not e["in_table"]} <= seen
    for p in packets.values():
        for c in p["contrary_evidence"]:
            assert c["finding_id"] in p["findings"]                  # the values compared are in the packet
            for ch in c["challenges"]:
                assert {"differs", "not_reported_for_one", "evidence_class"} <= set(ch)


# ------------------------------------------------------------------ release accounting
def _report(occurrences, verdict="VERIFIED"):
    return {"occurrence_inventory": occurrences,
            "verdicts": [{"occurrence_id": o["occurrence_id"], "verdict": verdict, "evidence_finding_ids": []}
                         for o in occurrences]}


def _occ(oid, items, cites, path=("manuscript", "sections", 0, "text_markdown")):
    return {"occurrence_id": oid, "path": list(path), "item_ids": items, "citation_record_ids": cites}


def test_release_accounting_requires_cited_verified_prose_or_a_justified_exclusion(fx):
    e = next(e for e in fx["register"] if not e["in_table"])
    reg, carrier, rid = [e], e["carried_by"][0], e["record_id"]
    table = fx["table"]
    ok = bridge.contrary_accounting(reg, _report([_occ("OC-1", [carrier], [rid])]), table)
    assert ok["counts"]["ADDRESSED_IN_PROSE"] == 1 and not ok["release_blocked"]
    for report in (_report([_occ("OC-1", [carrier], [])]),                       # tagged, paper not cited
                   _report([_occ("OC-1", ["P-unrelated"], [rid])]),              # cited, no carrier tagged
                   _report([_occ("OC-1", [carrier], [rid])], "DEFECT"),          # A10 did not verify it
                   _report([_occ("OC-1", [carrier], [rid], ("manuscript", "abstract"))])):   # not body prose
        acc = bridge.contrary_accounting(reg, report, table)
        assert acc["unaddressed"] == [e["finding_id"]] and acc["release_blocked"]
    ex = bridge.contrary_accounting(reg, _report([]), table, {e["finding_id"]: "Different compound class; see notes."})
    assert ex["counts"]["EXCLUSION_APPROVED"] == 1 and not ex["release_blocked"]
    shown = next(x for x in fx["register"] if x["in_table"])
    assert bridge.contrary_accounting([shown], _report([]), table)["counts"]["SHOWN_IN_TABLE"] == 1


def test_release_accounting_detects_a_table_that_conceals_contrary_evidence(fx):
    pair = next((e, c) for e in fx["register"] if e["in_table"] for c in e["challenges"] if c["in_table"])
    tampered = {**fx["table"], "row_finding_ids": [f for f in fx["table"]["row_finding_ids"] if f != pair[0]["finding_id"]]}
    acc = bridge.contrary_accounting(fx["register"], _report([]), tampered,
                                     {e["finding_id"]: "x" * 30 for e in fx["register"]})
    assert acc["table_conceals"] and acc["release_blocked"]


# ------------------------------------------------------------------ A10
def test_a10_global_pages_carry_register_entries_and_contrary_codes_keep_their_floor(fx):
    entry = fx["register"][0]

    class Reg:
        findings = {entry["finding_id"]: {}, "R9999:F1": {}}

        def index_line(self, fid):
            return f"line {fid}"
    job = verification_job.VerificationJob.__new__(verification_job.VerificationJob)
    job.contrary = {entry["finding_id"]: {"in_table": entry["in_table"]}}
    job.registry, job.package, job.cfg = Reg(), {}, {"max_global_entries_per_page": 128}
    job.admitted = lambda mode, payload: True
    job.global_payload = lambda page, verdicts: {}
    page = next(job.global_pages([]))
    by_id = {p["id"]: p for p in page}
    assert by_id[entry["finding_id"]]["contrary_evidence"] == {"in_table": entry["in_table"]}
    assert "contrary_evidence" not in by_id["R9999:F1"]
    issues = [{"code": "CONTRARY_EVIDENCE_UNADDRESSED", "severity": "MINOR", "occurrence_ids": ["OC-1"], "finding_ids": []},
              {"code": "FORCED_EQUIVALENCE", "severity": "MINOR", "occurrence_ids": ["OC-1"], "finding_ids": []}]
    job.validate_issues(issues, {"OC-1"}, set())
    assert [i["severity"] for i in issues] == ["BLOCKING", "MAJOR"]


# ------------------------------------------------------------------ the release gate in a run
def test_release_blocks_until_contrary_evidence_is_addressed_or_justifiably_excluded(tmp_path, monkeypatch, fx):
    """A writer that drops citations (first three papers per sentence) leaves contrary findings tagged but uncited:
    release pauses at CP_CONTRARY; a justification is required; the approval is recorded in provenance."""
    run = make_run(tmp_path, monkeypatch, fx)

    def truncating(agent, payload, step, out):
        if agent == "A09-WRI" and payload["mode"] == "SECTION":
            out["section"]["text_markdown"] = tagged_text(payload["section_packet"], max_citations=3)
        return out
    agents = Agents(run, fx, hook=truncating)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    assert run.stage_draft(run.state()) == "review_loop"
    assert run.stage_review_loop(run.state()) == "finish_edit"
    assert run.stage_finish_edit(run.state()) == "finalize"
    with pytest.raises(orch.Pause, match="CP_CONTRARY"):      # completion is blocked, before any export
        run.stage_finalize(run.state())
    assert not (run.dir / "final").exists()
    rel = run.load("bridge/contrary_release.json")
    assert rel["unaddressed"] and rel["release_blocked"]
    d = checkpoints.cp_dir(run.dir)
    decision = json.loads((d / "CP_CONTRARY_decision.json").read_text(encoding="utf-8"))
    decision["exclusions"] = [{"finding_id": f, "justification": "too short"} for f in rel["unaddressed"]]
    (d / "CP_CONTRARY_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    with pytest.raises(checkpoints.DecisionIncomplete, match="justification"):
        checkpoints.approve(run.dir, "CP_CONTRARY", run.prov)
    decision["exclusions"] = [{"finding_id": f, "justification": "Different compound and system; discussed by the "
                                                                 "authors elsewhere; not material to the table's claims."}
                              for f in rel["unaddressed"]]
    (d / "CP_CONTRARY_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    checkpoints.approve(run.dir, "CP_CONTRARY", run.prov)
    run._contrary_release(run._current(), run.load("rv_final.json"))       # the gate finalize runs first now passes
    rel = run.load("bridge/contrary_release.json")
    assert rel["counts"]["EXCLUSION_APPROVED"] == len(decision["exclusions"]) and not rel["release_blocked"]
    assert any(e["type"] == "human_decision" and e.get("checkpoint") == "CP_CONTRARY" for e in run.prov.events())


def test_complete_writer_releases_with_every_contrary_finding_accounted_for(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    agents = Agents(run, fx)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    run.stage_draft(run.state())
    run.stage_review_loop(run.state())
    assert run.stage_finish_edit(run.state()) == "finalize"
    run._contrary_release(run._current(), run.load("rv_final.json"))
    rel = run.load("bridge/contrary_release.json")
    assert rel["unaddressed"] == [] and rel["counts"]["EXCLUSION_APPROVED"] == 0
    assert rel["counts"]["SHOWN_IN_TABLE"] + rel["counts"]["ADDRESSED_IN_PROSE"] == len(fx["table"]["contrary_finding_ids"])
