"""Offline measurement of every downstream request the bridge builds, on the evaluation-only fixtures.

    python -B tests/bridge_capacity_audit.py            # offline: byte bounds, admissions, projections
    python -B tests/bridge_capacity_audit.py --count    # also Anthropic's free input-token counter (A09, A12)

No generation endpoint is ever called. The four stages (outline, draft, review loop, finish edit) run on the compact
120-paper fixture with scripted agents (tests/test_bridge.py `Agents`), in a temporary run directory; spend guards
are off because the fixture has no projection (A07 and A10 lines are not this task's). The oversized fixture is
measured by admission alone. --count sends the largest A09 section request, the A09 front-matter request and the
A12 integration request to messages.count_tokens (free; documented at
https://platform.claude.com/docs/en/build-with-claude/token-counting). GPT-6.1 and Kimi requests are not counted.
Writes docs/bridge_validation/measurements.json.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from litreview import admission, bridge, config                                     # noqa: E402
from litreview import orchestrator as orch                                           # noqa: E402
from litreview.agents.base import build_system_prompt, user_parts                    # noqa: E402
from litreview.budget import BudgetTracker                                           # noqa: E402
from litreview.synthesis_registry import fingerprint                                 # noqa: E402
from litreview.tools import downstream_projection as dp                              # noqa: E402
from bridge_fixtures import compact_package, describe, fixture_plan, oversized_package  # noqa: E402
from test_bridge import Agents                                                       # noqa: E402

OUT = ROOT / "docs" / "bridge_validation"


def run_stages(fx, root):
    orch.RUNS_DIR = root
    run = orch.Run("bridge-audit")
    run.save_state({"stage": "outline", "status": "READY", "counters": {}})
    for name, value in (("synthesis_approved.json", fx["pkg"]), ("selected_corpus.json", fx["corpus"]),
                        ("validated_findings.json", fx["findings"])):
        run.save(name, value)
    run.cfg = {**run.cfg, "bridge": {**run.cfg["bridge"], "ledger_approval": False}}
    report = lambda m, *a, **k: {"verification_fingerprint": fingerprint(m), "verification_execution": "COMPLETE",
                                 "findings": [], "occurrence_inventory": [], "release_disposition": "APPROVED"}
    for name, value in (("_publishable", lambda n: run.load(n)), ("_findings", lambda: run.load("validated_findings.json")),
                        ("_verify", report), ("_maybe_verify", report),
                        ("_verification_current", lambda rv, m: rv.get("verification_fingerprint") == fingerprint(m)),
                        ("_prose_vendors", lambda reader: frozenset({"anthropic"})),   # A11 on Kimi K3.1 Pro
                        ("_reproject", lambda stage: None), ("_downstream_gate", lambda *a: None),
                        ("_check_request_line", lambda a: None), ("_check_long_context", lambda *a: None),
                        ("_require_projection", lambda: None)):
        setattr(run, name, value)
    agents = Agents(run, fx)
    run.agent = agents
    for stage in ("outline", "draft", "review_loop", "finish_edit"):
        getattr(run, f"stage_{stage}")(run.state())
    admissions = [e["summary"] | {"step": e["step"]} for e in run.prov.events()
                  if e["type"] == "tool_run" and e["tool"] == "admission"]
    return run, agents, admissions


def oversized(big):
    cfg, prices = config.load("pipeline"), config.load("prices")
    adm = cfg["admission"]
    route = lambda a: config.agent_candidates(a)[0]
    journal = config.load("journal_scirev")
    table = bridge.comparative_table(big["pkg"], big["findings"], big["corpus"])
    plan, ledger = fixture_plan(big["pkg"], big["corpus"], table)
    packets = bridge.section_packets(plan, ledger, big["pkg"], big["findings"], big["corpus"])
    amap = bridge.argument_map(big["pkg"], big["corpus"])
    largest = max(packets, key=lambda s: bridge.size(packets[s]))
    m = {"title": "t", "abstract": "a ⟦ORG⟧", "sections": [{"section_id": s["section_id"], "heading": s["heading"],
                                                             "text_markdown": "x ⟦ORG⟧"} for s in plan["sections"]]}
    requests = {"A08-OL": bridge.outline_payload(big["pkg"], big["corpus"], journal, table, cfg["bridge"]),
                "A09-WRI": bridge.writer_payload(plan, packets[largest], [], amap, journal),
                "A11-RC": bridge.critique_payload(m, amap, ledger, {}, journal, None),
                "A12-EDI (one unit)": bridge.editor_payload("LINE", {"sections": m["sections"][:1]}, amap, ledger, plan)}
    out = {}
    for label, payload in requests.items():
        agent = label.split()[0]
        model = route(agent)
        out[label] = admission.assess(agent, payload, model, adm, prices)
    return describe(big), out


def projections(fx):
    import dataclasses  # noqa: F401
    b = BudgetTracker(Path(tempfile.mkdtemp()))
    cfg = config.load("pipeline")
    route = lambda a, ex=frozenset(): config.agent_candidates(a)[0]
    keep = ("stage", "basis", "calls", "usd", "long_context_calls", "over_window_calls", "max_input_bound")
    inputs = {"pkg": fx["pkg"], "findings": fx["findings"], "corpus": fx["corpus"], "plan": fx["plan"], "ledger": fx["ledger"]}
    return {"request_bound_with_plan": [{k: x[k] for k in keep} for x in dp.lines(b, route, cfg, len(fx["findings"]), inputs)],
            "estimate_before_package": [{k: x[k] for k in keep} for x in dp.lines(b, route, cfg, len(fx["findings"]))],
            "estimate_two_papers": [{k: x[k] for k in keep} for x in dp.lines(b, route, cfg, 82)]}


def provider_counts(agents):
    from dotenv import load_dotenv
    from litreview.llm.anthropic_client import count_tokens
    load_dotenv(ROOT.parent / "lit-review-agents" / ".env")
    load_dotenv(ROOT / ".env")
    sections = [(s, p) for a, s, p in agents.calls if a == "A09-WRI" and p["mode"] == "SECTION"]
    step, largest = max(sections, key=lambda sp: bridge.size(sp[1]))
    front = next((s, p) for a, s, p in agents.calls if a == "A09-WRI" and p["mode"] == "FRONT_MATTER")
    integration = next((s, p) for a, s, p in agents.calls if a == "A12-EDI" and p["mode"] == "INTEGRATION")
    out = []
    for agent, (s, payload) in (("A09-WRI", (step, largest)), ("A09-WRI", front), ("A12-EDI", integration)):
        model = config.agent_candidates(agent)[0]
        system = build_system_prompt(agent)
        tokens = count_tokens(system, user_parts(payload), model.model)
        bound = admission.input_bound(system, payload)
        out.append({"agent": agent, "step": s, "model": model.model, "provider_input_tokens": tokens,
                    "input_byte_bound": bound, "bytes_per_token": round(bound / tokens, 3)})
    return out


def main(count: bool):
    fx = compact_package(120)
    fx["table"] = bridge.comparative_table(fx["pkg"], fx["findings"], fx["corpus"])
    fx["plan"], fx["ledger"] = fixture_plan(fx["pkg"], fx["corpus"], fx["table"])
    problems, report = bridge.validate_plan(fx["plan"], fx["ledger"], fx["pkg"], fx["corpus"], fx["table"],
                                            config.load("journal_scirev"), config.load("pipeline")["bridge"])
    packets = bridge.section_packets(fx["plan"], fx["ledger"], fx["pkg"], fx["findings"], fx["corpus"])
    with tempfile.TemporaryDirectory(prefix="bridge-audit-") as tmp:
        run, agents, admissions = run_stages(fx, Path(tmp))
        counts = provider_counts(agents) if count else None
    by_agent = {}
    for a in admissions:
        x = by_agent.setdefault(a["agent"], {"requests": 0, "max_input_bound": 0, "sum_input_bound": 0, "all_fit": True,
                                             "crossing_threshold": 0, "window": a["window"], "model": a["model"]})
        x["requests"] += 1
        x["max_input_bound"] = max(x["max_input_bound"], a["input_bound"])
        x["sum_input_bound"] += a["input_bound"]
        x["all_fit"] &= a["fits"]
        x["crossing_threshold"] += a["crosses_threshold"]
    big_shape, big = oversized(oversized_package())
    result = {
        "method": "evaluation-only fixtures; production request builders; scripted agents; no generation endpoint",
        "compact_fixture": describe(fx), "plan_problems": problems, "ledger_counts": report["counts"],
        "mandatory_elements": len(report["mandatory"]),
        "table": {k: (len(v) if isinstance(v, list) else v) for k, v in fx["table"].items()
                  if k in ("rows", "contrary_finding_ids", "contrary_findings_not_shown", "eligible_findings_not_shown",
                           "propositions_fully_shown")},
        "section_packet_bytes": {s: bridge.size(p) for s, p in packets.items()},
        "argument_map_bytes": bridge.size(bridge.argument_map(fx["pkg"], fx["corpus"])),
        "admissions_by_agent": by_agent, "admissions": admissions,
        "oversized_fixture": big_shape, "oversized_admission": big,
        "projections": projections(fx), "provider_counts": counts}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "measurements.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("compact_fixture", "ledger_counts", "table", "admissions_by_agent",
                                             "oversized_admission", "provider_counts")}, indent=1))
    print(json.dumps(result["projections"], indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true", help="also use Anthropic's free input-token counter")
    main(ap.parse_args().count)
