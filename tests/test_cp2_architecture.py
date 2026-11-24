"""Orchestrator-level acceptance tests. Only synthetic sources and mocked providers."""
import copy
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from litreview import checkpoints, corpus_policy as policy, evaluation_budget as eb, orchestrator as orch, pilot_authorization as pa
from litreview.tools import fulltext
from litreview.tools.literature.base import Record, SearchResult
from litreview.agents import base
from litreview.llm.base import LLMResponse
from test_pilot_authorization import run, authorize
from test_cp2_integrity import xml, plan
pytestmark = pytest.mark.projection_guard


def records():
    return [{'record_id':'R0001','pmid':'34638842','pmcid':'PMC8508702','title':'Synthetic Liu','abstract':'Synthetic abstract'},
            {'record_id':'R0002','pmid':'30771200','title':'Synthetic Huang','abstract':'Synthetic abstract'},
            {'record_id':'R0003','pmid':'27006494','title':'Synthetic Lun','abstract':'Synthetic abstract'}]


def prepare(r, stage):
    r.save_state({**r.state(),'stage':stage})
    r.save('spec_approved.json',{'researcher_decision':{'selected_option_id':'P1'},'corpus_policy':policy.resolve(r)})
    r.save('theme_framework.json',{'primary_themes':[{'theme_id':f'T{i}'} for i in range(1,6)]})
    r.save('records.json',records())
    r.save('qualifications.json',[{'record_id':x['record_id'],'disposition':'QUALIFIED','role':'PRIMARY','themes':[],
          'flags':[],'is_contrary_evidence':x['record_id']=='R0002'} for x in records()])


def provider(r, monkeypatch, output):
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs)
        result=output(kwargs) if callable(output) else output
        return LLMResponse(json.dumps(result),'openai',kwargs['model'],10,10,'end_turn')
    monkeypatch.setattr(base,'complete',complete)
    monkeypatch.setattr(base,'validate',lambda *a,**k:None)  # output semantics not claimed; real run/finance boundaries exercised
    monkeypatch.setattr(r,'_context_check',lambda *a,**k:{'input_counted':100,'input_byte_bound':100,'output_reserve':32000})
    monkeypatch.setattr(r,'_context_actual',lambda *a,**k:None)
    monkeypatch.setattr(orch.model_record,'add',lambda *a,**k:None)
    monkeypatch.setattr(orch.notify,'send',lambda *a,**k:None)
    return calls


def test_policy_preexists_cp1_and_cp1_must_confirm(run):
    p=policy.resolve(run)
    assert p['mode']=='FIXED_CORPUS' and not p['broad_discovery'] and not p['citation_expansion']
    checkpoints.write_cp1(run.dir,{'theme_framework':{},'selection_criteria':{}})
    path=run.dir/'checkpoints/CP1_decision.json'
    d=json.loads(path.read_text());d.update(selected_option_id='P1',approve_selection_criteria=True)
    path.write_text(json.dumps(d))
    with pytest.raises(checkpoints.DecisionIncomplete,match='corpus authority'):checkpoints.approve(run.dir,'CP1',run.prov)
    d['confirm_corpus_policy']=True;path.write_text(json.dumps(d))
    checkpoints.approve(run.dir,'CP1',run.prov)
    assert policy.resolve(orch.Run(run.id))==p


def test_fixed_mode_cannot_be_downgraded_on_resume(run,monkeypatch):
    prepare(run,'expand');run.save_state({**run.state(),'execution_mode':'STANDARD'})
    calls=provider(run,monkeypatch,{})
    with pytest.raises(ValueError,match='downgraded'):run.run()
    assert calls==[]


def test_policy_file_mutation_blocks_dispatch(run,monkeypatch):
    path=run.dir/'input/corpus_policy.json';p=json.loads(path.read_text());p['citation_expansion']=True;path.write_text(json.dumps(p))
    calls=provider(run,monkeypatch,{})
    with pytest.raises(orch.Pause,match='policy'):run.agent('A03-LM',{},'forged')
    assert calls==[]


def test_real_run_contrary_record_never_dispatches_expansion(run,monkeypatch):
    prepare(run,'expand');authorize(run)
    calls=provider(run,monkeypatch,{})
    monkeypatch.setattr(orch,'expand',lambda *a,**k:pytest.fail('out-of-corpus request'))
    assert 'stopped before cp2' in run.run(until='cp2')
    assert calls==[] and len(run.load('records.json'))==3


def test_a03_human_input_stops_real_run_and_resume_reuses_response(run,monkeypatch):
    prepare(run,'search');authorize(run)
    calls=provider(run,monkeypatch,{**plan(),'status':'NEEDS_HUMAN_INPUT','warnings':['Synthetic unresolved source identity']})
    fetched=[]
    def search(*args):
        fetched.append(args)
        return SearchResult('pubmed','QF01','q',3,[Record('pubmed',r['title'],abstract=r['abstract'],pmid=r['pmid'],pmcid=r.get('pmcid')) for r in records()])
    monkeypatch.setattr(orch,'search',search)
    assert 'CP_AGENT_REVIEW' in run.run(until='qualify')
    assert fetched==[] and len(calls)==1
    dpath=run.dir/'checkpoints/CP_AGENT_REVIEW_decision.json';d=json.loads(dpath.read_text())
    d.update(approve_continue=True,notes='Synthetic human resolves the precise source issue within fixed policy.')
    dpath.write_text(json.dumps(d));checkpoints.approve(run.dir,'CP_AGENT_REVIEW',run.prov)
    assert 'stopped before qualify' in run.run(until='qualify')
    assert len(calls)==1 and len(fetched)==1  # accepted response not paid/generated again


def test_a03_receives_answered_permissions_without_another_checkpoint(run,monkeypatch):
    prepare(run,'search');authorize(run)
    calls=provider(run,monkeypatch,{**plan(),'status':'COMPLETE'})
    seen=[]
    original=orch.run_agent
    def observed(agent,payload,*args,**kwargs):
        seen.append(payload);return original(agent,payload,*args,**kwargs)
    monkeypatch.setattr(orch,'run_agent',observed)
    monkeypatch.setattr(orch,'search',lambda *a:SearchResult('pubmed','QF01','q',3,[Record('pubmed',r['title'],abstract=r['abstract'],pmid=r['pmid']) for r in records()]))
    assert 'stopped before qualify' in run.run(until='qualify')
    assert seen[0]['corpus_policy']['mode']=='FIXED_CORPUS' and seen[0]['corpus_policy']['broad_discovery'] is False
    assert not (run.dir/'checkpoints/CP_AGENT_REVIEW_state.json').exists() and len(calls)==1


def test_wrong_huang_membership_claim_cannot_change_canonical_membership(run,monkeypatch):
    prepare(run,'qualify');run.save('qualifications.json',[]);authorize(run)
    out={'status':'COMPLETE_WITH_WARNINGS','qualifications':[{'record_id':r['record_id'],'disposition':'QUALIFIED',
        'in_fixed_corpus':False,'themes':[],'flags':[]} for r in records()],
        'human_review_queue':[{'record_id':'R0002','question':'R0002 is not in the corpus (deliberately false fixture).'}]}
    calls=provider(run,monkeypatch,out)
    run.run(until='cp2')
    assert len(calls)==1
    assert all(q['in_fixed_corpus'] is True for q in run.load('qualifications.json'))
    registry=run.load('corpus_membership.json');huang=next(r for r in registry if r['record_id']=='R0002')
    assert huang['pmid']=='30771200' and huang['in_fixed_corpus'] is True
    assert run.load('screening_review.json')['B001']['membership_claim_conflicts']


def test_six_actual_questions_and_criteria_defect_reach_real_checkpoint(run,monkeypatch):
    prepare(run,'cp2')
    issues=json.loads((Path(__file__).parent/'fixtures/cp2_incident_review_questions.json').read_text(encoding='utf8'))
    run.save('screening_review.json',issues);authorize(run)
    calls=provider(run,monkeypatch,{})
    assert 'waiting for CP2' in run.run()
    text=(run.dir/'checkpoints/CP2_review.md').read_text(encoding='utf8')
    questions=[q for o in issues.values() for q in o['human_review_queue']]
    assert len(questions)==6 and all(q['question'] in text and q['why_consequential'] in text for q in questions)
    assert all(d['defect'] in text for o in issues.values() for d in o['criteria_defects'])
    assert calls==[]


@pytest.mark.parametrize('missing',['table','legend','methods','wrong_pmc'])
def test_real_extract_loop_blocks_incomplete_source_before_provider(run,monkeypatch,missing):
    import xml.etree.ElementTree as E
    prepare(run,'extract');run.save('selected_corpus.json',records());authorize(run)
    tree=E.fromstring(xml())
    if missing=='table':
        node=tree.find('.//table-wrap');next(p for p in tree.iter() if node in list(p)).remove(node)
    elif missing=='legend':tree.find('.//fig').remove(tree.find('.//fig/caption'))
    elif missing=='methods':tree.find('./body').remove(tree.find('./body/sec'))
    else:
        rows=run.load('selected_corpus.json');rows[0]['pmcid']='PMC99999';run.save('selected_corpus.json',rows)
        authorize(run)  # synthetic finance cannot waive source identity
    gets=[]
    monkeypatch.setattr(fulltext.requests,'get',lambda *a,**k:gets.append(a) or NS(status_code=200,content=E.tostring(tree)))
    calls=provider(run,monkeypatch,{})
    assert 'Required verified full text unavailable' in run.run(until='validate')
    assert calls==[] and (len(gets)==0 if missing=='wrong_pmc' else len(gets)==1)


def test_cp1_and_cp2_changes_invalidate_financial_identity(run):
    prepare(run,'cp1');old=authorize(run)
    run.save('spec.json',run.load('spec_approved.json'))
    checkpoints.write_cp1(run.dir,run.load('spec.json'))
    path=run.dir/'checkpoints/CP1_decision.json';d=json.loads(path.read_text());d.update(selected_option_id='P1',approve_selection_criteria=True,confirm_corpus_policy=True)
    path.write_text(json.dumps(d));checkpoints.approve(run.dir,'CP1',run.prov)
    run.stage_cp1(run.state())
    with pytest.raises(pa.AuthorizationRequired):pa.require(run,'A03-LM')
    second=authorize(run);assert second['fingerprint']!=old['fingerprint']
    run.save_state({**run.state(),'stage':'cp2'})
    checkpoints.write_cp2(run.dir,records(),run.load('qualifications.json'),{})
    csvpath=run.dir/'checkpoints/CP2_records.csv';rows=list(csv.DictReader(csvpath.open()))
    for row in rows:row['select']='Y'
    with csvpath.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    checkpoints.approve(run.dir,'CP2',run.prov);run.stage_cp2(run.state())
    with pytest.raises(pa.AuthorizationRequired):pa.require(run,'A05-KE')
    assert not run.load('pilot_'+pa.STAGE_2+'.json')


def prior_authority(tmp_path):
    parent=tmp_path/'incident';parent.mkdir()
    events=[{'provider':'openai','cost_usd':.0402335},{'provider':'openai','cost_usd':.0374235},
            {'provider':'anthropic','cost_usd':.0041179},{'provider':'anthropic','cost_usd':.009285},
            {'provider':'anthropic','cost_usd':.0061615}]
    raw=''.join(json.dumps(e)+'\n' for e in events).encode();p=parent/'costs.jsonl';p.write_bytes(raw)
    value={'evaluation_id':'synthetic-existing-evaluation','reviewed_by':'Synthetic human','cap_usd':35,'review_usd':25,'future_margin':.30,
      'restart_of':'incident','prior_ledgers':[{'run_id':'incident','path':str(p),'sha256':hashlib.sha256(raw).hexdigest()}],
      'prior_events':[{'event_id':eb.digest(e),'run_id':'incident','provider':e['provider'],'cost_usd':e['cost_usd']} for e in events]}
    a=tmp_path/'reviewed-authority.json';a.write_text(json.dumps(value));return a,value,events


def test_cumulative_costs_count_once_under_real_budget_and_projection(run,tmp_path):
    a,value,events=prior_authority(tmp_path)
    (run.dir/'input/evaluation_budget.json').write_text(json.dumps(eb.prepare(a)))
    prepare(run,'cp2')
    assert run.budget.spent()==pytest.approx(.0972214)
    p=pa.project(run,pa.STAGE_1)
    assert p['projected_total_usd']==pytest.approx(.0972214+1.3*p['uncommitted_future_usd']) and run.budget.cap==35
    assert run.cfg['run']['spend_review_usd']==25
    run.budget.log_path.write_text(json.dumps(events[0])+'\n')
    from litreview.budget import BudgetExceeded
    with pytest.raises(BudgetExceeded,match='duplicated'):run.budget.spent()


def test_budget_authority_cannot_omit_parent_or_create_silent_fresh_allowance(tmp_path,monkeypatch):
    a,value,events=prior_authority(tmp_path)
    value['prior_events']=value['prior_events'][1:];a.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='omitted'):eb.prepare(a)
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path/'must-not-exist')
    with pytest.raises(ValueError,match='authority'):orch.new_run('synthetic only')
    assert not (tmp_path/'must-not-exist').exists()


def test_open_mode_requires_explicit_configuration_and_budget_review(tmp_path,monkeypatch):
    from corpus_fixture import authority
    a=authority(tmp_path/'open-authority.json');v=json.loads(a.read_text());v['corpus_mode']='OPEN_CORPUS';a.write_text(json.dumps(v))
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path/'runs')
    rid=orch.new_run('synthetic open corpus',budget_authority=a,corpus_mode='OPEN_CORPUS');r=orch.Run(rid)
    assert policy.fixed(r)=={} and policy.resolve(r)['broad_discovery'] is True
    r.save_state({**r.state(),'stage':'expand'})
    r.save('records.json',records());r.save('qualifications.json',[{'record_id':'R0002','role':'PRIMARY','disposition':'QUALIFIED','is_contrary_evidence':True}])
    r.save('search_plan.json',{'citation_expansion_seed_families':[]})
    monkeypatch.setattr(r,'_qualify_pending',lambda:None)
    calls=[];monkeypatch.setattr(orch,'expand',lambda *a,**k:calls.append(a) or ([],[]))
    r.stage_expand(r.state());assert len(calls)==1


def test_ambiguous_internal_mapping_cannot_reach_a04(run,monkeypatch):
    prepare(run,'qualify');authorize(run);rows=run.load('records.json');rows[1]['record_id']='R0001';run.save('records.json',rows)
    calls=provider(run,monkeypatch,{})
    assert 'Ambiguous internal' in run.run(until='cp2') and calls==[]


def test_actual_run_stage2_attempt_remains_blocked(run,monkeypatch):
    prepare(run,'cp3');authorize(run)
    calls=provider(run,monkeypatch,{})
    monkeypatch.setattr(run,'stage_cp3',lambda state:'outline')
    monkeypatch.setattr(pa,'scientific_ready',lambda r:{})  # isolate financial boundary; no claim of CP3 validity
    monkeypatch.setattr(run,'stage_outline',lambda state:pytest.fail('Stage2 handler entered'))
    assert 'FULL_PIPELINE_AUTHORIZED' in run.run() and calls==[]
    assert not run.load('pilot_'+pa.STAGE_2+'.json') and not run.budget.reservations()


def test_clean_run_scope_configuration_is_not_inherited_checkpoint(tmp_path,monkeypatch):
    from corpus_fixture import authority
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path/'runs')
    config={'parent_run_id':'synthetic-parent','parent_cp1_sha256':'a'*64,'perspective':'P1','qualifications':['Synthetic human qualification']}
    rid=orch.new_run('synthetic',budget_authority=authority(tmp_path/'authority.json'),scope_configuration=config)
    r=orch.Run(rid)
    assert json.loads((r.dir/'input/human_scope_configuration.json').read_text())==config
    assert not (r.dir/'checkpoints/CP1_approved.json').exists() and r.state()['stage']=='scope'


def test_missing_policy_or_budget_cannot_silently_resume(run,monkeypatch):
    prepare(run,'search');authorize(run)
    (run.dir/'input/corpus_policy.json').unlink()
    calls=provider(run,monkeypatch,{})
    with pytest.raises(ValueError,match='persisted corpus policy'):run.run()
    assert calls==[]


def test_verified_fulltext_screening_survives_financial_pause_without_refetch(run,monkeypatch):
    prepare(run,'qualify')
    qs=run.load('qualifications.json');qs[0]['disposition']='UNRESOLVED_FULL_TEXT_REQUIRED';run.save('qualifications.json',qs)
    authorize(run);gets=[]
    monkeypatch.setattr(fulltext.requests,'get',lambda *a,**k:gets.append(a) or NS(status_code=200,content=xml()))
    calls=provider(run,monkeypatch,{'status':'COMPLETE','qualifications':[{'record_id':'R0001','disposition':'QUALIFIED','themes':[],'flags':[]}]})
    assert 'Missing/stale STAGE_1_AUTHORIZED' in run.run(until='cp2')
    assert len(gets)==1 and calls==[]
    source=run.load('fulltext_provenance/R0001.json')
    authorize(run)
    assert 'stopped before cp2' in run.run(until='cp2')
    assert len(gets)==1 and len(calls)==1 and run.load('fulltext_provenance/R0001.json')==source


def test_structured_source_retains_verbatim_spans_without_json_escaping():
    import xml.etree.ElementTree as E
    tree=E.fromstring(xml());caption='Synthetic "quoted" legend, not a scientific finding.'
    tree.find('.//fig/caption/p').text=caption
    sections=fulltext._sections(tree,strict=True)
    assert sections['Verbatim figure legend Figure 1']==caption
    table=json.loads(sections['Table Table 1'])
    assert table['rows'][1]==['Synthetic row','12.3']
    assert '12.3' in sections['Verbatim table Table 1']
