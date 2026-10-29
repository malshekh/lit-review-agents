"""A07's immutable evidence registry and bounded, deterministic payload builders.

The registry is authoritative; indexes are discovery aids, never evidence substitutes.
Unknown study/cohort identities stay unknown. No per-packet count establishes replication.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict

from .evidence import status_of


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def offline_tokens(value) -> int:
    """Conservative admission estimate: UTF-8 bytes (at most one token per byte), plus framing.

    Deliberately no network tokenizer. Runtime and simulations use this same estimator;
    caching never changes it. Provider token counts should later calibrate cost forecasts.
    """
    text = value if isinstance(value, str) else canonical(value)
    return len(text.encode("utf-8")) + 1024


def chunks(xs, size):
    return [xs[i:i + size] for i in range(0, len(xs), size)]


class EvidenceRegistry:
    def __init__(self, corpus: dict):
        self.corpus = json.loads(canonical(corpus))
        corpus = self.corpus
        self.findings = {f["finding_id"]: f for f in corpus["validated_findings"]}
        if len(self.findings) != len(corpus["validated_findings"]):
            raise ValueError("duplicate finding IDs")
        self.records = {r["record_id"]: r for r in corpus["selected_corpus"]}
        self.contexts = corpus.get("contexts") or {}
        self.framework = corpus.get("theme_framework") or {}
        self.themes = {t["theme_id"]: t for t in self.framework.get("primary_themes", [])}
        mandatory = sorted((m for m in corpus["coverage_manifest"]
                            if m.get("required_visibility") in ("CITED", "NARRATIVE")), key=lambda m: m["item_id"])
        self.items = {f"M{n:05d}": {**m, "item_id": f"M{n:05d}", "original_item_id": m["item_id"]}
                      for n, m in enumerate(mandatory, 1)}
        self.record_of = {fid: f["record_id"] for fid, f in self.findings.items()}
        for f in self.findings.values():
            if f["record_id"] not in self.records:
                raise ValueError(f"unknown source record: {f['finding_id']}")
            if f.get("context_id") and f["context_id"] not in self.contexts:
                raise ValueError(f"missing context: {f['finding_id']}")
        self.digest = fingerprint(self.corpus)

    def theme_of(self, f):
        pid = f.get("primary_theme_id")
        return pid if pid in self.themes else "UNMAPPED"

    def study_identity(self, fid):
        f, r = self.findings[fid], self.records[self.record_of[fid]]
        # Explicit identities only. A publication is never silently an independent study.
        return {k: f.get(k) or r.get(k) or (r.get("registration_id") if k == "nct_id" else None)
                for k in ("study_id", "cohort_id", "dataset_id", "nct_id")}

    def independence(self, ids):
        ids = sorted(set(ids))
        ident = [self.study_identity(f) for f in ids]
        known_studies = {x["study_id"] or x["nct_id"] for x in ident if x["study_id"] or x["nct_id"]}
        known_datasets = {x["dataset_id"] or x["cohort_id"] for x in ident if x["dataset_id"] or x["cohort_id"]}
        return {"papers": len({self.record_of[f] for f in ids}),
                "independent_studies": None, "independent_datasets_or_cohorts": None,
                "distinct_explicit_studies": len(known_studies), "distinct_explicit_datasets_or_cohorts": len(known_datasets),
                "known_study_ids": sorted(known_studies),
                "known_cohort_ids": sorted({x["cohort_id"] for x in ident if x["cohort_id"]}),
                "known_dataset_ids": sorted({x["dataset_id"] for x in ident if x["dataset_id"]}),
                "identity_unknown_findings": [f for f, x in zip(ids, ident) if not any(x.values())],
                "basis": "global explicit identifiers only; distinct IDs do not establish independence"}

    def index_line(self, fid):
        f = self.findings[fid]
        def entity(eid):
            e = (f.get("entities") or {}).get(eid) or (self.corpus.get("source_entities") or {}).get(f"{f['record_id']}:{eid}") or {}
            return [eid, e.get("mention"), e.get("type")]
        # Never truncate an assertion and then present the fragment as scientific evidence.
        return {"id": fid, "record": f["record_id"], "theme": self.theme_of(f),
                "relation": [entity(f.get("subject")), f.get("predicate"), f.get("predicate_detail"), entity(f.get("object"))],
                "state": [status_of(f), f.get("direction"), f.get("polarity"), f.get("modality"),
                          f.get("assertion_type"), f.get("attributed_to")],
                "context": f.get("context_id"), "study": {k:v for k,v in self.study_identity(fid).items() if v}}

    def item_source(self, iid):
        item = self.items[iid]
        th = item.get("theme_record")
        rec = (self.corpus.get("theme_records") or {}).get(th, {})
        if item["kind"] == "CONFLICT":
            source = (rec.get("conflicts") or [])[item["conflict_index"] - 1]
        elif item["kind"] == "EVIDENCE_REACH":
            source = rec.get("evidence_reach") or rec
        elif item["kind"] == "SELECTED_PAPER":
            source = self.records[item["record_id"]]
        else:
            source = item
        return {"item": item, "source": source}

    def item_findings(self, iid):
        return set(re.findall(r"\bR\d+:F\d+\b", canonical(self.item_source(iid)))) & set(self.findings)

    def packets(self, size=24, item_size=8):
        by_theme = defaultdict(list)
        for fid, f in sorted(self.findings.items()):
            by_theme[self.theme_of(f)].append(fid)
        packets = []
        for theme, fids in sorted(by_theme.items()):
            for part in chunks(fids, size):
                packets.append({"group_id": f"G{len(packets)+1:04d}", "primary_theme_id": theme,
                                "name": self.themes.get(theme, {}).get("name", theme),
                                "kind": "REPORTING_ONLY_THEME", "basis": "approved primary theme; no inferred relationship",
                                "finding_ids": part, "manifest_item_ids": []})
        # Evidence units are not copied to every packet. Every mandatory item gets exactly one owner.
        extra = []
        for iid, item in sorted(self.items.items()):
            anchors = self.item_findings(iid)
            candidates = [p for p in packets if anchors & set(p["finding_ids"])]
            if not candidates and item.get("record_id"):
                candidates = [p for p in packets if any(self.record_of[f] == item["record_id"] for f in p["finding_ids"])]
                candidates.sort(key=lambda p: not any(self.record_of[f] == item["record_id"] and
                    status_of(self.findings[f]) in ("SUPPORTING", "NOT_ESTABLISHED") for f in p["finding_ids"]))
            if not candidates and item.get("theme_record") in self.themes:
                candidates = [p for p in packets if p["primary_theme_id"] == item["theme_record"]]
            if candidates and len(candidates[0]["manifest_item_ids"]) < item_size:
                candidates[0]["manifest_item_ids"].append(iid)
            else:
                extra.append(iid)
        for part in chunks(extra, item_size):
            paper_anchors = []
            for iid in part:
                item = self.items[iid]
                if item["kind"] == "SELECTED_PAPER":
                    eligible = [f for f in self.findings if self.record_of[f] == item["record_id"] and
                                status_of(self.findings[f]) in ("SUPPORTING", "NOT_ESTABLISHED")]
                    paper_anchors.extend(eligible[:1])
            packets.append({"group_id": f"G{len(packets)+1:04d}", "primary_theme_id": "UNMAPPED",
                            "name": "Mandatory evidence records", "kind": "REPORTING_ONLY_THEME",
                            "basis": "explicit mandatory source records", "finding_ids": sorted(set(paper_anchors)), "manifest_item_ids": part})
        return packets

    def plan_payload(self, packets):
        return {"mode": "PLAN", "review_spec": self.corpus["review_spec"], "theme_framework": self.framework,
                "evidence_index": [self.index_line(f) for f in self.findings],
                "context_index": {cid: {k: c.get(k) for k in ("evidence_system", "species", "cell_line_or_type", "endpoint")
                                        if c and c.get(k)} for cid, c in self.contexts.items()},
                "coverage": self.alignment(packets), "revision_feedback": self.corpus.get("revision_feedback")}

    def alignment(self, packets):
        return {"themes": [{**t, "findings": sum(self.theme_of(f) == tid for f in self.findings.values()),
                            "subthemes": sorted({s for f in self.findings.values() if self.theme_of(f) == tid
                                                 for s in f.get("subthemes") or []}),
                            "independence": self.independence([fid for fid, f in self.findings.items() if self.theme_of(f) == tid])}
                           for tid, t in self.themes.items()],
                "unmapped": [fid for fid, f in self.findings.items() if self.theme_of(f) == "UNMAPPED"],
                "emerging": [fid for fid, f in self.findings.items() if f.get("emerging")],
                "mandatory_items": len(self.items), "packets": len(packets),
                "conflicts": [i for i, m in self.items.items() if m["kind"] in ("CONFLICT", "IN_PAPER_CONFLICT", "SOURCE_INCONSISTENCY")]}

    def details(self, ids):
        if set(ids) - set(self.findings):
            raise ValueError("retrieval requested unknown finding")
        entities = {}
        for fid in ids:
            f = self.findings[fid]
            for eid in (f.get("subject"), f.get("object")):
                key = f"{f['record_id']}:{eid}"
                if key in (self.corpus.get("source_entities") or {}):
                    entities[key] = self.corpus["source_entities"][key]
        return {"findings": [self.findings[f] for f in sorted(set(ids))], "source_entity_attributes": entities,
                "contexts": {self.findings[f]["context_id"]: self.contexts[self.findings[f]["context_id"]]
                             for f in ids if self.findings[f].get("context_id")}}

    def packet_payload(self, packet):
        return {"mode": "GROUP", "group": packet, **self.details(packet["finding_ids"]),
                "source_items": {i: self.item_source(i) for i in packet["manifest_item_ids"]},
                "theme_definition": self.themes.get(packet["primary_theme_id"]),
                "retrieval": {"available": True, "operations": ["finding_ids", "query"],
                              "note": "search the complete registry; all results retain their IDs"}}

    def retrieve(self, requests, limit=12):
        ids = set()
        for req in requests:
            if req.get("finding_ids"):
                if set(req["finding_ids"]) - set(self.findings):
                    raise ValueError("unknown retrieval ID")
                ids.update(req["finding_ids"])
            elif req.get("query"):
                terms = req["query"].casefold().split()
                hits = [fid for fid, f in self.findings.items() if all(t in canonical(
                    {"finding": f, "context": self.contexts.get(f.get("context_id"))}).casefold() for t in terms)]
                if len(hits) > limit:
                    raise ValueError("retrieval query too broad; narrow the query")
                ids.update(hits)
            else:
                raise ValueError("empty retrieval request")
        if len(ids) > limit:
            raise ValueError("retrieval exceeds finding limit")
        return sorted(ids)


def compact_proposition(p):
    """A complete short assertion plus anchors; full qualifiers remain retrievable in the registry."""
    return {k: p[k] for k in ("proposition_id", "assertion", "type", "supporting_finding_ids",
                              "conflicting_finding_ids", "appraised_finding_ids", "source_item_ids",
                              "primary_theme_id", "reconciliation_issue_ids") if k in p}


def projected_a07(cfg, n_findings, n_items=None):
    """Conservative planning envelope, not measured model performance; no cache savings assumed."""
    size = cfg.get("max_findings_per_group", 24)
    # Up to eight primary themes plus an unmapped bucket introduce at most eight partial packets.
    items = n_items if n_items is not None else n_findings
    groups = math.ceil(n_findings / size) + min(max(n_findings - 1, 0), 8) + math.ceil(items / cfg.get("max_items_per_group", 8))
    props = groups * cfg.get("max_propositions_per_group", 12)
    reconciles = math.ceil(props / cfg.get("reconcile_page_size", 32))
    limits = cfg.get("output_limits", {"PLAN": 4000, "GROUP": 12000, "RECONCILE": 6000, "FINAL": 6000})
    retrieval = cfg.get("max_retrieval_rounds", 2)
    calls = 2 + (groups + reconciles) * (1 + retrieval)
    output = limits["PLAN"] + limits["FINAL"] + (1 + retrieval) * (groups * limits["GROUP"] + reconciles * limits["RECONCILE"])
    # Serialized-size assumptions, not a strict bound on arbitrarily long source strings. Admission
    # and reservations use actual request bytes once the registry exists. Keep this labelled estimated.
    plan_input = 8000 + n_findings * 360
    group_input = (1 + retrieval) * (groups * 8000 + n_findings * 1300 + items * 1000 + groups * retrieval * 12 * 1300)
    reconcile_input = (1 + retrieval) * reconciles * (8000 + props * 600 + retrieval * 12 * 1300)
    final_input = 8000 + props * 600
    return {"calls": calls, "output_tokens": output, "input_tokens": plan_input + group_input + reconcile_input + final_input,
            "groups": groups, "reconcile_pages": reconciles}
