"""Actual A05 acceptance path, wire parity and independent A06 handoff; model replies are scripted offline."""
import copy,dataclasses,json
from pathlib import Path
import pytest,jsonschema
from litreview import extraction_mode as mode,structured,a05_functional,config,orchestrator as orch,model_record
from litreview.agents import base
from litreview.budget import BudgetTracker
from litreview.provenance import ProvenanceLog
from litreview.llm.base import LLMResponse
from litreview.llm import anthropic_client,batch
from contract_fixtures import a06_paper


def canonical(span,readout='concentration_classification',comparator='NONE_REPORTED'):
    return {'agent_id':'A05-KE','prompt_version':'0.9','status':'COMPLETE','warnings':[],'limitations':[],
      'sections_inspected':['Abstract'],'study_profile':{'study_type':'PRIMARY_RESEARCH','evidence_systems':['IN_VITRO_CELL_FREE']},
      'entities':[{'entity_id':'E1','mention':'glucose','type':'MOLECULE'},{'entity_id':'E2','mention':'spiked serum','type':'MATERIAL'}],
      'contexts':[{'context_id':'C1','fields':{'evidence_system':'IN_VITRO_CELL_FREE','comparator':comparator,'matrix':'spiked serum','readout':readout}}],
      'findings':[{'finding_id':'F1','subject_entity_id':'E1','predicate':'OTHER_SPECIFIED','predicate_detail':readout,
          'object_entity_id':'E2','polarity':'POSITIVE','modality':'ASSERTED','direction':'NOT_APPLICABLE','assertion_type':'REPORTED_RESULT',
          'origin':'EXPLICIT','context_id':'C1','span':span,'span_location':{'section':'Abstract'},'warrant_note':readout,
          'quantities':[{'measured_property':'concentration_class_range','raw_value':'5-10','raw_unit':'mM','value_type':'RANGE',
                         'variance_or_ci':None,'p_value':None,'n':None,'converted':None}]}],
      'author_stated_limitations':[]}

SPAN='The classifier assigned glucose in spiked serum to the 5-10 mM concentration range; it did not estimate a numerical concentration.'

def payload(span=SPAN):
    return {'record':{'record_id':'R1','content':{'Abstract':span}},'content_level':'ABSTRACT',
            'source_access':{'level':'ABSTRACT','figure_images_inspected':False,'figure_legends_read':False,'supplements_inspected':False}}


def test_plain_json_keeps_canonical_null_and_trusted_metadata():
    output=mode.accept(json.dumps(canonical(SPAN)),payload())
    assert output['record_id']=='R1' and output['content_level']=='ABSTRACT'
    assert output['findings'][0]['quantities'][0]['variance_or_ci'] is None
    assert output['contexts'][0]['fields']['comparator']=='NONE_REPORTED'
    assert not output['source_access']['figure_images_inspected']

@pytest.mark.parametrize('text',['{}','[]','```json\n{}\n```','{"a":1,"a":2}','{"a":NaN}','prose {}'])
def test_strict_parser_never_forwards_malformed_incomplete_or_duplicate_json(text):
    with pytest.raises(jsonschema.ValidationError):mode.accept(text,payload())

@pytest.mark.parametrize('change',[lambda d:d.update(record_id='OTHER'),lambda d:d.update(content_level='FULL_TEXT'),
 lambda d:d.update(source_access={'figure_images_inspected':True}),lambda d:d['findings'][0].update(subject_entity_id='missing'),
 lambda d:d['findings'][0].update(span='Invented quote'),lambda d:d['findings'][0]['quantities'][0].update(raw_value='20'),
 lambda d:d.update(sections_inspected=['Results'])])
def test_invalid_metadata_source_ids_and_quantities_are_rejected(change):
    doc=canonical(SPAN);change(doc)
    with pytest.raises(jsonschema.ValidationError):mode.accept(json.dumps(doc),payload())


def test_interactive_batch_and_functional_use_same_ordinary_generation_mode(tmp_path,monkeypatch):
    assert mode.active()
    assert structured.response_schema('A05-KE',None,'anthropic','claude-sonnet-5-5') is None
    calls=[]
    def complete(provider,**kw):
        calls.append(kw)
        body=anthropic_client.message_params(kw['system'],kw['user'],kw['model'],kw['max_tokens'],kw['temperature'],
            kw.get('effort'),trace=kw['trace'],response_schema=kw.get('response_schema'))
        assert 'format' not in body.get('output_config',{})
        return LLMResponse(json.dumps(canonical(SPAN)),provider,kw['model'],100,200,'end_turn')
    monkeypatch.setattr(base,'complete',complete)
    out=base.run_agent('A05-KE',payload(),tmp_path,'A05-KE_R1',BudgetTracker(tmp_path),ProvenanceLog(tmp_path),repair_limit=0)
    assert out['record_id']=='R1' and (tmp_path/'outputs/A05-KE_R1.raw0.txt').exists()
    trace=calls[0]['trace'];assert trace['generation_mode']==mode.MODE
    m=config.agent_model('A05-KE')
    req=batch.request('anthropic','r1',calls[0]['system'],calls[0]['user'],m.model,m.max_tokens,m.temperature,m.effort,trace=trace)
    assert 'format' not in req['params'].get('output_config',{})
    with pytest.raises(ValueError):anthropic_client.message_params('s','u',m.model,4000,0,trace=trace,response_schema={'schema':{}})
    assert (tmp_path/'input/extraction_generation.json').exists()


def test_invalid_and_truncated_interactive_reply_never_becomes_accepted(tmp_path,monkeypatch):
    for name,text,stop in [('bad','{}','end_turn'),('truncated',json.dumps(canonical(SPAN)),'max_tokens')]:
        path=tmp_path/name
        monkeypatch.setattr(base,'complete',lambda provider,**kw:LLMResponse(text,provider,kw['model'],100,200,stop))
        with pytest.raises(base.AgentError):base.run_agent('A05-KE',payload(),path,'step',BudgetTracker(path),ProvenanceLog(path),repair_limit=0,truncation_retries=0)
        assert (path/'outputs/step.raw0.txt').read_text()==text
        assert not (path/'outputs/step.json').exists()


def test_invalid_json_is_repaired_from_raw_once_using_same_mode(tmp_path,monkeypatch):
    calls=[]
    def complete(provider,**kw):
        calls.append(kw)
        bad=canonical(SPAN);bad.pop('warnings')
        return LLMResponse(json.dumps(bad) if len(calls)==1 else json.dumps(canonical(SPAN)),provider,kw['model'],100,200,'end_turn')
    monkeypatch.setattr(base,'complete',complete)
    out=base.run_agent('A05-KE',payload(),tmp_path,'step',BudgetTracker(tmp_path),ProvenanceLog(tmp_path),repair_limit=1,truncation_retries=0)
    assert len(calls)==2 and all(c['trace']['generation_mode']==mode.MODE and not c.get('response_schema') for c in calls)
    assert 'failed' in calls[1]['system'].lower() and out['record_id']=='R1'
    assert 'warnings' not in json.loads((tmp_path/'outputs/step.raw0.txt').read_text())

@pytest.mark.parametrize('interpretation',['concentration_classification','numerical_concentration_estimation'])
def test_real_a06_handoff_separates_classification_from_numerical_estimation(tmp_path,monkeypatch,interpretation):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path);monkeypatch.setattr(model_record,'RECORD',tmp_path/'models.jsonl')
    run=orch.Run('engineering');run.save_state({'profile':'pilot7','stage':'validate','counters':{}})
    ext=mode.accept(json.dumps(canonical(SPAN,interpretation)),payload())
    # Quote/quantity validation alone cannot establish interpretation: both readings quote identical text.
    run.budget.record('A05-KE','anthropic','claude-sonnet-5-5',100,100,step='A05-KE_R1')
    seen=[]
    def independent(agent,p,step,**kw):
        seen.append(p);assert agent=='A06-SV' and kw['exclude_providers']==frozenset({'anthropic'})
        assert p['gate1_results'][0]['span_found'] and p['gate1_results'][0]['numbers_match']
        assert p['extraction']['contexts'][0]['fields']['comparator']=='NONE_REPORTED'
        supported=p['extraction']['contexts'][0]['fields']['readout']=='concentration_classification'
        return a06_paper(record_id='R1',validations=[{'finding_id':'F1','gate1':'PASSED',
            'disposition':'SUPPORTED_WITH_CONSTRAINTS' if supported else 'DOES_NOT_ESTABLISH',
            'plain_language_limit':'Classification into a concentration range; no numerical estimate.'}])
    monkeypatch.setattr(run,'agent',independent)
    source={'payload':{**payload(),'review_spec':{'central_question':'Classification or estimation?'}}}
    if interpretation=='concentration_classification':
        val=a05_functional.handoff(run,ext,source);assert val['validations'][0]['disposition']=='SUPPORTED_WITH_CONSTRAINTS'
    else:
        with pytest.raises(ValueError,match='scientific validation'):a05_functional.handoff(run,ext,source)
    assert seen and run.data('a06_inputs/R1.json').exists()


def test_empty_records_cannot_pass_functional_science():
    source=a05_functional.fixture()
    with pytest.raises(jsonschema.ValidationError,match='omission'):a05_functional.require_expected({'entities':[],'contexts':[],'findings':[]},source['expected'])


def test_mode_and_canonical_contract_are_fingerprinted(tmp_path):
    from litreview.run_spec import configuration_snapshot
    assert configuration_snapshot()['extraction_generation']==mode.identity()
    first=mode.record_identity(tmp_path)
    assert first['generation_mode']==mode.MODE and first['contract_version']==mode.CONTRACT_VERSION
    p=tmp_path/'input/extraction_generation.json';v=json.loads(p.read_text());v['generation_mode']='other';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='continuation'):mode.record_identity(tmp_path)


@pytest.mark.parametrize('bad',[False,True])
def test_batch_ingestion_uses_identical_local_checks_and_never_forwards_invalid(tmp_path,monkeypatch,bad):
    from litreview.batch_stage import BatchStage
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path);monkeypatch.setattr(model_record,'RECORD',tmp_path/'models.jsonl')
    run=orch.Run('batch');run.save_state({'profile':'pilot7','stage':'extract','counters':{}})
    (run.dir/'outputs').mkdir()
    seen=[];stage=BatchStage(run,'A05-KE',[('step',payload())],lambda step,out:seen.append(out))
    m=config.agent_model('A05-KE');reqs,_=stage._requests(m,{'cid':'step'})
    assert 'format' not in reqs[0]['params'].get('output_config',{})
    text='{}' if bad else json.dumps(canonical(SPAN));resp=LLMResponse(text,'anthropic',m.model,100,200,'end_turn')
    counts={'refused':0,'repair':0,'succeeded':0};repairs=[]
    stage._ingest_one({'batch_id':'b','cache_requested':False,'prompt_chars':{}},'step',resp,repairs,counts)
    assert (run.dir/'outputs/step.raw0.txt').read_text()==text
    if bad:assert not seen and repairs==['step'] and not (run.dir/'outputs/step.json').exists()
    else:assert seen[0]['record_id']=='R1' and seen[0]['contexts'][0]['fields']['comparator']=='NONE_REPORTED'


def test_functional_guard_enforces_each_reviewed_bound_and_retains_uncertain_send(tmp_path):
    b=BudgetTracker(tmp_path);m=dataclasses.replace(config.agent_model('A05-KE'),max_tokens=4000,cache_system=False,cache_payload=())
    g=a05_functional.dispatch_guard(b,'A05-KE','A05-KE_FUNCTIONAL_SOURCE_1')
    for text in ['x'*(a05_functional.A05_INPUT_BYTES+1)]:
        with pytest.raises(ValueError,match='bounds'):g(0,text,[],m)
    with pytest.raises(ValueError):g(2,'s',[],m)
    with pytest.raises(ValueError):g(0,'s',[],dataclasses.replace(m,max_tokens=4001))
    key=g(0,'s',[{'text':'u','cache':False}],m);assert key in b.reservations()
    with pytest.raises(ValueError,match='Unsettled'):g(0,'s',[{'text':'u'}],m)
    assert key in b.reservations()
    b.record('A05-KE','anthropic',m.model,1,1,step='A05-KE_FUNCTIONAL_SOURCE_1',reservation_key=key)
    b.release(key)
    with pytest.raises(ValueError,match='already paid'):g(0,'s',[{'text':'u'}],m)


def test_all_nine_prior_successes_stay_strictly_reusable_but_a05_is_a_new_check():
    assert len(structured.schema_inventory())==14
    assert all(t['agent']!='A05-KE' for t in structured.targets())
    assert not a05_functional.verified(Path('does-not-exist'))


def test_ordinary_a05_http_error_keeps_request_evidence_and_billing_hold(tmp_path,monkeypatch):
    class Rejected(Exception):status_code=400;request_id='req_offline'
    def fail(*args,**kw):raise Rejected('invalid request')
    monkeypatch.setattr(base,'complete',fail)
    b=BudgetTracker(tmp_path);m=dataclasses.replace(config.agent_model('A05-KE'),max_tokens=4000,cache_system=False,cache_payload=())
    guard=a05_functional.dispatch_guard(b,'A05-KE','A05-KE_FUNCTIONAL_SOURCE_1')
    with pytest.raises(base.AgentError):base.run_agent('A05-KE',payload(),tmp_path,'A05-KE_FUNCTIONAL_SOURCE_1',b,ProvenanceLog(tmp_path),model=m,
         dispatch_guard=guard,repair_limit=0,truncation_retries=0)
    assert b.reserved()>0 and not b.entries()
    receipt=json.loads((tmp_path/'outputs/A05-KE_FUNCTIONAL_SOURCE_1.error0.json').read_text())
    assert receipt['provider_request_id']=='req_offline' and receipt['billing_status'].startswith('UNRESOLVED')


def test_ordinary_mode_accepted_record_resumes_without_repaying(tmp_path,monkeypatch):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path);monkeypatch.setattr(model_record,'RECORD',tmp_path/'models.jsonl')
    run=orch.Run('resume');run.save_state({'profile':'pilot7','stage':'extract','counters':{}})
    calls=[]
    def complete(provider,**kw):
        calls.append(kw);return LLMResponse(json.dumps(canonical(SPAN)),provider,kw['model'],100,200,'end_turn')
    monkeypatch.setattr(base,'complete',complete)
    first=run.agent('A05-KE',payload(),'A05-KE_R1');spent=run.budget.spent()
    assert run.agent('A05-KE',payload(),'A05-KE_R1')==first
    assert len(calls)==1 and run.budget.spent()==spent
    assert mode.identity()['generation_mode']==mode.MODE


def functional_record():
    source=a05_functional.fixture();requirements=source['expected']['requirements']
    ext={'agent_id':'A05-KE','prompt_version':'0.9','status':'COMPLETE','warnings':[],'limitations':['Abstract excerpt only.'],
         'sections_inspected':['Abstract'],'study_profile':{'study_type':'PRIMARY_RESEARCH','evidence_systems':['HUMAN_INTERVENTIONAL']},
         'entities':[{'entity_id':'E1','mention':'Diethyl-dithiocarbamate-copper','type':'MOLECULE'},
                     {'entity_id':'E2','mention':'plasma','type':'MATERIAL'}, {'entity_id':'E3','mention':'tumors','type':'MATERIAL'},
                     {'entity_id':'E4','mention':'DSF','type':'DRUG_STATUS_UNVERIFIED'}],
         'contexts':[],'findings':[],'author_stated_limitations':[]}
    for i,r in enumerate(requirements,1):
        ext['contexts'].append({'context_id':f'C{i}','fields':{'evidence_system':'HUMAN_INTERVENTIONAL','comparator':'NONE_REPORTED',
                                 'matrix':r.get('matrix','NOT_APPLICABLE'),'readout':r['task']}})
        f={'finding_id':f'F{i}','subject_entity_id':'E1' if i<3 else 'E4','predicate':r['predicate'],
           'object_entity_id':f'E{i+1}' if i<3 else None,'polarity':r['polarity'],'modality':'ASSERTED',
           'direction':'NOT_APPLICABLE','assertion_type':'REPORTED_RESULT','origin':'EXPLICIT','context_id':f'C{i}',
           'span':r['quote'],'span_location':{'section':'Abstract'},'warrant_note':r['task'],'primary_theme_id':'T1','quantities':[]}
        if i==3:f['quantities']=[{'measured_property':'maximum tolerated dose','raw_value':'375','raw_unit':'mg/d','value_type':'DOSE'}]
        ext['findings'].append(f)
    return mode.accept(json.dumps(ext),source['payload'])


def test_prepared_real_passage_requires_positive_negative_and_reported_dose():
    ext=functional_record();expected=a05_functional.fixture()['expected']
    assert a05_functional.require_expected(ext,expected)
    assert ext['findings'][1]['polarity']=='NEGATIVE'
    for change in [lambda d:d['findings'].pop(),lambda d:d['findings'][2]['quantities'][0].update(raw_unit='nM'),
                   lambda d:d['contexts'][0]['fields'].update(comparator='VEHICLE')]:
        bad=copy.deepcopy(ext);change(bad)
        with pytest.raises(jsonschema.ValidationError):a05_functional.require_expected(bad,expected)


def test_prepared_clinical_passage_uses_the_actual_independent_a06_handoff(tmp_path,monkeypatch):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path);monkeypatch.setattr(model_record,'RECORD',tmp_path/'models.jsonl')
    run=orch.Run('clinical-functional');run.save_state({'profile':'pilot7','stage':'validate','counters':{}})
    ext=functional_record();run.budget.record('A05-KE','anthropic','claude-sonnet-5-5',100,100,step='A05-KE_FUNCTIONAL_SOURCE_1')
    def independent(agent,p,step,**kw):
        assert kw['exclude_providers']==frozenset({'anthropic'}) and len(p['extraction']['findings'])==3
        assert all(g['span_found'] and g['numbers_match'] for g in p['gate1_results'])
        return a06_paper(record_id='FUNCTIONAL_SOURCE_1',validations=[{'finding_id':f['finding_id'],'disposition':'SUPPORTED_WITH_CONSTRAINTS',
             'gate1':'PASSED','plain_language_limit':'Abstract passage only; detection is not a numerical concentration estimate.'} for f in p['extraction']['findings']])
    monkeypatch.setattr(run,'agent',independent)
    assert len(a05_functional.handoff(run,ext,a05_functional.fixture())['validations'])==3


def test_functional_planner_is_read_only_and_reports_new_mode_separately(tmp_path,monkeypatch):
    b=BudgetTracker(tmp_path);b.reserve('smoke-unknown',0.099409,'smoke-test','Unresolved historical holds')
    before=b.reservations_path.read_bytes()
    monkeypatch.setattr(structured,'RECORD',tmp_path/'structured_output.json')
    proposal=a05_functional.plan(b)
    assert proposal['functional_worst_case_usd']==pytest.approx(0.658)  # Conservative implicit OpenAI cache-write pricing.
    assert proposal['provider_strict_schema_submitted'] is False and proposal['paid_dispatch_authorized'] is False
    assert b.reservations_path.read_bytes()==before and not b.entries()


def test_expectation_failure_is_not_accepted_and_does_not_erase_saved_science():
    ext=functional_record();ext['contexts'][0]['fields']['comparator']='NOT_APPLICABLE'
    before=copy.deepcopy(ext)
    with pytest.raises(jsonschema.ValidationError):a05_functional.require_expected(ext,a05_functional.fixture()['expected'])
    assert ext==before and len(ext['findings'])==3
    # Independent handoff itself requires a valid canonical extraction; expectation mismatch does not mutate it.
    base.validate('A05-KE',ext)
