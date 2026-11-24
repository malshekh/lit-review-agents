"""The calibration report reads a run and reports; it writes nothing in the run."""
import hashlib
import json

from litreview.tools import calibration_report


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _digest(root):
    return hashlib.sha256(b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())).hexdigest()


def test_report_counts_repeats_themes_a09_and_a10_without_writing(tmp_path):
    run = tmp_path / "r1"
    e = lambda agent, step, usd, out=100, **k: {"agent": agent, "step": step, "model": "m", "cost_usd": usd,
                                                "input_tokens": 1000, "output_tokens": out, **k}
    costs = [e("A06-SV", "A06-SV_R0001_repeat", 0.2), e("A06-SV", "A06-SV_R0002_repeat", 0.3),
             e("A06-SV", "A06-SV_theme_T1", 0.1), e("A07-SYN", "A07-SYN_job_PLAN", 1.0, out=900),
             e("A09-WRI", "A09-WRI_draft1_S2_r0", 0.5), e("A09-WRI", "A09-WRI_draft1_S2_r1", 0.6),
             e("A09-WRI", "A09-WRI_draft1_S3_r0", 0.4), e("A09-WRI", "A09-WRI_draft2_S3_r0", 0.4),
             e("A10-RV", "A10-RV_draft1_a10-x_LOCAL_abc_R0", 0.2), e("A10-RV", "A10-RV_draft1_a10-y_GLOBAL_0000_R0", 0.7)]
    (run).mkdir(parents=True)
    (run / "costs.jsonl").write_text("\n".join(json.dumps(x) for x in costs), encoding="utf-8")
    (run / "provenance.jsonl").write_text(json.dumps({"type": "tool_run", "tool": "context_utilisation_actual",
                                                      "summary": {"model": "gpt-6.1-sol", "byte_bound_over_actual": 2.6}}),
                                          encoding="utf-8")
    _write(run / "data" / "instability_test.json", {"papers": {"R0001": {}, "R0002": {}}, "agreement": {"disposition_agree": 9},
                                                    "by_cause": {"EXTRACTION_ERROR": 1}})
    _write(run / "data" / "validation_review.json", [{"kind": "REPEAT", "action": "QUARANTINED"}])
    _write(run / "data" / "theme_records.json", {"T1": {"conflicts": [{"x": 1}], "independence": []}})
    _write(run / "data" / "synthesis_package.json", {"propositions": [{}, {}, {}]})
    _write(run / "data" / "verification_jobs" / "j1" / "GLOBAL_0000_R0.json",
           {"output": {"issues": [{"code": "CONTRARY_EVIDENCE_UNADDRESSED"}]}})
    _write(run / "data" / "verification_jobs" / "j1" / "report.json",
           {"pass": "DRAFT", "findings": [{"code": "UNMATCHED", "severity": "BLOCKING", "responsible_stage": "A09-WRI"}]})
    before = _digest(run)
    r = calibration_report.report(run)
    assert _digest(run) == before                                      # read only
    assert r["a06_instability_repeat"]["calls"] == 2 and r["a06_instability_repeat"]["usd"] == 0.5
    assert r["a06_instability_repeat"]["caught"]["quarantined"] == 1
    assert r["a06_theme_pass"]["calls"] == 1 and r["a06_theme_pass"]["caught"]["T1"]["conflicts"] == 1
    a09 = r["a09_retrieval_and_redrafts"]
    assert a09["sections"] == 2 and a09["retrieval_frequency"] == 0.5 and a09["redraft_frequency"] == 0.5
    assert a09["caught"]["blocking_a10_findings_on_drafts"] == [{"code": "UNMATCHED", "severity": "BLOCKING"}]
    a10 = r["a10_local_and_global"]
    assert a10["local"]["calls"] == 1 and a10["global"]["usd"] == 0.7
    assert a10["caught"]["GLOBAL"] == {"CONTRARY_EVIDENCE_UNADDRESSED": 1}
    assert r["a07_output_tokens_per_proposition"] == 300.0
    assert r["bytes_per_token_by_model"]["gpt-6.1-sol"]["median"] == 2.6
    assert "REPORT ONLY" in r["label"]
