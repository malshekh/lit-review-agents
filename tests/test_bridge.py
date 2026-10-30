"""The evidence-to-manuscript bridge and the downstream controls (Task 2). No model call and no network: the
writing agents are scripted (`Agents` below) and every output they return is validated against its schema.
Fixtures are evaluation-only (bridge_fixtures.py)."""
import copy
import json
import re

import jsonschema
import pytest

from bridge_fixtures import compact_package, fixture_plan, oversized_package, tagged_text
from litreview import bridge, checkpoints, config, verification_job
from litreview import orchestrator as orch
from litreview.admission import AdmissionRefused
from litreview.agents.base import validate
from litreview.evidence import status_of
from litreview.synthesis_registry import canonical, fingerprint

JOURNAL = config.load("journal_scirev")
BCFG = config.load("pipeline")["bridge"]


@pytest.fixture(scope="module")
def fx():
    data = compact_package(120)
    data["table"] = bridge.comparative_table(data["pkg"], data["findings"], data["corpus"], BCFG["table_max_rows"])
    data["plan"], data["ledger"] = fixture_plan(data["pkg"], data["corpus"], data["table"])
    return data


@pytest.fixture(scope="module")
def packets(fx):
    return bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], fx["findings"], fx["corpus"])


def els(fx):
    return bridge.elements(fx["pkg"])


# ------------------------------------------------------------------ scripted agents and a run on the fixture
class Agents:
    """Scripted A08/A09/A11/A12. Every output is validated against the schema the call names. `hook` may replace
    an output: hook(agent, payload, step, out) -> out."""

    def __init__(self, run, fx, hook=None):
        self.run, self.fx, self.hook, self.calls = run, fx, hook, []

    def __call__(self, agent_id, payload, step, schema_file=None, reservation_key=None, **kw):
        assert reservation_key in self.run.budget.reservations(), "every downstream call holds a reservation"
        self.calls.append((agent_id, step, payload))
        out = self.output(agent_id, payload)
        if self.hook:
            out = self.hook(agent_id, payload, step, out)
        validate(agent_id, out, schema_file)
        return copy.deepcopy(out)

    def output(self, agent_id, payload):
        head = {"agent_id": agent_id, "prompt_version": "test", "status": "COMPLETE", "warnings": [], "limitations": []}
        if agent_id == "A08-OL":
            return {**copy.deepcopy(self.fx["plan"]), "allocation_ledger": copy.deepcopy(self.fx["ledger"])}
        if agent_id == "A09-WRI" and payload["mode"] == "SECTION":
            p = payload["section_packet"]
            text = tagged_text(p)
            return {**head, "mode": "SECTION", "retrieval_requests": [], "plan_gaps": [], "ceiling_unclear": [],
                    "section": {"section_id": p["section_id"], "heading": p["heading"], "text_markdown": text,
                                "word_count": len(text.split())}}
        if agent_id == "A09-WRI":
            ids = payload["outline"]["abstract_plan"]["ordered_proposition_ids"]
            return {**head, "mode": "FRONT_MATTER", "title": payload["outline"]["title"]["text"],
                    "abstract": " ".join(f"Evaluation abstract sentence. ⟦{i}⟧" for i in ids), "keywords": ["fixture"],
                    "table_captions": [{"display_id": "T1", "caption": "Evaluation caption of the comparison. ⟦ORG⟧"}]}
        if agent_id == "A11-RC":
            return {**head, "manuscript_version": "draft", "reader_passes": {}, "strengths": [], "concerns": [],
                    "decision": "ACCEPT", "decision_rationale": "Scripted evaluation critique"}
        m = payload["manuscript"]
        out = {**head, "mode": payload["mode"], "output_manuscript_version": "edited", "change_log": [],
               "queries": [], "escalations": [], **{k: m[k] for k in ("title", "abstract", "sections") if k in m}}
        if "unit" in payload:
            out["unit"] = payload["unit"]
        return out


def make_run(tmp_path, monkeypatch, fx, stage="outline"):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    run = orch.Run("bridge")
    run.save_state({"stage": stage, "status": "READY", "counters": {}})
    for name, value in (("synthesis_approved.json", fx["pkg"]), ("selected_corpus.json", fx["corpus"]),
                        ("validated_findings.json", fx["findings"])):
        run.save(name, value)
    # the fixture is stamped evaluation-only, so publication stages refuse it; these tests read it directly
    monkeypatch.setattr(run, "_publishable", lambda name: run.load(name))
    # current findings come from the fixture (Task 1 rebuilds them from extractions the fixture does not have)
    monkeypatch.setattr(run, "_findings", lambda: run.load("validated_findings.json"))
    # A10 is not under test here: a report is "current" for exactly the manuscript it was made for, and scripts every
    # occurrence as VERIFIED (so the contrary-evidence release gate reads what the scripted writer actually rendered)
    def report(m, *a, **k):
        occ = verification_job.inventory(m, run.load("display_items.json", []))
        return {"verification_fingerprint": fingerprint(m), "verification_execution": "COMPLETE", "findings": [],
                "occurrence_inventory": occ, "release_disposition": "APPROVED",
                "verdicts": [{"occurrence_id": o["occurrence_id"], "verdict": "VERIFIED", "evidence_finding_ids": []}
                             for o in occ]}
    monkeypatch.setattr(run, "_verify", report)
    monkeypatch.setattr(run, "_maybe_verify", report)
    monkeypatch.setattr(run, "_verification_current", lambda rv, m: rv.get("verification_fingerprint") == fingerprint(m))
    monkeypatch.setattr(run, "_prose_vendors", lambda reader: frozenset({"anthropic"}))
    return run


def kimi_window(run, tokens=None):
    """Kimi K3.1 Pro's window is recorded in pipeline.yaml from Moonshot's model endpoint; a test may override it."""
    if tokens is None:
        return
    adm = run.cfg["admission"]
    run.cfg = {**run.cfg, "admission": {**adm, "context_windows": {**adm["context_windows"], "kimi-k3.1-pro": tokens}}}


def approve_ledger(run):
    d = checkpoints.cp_dir(run.dir)
    decision = json.loads((d / "CP_LEDGER_decision.json").read_text(encoding="utf-8"))
    decision["approve_ledger"] = True
    (d / "CP_LEDGER_decision.json").write_text(json.dumps(decision), encoding="utf-8")
    checkpoints.approve(run.dir, "CP_LEDGER", run.prov)


def outline_and_approve(run, agents):
    with pytest.raises(orch.Pause, match="CP_LEDGER"):
        run.stage_outline(run.state())
    approve_ledger(run)
    assert run.stage_outline(run.state()) == "draft"
    assert sum(a == "A08-OL" for a, _, _ in agents.calls) == 1        # the approved plan is reused, not re-requested


# ------------------------------------------------------------------ the compact 120-paper plan processes fully
def test_compact_120_paper_plan_processes_fully_within_every_window(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)        # A11 on its configured model, Kimi K3.1 Pro (1,048,576)
    agents = Agents(run, fx)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    assert run.stage_draft(run.state()) == "review_loop"
    assert run.stage_review_loop(run.state()) == "finish_edit"
    assert run.stage_finish_edit(run.state()) == "finalize"
    admissions = [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "admission"]
    assert admissions and all(a["fits"] for a in admissions)
    sections = [s for a, s, _ in agents.calls if a == "A09-WRI" and "_front" not in s]
    assert len(sections) == len(fx["plan"]["sections"])               # one call per section, no retrieval needed
    order = [re.search(r"_(S\d+)_r0", s).group(1) for s in sections]
    assert order == fx["plan"]["writing_order"]
    final = run._current()
    assert [s["section_id"] for s in final["sections"]] == [s["section_id"] for s in fx["plan"]["sections"]]
    assert not run.budget.reservations()                              # every reservation released after its call


def test_each_writer_call_gets_outline_its_packet_and_all_earlier_prose(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    agents = Agents(run, fx)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    run.stage_draft(run.state())
    calls = [p for a, s, p in agents.calls if a == "A09-WRI" and p["mode"] == "SECTION"]
    for n, p in enumerate(calls):
        assert [x["section_id"] for x in p["previous_sections"]] == fx["plan"]["writing_order"][:n]
        assert p["section_packet"]["section_id"] == fx["plan"]["writing_order"][n]
        assert "argument_map" not in p and p["outline"]["writing_order"] == fx["plan"]["writing_order"]


# ------------------------------------------------------------------ bridge purity
def test_bridge_is_pure_deterministic_and_never_calls_a_model(monkeypatch, fx):
    import litreview.agents.base as base
    import litreview.llm.router as router
    monkeypatch.setattr(router, "complete", lambda *a, **k: pytest.fail("the bridge called a model"))
    monkeypatch.setattr(base, "run_agent", lambda *a, **k: pytest.fail("the bridge called an agent"))
    before = canonical(fx["pkg"])

    def everything():
        return canonical([bridge.argument_map(fx["pkg"], fx["corpus"]),
                          bridge.element_index(fx["pkg"], fx["corpus"], set()),
                          bridge.comparative_table(fx["pkg"], fx["findings"], fx["corpus"]),
                          bridge.validate_plan(fx["plan"], fx["ledger"], fx["pkg"], fx["corpus"], fx["table"], JOURNAL, BCFG),
                          bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], fx["findings"], fx["corpus"]),
                          bridge.outline_payload(fx["pkg"], fx["corpus"], JOURNAL, fx["table"], BCFG)])
    assert everything() == everything()
    assert canonical(fx["pkg"]) == before                              # its input is never modified
    src = (bridge.__file__ and open(bridge.__file__, encoding="utf-8").read())
    assert not re.search(r"^from \.(llm|agents)|^import .*(requests|socket|anthropic|openai)", src, re.M)


def test_every_assertion_and_record_is_byte_identical_to_a07(fx, packets):
    e = els(fx)
    amap = bridge.argument_map(fx["pkg"], fx["corpus"])
    for line in amap["major_propositions"]:
        assert line["assertion"] == e[line["proposition_id"]]["record"]["assertion"]
    for g in amap["knowledge_gaps"]:
        assert g["statement"] == e[g["gap_id"]]["record"]["statement"]
    for line in bridge.element_index(fx["pkg"], fx["corpus"], set()):
        rec = e[line["id"]]["record"]
        assert line["text"] == (rec.get("assertion") if line["kind"] == "PROPOSITION" else rec.get("statement"))
    seen = 0
    for p in packets.values():
        for i, r in bridge.packet_records(p).items():
            assert canonical(bridge.rejoin(r, p["findings"])) == canonical(e[i]["record"]), i
            seen += 1
        for line in p["index"]:
            assert line["text"] == e[line["id"]]["record"]["assertion"]
    assert seen >= len([x for x in fx["ledger"] if x["outcome"] in bridge.WRITTEN])


# ------------------------------------------------------------------ qualifier preservation
def test_no_dose_model_arm_identity_uncertainty_or_attribution_is_lost(fx, packets):
    fby = {f["finding_id"]: f for f in fx["findings"]}
    keys = ("context", "quantities", "constraints", "plain_language_limit", "modality", "assertion_type",
            "attributed_to", "entities", "subject", "object", "predicate", "polarity", "direction", "disposition")
    checked = set()
    for p in packets.values():
        for fid, f in p["findings"].items():
            for k in keys:
                assert canonical(f.get(k)) == canonical(fby[fid].get(k)), (fid, k)
            checked.add(fid)
    written = {i for x in fx["ledger"] if x["outcome"] in bridge.WRITTEN for i in [x["item_id"]]}
    behind = {f for i in written for f in bridge._finding_ids(els(fx)[i]["record"]) if f in fby}
    assert behind <= checked                                           # every finding behind written prose travels
    real = [r for p in packets.values() for r in bridge.packet_records(p).values()
            if "400 mg" in (r["record"].get("assertion") or "")]
    assert real and all("disulfiram 400 mg daily and copper" in r["record"]["assertion"] for r in real)
    hedged = [f for f in checked if fby[f].get("modality") in ("HEDGED", "SPECULATIVE", "REPORTED_BY_OTHERS")]
    assert hedged and all(packets_with(packets, f)["findings"][f]["modality"] == fby[f]["modality"] for f in hedged)


def packets_with(packets, fid):
    return next(p for p in packets.values() if fid in p["findings"])


# ------------------------------------------------------------------ grouped propositions
def test_a_group_carries_the_union_of_qualifications_and_a_hedged_member_keeps_its_hedge(fx):
    fby = {f["finding_id"]: f for f in fx["findings"]}
    e = els(fx)
    props = [i for i, el in e.items() if el["kind"] == "PROPOSITION" and el["record"]["type"] == "SOURCE_GROUNDED"]
    hedged = next(i for i in props if any(fby[f].get("modality") == "HEDGED" for f in bridge._finding_ids(e[i]["record"])))
    plain = next(i for i in props if i != hedged and all(fby[f].get("modality") == "ASSERTED"
                                                         for f in bridge._finding_ids(e[i]["record"])))
    table = {}
    recs = [bridge.full_record(i, e, fby, fx["pkg"], table) for i in (plain, hedged)]
    union = bridge.qualifications_union(recs, table)
    assert union["members"] == [plain, hedged]
    assert any(h["member"] == hedged and h["modality"] == "HEDGED" for h in union["hedges"])
    assert not any(h["member"] == plain for h in union["hedges"])
    for r in recs:
        assert set(r["record"]["constraints"]) <= set(union["constraints"])
        assert set(r["finding_ids"]) <= set(union["finding_ids"])
        assert all(union["ceiling"][f] == v for f, v in r["record"]["ceiling"].items())
    clash = copy.deepcopy(recs)
    f0 = next(iter(clash[0]["record"]["ceiling"]))
    clash[1]["record"]["ceiling"][f0] = "SOMETHING_ELSE"
    with pytest.raises(bridge.BridgeError, match="disagree"):
        bridge.qualifications_union(clash, table)


def test_grouping_never_creates_a_merged_claim(fx, packets):
    for p in packets.values():
        for u in p["units"]:
            if u["outcome"] == "GROUPED_WITH":
                assert set(u["records"]) == set(u["item_ids"]) and len(u["item_ids"]) >= 2
                assert "assertion" not in u and "assertion" not in u["qualifications_union"]


# ------------------------------------------------------------------ the allocation ledger
def test_the_fixture_ledger_accounts_for_every_element_and_writes_every_mandatory_one(fx):
    problems, report = bridge.validate_plan(fx["plan"], fx["ledger"], fx["pkg"], fx["corpus"], fx["table"], JOURNAL, BCFG)
    assert problems == []
    assert sum(report["counts"].values()) == report["elements"] == len(els(fx))
    assert all(m["outcome"] in bridge.WRITTEN for m in report["mandatory"].values())
    assert report["theme_to_sections"] and report["section_to_themes"]


@pytest.mark.parametrize("change,code", [
    ("drop", "LEDGER_MISSING"), ("mandatory_not_written", "MANDATORY_NOT_WRITTEN"),
    ("mandatory_table_only", "MANDATORY_NOT_WRITTEN"), ("no_reason", "LEDGER_REASON"),
    ("table_only_not_shown", "TABLE_ONLY_NOT_SHOWN"), ("duplicate", "LEDGER_DUPLICATE"),
    ("group_mismatch", "LEDGER_GROUP"), ("unknown", "LEDGER_UNKNOWN"), ("second_table", "DISPLAY_ITEMS")])
def test_the_ledger_rejects_silent_drops_and_inconsistent_outcomes(fx, change, code):
    plan, ledger = copy.deepcopy(fx["plan"]), copy.deepcopy(fx["ledger"])
    mand = bridge.mandatory_reasons(fx["pkg"], fx["corpus"])
    entry = lambda pred: next(x for x in ledger if pred(x))
    unplace = lambda iid: [s["ordered_items"].remove(it) for s in plan["sections"] for it in list(s["ordered_items"])
                           if it["item_id"] == iid]
    if change == "drop":
        ledger.remove(entry(lambda x: x["outcome"] == "NOT_INDIVIDUALLY_DISCUSSED"))
    elif change in ("mandatory_not_written", "mandatory_table_only"):
        x = entry(lambda x: mand[x["item_id"]] and x["outcome"] in bridge.WRITTEN)
        unplace(x["item_id"])
        x.update(outcome="NOT_INDIVIDUALLY_DISCUSSED" if change == "mandatory_not_written" else "TABLE_ONLY",
                 section_id=None, reason="space")
    elif change == "no_reason":
        entry(lambda x: x["outcome"] == "NOT_INDIVIDUALLY_DISCUSSED")["reason"] = " "
    elif change == "table_only_not_shown":
        entry(lambda x: x["outcome"] == "NOT_INDIVIDUALLY_DISCUSSED").update(outcome="TABLE_ONLY", reason=None)
    elif change == "duplicate":
        ledger.append(copy.deepcopy(ledger[0]))
    elif change == "group_mismatch":
        entry(lambda x: x["outcome"] == "GROUPED_WITH")["grouped_with"].pop()
    elif change == "unknown":
        ledger.append({"item_id": "GROUP_G0001.P999", "outcome": "DISCUSSED", "section_id": "S2", "grouped_with": [],
                       "reason": None})
    else:
        plan["display_items"].append({"display_id": "F1", "type": "FIGURE_EVIDENCE_MAP", "placement_section_id": "S2",
                                      "purpose": "x"})
    problems, _ = bridge.validate_plan(plan, ledger, fx["pkg"], fx["corpus"], fx["table"], JOURNAL, BCFG)
    assert any(p.startswith(code) for p in problems), problems[:5]


def test_a_rejected_plan_stops_before_any_writing(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    bad = copy.deepcopy(fx["ledger"])
    mand = bridge.mandatory_reasons(fx["pkg"], fx["corpus"])
    gap = next(x for x in bad if mand[x["item_id"]])
    gap.update(outcome="NOT_INDIVIDUALLY_DISCUSSED", reason="space")
    agents = Agents(run, fx, hook=lambda a, p, s, out: {**out, "allocation_ledger": bad} if a == "A08-OL" else out)
    monkeypatch.setattr(run, "agent", agents)
    with pytest.raises(orch.Pause, match="plan rejected by the bridge"):
        run.stage_outline(run.state())
    assert [a for a, _, _ in agents.calls] == ["A08-OL"]
    assert not (run.dir / "checkpoints" / "CP_LEDGER_review.md").exists()


def test_writing_waits_for_the_researchers_ledger_approval(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    agents = Agents(run, fx)
    monkeypatch.setattr(run, "agent", agents)
    with pytest.raises(orch.Pause, match="CP_LEDGER"):
        run.stage_outline(run.state())
    review = (run.dir / "checkpoints" / "CP_LEDGER_review.md").read_text(encoding="utf-8")
    assert "NOT_INDIVIDUALLY_DISCUSSED" in review and "Display-level detail" in review
    with pytest.raises(orch.Pause, match="not approved"):
        run.stage_draft(run.state())
    assert [a for a, _, _ in agents.calls] == ["A08-OL"]
    with pytest.raises(checkpoints.DecisionIncomplete):
        checkpoints.approve(run.dir, "CP_LEDGER", run.prov)           # approve_ledger is still false


# ------------------------------------------------------------------ the section gate
def first_unit_id(packet):
    return packet["units"][0]["item_ids"][0]


@pytest.mark.parametrize("text,code", [
    ("A sentence with no tag at all.", "UNTAGGED"),
    ("Evaluation sentence. ⟦GROUP_G0001.P99999⟧", "TAG_OUTSIDE_PACKET"),
    ("Survival was 987654 percent. ⟦{u}⟧", "UNMATCHED_NUMBER"),
    ("Organizational sentence with 42 items. ⟦ORG⟧", "NUMBER_IN_ORG"),
    ("Organizational sentence [@R0001]. ⟦ORG⟧", "CITATION_IN_ORG"),
    ("Evaluation sentence [@R9999]. ⟦{u}⟧", "CITATION_NOT_BOUND"),
    ("See {{{{T2}}}}. ⟦{u}⟧", "DISPLAY_NOT_PLANNED")])
def test_the_section_gate_fails_each_defect(packets, text, code):
    p = packets["S2"]
    problems = bridge.check_text(text.format(u=first_unit_id(p)), p, "S2")
    assert problems and problems[0].startswith(code), problems


def test_numbers_and_citations_from_the_tagged_records_pass(fx, packets):
    p = packets["S2"]
    e = els(fx)
    real = next(i for u in p["units"] for i in u["item_ids"] if re.search(r"\d", e[i]["record"].get("assertion") or ""))
    number = re.search(r"\b\d+(?:\.\d+)?\b", e[real]["record"]["assertion"]).group(0)
    cite = p["citations_by_tag"][real][0]
    assert bridge.check_text(f"The reported value was {number} [@{cite}]. ⟦{real}⟧", p, "S2") == []
    # the same number tagged with a record that does not contain it fails
    other = next(i for u in p["units"] for i in u["item_ids"] if not bridge.numbers(number) <= bridge._record_numbers(
        bridge.evidence_of(bridge.packet_records(p)[i], p)))
    assert bridge.check_text(f"The reported value was {number}. ⟦{other}⟧", p, "S2")


def test_a_failed_section_gate_stops_before_the_next_section_starts(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    bad_section = fx["plan"]["writing_order"][1]

    def hook(agent, payload, step, out):
        if agent == "A09-WRI" and payload["mode"] == "SECTION" and payload["section_packet"]["section_id"] == bad_section:
            out["section"]["text_markdown"] += " An untagged claim that the plan never approved."
        return out
    agents = Agents(run, fx, hook)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    with pytest.raises(orch.Pause, match=f"{bad_section}: section gate failed"):
        run.stage_draft(run.state())
    written = [p["section_packet"]["section_id"] for a, s, p in agents.calls if a == "A09-WRI"]
    assert written == fx["plan"]["writing_order"][:2]                  # nothing after the failed section


# ------------------------------------------------------------------ retrieval
def needs(requests):
    return {"agent_id": "A09-WRI", "prompt_version": "t", "status": "NEEDS_EVIDENCE", "warnings": [], "limitations": [],
            "mode": "SECTION", "section": None, "retrieval_requests": requests, "plan_gaps": [], "ceiling_unclear": []}


def test_retrieval_is_bounded_logged_and_joins_the_sections_evidence(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    first = fx["plan"]["writing_order"][0]
    elsewhere = next(x["item_id"] for x in fx["ledger"] if x["outcome"] == "NOT_INDIVIDUALLY_DISCUSSED")
    rounds = {"n": 0}

    def hook(agent, payload, step, out):
        if agent == "A09-WRI" and payload["mode"] == "SECTION" and payload["section_packet"]["section_id"] == first:
            if rounds["n"] == 0:
                rounds["n"] += 1
                return needs([{"element_ids": [elsewhere], "finding_ids": [], "reason": "comparison needs it"}])
            assert elsewhere in payload["section_packet"]["retrieved"]
            out["section"]["text_markdown"] += f" Evaluation sentence using retrieved evidence. ⟦{elsewhere}⟧"
        return out
    agents = Agents(run, fx, hook)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    run.stage_draft(run.state())
    log = [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "writer_retrieval"]
    assert log == [{"section_id": first, "round": 1, "items": [{"id": elsewhere, "reason": "comparison needs it",
                                                                 "kind": "PROPOSITION"}]}]


def test_retrieval_stops_after_its_rounds_and_never_supplies_unknown_or_ineligible_evidence(tmp_path, monkeypatch, fx):
    rejected = next(f["finding_id"] for f in fx["findings"] if status_of(f) == "REJECTED")
    for request, match in (([{"element_ids": ["GROUP_G0001.P9999"], "finding_ids": [], "reason": "x"}], "not in the approved"),
                           ([{"element_ids": [], "finding_ids": [rejected], "reason": "x"}], "ineligible"),
                           (None, "after 2 retrieval rounds")):
        run = make_run(tmp_path / match.split()[0], monkeypatch, fx)
        some = next(x["item_id"] for x in fx["ledger"] if x["outcome"] == "NOT_INDIVIDUALLY_DISCUSSED")
        req = request or [{"element_ids": [some], "finding_ids": [], "reason": "again"}]
        hook = lambda a, p, s, out: needs(req) if a == "A09-WRI" and p["mode"] == "SECTION" else out
        agents = Agents(run, fx, hook)
        monkeypatch.setattr(run, "agent", agents)
        outline_and_approve(run, agents)
        with pytest.raises(orch.Pause, match=match):
            run.stage_draft(run.state())
        calls = [s for a, s, _ in agents.calls if a == "A09-WRI"]
        assert len(calls) == (3 if request is None else 1)            # 1 + max_retrieval_rounds at most


# ------------------------------------------------------------------ cross-section contradictions
def test_known_contradictions_are_preserved_and_flagged_in_both_sections(fx):
    issues = fx["pkg"]["reconciliation"]
    assert issues
    # A08 may place the two sides of a contradiction in different sections: move one side of the first issue
    plan, ledger = copy.deepcopy(fx["plan"]), copy.deepcopy(fx["ledger"])
    mover = issues[0]["proposition_ids"][-1]
    src = next(s for s in plan["sections"] if any(it["item_id"] == mover for it in s["ordered_items"]))
    dst = next(s for s in plan["sections"][1:-1] if s is not src)
    item = next(it for it in src["ordered_items"] if it["item_id"] == mover)
    if item["group"]:
        for x in ledger:
            if x["item_id"] in [it["item_id"] for it in src["ordered_items"] if it["group"] == item["group"]]:
                x["grouped_with"] = [g for g in x["grouped_with"] if g != mover]
    src["ordered_items"].remove(item)
    dst["ordered_items"].append({**item, "group": None})
    next(x for x in ledger if x["item_id"] == mover).update(outcome="DISCUSSED", section_id=dst["section_id"], grouped_with=[])
    packets = bridge.section_packets(plan, ledger, fx["pkg"], fx["findings"], fx["corpus"])
    placed = {it["item_id"]: s["section_id"] for s in plan["sections"] for it in s["ordered_items"]}
    amap = bridge.argument_map(fx["pkg"], fx["corpus"])
    assert {c["issue"]["issue_id"] for c in amap["contradictions"] if c["kind"] == "RECONCILIATION_ISSUE"} == \
        {i["issue_id"] for i in issues}
    crossing = 0
    for issue in issues:
        sections = {placed[p] for p in issue["proposition_ids"] if p in placed}
        for sid in sections:
            p = packets[sid]
            here = {i for u in p["units"] for i in u["item_ids"]}
            for other in set(issue["proposition_ids"]) - here:
                assert other in p["contrary_context"] and p["contrary_context"][other]["contradicts"]
            assert issue["issue_id"] in {i["issue_id"] for i in p["reconciliation_issues"]}
        crossing += len(sections) > 1
    assert crossing, "the fixture has contradictions across sections"


def test_a_packet_is_never_restricted_to_agreeing_evidence(fx, packets):
    """Every conflicting finding of a written proposition is in its section's findings table."""
    e = els(fx)
    for p in packets.values():
        for u in p["units"]:
            for i in u["item_ids"]:
                for f in e[i]["record"].get("conflicting_finding_ids") or []:
                    assert f in p["findings"]


# ------------------------------------------------------------------ section continuity
def test_later_sections_keep_the_plans_terminology(fx, packets):
    plan = fx["plan"]
    u = first_unit_id(packets["S3"])
    earlier = [{"section_id": "S2", "text_markdown": "Copper diethyldithiocarbamate (CuET) was studied. ⟦ORG⟧"}]
    good = {"section_id": "S3", "heading": packets["S3"]["heading"],
            "text_markdown": f"Evaluation sentence on CuET. ⟦{u}⟧"}
    assert bridge.check_section(good, packets["S3"], plan, earlier) == []
    redefined = {**good, "text_markdown": f"Dose-scaled formulation (DSF) differs. ⟦{u}⟧"}
    assert any("TERMINOLOGY" in x for x in bridge.check_section(redefined, packets["S3"], plan, earlier))
    alternative = {**good, "text_markdown": f"Evaluation sentence on Cu(DDC)2 exposure. ⟦{u}⟧"}
    assert any("instead of 'CuET'" in x for x in bridge.check_section(alternative, packets["S3"], plan, earlier))


def test_earlier_prose_is_context_never_evidence(fx, packets):
    """A later section cannot rest a sentence on an element that only an earlier section had."""
    s2 = {i for u in packets["S2"]["units"] for i in u["item_ids"]}
    s3 = set(packets["S3"]["allowed_tags"])
    only_earlier = sorted(s2 - s3)[0]
    later = {"section_id": "S3", "heading": packets["S3"]["heading"],
             "text_markdown": f"As shown earlier, evaluation sentence. ⟦{only_earlier}⟧"}
    earlier = [{"section_id": "S2", "text_markdown": f"Evaluation sentence. ⟦{only_earlier}⟧"}]
    assert any(p.startswith("TAG_OUTSIDE_PACKET") for p in bridge.check_section(later, packets["S3"], fx["plan"], earlier))


# ------------------------------------------------------------------ oversized requests: stop or subdivide
@pytest.fixture(scope="module")
def big():
    data = oversized_package()
    data["table"] = bridge.comparative_table(data["pkg"], data["findings"], data["corpus"], BCFG["table_max_rows"])
    data["plan"], data["ledger"] = fixture_plan(data["pkg"], data["corpus"], data["table"])
    return data


def test_oversized_outline_request_stops_before_dispatch(tmp_path, monkeypatch, big):
    run = make_run(tmp_path, monkeypatch, big)
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("an oversized request was dispatched"))
    with pytest.raises(orch.Pause, match="A08 request not admitted"):
        run.stage_outline(run.state())
    a = [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "admission"][-1]
    assert not a["fits"] and a["input_bound"] > a["window"]
    assert not run.budget.reservations() and not run.budget.entries()


def test_oversized_section_request_stops_before_dispatch(tmp_path, monkeypatch, big):
    run = make_run(tmp_path, monkeypatch, big, stage="draft")
    pv = bridge.plan_version(big["plan"], big["ledger"])
    run.save("manuscript_plan.json", big["plan"]); run.save("allocation_ledger.json", big["ledger"])
    run.save("bridge/plan_check.json", {"plan_version": pv, "problems": []})
    run.save("display_items.json", [big["table"]])
    monkeypatch.setitem(run.cfg["bridge"], "ledger_approval", False)
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("an oversized request was dispatched"))
    with pytest.raises(orch.Pause, match="writer request not admitted.*split it in the plan"):
        run.stage_draft(run.state())
    assert not run.budget.entries()


def test_oversized_critique_request_stops_before_dispatch(tmp_path, monkeypatch, big, fx):
    run = make_run(tmp_path, monkeypatch, big, stage="review_loop")
    kimi_window(run)
    ps = {"pkg": big["pkg"], "findings": big["findings"], "corpus": big["corpus"], "plan": big["plan"],
          "ledger": big["ledger"], "packets": {}, "amap": bridge.argument_map(big["pkg"], big["corpus"]),
          "pv": "pv", "ev": "ev", "journal": JOURNAL, "table": None}
    monkeypatch.setattr(run, "_plan_state", lambda: ps)
    monkeypatch.setattr(run, "_require_current", lambda *a, **k: None)
    m = {"title": "t", "abstract": "a ⟦ORG⟧", "sections": []}
    run._save_manuscript(m, "m01_draft")
    run.save("rv_latest.json", run._verify(m))
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("an oversized request was dispatched"))
    with pytest.raises(orch.Pause, match="A11 request not admitted"):
        run.stage_review_loop(run.state())


def test_an_editor_request_too_large_for_one_call_is_edited_unit_by_unit_without_loss(tmp_path, monkeypatch, fx, packets):
    run = make_run(tmp_path, monkeypatch, fx, stage="finish_edit")
    ps = {"pkg": fx["pkg"], "findings": fx["findings"], "corpus": fx["corpus"], "plan": fx["plan"], "ledger": fx["ledger"],
          "packets": packets, "amap": bridge.argument_map(fx["pkg"], fx["corpus"]), "pv": "pv", "ev": "ev",
          "journal": JOURNAL, "table": fx["table"]}
    # a manuscript of ten 120 kB sections: over Sonnet 5.5's window as one request, each unit well within it
    filler = " ".join(["Evaluation sentence for an oversized manuscript. ⟦ORG⟧"] * 2300)
    m = {"title": "t", "abstract": "a ⟦ORG⟧", "keywords": [],
         "sections": [{"section_id": s["section_id"], "heading": s["heading"], "text_markdown": filler}
                      for s in fx["plan"]["sections"]]}
    agents = Agents(run, fx)
    monkeypatch.setattr(run, "agent", agents)
    edited = run._edit("LINE", m, ps, "A12-EDI_line")
    steps = [s for a, s, _ in agents.calls if a == "A12-EDI"]
    assert steps == ["A12-EDI_line_FRONT"] + [f"A12-EDI_line_{s['section_id']}" for s in fx["plan"]["sections"]]
    assert all(len(p["manuscript"].get("sections") or []) <= 1 for _, _, p in agents.calls)
    assert edited["sections"] == m["sections"] and edited["title"] == m["title"] and edited["edited_by_unit"]
    refused = [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "admission"][0]
    assert not refused["fits"]                                         # the whole-manuscript request was refused first


def test_an_editor_unit_that_alone_does_not_fit_stops(tmp_path, monkeypatch, fx, packets):
    run = make_run(tmp_path, monkeypatch, fx, stage="finish_edit")
    ps = {"pkg": fx["pkg"], "findings": fx["findings"], "corpus": fx["corpus"], "plan": fx["plan"], "ledger": fx["ledger"],
          "packets": packets, "amap": bridge.argument_map(fx["pkg"], fx["corpus"]), "pv": "pv", "ev": "ev",
          "journal": JOURNAL, "table": fx["table"]}
    huge = " ".join(["Evaluation sentence. ⟦ORG⟧"] * 60000)
    m = {"title": "t", "abstract": "a ⟦ORG⟧", "sections": [{"section_id": "S2", "heading": "h", "text_markdown": huge}]}
    monkeypatch.setattr(run, "agent", lambda agent, payload, step, **k: (
        pytest.fail("an oversized unit was dispatched") if "S2" in step else Agents(run, fx).output(agent, payload)))
    with pytest.raises(orch.Pause, match="unit S2 not admitted"):
        run._edit("LINE", m, ps, "A12-EDI_line")


# ------------------------------------------------------------------ the 272k pricing threshold
@pytest.mark.projection_guard
def test_crossing_the_long_context_threshold_requires_a_fresh_projection(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    monkeypatch.setattr(run, "_downstream_gate", lambda *a, **k: None)
    payload = bridge.outline_payload(fx["pkg"], fx["corpus"], JOURNAL, fx["table"], BCFG)

    def projection(long_calls, created="2026-10-30T00:00:00"):
        run.save("cost_projection.json", {"created": created, "verdict": "WITHIN_CAP", "projected_total_usd": 1,
                                          "cap_usd": 35, "lines": [{"stage": "A08-OL", "basis": "REQUEST_BOUND",
                                                                    "calls": 5, "usd": 30.0,
                                                                    "long_context_calls": long_calls}]})
    projection(0)
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("a long-context call was not re-projected first"))
    with pytest.raises(orch.Pause, match="crosses the 272,000-token pricing threshold"):
        run._admitted("A08-OL", payload, "A08-OL_v1")
    assert run.load("cost_projection.json")["verdict"] == "SUPERSEDED"
    projection(1, created="2099-01-01T00:00:00")          # a fresh projection that priced one long-context call
    monkeypatch.setattr(run, "agent", Agents(run, fx))
    assert run._admitted("A08-OL", payload, "A08-OL_v2")["allocation_ledger"]


def test_the_projection_prices_long_context_requests_at_the_long_rates(fx):
    from litreview.budget import BudgetTracker
    from litreview.tools import downstream_projection as dp
    import tempfile
    from pathlib import Path
    b = BudgetTracker(Path(tempfile.mkdtemp()))
    cfg = config.load("pipeline")
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    lines = {x["stage"]: x for x in dp.lines(b, route, cfg, len(fx["findings"]),
                                             {"pkg": fx["pkg"], "findings": fx["findings"], "corpus": fx["corpus"],
                                              "plan": fx["plan"], "ledger": fx["ledger"]})}
    a08 = lines["A08-OL"]
    assert a08["basis"] == "REQUEST_BOUND" and a08["max_input_bound"] > 272_000 and a08["long_context_calls"] == 1
    long = b._rates("gpt-6.1-sol", 300_000)
    assert a08["adverse_usd"] == pytest.approx((a08["max_input_bound"] / dp.BYTES_PER_TOKEN * long["input"]
                                                + 32_000 * long["output"]) / 1e6, abs=1e-4)
    base = cfg["forecast"]["scenarios"]["baseline"]
    tokens = a08["max_input_bound"] / base["bytes_per_token"]
    tier = b._rates("gpt-6.1-sol", int(tokens))                    # 302k tokens: still the long-context tier
    assert a08["baseline_usd"] == pytest.approx((tokens * tier["input"] + 32_000 * base["output"] * tier["output"]) / 1e6,
                                                abs=1e-4)
    assert a08["usd"] == pytest.approx(a08["baseline_usd"] * 1.3, abs=1e-3)
    assert lines["A11-RC"]["over_window_calls"] == 0                          # within Kimi's 1,048,576


# ------------------------------------------------------------------ fingerprints and stale approval
def test_fingerprints_change_with_text_plan_or_evidence(fx):
    m = {"sections": [{"section_id": "S2", "text_markdown": "x ⟦ORG⟧"}]}
    pv = bridge.plan_version(fx["plan"], fx["ledger"])
    ev = bridge.evidence_version(fx["pkg"], fx["findings"])
    base = bridge.content_fingerprint(m, pv, ev)
    edited = copy.deepcopy(m); edited["sections"][0]["text_markdown"] = "y ⟦ORG⟧"
    plan2 = copy.deepcopy(fx["plan"]); plan2["sections"][1]["word_budget"] += 1
    ledger2 = copy.deepcopy(fx["ledger"]); ledger2[-1]["reason"] = "changed"
    findings2 = copy.deepcopy(fx["findings"])
    target = next(f for f in findings2 if status_of(f) == "SUPPORTING")
    target["eligibility"] = {"status": "QUARANTINED"}
    assert len({base, bridge.content_fingerprint(edited, pv, ev),
                bridge.content_fingerprint(m, bridge.plan_version(plan2, fx["ledger"]), ev),
                bridge.content_fingerprint(m, bridge.plan_version(fx["plan"], ledger2), ev),
                bridge.content_fingerprint(m, pv, bridge.evidence_version(fx["pkg"], findings2))}) == 5


def test_requarantining_one_finding_invalidates_the_approval_and_stops_editing(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    kimi_window(run)
    agents = Agents(run, fx)
    monkeypatch.setattr(run, "agent", agents)
    outline_and_approve(run, agents)
    run.stage_draft(run.state())
    # after A10 approved the draft, one finding behind a written proposition is re-quarantined
    written = next(x["item_id"] for x in fx["ledger"] if x["outcome"] == "DISCUSSED"
                   and els(fx)[x["item_id"]]["kind"] == "PROPOSITION")
    fid = bridge._finding_ids(els(fx)[written]["record"])[0]
    findings = copy.deepcopy(fx["findings"])
    next(f for f in findings if f["finding_id"] == fid)["eligibility"] = {"status": "QUARANTINED"}
    run.save("validated_findings.json", findings)
    calls = len(agents.calls)
    # Task 1's package contract stops it first; the bridge's own eligibility check is the second line
    with pytest.raises(orch.Pause, match="evidence contract|no longer eligible|stale"):
        run.stage_review_loop(run.state())
    assert len(agents.calls) == calls                                  # neither A11 nor A12 ran on stale approval


def test_a11_and_a12_reject_verification_made_for_other_text(tmp_path, monkeypatch, fx, packets):
    run = make_run(tmp_path, monkeypatch, fx, stage="finish_edit")
    ps = {"pkg": fx["pkg"], "findings": fx["findings"], "plan": fx["plan"], "ledger": fx["ledger"], "packets": packets,
          "pv": "pv", "ev": "ev"}
    m = {"title": "t", "sections": []}
    rv = run._stamp(run._verify(m), m, ps)
    run._require_current(rv, m, ps, "A12-EDI")
    with pytest.raises(orch.Pause, match="not current"):
        run._require_current(rv, {**m, "title": "edited"}, ps, "A12-EDI")
    with pytest.raises(orch.Pause, match="stale"):
        run._require_current(rv, m, {**ps, "ev": "a re-quarantined finding"}, "A12-EDI")


# ------------------------------------------------------------------ the comparative table
def test_every_table_cell_and_citation_traces_to_eligible_evidence(fx):
    t = fx["table"]
    fby = {f["finding_id"]: f for f in fx["findings"]}
    props = {p["proposition_id"]: p for p in fx["pkg"]["propositions"]}
    assert t["status"] == "BUILT" and 0 < len(t["rows"]) <= BCFG["table_max_rows"] and len(t["columns"]) <= 7
    for fid, row in zip(t["row_finding_ids"], t["rows"]):
        f = fby[fid]
        assert status_of(f) == "SUPPORTING"
        assert row[-1] == f"[@{f['record_id']}]"
        tagged = re.search(r"⟦([^⟧]+)⟧", row[3]).group(1).split(",")
        assert tagged and all(any(x["finding_id"] == fid and x["role"] in ("SUPPORTING", "CONFLICTING")
                                  for x in props[p]["evidence"]) for p in tagged)
        ctx = f.get("context") or {}
        mention = ((f.get("entities") or {}).get(f.get("subject")) or {}).get("mention")
        for cell, sources in ((row[1], [v for v in ctx.values() if isinstance(v, str)]),
                              (row[2], [mention, ctx.get("agent"), ctx.get("dose_or_concentration")])):
            rest = cell
            for v in sorted((v for v in sources if v), key=len, reverse=True):
                rest = rest.replace(v, "")
            assert cell == bridge.NOT_REPORTED or not rest.replace(";", "").strip(), (fid, cell)
        for c in f.get("constraints") or []:
            assert c in row[5]
        if f.get("attributed_to"):
            assert f"Attributed to: {f['attributed_to']}" in row[5]
    assert bridge.comparative_table(fx["pkg"], fx["findings"], fx["corpus"]) == t       # deterministic


def test_the_table_never_shows_a_claim_without_its_contrary_evidence(fx):
    t = fx["table"]
    shown = set(t["row_finding_ids"])
    assert t["contrary_finding_ids"] and set(t["contrary_finding_ids"]) & shown
    for p in fx["pkg"]["propositions"]:
        sup = {x["finding_id"] for x in p["evidence"] if x["role"] == "SUPPORTING"} & shown
        con = {x["finding_id"] for x in p["evidence"] if x["role"] == "CONFLICTING"}
        if sup:
            assert con <= shown, p["proposition_id"]
    for issue in fx["pkg"]["reconciliation"]:
        named = set(issue["finding_ids"])
        assert not (named & shown) or named <= shown


def test_appraisal_only_and_ineligible_findings_never_enter_the_table(fx):
    fby = {f["finding_id"]: f for f in fx["findings"]}
    assert all(status_of(fby[f]) == "SUPPORTING" for f in fx["table"]["row_finding_ids"])
    appraised = {x["finding_id"] for p in fx["pkg"]["propositions"] for x in p["evidence"]
                 if x["role"] == "SUBJECT_OF_APPRAISAL"}
    assert not appraised & set(fx["table"]["row_finding_ids"])


def test_the_a08_prompt_and_journal_allow_one_display_item():
    from litreview.paths import AGENT_PROMPTS_DIR, SCHEMAS_DIR
    assert JOURNAL["limits"]["display_items_max"] == 1
    schema = json.loads((SCHEMAS_DIR / "A08-OL.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["display_items"]["maxItems"] == 1
    prompt = (AGENT_PROMPTS_DIR / "A08-OL_Outline.md").read_text(encoding="utf-8")
    assert "**one** display item" in prompt and "FIGURE_EVIDENCE_MAP" not in prompt
    assert "comparative table" in config.load("pipeline")["outline"]["display_preference"]


# ------------------------------------------------------------------ financial controls
@pytest.mark.projection_guard
def test_no_downstream_call_exceeds_the_cap_or_the_gate(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    payload = bridge.outline_payload(fx["pkg"], fx["corpus"], JOURNAL, fx["table"], BCFG)
    run.save("cost_projection.json", {"created": "2026-10-30T00:00:00", "verdict": "WITHIN_CAP", "projected_total_usd": 1,
                                      "cap_usd": 35, "lines": [{"stage": "A08-OL", "basis": "REQUEST_BOUND", "calls": 5,
                                                                "usd": 30.0, "long_context_calls": 5}]})
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("a call was made past a spend control"))
    # 1. the runtime gate: spent + committed + projected + this request over $150 stops it
    monkeypatch.setattr(orch.cost_projection, "remaining_for_run", lambda r: {"projected_remaining_usd": 149.99})
    with pytest.raises(orch.BudgetExceeded, match=r"over the \$150.00 gate"):
        run._admitted("A08-OL", payload, "A08-OL_v1")
    gate = [e["summary"] for e in run.prov.events() if e["type"] == "tool_run" and e["tool"] == "downstream_gate"][-1]
    assert gate["verdict"] == "STOP" and gate["limit_usd"] == 150.0
    # 2. the cap: the reservation (the existing mechanism, unchanged) refuses what does not fit under it
    monkeypatch.setattr(orch.cost_projection, "remaining_for_run", lambda r: {"projected_remaining_usd": 0.0})
    run.budget.cap = 0.10
    with pytest.raises(orch.BudgetExceeded, match="remains under the cap"):
        run._admitted("A08-OL", payload, "A08-OL_v2")
    assert not run.budget.reservations()
    # 3. no gate configured: nothing is called
    run.budget.cap = 35.0
    run.cfg = {**run.cfg, "batch": {k: v for k, v in run.cfg["batch"].items() if k != "gate_usd"}}
    with pytest.raises(orch.BudgetExceeded, match="gate_usd is not set"):
        run._admitted("A08-OL", payload, "A08-OL_v3")


@pytest.mark.projection_guard
def test_spend_past_a_request_line_supersedes_the_projection(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    monkeypatch.setattr(run, "_downstream_gate", lambda *a, **k: None)
    run.save("cost_projection.json", {"created": "2026-10-30T00:00:00", "verdict": "WITHIN_CAP", "projected_total_usd": 1,
                                      "cap_usd": 35, "lines": [{"stage": "A08-OL", "basis": "REQUEST_BOUND", "calls": 1,
                                                                "usd": 1.0, "long_context_calls": 2}]})
    with open(run.dir / "costs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": "2026-10-30T01:00:00", "agent": "A08-OL", "step": "A08-OL_v1", "provider": "openai",
                             "model": "gpt-6.1-sol", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.5}) + "\n")
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("a call past its projection line"))
    payload = bridge.outline_payload(fx["pkg"], fx["corpus"], JOURNAL, fx["table"], BCFG)
    with pytest.raises(orch.Pause, match="projection line overrun"):
        run._admitted("A08-OL", payload, "A08-OL_v2")
    assert run.load("cost_projection.json")["verdict"] == "SUPERSEDED"


def test_requests_that_cannot_be_bounded_or_placed_fail_closed(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("dispatched without admission"))
    with pytest.raises(AdmissionRefused, match="cannot be serialized"):
        run._admitted("A08-OL", {"not json": object()}, "A08-OL_v1")
    adm = run.cfg["admission"]
    run.cfg = {**run.cfg, "admission": {**adm, "context_windows": {k: v for k, v in adm["context_windows"].items()
                                                                   if k != "kimi-k3.1-pro"}}}
    with pytest.raises(AdmissionRefused, match="no context window recorded for kimi"):
        run._admitted("A11-RC", {"x": 1}, "A11-RC_cycle1", exclude=frozenset({"anthropic"}))
    assert not run.budget.reservations()


def test_a_failed_call_keeps_an_unlogged_reservation_until_reconciled(tmp_path, monkeypatch, fx):
    run = make_run(tmp_path, monkeypatch, fx)
    payload = bridge.outline_payload(fx["pkg"], fx["corpus"], JOURNAL, fx["table"], BCFG)

    def fail(*a, **k):
        raise orch.AgentError("simulated unknown billing")
    monkeypatch.setattr(run, "agent", fail)
    with pytest.raises(orch.AgentError):
        run._admitted("A08-OL", payload, "A08-OL_v1")
    assert len(run.budget.reservations()) == 1                         # provider billing unknown: still held
    with pytest.raises(orch.Pause, match="unsettled A08-OL reservation"):
        run._admitted("A08-OL", payload, "A08-OL_v1")
