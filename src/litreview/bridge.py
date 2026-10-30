"""Evidence-to-manuscript bridge: pure functions between the approved A07 package and the writing agents.

No model call, no network, no file write. Every function here takes data and returns data, so the same inputs
always give byte-identical outputs (tests/test_bridge.py checks this, and that no provider is reached).

What the bridge does NOT do is the whole point of it:
  * It never writes, shortens, merges or paraphrases a scientific statement. Every assertion, statement,
    qualifier and contradiction it passes on is a deep copy of A07's (or A06's) value, byte for byte.
    "Compression" means leaving out fields code can rejoin, and referring to elements by ID.
  * A grouping is an instruction ("discuss P12, P14 and P15 together"), never a merged claim. The packet for a
    group carries every member's full record and the union of their qualifications, so one hedged member
    keeps its hedge.
  * It never drops contrary or negative evidence, and never restricts a packet to evidence that agrees with
    its section: whatever contradicts an element in a section travels with that section as contrary context.
  * Citation presence is never support: a citation is allowed in a sentence only through the elements that
    sentence is tagged with.

Element IDs are A07's: proposition_id (propositions), gap_id (knowledge gaps), id (adopted author
interpretations, AI...). The allocation ledger gives every element exactly one outcome:
  DISCUSSED                   written individually, in one section
  GROUPED_WITH                written together with the listed elements, in one section, as one passage
  TABLE_ONLY                  shown only in the comparative table (every finding behind it is a table row)
  NOT_INDIVIDUALLY_DISCUSSED  not written individually; a reason is required
Mandatory elements may be DISCUSSED or GROUPED_WITH only (see `mandatory_reasons`).
"""
from __future__ import annotations

import copy
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from .evidence import role_allowed, status_of
from .synthesis_registry import canonical, fingerprint
from .tools import tags
from .tools.display_items import NOT_REPORTED, _ctx, _quantities, _relation

OUTCOMES = ("DISCUSSED", "GROUPED_WITH", "TABLE_ONLY", "NOT_INDIVIDUALLY_DISCUSSED")
WRITTEN = ("DISCUSSED", "GROUPED_WITH")
PROMINENCE_RANK = {"HEADLINE": 0, "NARRATIVE_PRIMARY": 1, "NARRATIVE_SUPPORTING": 2, "DISPLAY": 3, "SUPPLEMENTARY": 4}
# Finding fields left out of packets (rejoinable by finding ID): the source quotation (supplied on request through
# retrieval) and Gate 1's per-check detail. Gate 1's verdict and the source/finding fingerprints stay
# (`finding_record`), as do the span-correction history, eligibility status and its reason.
FINDING_AUDIT_FIELDS = ("span",)
GATE1_KEEP = ("passed", "source_fingerprint", "finding_fingerprint")
TABLE_COLUMNS = ["Evidence level", "System", "Intervention", "Key observation", "Role and contrary evidence",
                 "Limitation", "Citation"]
CLASS_ORDER = ("CLINICAL", "PRECLINICAL", "BIOCHEMICAL")
CLASS_LABEL = {"CLINICAL": "Clinical", "PRECLINICAL": "Preclinical", "BIOCHEMICAL": "Biochemical", None: "Not reported"}


class BridgeError(ValueError):
    """The bridge cannot build a faithful handoff (stale evidence, unknown IDs, an impossible table). The stage
    stops; nothing is dropped or guessed to make it fit."""


# ------------------------------------------------------------------ elements and mandatory status
def elements(pkg: dict) -> dict[str, dict]:
    """Every element the ledger must account for: {id: {"kind", "record"}} (records are the package's own)."""
    out: dict[str, dict] = {}

    def add(eid, kind, rec):
        if not eid:
            raise BridgeError(f"{kind} without an ID")
        if eid in out:
            raise BridgeError(f"duplicate element ID {eid}")
        out[eid] = {"kind": kind, "record": rec}
    for p in pkg.get("propositions") or []:
        add(p.get("proposition_id"), "PROPOSITION", p)
    for g in pkg.get("knowledge_gaps") or []:
        add(g.get("gap_id"), "GAP", g)
    for a in pkg.get("author_interpretations") or []:
        add(a.get("id"), "AUTHOR_INTERPRETATION", a)
    return out


def _links(rec: dict) -> list[dict]:
    return [x for x in rec.get("evidence") or [] if isinstance(x, dict) and x.get("finding_id")]


def _finding_ids(rec: dict) -> list[str]:
    """Findings an element rests on: its evidence links, or a gap's established_by."""
    ids = [x["finding_id"] for x in _links(rec)] + list(rec.get("established_by") or [])
    return list(dict.fromkeys(ids))


def _source_items(rec: dict) -> list[str]:
    return list(dict.fromkeys(list(rec.get("source_item_ids") or []) + list(rec.get("satisfies") or [])))


def mandatory_reasons(pkg: dict, corpus: list[dict]) -> dict[str, list[str]]:
    """Why each element must be written in prose (empty list: not mandatory). An element is mandatory when it
    carries a conflict (conflicting evidence, a CONFLICT item, a global reconciliation contradiction), contrary
    CORE evidence (a finding from a CORE paper flagged as contrary evidence), a researcher-verified inconsistency,
    a system gap, or any other coverage item A07's manifest requires at NARRATIVE visibility."""
    recs = {r["record_id"]: r for r in corpus}
    items = {i: (s or {}).get("item") or {} for i, s in (pkg.get("source_items") or {}).items()}
    coverage = {c["manifest_item_id"]: c for c in pkg.get("coverage_realization") or []}
    satisfied_by = defaultdict(list)
    for c in coverage.values():
        if c.get("satisfied_by"):
            satisfied_by[c["satisfied_by"]].append(c["manifest_item_id"])
    out = {}
    for eid, el in elements(pkg).items():
        rec, why = el["record"], set()
        for iid in _source_items(rec) + satisfied_by.get(eid, []):
            item = items.get(iid, {})
            kind = item.get("kind")
            vis = item.get("required_visibility") or (coverage.get(iid) or {}).get("required_visibility")
            if kind == "CONFLICT":
                why.add("CONFLICT_ITEM")
            if kind == "SYSTEM_GAP":
                why.add("SYSTEM_GAP")
            if kind in ("IN_PAPER_CONFLICT", "SOURCE_INCONSISTENCY") and item.get("researcher_verified"):
                why.add("RESEARCHER_VERIFIED_INCONSISTENCY")
            if vis == "NARRATIVE":
                why.add(f"NARRATIVE_VISIBILITY:{kind or 'ITEM'}")
        if el["kind"] == "PROPOSITION":
            if rec.get("conflicting_finding_ids"):
                why.add("CONFLICTING_EVIDENCE")
            if rec.get("reconciliation_issue_ids"):
                why.add("RECONCILIATION_CONTRADICTION")
            for fid in _finding_ids(rec):
                r = recs.get(fid.split(":")[0]) or {}
                if r.get("tier") == "CORE" and r.get("is_contrary_evidence"):
                    why.add("CONTRARY_CORE_FINDING")
        if el["kind"] == "GAP" and str(rec.get("type") or "").upper() == "SYSTEM_GAP":
            why.add("SYSTEM_GAP")
        out[eid] = sorted(why)
    return out


# ------------------------------------------------------------------ contradictions
def contradictions(pkg: dict) -> list[dict]:
    """Known contradictions, found by code only: a finding one proposition uses as SUPPORTING and another as
    CONFLICTING, and every global reconciliation issue (copied verbatim). Discovery of new contradictions is a
    model's job (A07 RECONCILE, A10 GLOBAL); this only keeps the known ones visible."""
    roles = defaultdict(lambda: defaultdict(list))
    for p in pkg.get("propositions") or []:
        for x in _links(p):
            roles[x["finding_id"]][x.get("role")].append(p["proposition_id"])
    out = [{"kind": "SHARED_FINDING_OPPOSITE_ROLES", "finding_id": fid,
            "supporting_proposition_ids": sorted(r["SUPPORTING"]), "conflicting_proposition_ids": sorted(r["CONFLICTING"])}
           for fid, r in sorted(roles.items()) if r.get("SUPPORTING") and r.get("CONFLICTING")]
    out += [{"kind": "RECONCILIATION_ISSUE", "issue": copy.deepcopy(i)} for i in pkg.get("reconciliation") or []]
    return out


def _contrary_of(pkg: dict) -> dict[str, set[str]]:
    """element -> elements that contradict it (both directions)."""
    out = defaultdict(set)
    for c in contradictions(pkg):
        ids = (c["supporting_proposition_ids"] + c["conflicting_proposition_ids"]
               if c["kind"] == "SHARED_FINDING_OPPOSITE_ROLES" else list(c["issue"].get("proposition_ids") or []))
        for a in ids:
            out[a] |= set(ids) - {a}
    return out


# ------------------------------------------------------------------ the global argument map
def argument_map(pkg: dict, corpus: list[dict], findings: list[dict] | None = None) -> dict:
    """One global map of the argument. Every text value is copied from A07's output; counts come from the
    registry (`global_independence`). The list of identity-unknown finding IDs is replaced by its length
    (the IDs stay in the package). With findings, each approved theme lists the subthemes A05 assigned to the
    findings its propositions rest on (verbatim, sorted)."""
    decision = pkg.get("researcher_decision") or {}
    chosen = decision.get("selected_thesis")
    option = next((copy.deepcopy(t) for t in pkg.get("thesis_options") or [] if t.get("option_id") == chosen), None)
    props = pkg.get("propositions") or []
    by_theme = defaultdict(list)
    for p in props:
        by_theme[p.get("primary_theme_id")].append(p["proposition_id"])
    fw = pkg.get("theme_framework") or {}
    fby = {f["finding_id"]: f for f in findings or []}
    subthemes = defaultdict(set)
    for p in props:
        for fid in _finding_ids(p):
            subthemes[p.get("primary_theme_id")] |= {s for s in (fby.get(fid) or {}).get("subthemes") or []
                                                     if isinstance(s, str)}
    themes = [{"theme": copy.deepcopy(t), "proposition_ids": by_theme.get(t.get("theme_id"), []),
               "subthemes": sorted(subthemes.get(t.get("theme_id"), ()))}
              for t in fw.get("primary_themes") or []]
    if by_theme.get("UNMAPPED"):
        themes.append({"theme": {"theme_id": "UNMAPPED", "name": "Unmapped (administrative bucket, not a theme)"},
                       "proposition_ids": by_theme["UNMAPPED"]})
    independence = copy.deepcopy(pkg.get("global_independence") or {})
    if "identity_unknown_findings" in independence:
        independence["identity_unknown_findings_count"] = len(independence.pop("identity_unknown_findings"))
    mandatory = mandatory_reasons(pkg, corpus)
    return {
        "notice": "Copied from the approved A07 package. Not evidence by itself: write from section packets.",
        "thesis": {"selected_thesis": copy.deepcopy(chosen), "option": option},
        "themes": themes,
        "major_propositions": [{k: copy.deepcopy(p.get(k)) for k in ("proposition_id", "assertion", "type",
                                                                      "prominence", "primary_theme_id")}
                               for p in props if p.get("prominence") in ("HEADLINE", "NARRATIVE_PRIMARY")],
        "contradictions": contradictions(pkg),
        "knowledge_gaps": [{k: copy.deepcopy(g.get(k)) for k in ("gap_id", "type", "statement")}
                           for g in pkg.get("knowledge_gaps") or []],
        "author_interpretations": copy.deepcopy(pkg.get("author_interpretations") or []),
        "study_independence": independence,
        "mandatory_element_ids": sorted(e for e, why in mandatory.items() if why),
    }


def element_index(pkg: dict, corpus: list[dict], table_ids: set[str] | None = None) -> list[dict]:
    """One line per element for A08: ID, verbatim assertion/statement, and what A08 needs to allocate it
    (prominence, theme, papers, mandatory reasons, whether the comparative table already shows all of it)."""
    mandatory = mandatory_reasons(pkg, corpus)
    contrary = _contrary_of(pkg)
    out = []
    for eid, el in elements(pkg).items():
        r = el["record"]
        line = {"id": eid, "kind": el["kind"],
                "text": copy.deepcopy(r.get("assertion") if el["kind"] == "PROPOSITION" else r.get("statement")),
                "mandatory_reasons": mandatory[eid]}
        if el["kind"] == "PROPOSITION":
            line.update(type=r.get("type"), prominence=r.get("prominence"), primary_theme_id=r.get("primary_theme_id"),
                        citation_record_ids=copy.deepcopy(r.get("citation_record_ids") or []),
                        has_conflicting_evidence=bool(r.get("conflicting_finding_ids")),
                        appraised=bool(r.get("appraised_finding_ids")),
                        contradicted_by=sorted(contrary.get(eid, ())),
                        table_shows_all_evidence=eid in (table_ids or set()))
        elif el["kind"] == "GAP":
            line.update(type=r.get("type"), citation_record_ids=copy.deepcopy(r.get("citation_record_ids") or []))
        else:
            line.update(premise_proposition_ids=copy.deepcopy(r.get("premise_proposition_ids") or []))
        out.append(line)
    return out


# ------------------------------------------------------------------ the single comparative table
def evidence_class(f: dict) -> str | None:
    """CLINICAL, PRECLINICAL or BIOCHEMICAL from the finding's A05 evidence system; None when the system is not
    reported or not applicable (stated, never inferred)."""
    s = str((f.get("context") or {}).get("evidence_system") or "").upper()
    if not s or s.startswith("NOT_"):
        return None
    if "HUMAN_" in s:
        return "CLINICAL"
    if "CELL_FREE" in s:
        return "BIOCHEMICAL"
    if any(k in s for k in ("IN_VITRO", "IN_VIVO", "EX_VIVO")):
        return "PRECLINICAL"
    return None


TABLE_RULE = (
    "The table is a selective synthesis of the most important evidence, not an inventory of every finding. Rows are "
    "eligible findings (A06 status SUPPORTING) that an approved proposition uses as SUPPORTING or CONFLICTING "
    "evidence; appraisal-only and ineligible findings never appear, and findings whose evidence system is not "
    "reported appear only as contrary evidence. Contrary evidence is a finding used as CONFLICTING evidence or named, "
    "with others, by a global reconciliation issue; every contrary finding is treated as material unless the "
    "researcher approves a justified exclusion. (1) Contrary findings come first, clinical before preclinical before "
    "biochemical. (2) Other rows rotate over clinical, preclinical and biochemical evidence; within a class, findings "
    "behind higher-prominence propositions come first, then findings used by more propositions, then findings from "
    "papers flagged as contrary evidence, then finding ID; at most one such row per paper. (3) No claim is shown "
    "without its contrary evidence: a supporting row enters only together with every contrary finding of the "
    "propositions it supports and every finding sharing a reconciliation issue with it; if they do not all fit, the "
    "row is left out. The role column links rows for and against the same claim by a set letter, and says when "
    "further contrary evidence is discussed in the text. The table stops at max_rows (one page). Contrary "
    "findings that do not fit stay in the contrary-evidence register: each must be carried by a written element, "
    "rendered in cited, A10-verified prose, or excluded by the researcher with a recorded justification "
    "(CP_CONTRARY) before release.")
# Context fields compared for a contradiction pair, so that disagreement across different systems, lines, doses or
# arms is never presented as like-for-like. Values stay in the findings themselves; the record names the fields.
COMPARABILITY_KEYS = ("evidence_system", "species", "cell_line_or_type", "primary_or_immortalized", "strain",
                      "model_type", "population", "idh_status", "mgmt_status", "agent", "dose_or_concentration",
                      "route", "duration", "frequency", "comparator", "setting", "endpoint", "assay", "readout",
                      "timepoint")


def _relations(pkg: dict, by_id: dict) -> tuple[dict, dict, set]:
    """(uses, partners, issue_findings). uses: eligible finding -> [(proposition, role)] for SUPPORTING and
    CONFLICTING links; partners: finding -> the contrary findings that must be shown with it (the CONFLICTING
    findings of the propositions it supports, and every finding sharing a reconciliation issue with it)."""
    uses = defaultdict(list)
    for p in pkg.get("propositions") or []:
        for x in _links(p):
            f = by_id.get(x["finding_id"])
            if x.get("role") in ("SUPPORTING", "CONFLICTING") and f is not None and status_of(f) == "SUPPORTING":
                uses[x["finding_id"]].append((p, x["role"]))
    partners = defaultdict(set)
    for p in pkg.get("propositions") or []:
        sup = [x["finding_id"] for x in _links(p) if x.get("role") == "SUPPORTING" and x["finding_id"] in uses]
        con = [x["finding_id"] for x in _links(p) if x.get("role") == "CONFLICTING" and x["finding_id"] in uses]
        for s in sup:
            partners[s] |= set(con)
    issue_findings = set()
    for i in pkg.get("reconciliation") or []:
        ids = {f for f in i.get("finding_ids") or [] if f in uses}
        issue_findings |= ids
        for f in ids:
            partners[f] |= ids - {f}
    return uses, partners, issue_findings


def _label(n: int) -> str:
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def comparative_table(pkg: dict, findings: list[dict], corpus: list[dict], max_rows: int = 25) -> dict:
    """The review's single display item, built by code. Each cell is copied from the finding (context fields,
    entity mentions, quantities, constraints, attribution); each row is tagged with the propositions that use
    the finding, so A10 verifies cells and citations like prose."""
    by_id = {f["finding_id"]: f for f in findings}
    recs = {r["record_id"]: r for r in corpus}
    uses, partners, issue_findings = _relations(pkg, by_id)

    def contrary(fid):
        return any(role == "CONFLICTING" for _, role in uses[fid]) or fid in issue_findings

    def rank(fid):
        return (min(PROMINENCE_RANK.get(p.get("prominence"), 9) for p, _ in uses[fid]), -len(uses[fid]),
                not (recs.get(by_id[fid]["record_id"]) or {}).get("is_contrary_evidence"), _natural(fid))

    def cls(fid):
        c = evidence_class(by_id[fid])
        return CLASS_ORDER.index(c) if c else 9

    contrary_ids = sorted((f for f in uses if contrary(f)), key=lambda f: (cls(f), rank(f)))
    chosen, picked = [], set()

    def take(unit, why):
        new = [f for f in unit if f not in picked]
        if len(chosen) + len(new) > max_rows:
            return False
        for f in new:
            picked.add(f)
            chosen.append((f, why if f == unit[0] else f"shown with {unit[0]} (its contrary evidence)"))
        return True
    for f in contrary_ids:
        take([f] + sorted(partners[f] - {f}, key=_natural), "contrary evidence")
    papers = {by_id[f]["record_id"] for f in picked}
    pools = {c: sorted((f for f in uses if f not in picked and evidence_class(by_id[f]) == c), key=rank)
             for c in CLASS_ORDER}
    while len(chosen) < max_rows and any(pools.values()):
        for c in CLASS_ORDER:
            while pools[c] and (by_id[pools[c][0]]["record_id"] in papers or pools[c][0] in picked):
                pools[c].pop(0)
            if pools[c] and len(chosen) < max_rows:
                fid = pools[c].pop(0)
                if take([fid] + sorted(partners[fid] - {fid}, key=_natural), f"{CLASS_LABEL[c].lower()} evidence"):
                    papers.add(by_id[fid]["record_id"])
    shown = [fid for fid, _ in chosen]
    covered = sorted(p["proposition_id"] for p in pkg.get("propositions") or []
                     if [x for x in _links(p) if x.get("role") in ("SUPPORTING", "CONFLICTING")]
                     and all(x["finding_id"] in picked for x in _links(p) if x.get("role") in ("SUPPORTING", "CONFLICTING"))
                     and not p.get("appraised_finding_ids"))
    # rows for and against the same claim share a set letter (connected through `partners`, both directions)
    parent = {f: f for f in shown}

    def root(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f
    for s in shown:
        for c in partners[s] & picked:
            parent[root(c)] = root(s)
    members = defaultdict(list)
    for f in shown:
        members[root(f)].append(f)
    letters = {}
    for f in shown:
        r = root(f)
        if len(members[r]) > 1 and r not in letters:
            letters[r] = _label(len(letters))
    against = _contrary_of(pkg)
    props = {p["proposition_id"]: p for p in pkg.get("propositions") or []}
    unshown_contrary = set(contrary_ids) - picked
    rows, selection = [], []
    for fid, why in chosen:
        f = by_id[fid]
        pids = sorted({p["proposition_id"] for p, _ in uses[fid]}, key=_natural)
        roles = sorted({role.lower() for _, role in uses[fid]})
        ctx = f.get("context") or {}
        system = "; ".join(x for x in (ctx.get("evidence_system"), _first(ctx, "cell_line_or_type", "species", "population"))
                           if x and x != "NOT_REPORTED") or NOT_REPORTED
        subject = ((f.get("entities") or {}).get(f.get("subject") or "") or {}).get("mention")
        intervention = "; ".join(x for x in (subject, ctx.get("agent"), ctx.get("dose_or_concentration"))
                                 if x and x != "NOT_REPORTED") or NOT_REPORTED
        quantities = _quantities(f)
        observation = _relation(f) + ("" if quantities == NOT_REPORTED else f" ({quantities})")
        limits = list(f.get("constraints") or []) or ([f["plain_language_limit"]] if f.get("plain_language_limit") else [])
        if f.get("attributed_to"):
            limits.append(f"Attributed to: {f['attributed_to']}")
        if f.get("modality") and f.get("modality") != "ASSERTED":
            limits.append(f"Modality: {f['modality']}")
        if f.get("assertion_type") == "AUTHORS_INTERPRETATION":
            limits.append("Authors' interpretation, not an observed result")
        letter = letters.get(root(fid))
        # further contrary evidence for this row's claims outside the table: a contrary finding of a proposition the
        # row's propositions are contradicted by, or one of their own, that is not shown
        further = any(x["finding_id"] in unshown_contrary for p in pids for q in {p} | against.get(p, set())
                      for x in _links(props.get(q) or {}) if x.get("role") in ("SUPPORTING", "CONFLICTING"))
        if contrary(fid):
            link = f"contrary evidence, set {letter}" if letter else "contrary evidence; the claim it challenges is discussed in the text"
        else:
            link = f"contrary evidence shown in set {letter}" if letter else "no contrary evidence identified in this review"
        if further:
            link += "; further contrary evidence is discussed in the text"
        rows.append([CLASS_LABEL[evidence_class(f)], system, intervention,
                     f"{observation} ⟦{','.join(pids)}⟧", f"{' / '.join(roles)}; {link}",
                     "; ".join(limits) or "None recorded", f"[@{f['record_id']}]"])
        selection.append({"finding_id": fid, "reason": why, "proposition_ids": pids,
                          "contrary_set": letter, "further_contrary_in_text": further})
    return {"display_id": "T1", "kind": "TABLE", "type": "TABLE_COMPARISON", "status": "BUILT" if rows else "EMPTY",
            "columns": list(TABLE_COLUMNS), "rows": rows, "row_finding_ids": shown,
            "row_selection": selection, "selection_rule": TABLE_RULE, "max_rows": max_rows,
            "contrary_finding_ids": contrary_ids,
            "contrary_findings_not_shown": [f for f in contrary_ids if f not in picked],
            "eligible_papers": len({by_id[f]["record_id"] for f in uses}),
            "eligible_findings_not_shown": len(uses) - len(chosen),
            "propositions_fully_shown": covered,
            "warnings": [] if rows else ["no eligible finding is used by an approved proposition"]}


def reader_table(table: dict, corpus: list[dict], discussed_in: list[str] | None = None) -> dict:
    """The table as the reader, A10 and the export see it: columns, tagged rows and notes. The notes state that the
    rows are a rule-based selection, how many eligible findings and papers they were drawn from, how rows for and
    against a claim are linked, and where contrary evidence that did not fit is discussed (discussed_in: headings of
    the sections whose written elements carry it, from the approved plan). Selection bookkeeping (row reasons,
    counts, IDs) stays in the full table record (data/display_items/T1.json), so it never becomes reader-facing text
    to verify."""
    eligible = len(table.get("row_finding_ids") or []) + int(table.get("eligible_findings_not_shown") or 0)
    papers = int(table.get("eligible_papers") or 0)
    hidden = len(table.get("contrary_findings_not_shown") or [])
    notes = [f"The rows are a selection by a fixed rule from {eligible} eligible findings in {papers} papers, not a "
             "summary of every study reviewed. A supporting row appears only together with the contrary evidence for "
             "the claims it supports; rows sharing a set letter in the role column report evidence for and against "
             "the same claim and may differ in system, dose or treatment arm."]
    if hidden:
        where = f", in: {'; '.join(discussed_in)}" if discussed_in else ""
        notes.append(f"{hidden} further contrary findings are discussed in the text rather than shown here{where}.")
    out = {k: copy.deepcopy(table.get(k)) for k in ("display_id", "kind", "type", "columns", "rows", "row_finding_ids",
                                                     "inconsistency_notes") if table.get(k) is not None}
    out["notes"] = notes
    return out


# ------------------------------------------------------------------ the contrary-evidence register
def carriers(pkg: dict) -> dict[str, set[str]]:
    """finding -> the elements that carry it into prose: every element whose evidence or established_by names it,
    and every proposition of a reconciliation issue that names it."""
    out = defaultdict(set)
    for eid, el in elements(pkg).items():
        for fid in _finding_ids(el["record"]) + list(el["record"].get("conflicting_finding_ids") or []):
            out[fid].add(eid)
    for i in pkg.get("reconciliation") or []:
        for fid in i.get("finding_ids") or []:
            out[fid] |= set(i.get("proposition_ids") or [])
    return out


def comparability(a: dict, b: dict) -> dict:
    """Which context fields of two findings differ, or are not reported for one of them (COMPARABILITY_KEYS).
    Names only: the values are the findings' own, verbatim, in the packet. Nothing is judged comparable here; the
    record says where an apparent disagreement may come from different systems, lines, doses or arms."""
    ca, cb = a.get("context") or {}, b.get("context") or {}
    missing = lambda v: v in (None, "", [], {}) or str(v).strip().upper() in ("NOT_REPORTED", "NOT_APPLICABLE")
    differs, unreported = [], []
    for k in COMPARABILITY_KEYS:
        va, vb = ca.get(k), cb.get(k)
        if missing(va) and missing(vb):
            continue
        if missing(va) or missing(vb):
            unreported.append(k)
        elif canonical(va) != canonical(vb):
            differs.append(k)
    return {"differs": differs, "not_reported_for_one": unreported,
            "evidence_class": [evidence_class(a), evidence_class(b)]}


def contrary_register(pkg: dict, findings: list[dict], table: dict, plan: dict | None = None,
                      ledger: list[dict] | None = None) -> list[dict]:
    """Every contrary finding (the table's contrary_finding_ids), in the table's order: whether the table shows it,
    why it is contrary, the elements that carry it, the supporting findings it challenges with a comparability
    record for each pair, and (with an approved plan) the written elements and sections that carry it. Every entry
    is material unless the researcher approves a justified exclusion at release (CP_CONTRARY)."""
    by_id = {f["finding_id"]: f for f in findings}
    uses, partners, issue_findings = _relations(pkg, by_id)
    carry = carriers(pkg)
    shown = set(table.get("row_finding_ids") or [])
    written, where = set(), {}
    if plan is not None and ledger is not None:
        written = {e["item_id"] for e in ledger if e.get("outcome") in WRITTEN}
        where = {it["item_id"]: s["section_id"] for s in plan.get("sections") or [] for it in s.get("ordered_items") or []}
    out = []
    for fid in table.get("contrary_finding_ids") or []:
        reasons = sorted({f"CONFLICTING_EVIDENCE_IN:{p['proposition_id']}" for p, role in uses[fid] if role == "CONFLICTING"}
                         | {f"RECONCILIATION_ISSUE:{i.get('issue_id')}" for i in pkg.get("reconciliation") or []
                            if fid in (i.get("finding_ids") or [])}, key=_natural)
        challenged = sorted((s for s, cs in partners.items() if fid in cs and s != fid), key=_natural)
        entry = {"finding_id": fid, "record_id": by_id[fid]["record_id"], "in_table": fid in shown,
                 "reasons": reasons, "carried_by": sorted(carry.get(fid, ()), key=_natural),
                 "challenges": [{"finding_id": s, "in_table": s in shown,
                                 "proposition_ids": sorted({p["proposition_id"] for p, role in uses[s] if role == "SUPPORTING"},
                                                           key=_natural),
                                 **comparability(by_id[fid], by_id[s])} for s in challenged]}
        if plan is not None and ledger is not None:
            entry["written_by"] = sorted(set(entry["carried_by"]) & written, key=_natural)
            entry["sections"] = sorted({where[e] for e in entry["written_by"] if e in where}, key=_natural)
        out.append(entry)
    return out


def contrary_problems(register: list[dict], table: dict) -> list[str]:
    """Structural rule for the plan: a contrary finding the table does not show must be carried by at least one
    element the plan writes; a supporting row may never be shown while a finding contrary to it is not."""
    problems = []
    shown = set(table.get("row_finding_ids") or [])
    for e in register:
        if not e["in_table"] and not e.get("written_by"):
            problems.append(f"CONTRARY_NOT_CARRIED: {e['finding_id']} is not in the table and no written element "
                            f"carries it (carriers: {e['carried_by'] or 'none'})")
        if not e["in_table"]:
            for c in e["challenges"]:
                if c["finding_id"] in shown:
                    problems.append(f"TABLE_CONCEALS_CONTRARY: row {c['finding_id']} is shown without its contrary "
                                    f"finding {e['finding_id']}")
    return problems


def contrary_accounting(register: list[dict], report: dict, table: dict | None,
                        exclusions: dict[str, str] | None = None) -> dict:
    """The release gate's account of every contrary finding against the final A10 report:
      SHOWN_IN_TABLE      a row of the final table;
      ADDRESSED_IN_PROSE  at least one body sentence A10 VERIFIED that is tagged with an element carrying the
                          finding and cites its paper (whether A10 named the finding itself is recorded);
      EXCLUSION_APPROVED  excluded by the researcher with a recorded justification (CP_CONTRARY);
      UNADDRESSED         none of these: blocks release.
    Also re-checks the table: no supporting row without its contrary findings."""
    verdicts = {v["occurrence_id"]: v for v in report.get("verdicts") or []}
    body = [o for o in report.get("occurrence_inventory") or [] if o.get("path", [])[:2] == ["manuscript", "sections"]
            and (verdicts.get(o["occurrence_id"]) or {}).get("verdict") == "VERIFIED"]
    rows = set((table or {}).get("row_finding_ids") or [])
    exclusions = exclusions or {}
    entries, blocking = [], []
    for e in register:
        fid, carry = e["finding_id"], set(e.get("carried_by") or [])
        hits = [o for o in body if e["record_id"] in (o.get("citation_record_ids") or []) and carry & set(o.get("item_ids") or [])]
        if fid in rows:
            status = "SHOWN_IN_TABLE"
        elif hits:
            status = "ADDRESSED_IN_PROSE"
        elif str(exclusions.get(fid) or "").strip():
            status = "EXCLUSION_APPROVED"
        else:
            status = "UNADDRESSED"
            blocking.append(fid)
        entries.append({"finding_id": fid, "record_id": e["record_id"], "status": status,
                        "occurrence_ids": [o["occurrence_id"] for o in hits],
                        "named_by_a10": any(fid in (verdicts[o["occurrence_id"]].get("evidence_finding_ids") or [])
                                            for o in hits),
                        **({"justification": exclusions[fid]} if status == "EXCLUSION_APPROVED" else {})})
    concealed = [f"{c['finding_id']} shown without {e['finding_id']}" for e in register if e["finding_id"] not in rows
                 for c in e["challenges"] if c["finding_id"] in rows]
    return {"entries": entries, "unaddressed": blocking, "table_conceals": concealed,
            "counts": {s: sum(1 for x in entries if x["status"] == s)
                       for s in ("SHOWN_IN_TABLE", "ADDRESSED_IN_PROSE", "EXCLUSION_APPROVED", "UNADDRESSED")},
            "release_blocked": bool(blocking or concealed)}


def _first(ctx: dict, *keys: str) -> str | None:
    return next((ctx[k] for k in keys if ctx.get(k) and ctx[k] != "NOT_REPORTED"), None)


def _natural(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ------------------------------------------------------------------ plan and ledger validation
def validate_plan(plan: dict, ledger: list[dict], pkg: dict, corpus: list[dict], table: dict | None,
                  journal: dict, cfg: dict, findings: list[dict] | None = None) -> tuple[list[str], dict]:
    """Every structural rule of the plan and the allocation ledger, checked by code. Returns (problems, report);
    any problem rejects the plan (there is no automatic repair). The report records the theme-to-section
    mapping, outcome counts and every mandatory element's placement. With findings and a built table, the
    contrary-evidence register is checked too: every contrary finding the table does not show must be carried by
    a written element (`contrary_problems`)."""
    problems: list[str] = []
    els = elements(pkg)
    mandatory = mandatory_reasons(pkg, corpus)
    sections = plan.get("sections") or []
    sids = [s.get("section_id") for s in sections]
    if len(set(sids)) != len(sids) or not all(sids):
        problems.append("SECTION_IDS: section IDs must be present and unique")
    order = plan.get("writing_order") or []
    if sorted(order) != sorted(sids):
        problems.append("WRITING_ORDER: writing_order must list every section exactly once")
    placed: dict[str, tuple[str, str | None]] = {}          # id -> (section, group)
    groups: dict[str, list[str]] = defaultdict(list)
    for s in sections:
        for it in s.get("ordered_items") or []:
            iid = it.get("item_id")
            if iid not in els:
                problems.append(f"UNKNOWN_ITEM: {iid} in {s.get('section_id')} is not an approved element")
                continue
            if iid in placed:
                problems.append(f"PLACED_TWICE: {iid} appears in more than one plan item")
            placed[iid] = (s.get("section_id"), it.get("group"))
            if it.get("group"):
                groups[it["group"]].append(iid)
    by_id = {}
    for e in ledger:
        eid = e.get("item_id")
        if eid in by_id:
            problems.append(f"LEDGER_DUPLICATE: {eid}")
        by_id[eid] = e
    for eid in sorted(set(by_id) - set(els)):
        problems.append(f"LEDGER_UNKNOWN: {eid} is not an approved element")
    for eid in sorted(set(els) - set(by_id), key=_natural):
        problems.append(f"LEDGER_MISSING: {eid} has no outcome")
    max_group = int(cfg.get("max_group_size", 16))
    for g, members in groups.items():
        if len(members) < 2:
            problems.append(f"GROUP_SINGLETON: group {g} has one member")
        if len(members) > max_group:
            problems.append(f"GROUP_TOO_LARGE: group {g} has {len(members)} members (max {max_group})")
        if len({placed[m][0] for m in members}) > 1:
            problems.append(f"GROUP_SPLIT: group {g} spans sections")
    table_shown = set((table or {}).get("propositions_fully_shown") or [])
    for eid, e in by_id.items():
        if eid not in els:
            continue
        out = e.get("outcome")
        where = placed.get(eid)
        if out not in OUTCOMES:
            problems.append(f"LEDGER_OUTCOME: {eid} has outcome {out!r}")
            continue
        if out in WRITTEN and where is None:
            problems.append(f"LEDGER_NOT_PLACED: {eid} is {out} but in no section")
        if out not in WRITTEN and where is not None:
            problems.append(f"LEDGER_PLACED: {eid} is {out} but placed in {where[0]}")
        if out in WRITTEN and where is not None and e.get("section_id") != where[0]:
            problems.append(f"LEDGER_SECTION: {eid} ledger says {e.get('section_id')}, plan places it in {where[0]}")
        if out == "DISCUSSED" and where is not None and where[1]:
            problems.append(f"LEDGER_GROUP: {eid} is DISCUSSED but placed in group {where[1]}")
        if out == "GROUPED_WITH":
            others = sorted(m for m in groups.get((where or (None, None))[1], []) if m != eid)
            if not where or not where[1]:
                problems.append(f"LEDGER_GROUP: {eid} is GROUPED_WITH but has no group in the plan")
            elif sorted(e.get("grouped_with") or []) != others:
                problems.append(f"LEDGER_GROUP: {eid} grouped_with {sorted(e.get('grouped_with') or [])} "
                                f"differs from its plan group {others}")
        if out == "TABLE_ONLY" and eid not in table_shown:
            problems.append(f"TABLE_ONLY_NOT_SHOWN: {eid}: the comparative table does not show all of its evidence")
        if out == "NOT_INDIVIDUALLY_DISCUSSED" and not str(e.get("reason") or "").strip():
            problems.append(f"LEDGER_REASON: {eid} is NOT_INDIVIDUALLY_DISCUSSED without a reason")
        if mandatory[eid] and out not in WRITTEN:
            problems.append(f"MANDATORY_NOT_WRITTEN: {eid} ({', '.join(mandatory[eid])}) is {out}; mandatory "
                            "elements are DISCUSSED or GROUPED_WITH")
    written = {e for e, x in by_id.items() if x.get("outcome") in WRITTEN and e in els}
    for s in sections:
        for pid in s.get("heading_proposition_ids") or []:
            _claim_binding(pid, f"heading of {s.get('section_id')}", els, written, problems)
    for pid in (plan.get("title") or {}).get("proposition_ids") or []:
        _claim_binding(pid, "title", els, written, problems)
    for pid in (plan.get("abstract_plan") or {}).get("ordered_proposition_ids") or []:
        if pid not in written:
            problems.append(f"ABSTRACT_BINDING: {pid} is not an element written in the body")
    # display items: exactly the code-built comparative table, at most journal display_items_max
    limit = int((journal.get("limits") or {}).get("display_items_max", 1))
    items = plan.get("display_items") or []
    if len(items) > limit or len(items) > 1:
        problems.append(f"DISPLAY_ITEMS: {len(items)} planned; one comparative table is the only display item")
    for d in items:
        if d.get("display_id") != "T1" or d.get("type") != "TABLE_COMPARISON":
            problems.append(f"DISPLAY_ITEMS: {d.get('display_id')} {d.get('type')}: only T1 TABLE_COMPARISON is allowed")
        if d.get("placement_section_id") not in sids:
            problems.append("DISPLAY_ITEMS: T1 must be placed in a planned section")
    if items and (table or {}).get("status") != "BUILT":
        problems.append("DISPLAY_ITEMS: T1 planned but no comparative table could be built")
    # every selected paper cited somewhere: through a written or table-only element, or a table row
    cited = set()
    for eid in by_id:
        if eid in els and by_id[eid].get("outcome") in ("DISCUSSED", "GROUPED_WITH", "TABLE_ONLY"):
            cited |= set(els[eid]["record"].get("citation_record_ids") or [])
    if items:
        cited |= {f.split(":")[0] for f in (table or {}).get("row_finding_ids") or []}
    unplaced = sorted({r["record_id"] for r in corpus} - cited, key=_natural)
    for rid in unplaced:
        problems.append(f"PAPER_NOT_CITED: selected paper {rid} is cited by no written element or table row")
    theme_sections, section_themes = defaultdict(set), defaultdict(set)
    for eid, (sid, _) in placed.items():
        th = els[eid]["record"].get("primary_theme_id") if els[eid]["kind"] == "PROPOSITION" else None
        if th:
            theme_sections[th].add(sid)
            section_themes[sid].add(th)
    register = None
    if findings is not None and table and table.get("status") == "BUILT":
        register = contrary_register(pkg, findings, table, plan, ledger)
        problems += contrary_problems(register, table)
    report = {"outcomes": {o: sorted((e for e, x in by_id.items() if x.get("outcome") == o and e in els), key=_natural)
                           for o in OUTCOMES},
              "counts": {o: sum(1 for x in by_id.values() if x.get("outcome") == o) for o in OUTCOMES},
              "elements": len(els),
              "mandatory": {e: {"reasons": why, "outcome": (by_id.get(e) or {}).get("outcome"),
                                "section_id": (placed.get(e) or (None,))[0]} for e, why in mandatory.items() if why},
              "groups": {g: sorted(m, key=_natural) for g, m in groups.items()},
              "theme_to_sections": {t: sorted(s) for t, s in sorted(theme_sections.items())},
              "section_to_themes": {s: sorted(t) for s, t in sorted(section_themes.items())},
              "papers_not_cited": unplaced}
    if register is not None:
        report["contrary_evidence"] = {
            "in_table": [e["finding_id"] for e in register if e["in_table"]],
            "not_in_table": {e["finding_id"]: {"written_by": e["written_by"], "sections": e["sections"]}
                             for e in register if not e["in_table"]}}
    return problems, report


def _claim_binding(pid, where, els, written, problems):
    el = els.get(pid)
    if el is None:
        problems.append(f"CLAIM_BINDING: {where} binds unknown element {pid}")
        return
    if pid not in written:
        problems.append(f"CLAIM_BINDING: {where} binds {pid}, which the body does not write")
    rec = el["record"]
    if rec.get("type") == "CLAIM_APPRAISAL" or rec.get("appraised_finding_ids"):
        problems.append(f"APPRAISED_AS_ESTABLISHED: {where} binds {pid}, which carries an appraised claim")


# ------------------------------------------------------------------ section packets
# Finding fields that are run administration, not interpretation (theme bookkeeping): left out of packets.
FINDING_ADMIN_FIELDS = ("themes", "subthemes", "emerging", "emerging_note")
# Record fields A07 copied from the findings themselves. A packet omits one only when code can rebuild it exactly
# from the packet's findings table (`rejoin`); otherwise the field stays.
EVIDENCE_QUALIFIER_KEYS = ("direction", "polarity", "modality", "assertion_type", "attributed_to", "context_id",
                           "plain_language_limit")
REJOINABLE = {"context_qualifiers": lambda f: f.get("context"),
              "evidence_qualifiers": lambda f: {k: f.get(k) for k in EVIDENCE_QUALIFIER_KEYS}}


def finding_record(f: dict) -> dict:
    """A finding as a packet carries it: everything needed to interpret it, verbatim (context, entities,
    quantities, constraints, limit, modality, attribution, disposition), without its audit trail (span, Gate 1
    record) or theme bookkeeping, which stay in the run and are joined by finding ID."""
    out = {k: copy.deepcopy(v) for k, v in f.items() if k not in FINDING_AUDIT_FIELDS + FINDING_ADMIN_FIELDS}
    if isinstance(f.get("provenance_gate1"), dict):
        out["provenance_gate1"] = {k: copy.deepcopy(f["provenance_gate1"][k]) for k in GATE1_KEEP
                                   if k in f["provenance_gate1"]}
    out["eligibility_status"] = status_of(f)
    return out


def _check_eligible(eid: str, rec: dict, findings: dict) -> None:
    for x in _links(rec):
        f = findings.get(x["finding_id"])
        if not role_allowed(f, x.get("role")):
            raise BridgeError(f"{eid}: finding {x['finding_id']} is no longer eligible as {x.get('role')} "
                              f"(status {status_of(f) if f else 'MISSING'}); return to synthesis")
    for fid in rec.get("established_by") or []:
        f = findings.get(fid)
        if f is None or status_of(f) != "SUPPORTING":
            raise BridgeError(f"{eid}: gap evidence {fid} is no longer eligible; return to synthesis")


def full_record(eid: str, els: dict, findings: dict, pkg: dict, table: dict | None = None) -> dict:
    """One element as a packet carries it: A07's record (fields rejoinable from the findings omitted, and named in
    `omitted`), the IDs of the findings it rests on, its source items, and for an author interpretation the
    premises it rests on. The findings themselves go into `table` (one copy per packet); with no table they are
    embedded under `findings`. Raises if any finding is no longer eligible for its role."""
    el = els[eid]
    rec = el["record"]
    _check_eligible(eid, rec, findings)
    fids = [f for f in _finding_ids(rec) if f in findings]
    own = {f: finding_record(findings[f]) for f in fids}
    view, omitted = copy.deepcopy(rec), []
    for field, rebuild in REJOINABLE.items():
        value = rec.get(field)
        if isinstance(value, dict) and value and all(f in findings for f in value) and \
                canonical(value) == canonical({f: rebuild(own.get(f) or finding_record(findings[f])) for f in value}):
            view.pop(field)
            omitted.append(field)
    out = {"id": eid, "kind": el["kind"], "record": view, "finding_ids": fids,
           "source_items": {i: copy.deepcopy((pkg.get("source_items") or {})[i])
                            for i in _source_items(rec) if i in (pkg.get("source_items") or {})}}
    if omitted:
        out["omitted"] = {field: sorted(rec[field]) for field in omitted}
    if table is None:
        out["findings"] = own
    else:
        table.update(own)
    if el["kind"] == "AUTHOR_INTERPRETATION":
        out["premises"] = {p: full_record(p, els, findings, pkg, table) for p in rec.get("premise_proposition_ids") or []
                           if p in els}
    return out


def rejoin(full: dict, table: dict | None = None) -> dict:
    """The A07 record a packet entry stands for, rebuilt exactly (tests check byte identity)."""
    findings = full.get("findings") or table or {}
    rec = copy.deepcopy(full["record"])
    for field, ids in (full.get("omitted") or {}).items():
        rec[field] = {f: REJOINABLE[field](findings[f]) for f in ids}
    return rec


def _union(values):
    out = []
    for v in values:
        for x in v or []:
            if x not in out:
                out.append(copy.deepcopy(x))
    return out


def qualifications_union(records: list[dict], table: dict) -> dict:
    """The union of every member's qualifications for a grouped passage. Nothing is resolved or merged: constraints
    and limitations are unioned in order; each finding keeps its own ceiling, context and qualifiers (by finding
    ID, in the packet's findings table); every hedge, attribution and appraisal is listed with its member. One
    hedged member keeps its hedge."""
    findings = lambda r: {f: (r.get("findings") or table)[f] for f in r["finding_ids"]}
    out = {"members": [r["id"] for r in records],
           "constraints": _union(r["record"].get("constraints") for r in records),
           "scientific_limitations": _union(r["record"].get("scientific_limitations") for r in records),
           "reconciliation_issue_ids": _union(r["record"].get("reconciliation_issue_ids") for r in records),
           "citation_record_ids": _union(r["record"].get("citation_record_ids") for r in records),
           "conflicting_finding_ids": _union(r["record"].get("conflicting_finding_ids") for r in records),
           "ceiling": {}, "finding_ids": _union(r["finding_ids"] for r in records),
           "hedges": [], "attributions": [], "appraisals": []}
    for r in records:
        for fid, v in (r["record"].get("ceiling") or {}).items():
            if fid in out["ceiling"] and out["ceiling"][fid] != v:
                raise BridgeError(f"{fid}: group members disagree on its ceiling; the group cannot be written faithfully")
            out["ceiling"][fid] = copy.deepcopy(v)
        for fid, f in findings(r).items():
            if f.get("modality") not in (None, "ASSERTED") or f.get("assertion_type") == "AUTHORS_INTERPRETATION":
                out["hedges"].append({"member": r["id"], "finding_id": fid, "modality": f.get("modality"),
                                      "assertion_type": f.get("assertion_type")})
            if f.get("attributed_to"):
                out["attributions"].append({"member": r["id"], "finding_id": fid, "attributed_to": f["attributed_to"]})
        for x in _links(r["record"]):
            if x.get("role") == "SUBJECT_OF_APPRAISAL":
                out["appraisals"].append({"member": r["id"], **copy.deepcopy(x)})
    return out


def section_packets(plan: dict, ledger: list[dict], pkg: dict, findings: list[dict], corpus: list[dict],
                    register: list[dict] | None = None) -> dict:
    """{section_id: packet}. A packet is everything A09 may write a section from: its units (records, and for a
    group the union of qualifications), the contrary context of every unit, one findings table, index lines
    (verbatim) for the section's other theme elements, the reconciliation issues touching it, and the tags and
    citations a sentence in it may use. With the contrary-evidence register, `contrary_evidence` lists every
    contrary finding in the packet's findings table: whether the table shows it, what it challenges, and which
    context fields differ between the two (comparability: names only, values are in the findings table)."""
    els = elements(pkg)
    fby = {f["finding_id"]: f for f in findings}
    out_of = {e["item_id"]: e for e in ledger}
    contrary = _contrary_of(pkg)
    known = contradictions(pkg)
    issues = {i.get("issue_id"): i for i in pkg.get("reconciliation") or []}
    placement = {it["item_id"]: s["section_id"] for s in plan.get("sections") or [] for it in s.get("ordered_items") or []}
    packets = {}
    for s in plan.get("sections") or []:
        units, seen, table = [], {}, {}
        for it in s.get("ordered_items") or []:
            g = it.get("group")
            if g and g in seen:
                seen[g]["item_ids"].append(it["item_id"])
                seen[g]["notes"].append(copy.deepcopy(it.get("note_to_writer")))
                continue
            unit = {"unit_id": g or it["item_id"], "outcome": "GROUPED_WITH" if g else "DISCUSSED",
                    "item_ids": [it["item_id"]], "notes": [copy.deepcopy(it.get("note_to_writer"))]}
            units.append(unit)
            if g:
                seen[g] = unit
        ids = [i for u in units for i in u["item_ids"]]
        for u in units:
            u["records"] = {i: full_record(i, els, fby, pkg, table) for i in u["item_ids"]}
            if u["outcome"] == "GROUPED_WITH":
                u["qualifications_union"] = qualifications_union(list(u["records"].values()), table)
        ctx_ids = sorted({c for i in ids for c in contrary.get(i, ())} - set(ids), key=_natural)
        contrary_context = {c: {**full_record(c, els, fby, pkg, table), "contradicts": sorted(set(contrary[c]) & set(ids)),
                                "allocated_to": placement.get(c), "outcome": (out_of.get(c) or {}).get("outcome")}
                            for c in ctx_ids}
        themes = {els[i]["record"].get("primary_theme_id") for i in ids if els[i]["kind"] == "PROPOSITION"} - {None}
        index = [{"id": e, "text": copy.deepcopy(els[e]["record"].get("assertion")),
                  "outcome": (out_of.get(e) or {}).get("outcome"), "section_id": placement.get(e)}
                 for e in els if els[e]["kind"] == "PROPOSITION" and els[e]["record"].get("primary_theme_id") in themes
                 and e not in ids and e not in contrary_context]
        premises = {p for u in units for r in u["records"].values() for p in (r.get("premises") or {})}
        allowed = set(ids) | set(contrary_context) | premises
        citations = {}
        for e in allowed:
            rec = els[e]["record"]
            cits = set(rec.get("citation_record_ids") or [])
            if els[e]["kind"] == "AUTHOR_INTERPRETATION":
                cits |= {c for p in rec.get("premise_proposition_ids") or [] if p in els
                         for c in els[p]["record"].get("citation_record_ids") or []}
            citations[e] = sorted(cits, key=_natural)
        touching = sorted({i for e in allowed for i in (els[e]["record"].get("reconciliation_issue_ids") or [])})
        packets[s["section_id"]] = {
            "section_id": s["section_id"], "heading": s.get("heading"), "level": s.get("level", 1),
            "purpose": s.get("purpose"), "word_budget": s.get("word_budget"),
            "heading_proposition_ids": copy.deepcopy(s.get("heading_proposition_ids") or []),
            "wording_restrictions": copy.deepcopy(s.get("wording_restrictions") or []),
            "transition_in": s.get("transition_in"), "transition_out": s.get("transition_out"),
            "display_item_ids": copy.deepcopy(s.get("display_item_ids") or []),
            "themes": sorted(themes), "units": units, "contrary_context": contrary_context,
            "findings": dict(sorted(table.items(), key=lambda kv: _natural(kv[0]))),
            "contradictions": [c for c in known if (
                set(c.get("supporting_proposition_ids", [])) | set(c.get("conflicting_proposition_ids", []))
                | set((c.get("issue") or {}).get("proposition_ids") or [])) & set(ids)],
            "reconciliation_issues": [copy.deepcopy(issues[i]) for i in touching if i in issues],
            "index": index,
            "allowed_tags": sorted(allowed, key=_natural),
            "citations_by_tag": citations,
        }
        if register is not None:
            packets[s["section_id"]]["contrary_evidence"] = [
                {k: copy.deepcopy(e[k]) for k in ("finding_id", "in_table", "reasons", "challenges")}
                for e in register if e["finding_id"] in table]
    return packets


def global_packet(packets: dict) -> dict:
    """The union of all section packets: what the front matter (title, abstract, caption) may draw on."""
    allowed, cits, records, table = set(), {}, {}, {}
    for p in packets.values():
        allowed |= set(p["allowed_tags"])
        cits.update(p["citations_by_tag"])
        table.update(p.get("findings") or {})
        records.update(packet_records(p))
    return {"allowed_tags": sorted(allowed, key=_natural), "citations_by_tag": cits, "records": records,
            "findings": table, "display_item_ids": sorted({d for p in packets.values() for d in p["display_item_ids"]})}


def packet_records(packet: dict) -> dict:
    """Every record a section may tag: units, contrary context, premises and retrieved records."""
    out = {}
    for u in packet.get("units") or []:
        for i, r in u["records"].items():
            out[i] = r
            out.update(r.get("premises") or {})
    out.update(packet.get("contrary_context") or {})
    out.update(packet.get("records") or {})
    out.update(packet.get("retrieved") or {})
    return out


def evidence_of(record: dict, packet: dict) -> dict:
    """A packet record with its findings and source items, as the gate reads it for numbers."""
    table = record.get("findings") or packet.get("findings") or {}
    return {"record": record.get("record"), "findings": {f: table.get(f) for f in record.get("finding_ids") or []},
            "source_items": record.get("source_items")}


# ------------------------------------------------------------------ retrieval for A09
def fulfil_retrieval(requests: list[dict], pkg: dict, findings: list[dict], limit: int = 12) -> tuple[dict, list[dict]]:
    """A09's structured request for more evidence: element IDs (propositions, gaps) or finding IDs. Every ID must
    exist; every element must still rest on eligible evidence; a finding must be SUPPORTING (or NOT_ESTABLISHED,
    then only as an appraisal subject, which is recorded on it). Returns (records, log), each record carrying its
    own findings. Raises on anything unknown or ineligible: A09 never receives an inference in place of evidence."""
    els = elements(pkg)
    fby = {f["finding_id"]: f for f in findings}
    records, log = {}, []
    for req in requests or []:
        ids = list(req.get("element_ids") or []) + list(req.get("finding_ids") or [])
        if not ids:
            raise BridgeError("empty retrieval request")
        for i in ids:
            if i in els:
                records[i] = full_record(i, els, fby, pkg)
            elif i in fby:
                st = status_of(fby[i])
                if st not in ("SUPPORTING", "NOT_ESTABLISHED"):
                    raise BridgeError(f"retrieval: finding {i} is {st}; ineligible evidence is never supplied")
                # an explicitly requested finding comes with its original source quotation
                records[i] = {"id": i, "kind": "FINDING", "record": {"citation_record_ids": [fby[i]["record_id"]]},
                              "finding_ids": [i], "findings": {i: {**finding_record(fby[i]),
                                                                   "span": copy.deepcopy(fby[i].get("span"))}},
                              "allowed_role": "SUPPORTING or CONFLICTING" if st == "SUPPORTING" else "SUBJECT_OF_APPRAISAL only"}
            else:
                raise BridgeError(f"retrieval: {i} is not in the approved package or the evidence registry")
            log.append({"id": i, "reason": req.get("reason"), "kind": records[i]["kind"]})
    if len(records) > limit:
        raise BridgeError(f"retrieval of {len(records)} items exceeds the limit of {limit}")
    return records, log


# ------------------------------------------------------------------ the section gate
_STRIP = [tags.CITE_RE, tags.DISPLAY_RE, tags.GAP_RE, re.compile(r"⟦[^⟧]*⟧")]
_ID_RE = re.compile(r"\b(?:R\d+(?::[A-Z]+\d+)?|GROUP_G\d+(?:_LOOKUP\d+)?\.[PK]\d+|G\d{3,}|M\d{5}|RC-[0-9a-f]+|"
                    r"OC-[0-9a-f]+|[TSUPK]\d+|AI\d+|PI\d+|F\d+|E\d+|C\d+)\b")
_NUM_RE = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|(?<![\w\d])\.\d+")


def numbers(text: str) -> set[Decimal]:
    """Numeric values in text, ignoring identifiers (R0021, R0021:F1, P12, T1...) and markup."""
    for rx in _STRIP:
        text = rx.sub(" ", text)
    text = _ID_RE.sub(" ", text)
    out = set()
    for m in _NUM_RE.finditer(text):
        try:
            out.add(Decimal(m.group(0).replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return out


def _record_numbers(record) -> set[Decimal]:
    out = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, bool) or v is None:
            return
        elif isinstance(v, (int, float)):
            out.add(Decimal(str(v)).normalize())
        else:
            out.update(numbers(str(v)))
    walk(record)
    return out


def _sentences(text: str) -> list[tuple[str, list[str]]]:
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    return [(s, ids) for s, ids in tags.bindings("\n".join(lines)) if s.strip()]


def max_findings_per_sentence() -> int:
    """A10 records at most this many evidence findings per occurrence verdict (A10-RV.bounded.schema.json), so a
    sentence may not bind more: A10 could not verify it. Read from A10's schema, its single source."""
    import json
    from .paths import SCHEMAS_DIR
    schema = json.loads((SCHEMAS_DIR / "A10-RV.bounded.schema.json").read_text(encoding="utf-8"))
    return int(schema["properties"]["verdicts"]["items"]["properties"]["evidence_finding_ids"]["maxItems"])


def sentence_findings(ids: list[str], records: dict) -> set[str]:
    """Findings a sentence tagged with ids binds, as A10 follows them (premises of an interpretation included)."""
    out = set()
    for i in ids:
        r = records.get(i) or {}
        out |= set(r.get("finding_ids") or [])
        for p in (r.get("premises") or {}).values():
            out |= set(p.get("finding_ids") or [])
    return out


def check_text(text: str, packet: dict, where: str) -> list[str]:
    """The deterministic gate for one piece of prose: every sentence tagged; tags only from the packet; every
    number found in the full records of the elements its sentence is tagged with; citations only those of the
    tagged elements; no more findings bound than A10 can verify in one occurrence; display references only those
    planned here. Organizational sentences carry no numbers and no citations."""
    problems = []
    records = packet_records(packet)
    allowed = set(packet.get("allowed_tags") or []) | set(packet.get("retrieved") or {})
    cits = {**(packet.get("citations_by_tag") or {}),
            **{i: sorted(set((r.get("record") or {}).get("citation_record_ids") or []) |
                         {f.split(":")[0] for f in r.get("finding_ids") or []}, key=_natural)
               for i, r in (packet.get("retrieved") or {}).items()}}
    for n, (sentence, ids) in enumerate(_sentences(text), 1):
        label = f"{where} sentence {n}"
        if not ids:
            problems.append(f"UNTAGGED: {label}: {sentence[:120]!r}")
            continue
        sci = [i for i in ids if i != "ORG"]
        outside = [i for i in sci if i not in allowed]
        if outside:
            problems.append(f"TAG_OUTSIDE_PACKET: {label} tags {outside}")
        cited = tags.cited_records(sentence)
        if not sci:
            if numbers(sentence):
                problems.append(f"NUMBER_IN_ORG: {label}: an organizational sentence states a number")
            if cited:
                problems.append(f"CITATION_IN_ORG: {label}: an organizational sentence carries a citation")
            continue
        bound = sentence_findings(sci, records)
        if len(bound) > max_findings_per_sentence():
            problems.append(f"TOO_MANY_FINDINGS: {label} binds {len(bound)} findings; A10 verifies at most "
                            f"{max_findings_per_sentence()} per sentence: split it")
        known = set()
        for i in sci:
            if i in records:
                known |= _record_numbers(evidence_of(records[i], packet))
        unmatched = sorted(str(x) for x in numbers(sentence) - known)
        if unmatched:
            problems.append(f"UNMATCHED_NUMBER: {label}: {unmatched} not in the records of {sci}")
        permitted = {c for i in sci for c in cits.get(i, [])}
        stray = sorted(set(cited) - permitted)
        if stray:
            problems.append(f"CITATION_NOT_BOUND: {label}: {stray} not cited by {sci}")
        refs = {m.group(1) for m in tags.DISPLAY_RE.finditer(sentence)}
        if refs - set(packet.get("display_item_ids") or []):
            problems.append(f"DISPLAY_NOT_PLANNED: {label}: {sorted(refs)}")
    return problems


def check_section(section: dict, packet: dict, plan: dict, previous: list[dict]) -> list[str]:
    """The gate run after each section, before the next starts: `check_text`, the planned heading, and
    continuity with what was written before (the plan's abbreviations and nomenclature; nothing here judges
    meaning, which A10 and A11 do)."""
    sid = packet["section_id"]
    problems = []
    if section.get("section_id") != sid:
        problems.append(f"SECTION_ID: expected {sid}, got {section.get('section_id')}")
    if section.get("heading") != packet.get("heading"):
        problems.append(f"HEADING: {sid} heading differs from the approved plan")
    text = section.get("text_markdown") or ""
    problems += check_text(text, packet, sid)
    problems += continuity(text, sid, plan, previous)
    return problems


def continuity(text: str, sid: str, plan: dict, previous: list[dict]) -> list[str]:
    """Terminology across sections: an abbreviation is expanded as the plan's readability list says; a name the
    plan gives an alternative for uses the alternative only at its first mention in the manuscript."""
    problems = []
    read = plan.get("readability") or {}
    plain = tags.strip_tags(text)
    before = " ".join(tags.strip_tags(p.get("text_markdown") or "") for p in previous)
    for a in read.get("abbreviations") or []:
        abbr, exp = a.get("abbr"), a.get("expansion")
        if not abbr or not exp:
            continue
        for m in re.finditer(r"([^.;:()]{1,120})\(\s*" + re.escape(abbr) + r"\s*\)", plain):
            if not m.group(1).strip().lower().endswith(exp.lower()):
                problems.append(f"TERMINOLOGY: {sid} defines {abbr} differently from the plan ({exp!r})")
    for n in read.get("nomenclature") or []:
        alt, form = n.get("alternative_at_first_mention"), n.get("form_to_use")
        if not alt or not form:
            continue
        first_seen = re.search(re.escape(form), before) is not None
        uses = [m.start() for m in re.finditer(r"\b" + re.escape(alt) + r"\b", plain)]
        for pos in uses:
            in_parens = plain.rfind("(", 0, pos) > plain.rfind(")", 0, pos)
            if first_seen or not in_parens:
                problems.append(f"TERMINOLOGY: {sid} uses {alt!r} instead of {form!r} after first mention")
                break
    return problems


# ------------------------------------------------------------------ integration and fingerprints
def scientific_sentences(m: dict) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Per section, (whitespace-normalized sentence, tags) for every sentence tagged with an element."""
    out = {}
    for s in m.get("sections") or []:
        out[s.get("section_id")] = [(" ".join(t.split()), tuple(sorted(i)))
                                    for t, i in _sentences(s.get("text_markdown") or "") if set(i) - {"ORG"}]
    return out


def classify_integration(before: dict, after: dict) -> dict:
    """An integration edit is non-semantic only if every element-tagged sentence survives with the same text (up
    to whitespace) and the same tags. Anything else is substantive and needs A10 (which verifies the integrated
    draft in any case: this record says what changed, it never waives verification)."""
    a, b = scientific_sentences(before), scientific_sentences(after)
    changed = {sid: {"removed": [x for x in a.get(sid, []) if x not in b.get(sid, [])],
                     "added": [x for x in b.get(sid, []) if x not in a.get(sid, [])]}
               for sid in sorted(set(a) | set(b))}
    changed = {k: v for k, v in changed.items() if v["removed"] or v["added"]}
    return {"substantive": bool(changed), "changed_sections": changed,
            "sections_before": sorted(a), "sections_after": sorted(b)}


def evidence_version(pkg: dict, findings: list[dict]) -> str:
    """The evidence registry's version as the manuscript depends on it: the approved registry snapshot plus the
    current eligibility of every finding. Re-quarantining one finding changes it."""
    return fingerprint({"registry": pkg.get("registry_fingerprint"),
                        "findings": sorted([f["finding_id"], status_of(f), f.get("disposition")] for f in findings)})


def plan_version(plan: dict, ledger: list[dict]) -> str:
    return fingerprint({"plan": plan, "ledger": ledger})


def content_fingerprint(content, plan_ver: str, evidence_ver: str) -> str:
    """Text, plan version and evidence-registry version together: any of the three changing invalidates every
    approval made against the old fingerprint."""
    return fingerprint({"content": content, "plan": plan_ver, "evidence": evidence_ver})


# ------------------------------------------------------------------ request builders
def outline_view(plan: dict) -> dict:
    """The approved outline as every writer call sees it: structure only, no evidence."""
    keep = ("section_id", "level", "heading", "heading_kind", "purpose", "word_budget", "transition_in",
            "transition_out", "display_item_ids")
    return {"title": copy.deepcopy(plan.get("title")), "abstract_plan": copy.deepcopy(plan.get("abstract_plan")),
            "writing_order": copy.deepcopy(plan.get("writing_order")),
            "sections": [{k: copy.deepcopy(s.get(k)) for k in keep} for s in plan.get("sections") or []],
            "readability": copy.deepcopy(plan.get("readability"))}


def ledger_summary(ledger: list[dict]) -> list[dict]:
    return [{k: copy.deepcopy(e.get(k)) for k in ("item_id", "outcome", "section_id", "grouped_with", "reason")
             if e.get(k) is not None} for e in ledger]


def outline_payload(pkg: dict, corpus: list[dict], journal: dict, table: dict, cfg: dict,
                    findings: list[dict] | None = None) -> dict:
    """A08's input: the global map, one line per element and the table's coverage. Never the full package."""
    return {"argument_map": argument_map(pkg, corpus, findings),
            "element_index": element_index(pkg, corpus, set(table.get("propositions_fully_shown") or [])),
            "comparative_table": {k: copy.deepcopy(table.get(k)) for k in ("display_id", "type", "columns",
                                  "row_finding_ids", "propositions_fully_shown", "selection_rule", "status")},
            "selected_corpus": [{k: r.get(k) for k in ("record_id", "year", "tier", "is_preprint", "is_contrary_evidence")}
                                for r in corpus],
            "journal_profile": copy.deepcopy(journal), "max_group_size": int(cfg.get("max_group_size", 16)),
            "revision_feedback": copy.deepcopy(pkg.get("revision_feedback"))}


def writer_payload(plan: dict, packet: dict, previous: list[dict], amap: dict, journal: dict,
                   revision_request=None) -> dict:
    """A09's input for one section: the approved outline, the selected thesis, its own packet and the full prose
    of the sections written before it (narrative context only). Not the whole argument map: the packet already
    carries every contradiction touching the section."""
    return {"mode": "SECTION", "outline": outline_view(plan), "thesis": copy.deepcopy(amap.get("thesis")),
            "section_packet": packet,
            "previous_sections": [{k: p.get(k) for k in ("section_id", "heading", "text_markdown")} for p in previous],
            "journal_profile": copy.deepcopy(journal), "revision_request": copy.deepcopy(revision_request)}


def front_matter_payload(plan: dict, sections: list[dict], amap: dict, journal: dict, table: dict | None) -> dict:
    return {"mode": "FRONT_MATTER", "outline": outline_view(plan), "thesis": copy.deepcopy(amap.get("thesis")),
            "sections": [{k: s.get(k) for k in ("section_id", "heading", "text_markdown")} for s in sections],
            "comparative_table": copy.deepcopy({k: table.get(k) for k in ("display_id", "columns", "rows", "notes")})
            if table else None, "journal_profile": copy.deepcopy(journal)}


def critique_payload(manuscript: dict, amap: dict, ledger: list[dict], a10_summary: dict, journal: dict,
                     previous) -> dict:
    """A11 gets the manuscript, the compact map and the ledger, never the full plan or package."""
    return {"manuscript": manuscript, "argument_map": amap, "allocation_ledger": ledger_summary(ledger),
            "a10_findings": a10_summary, "journal_profile": copy.deepcopy(journal), "previous_critique": previous}


def manuscript_units(m: dict) -> list[tuple[str, dict]]:
    """A manuscript as the units the editor may be called on one at a time: front matter, then each section."""
    front = {k: copy.deepcopy(m.get(k)) for k in ("title", "abstract", "keywords", "table_captions", "figure_legends")
             if k in m}
    return [("FRONT", front)] + [(s.get("section_id"), {"sections": [copy.deepcopy(s)]}) for s in m.get("sections") or []]


def editor_payload(mode: str, manuscript: dict, amap: dict, ledger: list[dict], plan: dict, **extra) -> dict:
    """A12 gets the manuscript (or one unit of it), the compact map, the ledger and the readability plan."""
    return {"mode": mode, "manuscript": manuscript, "argument_map": amap, "allocation_ledger": ledger_summary(ledger),
            "outline": outline_view(plan), **{k: copy.deepcopy(v) for k, v in extra.items()}}


def merge_units(m: dict, outputs: dict[str, dict]) -> dict:
    """Reassemble a manuscript from per-unit editor outputs, in the original order."""
    out = copy.deepcopy(m)
    if "FRONT" in outputs:
        for k in ("title", "abstract", "keywords", "table_captions", "figure_legends"):
            if k in outputs["FRONT"]:
                out[k] = copy.deepcopy(outputs["FRONT"][k])
    by_id = {s.get("section_id"): s for o in outputs.values() for s in o.get("sections") or []}
    out["sections"] = [copy.deepcopy(by_id.get(s.get("section_id"), s)) for s in m.get("sections") or []]
    return out


def size(payload) -> int:
    """Serialized bytes, the basis of every bound here (canonical JSON)."""
    return len(canonical(payload).encode("utf-8"))
