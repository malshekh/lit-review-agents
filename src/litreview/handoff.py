"""The A05/A06 -> A07 handoff contract: what each validated finding must carry so its scientific meaning
survives serialization into synthesis and verification.

A finding's meaning is not only its subject, predicate and object. Whether it was hedged, whether the paper
reported it as someone else's result, whether it is the authors' interpretation rather than a result, and
which way the effect ran are part of what it says. Dropping any of them lets a later stage state a hedged
claim flat, cite a secondhand claim as primary evidence, or read antagonism as synergy. The contract fields
below are therefore carried on every validated finding, checked by code before A07 runs, and sent to A07
and A10 as fields (A07 does not receive spans, so nothing else could carry them).
"""
from __future__ import annotations

PREDICATES = (
    # relations (A05-KE v0.4 vocabulary)
    "ASSOCIATED_WITH", "CORRELATES_WITH", "PREDICTS", "DETECTS", "EXPRESSED_IN", "LOCALIZES_TO", "COLOCALIZES_WITH",
    "INTERACTS_WITH", "BINDS", "TARGETS", "INHIBITS", "ACTIVATES", "CATALYZES", "IS_SUBSTRATE_OF", "METABOLIZES",
    "INCREASES", "DECREASES", "REGULATES", "REQUIRED_FOR", "CAUSES", "PREVENTS", "IMPROVES_OUTCOME",
    "WORSENS_OUTCOME", "NO_EFFECT_ON",
    # added in A05-KE v0.5, from the OTHER_SPECIFIED clusters of run 20261025-100039
    "NO_SIGNIFICANT_DIFFERENCE", "SYNERGIZES_WITH", "ANTAGONIZES", "ADDITIVE_WITH", "POTENTIATES", "SENSITIZES_TO",
    "REVERSES_EFFECT_OF", "ACTIVE_AGAINST", "MORE_EFFECTIVE_THAN", "SIMILAR_TO", "DETECTED_IN", "CROSSES",
    "CONVERTED_TO", "EXPLAINED_BY", "PRECEDES", "DISTINCT_FROM", "USED_FOR", "UNDER_INVESTIGATION_FOR",
    # intrinsic: a property of the subject, measured or observed; no object entity
    "OBSERVED_OUTCOME", "TOLERATED", "MAXIMUM_TOLERATED_DOSE", "HALF_LIFE",
    "OTHER_SPECIFIED",
)
INTRINSIC = frozenset({"OBSERVED_OUTCOME", "TOLERATED", "MAXIMUM_TOLERATED_DOSE", "HALF_LIFE"})

# every validated finding carries every one of these keys (a value may be null where the source has none)
CONTRACT = ("finding_id", "record_id", "subject", "predicate", "predicate_detail", "object", "polarity",
            "direction", "modality", "assertion_type", "attributed_to", "origin", "context_id",
            "alignment_disposition", "disposition", "eligibility", "constraints", "plain_language_limit")
LEGACY_DETAIL = "LEGACY_WARRANT_NOTE"


def extraction_problems(ext: dict) -> list[str]:
    """Contract checks on an A05 output: a known predicate; OTHER_SPECIFIED always names its relation in
    `predicate_detail`; an object entity unless the predicate is intrinsic (never a dummy object)."""
    out = []
    for f in ext.get("findings", []):
        fid, p = f.get("finding_id"), f.get("predicate")
        if p not in PREDICATES:
            out.append(f"{fid}: predicate {p!r} is not in the vocabulary")
        if p == "OTHER_SPECIFIED" and len(str(f.get("predicate_detail") or "").strip()) < 3:
            out.append(f"{fid}: OTHER_SPECIFIED without a predicate_detail naming the relation")
        if not f.get("object_entity_id") and p not in INTRINSIC:
            out.append(f"{fid}: no object, but {p} is not an intrinsic predicate")
    return out


def _legacy(extraction_version: str | None) -> bool:
    try:
        return tuple(int(x) for x in str(extraction_version or "0").split(".")[:2]) < (0, 5)
    except ValueError:
        return True


def project(f: dict, v: dict, extraction_version: str | None) -> dict:
    """The contract fields of one finding, from its A05 record and its A06 validation. An extraction made
    before `predicate_detail` existed (A05-KE < 0.5) keeps OTHER_SPECIFIED with the relation in its warrant
    note, marked as such; nothing is reconstructed. A newer extraction without it fails the contract."""
    detail = f.get("predicate_detail")
    legacy = f.get("predicate") == "OTHER_SPECIFIED" and not detail and _legacy(extraction_version)
    return {"subject": f.get("subject_entity_id"), "predicate": f.get("predicate"),
            "predicate_detail": detail,
            **({"predicate_detail_source": LEGACY_DETAIL, "warrant_note": f.get("warrant_note")} if legacy else {}),
            "object": f.get("object_entity_id"), "polarity": f.get("polarity"), "direction": f.get("direction"),
            "modality": f.get("modality"), "assertion_type": f.get("assertion_type"),
            "attributed_to": f.get("attributed_to"), "origin": f.get("origin"),
            "alignment_disposition": v.get("gate2")}


def contract_problems(findings: list[dict]) -> list[str]:
    """Checks on validated findings before they are handed to A07: every contract key present; the relation
    of an OTHER_SPECIFIED finding named (or explicitly legacy); an object unless intrinsic."""
    out = []
    for f in findings:
        missing = [k for k in CONTRACT if k not in f]
        if missing:
            out.append(f"{f.get('finding_id')}: missing {', '.join(missing)}")
            continue
        if f["predicate"] == "OTHER_SPECIFIED" and not f["predicate_detail"] and f.get("predicate_detail_source") != LEGACY_DETAIL:
            out.append(f"{f['finding_id']}: OTHER_SPECIFIED with no relation named")
    return out
