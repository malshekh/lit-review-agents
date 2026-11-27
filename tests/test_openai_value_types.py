"""Regress the exact A08 rejection and audit the request body actually submitted to OpenAI."""
import copy,json
from pathlib import Path
import jsonschema,pytest
from litreview import structured
from litreview.tools import contract,structured_contract
from litreview.llm.openai_compatible import chat_params
ROOT=Path(__file__).resolve().parents[1]


def nodes(n,path='$'):
    if not isinstance(n,dict):return
    yield path,n
    for k,v in n.get('properties',{}).items():yield from nodes(v,path+'.'+k)
    if 'items' in n:yield from nodes(n['items'],path+'[]')
    for key in ('$defs','definitions'):
        for k,v in n.get(key,{}).items():yield from nodes(v,path+'.'+key+'.'+k)
    for key in ('anyOf','oneOf','allOf'):
        for i,v in enumerate(n.get(key,[])):yield from nodes(v,path+'.'+key+str(i))


def test_exact_rejected_a08_is_detected_and_both_fixed_constants_are_preserved():
    rejected=json.loads((ROOT/'tests/fixtures/rejected_a08_openai.schema.json').read_text())
    errors=structured_contract.problems(rejected,'openai')
    assert any('display_id' in e and 'explicit type' in e for e in errors)
    assert any('display_items[].type' in e and 'explicit type' in e for e in errors)
    source=json.loads((ROOT/'schemas/A08-OL.schema.json').read_text())
    props=source['properties']['display_items']['items']['properties']
    assert props['display_id']=={'const':'T1','type':'string'}
    assert props['type']=={'const':'TABLE_COMPARISON','type':'string'}
    fixed,_=contract.for_structured_output(rejected,'openai')
    assert not structured_contract.problems(fixed,'openai')
    for (old_path,old),(new_path,new) in zip(nodes(rejected),nodes(fixed)):
        assert old_path==new_path
        if 'enum' in old:assert old['enum']==new['enum']
        if 'const' in old:assert old['const']==new['const']
        assert set(old.get('properties',{}))==set(new.get('properties',{}))


def test_every_actual_openai_request_declares_value_types():
    targets=[t for t in structured.targets() if t['provider']=='openai']
    assert len(targets)==5
    for t in targets:
        request=chat_params('s','u',t['model'],1500,0,'openai',t['effort'],{'name':'audit','schema':t['schema']})
        wire=request['response_format']['json_schema']
        assert wire['strict'] is True
        assert all('type' in n for _,n in nodes(wire['schema']) if 'const' in n or 'enum' in n)
        assert not structured_contract.problems(wire['schema'],'openai')

@pytest.mark.parametrize('constraint',[{'const':'T1'},{'enum':['CORE','CONTEXT']}])
def test_string_value_type_completion_is_semantically_equivalent_and_provider_specific(constraint):
    source={'type':'object','properties':{'value':constraint},'required':['value'],'additionalProperties':False}
    fixed,_=contract.for_structured_output(source,'openai')
    for value in ['T1','T2','CORE','CONTEXT','',None,True,1,[],{}]:
        assert jsonschema.Draft202012Validator(source).is_valid({'value':value})==jsonschema.Draft202012Validator(fixed).is_valid({'value':value})
    assert contract.for_structured_output(source,'anthropic')[0]==source


def test_missing_types_inside_definitions_refs_items_and_branches_are_audited():
    shape={'type':'object','properties':{'rows':{'type':'array','items':{'$ref':'#/$defs/value'}}},'required':['rows'],'additionalProperties':False,
        '$defs':{'value':{'anyOf':[{'enum':['A','B']},{'type':'null'}]}}}
    assert any('explicit type' in x for x in structured_contract.problems(shape,'openai'))
    fixed,_=contract.for_structured_output(shape,'openai')
    assert not structured_contract.problems(fixed,'openai')
    assert fixed['$defs']['value']['anyOf'][0]['type']=='string'


def test_future_smoke_forecast_and_receipt_recovery_include_implicit_cache_writes(tmp_path,monkeypatch):
    from litreview.budget import BudgetTracker
    b=BudgetTracker(tmp_path)
    shape={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
    digest=structured.smoke_validation.schema_hash(shape)
    monkeypatch.setattr(structured,'RECORD',tmp_path/'structured_output.json')
    monkeypatch.setattr(structured,'slim',lambda *a:(shape,digest))
    bound=structured.smoke_worst(b,'openai','gpt-6.1-sol',1000,1500)
    assert bound>=b.cost('gpt-6.1-sol',0,1500,cache_write_tokens=1000)
    r={'state':'RECEIVED','reservation':'smoke-cache','provider':'openai','model':'gpt-6.1-sol',
       'schema_sha256':digest,'schema_file':'fixture','submitted_schema':shape,'text':'{"ok":true}','stop_reason':'stop',
       'input_tokens':3,'output_tokens':10,'cached_input_tokens':0,'cache_write_tokens':1000,'cache_write_1h_tokens':0}
    folder=tmp_path/'smoke_receipts';folder.mkdir();p=folder/'smoke-cache.json';p.write_text(json.dumps(r));before=p.read_bytes()
    structured.recover_smoke_receipts(b)
    assert b.entries()[0]['cache_write_tokens']==1000
    assert b.spent()==pytest.approx(b.cost('gpt-6.1-sol',3,10,cache_write_tokens=1000))
    structured.recover_smoke_receipts(b)
    assert len(b.entries())==1 and p.read_bytes()==before
