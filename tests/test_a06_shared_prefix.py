import copy
import json
import pytest
from litreview import a06_batches as b,config
from litreview.a06_request import canonical,parts as split
from litreview.agents.base import user_parts
from litreview.llm.openai_compatible import chat_params,parse_completion
from test_a06_batches import ready,response
from test_pilot_authorization import run


def configured(monkeypatch,mode='explicit',ttl='30m'):
    original=config.load
    cfg=copy.deepcopy(original('pipeline'));cfg['providers']['openai']['a06_cache']={'mode':mode,'ttl':ttl}
    monkeypatch.setattr(config,'load',lambda name:cfg if name=='pipeline' else original(name))


def test_shared_prefix_constructed_once_source_schema_and_scope_retained(ready,monkeypatch):
    import litreview.a06_request as request
    r,p=ready;seen=[];original=request.shared_prefix
    monkeypatch.setattr(request,'shared_prefix',lambda value:seen.append(value) or original(value))
    values=b.batches(p,shared_prefix=True)
    assert len(seen)==1 and len(values)==3
    assert values[0]['_a06_shared_prefix'] is values[1]['_a06_shared_prefix']
    shared=json.loads(user_parts(values[0])[0]['text'].split('\n',1)[1])
    assert shared['paper_text']==p['paper_text'] and shared['review_spec']==p['review_spec']
    assert shared['validation_output_schema'] and len(shared['paper_finding_index'])==37
    assert 'a06_validation_batch' not in shared and 'extraction' not in shared
    for value in values:
        variable=json.loads(user_parts(value)[1]['text'].split('\n',1)[1])
        assert variable['extraction']==value['extraction']
        assert variable['gate1_results']==value['gate1_results']
        assert variable['a06_validation_batch']==value['a06_validation_batch']


def test_deterministic_shared_prefix_and_source_mutation_identity(ready):
    _,p=ready;first=b.batches(p,shared_prefix=True)
    reordered=copy.deepcopy(p);reordered['paper_text']=dict(reversed(list(p['paper_text'].items())))
    assert b.batches(reordered,shared_prefix=True)[0]['_a06_shared_prefix']==first[0]['_a06_shared_prefix']
    changed=copy.deepcopy(p);changed['paper_text']['Results']+=' Changed source.'
    assert b.batches(changed,shared_prefix=True)[0]['_a06_shared_prefix']!=first[0]['_a06_shared_prefix']
    changed=copy.deepcopy(p);changed['review_spec']['purpose']='Different scope'
    assert b.batches(changed,shared_prefix=True)[0]['_a06_shared_prefix']!=first[0]['_a06_shared_prefix']


@pytest.mark.parametrize('level',['FULL_TEXT','ABSTRACT'])
def test_real_chat_builder_identical_prefix_variable_after_boundary(ready,level):
    _,p=ready;p['extraction']['content_level']=level
    if level=='ABSTRACT':p['paper_text']={'Abstract':'Authorized synthetic abstract only.'}
    values=b.batches(p,shared_prefix=True)
    requests=[chat_params('Shared scientific instructions',user_parts(v),'gpt-6.1-sol',64000,0) for v in values]
    a,c=requests[:2]
    assert a['messages'][0]==c['messages'][0]
    assert a['messages'][1]['content'][0]==c['messages'][1]['content'][0]
    assert a['messages'][1]['content'][1]!=c['messages'][1]['content'][1]
    assert a['messages'][1]['content'][0]['prompt_cache_breakpoint']=={'mode':'explicit'}
    assert 'prompt_cache_breakpoint' not in a['messages'][1]['content'][1]
    assert a['prompt_cache_options']=={'mode':'explicit','ttl':'30m'}
    assert a['max_completion_tokens']==64000 and a['response_format']=={'type':'json_object'}
    assert not any(k in a for k in ('diagnostics','prompt_cache_retention','user'))
    if level=='ABSTRACT':assert json.loads(values[0]['_a06_shared_prefix'].split('\n',1)[1])['paper_text']==p['paper_text']


def test_no_cache_control_has_no_breakpoint(ready,monkeypatch):
    configured(monkeypatch,'off');_,p=ready
    req=chat_params('System',user_parts(b.batches(p,shared_prefix=True)[0]),'gpt-6.1-sol',64000,0)
    assert req['prompt_cache_options']['mode']=='explicit'
    assert all('prompt_cache_breakpoint' not in v for v in req['messages'][1]['content'])


def test_unsupported_retention_fails_before_provider(ready,monkeypatch):
    configured(monkeypatch,ttl='12h');_,p=ready
    with pytest.raises(ValueError,match='30m'):
        chat_params('System',user_parts(b.batches(p,shared_prefix=True)[0]),'gpt-6.1-sol',64000,0)


def test_kimi_and_non_a06_requests_remain_unchanged(ready):
    _,p=ready;req=chat_params('System',user_parts(b.batches(p,shared_prefix=True)[0]),'kimi-k2.5',64000,0,'kimi')
    assert 'prompt_cache_options' not in req and isinstance(req['messages'][1]['content'],str)
    plain=chat_params('System','Task','gpt-6.1-sol',64000,0)
    assert plain['messages'][1]['content']=='Task' and 'prompt_cache_options' not in plain


def test_cache_miss_or_expiry_usage_is_not_fabricated_or_retried():
    raw={'id':'synthetic','object':'chat.completion','created':0,'model':'gpt-6.1-sol','choices':[{'index':0,'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}],
         'usage':{'prompt_tokens':10000,'completion_tokens':100,'total_tokens':10100,'prompt_tokens_details':{'cached_tokens':0,'cache_write_tokens':9000}}}
    out=parse_completion(raw,'openai','gpt-6.1-sol')
    assert out.input_tokens==1000 and out.cache_write_tokens==9000 and out.cached_input_tokens==0
    raw['usage']['prompt_tokens_details']={'cached_tokens':8000,'cache_write_tokens':1000}
    out=parse_completion(raw,'openai','gpt-6.1-sol')
    assert out.input_tokens==1000 and out.cache_write_tokens==1000 and out.cached_input_tokens==8000


def test_optimized_partial_failure_and_merge_preserve_scientific_constraints(ready,monkeypatch):
    from test_a06_batches import fake_agent
    r,p=ready;r.cfg['validation']['shared_prefix']=True
    calls,_=fake_agent(r,monkeypatch,lambda step,n:'_B002_' in step and '_try1' in step)
    merged=b.audit(r,p,'optimized',exclude=frozenset({'anthropic'}))
    assert len(calls)==4 and len(merged['validations'])==37
    assert merged==b.audit(r,p,'optimized',exclude=frozenset({'anthropic'})) and len(calls)==4
    assert all(v['constraints']==['Synthetic limit'] for v in merged['validations'])


def test_optimized_real_dispatch_financial_vendor_and_cached_resume(ready,monkeypatch):
    from litreview import orchestrator as orch
    from litreview.agents import base
    from litreview.llm.base import LLMResponse
    from test_pilot_authorization import authorize
    r,p=ready;r.cfg['validation']['shared_prefix']=True
    r.save('selected_corpus.json',[{'record_id':'R0001','pmid':'34638842','pmcid':'PMC8508702','abstract':'Synthetic study'},
      {'record_id':'R0002','pmid':'27006494','abstract':'Synthetic'},{'record_id':'R0003','pmid':'30771200','abstract':'Synthetic'}])
    authorize(r);calls=[]
    monkeypatch.setattr(r,'_context_check',lambda *a:{'input_counted':100,'input_byte_bound':100,'output_reserve':64000})
    monkeypatch.setattr(r,'_context_actual',lambda *a:None);monkeypatch.setattr(orch.model_record,'add',lambda *a,**k:None)
    def complete(provider,**kw):
        assert provider=='openai';req=chat_params(kw['system'],kw['user'],kw['model'],kw['max_tokens'],kw['temperature'])
        calls.append(req)
        variable=json.loads(kw['user'][1]['text'].split('\n',1)[1])
        return LLMResponse(json.dumps(response(variable)),'openai',kw['model'],100,100,'stop',cached_input_tokens=8000 if len(calls)>1 else 0,cache_write_tokens=8000 if len(calls)==1 else 0)
    monkeypatch.setattr(base,'complete',complete)
    result=r.agent('A06-SV',p,'optimized-real',exclude_providers=frozenset({'anthropic'}))
    assert len(calls)==3 and len(result['validations'])==37 and not r.budget.reservations()
    assert r.agent('A06-SV',p,'optimized-real',exclude_providers=frozenset({'anthropic'}))==result and len(calls)==3
    assert len(r.budget.entries())==3 and r.budget.entries()[1]['cached_input_tokens']==8000
    assert all(x['messages'][1]['content'][0]==calls[0]['messages'][1]['content'][0] for x in calls)


def test_different_papers_even_with_identical_text_have_distinct_prefixes(ready):
    _,p=ready;other=copy.deepcopy(p);other['extraction']['record_id']='R0002'
    assert b.batches(p,shared_prefix=True)[0]['_a06_shared_prefix']!=b.batches(other,shared_prefix=True)[0]['_a06_shared_prefix']


def test_original_and_optimized_scripted_merge_preserves_numerical_and_contrary_constraints(ready):
    _,p=ready
    notes=['Positive observation at 2 micromolar, not 2 millimolar; model A only.',
           'Negative comparator observation; distinct arm and assay.',
           'Null result with uncertainty; absence of abstract detail is not experimental absence.',
           'Contrary pathway interpretation; does not establish clinical efficacy.']
    original=b.batches(p);optimized=b.batches(p,shared_prefix=True)
    outputs=[]
    for part in original:
        value=response(part)
        for n,row in enumerate(value['validations']):
            row['constraints']=[notes[n%4]];row['plain_language_limit']=notes[n%4]
        outputs.append(value)
    before=b.merge(p,original,outputs);after=b.merge(p,optimized,outputs)
    assert before==after
    assert [v['finding_id'] for v in after['validations']]==[v['finding_id'] for v in p['extraction']['findings']]


def test_cache_economics_writes_reads_expiry_and_output_do_not_overlap():
    from litreview.tools.cache_cost import estimate
    a=estimate(10000,[100,200],[50,60],caching=False)
    b=estimate(10000,[100,200],[50,60],gaps=[0,120])
    c=estimate(10000,[100,200],[50,60],gaps=[0,1900])
    assert a['uncached_input_tokens']==20300 and a['cache_write_tokens']==a['cache_read_tokens']==0
    assert b['uncached_input_tokens']==300 and b['cache_write_tokens']==b['cache_read_tokens']==10000
    assert c['cache_write_tokens']==20000 and c['cache_read_tokens']==0
    assert b['cost_parts_usd']['output']==a['cost_parts_usd']['output']==.0011
    assert b['total_usd']<a['total_usd']<c['total_usd']


def test_real_sdk_constructs_explicit_request_without_network(ready,monkeypatch):
    import openai
    from litreview.llm import openai_compatible as client
    _,p=ready;seen=[]
    def post(path,*,body,**kwargs):
        value=json.loads(json.dumps(body));seen.append(value)
        assert path=='/chat/completions'
        assert value['prompt_cache_options']=={'mode':'explicit','ttl':'30m'}
        assert value['messages'][1]['content'][0]['prompt_cache_breakpoint']=={'mode':'explicit'}
        return openai.types.chat.ChatCompletion.model_validate({'id':'synthetic','object':'chat.completion','created':0,'model':'gpt-6.1-sol',
          'choices':[{'index':0,'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}],
          'usage':{'prompt_tokens':10000,'completion_tokens':100,'total_tokens':10100,'prompt_tokens_details':{'cached_tokens':8000,'cache_write_tokens':1000}}})
    sdk=openai.OpenAI(api_key='synthetic-test-only',base_url='https://offline.invalid/v1',max_retries=0)
    monkeypatch.setattr(sdk,'post',post)
    monkeypatch.setitem(client._clients,'openai',sdk)
    result=client.complete('System',user_parts(b.batches(p,shared_prefix=True)[0]),'gpt-6.1-sol',64000,0)
    assert len(seen)==1 and result.input_tokens==1000 and result.cached_input_tokens==8000 and result.cache_write_tokens==1000
    sdk.close()
