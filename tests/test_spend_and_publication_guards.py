"""No spend after CP2 without a projection within the cap; evaluation-only synthesis never enters a
publication workflow."""
import json

import pytest

from litreview import checkpoints, model_record, publication
from litreview import orchestrator as orch
from litreview.tools import cost_projection as cp

RATES = {"reference_run": "ref", "per_paper": {
    "ABSTRACT": {"papers": 10, "p90_usd": 0.6, "findings_p90": 18},
    "FULL_TEXT": {"papers": 10, "p90_usd": 2.0, "findings_p90": 41}},
    "per_theme": {"themes": 10, "p90_usd": 0.1}, "themes_per_paper": 2.3}


def _run(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "mr.jsonl")
    run = orch.Run("t")
    run.save_state({"stage": stage, "status": "READY", "counters": {}})
    return run


@pytest.mark.projection_guard
def test_no_agent_call_after_cp2_without_a_projection_within_the_cap(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "extract")
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: {"ok": True})
    with pytest.raises(orch.Pause, match="no cost projection"):
        run.agent("A05-KE", {}, "A05-KE_R0001")
    run.save("cost_projection.json", {"verdict": "OVER_CAP", "projected_total_usd": 50, "cap_usd": 35})
    with pytest.raises(orch.Pause, match="exceeds the"):
        run.agent("A05-KE", {}, "A05-KE_R0001")
    run.save("cost_projection.json", {"verdict": "WITHIN_CAP"})
    assert run.agent("A05-KE", {}, "A05-KE_R0001") == {"ok": True}
    before = _run(tmp_path / "b", monkeypatch, "qualify")            # before CP2 nothing is projected yet
    assert before.agent("A04-CQ", {}, "A04-CQ_B001") == {"ok": True}


def _cp2(tmp_path, monkeypatch, n, pmcid):
    run = _run(tmp_path, monkeypatch, "cp2")
    recs = [{"record_id": f"R{i:04d}", **({"pmcid": "PMC1"} if pmcid else {})} for i in range(n)]
    run.save("records.json", recs)
    run.save("qualifications.json", [{"record_id": r["record_id"], "disposition": "QUALIFIED"} for r in recs])
    monkeypatch.setattr(checkpoints, "approved", lambda d, c: {"selected_record_ids": [r["record_id"] for r in recs],
                                                               "tier_overrides": {}})
    monkeypatch.setattr(run, "_framework_update", lambda d, c: None)
    monkeypatch.setattr(cp, "load_rates", lambda: RATES)
    return run


def test_cp2_refuses_a_selection_projected_over_the_cap(tmp_path, monkeypatch):
    run = _cp2(tmp_path, monkeypatch, 12, pmcid=True)
    with pytest.raises(orch.Pause, match="over the"):
        run.stage_cp2(run.state())
    assert run.load("selected_corpus.json") is None                  # nothing proceeds
    proj = run.load("cost_projection.json")
    assert proj["verdict"] == "OVER_CAP" and proj["by_level"] == {"ABSTRACT": 0, "FULL_TEXT": 12}
    # A08, A09, A11 and A12 come from the bridge's request builders: an estimate before any package exists
    assert {x["basis"] for x in proj["lines"]} == {"MEASURED_P90", "ESTIMATED_ENVELOPE"}


def test_cp2_passes_a_selection_within_the_cap_and_records_the_projection(tmp_path, monkeypatch):
    run = _cp2(tmp_path, monkeypatch, 2, pmcid=False)
    # exercise admission independently of the $35 pilot cap. $200: the section-by-section A09 line alone is about
    # $40 for two papers at worst case (8 sections x 3 retrieval rounds x 2 drafts), set by the review's length
    run.budget.cap = 200.0
    assert run.stage_cp2(run.state()) == "extract"
    proj = run.load("cost_projection.json")
    assert proj["verdict"] == "WITHIN_CAP" and proj["projected_total_usd"] <= proj["cap_usd"]
    assert proj["lines"][0]["usd"] == pytest.approx(1.2)               # 2 abstracts x $0.60 measured


def test_measured_rates_come_from_the_cost_log(tmp_path):
    (tmp_path / "data" / "extractions").mkdir(parents=True)
    for rid, level, n in (("R0001", "ABSTRACT", 5), ("R0002", "FULL_TEXT", 30)):
        (tmp_path / "data" / "extractions" / f"{rid}.json").write_text(json.dumps(
            {"content_level": level, "findings": [{}] * n}))
    log = [("A05-KE_R0001", 0.2), ("A06-SV_R0001_v1", 0.1), ("A05-KE_R0002", 1.0), ("A05-KE_R0002_reextract", 0.5),
           ("A06-SV_R0002_v1", 0.3), ("A06-SV_R0002_reval1", 9.0), ("A06-SV_theme_X", 0.05)]
    (tmp_path / "costs.jsonl").write_text("\n".join(json.dumps({"step": s, "cost_usd": c}) for s, c in log))
    r = cp.measured_rates(tmp_path)
    assert r["per_paper"]["ABSTRACT"]["mean_usd"] == pytest.approx(0.3)
    assert r["per_paper"]["FULL_TEXT"]["mean_usd"] == pytest.approx(1.8)       # revalidation left out
    assert r["per_theme"]["mean_usd"] == pytest.approx(0.05) and r["themes_per_paper"] == 0.5


# ------------------------------------------------------------------ evaluation-only
PKG = {"propositions": [], "researcher_decision": {}, "proposed_interpretations": []}


def test_an_evaluation_only_synthesis_is_stamped_and_refused_by_every_publication_stage(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "cp3")
    run.save("synthesis_package.json", PKG)
    run.mark_evaluation_only("structural test of the A07 architecture; output not scientifically usable")
    stamped = run.load("synthesis_package.json")
    assert stamped[publication.MARK]["run_id"] == "t"                  # in the data itself
    monkeypatch.setattr(checkpoints, "approved", lambda d, c: {"adopted_interpretations": []})
    with pytest.raises(publication.EvaluationOnly):
        run.stage_cp3(run.state())
    status = run.run()                                                  # the run loop reports it plainly
    assert status.startswith("REFUSED_EVALUATION_ONLY")


def test_a_copied_evaluation_only_package_is_refused_in_another_run(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, "outline")
    run.save("synthesis_approved.json", publication.stamp(PKG, "architecture test", "20261025-100039"))
    monkeypatch.setattr(run, "agent", lambda *a, **k: pytest.fail("A08 must not be called"))
    with pytest.raises(publication.EvaluationOnly, match="20261025-100039"):
        run.stage_outline(run.state())
    for stage in ("_verify", "stage_review_loop"):
        with pytest.raises(publication.EvaluationOnly):
            run.save("manuscript_plan.json", {})
            getattr(run, stage)(*(({"sections": []}, "DRAFT", "s") if stage == "_verify" else (run.state(),)))
