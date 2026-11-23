"""Phase 1.5 NON-REPRESENTATIVE A07 -> A09 sample mode. Offline only; fixture outputs are not scientific results."""
import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from litreview import config, checkpoints, sample_mode as sm, singlepaper_eval as se
from litreview.budget import BudgetTracker, BudgetExceeded
from litreview.orchestrator import Run, Pause
from litreview.provenance import ProvenanceLog
from litreview.scientific_validation import require_package
from litreview.synthesis_bounded import RegistrySynthesisJob, ImportApprovalRequired
from litreview.synthesis_job import JobStopped
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens, canonical, fingerprint
from test_synthesis_bounded import corpus, FixtureModel, header

SOURCE_TAG = "0123456789abcdef"
STEP = f"A07-SYN_job{SOURCE_TAG}_PLAN"
SETTINGS = {"max_findings_per_group": 2}


def repaired_plan():
    return {**header("PLAN"), "theme_change_proposals": [], "scope_drift": ["fixture"],
            "unresolved_questions": [{"theme_id": "T1", "questions": ["fixture"]}]}


class FakeRun:
    """The parts of WritingRun that sample_mode uses, over the bounded-synthesis test corpus."""

    def __init__(self, tmp, sample_ids=None, model=None):
        self.dir, self.id = Path(tmp) / "run", "single"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cfg = copy.deepcopy(config.load("pipeline"))
        self.budget, self.prov = BudgetTracker(self.dir), ProvenanceLog(self.dir)
        self.baseline = Decimal("7.3163356")
        self.data_ = corpus()
        self.model = model
        self.sample = None
        if sample_ids is not None:
            self.sample = sm.write_policy(self, sample_ids, created_by="test")

    def route(self, agent, exclude=frozenset()):
        return config.agent_model(agent)

    def load(self, name, default=None):
        p = self.dir / "data" / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def save(self, name, obj):
        p = self.dir / "data" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    def _synthesis_job(self):
        cfg = {**self.cfg["synthesis"], **SETTINGS, "max_retrieval_rounds": 0}
        cls = RegistrySynthesisJob
        if self.sample:
            cfg["sample"] = {"version": sm.VERSION, "label": sm.LABEL, "group_ids": self.sample["group_ids"]}
            cls = sm.SampleSynthesisJob
        reg = EvidenceRegistry(self.data_)
        tag = fingerprint({"corpus": reg.digest, "settings": cfg})[:16]
        model = self.model or FixtureModel(reg)
        self.model = model
        approve = lambda digest, alignment: bool((checkpoints.approved(self.dir, "CP_SYN") or {}).get("approve_alignment"))
        return cls(self.dir / "data" / f"synthesis_job_{tag}", reg, model, offline_tokens, cfg,
                   {"prompt": "fixture"}, approve), tag


def owners(tmp):
    """Packets that own mandatory items (the minimum honest sample) and the full packet list."""
    job, _ = FakeRun(Path(tmp) / "probe")._synthesis_job()
    own = [p["group_id"] for p in job.packets if p["manifest_item_ids"]]
    return own, [p["group_id"] for p in job.packets]


def stage_source(run, repaired=None):
    out = run.dir / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    raw = '{"agent_id": "A07-SYN", "status": "COMPLETE", "fivew1h": [{"theme_id": "T1", "unresolved": ["a", "b"]}]}'
    (out / f"{STEP}.raw0.txt").write_text(raw, encoding="utf-8")
    (out / f"{STEP}.repaired.json").write_text(json.dumps(repaired or repaired_plan()), encoding="utf-8")
    (out / f"{STEP}.provider.receipt0.json").write_text(json.dumps({"id": "msg_fixture", "stop_reason": "end_turn"}))
    src = run.dir / "data" / f"synthesis_job_{SOURCE_TAG}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "registry.json").write_text(canonical(EvidenceRegistry(run.data_).corpus), encoding="utf-8")
    (src / "identity.json").write_text(json.dumps({"fingerprint": "v10-identity"}))
    return sm.sha256_file(out / f"{STEP}.raw0.txt"), sm.sha256_file(out / f"{STEP}.repaired.json")


def do_import(run, raw, rep):
    return sm.import_repaired_plan(run, source_step=STEP, raw_sha=raw, repaired_sha=rep)


# ------------------------------------------------------------------ import
def test_import_refuses_hash_mismatch_and_writes_nothing(tmp_path):
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own)
    raw, rep = stage_source(run)
    with pytest.raises(sm.SampleRefused, match="hash mismatch"):
        sm.import_repaired_plan(run, source_step=STEP, raw_sha=raw, repaired_sha="0" * 64)
    with pytest.raises(sm.SampleRefused, match="hash mismatch"):
        sm.import_repaired_plan(run, source_step=STEP, raw_sha="0" * 64, repaired_sha=rep)
    assert not list((run.dir / "data").glob("synthesis_job_*/plan_import.json"))
    assert not list((run.dir / "data").glob("synthesis_job_*/turns/PLAN.json"))


def test_v10_hashes_are_the_defaults():
    assert sm.V10_RAW_SHA.startswith("3d2f03ade433") and sm.V10_REPAIRED_SHA.startswith("958ea8e00eab")


@pytest.mark.parametrize("defect", ["missing_mode", "fivew1h_array", "long_rationale", "fifteen_ids"])
def test_import_runs_the_production_plan_validator_on_v10_violation_types(tmp_path, defect):
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own)
    reg = EvidenceRegistry(run.data_)
    plan = repaired_plan()
    if defect == "missing_mode":
        plan.pop("mode")
    elif defect == "fivew1h_array":
        plan["fivew1h"] = [{"theme_id": "T1", "unresolved": ["a", "b"]}]
    elif defect == "long_rationale":
        plan["theme_change_proposals"] = [{"proposal": "p", "rationale": "r" * 517, "finding_ids": [sorted(reg.findings)[0]]}]
    else:
        plan["theme_change_proposals"] = [{"proposal": "p", "rationale": "r", "finding_ids": sorted(reg.findings)[:12] * 2}]
    raw, rep = stage_source(run, plan)
    with pytest.raises(Exception) as e:
        do_import(run, raw, rep)
    assert type(e.value).__name__ in ("ValidationError", "ValueError")
    job, _ = run._synthesis_job()
    assert job._marker("PLAN") is None and not (job.dir / "plan_import.json").exists()


def test_imported_plan_is_not_a_model_acceptance_and_blocks_group_until_approved(tmp_path):
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own)
    raw, rep = stage_source(run)
    out = do_import(run, raw, rep)
    assert out["record"]["researcher_approved"] is False
    assert out["record"]["original_raw_sha256"] == raw and out["record"]["repaired_sha256"] == rep
    assert out["record"]["repair_audit_sha256"] and out["record"]["source_identity_fingerprint"] == "v10-identity"
    job, _ = run._synthesis_job()
    events = [e["event"] for e in job.ledger.events()]
    assert "TURN_IMPORTED_REPAIR" in events and "TURN_ACCEPTED" not in events
    assert job.ledger.state()["models_by_turn"]["PLAN"] == "researcher-repair-of:" + raw
    with pytest.raises(ImportApprovalRequired):
        job.run()
    assert run.model.calls == []                                   # no GROUP, and the PLAN was never re-generated
    with pytest.raises(sm.SampleRefused, match="different repaired PLAN"):
        sm.approve_plan_import(run, "f" * 64, "May")
    with pytest.raises(sm.SampleRefused, match="named approver"):
        sm.approve_plan_import(run, rep, " ")
    sm.approve_plan_import(run, rep, "May")
    with pytest.raises(sm.SampleRefused, match="refusing overwrite"):
        sm.approve_plan_import(run, rep, "May")
    with pytest.raises(sm.SampleRefused, match="refusing a second|already"):
        do_import(run, raw, rep)


def test_import_in_a_live_runtime_requires_the_live_flag(tmp_path, monkeypatch):
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own)
    raw, rep = stage_source(run)
    monkeypatch.setattr(sm, "frozen_runtime", lambda: True)
    with pytest.raises(sm.SampleRefused, match="live runtime"):
        do_import(run, raw, rep)


# ------------------------------------------------------------------ sample scope
def test_sample_must_own_every_mandatory_item(tmp_path):
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own[1:])
    with pytest.raises(JobStopped, match="mandatory items unowned"):
        run._synthesis_job()


def test_sample_package_labels_out_of_scope_and_passes_the_unchanged_cp3_validator(tmp_path):
    own, every = owners(tmp_path)
    assert len(own) < len(every)
    run = FakeRun(tmp_path, own)
    raw, rep = stage_source(run)
    do_import(run, raw, rep)
    sm.approve_plan_import(run, rep, "May")
    job, _ = run._synthesis_job()
    job.approve = lambda *a: True
    pkg = job.run()
    assert pkg["status"] == "COMPLETE" and pkg["sample"]["label"] == sm.LABEL
    assert pkg["warnings"][0].startswith(sm.LABEL)
    excluded = set(pkg["sample"]["excluded_finding_ids"])
    assert excluded and all(pkg["finding_dispositions"][f] == [sm.OUT_OF_SCOPE] for f in excluded)
    assert [m for m, _, _ in run.model.calls if m == "PLAN"] == []
    assert {t for m, _, t in run.model.calls if m == "GROUP"} == {f"GROUP_{g}_LOOKUP0" for g in own}
    require_package(pkg, run.data_["validated_findings"])


def test_a_full_run_refuses_a_sample_package(monkeypatch):
    r = Run.__new__(Run)
    r.dir = Path(".")
    r._sample_mode = lambda: False
    monkeypatch.setattr(checkpoints, "approved", lambda *a: {"synthesis_fingerprint": "x"})
    r._framework_update = lambda *a: None
    r._publishable = lambda name: {"status": "COMPLETE", "sample": {"label": sm.LABEL}}
    with pytest.raises(Pause, match="NON-REPRESENTATIVE"):
        r.stage_cp3({})


# ------------------------------------------------------------------ dry run, projection, reserve
def test_dry_run_makes_no_network_call_and_never_writes_the_run(tmp_path, monkeypatch):
    from litreview.llm import router, anthropic_client, openai_compatible
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own)
    raw, rep = stage_source(run)
    do_import(run, raw, rep)
    calls = []
    for name in list(router._PROVIDERS):
        monkeypatch.setitem(router._PROVIDERS, name, lambda **k: calls.append(k))
    monkeypatch.setattr(anthropic_client, "_get_client", lambda *a: calls.append("anthropic sdk"))
    monkeypatch.setattr(openai_compatible, "_get_client", lambda *a: calls.append("openai sdk"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.dir.rglob("*") if p.is_file()}
    lines = []
    out = sm.dry_run(run, out=lines.append)
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.dir.rglob("*") if p.is_file()}
    assert calls == [] and before == after
    assert out["gates"] == {"plan_imported": True, "plan_import_approved": False, "cp_syn_approved": False}
    groups = [r for r in out["rows"] if r.get("mode") == "GROUP"]
    assert len(groups) == len(own) and all(r["basis"].startswith("EXACT") and r["usd"] > 0 for r in groups)
    assert any(r.get("mode") == "RECONCILE" and r["basis"].startswith("ENVELOPE") for r in out["rows"])
    assert not any(r.get("agent") in ("A10-RV", "A11-RC", "A12-EDI") for r in out["rows"])
    assert router._PROVIDERS[next(iter(router._PROVIDERS))] is not None and calls == []


def test_sample_projection_prices_only_sample_calls_and_excludes_the_candidate(tmp_path):
    from litreview import pilot_authorization as pilot
    own, _ = owners(tmp_path)
    run = FakeRun(tmp_path, own)
    p = sm.projection(run, pilot.STAGE_1)
    assert {x["stage"] for x in p["lines"]} == {"A07-SYN"} and p["retry_share"] == 0.0
    n = len(p["lines"])
    q = sm.projection(run, pilot.STAGE_1, candidate=("A07-SYN", 1.0))
    assert len(q["lines"]) == n - 1 and q["committed_usd"] == pytest.approx(1.0)
    with pytest.raises(pilot.AuthorizationRequired, match="undetermined until CP3"):
        sm.projection(run, pilot.STAGE_2)


def test_worst_case_prices_input_at_the_cache_write_rate():
    b = StubBudget()
    opus, gpt = config.agent_model("A09-WRI"), config.agent_model("A08-OL")
    assert sm.worst_case_usd(b, opus, 1_000_000, 0) == pytest.approx(10.0)    # 1h write, not $5 input
    assert sm.worst_case_usd(b, gpt, 100_000, 0) == pytest.approx(0.25)       # 30m write $2.50, not $2.00 input


class StubBudget(BudgetTracker):
    """Real price tables and cost arithmetic; spent/reserved supplied by the test."""
    def __init__(self, spent=7.3163356):
        self.prices, self._spent = config.load("prices"), spent

    def spent(self):
        return self._spent

    def reserved(self):
        return 0.0

    def reservations(self):
        return {}


def writing_run(sample=True, spent=7.3163356):
    r = se.WritingRun.__new__(se.WritingRun)
    r.baseline, r.dry_cap = Decimal("7.3163356"), None
    r.sample = {"a08_max_tokens": 8000, "a09_max_tokens": 16000, "a09_effort": "medium", "max_sections": 2,
                "min_words": 800, "max_words": 1000, "group_ids": ["G0001"]} if sample else None
    r.budget = StubBudget(spent)
    r.cfg = copy.deepcopy(config.load("pipeline"))
    r.route = lambda agent, exclude=frozenset(): config.agent_model(agent)
    return r


def test_reserve_blocks_an_over_cap_sample_call_before_dispatch(monkeypatch):
    r = writing_run(spent=7.3163356 + 14.0)
    saved, calls = [], []
    r.save = lambda *a: saved.append(a)
    monkeypatch.setattr(Run, "_reserve", lambda *a, **k: calls.append(a))
    with pytest.raises(BudgetExceeded):
        r._reserve("a09-key", 0.80, "A09-WRI", steps=["A09-WRI_sample1_S1_r0"])   # 14 + 0.80 x 1.3 > 15
    assert calls == [] and saved[0][1]["provider_dispatched"] is False
    r2 = writing_run()
    r2.save = lambda *a: None
    r2._reserve("a09-key", 0.20, "A09-WRI")
    assert len(calls) == 1


def test_sample_admission_applies_sample_caps_effort_and_refuses_a10_a12(monkeypatch):
    r = writing_run()
    seen = {}

    def native(self, agent_id, payload, step, schema_file=None, exclude=frozenset(), limit=None, extra=None):
        seen.update(agent=agent_id, extra=extra, floor=self._cache_reservation_floor, limit=limit)
        return {"status": "COMPLETE"}
    monkeypatch.setattr(Run, "_admitted", native)
    r._admitted("A09-WRI", {"mode": "SECTION"}, "A09-WRI_sample1_S1_r0", limit="A09_SECTION")
    assert seen["extra"] == {"max_tokens": 16000, "effort": "medium"} and seen["floor"][1] > 0
    r._admitted("A08-OL", {"x": 1}, "A08-OL_v1")
    assert seen["extra"] == {"max_tokens": 8000}
    for agent in ("A10-RV", "A11-RC", "A12-EDI"):
        with pytest.raises(Pause, match="never runs"):
            r._admitted(agent, {}, "x")


def test_a09_request_sends_effort_only_never_a_thinking_budget():
    from litreview.llm.anthropic_client import message_params
    body = message_params("system", [{"text": "u", "cache": False}], "claude-opus-5", 16000, 0.5, "medium",
                          trace={"agent": "A09-WRI", "step": "A09-WRI_sample1_S1_r0"})
    assert body["output_config"] == {"effort": "medium"} and body["max_tokens"] == 16000
    assert "budget_tokens" not in json.dumps(body)


def test_a09_16k_cap_leaves_thinking_headroom_for_a_1000_word_section():
    """A schema-valid ~1,000-word section with a tag on every sentence. Its byte bound (>= its token count) must
    leave at least 5,000 tokens of the 16k cap for adaptive thinking; 2,500 cannot even hold the text."""
    import jsonschema
    from litreview.paths import SCHEMAS_DIR
    sentence = ("Disulfiram combined with copper reduced viability in the reported glioblastoma cell line under the "
                "stated exposure conditions [R0001] ⟦GROUP_G0003.P12, GROUP_G0001.K1⟧ ")
    text = sentence * 51
    words = len(text.split())
    out = {"agent_id": "A09-WRI", "prompt_version": "0.3", "status": "COMPLETE", "warnings": [], "limitations": [],
           "mode": "SECTION", "section": {"section_id": "S1", "heading": "Preclinical evidence",
                                          "text_markdown": text, "word_count": words},
           "retrieval_requests": [], "plan_gaps": [], "ceiling_unclear": []}
    jsonschema.validate(out, json.loads((SCHEMAS_DIR / "A09-WRI.section.schema.json").read_text(encoding="utf-8")))
    assert 1000 <= words <= 1050
    bound = offline_tokens(out)
    assert bound <= 16000 - 5000
    assert bound > 2500


# ------------------------------------------------------------------ control flow
def flow_run(tmp_path, sample=True, state=None):
    r = writing_run(sample=sample)
    r.dir = tmp_path
    st = {"stage": "draft", "evaluation_phase": "write_once", **(state or {})}
    box = {"state": st}
    r.state = lambda: dict(box["state"])
    r.save_state = lambda s: box.update(state=dict(s))
    saved = {}
    r.save = lambda name, obj: saved.update({name: obj})
    return r, box, saved


def test_stop_after_a09_reaches_complete_sample_and_never_calls_a10_a12(tmp_path, monkeypatch):
    r, box, saved = flow_run(tmp_path)
    plan = {"sections": [{"section_id": "S1", "word_budget": 500}, {"section_id": "S2", "word_budget": 450}],
            "writing_order": ["S1", "S2"]}
    r._reproject = lambda stage: None
    r._plan_state = lambda: {"plan": plan, "pv": "pv", "ev": "ev"}
    r._write_sections = lambda ps, label: [{"section_id": "S1", "word_count": 480}, {"section_id": "S2", "word_count": 440}]
    for name in ("_verify_once", "_critique_once", "_edit_once", "_draft_once"):
        setattr(r, name, lambda st, n=name: pytest.fail(f"{n} must not run in sample mode"))
    r.continue_evaluation()
    st = box["state"]
    assert st["stage"] == "sample_complete" and st["status"] == "COMPLETE_SAMPLE" and st["sample"] == sm.LABEL
    out = saved["sample_output.json"]
    assert out["label"] == sm.LABEL and out["verified"] is False and out["a10_a12_run"] is False
    assert out["word_count"] == 920 and out["front_matter_written"] is False


def test_sample_outline_outside_bounds_pauses_not_fails(tmp_path):
    r, box, _ = flow_run(tmp_path)
    r._reproject = lambda stage: None
    r._plan_state = lambda: {"plan": {"sections": [{"word_budget": 300}] * 3, "writing_order": []}, "pv": "", "ev": ""}
    r._write_sections = lambda *a: pytest.fail("no A09 call for an out-of-bounds outline")
    r.continue_evaluation()
    assert box["state"]["status"].startswith("PAUSED: A08 sample outline outside")


def test_sample_never_reaches_verification_phases(tmp_path):
    r, box, _ = flow_run(tmp_path, state={"stage": "review_loop", "evaluation_phase": "verify_once"})
    r._verify_once = lambda st: pytest.fail("A10 must not run in sample mode")
    r.continue_evaluation()
    assert box["state"]["status"].startswith("PAUSED: Unsupported")


def test_critique_still_runs_when_sample_mode_is_off(tmp_path):
    r, box, _ = flow_run(tmp_path, sample=False, state={"stage": "review_loop", "evaluation_phase": "critique_once"})
    ran = []

    def critique(st):
        ran.append("A11")
        r.save_state({**r.state(), "evaluation_phase": "edit_once"})
        return "review_loop"
    r._critique_once = critique
    r._edit_once = lambda st: (ran.append("A12"), "evaluation_done")[1]
    r.continue_evaluation()
    assert ran == ["A11", "A12"] and box["state"]["stage"] == "evaluation_done"


def test_constructor_sample_zero_loops_default_unchanged(tmp_path, monkeypatch):
    from test_singlepaper_eval import make_policy
    make_policy(tmp_path)

    def init(self, run_id):
        self.id, self.dir = run_id, tmp_path
        self.cfg = copy.deepcopy(config.load("pipeline"))
        self.budget = SimpleNamespace()
    monkeypatch.setattr(Run, "__init__", init)
    r = se.WritingRun("single")
    assert r.sample is None and r.cfg["loops"]["max_critique_cycles"] == 1
    monkeypatch.setattr(config, "load", lambda name, _l=config.load: (
        {**_l(name), "loops": {**_l(name)["loops"], "max_critique_cycles": 0}} if name == "pipeline" else _l(name)))
    with pytest.raises(Pause, match="0 redrafts / 1 critique"):
        se.WritingRun("single")
    monkeypatch.undo()
    monkeypatch.setattr(Run, "__init__", init)
    sm.write_policy(SimpleNamespace(dir=tmp_path, id="single"), ["G0001"], created_by="test")
    r = se.WritingRun("single")
    assert r.sample and r.cfg["loops"]["max_critique_cycles"] == 0 and r.cfg["loops"]["max_redrafts"] == 0
    assert r.cfg["synthesis"]["max_retrieval_rounds"] == 0 and r.cfg["bridge"]["max_retrieval_rounds"] == 0
    assert config.load("pipeline")["loops"]["max_critique_cycles"] == 1        # shared configuration untouched


def test_sample_authority_bounds_are_enforced(tmp_path):
    run = SimpleNamespace(dir=tmp_path, id="single")
    for bad in ({"a09_max_tokens": 2500}, {"max_sections": 3}, {"max_words": 1500}, {"a09_effort": "high"}):
        with pytest.raises(sm.SampleRefused):
            sm.write_policy(run, ["G0001"], created_by="t", **bad)
    assert not (tmp_path / sm.POLICY).exists()


# ------------------------------------------------------------------ promotion fixes (2026-11-04 review)
def test_plan_retry_hold_carries_the_margin_once_through_the_real_run_reserve(tmp_path):
    """The previous test replaced Run._reserve, where the second 30% was added. This one runs it."""
    from litreview import plan_retry as pr
    r = pr.PlanRetryRun.__new__(pr.PlanRetryRun)
    r.quote_only, r.baseline, r.dir = False, Decimal("7.3163356"), tmp_path      # no state.json: pilot off
    r.retry = {"allowed_step": "synthetic_PLAN", "cold_plan_usd": 1.624021, "reservation_with_margin_usd": 2.111228}
    held = []
    r.budget = SimpleNamespace(spent=lambda: 7.6957206, reserved=lambda: 0,
                               reserve=lambda key, usd, agent, note="": held.append(usd) or (True, 14))
    r._reserve("key", 1.62402, "A07-SYN", steps=["synthetic_PLAN"])
    assert held == [pytest.approx(2.111228)]                                  # not 2.111228 x 1.30


def test_ordinary_writing_reserve_still_adds_the_margin_once(tmp_path):
    r = Run.__new__(Run)
    r.dir, held = tmp_path, []
    r.budget = SimpleNamespace(reserve=lambda key, usd, agent, note="": held.append(usd) or (True, 1))
    r._reserve("k", 1.0, "A09-WRI")
    assert held == [pytest.approx(1.30)]


def test_openai_writing_quote_and_hold_use_the_cache_write_rate():
    from litreview.writing_admission import quote_call, worst_case_usd
    b, gpt = StubBudget(), config.agent_model("A08-OL")
    assert worst_case_usd(b, gpt, 100_000, 0) == pytest.approx(0.25)          # $2.50/M write, not $2.00 input
    cfg = config.load("pipeline")["admission"]
    q = quote_call("s", "m", gpt, cfg, b)
    tokens = offline_tokens("s") + offline_tokens("m")
    assert q == pytest.approx(1.30 * (tokens * 2.50 + gpt.max_tokens * 10.0) / 1e6)


def test_native_downstream_admission_reserves_openai_input_at_the_cache_write_rate(monkeypatch):
    from litreview import admission
    r = Run.__new__(Run)
    r.budget, r.cfg = StubBudget(), copy.deepcopy(config.load("pipeline"))
    r.route = lambda agent, exclude=frozenset(): config.agent_model(agent)
    r.prov = SimpleNamespace(tool_run=lambda *a: None)
    monkeypatch.setattr(admission, "assess", lambda *a, **k: {"input_bound": 100_000, "output_reserve": 0, "fits": True,
                                                              "crosses_threshold": False, "window": 1, "agent": "A08-OL"})
    seen = {}
    r._require_projection = r._check_request_line = lambda *a: None
    r._downstream_gate = lambda agent, usd: seen.setdefault("usd", usd)
    r._reserve = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop before dispatch"))
    with pytest.raises(RuntimeError, match="stop before dispatch"):
        r._admitted("A08-OL", {}, "A08-OL_v1")
    assert seen["usd"] == pytest.approx(0.25)


def test_no_config_yaml_key_is_parsed_as_a_non_string():
    """YAML 1.1 turns bare on/off/yes/no keys into booleans; notify.py's .get("on") then finds nothing."""
    import yaml
    from litreview.paths import CONFIG_DIR

    def bad(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if not isinstance(k, str):
                    yield f"{path}.{k!r}"
                yield from bad(v, f"{path}.{k}")
        elif isinstance(node, list):
            for n, v in enumerate(node):
                yield from bad(v, f"{path}[{n}]")
    found = [x for f in sorted(CONFIG_DIR.glob("*.yaml"))
             for x in bad(yaml.safe_load(f.read_text(encoding="utf-8")), f.name)]
    assert found == []
    assert "checkpoint" in config.load("pipeline")["notify"]["on"]


def test_one_section_authority_and_outline_check():
    sample = {"max_sections": 1, "min_words": 800, "max_words": 1000}
    assert sm.check_outline({"sections": [{"word_budget": 900}]}, sample) == []
    assert sm.check_outline({"sections": [{"word_budget": 450}, {"word_budget": 450}]}, sample)
