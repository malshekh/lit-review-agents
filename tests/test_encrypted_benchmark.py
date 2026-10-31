"""Synthetic-only encrypted benchmark bookkeeping and Stage 1 release gates."""
import copy
import json
from pathlib import Path
import pytest
from test_pilot_authorization import run, authorize
from litreview import pilot_authorization as pa, evaluation_release as release
from litreview.synthesis_registry import fingerprint
pytestmark = pytest.mark.projection_guard

@pytest.fixture
def encrypted(run):
    meta={'version':'synthetic-v2','sha256':'a'*64,'commit':'synthetic-human-content-commitment',
          'verified_by':'Synthetic reviewer','approved_at':'2026-10-30','human_verified':True,
          'storage_mode':'HUMAN_CONTROLLED_ENCRYPTED','vault_dismounted':True,
          'decryption_control':'HUMAN_ONLY','evaluation_release':'AFTER_FINALIZED_A07_CP3',
          'attestation_id':'synthetic-attestation'}
    pa.record_key(run,meta)
    return run


def test_encrypted_metadata_never_opens_or_resolves_plaintext(encrypted,monkeypatch):
    with monkeypatch.context() as guard:
        def forbidden(*a,**kw): pytest.fail('plaintext access attempted')
        guard.setattr(Path,'read_bytes',forbidden)
        guard.setattr(Path,'resolve',forbidden)
        meta=pa.key_metadata(encrypted)
    assert meta['sha256']=='a'*64 and 'store_path' not in meta


@pytest.mark.parametrize('field,value',[('vault_dismounted',False),('decryption_control','PIPELINE'),
    ('evaluation_release','BEFORE_OUTPUTS'),('human_verified',False),('sha256','bad'),
    ('attestation_id',''),('store_path','C:/not-a-key')])
def test_incomplete_or_plaintext_attestation_rejected(encrypted,field,value):
    original=encrypted.load('pilot_reference_approval.json')
    changed={**original,field:value}
    with pytest.raises(pa.AuthorizationRequired):pa.record_key(encrypted,changed)
    assert encrypted.load('pilot_reference_approval.json')==original


def test_changed_attestation_invalidates_authority_without_key_read(encrypted):
    authorize(encrypted)
    meta=encrypted.load('pilot_reference_approval.json');meta['sha256']='b'*64
    pa.record_key(encrypted,meta)
    with pytest.raises(pa.AuthorizationRequired):pa.require(encrypted,'A02-SP')
    assert not encrypted.budget.reservations()


def test_encrypted_key_never_authorizes_stage2(encrypted):
    authorize(encrypted)
    with pytest.raises(pa.AuthorizationRequired):pa.require(encrypted,'A08-OL')
    assert not encrypted.load('pilot_'+pa.STAGE_2+'.json') and not encrypted.budget.reservations()


def test_missing_real_cp3_blocks_evaluation(encrypted):
    with pytest.raises(release.EvaluationNotReady):release.seal_stage1(encrypted)
    encrypted.save_state({'stage':'cp3','execution_mode':'STAGED_PILOT'})
    with pytest.raises(release.EvaluationNotReady,match='scientific CP3'):release.seal_stage1(encrypted)


@pytest.fixture
def finalized(encrypted,monkeypatch):
    # Isolate seal mechanics. Scientific CP3 correctness is exercised unmocked by
    # test_scientific_integrity_gates; no real reference answers are used here.
    r=encrypted;r.save_state({'stage':'cp3','execution_mode':'STAGED_PILOT'})
    for name in ('synthesis_package.json','synthesis_approved.json','validated_findings.json','selected_corpus.json'):
        r.save(name,{'synthetic':name})
    cp=r.dir/'checkpoints';cp.mkdir(exist_ok=True)
    (cp/'CP3_approved.json').write_text(json.dumps({'synthetic':'approved'}))
    out=r.dir/'outputs';out.mkdir();(out/'A07_fixture.json').write_text('{"synthetic":"accepted"}')
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{'synthetic':'already validated by separate gate'})
    return r


def test_seal_required_before_evaluation_and_grants_no_key_access(finalized):
    with pytest.raises(release.EvaluationNotReady):release.require_finalized_stage1(finalized)
    seal=release.seal_stage1(finalized)
    assert seal['key_access_granted'] is False
    assert release.require_finalized_stage1(finalized)==seal
    assert seal['snapshot']['reference']['storage_mode']=='HUMAN_CONTROLLED_ENCRYPTED'


@pytest.mark.parametrize('relative',['outputs/A07_fixture.json','checkpoints/CP3_approved.json',
                                    'data/synthesis_approved.json','data/validated_findings.json'])
def test_changed_finalized_output_or_cp3_invalidates_seal(finalized,relative):
    release.seal_stage1(finalized)
    (finalized.dir/relative).write_text('{"synthetic":"changed"}')
    with pytest.raises(release.EvaluationNotReady):release.require_finalized_stage1(finalized)


def test_outstanding_hold_blocks_evaluation(finalized):
    finalized.budget.reserve('synthetic-hold',1,'A07-SYN')
    with pytest.raises(release.EvaluationNotReady,match='commitments'):release.seal_stage1(finalized)


def test_tampered_seal_is_rejected(finalized):
    seal=release.seal_stage1(finalized);seal['fingerprint']='0'*64
    finalized.save('evaluation/stage1_seal.json',seal)
    with pytest.raises(release.EvaluationNotReady):release.require_finalized_stage1(finalized)
