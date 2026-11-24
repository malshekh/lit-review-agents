"""A07 and A10 request sizes at pilot scale, from the production builders. Offline; no API calls; no science.

    python -B tests/pilot_scale_measure.py

The calibrated A07/A10 forecasts (src/litreview/tools/forecast.py) were fitted on 642-1,996 findings; at a pilot's
100-160 findings they are extrapolations (A10's LOCAL packet size is held at its 1,996-finding measurement). This
measures the same production builders at pilot scale instead: the A07 job (RegistrySynthesisJob, FixtureModel's
mechanical outputs) and the A10 job (VerificationJob, ScriptedVerifier) over a 5,000-word structural fixture
manuscript (tests/a10_capacity_simulation.py), on registries built from reference-run papers chosen as stand-ins
for the pilot selection: the reference run's two largest full texts and largest abstracts (at or above the 90th
percentile of findings, so conservative). The reference run is read, never written: only the files the workload
reads are copied to a temporary directory, with the corpus reordered so the stand-ins come first.

Priced with the forecast's baseline assumptions (pipeline.yaml -> forecast.scenarios.baseline): input at the byte
bound / bytes_per_token, output at its share of each cap, retrieval share and A10 re-verification shares as
configured. Byte bounds are MEASURED here; everything about model behaviour is ASSUMED. Writes
docs/integration_validation/pilot_scale.json.
"""
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from litreview import config                                              # noqa: E402
from litreview.agents.base import build_system_prompt, user_parts         # noqa: E402
from litreview.budget import BudgetTracker                                # noqa: E402
from litreview.synthesis_bounded import RegistrySynthesisJob              # noqa: E402
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens  # noqa: E402
from litreview.verification_job import VerificationJob                   # noqa: E402
import a07_capacity_simulation as a07sim                                  # noqa: E402
from test_synthesis_bounded import FixtureModel                           # noqa: E402
from test_verification_job import ScriptedVerifier                        # noqa: E402

REFERENCE = ROOT.parent / "lit-review-agents" / "runs" / "20261025-100039" / "data"
STAND_INS = {"2 full texts + 3 abstracts": ["R0042", "R0045", "R0112", "R0155", "R0060"],
             "2 full texts + 2 abstracts": ["R0042", "R0045", "R0112", "R0155"],
             "2 full texts + 1 abstract": ["R0042", "R0045", "R0112"],
             "1 full text + 2 abstracts": ["R0042", "R0112", "R0155"],
             "1 full text + 1 abstract": ["R0042", "R0112"]}
FILES = ("selected_corpus.json", "validated_findings.json", "theme_records.json", "spec_approved.json")


def fixture(registry, package, sentences=200):
    """a10_capacity_simulation.fixture with the same shape (200 cited, tagged sentences of about 25 words, so about
    5,000 words; a 12-row table), cycling over the pilot's few records for the table rows as well."""
    props = package["propositions"]
    records = list(registry.records)

    def binding(record):
        prop = next((p for p in props if any(registry.record_of[e["finding_id"]] == record for e in p["evidence"])), None)
        if prop:
            return prop["proposition_id"]
        return next(g for g in package["knowledge_gaps"] if record in g.get("citation_record_ids", []))["gap_id"]
    lines = []
    for i in range(sentences):
        record = records[i % len(records)]
        lines.append(" ".join(["Evaluation"] * 20 + ["fixture", "occurrence", str(i), "only", f"[@{record}]"])
                     + " ⟦" + binding(record) + "⟧.")
    manuscript = {"title": "Structural evaluation fixture", "abstract": "Evaluation input only",
                  "sections": [{"section_id": "S1", "heading": "Evaluation introduction",
                                "text_markdown": " ".join(lines[:sentences // 2])},
                               {"section_id": "S2", "heading": "Evaluation conclusion",
                                "text_markdown": " ".join(lines[sentences // 2:])}]}
    table = {"kind": "TABLE", "display_id": "T1", "caption": "Structural comparative evidence table fixture",
             "columns": ["Source", "Model", "Exposure", "Finding"],
             "rows": [[f"[@{records[i % len(records)]}]", "Evaluation model", "Evaluation exposure",
                       "Evaluation input ⟦" + binding(records[i % len(records)]) + "⟧"] for i in range(12)]}
    return manuscript, [table]


def staged(tmp: Path, first: list[str]) -> Path:
    data = tmp / "runs" / "20261025-100039" / "data"
    (data / "extractions").mkdir(parents=True)
    for name in FILES:
        shutil.copyfile(REFERENCE / name, data / name)
    for rid in first:
        shutil.copyfile(REFERENCE / "extractions" / f"{rid}.json", data / "extractions" / f"{rid}.json")
    corpus = json.loads((data / "selected_corpus.json").read_text(encoding="utf-8"))
    corpus.sort(key=lambda r: (r["record_id"] not in first, first.index(r["record_id"]) if r["record_id"] in first else 0))
    (data / "selected_corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    return tmp


def measure(first: list[str], tmp: Path, words_options=(5000,)) -> dict:
    a07sim.ROOT = staged(tmp, first)
    registry = EvidenceRegistry(a07sim.workload(len(first)))
    syn = config.load("pipeline")["synthesis"]
    sys7 = build_system_prompt("A07-SYN")
    count7 = lambda p: offline_tokens(sys7) + offline_tokens(user_parts(p))
    model7 = FixtureModel(registry)
    job = RegistrySynthesisJob(tmp / "a07", registry, model7, count7, syn, {"prompt": sys7}, lambda *_: True)
    pkg = job.run()
    a07 = defaultdict(lambda: {"calls": 0, "input_bytes": 0, "output_cap": 0})
    for mode, payload, _ in model7.calls:
        a07[mode]["calls"] += 1
        a07[mode]["input_bytes"] += count7(payload)
        a07[mode]["output_cap"] += job.limit(mode)
    vc = config.load("pipeline")["scientific_verification"]
    sys10 = build_system_prompt("A10-RV")
    count10 = lambda p: offline_tokens(sys10) + offline_tokens(user_parts(p))
    by_words = {}
    for words in words_options:         # the fixture's sentences are 25 words each
        a10 = defaultdict(lambda: {"calls": 0, "input_bytes": 0, "output_cap": 0})
        verifier = ScriptedVerifier()

        def call(mode, payload, name):
            a10[mode]["calls"] += 1
            a10[mode]["input_bytes"] += count10(payload)
            a10[mode]["output_cap"] += vc["output_limits"][mode]
            return verifier(mode, payload, name)
        manuscript, tables = fixture(registry, pkg, max(2, words // 25))
        report = VerificationJob(tmp / f"a10_{words}", manuscript, {}, pkg, registry, tables, vc, call, count10,
                                 {"prompt": sys10}).run("DRAFT")
        by_words[words] = {"a10": dict(a10), "a10_occurrences": report["coverage"]["occurrences_total"]}
    return {"stand_in_records": first, "findings": len(registry.findings), "propositions": len(pkg["propositions"]),
            "a07_status": pkg["status"], "a07": dict(a07), **by_words[words_options[0]], "by_words": by_words}


def price(m: dict, cfg: dict) -> dict:
    """Baseline scenario, as forecast.py prices A07 and A10, from these measured requests."""
    s = cfg["forecast"]["scenarios"]["baseline"]
    bpt, out_share = float(s["bytes_per_token"]), float(s["output"])
    b = BudgetTracker(Path(tempfile.mkdtemp()))
    route = lambda a: config.agent_candidates(a)[0]
    m7, m10 = route("A07-SYN").model, route("A10-RV").model
    r7 = b._rates(m7, 0)
    usd7, calls7 = 0.0, 0.0
    for mode, x in m["a07"].items():
        w = 1.0 + (float(s["a07_retrieval"]) if mode in ("GROUP", "RECONCILE") else 0.0)
        extra = float(s["a07_retrieval"]) * x["calls"] * 12 * 1300 if mode in ("GROUP", "RECONCILE") else 0.0
        usd7 += ((x["input_bytes"] / bpt) * w + extra) * r7["input"] / 1e6 + x["output_cap"] * w * out_share * r7["output"] / 1e6
        calls7 += x["calls"] * w
    r = float(s["a10_retrieval"])
    mult = 1 + r * (1 + 0.15)
    usd10, calls10 = 0.0, 0.0
    for share in s["a10_local_rerun"]:
        for mode, factor in (("LOCAL", share), ("GLOBAL", 1.0)):
            x = m["a10"].get(mode)
            if not x:
                continue
            per = x["input_bytes"] / x["calls"] / bpt
            rates = b._rates(m10, int(per))
            usd10 += x["calls"] * factor * mult * (per * rates["input"] + x["output_cap"] / x["calls"] * out_share * rates["output"]) / 1e6
            calls10 += x["calls"] * factor * (1 + r)
    return {"A07-SYN": {"model": m7, "expected_calls": round(calls7, 1), "baseline_usd": round(usd7, 4)},
            "A10-RV": {"model": m10, "expected_calls": round(calls10, 1), "baseline_usd": round(usd10, 4)}}


def main():
    cfg = config.load("pipeline")
    out = {"method": __doc__.split("\n\n")[0], "basis": "byte bounds MEASURED with production builders on stand-in "
           "registries; model behaviour ASSUMED (forecast baseline)", "selections": {}}
    for name, first in STAND_INS.items():
        with tempfile.TemporaryDirectory(prefix="pilot-scale-") as tmp:
            m = measure(first, Path(tmp))
        m["priced_baseline"] = price(m, cfg)
        out["selections"][name] = m
        print(f"{name:28s} findings {m['findings']:4d}  A07 {m['priced_baseline']['A07-SYN']}  A10 {m['priced_baseline']['A10-RV']}"
              f"  A10 calls {json.dumps({k: v['calls'] for k, v in m['a10'].items()})}")
    path = ROOT / "docs" / "integration_validation" / "pilot_scale.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
