"""The run specification (outline, corpus manifest), the science wording rules, structured-output gating and the
budget plan for an explicit corpus."""
import copy
import json

import pytest

from litreview import config, model_record, run_spec, structured
from litreview import orchestrator as orch
from litreview.budget import BudgetTracker, derive_stage_caps
from litreview.paths import REPO_ROOT, SHARED_PROMPTS_DIR
from litreview.tools import science_lint

LIMITS = {"max_papers": 15, "max_full_text": 5}


def outline():
    return {"outline_version": 1, "working_title": "Disulfiram in glioblastoma",
            "sections": [
                {"section_id": "S1", "heading": "Rationale", "questions": ["Why was disulfiram proposed for glioblastoma?"],
                 "intended_contribution": "Sets out the hypothesis and its origin.", "word_budget": 300,
                 "scope": {"includes": ["mechanistic rationale"], "excludes": ["other tumours"]}},
                {"section_id": "S2", "heading": "Copper dependence", "questions": ["Is the activity copper dependent?",
                                                                                   "Which studies supplemented copper?"],
                 "intended_contribution": "Separates supplemented from unsupplemented conditions.", "word_budget": 600,
                 "scope": {"includes": ["in vitro", "in vivo"], "excludes": []}}]}


def paper(n, level="ABSTRACT", importance="SUPPORTING", **over):
    return {"paper_id": f"P{n:02d}", "pmid": str(30000000 + n), "title": f"Paper number {n}",
            "selection_reason": "Reports the primary endpoint for the question.", "scientific_importance": importance,
            "intended_reading_level": level,
            "actual_access": {"level": level, "figures_inspected": level == "FULL_TEXT", "supplements_inspected": False},
            **over}


def manifest(full=5, abstracts=10):
    return {"manifest_version": 1, "papers": [paper(i, "FULL_TEXT", "CORE") for i in range(1, full + 1)]
            + [paper(i) for i in range(full + 1, full + abstracts + 1)]}


# ------------------------------------------------------------------------------------------ run specification
def test_a_valid_five_plus_ten_specification_passes_and_is_fingerprinted():
    summary = run_spec.check(outline(), manifest(), LIMITS)
    assert (summary["papers"], summary["full_text"], summary["abstract"], summary["sections"]) == (15, 5, 10, 2)
    assert len(summary["outline_sha256"]) == 64 and summary["word_budget"] == 900
    changed = outline()
    changed["sections"][0]["questions"] = ["Why was disulfiram first tested in glioblastoma?"]
    assert run_spec.check(changed, manifest(), LIMITS)["outline_sha256"] != summary["outline_sha256"]


@pytest.mark.parametrize("mutate,expected", [
    (lambda o, m: o["sections"][0]["questions"].append("Disulfiram is effective against glioblastoma."), "is not a question"),
    (lambda o, m: o["sections"][1].update(heading="Copper demonstrates synergy"), "asserts a result"),
    (lambda o, m: o["sections"][1].update(section_id="S1"), "used more than once"),
    (lambda o, m: m["papers"].append(paper(16)), "at most 15"),
    (lambda o, m: m["papers"][5].update(intended_reading_level="FULL_TEXT",
                                        actual_access={"level": "FULL_TEXT", "figures_inspected": True, "supplements_inspected": False}),
     "the priced plan allows 5"),
    (lambda o, m: m["papers"][0]["actual_access"].update(level="ABSTRACT", figures_inspected=False), "only the abstract was obtained"),
    (lambda o, m: m["papers"][7]["actual_access"].update(figures_inspected=True), "cannot have been inspected for an abstract-only"),
    (lambda o, m: m["papers"][3].update(pmid=m["papers"][2]["pmid"]), "same pmid"),
    (lambda o, m: m["papers"][3].update(pmid=None), "needs a PMID"),
    (lambda o, m: m["papers"][3].update(informs_sections=["S9"]), "which the outline does not have"),
])
def test_specification_problems_are_named(mutate, expected):
    o, m = outline(), manifest()
    mutate(o, m)
    with pytest.raises(run_spec.SpecError, match=expected):
        run_spec.check(o, m, LIMITS)


def test_importance_and_access_are_separate_facts():
    m = manifest()
    m["papers"][8].update(scientific_importance="CORE")               # a CORE paper available only as an abstract
    summary = run_spec.check(outline(), m, LIMITS)
    assert summary["core_read_as_abstract"] == ["P09"] and summary["full_text"] == 5
    access = run_spec.source_access(m["papers"][8], "ABSTRACT")
    assert access == {"level": "ABSTRACT", "figure_legends_read": False, "figure_images_inspected": False,
                      "researcher_inspected_figures": False, "supplements_inspected": False,
                      "scientific_importance": "CORE", "note": ""}


def test_the_cp2_selection_must_be_exactly_the_manifest():
    m = manifest(2, 1)
    records = [{"record_id": "R0001", "pmid": "30000001"}, {"record_id": "R0002", "doi": "10.1000/x", "pmid": "999"},
               {"record_id": "R0003", "pmid": "30000003"}]
    problems = run_spec.selection_problems(m, records)
    assert problems == ["selected but not in the corpus manifest: R0002",
                        "in the corpus manifest but not selected (not retrieved, or deselected): P02"]
    assert run_spec.selection_problems(m, [{"record_id": f"R{i}", "pmid": str(30000000 + i)} for i in (1, 2, 3)]) == []


def test_plan_must_use_the_outline_and_unplaced_evidence_goes_to_a_queue():
    plan = {"sections": [{"section_id": "S1", "ordered_items": [{"item_id": "P1"}]}, {"section_id": "S7", "ordered_items": []}]}
    problems, coverage = run_spec.plan_problems(plan, outline())
    assert problems == ["plan section S7 is not in the researcher's outline"]
    assert coverage["sections_without_evidence"] == ["S2"]            # reported, not padded
    ledger = [{"item_id": "P1", "outcome": "DISCUSSED", "section_id": "S1", "reason": None},
              {"item_id": "P9", "outcome": "NOT_INDIVIDUALLY_DISCUSSED", "section_id": None, "reason": "OUTSIDE_OUTLINE: pharmacokinetics"}]
    assert run_spec.unmapped(ledger) == [{"item_id": "P9", "outcome": "NOT_INDIVIDUALLY_DISCUSSED",
                                          "reason": "OUTSIDE_OUTLINE: pharmacokinetics"}]


def test_a_new_run_stores_the_specification_and_seeds_the_search_with_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    with pytest.raises(ValueError, match="a corpus manifest needs an outline"):
        orch.new_run("topic", corpus_manifest=manifest(), corpus_mode="OPEN_CORPUS")
    with pytest.raises(ValueError, match="OPEN_CORPUS"):
        orch.new_run("topic", outline=outline(), corpus_manifest=manifest())
    bad = manifest()
    bad["papers"].append(paper(16))
    with pytest.raises(run_spec.SpecError):
        orch.new_run("topic", outline=outline(), corpus_manifest=bad, corpus_mode="OPEN_CORPUS", profile="corpus15")
    assert list(tmp_path.iterdir()) == [] or not any(p.is_dir() and (p / "state.json").exists() for p in tmp_path.iterdir())
    run_id = orch.new_run("topic", outline=outline(), corpus_manifest=manifest(), corpus_mode="OPEN_CORPUS", profile="corpus15")
    d = tmp_path / run_id
    spec = json.loads((d / "input" / "run_spec.json").read_text())
    assert spec["full_text"] == 5 and "A07-SYN" in spec["configuration"]["agents"] and spec["configuration"]["prices_sha256"]
    assert len((d / "input" / "seeds.txt").read_text().split()) == 15
    state = json.loads((d / "state.json").read_text())
    assert state["profile"] == "corpus15" and state["execution_mode"] == "STANDARD"
    assert BudgetTracker(d).cap == 80.0 and run_spec.load(d)[0]["working_title"] == "Disulfiram in glioblastoma"
    assert BudgetTracker(d).spent() == 0.0                       # a fresh run starts from zero: no carried-over spend
    from litreview import corpus_policy
    run = orch.Run(run_id)
    policy = corpus_policy.resolve(run)                          # identifier-only retrieval of exactly the manifest
    assert (policy["source"], policy["broad_discovery"], policy["citation_expansion"]) == ("MANIFEST", False, False)
    levels = corpus_policy.fixed(run)
    assert len(levels) == 15 and sorted(levels.values()).count("FULL_TEXT") == 5
    corpus_policy.require_source(run, {"pmid": "30000001", "pmcid": "PMC1"})          # a full-text paper: allowed
    with pytest.raises(ValueError, match="does not mark this paper for full-text"):
        corpus_policy.require_source(run, {"pmid": "30000009", "pmcid": "PMC9"})      # an abstract paper: refused
    with pytest.raises(ValueError, match="unexpected/missing/duplicate PMID"):
        corpus_policy.require_records(run, [{"pmid": "12345"}])                       # nothing outside the manifest
    with pytest.raises(ValueError, match="identifier-only"):
        corpus_policy.require_query(run, "pubmed", {"purpose": "DISCOVERY"}, "disulfiram AND glioblastoma")
    tampered = json.loads((d / "input" / "corpus_manifest.json").read_text())
    tampered["papers"][0]["intended_reading_level"] = "ABSTRACT"
    (d / "input" / "corpus_manifest.json").write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="differs from the run's corpus manifest"):
        corpus_policy.resolve(run)
    assert not (d / "input" / "evaluation_budget.json").exists()


def test_templates_in_the_repository_are_valid():
    o = json.loads((REPO_ROOT / "docs" / "run_spec" / "outline.template.json").read_text(encoding="utf-8"))
    m = json.loads((REPO_ROOT / "docs" / "run_spec" / "corpus.template.json").read_text(encoding="utf-8"))
    assert run_spec.outline_problems(o) == [] and run_spec.corpus_problems(m, LIMITS, None, o) == []


# --------------------------------------------------------------------------------------- science wording rules
FLAGGED = [
    ("COPPER_ABSENCE", "Disulfiram without copper reduced sphere formation [@R0001]."),
    ("COPPER_ABSENCE", "Under copper-free conditions the drug was inactive [@R0001]."),
    ("NULL_FROM_NONSIGNIFICANCE", "Disulfiram had no effect on tumour growth in vivo [@R0001]."),
    ("NULL_FROM_NONSIGNIFICANCE", "Exogenous TGF-Î²1 did not affect motility of resistant cells [@R0001]."),
    ("UNDEFINED_MEDIAN", "Median survival was not reached in the three treated arms [@R0001]."),
    ("UNDEFINED_MEDIAN", "The median survival of treated mice was not defined [@R0001]."),
    ("PERCENT_WITHOUT_COMPARATOR", "Three treatments left 85.5% viability in resistant cells [@R0001]."),
    ("REPLICATION_CLAIM", "This effect was independently replicated in two cohorts [@R0002; @R0003]."),
    ("REPLICATION_CLAIM", "The finding was consistent across studies [@R0002; @R0003]."),
]
CLEAN = [
    "Disulfiram was given with no copper supplementation reported [@R0001].",
    "Tumour growth did not differ significantly between disulfiram and vehicle (test not reported) [@R0001].",
    "Viability was 85.5% relative to untreated cells after three treatments [@R0001].",
    "Two papers reported the same trial, so they count as one study [@R0002; @R0003].",
    "The authors stated that median survival for vehicle-treated mice was 54 days [@R0001].",
]


@pytest.mark.parametrize("rule,sentence", FLAGGED)
def test_overstating_wording_is_flagged(rule, sentence):
    flags = science_lint.check_text(sentence)
    assert rule in {f["rule"] for f in flags}, flags


@pytest.mark.parametrize("sentence", CLEAN)
def test_careful_wording_is_not_flagged(sentence):
    assert science_lint.check_text(sentence) == []


def test_abstract_only_citations_cannot_carry_methods_or_figures():
    access = {"R0001": "FULL_TEXT", "R0002": "ABSTRACT", "R0003": "ABSTRACT"}
    s = "Western blot in Figure 2 showed reduced ALDH1A1 [@R0002; @R0003]."
    assert [f["rule"] for f in science_lint.check_text(s, access)] == ["ABSTRACT_OVERREACH"]
    assert science_lint.check_text("Western blot in Figure 2 showed reduced ALDH1A1 [@R0001; @R0002].", access) == []
    assert science_lint.check_text("The abstract reports reduced ALDH1A1 [@R0002].", access) == []


def test_every_rule_is_also_a_prompt_instruction():
    policy = (SHARED_PROMPTS_DIR / "language_policy.md").read_text(encoding="utf-8")
    core = (SHARED_PROMPTS_DIR / "core_rules.md").read_text(encoding="utf-8")
    for phrase in ("no copper supplement is not copper-free", "A non-significant result is not a null result",
                   '"not reached" only if the source says so', "A percentage needs its reference",
                   "are one study"):
        assert phrase in policy, phrase
    for phrase in ("A missing measurement stays unresolved", "bounded by its abstract", "researcher_decisions"):
        assert phrase in core, phrase
    a05 = (REPO_ROOT / "prompts" / "agents" / "A05-KE_Knowledge_Extraction.md").read_text(encoding="utf-8")
    assert "percentage of control with no control named stays `NONE_REPORTED`" in a05


def test_flags_block_submission_until_a_person_reviews_them(tmp_path):
    from litreview.tools import submission
    flags = science_lint.check_manuscript({"title": "T", "abstract": "A.", "sections": [
        {"section_id": "S2", "text_markdown": "Disulfiram had no effect on tumour growth [@R0001]. âŸ¦P1âŸ§"}]})
    assert len(flags) == 1
    comp = {"checks": []}
    blocked = submission.status(tmp_path, {}, [], comp, None, flags)
    assert any("NULL_FROM_NONSIGNIFICANCE" in b for b in blocked["blockers"])
    (tmp_path / "science_lint_reviewed.json").write_text(json.dumps(
        {flags[0]["key"]: {"by": "May Khalid", "note": "source reports an equivalence margin; wording kept"}}))
    after = submission.status(tmp_path, {}, [], comp, None, flags)
    assert not any("Wording to check" in b for b in after["blockers"])


# ---------------------------------------------------------------------------------- structured output gating
def test_structured_output_is_used_only_for_a_combination_the_smoke_test_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(structured, "RECORD", tmp_path / "structured_output.json")
    assert structured.response_schema("A07-SYN", "A07-SYN.bounded-plan.schema.json", "anthropic", "claude-opus-5") is None
    schema, sha = structured.slim("A07-SYN.bounded-plan.schema.json")
    assert "maxLength" not in json.dumps(schema) and schema["additionalProperties"] is False
    from litreview.smoke_validation import inspect_response
    example=json.loads((REPO_ROOT / "docs/a07_a12_contract_hardening/schema_examples.json").read_text(encoding="utf-8"))["A07-SYN.bounded-plan.schema.json"]
    proof=inspect_response("anthropic",json.dumps(example),"end_turn",schema,sha)
    assert proof["accepted"]
    structured.record("anthropic", "claude-opus-5", sha, True, "stop_reason end_turn",validation=proof)
    got = structured.response_schema("A07-SYN", "A07-SYN.bounded-plan.schema.json", "anthropic", "claude-opus-5")
    assert got["schema"] == schema and got["name"] == "A07_SYN_bounded_plan"
    assert structured.response_schema("A07-SYN", "A07-SYN.bounded-plan.schema.json", "anthropic", "claude-opus-5-5") is None
    structured.record("anthropic", "claude-opus-5", sha, False, "400 unsupported keyword")
    assert structured.response_schema("A07-SYN", "A07-SYN.bounded-plan.schema.json", "anthropic", "claude-opus-5") is None
    assert structured.response_schema("A11-RC", None, "kimi", "kimi-k3.1-pro") is None        # Kimi: JSON mode only


def test_the_request_carries_the_schema_and_the_full_validator_still_runs():
    from litreview.llm import anthropic_client, openai_compatible as oc
    shape = {"name": "x", "schema": {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}}
    body = anthropic_client.message_params("s", "u", "claude-opus-5", 100, 0.0, "medium", response_schema=shape)
    assert body["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": shape["schema"]}}
    assert "format" not in anthropic_client.message_params("s", "u", "claude-opus-5", 100, 0.0, "medium").get("output_config", {})
    chat = oc.chat_params("s", "u", "gpt-6.1-sol", 100, 0.0, effort="medium", response_schema=shape)
    assert chat["response_format"]["type"] == "json_schema" and chat["response_format"]["json_schema"]["schema"] == shape["schema"]
    assert oc.chat_params("s", "u", "gpt-6.1-sol", 100, 0.0)["response_format"] == {"type": "json_object"}


def test_smoke_test_lists_targets_and_refuses_without_an_approved_amount(tmp_path, monkeypatch):
    from litreview.smoke_validation import schema_hash
    shape={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    sample=[{"agent":a,"provider":p,"model":m,"effort":None,"schema_file":a+".fixture","schema":shape,"schema_sha256":schema_hash(shape),"already_verified":False}
        for a,p,m in [("A05-KE","anthropic","claude-haiku-5-5"),("A07-SYN","anthropic","claude-opus-5"),("A10-RV","openai","gpt-6.1-sol")]]
    monkeypatch.setattr(structured,"targets",lambda:sample)
    monkeypatch.setattr(structured, "RECORD", tmp_path / "structured_output.json")
    b = BudgetTracker(tmp_path)
    usd, todo = structured.smoke_estimate(b)
    assert usd > 0 and {t["agent"] for t in todo} >= {"A05-KE", "A07-SYN", "A10-RV"} and all(t["provider"] != "kimi" for t in todo)
    with pytest.raises(ValueError, match="over the approved"):
        structured.smoke_test(b, 0.0001, "May Khalid")
    with pytest.raises(ValueError, match="name of the person"):
        structured.smoke_test(b, 100.0, "")
    calls = []

    def complete(provider, **kw):
        calls.append((provider, kw["model"], bool(kw["response_schema"])))
        if kw["model"] == "claude-haiku-5-5":
            raise RuntimeError("400 schema not supported")
        from litreview.llm.base import LLMResponse
        return LLMResponse('{"ok":true}', provider, kw["model"], 500, 20, "end_turn" if provider=="anthropic" else "stop")
    monkeypatch.setattr("litreview.llm.complete", complete)
    result = structured.smoke_test(b, usd + 1, "May Khalid", tmp_path / "smoke.jsonl")
    assert result["tested"] == len(todo) == len(calls) and all(c[2] for c in calls)
    assert result["accepted"] == result["tested"] - sum(1 for t in todo if t["model"] == "claude-haiku-5-5")
    assert structured.smoke_estimate(b)[1] != [] or result["accepted"] == result["tested"]    # rejected ones stay listed


# ----------------------------------------------------------------------------------------------- budget plan
def test_stage_caps_are_derived_from_the_projection_and_cannot_conflict_with_it():
    d = derive_stage_caps({"A07-SYN": 35.9, "A10-RV": 41.49, "A08-OL": 1.25, "A09-WRI": 23.64}, 0.15)
    assert d["caps_usd"]["A07"] >= 35.9 * 1.15 and d["caps_usd"]["A10"] >= 41.49 * 1.15
    assert d["caps_usd"]["A08-A09"] >= (1.25 + 23.64) * 1.15 and d["total_usd"] == round(sum(d["caps_usd"].values()), 2)
    for name in ("manuscript", "corpus15"):
        assert config.run_settings(name)["stage_caps_usd"] == "derived"


def test_the_five_plus_ten_plan_separates_its_parts_and_fits_its_profile():
    import importlib.util
    spec = importlib.util.spec_from_file_location("plan_budget", REPO_ROOT / "scripts" / "plan_budget.py")
    pb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pb)
    plan = pb.plan(5, 10, None, "corpus15")
    assert plan["corpus"] == {"full_text": 5, "abstract": 10, "expected_findings": 238, "manuscript_words_assumed": 5000}
    assert plan["expected_usd"]["total"] == pytest.approx(sum(v for k, v in plan["expected_usd"].items() if k != "total"), abs=0.02)
    assert plan["uncertainty_allowance_usd"] == pytest.approx(plan["expected_usd"]["total"] * 0.3, abs=0.02)
    assert plan["recovery_allowance_usd"] > 0 and plan["smoke_test_allowance_usd"] == 1.0
    for stage, cap in plan["stage_sub_caps_usd"].items():
        assert cap >= plan["expected_usd"][stage] * 1.3                 # every stage can afford its own projected work
    assert all(plan["fits"].values()) and plan["stage_sub_caps_total_usd"] + 1.0 <= plan["profile"]["hard_cap_usd"]
    shorter = pb.plan(5, 10, 3000, "corpus15")
    assert shorter["expected_usd"]["A10"] < plan["expected_usd"]["A10"]  # verification scales with the prose, not the papers
    assert shorter["expected_usd"]["A07"] == plan["expected_usd"]["A07"]


def test_explicit_counts_ignore_the_assumed_core_share(tmp_path):
    from litreview.tools import forecast
    cfg = copy.deepcopy(config.load("pipeline"))
    b = BudgetTracker(tmp_path)
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]   # noqa: E731
    rates = json.loads((REPO_ROOT / "records" / "cost_rates.json").read_text(encoding="utf-8"))
    r = forecast.full_run(15, 0.99, cfg, b, route, rates, explicit={"full_text": 5, "abstract": 10})
    cfg["forecast"]["core_share"] = 0.05
    r2 = forecast.full_run(15, 0.01, cfg, b, route, rates, explicit={"full_text": 5, "abstract": 10})
    assert (r["full_text"], r["abstract"]) == (5, 10) == (r2["full_text"], r2["abstract"]) and r["findings"] == r2["findings"]


# ----------------------------------------------------------------------- early check after the first papers
def test_extraction_stops_after_one_full_text_and_two_abstracts_until_the_researcher_has_looked(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    monkeypatch.setattr(orch.notify, "send", lambda *a, **k: False)
    run_id = orch.new_run("topic", outline=outline(), corpus_manifest=manifest(), corpus_mode="OPEN_CORPUS", profile="corpus15")
    run = orch.Run(run_id)
    corpus = [{"record_id": f"R{i:04d}", "pmid": p["pmid"], "pmcid": f"PMC{i}", "abstract": "An abstract.",
               "manifest_paper_id": p["paper_id"], "intended_reading_level": p["intended_reading_level"],
               "tier": p["scientific_importance"]} for i, p in enumerate(manifest()["papers"], 1)]
    run.save("selected_corpus.json", corpus)
    run.save("spec_approved.json", {"central_question": "q"})
    for r in corpus[:5]:
        run.save(f"fulltext/{r['record_id']}.json", {"Abstract": "a", "Results": "b"})
    run.save_state({**run.state(), "stage": "extract"})
    monkeypatch.setattr(orch, "verify_cached_source", lambda *a, **k: None)
    calls = []

    def run_many(agent, items, on_output, exclude=None):
        for step, payload in items:
            calls.append(step)
            on_output(step, {"content_level": payload["content_level"], "findings": [{"finding_id": "F1", "context_id": "C1"}],
                             "contexts": [{"context_id": "C1", "comparator": "NONE_REPORTED"}]})
    monkeypatch.setattr(run, "run_many", run_many)
    monkeypatch.setattr(run, "_normalize", lambda rid, ext: ext)
    def validate(corpus):
        for r in corpus:
            rid = r["record_id"]
            if not run.data(f"validations/{rid}.json").exists():
                calls.append(f"A06-SV_{rid}_v1")
                run.save(f"validations/{rid}.json", {"validations": [{"disposition": "SUPPORTED"}]})
    monkeypatch.setattr(run, "_validate_subset", validate)
    with pytest.raises(orch.Pause, match="waiting for CP_EARLY"):
        run.stage_extract(run.state())
    assert calls == ["A05-KE_R0001", "A05-KE_R0006", "A05-KE_R0007", "A06-SV_R0001_v1", "A06-SV_R0006_v1", "A06-SV_R0007_v1"]     # one full text, two abstracts, manifest order
    report = run.load("early_check.json")
    assert [p["level"] for p in report["papers"]] == ["FULL_TEXT", "ABSTRACT", "ABSTRACT"]
    assert report["papers"][0]["comparator_not_reported"] == 1 and "forecast" in report
    access = run.load("source_access.json")
    assert access["R0006"]["level"] == "ABSTRACT" and access["R0001"]["figure_images_inspected"] is False
    cp = orch.checkpoints.cp_dir(run.dir)
    with pytest.raises(orch.checkpoints.DecisionIncomplete, match="record what you inspected"):
        orch.checkpoints.approve(run.dir, "CP_EARLY", run.prov)
    decision = json.loads((cp / "CP_EARLY_decision.json").read_text())
    decision.update(approve_continue=True, notes="Checked spans and comparators for P01, P06 and P07 against the PDFs.")
    (cp / "CP_EARLY_decision.json").write_text(json.dumps(decision))
    orch.checkpoints.approve(run.dir, "CP_EARLY", run.prov)
    assert run.stage_extract(run.state()) == "validate"
    assert len(calls) == 18 and len(set(calls)) == 18                     # the first three are not read again
