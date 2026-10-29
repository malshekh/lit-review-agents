"""Offline workload replication with ACTUAL payload builders. No APIs and no scientific synthesis.

Run from repository root: python -B tests/a07_capacity_simulation.py --output docs/a07_capacity_redesign.json
Replicated old papers get synthetic primary theme assignments solely for capacity measurement.
"""
import argparse
import copy
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from litreview import config
from litreview.agents.base import build_system_prompt, user_parts
from litreview.synthesis_input import build_corpus, build_manifest
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens
from litreview.synthesis_bounded import RegistrySynthesisJob
from litreview.tools.cost_projection import downstream
from litreview.budget import BudgetTracker
from test_synthesis_bounded import FixtureModel


def workload(n):
    data = ROOT / "runs/20261025-100039/data"
    records = json.loads((data / "selected_corpus.json").read_text(encoding="utf-8"))
    fs = json.loads((data / "validated_findings.json").read_text(encoding="utf-8"))
    by_record = defaultdict(list)
    for f in fs:by_record[f["record_id"]].append(f)
    selected, findings, entities = [], [], {}
    def remap(value, mapping):
        if isinstance(value, str):return re.sub(r"\bR\d{4}\b", lambda m: mapping.get(m[0], m[0]), value)
        if isinstance(value, list):return [remap(x, mapping) for x in value]
        if isinstance(value, dict):return {remap(k, mapping): remap(v, mapping) for k, v in value.items()}
        return value
    for i in range(n):
        original = records[i % len(records)]
        offset = i // len(records) * len(records)
        mapping = {r["record_id"]: f"R{offset+j+1:04d}" for j, r in enumerate(records)}
        rec = remap(original, mapping)
        rec["themes"] = [f"T{i%8+1}"]
        selected.append(rec)
        ext = json.loads((data / "extractions" / f"{original['record_id']}.json").read_text(encoding="utf-8"))
        for ent in ext.get("entities", []):
            entities[f"{rec['record_id']}:{ent['entity_id']}"] = {k: ent.get(k) for k in
                ("mention", "type", "subtype", "molecule_species", "measured_at", "identity_relation", "construct")}
        for old in by_record[original["record_id"]]:
            f = remap(old, mapping)
            f["subthemes"] = f.get("themes", [])
            f["themes"] = rec["themes"]
            f["primary_theme_id"] = rec["themes"][0]
            findings.append(f)
    # Keep each legacy thematic evidence record distinct, including its source-linked conflicts.
    original_themes = json.loads((data / "theme_records.json").read_text(encoding="utf-8"))
    themes = {}
    for cycle in range((n + len(records)-1)//len(records)):
        mapping = {r["record_id"]: f"R{cycle*len(records)+j+1:04d}" for j, r in enumerate(records)}
        for name, source in original_themes.items():
            themes[f"replica{cycle}:{name}"] = remap(source, mapping)
    fw = {"version": 1, "primary_themes": [{"theme_id": f"T{i}", "name": f"Synthetic capacity theme {i}"} for i in range(1,9)]}
    spec = json.loads((data / "spec_approved.json").read_text(encoding="utf-8"))
    result = build_corpus(spec, selected, findings, themes, build_manifest(selected, themes, []), fw)
    # A07 registry preserves spans; historical build_corpus intentionally excludes them for comparison.
    result["validated_findings"] = [{k:v for k,v in f.items() if k != "context"} for f in findings]
    result["selected_corpus"] = selected
    result["source_entities"] = entities
    return result


def simulate(n, directory):
    r = EvidenceRegistry(workload(n))
    fixture = FixtureModel(r)
    raw_sizes = {}
    def model(mode, payload, turn):
        result = fixture(mode, payload, turn)
        raw_sizes[turn] = offline_tokens(result)
        return result
    settings = config.load("pipeline")["synthesis"]
    system = build_system_prompt("A07-SYN")
    count = lambda payload: offline_tokens(system) + offline_tokens(user_parts(payload))
    j = RegistrySynthesisJob(directory, r, model, count, settings, {"prompt": system}, lambda *_: True)
    pkg = j.run()
    prices = config.load("prices")[config.agent_model("A07-SYN").model]
    totals = defaultdict(lambda: {"calls":0, "input_upper_tokens":0, "output_upper_tokens":0, "output_cap_tokens":0,
                                  "max_input_plus_output_cap":0})
    for mode, payload, name in fixture.calls:
        inp = count(payload)
        # Recreate fixture output without dispatching anything; output size is recorded separately
        # from the configured cap, which includes reasoning absent from this mechanical fixture.
        # All model responses are in accepted turn files; lookup suffix is absent for this fixture.
        turn = j._committed(name)
        if turn is None:
            # Completed GROUP/RECONCILE responses use the logical turn name, not LOOKUP0.
            turn = j._committed(name.rsplit("_LOOKUP",1)[0])
        ot = raw_sizes[name]
        row = totals[mode]
        row["calls"] += 1;row["input_upper_tokens"] += inp
        row["output_upper_tokens"] += ot;row["output_cap_tokens"] += j.limit(mode)
        row["max_input_plus_output_cap"] = max(row["max_input_plus_output_cap"], inp+j.limit(mode))
    # Input bound uses bytes. Cost baseline uses fixture output bytes with NO reasoning; stress
    # uses every output cap and all input billed as 1h writes. Neither claims measured live usage.
    inp = sum(v["input_upper_tokens"] for v in totals.values())
    out = sum(v["output_upper_tokens"] for v in totals.values())
    cap = sum(v["output_cap_tokens"] for v in totals.values())
    old = build_corpus(r.corpus["review_spec"], list(r.records.values()),
                      [{**f, "context":r.contexts.get(f.get("context_id"))} for f in r.findings.values()],
                      r.corpus["theme_records"], r.corpus["coverage_manifest"], r.framework)
    legacy_plan_upper = count({"corpus":old,"turn":{"mode":"PLAN","mandatory_item_ids":list(r.items)}})
    legacy_final_upper = count({"corpus":old,"turn":{"mode":"FINAL","propositions":pkg["propositions"]}})
    baseline = (inp * prices["input"] + out * prices["output"])/1e6
    stress = (inp * prices["cache_write_1h"] + cap * prices["output"])/1e6
    b = BudgetTracker(directory / "cost_projection")
    downstream_lines = downstream(b, lambda a: config.agent_model(a), config.load("pipeline"), len(r.findings))[1:]
    rates = json.loads((ROOT / "records/cost_rates.json").read_text())
    oldmix = 11/28
    perpaper = n*((1-oldmix)*rates["per_paper"]["ABSTRACT"]["mean_usd"] + oldmix*rates["per_paper"]["FULL_TEXT"]["mean_usd"])
    repeat = n*((1-oldmix)*rates["per_paper"]["ABSTRACT"]["a06_p90_usd"] + oldmix*rates["per_paper"]["FULL_TEXT"]["a06_p90_usd"])
    theme = n*rates["themes_per_paper"]*rates["per_theme"]["mean_usd"]
    return {"papers":n,"findings":len(r.findings),"mandatory_items":len(r.items),"propositions":len(pkg["propositions"]),
            "legacy_same_workload_plan_input_upper":legacy_plan_upper,
            "legacy_same_workload_final_input_upper":legacy_final_upper,
            "status":pkg["status"],"unaccounted":len(pkg["findings_unaccounted"]),
            "pending":len(pkg["coverage_incomplete_item_ids"]),"by_mode":dict(totals),
            "all_requests_admitted":all(v["max_input_plus_output_cap"]<=settings["context_ceiling_tokens"] for v in totals.values()),
            "a07_fixture_output_upper_cost_usd":round(baseline,2),"a07_all_output_caps_cache_miss_usd":round(stress,2),
        "pipeline_scenario_usd":round(stress + perpaper/2 + repeat/2 + theme + sum(x["usd"] for x in downstream_lines) + 4,2),
        "planning_scenario_a07_usd":round((inp/3*prices["input"] + (out/3+cap*.25)*prices["output"])/1e6,2),
        "planning_scenario_assumptions":"3 UTF-8 bytes/token; raw fixture outputs plus reasoning equal to 25% of total output caps; no retrieval; unmeasured, not a budget guarantee",
            "pipeline_assumptions":{"pre_cp2_usd":4,"paper_costs":"historical mean /2 batch approximation",
                "repeat_costs":"historical p90 /2, every paper repeated", "theme_costs":"historical means scaled by paper count",
                "A08_A12":"existing projection, untouched and not proven to fit context"}}


def main():
    parser = argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="a07-capacity-") as tmp:
        rows = [simulate(n, Path(tmp)/str(n)) for n in [40,80,120]]
    result={"method":"OFFLINE: existing evaluation records replicated with synthetic approved theme IDs; actual production payload builders and schemas; one-token-per-UTF8-byte upper estimates; no APIs, no model reasoning, no claim of scientific accuracy",
            "rows":rows,"original_capacity_record":"records/a07_capacity_20261029.json"}
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":main()
