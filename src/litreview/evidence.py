"""Evidence eligibility and evidence roles.

Eligibility: what a validated finding may be used for, decided from its A06-SV disposition alone. Entity
normalization never decides it: a correctly resolved ontology identifier does not make a finding supported,
and an ambiguous or conflicting one does not make it unsupported. The normalizer can only make a finding
*wait*: one whose entity identity changed after A06 validated it must be revalidated before it is used, so
correcting an identifier never promotes a finding by itself.

  status                 disposition                                            may serve as
  SUPPORTING             SUPPORTED, SUPPORTED_WITH_CONSTRAINTS,                 SUPPORTING or CONFLICTING evidence
                         SUPPORTED_FOR_OBSERVATION, PARTIALLY_SUPPORTED
  NOT_ESTABLISHED        DOES_NOT_ESTABLISH                                     SUBJECT_OF_APPRAISAL only
  HELD_FOR_CORRECTION    BLOCKED_ALIGNMENT caused only by a code-attached       nothing
                         identity (kept recoverable, never rejected)
  REVALIDATION_REQUIRED  any: an entity identity changed after validation       nothing, until A06 revalidates
  QUARANTINED            a revalidation changed the disposition with no change  nothing, until a human decides
                         to the extraction and no identity correction to
                         explain it (see review_changes)
  REJECTED               BLOCKED_PROVENANCE; BLOCKED_ALIGNMENT (extraction)     nothing
  UNRESOLVED             HUMAN_REVIEW_REQUIRED, UNRESOLVED_SOURCE_ACCESS, none  nothing

Evidence roles sit on each finding-proposition link, not on the proposition: one proposition may cite
validated findings as SUPPORTING or CONFLICTING and a DOES_NOT_ESTABLISH finding as SUBJECT_OF_APPRAISAL,
which is the sentence a critical review writes ("X reported Y, but its evidence does not establish it").
An appraisal link carries its own appraisal statement, the record that made the original claim, and A06's
rationale quoted verbatim. Code checks what it can (disposition, role, attribution, that the rationale is
A06's); whether the prose keeps the claim appraised rather than established is a semantic question that
A10 answers for every appraisal binding, and code requires an answer for each.

Enforced by code wherever findings are consumed as evidence, independently of each other and of what the
agents' prompts say: the A07 job (synthesis_job), display tables (display_items) and A10 verification.
"""
from __future__ import annotations

import json
import re

USABLE = frozenset({"SUPPORTED", "SUPPORTED_WITH_CONSTRAINTS", "SUPPORTED_FOR_OBSERVATION", "PARTIALLY_SUPPORTED"})
STATUSES = ("SUPPORTING", "NOT_ESTABLISHED", "HELD_FOR_CORRECTION", "REVALIDATION_REQUIRED", "QUARANTINED",
            "REJECTED", "UNRESOLVED")
ROLES = ("SUPPORTING", "CONFLICTING", "SUBJECT_OF_APPRAISAL")
ALLOWED_ROLES = {"SUPPORTING": {"SUPPORTING", "CONFLICTING"}, "NOT_ESTABLISHED": {"SUBJECT_OF_APPRAISAL"}}
FINDING_RE = re.compile(r"\bR\d+:F\d+\b")


def can_cite(disposition: str | None) -> bool:
    """Supporting or conflicting evidence: only a supported A06 disposition."""
    return disposition in USABLE


def status_of(finding: dict) -> str:
    """The eligibility status of a validated-finding record. The disposition sets the ceiling; a stored
    status can only lower it (held, revalidation required), never raise it."""
    stored = (finding.get("eligibility") or {}).get("status")
    d = finding.get("disposition")
    if stored in ("HELD_FOR_CORRECTION", "REVALIDATION_REQUIRED", "QUARANTINED", "REJECTED", "UNRESOLVED"):
        return stored
    if can_cite(d):
        return "SUPPORTING"
    if d == "DOES_NOT_ESTABLISH":
        return "NOT_ESTABLISHED"
    return "REJECTED" if str(d or "").startswith("BLOCKED_") else "UNRESOLVED"


def role_allowed(finding: dict | None, role: str) -> bool:
    return finding is not None and role in ALLOWED_ROLES.get(status_of(finding), set())


# ------------------------------------------------------------------ classification (per paper)
def _codes(*values) -> set[str]:
    out = set()
    for v in values:
        for part in re.split(r"[;,]", str(v or "")):
            code = part.split(":")[0].strip().upper()
            if code and code != "NONE":
                out.add(code)
    return out


def _attached_identity(entity: dict) -> list[str]:
    """What code attached to the entity (identifier and its label), as opposed to what A05 extracted."""
    if entity.get("normalization_state") != "RESOLVED":
        return []
    return [str(x) for x in (entity.get("normalized_id"), entity.get("approved_name"), entity.get("approved_symbol"))
            if x and len(str(x)) > 3]


def normalization_entities(validation_doc: dict, entities: list[dict], snapshot: dict | None = None) -> set[str]:
    """Entity IDs whose code-attached identity A06 objected to anywhere in this paper's validation (it quotes
    the identifier or label it saw). Used only when A06 recorded no defect `cause`."""
    text = json.dumps({k: v for k, v in validation_doc.items() if k != "_entity_identities"}, ensure_ascii=False).lower()
    if snapshot is not None:   # only what A06 actually saw when it validated
        seen = {eid: [str(x) for x in (i.get("normalized_id"), i.get("approved_name")) if x and len(str(x)) > 3]
                for eid, i in snapshot.items() if i and i.get("normalized_id")}
    else:
        seen = {e["entity_id"]: _attached_identity(e) for e in entities}
    # a label that is just a mention in the paper ("disulfiram") says nothing about the attached identity
    mentions = {" ".join(str(e.get("mention") or "").lower().split()) for e in entities}
    return {eid for eid, xs in seen.items()
            if any(x.lower() in text and " ".join(x.lower().split()) not in mentions for x in xs)}


def identity_key(entity: dict | None) -> dict:
    """The identity A06 saw for an entity: recorded with each validation, compared later."""
    e = entity or {}
    return {"normalized_id": e.get("normalized_id") if e.get("normalization_state") == "RESOLVED" else None,
            "approved_name": e.get("approved_name") if e.get("normalization_state") == "RESOLVED" else None,
            "normalization_state": e.get("normalization_state")}


def identity_snapshot(extraction: dict) -> dict[str, dict]:
    return {e["entity_id"]: identity_key(e) for e in extraction.get("entities", [])}


def classify(finding: dict, validation: dict | None, defects: list[dict], implicated: set[str],
             changed: set[str] = frozenset()) -> dict:
    """{status, disposition, reason, basis} for one finding of one paper. `defects`: this finding's A06
    defect reports; `implicated`: from normalization_entities(); `changed`: entity IDs whose identity
    differs from what A06 saw when it validated."""
    v = validation or {}
    d = v.get("disposition")
    moved = {finding.get("subject_entity_id"), finding.get("object_entity_id")} & set(changed)
    if moved:
        return {"status": "REVALIDATION_REQUIRED", "disposition": d, "entities": sorted(moved),
                "reason": "entity identity changed after A06 validated this finding (" + ", ".join(sorted(moved))
                          + "); it is not used until revalidated"}
    if d in USABLE:
        return {"status": "SUPPORTING", "disposition": d}
    if d == "DOES_NOT_ESTABLISH":
        return {"status": "NOT_ESTABLISHED", "disposition": d,
                "reason": "A06: the paper's evidence does not establish the finding as stated"}
    if d == "BLOCKED_PROVENANCE":
        return {"status": "REJECTED", "disposition": d, "reason": "Gate 1 (provenance) failed"}
    if d == "BLOCKED_ALIGNMENT":
        codes = _codes(v.get("gate2"), *(x.get("defect_type") for x in defects))
        causes = {str(x.get("cause") or "").upper() for x in defects} - {""}
        if codes == {"ENTITY_MISMATCH"}:
            if causes == {"NORMALIZATION"}:
                return {"status": "HELD_FOR_CORRECTION", "disposition": d, "basis": "A06 defect cause",
                        "reason": "entity identity attached by normalization contradicts the source"}
            ents = {finding.get("subject_entity_id"), finding.get("object_entity_id")} & implicated
            if not causes and ents:
                return {"status": "HELD_FOR_CORRECTION", "disposition": d, "basis": "inferred",
                        "entities": sorted(ents),
                        "reason": "entity identity attached by normalization contradicts the source "
                                  "(inferred: A06 quotes the code-attached identity of " + ", ".join(sorted(ents)) + ")"}
        return {"status": "REJECTED", "disposition": d,
                "reason": "Gate 2 (alignment) failed: " + ", ".join(sorted(codes) or ["unspecified"])}
    return {"status": "UNRESOLVED", "disposition": d, "reason": f"disposition {d or 'missing'}"}


def annotate_paper(extraction: dict, validation_doc: dict, review: dict[str, dict] | None = None) -> dict[str, dict]:
    """finding_id (paper-local, F3) -> eligibility, for one paper. A validation records the identities A06
    saw (`_entity_identities`); one without that record predates it and is taken to match the extraction.
    `review`: this paper's review items (review_changes), keyed by local finding ID. A quarantined change is
    not applied until a human decides: KEEP_OLD restores the previous validation's entry, ACCEPT_NEW applies
    the new one, and while undecided the finding is QUARANTINED."""
    vals = {v["finding_id"]: v for v in validation_doc.get("validations", [])}
    quarantined = {}
    for fid, item in (review or {}).items():
        if item.get("action") != "QUARANTINED":
            continue
        if item.get("decision") == "KEEP_OLD":
            vals[fid] = item["old_validation"]
        elif item.get("decision") != "ACCEPT_NEW":
            quarantined[fid] = item
    defects: dict[str, list] = {}
    for x in validation_doc.get("defect_reports") or []:
        defects.setdefault(x.get("finding_id"), []).append(x)
    snap = validation_doc.get("_entity_identities")
    now = identity_snapshot(extraction)
    changed = {eid for eid, ident in (snap or {}).items() if ident.get("normalized_id")
               and ident.get("normalized_id") != (now.get(eid) or {}).get("normalized_id")}
    implicated = normalization_entities(validation_doc, extraction.get("entities", []), snap)
    out = {f["finding_id"]: classify(f, vals.get(f["finding_id"]), defects.get(f["finding_id"], []), implicated,
                                     changed)
           for f in extraction.get("findings", [])}
    for fid, item in quarantined.items():
        if fid in out:
            out[fid] = {"status": "QUARANTINED", "disposition": item["new_disposition"],
                        "previous_disposition": item["old_disposition"], "direction": item["direction"],
                        "reason": item["reason"] + "; awaiting human review (litreview review-validation)"}
    return out


# ------------------------------------------------------------------ revalidation review
SOURCE_ENTITY_FIELDS = ("mention", "type", "subtype", "roles", "molecule_species", "measured_at",
                        "identity_relation", "construct")
RANK = {"SUPPORTED": 6, "SUPPORTED_WITH_CONSTRAINTS": 5, "PARTIALLY_SUPPORTED": 4, "SUPPORTED_FOR_OBSERVATION": 4,
        "DOES_NOT_ESTABLISH": 2, "HUMAN_REVIEW_REQUIRED": 1, "UNRESOLVED_SOURCE_ACCESS": 1}


def usability(disposition: str | None) -> int:
    """2: may support or conflict; 1: may be appraised; 0: no role."""
    return 2 if can_cite(disposition) else 1 if disposition == "DOES_NOT_ESTABLISH" else 0


def finding_fingerprints(extraction: dict) -> dict[str, str]:
    """What A05 recorded for each finding, with the source fields (never the code-attached identity) of its
    subject, object and context: a change here is a change to the extraction."""
    import hashlib
    ents = {e["entity_id"]: {k: e.get(k) for k in SOURCE_ENTITY_FIELDS} for e in extraction.get("entities", [])}
    ctx = {c["context_id"]: c for c in extraction.get("contexts", [])}
    out = {}
    for f in extraction.get("findings", []):
        blob = {"finding": f, "subject": ents.get(f.get("subject_entity_id")),
                "object": ents.get(f.get("object_entity_id")), "context": ctx.get(f.get("context_id"))}
        out[f["finding_id"]] = hashlib.sha256(json.dumps(blob, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return out


def review_changes(record_id: str, old_val: dict, old_ext: dict, new_val: dict, new_ext: dict) -> list[dict]:
    """Every disposition a revalidation changed, and whether the change is explained.

    Explained: the finding's extraction changed, or it was HELD_FOR_CORRECTION and an identity it rests on
    was corrected. Anything else is the same input read differently and is not applied automatically:
    - an improvement (a higher disposition, or a role the finding lacked) is QUARANTINED;
    - a lost role (usable -> unusable, appraisable -> nothing) is QUARANTINED too: instability in that
      direction silently removes evidence;
    - a narrowing that changes no role (SUPPORTED -> SUPPORTED_WITH_CONSTRAINTS) is applied and noted.
    A human decides each quarantined item with `litreview review-validation`."""
    old = {v["finding_id"]: v for v in old_val.get("validations", [])}
    seen = old_val.get("_entity_identities") or identity_snapshot(old_ext)
    # the old status as of that validation: against the identities A06 saw then, not today's
    as_seen = {**old_ext, "entities": [{**e, **(seen.get(e["entity_id"]) or {})} for e in old_ext.get("entities", [])]}
    old_status = annotate_paper(as_seen, old_val)
    old_fp = old_val.get("_finding_fingerprints") or finding_fingerprints(old_ext)
    new_fp = finding_fingerprints(new_ext)
    now = identity_snapshot(new_ext)
    by_id = {f["finding_id"]: f for f in new_ext.get("findings", [])}
    items = []
    for v in new_val.get("validations", []):
        fid = v["finding_id"]
        od, nd = (old.get(fid) or {}).get("disposition"), v.get("disposition")
        if fid not in old or od == nd:
            continue
        f = by_id.get(fid, {})
        ents = {f.get("subject_entity_id"), f.get("object_entity_id")} - {None}
        moved = {e for e in ents if (seen.get(e) or {}).get("normalized_id") != (now.get(e) or {}).get("normalized_id")}
        st = old_status.get(fid) or {}
        if old_fp.get(fid) != new_fp.get(fid):
            explained = "the extraction of this finding changed"
        elif st.get("status") == "HELD_FOR_CORRECTION" and moved & set(st.get("entities") or ents):
            explained = "held for a code-attached identity, which was corrected (" + ", ".join(sorted(moved)) + ")"
        else:
            explained = None
        uo, un = usability(od), usability(nd)
        if un > uo or (un == uo and RANK.get(nd, 0) > RANK.get(od, 0)):
            direction = "IMPROVED"
        elif un < uo:
            direction = "LOST_ROLE"
        else:
            direction = "NARROWED"
        action = "APPLIED" if explained or direction == "NARROWED" else "QUARANTINED"
        why = ("explained: " + explained) if explained else             "with no change to the extraction and no identity correction to explain it"
        items.append({"finding_id": f"{record_id}:{fid}", "record_id": record_id, "local_id": fid,
                      "old_disposition": od, "new_disposition": nd, "old_gate2": (old.get(fid) or {}).get("gate2"),
                      "new_gate2": v.get("gate2"), "direction": direction, "explained_by": explained,
                      "identity_changed": sorted(moved), "action": action,
                      "reason": f"revalidation changed {od} -> {nd} ({direction}) {why}",
                      "old_validation": old.get(fid), "decision": None})
    return items


def summary(findings: list[dict]) -> dict:
    out = {s: 0 for s in STATUSES}
    for f in findings:
        out[status_of(f)] += 1
    return out


# ------------------------------------------------------------------ evidence links
def links_of(p: dict) -> list[dict]:
    """A proposition's finding links with their roles: its `evidence` list, or, for a proposition written
    with the older parallel lists, SUPPORTING and CONFLICTING links derived from them."""
    if p.get("evidence"):
        return [x for x in p["evidence"] if isinstance(x, dict)]
    return ([{"finding_id": f, "role": "SUPPORTING"} for f in p.get("supporting_finding_ids") or []]
            + [{"finding_id": f, "role": "CONFLICTING"} for f in p.get("conflicting_finding_ids") or []])


def _squash(s: str | None) -> str:
    return " ".join(str(s or "").split()).lower()


def link_problems(p: dict, findings: dict[str, dict], record_of: dict[str, str]) -> list[str]:
    """Structural checks on one proposition's evidence links. [] = acceptable. `findings`: finding ID ->
    validated-finding record (disposition, eligibility, plain_language_limit, constraints)."""
    problems = []
    links = links_of(p)
    if p.get("evidence") and (p.get("supporting_finding_ids") or p.get("conflicting_finding_ids")):
        derived = ({x["finding_id"] for x in links if x.get("role") == "SUPPORTING"},
                   {x["finding_id"] for x in links if x.get("role") == "CONFLICTING"})
        if derived != (set(p.get("supporting_finding_ids") or []), set(p.get("conflicting_finding_ids") or [])):
            problems.append("evidence roles and supporting/conflicting lists disagree")
    seen = set()
    for x in links:
        fid, role = x.get("finding_id"), x.get("role")
        if fid in seen:
            problems.append(f"{fid} linked twice (one role per finding per proposition)")
        seen.add(fid)
        f = findings.get(fid)
        if f is None:
            problems.append(f"unknown finding ID {fid}")
            continue
        if role not in ROLES:
            problems.append(f"{fid}: unknown role {role!r}")
            continue
        if not role_allowed(f, role):
            problems.append(f"{fid} ({status_of(f)}, {f.get('disposition') or 'no disposition'}) may not serve as {role}")
            continue
        if role == "SUBJECT_OF_APPRAISAL":
            a = x.get("appraisal") or {}
            if not str(a.get("statement") or "").strip():
                problems.append(f"{fid}: appraisal link without an appraisal statement")
            if a.get("claim_source_record_id") != record_of.get(fid):
                problems.append(f"{fid}: appraisal must name the record that made the claim ({record_of.get(fid)})")
            quoted = _squash(a.get("a06_rationale"))
            a06 = [_squash(f.get("plain_language_limit"))] + [_squash(c) for c in f.get("constraints") or []]
            if not quoted or not any(quoted in t for t in a06 if t):
                problems.append(f"{fid}: a06_rationale must quote A06's plain_language_limit or a constraint verbatim")
    roles = [x.get("role") for x in links]
    if p.get("type") == "SOURCE_GROUNDED" and not {"SUPPORTING", "CONFLICTING"} & set(roles):
        problems.append("appraised claims never support a proposition: a SOURCE_GROUNDED proposition needs a "
                        "SUPPORTING or CONFLICTING finding" if roles else "cites no finding")
    if p.get("type") == "CLAIM_APPRAISAL" and "SUBJECT_OF_APPRAISAL" not in roles:
        problems.append("a CLAIM_APPRAISAL proposition needs a SUBJECT_OF_APPRAISAL link")
    return problems


def normalized_proposition(p: dict) -> dict:
    """The proposition with `evidence` and the derived lists (supporting, conflicting, appraised) in step,
    so every consumer that reads the lists sees exactly the roles that were checked."""
    links = links_of(p)
    return {**p, "evidence": links,
            "supporting_finding_ids": [x["finding_id"] for x in links if x.get("role") == "SUPPORTING"],
            "conflicting_finding_ids": [x["finding_id"] for x in links if x.get("role") == "CONFLICTING"],
            "appraised_finding_ids": [x["finding_id"] for x in links if x.get("role") == "SUBJECT_OF_APPRAISAL"]}


# ------------------------------------------------------------------ A10
def _named(*docs) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.endswith("_id") and isinstance(v, str) and v and k != "finding_id":
                    idx.setdefault(v, []).append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for d in docs:
        walk(d)
    return idx


def _links_behind(item_id: str, idx: dict, seen: set | None = None) -> list[dict]:
    """Every evidence link behind an item: a proposition's own links, and for an item that rests on
    propositions (a gap's established_by, premise_proposition_ids), theirs. A bare finding ID is a
    SUPPORTING link."""
    seen = seen if seen is not None else set()
    if item_id in seen:
        return []
    seen.add(item_id)
    if FINDING_RE.fullmatch(item_id):
        return [{"finding_id": item_id, "role": "SUPPORTING"}]
    out = []
    for d in idx.get(item_id, []):
        if any(k in d for k in ("evidence", "supporting_finding_ids", "conflicting_finding_ids")):
            out += [{**x, "proposition_id": item_id} for x in links_of(d)]
        for k, v in d.items():
            if k == "established_by" or k.endswith("proposition_ids"):
                for x in v if isinstance(v, list) else [v]:
                    if isinstance(x, str):
                        out += _links_behind(x, idx, seen)
    return out


def verification_bindings(manuscript: dict, package: dict, findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """(flags, appraisal_bindings) for every tagged manuscript sentence.

    flags: links that may not be used in their role. A claim whose supporting links are all unusable is
    BLOCKING (`SUPPORTED_ONLY_BY_INELIGIBLE_EVIDENCE`): it must never be verified as supported; any other
    unusable link is MAJOR (`INELIGIBLE_EVIDENCE_CITED`).
    appraisal_bindings: each sentence bound to a SUBJECT_OF_APPRAISAL link, with the appraisal it must
    preserve. A10 must return a verdict for each (`appraisal_checks`)."""
    from .tools import tags
    by_id = {f["finding_id"]: f for f in findings}
    idx = _named(package or {})
    flags, bindings, done = [], [], set()
    for sec in manuscript.get("sections") or []:
        for sentence, ids in tags.bindings(sec.get("text_markdown") or ""):
            ids = [i for i in ids if i != "ORG"]
            if not ids:
                continue
            key = (tuple(sorted(ids)), sec.get("section_id"))
            if key in done:
                continue
            done.add(key)
            links = [x for i in ids for x in _links_behind(i, idx)]
            loc = {"item_ids": sorted(ids), "section_id": sec.get("section_id"), "sentence_excerpt": sentence[:200]}
            bad = [x for x in links if not role_allowed(by_id.get(x["finding_id"]), x.get("role"))]
            sup = [x for x in links if x.get("role") == "SUPPORTING"]
            bad_sup = [x for x in bad if x.get("role") == "SUPPORTING"]
            if bad:
                only = bool(sup) and len(bad_sup) == len(sup)
                flags.append({**loc,
                              "code": "SUPPORTED_ONLY_BY_INELIGIBLE_EVIDENCE" if only else "INELIGIBLE_EVIDENCE_CITED",
                              "severity": "BLOCKING" if only else "MAJOR",
                              "ineligible_findings": [
                                  {"finding_id": x["finding_id"], "role": x.get("role"),
                                   "disposition": (by_id.get(x["finding_id"]) or {}).get("disposition"),
                                   "status": status_of(by_id[x["finding_id"]]) if x["finding_id"] in by_id else "UNKNOWN"}
                                  for x in bad],
                              "citable_supporting": sorted({x["finding_id"] for x in sup} - {x["finding_id"] for x in bad_sup})})
            for x in links:
                if x.get("role") == "SUBJECT_OF_APPRAISAL" and x not in bad:
                    a = x.get("appraisal") or {}
                    bindings.append({**loc, "binding_id": f"AB{len(bindings) + 1}", "finding_id": x["finding_id"],
                                     "proposition_id": x.get("proposition_id"),
                                     "claim_source_record_id": a.get("claim_source_record_id"),
                                     "appraisal_statement": a.get("statement"), "a06_rationale": a.get("a06_rationale")})
    return flags, bindings


def claims_on_ineligible_evidence(manuscript: dict, package: dict, findings: list[dict]) -> list[dict]:
    return verification_bindings(manuscript, package, findings)[0]


_RANK = {"NONE": 0, "MINOR": 1, "MAJOR": 2, "BLOCKING": 3}
# A10 codes whose severity code will not let be lowered
SEVERITY_FLOOR = {"APPRAISED_CLAIM_PROMOTED": "BLOCKING", "SUPPORTED_ONLY_BY_INELIGIBLE_EVIDENCE": "BLOCKING"}


def apply_to_verification(rv: dict, flags: list[dict], pass_: str, bindings: list[dict] = ()) -> dict:
    """Merge code's checks into A10's output, so a claim resting on unusable evidence, or an appraised claim
    promoted into an established one, can never come back verified:
    - each flag becomes a CODE finding (responsible stage A7-SYN: the synthesis cited the evidence);
    - every appraisal binding needs a verdict in `appraisal_checks`; `preserved: false` becomes a BLOCKING
      APPRAISED_CLAIM_PROMOTED finding, a missing verdict a MAJOR APPRAISAL_UNCHECKED one;
    - codes in SEVERITY_FLOOR keep their floor whatever severity A10 gave them;
    - a FINAL pass cannot approve over any of these."""
    original, rv = rv, dict(rv)
    findings = [dict(f) for f in rv.get("findings") or []]
    for f in findings:
        floor = SEVERITY_FLOOR.get(f.get("code"))
        if floor and _RANK.get(str(f.get("severity")), 0) < _RANK[floor]:
            f["severity"], f["severity_floor_applied"] = floor, True
    added = []
    for n, fl in enumerate(flags, 1):
        added.append({
            "id": f"CODE-ELIG-{n}", "pass": pass_, "check": "TRACEABILITY", "code": fl["code"],
            "severity": fl["severity"], "priority": "CRITICAL", "source": "CODE",
            "location": {"section_id": fl["section_id"], "sentence_excerpt": fl["sentence_excerpt"]},
            "text_says": fl["sentence_excerpt"],
            "evidence_supports": "; ".join(f"{x['finding_id']} ({x['role']}, {x['disposition']})"
                                           for x in fl["ineligible_findings"]),
            "rationale": "Uses validated findings in a role their A06 disposition does not permit"
                         + (" and has no usable support" if fl["severity"] == "BLOCKING" else ""),
            "responsible_stage": "A7-SYN"})
    checks = {c.get("binding_id"): c for c in rv.get("appraisal_checks") or [] if isinstance(c, dict)}
    promoted = {(f.get("location") or {}).get("sentence_excerpt") for f in findings
                if f.get("code") == "APPRAISED_CLAIM_PROMOTED"}
    unchecked = []
    for b in bindings:
        c = checks.get(b["binding_id"])
        if c is None:
            unchecked.append(b["binding_id"])
            added.append({"id": f"CODE-APPR-{b['binding_id']}", "pass": pass_, "check": "ENTAILMENT",
                          "code": "APPRAISAL_UNCHECKED", "severity": "MAJOR", "priority": "CRITICAL", "source": "CODE",
                          "location": {"section_id": b["section_id"], "sentence_excerpt": b["sentence_excerpt"]},
                          "rationale": f"No verdict on whether {b['finding_id']} stays an appraised claim",
                          "responsible_stage": "A9-WRI" if pass_ == "DRAFT" else "A12-EDI"})
        elif c.get("preserved") is not True and b["sentence_excerpt"] not in promoted:
            added.append({"id": f"CODE-APPR-{b['binding_id']}", "pass": pass_, "check": "ENTAILMENT",
                          "code": "APPRAISED_CLAIM_PROMOTED", "severity": "BLOCKING", "priority": "CRITICAL",
                          "source": "CODE+A10",
                          "location": {"section_id": b["section_id"], "sentence_excerpt": b["sentence_excerpt"]},
                          "text_says": b["sentence_excerpt"],
                          "evidence_supports": f"{b['finding_id']} is DOES_NOT_ESTABLISH: {b.get('a06_rationale')}",
                          "rationale": c.get("rationale") or "A10 found the appraised claim stated as established",
                          "responsible_stage": "A9-WRI" if pass_ == "DRAFT" else "A12-EDI"})
    findings += added
    if not added and findings == list(rv.get("findings") or []):
        return original
    rv["findings"] = findings
    worst = max((_RANK.get(str(f.get("severity")), 0) for f in findings), default=0)
    if _RANK.get(str(rv.get("finding_severity") or "NONE"), 0) < worst:
        rv["finding_severity"] = {v: k for k, v in _RANK.items()}[worst]
    if rv.get("release_disposition") in ("APPROVED", "APPROVED_WITH_MINOR_FINDINGS"):
        if worst >= _RANK["MAJOR"]:
            rv["release_disposition"] = ("HOLD_FOR_UPSTREAM_REVIEW" if flags else
                                         "INCOMPLETE_VERIFICATION" if unchecked else "HOLD_FOR_REVISION")
            rv["release_overridden_by_code"] = "evidence roles or appraisal checks failed (evidence.py)"
    if flags:
        rv["ineligible_evidence_claims"] = flags
    if unchecked:
        rv["appraisal_bindings_unchecked"] = unchecked
    return rv
