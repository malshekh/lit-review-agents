"""Deterministic boundaries for the explicitly staged, three-publication pilot.

Scientific prose never overrides these identifier/access constraints. Open-corpus
legacy runs retain their existing discovery behavior.
"""
import re
from . import pilot_authorization as pilot


def default_policy(mode="FIXED_CORPUS"):
    if mode not in {"FIXED_CORPUS", "OPEN_CORPUS"}:
        raise ValueError("Unknown corpus mode")
    papers = [{**p, **({"pmcid": "PMC8508702"} if p["pmid"] == "34638842" else {})} for p in pilot.PAPERS]
    return {"mode": mode, "papers": papers if mode == "FIXED_CORPUS" else [],
            "broad_discovery": mode == "OPEN_CORPUS", "citation_expansion": mode == "OPEN_CORPUS"}


def initialize(run_dir, policy=None):
    import json
    from pathlib import Path
    from .synthesis_registry import fingerprint
    path = Path(run_dir) / "input/corpus_policy.json"
    if path.exists():
        raise ValueError("Corpus authority already established; create a separately reviewed run")
    policy = policy or default_policy()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, sort_keys=True, indent=2), encoding="utf-8")
    return fingerprint(policy)


def resolve(run):
    from .synthesis_registry import fingerprint
    policy = run.dir / "input/corpus_policy.json"
    if not policy.exists():
        if pilot.enabled(run):
            raise ValueError("Explicit persisted corpus policy required; do not retroactively upgrade an incident run")
        return None
    import json
    value = json.loads(policy.read_text(encoding="utf-8"))
    if value.get("mode") not in {"FIXED_CORPUS", "OPEN_CORPUS"} or run.state().get("corpus_policy_fingerprint") != fingerprint(value):
        raise ValueError("Corpus policy missing/stale; researcher resolution required")
    if value["mode"] == "FIXED_CORPUS" and not pilot.enabled(run):
        raise ValueError("Fixed corpus cannot be downgraded to non-pilot execution")
    if value["mode"] == "OPEN_CORPUS" and pilot.enabled(run):
        raise ValueError("Open discovery cannot masquerade as the fixed staged pilot")
    if value["mode"] == "FIXED_CORPUS":
        expected = default_policy()
        if value != expected:
            raise ValueError("Fixed pilot identifiers/access/expansion authority changed")
    elif value.get("broad_discovery") is not True or value.get("citation_expansion") is not True:
        raise ValueError("Explicit open-corpus discovery authority required")
    return value


def fixed(run):
    policy = resolve(run)
    return {p["pmid"]: p["content_level"] for p in policy["papers"]} if policy and policy["mode"] == "FIXED_CORPUS" else {}


def require_source(run, record):
    policy = resolve(run)
    if not policy or policy["mode"] != "FIXED_CORPUS":
        return
    expected = next((p for p in policy["papers"] if p["pmid"] == str(record.get("pmid"))), None)
    if not expected or expected["content_level"] != "FULL_TEXT" or record.get("pmcid") != expected.get("pmcid"):
        raise ValueError("Full-text retrieval is not authorized for this publication/source identifier")


def require_records(run, records, internal_ids=False):
    allowed = fixed(run)
    if not allowed:
        return
    ids = [str(r.get("pmid") or "") for r in records]
    if internal_ids:
        local = [r.get("record_id") for r in records]
        if any(not isinstance(x, str) or not re.fullmatch(r"R\d+", x) for x in local) or len(set(local)) != len(local):
            raise ValueError("Ambiguous internal record ID / external publication ID mapping")
    for key in ("doi", "pmcid"):
        values = [str(r[key]).lower() for r in records if r.get(key)]
        if len(values) != len(set(values)):
            raise ValueError("Conflicting publication-identifier mapping requires human resolution")
    if any(pmid not in allowed for pmid in ids) or len(ids) != len(set(ids)):
        raise ValueError("Fixed corpus: unexpected/missing/duplicate PMID; no screening or expansion permitted")


def require_query(run, source, family, query):
    allowed = fixed(run)
    if not allowed:
        return
    if family.get("purpose") != "KNOWN_ITEM":
        raise ValueError("Fixed corpus permits identifier-only KNOWN_ITEM retrieval")
    text = query.strip()
    if source == "pubmed":
        pattern = r"\(?\s*\d+\[PMID\](?:\s+OR\s+\d+\[PMID\])*\s*\)?"
        ids = re.findall(r"(\d+)\[PMID\]", text, flags=re.I)
    elif source == "europepmc":
        pattern = r"SRC:MED\s+AND\s+\(\s*EXT_ID:\d+(?:\s+OR\s+EXT_ID:\d+)*\s*\)"
        ids = re.findall(r"EXT_ID:(\d+)", text, flags=re.I)
    else:
        raise ValueError("Fixed corpus retrieval source not supported; human review required")
    if not re.fullmatch(pattern, text, flags=re.I) or not ids or not set(ids) <= set(allowed):
        raise ValueError("Fixed corpus query contains unapproved identifiers or discovery terms")


def registry(records, allowed):
    return [{"record_id": r["record_id"], "pmid": str(r.get("pmid") or ""),
             "doi": r.get("doi"), "in_fixed_corpus": (str(r.get("pmid") or "") in allowed) if allowed else None,
             "required_access": allowed.get(str(r.get("pmid") or ""))} for r in records]
