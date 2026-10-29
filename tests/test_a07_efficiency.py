"""Targeted packing regressions. Mocked output tests accounting, never scientific discovery."""
import copy
from collections import Counter
import pytest
from litreview import config
from litreview.synthesis_input import build_manifest
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens
from litreview.synthesis_bounded import RegistrySynthesisJob
from litreview.synthesis_job import JobStopped
from test_synthesis_bounded import corpus, FixtureModel


def source_corpus():
    data=corpus()
    data['theme_records']={f'legacy:{i}':{'evidence_reach':{'summary':f'Source-specific reach {i}',
        'systems_missing':['HUMAN'], 'main_constraints':[f'Constraint {i}']},
        'conflicts':[]} for i in range(33)}
    data['coverage_manifest']=build_manifest(data['selected_corpus'],data['theme_records'],[])
    return data


def run_job(path,data,source_size=16,wrapper=None):
    r=EvidenceRegistry(data)
    model=FixtureModel(r)
    call=wrapper(model) if wrapper else model
    cfg={**config.load('pipeline')['synthesis'],'max_items_per_source_group':source_size}
    j=RegistrySynthesisJob(path,r,call,offline_tokens,cfg,{},lambda *_:True)
    return j,j.run(),model


def test_source_only_consolidation_keeps_every_obligation_and_theme(tmp_path):
    old,a,ma=run_job(tmp_path/'old',source_corpus(),8)
    new,b,mb=run_job(tmp_path/'new',source_corpus())
    assert len([x for x in mb.calls if x[0]=='GROUP']) < len([x for x in ma.calls if x[0]=='GROUP'])
    assert a['status']==b['status']=='COMPLETE'
    assert not b['findings_unaccounted'] and not b['coverage_incomplete_item_ids']
    assert a['global_independence']==b['global_independence']
    assert a['manifest_aliases']==b['manifest_aliases']
    ownership=Counter(i for p in new.packets for i in p['manifest_item_ids'])
    assert set(ownership)==set(new.registry.items) and set(ownership.values())=={1}
    for p in new.packets:
        if p.get('source_only'):
            assert not p['finding_ids'] and len(p['manifest_item_ids'])<=16
            sent=new.registry.packet_payload(p)
            for iid,u in sent['source_items'].items():
                original=new.registry.item_source(iid)
                assert u['item'].get('theme_record')==original['item'].get('theme_record')
                assert 'original_item_id' not in u['item']
                if u['item']['kind']=='SYSTEM_GAP':
                    assert 'source' not in u
                    assert u['item']['source_occurrence_ids']==original['source']['source_occurrence_ids']
                else:assert u['source']==original['source']
    assert len(b['knowledge_gaps'])==len(a['knowledge_gaps'])
    assert a['theme_framework']==b['theme_framework']


def test_packing_checks_all_anchored_candidates():
    data=corpus(1,48)
    data['theme_records']={'T1':{'evidence_reach':{'summary':'All detailed anchors',
        'finding_ids':['R0001:F1','R0001:F48']},'conflicts':[
            {'finding_ids':['R0001:F1','R0001:F48'],'description':f'Conflict {n}'} for n in range(10)]}}
    data['coverage_manifest']=build_manifest(data['selected_corpus'],data['theme_records'],[])
    r=EvidenceRegistry(data)
    packets=r.packets()
    assert len(packets)==2
    assert all(p['primary_theme_id']=='T1' for p in packets)
    assert all(len(p['manifest_item_ids'])<=8 for p in packets)
    assert {i for p in packets for i in p['manifest_item_ids']}==set(r.items)


def test_changed_consolidation_setting_invalidates_resume(tmp_path):
    j,_,_=run_job(tmp_path,source_corpus(),8)
    cfg={**j.cfg,'max_items_per_source_group':16}
    with pytest.raises(JobStopped,match='stale'):
        RegistrySynthesisJob(tmp_path,j.registry,j.call,j.count,cfg,{},lambda *_:True)


def test_consolidated_group_failure_is_atomic_and_resumable(tmp_path):
    r=EvidenceRegistry(source_corpus())
    m=FixtureModel(r)
    def call(mode,payload,turn):
        if mode=='GROUP' and payload['group'].get('source_only'):
            from litreview.agents.base import AgentError
            raise AgentError('truncated source analysis')
        return m(mode,payload,turn)
    cfg=config.load('pipeline')['synthesis']
    j=RegistrySynthesisJob(tmp_path,r,call,offline_tokens,cfg,{},lambda *_:True)
    with pytest.raises(JobStopped,match='truncated'):j.run()
    before=copy.deepcopy(j._all_props())
    pending=set(j._pending())
    assert pending
    resumed=FixtureModel(r)
    j=RegistrySynthesisJob(tmp_path,r,resumed,offline_tokens,cfg,{},lambda *_:True)
    pkg=j.run()
    assert pkg['status']=='COMPLETE' and len(pkg['propositions'])==len(before)
    assert not pkg['coverage_incomplete_item_ids']
    assert all(mode!='PLAN' for mode,_,_ in resumed.calls)


@pytest.mark.parametrize('kind',['SHARED_EVIDENCE','UNRESOLVED_CONTRADICTION'])
def test_consolidated_reconciliation_still_preserves_cross_group_issue(tmp_path,kind):
    from test_synthesis_bounded import header
    r=EvidenceRegistry(source_corpus())
    base=FixtureModel(r)
    def model(mode,payload,turn):
        if mode!='RECONCILE':return base(mode,payload,turn)
        if not payload['retrieved_evidence']['findings']:
            return {**header(mode),'status':'NEEDS_EVIDENCE','reviews':[],'issues':[],
                'retrieval_requests':[{'finding_ids':['R0001:F1','R0002:F1']}]}
        out=base(mode,payload,turn)
        pids=[p['proposition_id'] for p in payload['global_proposition_index'][:2]]
        out['issues']=[{'kind':kind,'proposition_ids':pids,
            'finding_ids':['R0001:F1','R0002:F1'],'limitation':'Supplied shared-study relationship'}]
        for review in out['reviews']:
            if review['proposition_id'] in pids:review['outcome']='ISSUES_IDENTIFIED'
        return out
    j=RegistrySynthesisJob(tmp_path,r,model,offline_tokens,config.load('pipeline')['synthesis'],{},lambda *_:True)
    pkg=j.run()
    assert len(pkg['reconciliation'])==1
    assert all(pkg['propositions'][n]['scientific_limitations'] for n in (0,1))


@pytest.mark.parametrize('source_only',[False,True])
def test_gap_limits_are_enforced_atomically(tmp_path,source_only):
    r=EvidenceRegistry(source_corpus() if source_only else corpus())
    base=FixtureModel(r)
    def model(mode,payload,turn):
        out=base(mode,payload,turn)
        if mode=='GROUP' and bool(payload['group'].get('source_only'))==source_only:
            assert out['knowledge_gaps']
            out['knowledge_gaps']=[copy.deepcopy(out['knowledge_gaps'][0]) for _ in range(17 if source_only else 9)]
        return out
    j=RegistrySynthesisJob(tmp_path,r,model,offline_tokens,config.load('pipeline')['synthesis'],{},lambda *_:True)
    with pytest.raises(JobStopped):j.run()
    assert j._committed('FINAL') is None
    if source_only:
        assert all(not j._committed(f'GROUP_{p["group_id"]}') for p in j.packets if p.get('source_only'))
    else:assert not j._all_props()
