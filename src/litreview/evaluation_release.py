"""Fingerprint finalized Stage 1 outputs before independent benchmark evaluation.

This module never opens a reference key or mounts/decrypts a vault. A seal permits
export of scientific outputs for evaluation; it grants no financial authority.
"""
import hashlib
from . import pilot_authorization as pilot
from .synthesis_registry import fingerprint


class EvaluationNotReady(ValueError):
    pass


def _snapshot(run):
    if run.state().get('stage') != 'cp3':
        raise EvaluationNotReady('Stage 1 must be finalized at CP3')
    if run.budget.reservations():
        raise EvaluationNotReady('Unsettled financial commitments block finalization')
    try:
        pilot.scientific_ready(run)
    except (ValueError, OSError, KeyError) as exc:
        raise EvaluationNotReady('Current scientific CP3 approval and complete A07 evidence required') from exc
    required = ('data/synthesis_package.json', 'data/synthesis_approved.json',
                'data/validated_findings.json', 'data/selected_corpus.json',
                'checkpoints/CP3_approved.json')
    paths = {run.dir / name for name in required}
    if any(not p.is_file() for p in paths):
        raise EvaluationNotReady('Missing finalized Stage 1 artifact')
    for folder in ('input', 'outputs', 'checkpoints', 'data/extractions', 'data/validations', 'data/fulltext', 'data/fulltext_provenance'):
        paths.update(p for p in (run.dir / folder).rglob('*') if p.is_file())
    # Include all A07 job state so a changed accepted turn invalidates the seal.
    for job in (run.dir / 'data').glob('synthesis_job_*'):
        paths.update(p for p in job.rglob('*') if p.is_file())
    for name in ('spec_approved.json', 'theme_framework.json', 'theme_records.json', 'source_readiness.json', 'corpus_membership.json'):
        p = run.dir / 'data' / name
        if p.exists(): paths.add(p)
    for p in paths:
        if p.is_symlink() or not p.resolve().is_relative_to(run.dir.resolve()):
            raise EvaluationNotReady('Finalized artifact escapes run directory')
    files = {}
    for p in sorted(paths):
        digest = hashlib.sha256()
        with p.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        files[str(p.relative_to(run.dir))] = digest.hexdigest()
    return {'run_id':run.id, 'files':files,
            'reference':pilot.key_metadata(run),
            'scientific_basis':pilot.work_basis(run)}


def seal_stage1(run):
    before = _snapshot(run)
    if _snapshot(run) != before:
        raise EvaluationNotReady('Scientific outputs changed during finalization')
    seal = {'status':'FINALIZED_A07_CP3', 'snapshot':before,
            'fingerprint':fingerprint(before), 'key_access_granted':False}
    run.save('evaluation/stage1_seal.json', seal)
    return seal


def require_finalized_stage1(run):
    seal = run.load('evaluation/stage1_seal.json') or {}
    if (seal.get('status') != 'FINALIZED_A07_CP3'
            or seal.get('fingerprint') != fingerprint(seal.get('snapshot'))
            or fingerprint(_snapshot(run)) != seal['fingerprint']):
        raise EvaluationNotReady('Missing or stale finalized Stage 1 seal')
    return seal
