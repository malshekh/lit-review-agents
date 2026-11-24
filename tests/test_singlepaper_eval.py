import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from litreview import singlepaper_eval as se, pilot_authorization as pilot
from litreview.orchestrator import Run, Pause
from litreview.budget import BudgetExceeded

pytestmark = pytest.mark.projection_guard


def test_original_pilot_still_requires_three_papers(tmp_path):
    r = SimpleNamespace(dir=tmp_path, id="legacy", load=lambda *a: None)
    assert se.policy(r) is None
    assert len(pilot.selection(r)) == 3


def make_policy(tmp_path):
    (tmp_path / "input").mkdir()
    source = tmp_path / "accepted.json"
    source.write_text("accepted original input")
    p = {"version":se.VERSION, "run_id":"single", "record_ids":["R0001"],
         "pmids":["34638842"], "sub_cap_usd":15, "parent_cap_usd":35,
         "review_usd":25, "margin":.30, "researcher_authorized":True,
         "parent_run_id":"20261031-213324", "authority_sha256":"a" * 64,
         "baseline_cumulative_usd":7.3163356,
         "parent_files":{"accepted.json":hashlib.sha256(source.read_bytes()).hexdigest()}}
    (tmp_path / "input/r0001_writing_evaluation.json").write_text(json.dumps(p))
    return p


def test_scoped_selection_never_allows_second_paper(tmp_path):
    make_policy(tmp_path)
    r = SimpleNamespace(dir=tmp_path, id="single", load=lambda *a:None)
    assert len(pilot.selection(r)) == 1
    assert pilot.selection(r)[0]["pmid"] == "34638842"
    with pytest.raises(pilot.AuthorizationRequired):
        pilot.selection(r, [{"record_id":"R0002", "pmid":"30771200"}])


def test_evidence_change_invalidates_scope(tmp_path):
    make_policy(tmp_path)
    r = SimpleNamespace(dir=tmp_path, id="single")
    assert se.policy(r)
    (tmp_path / "accepted.json").write_text("changed")
    with pytest.raises(pilot.AuthorizationRequired): se.policy(r)


def test_001_cap_refuses_before_native_reservation_or_dispatch(monkeypatch):
    r = se.WritingRun.__new__(se.WritingRun)
    r.baseline = Decimal("7.3163356")
    r.dry_cap = .01
    r.budget = SimpleNamespace(spent=lambda:7.3163356, reserved=lambda:0)
    saved=[];calls=[]
    r.save=lambda *a:saved.append(a)
    monkeypatch.setattr(Run,"_reserve",lambda *a,**k:calls.append(a))
    with pytest.raises(BudgetExceeded): r._reserve("first-plan",.10,"A07-SYN")
    assert not calls
    assert saved[0][1]["provider_dispatched"] is False
    r.dry_cap=None
    r._reserve("first-plan",.10,"A07-SYN")
    assert len(calls)==1


def test_subcap_counts_paid_failures_and_holds(monkeypatch):
    r=se.WritingRun.__new__(se.WritingRun)
    r.baseline=Decimal("7.3163356");r.dry_cap=None
    r.budget=SimpleNamespace(spent=lambda:21.3163356, reserved=lambda:.5)
    r.save=lambda *a:None
    monkeypatch.setattr(Run,"_reserve",lambda *a,**k:pytest.fail("Unaffordable dispatch"))
    with pytest.raises(BudgetExceeded):r._reserve("next",.5,"A07-SYN")


def test_upstream_repeats_and_other_records_blocked(monkeypatch):
    r=se.WritingRun.__new__(se.WritingRun)
    r.state=lambda:{"stage":"synthesize"}
    monkeypatch.setattr(Run,"agent",lambda *a,**k:pytest.fail("Unauthorized native call"))
    with pytest.raises(Pause):r.agent("A06-SV",{},"repeat")
    with pytest.raises(Pause):r.agent("A07-SYN",{"record_id":"R0002"},"other")


def test_draft_uses_no_integration_or_redraft():
    r=se.WritingRun.__new__(se.WritingRun);state={"stage":"draft"};calls=[]
    r._reproject=lambda *a:None;r._plan_state=lambda:{}
    r._write_sections=lambda *a:calls.append("A09") or []
    r._assemble=lambda *a:{"sections":[]};r._save_manuscript=lambda *a:None
    r.state=lambda:state;r.save_state=lambda x:state.update(x)
    r._integrate=lambda *a:pytest.fail("Extra A12 integration")
    assert r._draft_once(state)=="draft"
    assert state["evaluation_phase"]=="verify_once" and calls==["A09"]


def test_edit_stops_without_post_edit_verification():
    r=se.WritingRun.__new__(se.WritingRun);calls=[]
    r._plan_state=lambda:{};r._current=lambda:{}
    r.load=lambda name:{"bridge_fingerprint":"same", "findings":[{"severity":"MAJOR"}]}
    r._require_current=lambda *a:None;r._bridge_fingerprint=lambda *a:"same"
    r._edit=lambda *a,**k:calls.append("A12") or {};r._binding_gate=lambda *a:None
    r._save_manuscript=lambda *a:None;r.save=lambda *a:calls.append(a)
    r._verify=lambda *a:pytest.fail("Second verification cycle")
    assert r._edit_once({})=="evaluation_done"
    assert calls[0]=="A12" and calls[1][1]["post_edit_verified"] is False


def test_configuration_keys_are_consumed():
    from litreview import config
    cfg=config.load("pipeline")
    assert cfg["loops"]["max_redrafts"]==0
    assert cfg["loops"]["max_critique_cycles"]==1


def test_native_atomic_ceiling_preserves_parent_cap(tmp_path):
    from litreview.budget import BudgetTracker
    b=BudgetTracker.__new__(BudgetTracker)
    b.cap=35;b.log_path=tmp_path/"costs.jsonl";b.reservations_path=tmp_path/"reservations.json"
    b.log_path.write_text(json.dumps({"cost_usd":7.3163356})+"\n")
    b.operational_ceiling=7.3263356
    ok,_=b.reserve("first-a07",1.32402,"A07-SYN")
    assert not ok and b.cap==35 and not b.reservations()
    b.operational_ceiling=22.3163356
    ok,_=b.reserve("first-a07",1.32402,"A07-SYN")
    assert ok and b.cap==35


def test_record_ids_in_lists_and_mapping_keys_blocked():
    for payload in [{"finding_ids":["R0002:F1"]},{"R0003:F2":{}}]:
        with pytest.raises(Pause):se.WritingRun._only_r0001(payload)


def test_unrestricted_run_cannot_dispatch_evaluation(tmp_path):
    make_policy(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"execution_mode":"STAGED_PILOT", "stage":"synthesize"}))
    r=Run.__new__(Run);r.dir=tmp_path;r.id="single"
    with pytest.raises(pilot.AuthorizationRequired,match="guarded continue_stage1"):
        pilot.require(r,"A07-SYN")


def test_cache_floor_is_included_before_subcap_admission(monkeypatch):
    r=se.WritingRun.__new__(se.WritingRun);r.baseline=Decimal("7.3163356");r.dry_cap=None
    r.budget=SimpleNamespace(spent=lambda:21.3163356,reserved=lambda:0)
    r._cache_reservation_floor=("A12-EDI",1)
    r.save=lambda *a:None
    monkeypatch.setattr(Run,"_reserve",lambda *a,**k:pytest.fail("Unadmitted cache charge"))
    with pytest.raises(BudgetExceeded):r._reserve("edit",.1,"A12-EDI")
