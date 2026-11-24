"""Deterministic A06 acceptance and provenance contracts; no scientific interpretation."""
from .synthesis_registry import fingerprint

DISPOSITIONS = frozenset({'SUPPORTED', 'SUPPORTED_WITH_CONSTRAINTS', 'SUPPORTED_FOR_OBSERVATION',
    'PARTIALLY_SUPPORTED', 'DOES_NOT_ESTABLISH', 'BLOCKED_PROVENANCE', 'BLOCKED_ALIGNMENT',
    'HUMAN_REVIEW_REQUIRED', 'UNRESOLVED_SOURCE_ACCESS'})


def require_complete(doc, extraction, record_id=None):
    # Older stored documents omit shared header fields. Their finding contract is
    # still checked; new provider responses also pass the mode-specific JSON schema.
    if not isinstance(doc, dict):raise ValueError('A06 response is not an object')
    if doc.get('mode', 'PER_PAPER') != 'PER_PAPER':
        raise ValueError('expected A06 PER_PAPER validation')
    if doc.get('status', 'COMPLETE') not in ('COMPLETE', 'COMPLETE_WITH_WARNINGS'):
        raise ValueError('A06 validation is not complete')
    if record_id and doc.get('record_id', record_id) != record_id:
        raise ValueError('A06 record identity mismatch')
    submitted = [f['finding_id'] for f in extraction.get('findings', [])]
    entries = doc.get('validations')
    if not isinstance(entries, list) or len(set(submitted)) != len(submitted):
        raise ValueError('A06 missing validations or duplicated extraction IDs')
    ids = [v.get('finding_id') for v in entries if isinstance(v, dict)]
    if any(not isinstance(i,str) or not i for i in ids):raise ValueError('A06 invalid finding ID')
    if len(ids) != len(entries) or len(ids) != len(set(ids)) or set(ids) != set(submitted):
        raise ValueError('A06 missing, duplicate or unexpected finding dispositions')
    for v in entries:
        if not isinstance(v.get('disposition'),str) or v['disposition'] not in DISPOSITIONS:
            raise ValueError('A06 invalid disposition')
        if 'constraints' in v and (not isinstance(v['constraints'],list)
                or any(not isinstance(c,str) for c in v['constraints'])):
            raise ValueError('A06 malformed scientific constraints')
        if v['disposition'] in ('HUMAN_REVIEW_REQUIRED', 'UNRESOLVED_SOURCE_ACCESS'):
            if not (v.get('plain_language_limit') or v.get('reason')):
                raise ValueError('A06 unresolved outcome requires a reason')
    for key in ('defect_reports','source_inconsistencies','normalization_conflicts'):
        if not isinstance(doc.get(key, []),list) or any(not isinstance(x,dict) for x in doc.get(key, [])):
            raise ValueError('A06 malformed scientific annotations')
    for obj in doc.get('defect_reports', []):
        if obj.get('finding_id') not in set(submitted):
            raise ValueError('A06 defect references unknown finding')
    for obj in doc.get('source_inconsistencies', []) + doc.get('normalization_conflicts', []):
        if set(obj.get('finding_ids', [])) - set(submitted):
            raise ValueError('A06 scientific annotation references unknown finding')


def source_fingerprint(sections):
    return fingerprint(sections)


def require_theme(doc, theme, findings):
    if doc.get('mode') != 'PER_THEME' or doc.get('theme') != theme:
        raise ValueError('A06 theme identity mismatch')
    if doc.get('status') not in ('COMPLETE', 'COMPLETE_WITH_WARNINGS'):
        raise ValueError('A06 theme validation incomplete')
    if (not isinstance(doc.get('conflicts'), list) or not isinstance(doc.get('independence'), list)
            or not isinstance(doc.get('evidence_reach'), dict)):
        raise ValueError('A06 theme validation missing scientific results')
    allowed = {f['finding_id'] for f in findings}
    for conflict in doc.get('conflicts', []):
        if not conflict.get('finding_ids') or set(conflict['finding_ids']) - allowed:
            raise ValueError('A06 theme conflict references unknown findings')


def require_package(pkg, findings):
    from . import evidence
    if (pkg.get('status') != 'COMPLETE' or pkg.get('coverage_incomplete_item_ids')
            or pkg.get('findings_unaccounted')):
        raise ValueError('incomplete synthesis or mandatory coverage')
    fs = {f['finding_id']:f for f in findings}
    record_of = {fid:f['record_id'] for fid,f in fs.items()}
    props = pkg.get('propositions', [])
    ids = [p['proposition_id'] for p in props]
    if len(ids) != len(set(ids)):raise ValueError('duplicate proposition IDs')
    if 'manifest_aliases' in pkg:
        coverage = pkg.get('coverage_realization', [])
        item_ids = [c['manifest_item_id'] for c in coverage]
        if len(item_ids) != len(set(item_ids)) or set(item_ids) != set(pkg['manifest_aliases']):
            raise ValueError('synthesis mandatory accounting incomplete')
        anchors = set(ids) | {g['gap_id'] for g in pkg.get('knowledge_gaps', [])}
        for c in coverage:
            by = c.get('satisfied_by')
            by = by if isinstance(by,list) else [by]
            if c.get('status') != 'SATISFIED' or not by or any(x not in anchors for x in by):
                raise ValueError('synthesis mandatory coverage not satisfied')
        dispositions = pkg.get('finding_dispositions', {})
        if set(dispositions) != set(fs) or any(not v or 'UNACCOUNTED' in v for v in dispositions.values()):
            raise ValueError('synthesis finding accounting incomplete')
    for p in props:
        problems = evidence.link_problems(p, fs, record_of)
        if problems:raise ValueError('invalid synthesis evidence: ' + '; '.join(problems))
    for obj in props + pkg.get('knowledge_gaps', []):
        if set(obj.get('source_item_ids', [])) - set(pkg.get('source_items', {})):
            raise ValueError('unknown synthesis source item')
        if set(obj.get('premise_proposition_ids', [])) - set(ids):
            raise ValueError('unknown synthesis proposition reference')
        # bounded A07 (A07-SYN prompt and RegistrySynthesisJob.group): a gap is established by eligible FINDING IDs;
        # legacy packages named propositions. Anything else, or an ineligible finding, is refused.
        for ref in obj.get('established_by', []):
            if ref in fs:
                if evidence.status_of(fs[ref]) != 'SUPPORTING':
                    raise ValueError(f'gap established by ineligible finding {ref}')
            elif ref not in ids:
                raise ValueError('unknown synthesis proposition or finding reference')
