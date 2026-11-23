"""Applied researcher decisions, the paged A06 theme pass, and prompt contracts generated from schemas."""
import json

import pytest

from litreview import config, decisions, model_record, theme_paging
from litreview import orchestrator as orch
from litreview.agents import base as agent_base
from litreview.llm.base import LLMResponse
from litreview.paths import AGENT_PROMPTS_DIR, SCHEMAS_DIR
from litreview.tools import contract


# ------------------------------------------------------------------------------------------ decisions
def test_a_decision_needs_targets_an_author_and_an_instruction(tmp_path):
    with pytest.raises(decisions.DecisionError, match="must name what it applies to"):
        decisions.add(tmp_path, "WORDING", "use no copper supplementation reported", {}, "May Khalid")
    with pytest.raises(decisions.DecisionError, match="author"):
        decisions.add(tmp_path, "WORDING", "use no copper supplementation reported", {"finding_ids": ["R1:F1"]}, "")
    with pytest.raises(decisions.DecisionError, match="exact instruction"):
        decisions.add(tmp_path, "WORDING", "fix", {"finding_ids": ["R1:F1"]}, "May Khalid")
    with pytest.raises(decisions.DecisionError, match="revising the approved framework"):
        decisions.add(tmp_path, "THEME_FRAMEWORK", "relabel T5 as author interpretation", {"theme_ids": ["T5"]}, "May Khalid")
    assert decisions.load(tmp_path) == []


def test_a_decision_reaches_only_requests_that_contain_what_it_names(tmp_path):
    d = decisions.add(tmp_path, "WORDING", 'Describe DSF exposure as "no copper supplementation reported", never "without copper".',
                      {"finding_ids": ["R0001:F36", "R0001:F105"]}, "May Khalid", "CP_SYN")
    assert (d["decision_id"], d["version"], d["status"]) == ("D001", 1, "ACTIVE")
    with_it = decisions.attach(tmp_path, "A07-SYN", {"mode": "GROUP", "findings": [{"finding_id": "R0001:F36"}]})
    assert [x["decision_id"] for x in with_it["researcher_decisions"]] == ["D001"]
    assert "never \"without copper\"" in with_it["researcher_decisions"][0]["instruction"]
    without = decisions.attach(tmp_path, "A07-SYN", {"mode": "GROUP", "findings": [{"finding_id": "R0001:F360"}]})
    assert "researcher_decisions" not in without                      # exact identifiers, never substrings
    assert "researcher_decisions" not in decisions.attach(tmp_path, "A03-LM", {"x": "R0001:F36"})   # not a downstream agent
    assert decisions.attach(tmp_path, "A07-SYN", with_it) == with_it  # idempotent
    # IDs used as dictionary keys count as present (section packets and registries are keyed by ID)
    assert "researcher_decisions" in decisions.attach(tmp_path, "A09-WRI", {"evidence": {"R0001:F105": {"span": "x"}}})


def test_a_new_version_replaces_the_old_and_a_withdrawal_removes_it(tmp_path):
    decisions.add(tmp_path, "CONSTRAINT", "Do not present T5 items as cross-study agreement.", {"theme_ids": ["T5"]}, "May")
    v2 = decisions.add(tmp_path, "CONSTRAINT", "Present T5 items as single-paper author interpretation only.",
                       {"theme_ids": ["T5"]}, "May", decision_id="D001")
    assert v2["version"] == 2 and [d["version"] for d in decisions.active(tmp_path)] == [2]
    assert len(decisions.load(tmp_path)) == 2                         # history is kept
    before = decisions.fingerprint(tmp_path)
    decisions.add(tmp_path, "CONSTRAINT", "", {"theme_ids": ["T5"]}, "May", decision_id="D001", withdraw=True)
    assert decisions.active(tmp_path) == [] and decisions.fingerprint(tmp_path) != before


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: False)
    r = orch.Run("t")
    r.save_state({"stage": "extract", "status": "READY", "counters": {}})
    (r.dir / "input").mkdir(parents=True, exist_ok=True)
    (r.dir / "input" / "topic_family.txt").write_text("onc", encoding="utf-8")
    monkeypatch.setattr(r, "_context_check", lambda *a: {"input_counted": 100, "input_byte_bound": 100,
                                                         "output_reserve": 100, "step": a[2]})
    monkeypatch.setattr(r, "_context_actual", lambda *a: None)
    monkeypatch.setattr(agent_base, "validate", lambda a, o, s=None: None)
    monkeypatch.setattr(orch.corpus_policy, "resolve", lambda run: None)
    return r


def _model(monkeypatch):
    calls = []

    def complete(provider, **kw):
        calls.append(json.loads(kw["user"][0]["text"]))
        return LLMResponse(json.dumps({"n": len(calls)}), provider, kw["model"], 100, 50, "end_turn")
    monkeypatch.setattr(agent_base, "complete", complete)
    return calls


def test_changing_a_decision_invalidates_the_affected_output_and_keeps_unrelated_work(run, monkeypatch):
    calls = _model(monkeypatch)
    copper = {"section_id": "S2", "findings": [{"finding_id": "R0001:F36"}]}
    other = {"section_id": "S3", "findings": [{"finding_id": "R0002:F4"}]}
    a, b = run.agent("A09-WRI", copper, "A09-WRI_S2"), run.agent("A09-WRI", other, "A09-WRI_S3")
    assert len(calls) == 2 and "researcher_decisions" not in calls[0]
    run.decide("WORDING", 'Write "no copper supplementation reported"; never "without copper".',
               {"finding_ids": ["R0001:F36"]}, "May Khalid", "CP_SYN")
    assert run.agent("A09-WRI", other, "A09-WRI_S3") == b and len(calls) == 2       # unrelated section: reused, not paid again
    a2 = run.agent("A09-WRI", copper, "A09-WRI_S2")                                 # affected section: a new request
    assert a2 != a and len(calls) == 3
    assert calls[2]["researcher_decisions"][0]["instruction"].startswith('Write "no copper supplementation reported"')
    assert run.agent("A09-WRI", copper, "A09-WRI_S2") == a2 and len(calls) == 3     # and stable until it changes again
    run.decide("WORDING", 'Write "copper supplementation not reported".', {"finding_ids": ["R0001:F36"]}, "May Khalid",
               decision_id="D001")
    run.agent("A09-WRI", copper, "A09-WRI_S2")
    assert len(calls) == 4 and calls[3]["researcher_decisions"][0]["version"] == 2
    logged = [e for e in run.prov.events() if e["type"] == "human_decision" and e["checkpoint"] == "APPLIED_DECISION"]
    assert [e["decision"]["version"] for e in logged] == [1, 2] and logged[0]["decision"]["author"] == "May Khalid"


def test_job_identities_change_only_when_a_decision_can_reach_the_agent(run):
    assert run._decision_identity("A07-SYN") == {}                    # no decisions: identities are untouched
    run.decide("CONSTRAINT", "Do not describe the abstract-only papers' methods.", {"all": True, "agents": ["A09-WRI"]}, "May")
    assert run._decision_identity("A07-SYN") == {} and "applied_decisions" in run._decision_identity("A09-WRI")


def test_a_theme_is_relabelled_by_revising_the_framework_not_by_a_note(run):
    themes = [{"theme_id": "T1", "label": "Study systems"}, {"theme_id": "T5", "label": "Cross-paper interpretation"}]
    run.save("theme_framework.json", orch.theme_framework.create(themes, "two themes", "CP1"))
    run.save("theme_records.json", {"T1": {}, "T5": {}})
    with pytest.raises(ValueError, match="author and the reason"):
        run.revise_framework(themes, "May Khalid", "")
    revised = [themes[0], {"theme_id": "T5", "label": "Author interpretation and translational boundaries"}]
    new = run.revise_framework(revised, "May Khalid", "single-paper run: T5 cannot compare studies")
    assert new["version"] == 2 and run.load("theme_framework.json")["primary_themes"][1]["label"].startswith("Author")
    assert run.load("theme_records_stale.json") == ["T1", "T5"]       # the theme pass is rebuilt on the new framework
    assert new["history"][-1]["previous_primary_themes"] == themes
    assert "researcher_decisions" in (AGENT_PROMPTS_DIR.parent / "shared" / "core_rules.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------- paged A06 theme pass
S = {"enabled": True, "max_input_tokens": 3000, "output_tokens_per_finding": 165, "output_share_of_cap": 0.6,
     "bytes_per_token": 2.1, "max_retrieval_rounds": 2, "reconcile_max_input_tokens": 10 ** 6}


def _finding(record, n, pad=400):
    return {"finding_id": f"{record}:F{n}", "record_id": record, "predicate": "DECREASES", "polarity": "POSITIVE",
            "direction": "DECREASE", "disposition": "SUPPORTED", "span": "x" * pad,
            "context": {"evidence_system": "IN_VIVO", "species": "mouse", "comparator": "VEHICLE"}}


FINDINGS = [_finding(f"R{r:04d}", n) for r in range(1, 5) for n in range(1, 5)]      # 16 findings, 4 papers


def test_packets_cover_every_finding_once_and_are_sized_by_tokens_not_counts():
    parts = theme_paging.packets(FINDINGS, S, 24000, 500)
    ids = [f["finding_id"] for p in parts for f in p]
    assert len(parts) > 1 and sorted(ids) == sorted(f["finding_id"] for f in FINDINGS) and len(ids) == len(set(ids))
    assert all(sum(theme_paging.est_tokens(f, 2.1) for f in p) <= 2500 for p in parts)
    big = theme_paging.packets([_finding("R0001", n, pad=3000) for n in range(1, 4)], S, 24000, 500)
    small = theme_paging.packets([_finding("R0001", n, pad=50) for n in range(1, 4)], S, 24000, 500)
    assert len(big) == 3 and len(small) == 1                          # same count of findings, different packets
    out_bound = theme_paging.packets(FINDINGS, {**S, "max_input_tokens": 10 ** 6}, 1000, 0)
    assert all(len(p) <= 3 for p in out_bound)                        # expected output closes a packet too (600 / 165)
    assert not theme_paging.needs_paging(FINDINGS[:2], S, 24000, 500)


def test_a_finding_too_large_for_any_packet_stops_instead_of_being_cut():
    with pytest.raises(theme_paging.PagingError, match="not truncated or dropped"):
        theme_paging.packets([_finding("R0001", 1, pad=20000)], S, 24000, 500)


def _theme_model(script=None):
    """A scripted A06: each packet reports one in-packet conflict; packet 1 flags a pair that spans packets."""
    seen = []

    def call(suffix, payload):
        seen.append((suffix, payload))
        if "theme_packet" in payload:
            ids = payload["theme_packet"]["finding_ids"]
            other = next(e["finding_id"] for e in payload["theme_index"] if e["finding_id"] not in ids)
            return {"mode": "PER_THEME", "theme": "T4", "status": "COMPLETE",
                    "conflicts": [{"finding_ids": ids[:2], "type": "CONTEXT_DEPENDENT"}] if len(ids) > 1 else [],
                    "independence": [], "evidence_reach": {},
                    "cross_packet_candidates": [{"finding_ids": [ids[0], other], "kind": "POSSIBLE_SAME_STUDY", "reason": "same model"}]}
        return (script or (lambda p, n: None))(payload, len(seen)) or {
            "mode": "PER_THEME", "theme": "T4", "status": "COMPLETE", "independence": [], "evidence_reach": {"summary": "s"},
            "conflicts": [c for r in payload["packet_results"] for c in r["conflicts"]]}
    return call, seen


def test_reconciliation_sees_every_packet_the_global_index_and_the_originals_it_needs():
    call, seen = _theme_model()
    saved = []
    rec = theme_paging.run("T4", FINDINGS, {"mode": "PER_THEME", "theme": "T4"}, S, 24000, 500, call, saved.append)
    packets_seen = [p for s, p in seen if "theme_packet" in p]
    final = seen[-1][1]
    assert len(packets_seen) == rec["theme_paging"]["packets"] > 1 and seen[-1][0] == "reconcile"
    assert all(len(p["theme_index"]) == 16 for _, p in seen)                     # every call has the whole theme's index
    assert len(final["packet_results"]) == len(packets_seen)
    named = {i for r in final["packet_results"] for c in r["conflicts"] + r["cross_packet_candidates"] for i in c["finding_ids"]}
    assert {f["finding_id"] for f in final["validated_findings"]} == named       # originals of every named finding
    assert saved[0]["coverage"] == "every finding in exactly one packet" and saved[0]["findings"] == 16


def test_reconciliation_can_retrieve_originals_and_is_bounded():
    def ask_once(payload, n):
        if payload["theme_reconcile"]["retrieval_round"] == 0:
            have = {f["finding_id"] for f in payload["validated_findings"]}
            wanted.append(next(f["finding_id"] for f in FINDINGS if f["finding_id"] not in have))
            return {"mode": "PER_THEME", "theme": "T4", "status": "COMPLETE", "conflicts": [], "independence": [],
                    "evidence_reach": {}, "retrieval_requests": wanted[-1:]}
    wanted = []
    call, seen = _theme_model(ask_once)
    theme_paging.run("T4", FINDINGS, {"mode": "PER_THEME", "theme": "T4"}, S, 24000, 500, call)
    assert seen[-1][0] == "reconcile_r1" and wanted[0] in {f["finding_id"] for f in seen[-1][1]["validated_findings"]}

    def always(payload, n):
        have = {f["finding_id"] for f in payload["validated_findings"]}
        want = next(f["finding_id"] for f in many if f["finding_id"] not in have)
        return {"mode": "PER_THEME", "theme": "T4", "status": "COMPLETE", "conflicts": [], "independence": [],
                "evidence_reach": {}, "retrieval_requests": [want]}
    many = [_finding(f"R{r:04d}", n) for r in range(1, 21) for n in range(1, 5)]
    call, _ = _theme_model(always)
    with pytest.raises(theme_paging.PagingError, match="after 2 retrieval rounds"):
        theme_paging.run("T4", many, {"mode": "PER_THEME", "theme": "T4"}, S, 24000, 500, call)


def test_a_conflict_found_in_a_packet_cannot_silently_disappear():
    def drop(payload, n):
        return {"mode": "PER_THEME", "theme": "T4", "status": "COMPLETE", "conflicts": [], "independence": [], "evidence_reach": {}}
    call, _ = _theme_model(drop)
    with pytest.raises(theme_paging.PagingError, match="lost a conflict a packet recorded"):
        theme_paging.run("T4", FINDINGS, {"mode": "PER_THEME", "theme": "T4"}, S, 24000, 500, call)

    def explain(payload, n):
        return {"mode": "PER_THEME", "theme": "T4", "status": "COMPLETE", "conflicts": [], "independence": [], "evidence_reach": {},
                "packet_conflicts_not_retained": [{"finding_ids": c["finding_ids"], "reason": "different doses; scope, not conflict"}
                                                  for r in payload["packet_results"] for c in r["conflicts"]]}
    call, _ = _theme_model(explain)
    assert theme_paging.run("T4", FINDINGS, {"mode": "PER_THEME", "theme": "T4"}, S, 24000, 500, call)["conflicts"] == []


def test_a_packet_may_not_judge_a_finding_it_only_saw_in_the_index():
    with pytest.raises(theme_paging.PagingError, match="outside its packet"):
        theme_paging.check_packet({"conflicts": [{"finding_ids": ["R0001:F1", "R0009:F9"]}]}, {"R0001:F1"}, {"R0001:F1", "R0009:F9"})


def test_the_theme_stage_pages_a_large_theme_and_leaves_a_small_one_alone(run, monkeypatch):
    monkeypatch.setitem(run.cfg["validation"], "theme_paging", {**S, "max_input_tokens": 60000, "output_tokens_per_finding": 2000})
    steps = []

    def agent(agent_id, payload, step, **kw):
        steps.append(step)
        if "theme_packet" in payload:
            return {"mode": "PER_THEME", "theme": payload["theme"], "status": "COMPLETE", "conflicts": [], "independence": [],
                    "evidence_reach": {}}
        return {"mode": "PER_THEME", "theme": payload["theme"], "status": "COMPLETE", "conflicts": [], "independence": [],
                "evidence_reach": {"summary": "ok"}}
    monkeypatch.setattr(run, "agent", agent)
    monkeypatch.setattr(run, "_extraction_vendor", lambda rid, entries=None: "anthropic")
    big = [{**f, "themes": ["T4"]} for f in FINDINGS] + [{**_finding("R0009", 1), "themes": ["T1"]}]
    records = run._theme_pass([{"record_id": f"R{r:04d}"} for r in (1, 2, 3, 4, 9)], big)
    assert "A06-SV_theme_T1" in steps and "A06-SV_theme_T4" not in steps
    assert any(s.startswith("A06-SV_theme_T4_P001of") for s in steps) and "A06-SV_theme_T4_reconcile" in steps
    assert records["T4"]["theme_paging"]["findings"] == 16 and "theme_paging" not in records["T1"]
    assert run.load("theme_paging/T4.json")["packets"] >= 2
    assert config.load("pipeline")["validation"]["theme_paging"]["enabled"] is True
    assert "theme_reconcile" in (AGENT_PROMPTS_DIR / "A06-SV_Scientific_Validation.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------- contracts from schemas
def test_every_prompt_contract_line_is_generated_from_its_schema():
    stale = {}
    for prompt in sorted(AGENT_PROMPTS_DIR.glob("*.md")):
        _, changed = contract.regenerate(prompt.read_text(encoding="utf-8"), SCHEMAS_DIR)
        if changed:
            stale[prompt.name] = changed
    assert stale == {}, "run: python -m litreview.tools.contract --write"
    plan = (AGENT_PROMPTS_DIR / "A07-SYN_Synthesis.md").read_text(encoding="utf-8")
    assert "fivew1h" not in plan and "$.unresolved_questions[].questions[] maxLength=480" in plan


def test_unresolved_questions_is_typed_and_a_list_inside_a_string_is_refused():
    import jsonschema
    schema = json.loads((SCHEMAS_DIR / "A07-SYN.bounded-plan.schema.json").read_text(encoding="utf-8"))
    base = {"agent_id": "A07-SYN", "prompt_version": "1.0", "mode": "PLAN", "status": "COMPLETE", "warnings": [],
            "limitations": [], "theme_change_proposals": [], "scope_drift": []}
    jsonschema.validate({**base, "unresolved_questions": [{"theme_id": "T2", "questions": ["Was copper present?", "Which DSF form?"]}]}, schema)
    for bad in ([{"theme_id": "T2", "questions": '["Was copper present?"]'}], [{"theme_id": "T2", "unresolved": "x"}],
                [{"theme_id": "T2", "questions": []}]):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**base, "unresolved_questions": bad}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**base, "fivew1h": []}, schema)


def test_contract_summary_and_structured_output_form():
    schema = {"type": "object", "required": ["mode", "items"], "additionalProperties": False,
              "properties": {"mode": {"const": "X"}, "note": {"type": ["string", "null"], "maxLength": 9},
                             "items": {"type": "array", "maxItems": 2, "items": {"type": "object", "required": ["id"],
                                       "properties": {"id": {"type": "string", "pattern": "^F"}}}}},
              "allOf": [{"if": {"properties": {"mode": {"const": "X"}}}, "then": {"required": ["note"]}}]}
    text = contract.summary(schema)
    assert text.startswith('$ required=["mode","items"]; $ additionalProperties=false; $.mode const="X"')
    assert "$.items maxItems=2" in text and '$.items[].id pattern="^F"' in text and '[when $.mode const="X"] $ required=["note"]' in text
    slim, removed = contract.for_structured_output(schema)
    assert "$.properties.note.maxLength" not in json.dumps(slim) and "maxItems" not in json.dumps(slim) and "pattern" not in json.dumps(slim)
    assert {"$.note.maxLength", "$.items.maxItems", "$.items.items.id.pattern"} <= set(removed)
    assert slim["properties"]["items"]["items"]["additionalProperties"] is False and slim["required"] == ["mode", "items"]
