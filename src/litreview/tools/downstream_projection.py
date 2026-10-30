"""Projection lines for A08 (outline), A09 (writing), A11 (critique) and A12 (editing), from the bounded request
builders in bridge.py, the same builders the calls use.

Every request is sized by its admission bound (admission.py: UTF-8 bytes of the exact serialized request). Its
pricing tier is chosen by that bound, as at dispatch: a request whose bound is above a model's long-context
threshold is priced entirely at the long-context rates and counted in `long_context_calls`, so the dispatch-time
threshold check finds it already priced. Its input is priced as BYTES_PER_TOKEN bytes per token, uncached, plus
its full output reserve. No cache savings are assumed. Dispatch reserves the full byte bound (one token per byte),
which is stricter still.

Basis, by what exists when the projection is made:
  REQUEST_BOUND        the approved package exists: A08's request is built exactly; A09's from the actual section
                       packets once the plan exists (before it, one packet per primary theme); earlier prose,
                       manuscripts and A10 summaries from the journal's word limits and fixed allowances.
  ESTIMATED_ENVELOPE   no package yet (CP2): sizes per finding measured on the compact 120-paper fixture
                       (tests/bridge_fixtures.py, docs/bridge_validation.md), scaled by the projected findings.
                       An estimate, not a bound; each call is admitted and reserved at its own bound at dispatch.

Call counts are the most each stage can make under the configured loops: each A09 section with every retrieval
round, every section redrafted `max_redrafts` times, the front matter per draft, every critique cycle followed by
a revision, and the integration (per draft), LINE and PROOF passes. A12 requests too large for the window are
counted per unit (front matter plus one per section), which is how they are dispatched.
"""
from __future__ import annotations

import dataclasses

from .. import bridge
from ..admission import AdmissionRefused, context_window, output_reserve
from ..agents.base import build_system_prompt
from ..synthesis_registry import offline_tokens

# Upper bound on serialized bytes per word of tagged prose: about 6.5 bytes per English word with its space, a
# ⟦…⟧ tag (each bracket 3 bytes in UTF-8) per sentence and a [@R…] citation about every 15 words.
BYTES_PER_WORD = 12
# Before a package exists: sizes per projected finding, measured on the compact 120-paper fixture (1,996 findings,
# 1,052 elements, 2026-10-30; docs/bridge_validation.md), rounded up: argument map 92 bytes, element index 186,
# section packets 2,253 summed over all sections; 1.9 findings per element; a retrieved record with its own
# findings about 5.4 kB.
AMAP_BYTES_PER_FINDING = 100
INDEX_BYTES_PER_FINDING = 200
PACKET_BYTES_PER_FINDING = 2400
FINDINGS_PER_ELEMENT = 1.9
RETRIEVED_RECORD_BYTES = 6000
# Bytes per input token, from Anthropic's free token counter (docs/bridge_validation/measurements.json, 2026-10-30):
# the bridge's own requests on the compact fixture gave 2.381 (largest A09 section, Opus 5), 2.147 (A09 front
# matter) and 1.925 (A12 integration, Sonnet 5.5: map and ledger IDs tokenize densely); the integrated audit's
# writer and editor requests gave 2.33-2.34. 1.8 is below every observation, so it overstates tokens.
BYTES_PER_TOKEN = 1.8
A10_SUMMARY_BYTES = 200_000      # A10's findings as A11/A12 receive them (no inventory or verdicts): an allowance
ESTIMATE_SECTIONS = 8            # introduction, six body sections, conclusion
FRAMING = 4096                   # payload keys, journal profile and outline beyond what is counted separately


def _system(agent: str) -> int:
    return offline_tokens(build_system_prompt(agent))


def _model(agent: str, route, bcfg: dict, limit: str | None):
    m = route(agent)
    return dataclasses.replace(m, max_tokens=int(bcfg["output_limits"][limit])) if limit else m


def _price(agent: str, bound: int, limit: str | None, budget, route, adm: dict, bcfg: dict, s: dict | None) -> tuple:
    """(usd, output tokens, crosses threshold, over window) for one request. s None: strict pricing (input at the
    byte bound / BYTES_PER_TOKEN, tier by the byte bound as at dispatch, the full output reserve); s a scenario:
    input at bytes / its bytes_per_token, tier by those tokens, its share of the output reserve."""
    m = _model(agent, route, bcfg, limit)
    try:
        out = output_reserve(m, adm)
    except AdmissionRefused:
        out = 2 * int(m.max_tokens)          # reasoning reserve unknown: priced at twice the cap
    threshold = (budget.prices.get(m.model) or {}).get("long_context_threshold")
    tokens = bound / (float(s["bytes_per_token"]) if s else BYTES_PER_TOKEN)
    rates = budget._rates(m.model, bound if s is None else int(tokens))
    used = out * (float(s["output"]) if s else 1.0)
    usd = 0.0 if rates is None else (tokens * rates["input"] + used * rates["output"]) / 1e6
    try:
        over = bound + out > context_window(m.model, adm)
    except AdmissionRefused:
        over = True                          # no recorded window: refused at dispatch
    return usd, used, bool(threshold and bound > threshold), over


def _weight(tag: str, s: dict) -> float:
    """How many times a tagged request is expected under scenario s (adverse: every loop at its maximum)."""
    kind, _, n = tag.partition(":")
    r, d = float(s["retrieval"]), float(s["redraft"])
    if kind == "retrieval":                  # round n of a section's evidence requests
        return r if (int(n) == 1 or r >= 1.0) else 0.0
    if kind in ("redraft", "front_redraft", "integration_redraft"):
        return d
    if kind == "redraft_retrieval":
        return d * (r if (int(n) == 1 or r >= 1.0) else 0.0)
    if kind == "critique":
        return 1.0 if int(n) <= int(s["cycles"]) else 0.0
    if kind == "revision":
        return 1.0 if int(n) <= int(s["revisions"]) else 0.0
    return 1.0                               # outline, section, front, integration, line, proof


def _line(agent: str, requests: list[tuple[int, str | None, str]], budget, route, cfg: dict, basis: str,
          detail: str) -> dict:
    """The projection line for one agent. `usd`: the calibrated baseline plus the forecast's uncertainty margin
    (pipeline.yaml -> forecast). `adverse_usd`: every request the loops allow, full output, strict pricing.
    `calls` and `long_context_calls` count every request the configured loops allow, so neither a retrieval
    round nor a redraft forces re-projection, while spend beyond `usd` does. `scenarios`: each scenario's figure."""
    adm, bcfg, fc = cfg.get("admission") or {}, cfg.get("bridge") or {}, cfg.get("forecast") or {}
    scen = {name: round(sum(_weight(t, s) * _price(agent, b, k, budget, route, adm, bcfg, s)[0] for b, k, t in requests), 4)
            for name, s in (fc.get("scenarios") or {}).items()}
    strict = [_price(agent, b, k, budget, route, adm, bcfg, None) for b, k, _ in requests]
    margin = float(fc.get("uncertainty_margin", 0.30))
    adverse = sum(x[0] for x in strict)
    baseline = scen.get("baseline", adverse)
    m = route(agent)
    return {"stage": agent, "basis": basis, "calls": len(requests), "usd": round(baseline * (1 + margin), 4),
            "baseline_usd": round(baseline, 4), "uncertainty_margin": margin, "adverse_usd": round(adverse, 4),
            "scenarios": scen, "long_context_calls": sum(x[2] for x in strict),
            "over_window_calls": sum(x[3] for x in strict), "max_input_bound": max((b for b, _, _ in requests), default=0),
            "detail": f"up to {len(requests)} requests on {m.model}; usd = calibrated baseline x {1 + margin:.2f}; "
                      f"adverse = every request, full output, bytes / {BYTES_PER_TOKEN}; {detail}"}


def _prose_bytes(journal: dict) -> int:
    lim = journal.get("limits") or {}
    words = sum(int(lim.get(k, d)) for k, d in (("main_text_max_words", 5000), ("abstract_max_words", 200),
                                                  ("title_max_words", 20), ("figure_legend_max_words", 350)))
    return words * BYTES_PER_WORD


def requests(route, cfg: dict, n_findings: int, inputs: dict | None = None) -> dict:
    """Every A08, A09, A11 and A12 request the configured loops allow, as (byte bound, output-limit kind, tag)."""
    from .. import config
    inputs = inputs or {}
    journal = inputs.get("journal") or config.load("journal_scirev")
    adm, bcfg, loops = cfg.get("admission") or {}, cfg.get("bridge") or {}, cfg["loops"]
    cycles, redrafts = int(loops["max_critique_cycles"]), int(loops["max_redrafts"])
    rounds, rlimit = int(bcfg.get("max_retrieval_rounds", 2)), int(bcfg.get("retrieval_limit", 12))
    prose = _prose_bytes(journal)
    pkg = inputs.get("pkg")
    if pkg:
        basis = "REQUEST_BOUND"
        corpus, findings, plan, ledger = (inputs.get("corpus") or [], inputs.get("findings") or [],
                                          inputs.get("plan"), inputs.get("ledger"))
        try:
            table = bridge.comparative_table(pkg, findings, corpus, int(bcfg.get("table_max_rows", 25)))
        except bridge.BridgeError:
            table = {"propositions_fully_shown": [], "row_finding_ids": [], "rows": []}
        amap = bridge.argument_map(pkg, corpus, findings)
        a08 = _system("A08-OL") + offline_tokens(bridge.outline_payload(pkg, corpus, journal, table, bcfg, findings))
        # packets carry the contrary-evidence register entries, as the writing stage builds them
        register = (bridge.contrary_register(pkg, findings, table, plan, ledger if plan else None)
                    if table.get("status") == "BUILT" else None)
        packets = _packets(plan, ledger, pkg, findings, corpus, register)
        outline = bridge.outline_view(plan) if plan else None
        outline_b = bridge.size(outline) if outline else 4_000 + 600 * len(packets)
        thesis_b = bridge.size(amap.get("thesis"))
        record_sizes = sorted((bridge.size(r) for p in packets.values() for r in bridge.packet_records(p).values()),
                              reverse=True)
        packet_b = {sid: bridge.size(p) for sid, p in packets.items()}
        budgets = {s["section_id"]: int(s.get("word_budget") or 0) for s in (plan or {}).get("sections") or []}
        order = (plan or {}).get("writing_order") or list(packets)
        ledger_rows = len(bridge.elements(pkg))
        amap_b = bridge.size(amap)
        table_b = bridge.size(table.get("rows"))
        detail_plan = "the approved plan's sections" if plan else f"{len(packets)} sections estimated from the themes"
    else:
        basis = "ESTIMATED_ENVELOPE"
        amap_b = n_findings * AMAP_BYTES_PER_FINDING
        a08 = _system("A08-OL") + amap_b + n_findings * INDEX_BYTES_PER_FINDING + FRAMING
        packets = {f"S{i}": None for i in range(1, ESTIMATE_SECTIONS + 1)}
        packet_b = {sid: n_findings * PACKET_BYTES_PER_FINDING // ESTIMATE_SECTIONS for sid in packets}
        order, budgets, outline_b, thesis_b = list(packets), {}, 4_000 + 600 * ESTIMATE_SECTIONS, 2_000
        n_elements = max(1, int(n_findings / FINDINGS_PER_ELEMENT))
        record_sizes = [RETRIEVED_RECORD_BYTES] * n_elements
        ledger_rows, table_b = n_elements, 25 * 900
        detail_plan = f"{ESTIMATE_SECTIONS} sections assumed; sizes per finding from the compact fixture"
    per_round = [sum(record_sizes[i * rlimit:(i + 1) * rlimit]) for i in range(rounds)]
    a09, written = [], 0
    for k, sid in enumerate(order):
        earlier = written if budgets else prose * k // max(1, len(order))
        base = _system("A09-WRI") + FRAMING + outline_b + thesis_b + packet_b[sid] + earlier
        a09.append((base, "A09_SECTION", "section"))
        a09 += [(base + sum(per_round[:n]), "A09_SECTION", f"retrieval:{n}") for n in range(1, rounds + 1)]
        written += budgets.get(sid, 0) * BYTES_PER_WORD
    first = list(a09)
    for _ in range(redrafts):
        a09 += [(b, k, "redraft" if t == "section" else "redraft_retrieval:" + t.partition(":")[2]) for b, k, t in first]
    front = _system("A09-WRI") + FRAMING + outline_b + thesis_b + table_b + prose
    a09 += [(front, "A09_FRONT_MATTER", "front")] + [(front, "A09_FRONT_MATTER", "front_redraft")] * redrafts
    ledger_b = ledger_rows * 90
    a11_in = _system("A11-RC") + FRAMING + prose + amap_b + ledger_b + A10_SUMMARY_BYTES + 4 * int(route("A11-RC").max_tokens)
    a11 = [(a11_in, None, f"critique:{c}") for c in range(1, cycles + 1)]
    whole = _system("A12-EDI") + FRAMING + prose + amap_b + ledger_b + outline_b + A10_SUMMARY_BYTES \
        + 4 * int(route("A11-RC").max_tokens)
    passes = ["integration"] + ["integration_redraft"] * redrafts + [f"revision:{c}" for c in range(1, cycles + 1)] \
        + ["line", "proof"]
    m12 = route("A12-EDI")
    try:
        fits = whole + output_reserve(m12, adm) <= context_window(m12.model, adm)
    except AdmissionRefused:
        fits = False
    if fits:
        a12, how = [(whole, None, tag) for tag in passes], "whole-manuscript requests"
    else:
        units = len(packets) + 1
        a12 = [(whole - prose + -(-prose // max(1, units - 1)), "A12_UNIT", tag) for tag in passes for _ in range(units)]
        how = f"{units} units per pass (the whole manuscript does not fit the window)"
    return {"basis": basis,
            "A08-OL": ([(a08, None, "outline")], "the outline request (map, element index, table coverage)"),
            "A09-WRI": (a09, f"{detail_plan}, each with up to {rounds} retrieval rounds and {redrafts} redraft(s), "
                             "plus front matter per draft"),
            "A11-RC": (a11, f"up to {cycles} critique cycles: manuscript, map, ledger, A10 summary"),
            "A12-EDI": (a12, f"integration per draft, up to {cycles} revisions, LINE and PROOF ({how})")}


def lines(budget, route, cfg: dict, n_findings: int, inputs: dict | None = None) -> list[dict]:
    """A08, A09, A11 and A12 lines. inputs: {"pkg", "corpus", "findings", "plan", "ledger", "journal"} (any may be
    missing; without a package the lines are estimates)."""
    req = requests(route, cfg, n_findings, inputs)
    return [_line(a, req[a][0], budget, route, cfg, req["basis"], req[a][1])
            for a in ("A08-OL", "A09-WRI", "A11-RC", "A12-EDI")]


def _packets(plan, ledger, pkg, findings, corpus, register=None) -> dict:
    """The approved plan's packets; before a plan, one estimated packet per primary theme (its propositions, an even
    share of gaps and interpretations, their contrary context and index), plus an introduction and a conclusion
    the size of the largest. Stale evidence is priced as it stands (the stage itself refuses it)."""
    if plan and ledger is not None:
        try:
            return bridge.section_packets(plan, ledger, pkg, findings, corpus, register)
        except bridge.BridgeError:
            pass
    els = bridge.elements(pkg)
    themes: dict[str, list[str]] = {}
    for e, el in els.items():
        if el["kind"] == "PROPOSITION":
            themes.setdefault(el["record"].get("primary_theme_id") or "UNMAPPED", []).append(e)
    others = [e for e, el in els.items() if el["kind"] != "PROPOSITION"]
    n = max(1, len(themes))
    fby = {f["finding_id"]: f for f in findings}
    out = {}
    for i, (th, ids) in enumerate(sorted(themes.items()), start=2):
        items = ids + others[i - 2::n]
        sid = f"S{i}"
        section = {"section_id": sid, "heading": th, "ordered_items": [{"item_id": x} for x in items]}
        led = [{"item_id": x, "outcome": "DISCUSSED", "section_id": sid} for x in items]
        try:
            out[sid] = bridge.section_packets({"sections": [section]}, led, pkg, findings, corpus, register)[sid]
        except bridge.BridgeError:
            out[sid] = {"units": [{"records": {x: {"record": els[x]["record"],
                                                   "findings": {f: fby.get(f) for f in bridge._finding_ids(els[x]["record"])}}
                                               for x in items}}]}
    largest = max(out.values(), key=bridge.size) if out else {"units": []}
    out["S1"], out[f"S{n + 2}"] = largest, largest
    return dict(sorted(out.items(), key=lambda kv: bridge._natural(kv[0])))
