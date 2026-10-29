"""Independent adversarial inputs; scripted outputs test preservation, not discovery."""
import copy
import pytest
from litreview import config
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens
from litreview.synthesis_bounded import RegistrySynthesisJob
from litreview.synthesis_job import JobStopped
from test_synthesis_bounded import corpus, FixtureModel, header


def adversarial():
    data=corpus(4, 1)
    for i,f in enumerate(data['validated_findings']):
        f['predicate']='SYNERGIZES_WITH' if i%2==0 else 'ANTAGONIZES'
        f['constraints']=['Dose and model specific; no clinical efficacy inference']
        data['contexts'][f['context_id']]={'dose':1 if i%2==0 else 1000,
            'unit':'uM' if i%2==0 else 'nM','treatment_arm':'DSF+Cu' if i%2==0 else 'DSF alone',
            'evidence_system':'IN_VITRO_CELLULAR' if i<2 else 'IN_VIVO_ANIMAL',
            'cell_line':'U87' if i%2==0 else 'patient-derived'}
    return data


def test_independent_contexts_and_shared_identity_survive(tmp_path):
    r=EvidenceRegistry(adversarial())
    assert r.theme_of(r.findings['R0001:F1']) != r.theme_of(r.findings['R0002:F1'])
    ids=['R0001:F1','R0002:F1']
    ind=r.independence(ids)
    assert ind['papers']==2 and ind['distinct_explicit_studies']==1
    assert ind['known_cohort_ids']==['SHARED_COHORT']
    assert ind['independent_studies'] is None
    j=RegistrySynthesisJob(tmp_path,r,FixtureModel(r),offline_tokens,config.load('pipeline')['synthesis'],{},lambda *_:True)
    pkg=j.run()
    retained={fid:c for p in pkg['propositions'] for fid,c in p['context_qualifiers'].items()}
    for fid in r.findings:
        assert retained[fid]==r.contexts[r.findings[fid]['context_id']]
    assert r.findings[ids[0]]['predicate'] != r.findings[ids[1]]['predicate']
    # The model did not discover the supplied relationship: empty issues can still complete.
    assert pkg['reconciliation']==[]


def test_reconciliation_rejects_unrelated_retrieved_anchors(tmp_path):
    r=EvidenceRegistry(adversarial())
    base=FixtureModel(r)
    def model(mode,payload,turn):
        if mode!='RECONCILE':return base(mode,payload,turn)
        if not payload['retrieved_evidence']['findings']:
            return {**header(mode),'status':'NEEDS_EVIDENCE','reviews':[],'issues':[],
                    'retrieval_requests':[{'finding_ids':['R0004:F1']}]}
        out=base(mode,payload,turn)
        p=payload['focus'][0]['proposition_id']
        out['issues']=[{'kind':'UNRESOLVED_CONTRADICTION','proposition_ids':[p],
            'finding_ids':['R0004:F1'],'limitation':'Unrelated anchor must not validate this issue'}]
        out['reviews'][0]['outcome']='ISSUES_IDENTIFIED'
        return out
    j=RegistrySynthesisJob(tmp_path,r,model,offline_tokens,config.load('pipeline')['synthesis'],{},lambda *_:True)
    with pytest.raises(JobStopped,match='proposition evidence'):
        j.run()


def test_interruption_after_commit_is_idempotent(tmp_path):
    r=EvidenceRegistry(adversarial())
    base=FixtureModel(r)
    def interrupted(mode,payload,turn):
        if mode=='RECONCILE':raise RuntimeError('simulated interruption')
        return base(mode,payload,turn)
    cfg=config.load('pipeline')['synthesis']
    j=RegistrySynthesisJob(tmp_path,r,interrupted,offline_tokens,cfg,{},lambda *_:True)
    with pytest.raises(RuntimeError,match='interruption'):j.run()
    before=copy.deepcopy(j._all_props())
    resumed=FixtureModel(r)
    j=RegistrySynthesisJob(tmp_path,r,resumed,offline_tokens,cfg,{},lambda *_:True)
    pkg=j.run()
    assert len(pkg['propositions'])==len(before)
    assert all(mode not in ('PLAN','GROUP') for mode,_,_ in resumed.calls)
    assert len({p['proposition_id'] for p in pkg['propositions']})==len(before)


@pytest.mark.parametrize('change',['framework','context','finding'])
def test_registry_changes_invalidate_resume(tmp_path,change):
    data=adversarial()
    cfg=config.load('pipeline')['synthesis']
    r=EvidenceRegistry(data)
    j=RegistrySynthesisJob(tmp_path,r,FixtureModel(r),offline_tokens,cfg,{},lambda *_:True)
    j.run()
    changed=copy.deepcopy(data)
    if change=='framework':changed['theme_framework']['primary_themes'][0]['name']='Changed approval'
    elif change=='context':changed['contexts']['R0001:C1']['dose']=99
    else:changed['validated_findings'][0]['constraints'].append('New restriction')
    r=EvidenceRegistry(changed)
    with pytest.raises(JobStopped,match='stale'):
        RegistrySynthesisJob(tmp_path,r,FixtureModel(r),offline_tokens,cfg,{},lambda *_:True)


def test_bounded_truncation_never_changes_coverage(tmp_path):
    from litreview.agents.base import AgentError
    r=EvidenceRegistry(adversarial())
    base=FixtureModel(r)
    def truncated(mode,payload,turn):
        if mode=='GROUP':raise AgentError('max_tokens: truncated')
        return base(mode,payload,turn)
    j=RegistrySynthesisJob(tmp_path,r,truncated,offline_tokens,config.load('pipeline')['synthesis'],{},lambda *_:True)
    with pytest.raises(JobStopped,match='truncated'):j.run()
    assert not j._all_props()
    assert set(j._pending())==set(r.items)


def test_existing_a10_scope_follows_bounded_proposition_ids(tmp_path):
    from litreview.tools.verification_scope import scope
    r=EvidenceRegistry(adversarial())
    j=RegistrySynthesisJob(tmp_path,r,FixtureModel(r),offline_tokens,config.load('pipeline')['synthesis'],{},lambda *_:True)
    pkg=j.run()
    p=pkg['propositions'][0]
    full,index,stats=scope({}, {'proposition_ids':[p['proposition_id']]},pkg,list(r.findings.values()))
    assert {f['finding_id'] for f in full}=={e['finding_id'] for e in p['evidence']}
    assert len(full)+len(index)==len(r.findings)
