"""Versioned deterministic source interpretation, separate from raw A05/A06 evidence.

This is a conservative adapter, not an independent scientific validator. Ambiguous
specimen/polarity links stop the handoff; unsupported categorical entity labels
are quarantined and replaced with source-neutral types, with an immutable audit.
"""
from __future__ import annotations
import copy, hashlib, json, re

RULE_VERSION = "source-semantics-2"
NONDETECTION_NOTE = "[source-semantics-2] Tested and not detected under reported conditions; not biological absence or a non-significant comparison."
PROTECTED_LABELS = {"ENDOGENOUS_METABOLITE": "MOLECULE", "APPROVED_DRUG": "DRUG_STATUS_UNVERIFIED"}
LABEL_WORDS = {"ENDOGENOUS_METABOLITE": r"\bendogenous\b", "APPROVED_DRUG": r"\b(?:FDA[- ]approved|approved (?:drug|medicine|by))\b"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_evidence(run_dir, rows):
    """Resolve lookup evidence only from hash-bound files inside this run."""
    from pathlib import Path
    root = Path(run_dir).resolve()
    out = []
    for row in rows:
        row = dict(row)
        if row.get('kind') == 'RECORDED_LOOKUP':
            target = (root / row.get('archive_path', '')).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                continue
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row.get('archive_sha256'):
                continue
            row['archived_text'] = raw.decode('utf-8')
        out.append(row)
    return out


def label_supported(entity, sections, evidence=()):
    """Evidence is a recorded entity/label/quotation binding, never a naked URL.

    Lookup evidence must be supplied by the caller from an archived response and
    have its full text hash checked here; no network lookup or status inference.
    """
    for row in evidence:
        if row.get("entity_id") != entity["entity_id"] or row.get("label") != entity["type"]:
            continue
        if row.get("kind") == "SOURCE_QUOTATION":
            text = sections.get(row.get("section"), "")
        elif row.get("kind") == "RECORDED_LOOKUP":
            # Only locally archived, hash-bound lookup responses supplied by code.
            text = row.get("archived_text", "")
            if not row.get("source_url") or not row.get("archive_path") or hashlib.sha256(text.encode()).hexdigest() != row.get("archive_sha256"):
                continue
        else:
            continue
        quote = row.get("quote", "")
        if (quote and quote in text and entity["mention"].casefold() in quote.casefold()
                and not re.search(r"\b(?:not|never|unapproved|unclear|unknown|unconfirmed)\b|no evidence", quote, re.I)
                and re.search(LABEL_WORDS[entity["type"]], quote, re.I)):
            return True
    return False


def detection_outcome(finding, entity, sections):
    quote = finding.get("span", "")
    section = finding.get("span_location", {}).get("section")
    if not quote or quote not in sections.get(section, ""):
        raise ValueError(f"{finding['finding_id']}: ungrounded detection passage")
    mention = re.escape(entity.get("mention", ""))
    if not mention:
        raise ValueError(f"{finding['finding_id']}: missing specimen entity")
    # Bind the phrase to THIS finding's object. Shared context is not a substitute.
    tail = r"\b" if entity["mention"][-1:].isalnum() else ""
    specimen = mention + tail
    neg = bool(re.search(r"(?:not detected|undetected) in (?:the )?" + specimen + r"|but not in (?:the )?" + specimen, quote, re.I))
    pos = bool(re.search(r"(?<!not )(?<!un)\bdetected in (?:the )?" + specimen, quote, re.I))
    if neg == pos:
        raise ValueError(f"{finding['finding_id']}: detection/specimen link is ambiguous or untested")
    outcome = "NOT_DETECTED_UNDER_REPORTED_CONDITIONS" if neg else "DETECTED_UNDER_REPORTED_CONDITIONS"
    permitted = ("NEGATIVE", "NULL") if neg else ("POSITIVE",)
    if finding.get("polarity") not in permitted:
        raise ValueError(f"{finding['finding_id']}: specimen/polarity contradicts the source")
    if re.search(r"biological absence|molecule (?:was |is )?absent|absent from|proved absence", str(finding.get("predicate_detail", "")) + " " + str(finding.get("warrant_note", "")).replace(NONDETECTION_NOTE, ""), re.I):
        raise ValueError(f"{finding['finding_id']}: non-detection cannot establish biological absence")
    if finding.get("quantities"):
        raise ValueError(f"{finding['finding_id']}: descriptive detection needs quantitative source interpretation")
    return outcome


def interpret(extraction, sections, label_evidence=()):
    ext = copy.deepcopy(extraction)
    audit = {"rule_version": RULE_VERSION, "input_sha256": digest(extraction), "entity_label_defects": [], "findings": {}}
    entities = {e["entity_id"]: e for e in ext.get("entities", [])}
    contexts = {c["context_id"]: c.get("fields", {}) for c in ext.get("contexts", [])}
    for e in entities.values():
        if e.get('drug_status_verified') and not label_supported({**e, 'type':'APPROVED_DRUG'}, sections, label_evidence):
            e.pop('drug_status_verified', None)
            audit['entity_label_defects'].append({'entity_id':e['entity_id'], 'unsupported_label':'drug_status_verified', 'action':'QUARANTINED_LABEL', 'reason':'No entity-bound source or archived lookup evidence for approval flag'})
        if e.get("type") in PROTECTED_LABELS and not label_supported(e, sections, label_evidence):
            old = e["type"]
            e["type"] = PROTECTED_LABELS[old]
            audit["entity_label_defects"].append({"entity_id": e["entity_id"], "unsupported_label": old, "replacement": e["type"], "action": "QUARANTINED_LABEL", "reason": "No entity-bound source or recorded lookup evidence"})
    for f in ext.get("findings", []):
        item = {"rule_version": RULE_VERSION, "comparator": contexts.get(f.get("context_id"), {}).get("comparator", "NONE_REPORTED")}
        if f.get("predicate") == "DETECTED_IN":
            specimen = entities.get(f.get("object_entity_id"))
            if specimen is None:
                raise ValueError(f"{f['finding_id']}: missing specimen reference")
            if f.get('quantities') or item['comparator'] not in ('NOT_APPLICABLE', 'NONE_REPORTED', None):
                # A measured concentration or genuine comparative experiment is
                # not the descriptive detection case. Preserve its comparator,
                # quantities and polarity for A06; never recode it as N/A.
                item.update(specimen_entity_id=specimen['entity_id'], specimen=specimen['mention'], detection_outcome='QUANTITATIVE_OR_COMPARATIVE_NOT_RECODED')
                audit['findings'][f['finding_id']] = item
                continue
            item.update(specimen_entity_id=specimen["entity_id"], specimen=specimen["mention"], detection_outcome=detection_outcome(f, specimen, sections), comparator="NOT_APPLICABLE", comparator_basis="Descriptive specimen-specific detection; no comparative effect claimed")
            if item["detection_outcome"] == "NOT_DETECTED_UNDER_REPORTED_CONDITIONS":
                f["polarity"] = "NEGATIVE"
                note = NONDETECTION_NOTE
                if note not in f.get("warrant_note", ""):
                    f["warrant_note"] = (f.get("warrant_note", "") + " " + note).strip()
        elif f.get("predicate") == "MAXIMUM_TOLERATED_DOSE":
            if any(q.get("value_type") != "DOSE" or re.search("concentration", q.get("measured_property", ""), re.I) for q in f.get("quantities", [])):
                raise ValueError(f"{f['finding_id']}: maximum tolerated dose is not a concentration")
        audit["findings"][f["finding_id"]] = item
    audit["output_sha256"] = digest(ext)
    return ext, audit
