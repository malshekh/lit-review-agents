"""Gate 2 regression report after a normalization correction: recovery and new error, side by side.

Counting only the blocks that disappear would look like success while missing the opposite failure. So the
report covers both directions, from the validations archived before revalidation (data/renormalization/
validations_before/) and the current ones:

- the original ENTITY_MISMATCH findings, each classified: resolved by the normalization correction, still
  justified by a source-level discrepancy, now blocked or downgraded for another reason, or not revalidated;
- the findings held for correction, with their final dispositions;
- every finding accepted before that is not usable now, split by whether an identity it rests on changed
  (a surfaced false acceptance) or not (a different reading on revalidation);
- every finding newly flagged at Gate 2;
- the normalization conflicts A06 reported on revalidation.

Confirmed corrections are kept apart from changed judgments. A confirmed correction is a change the input
explains: the finding was held for a code-attached identity and that identity was corrected. A changed
judgment is A06 reading the same extraction and identity differently; it is quarantined for human review
(evidence.review_changes) and counted in no recovery tally. A fall in the ENTITY_MISMATCH count is not, by
itself, evidence that validation became more accurate.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import evidence

ENTITY = "ENTITY_MISMATCH"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _by_finding(val: dict | None) -> dict[str, dict]:
    return {v["finding_id"]: v for v in (val or {}).get("validations", [])}


def build(data: Path, before_ext_dir: Path | None = None) -> dict:
    data = Path(data)
    before_dir = data / "renormalization" / "validations_before"
    before_ext_dir = before_ext_dir or data / "renormalization" / "extractions_before"
    rows = []
    review = {}
    for i in _load(data / "validation_review.json") or []:
        review.setdefault(i["record_id"], {})[i["local_id"]] = i
    for p in sorted((data / "validations").glob("*.json")):
        rid = p.stem
        now_val = _load(p)
        old_val = _load(before_dir / p.name) or now_val
        # revalidated = a fresh A06 call was made (renormalize archives every paper, revalidated or not)
        revalidated = any(x for x in (data.parent / "outputs").glob(f"A06-SV_{rid}_reval*.json") if ".raw" not in x.name)
        ext_now = _load(data / "extractions" / p.name) or {}
        ext_old = _load(before_ext_dir / p.name) or ext_now
        elig_old = evidence.annotate_paper(ext_old, {k: v for k, v in old_val.items() if k != "_entity_identities"})
        elig_now = evidence.annotate_paper(ext_now, now_val, review.get(rid))
        old, now = _by_finding(old_val), _by_finding(now_val)
        ents_old = {e["entity_id"]: e for e in ext_old.get("entities", [])}
        ents_now = {e["entity_id"]: e for e in ext_now.get("entities", [])}
        for f in ext_now.get("findings", []):
            fid = f["finding_id"]
            ids = [x for x in (f.get("subject_entity_id"), f.get("object_entity_id")) if x]
            identity = {eid: {"before": evidence.identity_key(ents_old.get(eid)), "now": evidence.identity_key(ents_now.get(eid)),
                              "mention": (ents_now.get(eid) or {}).get("mention")} for eid in ids}
            rows.append({
                "finding_id": f"{rid}:{fid}", "record_id": rid, "revalidated": revalidated,
                "gate2_before": (old.get(fid) or {}).get("gate2"), "gate2_now": (now.get(fid) or {}).get("gate2"),
                "disposition_before": (old.get(fid) or {}).get("disposition"),
                "disposition_now": (now.get(fid) or {}).get("disposition"),
                "status_before": (elig_old.get(fid) or {}).get("status"), "status_now": (elig_now.get(fid) or {}).get("status"),
                "identity_changed": any(v["before"]["normalized_id"] != v["now"]["normalized_id"] for v in identity.values()),
                "review": {k: (review.get(rid) or {}).get(fid, {}).get(k) for k in
                           ("action", "direction", "explained_by", "decision", "reviewer_note")},
                "identity": identity})
    conflicts = {rid: (_load(data / "validations" / f"{rid}.json") or {}).get("normalization_conflicts") or []
                 for rid in sorted({r["record_id"] for r in rows if r["revalidated"]})}

    def entity(r, key):
        return ENTITY in str(r[key] or "")

    original = [r for r in rows if entity(r, "gate2_before")]
    for r in original:
        rv = r["review"]
        r["outcome"] = ("NOT_REVALIDATED" if not r["revalidated"] else
                        "CHANGED_JUDGMENT_QUARANTINED" if r["status_now"] == "QUARANTINED" else
                        "STILL_ENTITY_MISMATCH" if entity(r, "gate2_now") else
                        "CONFIRMED_CORRECTION_NOW_USABLE" if rv.get("explained_by") and r["status_now"] == "SUPPORTING" else
                        "CONFIRMED_CORRECTION_NOT_USABLE" if rv.get("explained_by") else
                        "STILL_BLOCKED_FOR_ANOTHER_DEFECT")
    held = [r for r in rows if r["status_before"] == "HELD_FOR_CORRECTION"]
    lost = [r for r in rows if r["status_before"] == "SUPPORTING" and r["status_now"] != "SUPPORTING"]
    new_flags = [r for r in rows if r["revalidated"] and str(r["gate2_before"] or "") in ("ALIGNED", "")
                 and str(r["gate2_now"] or "ALIGNED") not in ("ALIGNED", "NOT_ASSESSED", "None")]
    gained = [r for r in rows if r["status_before"] != "SUPPORTING" and r["status_now"] == "SUPPORTING"]
    quarantined = [r for r in rows if r["status_now"] == "QUARANTINED"]
    probes = _load(data / "renormalization" / "a06_probes.json") or {}
    stability: dict[str, list] = {}
    for step, out in probes.items():
        if step.startswith("A06-SV_stability_"):
            rid, fid = step.split("_")[2:4]
            v = next((x for x in out.get("validations", []) if x["finding_id"] == fid), {})
            stability.setdefault(f"{rid}:{fid}", []).append(v.get("disposition"))

    def count(rs, key):
        out: dict[str, int] = {}
        for r in rs:
            out[str(r[key])] = out.get(str(r[key]), 0) + 1
        return out
    return {
        "papers_revalidated": sorted({r["record_id"] for r in rows if r["revalidated"]}),
        "original_entity_mismatches": {"count": len(original), "by_outcome": count(original, "outcome"), "findings": original},
        "held_for_correction": {"count": len(held), "final_dispositions": count(held, "disposition_now"),
                                "final_status": count(held, "status_now"), "findings": held},
        "previously_accepted_now_not_usable": {
            "count": len(lost),
            "identity_changed": [r for r in lost if r["identity_changed"]],
            "identity_unchanged": [r for r in lost if not r["identity_changed"]]},
        "newly_flagged_at_gate2": {"count": len(new_flags), "by_code": count(new_flags, "gate2_now"), "findings": new_flags},
        "newly_usable": {"count": len(gained), "findings": gained},
        "changed_judgments_quarantined": {"count": len(quarantined), "by_direction": count(
            [{"d": r["review"].get("direction")} for r in quarantined], "d"), "findings": quarantined},
        "identical_input_repeats": {k: {"dispositions": v, "consistent": len(set(v)) == 1} for k, v in stability.items()},
        "normalization_conflicts_reported_by_a06": conflicts,
        "status_totals": {"before": count(rows, "status_before"), "now": count(rows, "status_now")},
    }


def text(rep: dict) -> str:
    o, h, lost, nf = (rep["original_entity_mismatches"], rep["held_for_correction"],
                      rep["previously_accepted_now_not_usable"], rep["newly_flagged_at_gate2"])
    q = rep["changed_judgments_quarantined"]
    usable = o["by_outcome"].get("CONFIRMED_CORRECTION_NOW_USABLE", 0)
    lines = [f"Papers revalidated: {len(rep['papers_revalidated'])} ({', '.join(rep['papers_revalidated'])})",
             f"Original ENTITY_MISMATCH findings: {o['count']} -> " + ", ".join(f"{k} {v}" for k, v in sorted(o['by_outcome'].items())),
             f"  Recovered: at most {usable} (changes explained by an identity correction; A06 also re-read them, "
             "so some share may be re-readings rather than corrections). A fall in ENTITY_MISMATCH is not evidence "
             "of improved accuracy.",
             f"Changed judgments, quarantined for human review: {q['count']} "
             + ", ".join(f"{k} {v}" for k, v in sorted(q['by_direction'].items())),
             "Identical-input repeats: " + "; ".join(f"{k} {'/'.join(map(str, v['dispositions']))}"
                                                     + ("" if v["consistent"] else " INCONSISTENT")
                                                     for k, v in sorted(rep["identical_input_repeats"].items())),
             f"Held for correction: {h['count']} -> dispositions " + ", ".join(f"{k} {v}" for k, v in sorted(h['final_dispositions'].items())),
             f"Accepted before, not usable now: {lost['count']} ({len(lost['identity_changed'])} with a changed identity, "
             f"{len(lost['identity_unchanged'])} without)",
             f"Newly flagged at Gate 2: {nf['count']} " + ", ".join(f"{k} {v}" for k, v in sorted(nf['by_code'].items())),
             f"Newly usable: {rep['newly_usable']['count']}",
             "Status totals before: " + json.dumps(rep["status_totals"]["before"], sort_keys=True),
             "Status totals now:    " + json.dumps(rep["status_totals"]["now"], sort_keys=True)]
    return "\n".join(lines)
