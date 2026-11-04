import copy
import json
import pytest
from litreview import a06_batches as b,orchestrator as orch
from litreview.agents.base import AgentError
from litreview.synthesis_registry import fingerprint
from test_pilot_authorization import run

@pytest.fixture
def ready(run):
    r=run;r.cfg=copy.deepcopy(r.cfg);r.cfg['validation']['findings_per_call']=15;r.cfg['validation']['truncation_retries']=1
    r.save_state({**r.state(),'stage':'validate'})
    source={'Abstract':'Synthetic study','Results':'Synthetic finding.','Methods':'Synthetic conditions.'}
    ext={'record_id':'R0001','content_level':'FULL_TEXT','entities':[{'entity_id':'E1','mention':'Synthetic entity'}],
         'contexts':[{'context_id':'C1','intervention':{'entity_id':'E1'}}],
         'findings':[{'finding_id':'F'+str(i),'subject_entity_id':'E1','object_entity_id':None,'context_id':'C1','span':'Synthetic finding.','predicate':'OBSERVED_OUTCOME'} for i in range(1,38)]}
    r.save('fulltext/R0001.json',source)
    payload={'mode':'PER_PAPER','review_spec':{},'extraction':ext,'paper_text':source,'gate1_results':[]}
    return r,payload


def response(payload):
    return {'agent_id':'A6-SV','prompt_version':'0.3','status':'COMPLETE','warnings':[],'limitations':[],
            'mode':'PER_PAPER','record_id':'R0001','validations':[{'finding_id':f['finding_id'],'disposition':'SUPPORTED_WITH_CONSTRAINTS',
            'gate1':'PASSED','constraints':['Synthetic limit'],'plain_language_limit':'Synthetic bound'} for f in payload['extraction']['findings']],
            'defect_reports':[],'source_inconsistencies':[],'normalization_conflicts':[]}


def fake_agent(r,monkeypatch,fail=None):
    calls=[];cache={}
    def agent(agent,payload,step,**kwargs):
        if step in cache:return copy.deepcopy(cache[step])
        calls.append((step,[f['finding_id'] for f in payload['extraction']['findings']]))
        assert kwargs['repair_limit']==0 and kwargs['exclude_providers']==frozenset({'anthropic'})
        if fail and fail(step,len(calls)):raise AgentError('Output was truncated at max_tokens')
        out=response(payload);cache[step]=copy.deepcopy(out);return out
    monkeypatch.setattr(r,'agent',agent);monkeypatch.setattr(r,'_agent_human_review',lambda *a:None)
    return calls,cache


def test_partitions_15_findings_and_retains_full_source(ready):
    r,p=ready;parts=b.batches(p);assert [len(x['extraction']['findings']) for x in parts]==[15,15,7]
    assert [f['finding_id'] for x in parts for f in x['extraction']['findings']]==[f['finding_id'] for f in p['extraction']['findings']]
    assert all(x['paper_text'] is p['paper_text'] for x in parts)
    assert all(len(x['paper_finding_index'])==37 for x in parts)
    assert all(x['extraction']['entities']==p['extraction']['entities'] for x in parts)


def test_only_truncated_batch_retried_and_accepted_batches_reused(ready,monkeypatch):
    r,p=ready;calls,cache=fake_agent(r,monkeypatch,lambda step,n:'_B002_' in step and '_try1' in step)
    merged=b.audit(r,p,'A06-SV_R0001_recovery',exclude=frozenset({'anthropic'}))
    assert len(calls)==4 and [len(ids) for _,ids in calls]==[15,15,15,7]
    assert len(merged['validations'])==37 and all(v['constraints']==['Synthetic limit'] for v in merged['validations'])
    assert b.audit(r,p,'A06-SV_R0001_recovery',exclude=frozenset({'anthropic'}))==merged
    assert len(calls)==4


def test_two_truncations_preserve_prior_batches_and_stop(ready,monkeypatch):
    r,p=ready;calls,_=fake_agent(r,monkeypatch,lambda step,n:'_B002_' in step)
    with pytest.raises(AgentError):b.audit(r,p,'root',exclude=frozenset({'anthropic'}))
    assert len(calls)==3 and not r.load('a06_batch_receipts/root.json')
    assert len(list(r.data('a06_batches').rglob('1.json')))==1
    with pytest.raises(ValueError,match='exhausted'):b.audit(r,p,'root',exclude=frozenset({'anthropic'}))
    assert len(calls)==3


@pytest.mark.parametrize('change',['missing','duplicate','unknown','wrong_record','failed','unknown_cross_ref'])
def test_invalid_batch_never_accepted(ready,change):
    _,p=ready;part=b.batches(p)[0];out=response(part)
    if change=='missing':out['validations'].pop()
    elif change=='duplicate':out['validations'][1]=copy.deepcopy(out['validations'][0])
    elif change=='unknown':out['validations'][0]['finding_id']='F999'
    elif change=='wrong_record':out['record_id']='R0002'
    elif change=='failed':out['status']='FAILED'
    else:out['source_inconsistencies']=[{'finding_ids':['F999']}]
    with pytest.raises(ValueError):b.validate_batch(out,part,p)


def test_cross_batch_annotations_and_constraints_survive_merge(ready):
    _,p=ready;parts=b.batches(p);outs=[response(x) for x in parts]
    issue={'finding_ids':['F1','F37'],'description':'Synthetic shared-study cross-batch inconsistency','locations':['Results','Table 1']}
    outs[0]['source_inconsistencies']=[issue];outs[-1]['source_inconsistencies']=[issue]
    merged=b.merge(p,parts,outs)
    assert merged['source_inconsistencies']==[issue] and len(merged['validations'])==37
    assert merged['validations'][-1]['finding_id']=='F37'


def test_changed_source_stops_before_model_call(ready,monkeypatch):
    r,p=ready;calls,_=fake_agent(r,monkeypatch);p['paper_text']={'Results':'Changed'}
    with pytest.raises(ValueError,match='source'):b.audit(r,p,'root',exclude=frozenset({'anthropic'}))
    assert not calls


def test_paper_batch_api_cannot_bypass_partitioning(ready,monkeypatch):
    r,p=ready;r.cfg['batch']['enabled']=True;seen=[]
    monkeypatch.setattr(r,'agent',lambda a,p,s,**kw:seen.append((s,p)) or response(p))
    monkeypatch.setattr(orch,'BatchStage',lambda *a:pytest.fail('Oversized paper must not be sent as a vendor batch item'))
    accepted=[];r.run_many('A06-SV',[('root',p)],lambda s,o:accepted.append(o))
    assert len(seen)==len(accepted)==1  # normal agent is the bounded dispatch entry point


def test_completed_validations_remain_skipped(ready,monkeypatch):
    r,p=ready;r.save('selected_corpus.json',[{'record_id':'R0002'}]);r.save('validations/R0002.json',{'synthetic':'already accepted'})
    monkeypatch.setattr(r,'_instability_test',lambda *a:None);monkeypatch.setattr(r,'_require_complete_validation',lambda *a:None)
    monkeypatch.setattr(r,'_validated_findings',lambda *a:[]);monkeypatch.setattr(r,'_theme_pass',lambda *a:[]);monkeypatch.setattr(r,'_save_held',lambda *a:None)
    monkeypatch.setattr(r,'run_many',lambda a,items,*args,**kw:None if items==[] else pytest.fail('Already validated paper was resubmitted'))
    assert r.stage_validate(r.state())=='synthesize'


@pytest.mark.projection_guard
def test_real_agent_batches_64k_and_records_only_failed_batch_retry(ready,monkeypatch):
    from litreview import pilot_authorization as pa
    from litreview.agents import base
    from litreview.llm.base import LLMResponse
    from test_pilot_authorization import authorize
    r,p=ready;r.cfg['agents']['A06-SV']['max_tokens']=64000
    r.save('selected_corpus.json',[{'record_id':'R0001','pmid':'34638842','pmcid':'PMC8508702','abstract':'Synthetic study'},
                                 {'record_id':'R0002','pmid':'27006494','abstract':'Synthetic'},
                                 {'record_id':'R0003','pmid':'30771200','abstract':'Synthetic'}])
    authorize(r)
    monkeypatch.setattr(r,'_require_projection',lambda:None);monkeypatch.setattr(r,'_check_worst_case_line',lambda *a:None)
    monkeypatch.setattr(r,'_context_check',lambda *a:{'input_counted':100,'input_byte_bound':100,'output_reserve':64000})
    monkeypatch.setattr(r,'_context_actual',lambda *a:None);monkeypatch.setattr(orch.model_record,'add',lambda *a,**k:None)
    calls=[]
    def complete(*args,**kwargs):
        data=json.loads(kwargs['user'][0]['text']);calls.append(data['a06_validation_batch']['finding_ids'])
        assert kwargs['max_tokens']==64000
        if len(calls)==2:return LLMResponse('', 'openai',r.route('A06-SV').model,10,64000,'length')
        return LLMResponse(json.dumps(response(data)),'openai',r.route('A06-SV').model,10,100,'stop')
    monkeypatch.setattr(base,'complete',complete)
    merged=r.agent('A06-SV',p,'A06-SV_R0001_recovery',exclude_providers=frozenset({'anthropic'}))
    assert len(calls)==4 and calls[1]==calls[2] and len(merged['validations'])==37
    assert len(r.budget.entries())==4 and not r.budget.reservations()
    assert not (r.dir/'outputs/A06-SV_R0001_recovery.json').exists()
    assert r.agent('A06-SV',p,'A06-SV_R0001_recovery',exclude_providers=frozenset({'anthropic'}))==merged
    assert len(calls)==4 and len(r.budget.entries())==4
    r.save('extractions/R0001.json',p['extraction'])
    r.save('a06_inputs/R0001.json',{'payload':p})
    r._save_validation('R0001',merged)
    accepted=r.load('validations/R0001.json')
    assert len(accepted['validations'])==37 and accepted['_source_fingerprint']
    assert all(v['constraints']==['Synthetic limit'] for v in accepted['validations'])


def test_openai_builder_sends_64k_completion_cap():
    from litreview.llm.openai_compatible import chat_params
    result=chat_params('Synthetic system','Synthetic user','gpt-6.1-sol',64000,0.0)
    assert result['max_completion_tokens']==64000


def test_forecast_uses_observed_cache_write_class_not_1h_fallback(ready,monkeypatch):
    import math
    from litreview import pilot_authorization as pa
    from litreview.agents.base import build_system_prompt,user_parts
    from litreview.synthesis_registry import offline_tokens
    from litreview.tools import cost_projection as cp
    r,p=ready;r.cfg['validation']['instability_test']=False
    r.save('a06_inputs/R0001.json',{'payload':p})
    monkeypatch.setattr(r,'_extraction_vendor',lambda rid:'anthropic')
    pa.atomic(r.dir/'input/a06_batch_recovery.json',{'record_id':'R0001','root_step':'root','observed_input_tokens':100,'observed_input_byte_bound':500})
    extra,count=b.forecast_increment(r);assert count==3
    model=r.route('A06-SV',frozenset({'anthropic'}));expected=0.
    for part in b.batches(p):
        bound=offline_tokens(build_system_prompt('A06-SV'))+offline_tokens(user_parts(part,model.cache_payload))
        expected+=r.budget.cost(model.model,0,0,cache_write_tokens=math.ceil(bound*.2))+cp.load_rates()['per_paper']['ABSTRACT']['a06_p90_usd']
    replaced=cp.load_rates()['per_paper']['FULL_TEXT']['a06_p90_usd']
    assert extra==pytest.approx(max(0.,expected-replaced))
