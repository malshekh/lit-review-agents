"""Evidence-first reconciliation paging. The global index remains visible on every turn."""
from .synthesis_registry import compact_proposition, fingerprint


def build_pages(job, rejected_focus, leads, measure, max_findings, max_bytes, questions):
    props = job._all_props()
    by_id = {p["proposition_id"]: p for p in props}
    index = [compact_proposition(p) for p in props]
    if len(set(rejected_focus)) != len(rejected_focus) or set(rejected_focus) - by_id.keys():
        raise ValueError("invalid rejected-page focus")
    links = {pid: {e["finding_id"] for e in p["evidence"]} for pid, p in by_id.items()}
    if len(questions) != len(leads):
        raise ValueError("each unaccepted issue needs a comparison question")
    assignments = {pid: [] for pid in by_id}
    for n, issue in enumerate(leads, 1):
        related = set(issue["proposition_ids"])
        anchors = set(issue["finding_ids"])
        candidates = related.intersection(rejected_focus)
        if not candidates or related - by_id.keys() or anchors - job.registry.findings.keys():
            raise ValueError("unbound reconciliation lead")
        # Own each hypothesis once. Prefer a proposition that joins many of its evidence links.
        owner = min(candidates, key=lambda p: (-len(links[p] & anchors), len(links[p]), p))
        assignments[owner].append({"lead": n, "question": questions[n-1], "compare": sorted(related), "inspect": sorted(anchors)})
    def make(focus):
        hints = [h for pid in focus for h in assignments[pid]]
        ids = set().union(*(links[p] for p in focus), *(set(h["inspect"]) for h in hints))
        sources = {}
        for pid in focus:
            if links[pid]:
                continue
            for iid in by_id[pid].get("source_item_ids", []):
                sources[iid] = {
                    "frozen_source_sha256": fingerprint(job.registry.item_source(iid)),
                    "accepted_propositions": [p["proposition_id"] for p in props if iid in p["source_item_ids"]],
                    "accepted_gap_statements": [g["statement"] for g in job._gaps() if iid in g.get("source_item_ids", [])],
                }
        return {"mode":"RECONCILE", "focus":[{"proposition_id":p} for p in focus],
                "global_proposition_index":index, "global_independence":job.registry.independence(job.finding_ids),
                "mandatory_conflict_index":[{"item_id":i,"findings":sorted(job.registry.item_findings(i))}
                                           for i,m in job.mandatory.items() if m["kind"]=="CONFLICT"],
                "retrieval":{"available":True,"operations":["finding_ids","query"]},
                "source_items_for_reporting_only_propositions":sources, "comparison_leads":hints,
                "reconciliation_instruction":("Review every focal proposition and search the full index for other comparisons. "
                    "The leads are unverified suggestions. Check reported outcome, task, split, matrix and uncertainty. "
                    "Different models, contexts or metrics can yield different results without a contradiction. "
                    "Request missing full records before judging; use only findings supplied in this turn for issue anchors. "
                    "For T5 use three contributing publications with unknown study and dataset independence; "
                    "The T8 packet has zero eligible supporting findings. Keep R0090:F3 quarantined and R0090:F11 and R0078:F25 pending. R0078:F28 is source-derived. R0090 reports detection limits of 0.54 micromolar in spiked water and 0.69 micromolar in commercial plasma spiked before ethanol pretreatment. Total versus unbound erlotinib remains unestablished. Post-dose and serial performance are unestablished in the eligible T5 findings. T6 and T7 are gaps in this corpus."),
                "prefill_finding_ids":sorted(ids)}
    def size(focus):
        p = make(focus)
        ids = p["prefill_finding_ids"]
        if len(ids)>max_findings or len(focus)>32:
            return None
        n = measure({**p,"retrieved_evidence":job.registry.details(ids)})
        return n if n <= max_bytes else None
    pages = []
    for cohort in (rejected_focus,[p for p in by_id if p not in rejected_focus]):
        bins = []
        # Place expensive focal units first, preferring the smallest marginal rendered size.
        for pid in sorted(cohort,key=lambda p: -len(make([p])["prefill_finding_ids"])):
            if size([pid]) is None:
                raise ValueError(f"single evidence unit exceeds reconciliation bounds: {pid}")
            choices = []
            for i,(members,previous) in enumerate(bins):
                total = size(members+[pid])
                if total is not None: choices.append((total-previous,i,total))
            if choices:
                _,i,total = min(choices)
                bins[i]=(bins[i][0]+[pid], total)
            else:
                bins.append(([pid],size([pid])))
        pages.extend(make(sorted(members,key=cohort.index)) for members,_ in bins)
    return pages

def provider_body(run, enriched, model, cap):
    """Render the same Anthropic streaming parameters as the paid A07 call, with no client."""
    from .agents.base import build_system_prompt, user_parts
    return generation_body(build_system_prompt("A07-SYN"), user_parts(enriched), model, cap,
                           True, run.cfg["synthesis"].get("cache_ttl", "1h"))


def generation_body(system, message, model, cap, cache_system, cache_ttl):
    from .agents.base import _provider_response_schema
    from .llm.anthropic_client import message_params
    if model.provider != "anthropic":
        raise ValueError("reconciliation quote requires the reviewed Anthropic route")
    agent = "A07-SYN"
    schema = _provider_response_schema(agent, "A07-SYN.bounded-reconcile.schema.json", model.provider, model.model)
    params = message_params(system, message, model.model, cap, model.temperature, model.effort,
                            cache_system, cache_ttl, {"agent":agent}, schema)
    return {**params, "stream":True}


def body_bytes(params):
    import json
    return json.dumps(params,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode("utf8")


def check_spend(approval, stage_committed, new_hold):
    """The incremental ceiling includes every retry, lookup and unsettled reservation."""
    from decimal import Decimal
    # Ledger entries are stored as floats. Strip binary summation noise below a trillionth of a dollar.
    used = (Decimal(str(stage_committed)) - Decimal(str(approval["baseline_stage_usd"]))).quantize(Decimal("1e-12"))
    if used < 0 or used + Decimal(str(new_hold)) > Decimal(str(approval["max_increment_usd"])):
        raise ValueError("reconciliation repair would exceed the approved incremental reservation")
