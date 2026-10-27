import pytest

from litreview import model_record
from litreview import orchestrator as orch
from litreview import theme_framework as tf
from litreview.checkpoints import write_cp2, write_cp3

FW = tf.create([{"theme_id": "T1", "name": "Exposure", "scope": "s", "includes": "i", "excludes": "e"},
                {"theme_id": "T2", "name": "Efficacy", "scope": "s", "includes": "i", "excludes": "e"}], "two because", "CP1")


def test_no_agent_can_create_a_primary_theme():
    ok = tf.normalize({"primary_theme_id": "T2", "subthemes": ["NPL4 pathway"]}, FW)
    assert ok["themes"] == ["T2"] and ok["subthemes"] == ["NPL4 pathway"] and not ok.get("emerging")
    bad = tf.normalize({"primary_theme_id": "T9", "subthemes": ["cuproptosis"]}, FW)
    assert bad["themes"] == [] and bad["primary_theme_id"] is None and bad["emerging"]
    assert "unknown primary theme 'T9'" in bad["emerging_note"] and bad["subthemes"] == ["cuproptosis"]


def test_framework_changes_are_new_versions_with_history():
    v2 = tf.revise(FW, FW["primary_themes"] + [{"theme_id": "T3", "name": "Tolerability"}], "CP2", "trial toxicity")
    assert v2["version"] == 2 and v2["history"][-1]["added"] == ["T3"] and v2["history"][-1]["checkpoint"] == "CP2"
    assert v2["history"][-1]["previous_primary_themes"] == FW["primary_themes"] and FW["version"] == 1


def test_emerging_queue_and_checkpoint_sections(tmp_path):
    quals = [tf.normalize({"record_id": "R1", "disposition": "QUALIFIED", "primary_theme_id": "T1"}, FW),
             tf.normalize({"record_id": "R2", "disposition": "QUALIFIED", "primary_theme_id": "T1",
                           "emerging": True, "emerging_note": "imaging study"}, FW)]
    q = tf.emerging(quals, "record_id")
    assert [e["id"] for e in q] == ["R2"]
    write_cp2(tmp_path, [{"record_id": "R1"}, {"record_id": "R2"}], quals, {}, emerging=q, framework=FW)
    text = (tmp_path / "checkpoints" / "CP2_review.md").read_text(encoding="utf-8")
    assert "Emerging evidence: 1 records fit no primary theme" in text and "imaging study" in text
    assert "Current theme framework — version 1" in text
    assert '"theme_framework_update": null' in (tmp_path / "checkpoints" / "CP2_decision.json").read_text()
    write_cp3(tmp_path, {"coverage_incomplete_item_ids": ["MISSING:HUMAN"], "findings_unaccounted": []}, [], FW)
    cp3 = (tmp_path / "checkpoints" / "CP3_review.md").read_text(encoding="utf-8")
    assert "Synthesis coverage is INCOMPLETE" in cp3 and "MISSING:HUMAN" in cp3 and "structural only" in cp3
    write_cp3(tmp_path, {"coverage_incomplete_item_ids": [], "findings_unaccounted": []}, [], FW)
    complete = (tmp_path / "checkpoints" / "CP3_review.md").read_text(encoding="utf-8")
    assert "INCOMPLETE" not in complete and "Coverage is structural only" in complete


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(model_record, "RECORD", tmp_path / "model_record.jsonl")
    r = orch.Run("t")
    r.save_state({"stage": "cp1", "status": "READY", "counters": {}})
    return r


def test_cp1_approval_creates_version_1_and_logs_it(run):
    run.save("spec.json", {"theme_framework": {"primary_themes": FW["primary_themes"], "count_justification": "x"}})
    (run.dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    (run.dir / "checkpoints" / "CP1_approved.json").write_text('{"selected_option_id": "P1"}', encoding="utf-8")
    assert run.stage_cp1(run.state()) == "search"
    fw = run.load("theme_framework.json")
    assert fw["version"] == 1 and tf.ids(fw) == {"T1", "T2"}
    ev = [e for e in run.prov.events() if e["type"] == "human_decision"][-1]
    assert ev["checkpoint"] == "THEME_FRAMEWORK" and ev["decision"]["version"] == 1


def test_cp2_framework_update_is_a_logged_new_version(run):
    run.save("theme_framework.json", FW)
    run._framework_update({"theme_framework_update": {"primary_themes": FW["primary_themes"][:1], "note": "merge"}}, "CP2")
    fw = run.load("theme_framework.json")
    assert fw["version"] == 2 and fw["history"][-1]["removed"] == ["T2"]
    assert run.prov.events()[-1]["decision"]["version"] == 2


def test_finding_outside_the_framework_attaches_to_its_records_primary_theme(run):
    run.save("theme_framework.json", FW)
    out = run._finding_themes({"primary_theme_id": "T7", "subthemes": ["imaging"]}, {"themes": ["T2"]})
    assert out["themes"] == ["T2"] and out["primary_theme_id"] == "T2" and out["emerging"]
    assert out["subthemes"] == ["imaging"]
