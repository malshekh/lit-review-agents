"""Scientific extraction shapes, recursive provider compatibility and exact smoke acceptance."""
import copy,json
from pathlib import Path
import pytest,jsonschema
from litreview.agents.base import validate
from litreview import structured,smoke_validation
from litreview.tools import contract,span_check,structured_contract
ROOT=Path(__file__).resolve().parents[1]

def _wire_fill(schema, value):
    # Synthetic fixture completion records missingness only; existing scientific values are never changed.
    if '$ref' in schema:raise AssertionError('fixture has no references')
    if 'anyOf' in schema:
        if value is None and any(x.get('type')=='null' for x in schema['anyOf']):return None
        return _wire_fill(next(x for x in schema['anyOf'] if x.get('type')!='null'),value)
    kind=schema.get('type')
    if kind=='object':
        value=value or {}
        return {k:_wire_fill(v,value.get(k)) for k,v in schema['properties'].items()}
    if kind=='array':return [_wire_fill(schema['items'],v) for v in value or []]
    if value is not None:return value
    if kind=='null' or isinstance(kind,list) and 'null' in kind:return None
    if 'const' in schema:return schema['const']
    if kind=='boolean':return False
    return 'NOT_REPORTED'


def extraction():
    span='Doxorubicin was measured at 5 nM in spiked plasma compared with vehicle (n=3).'
    value={'agent_id':'A05-KE','prompt_version':'1.0','status':'COMPLETE','warnings':[],
      'limitations':['Spiked plasma; no samples collected after administration.'],'record_id':'R0001',
      'content_level':'FULL_TEXT','sections_inspected':['Results','Figure legend Figure 1'],
      'study_profile':{'study_type':'PRIMARY_RESEARCH','evidence_systems':['IN_VITRO_CELL_FREE'],'funding_and_conflicts':'NOT_REPORTED'},
      'entities':[{'entity_id':'E1','mention':'Doxorubicin','type':'DRUG_STATUS_UNVERIFIED','normalized_id':None,'normalization_state':None},
                  {'entity_id':'E2','mention':'plasma','type':'MATERIAL'}],
      'contexts':[{'context_id':'C1','fields':{'evidence_system':'IN_VITRO_CELL_FREE','comparator':'VEHICLE','matrix':'spiked plasma','n':'3','replicate_type':'TECHNICAL'},
                   'context_source':'IN_SPAN','context_spans':[span]}],
      'findings':[{'finding_id':'F1','subject_entity_id':'E1','predicate':'DETECTED_IN','object_entity_id':'E2','polarity':'POSITIVE',
                   'modality':'ASSERTED','direction':'NOT_APPLICABLE','assertion_type':'REPORTED_RESULT','origin':'EXPLICIT','context_id':'C1',
                   'span':span,'span_location':{'section':'Results','figure_or_table':None,'paragraph':'1'},'warrant_note':'A measurement in spiked plasma only.',
                   'primary_theme_id':'T1','quantities':[{'measured_property':'concentration','raw_value':'5','raw_unit':'nM','value_type':'SINGLE_TESTED_CONCENTRATION',
                     'n':'3','variance_or_ci':None,'p_value':None,'converted':None}]}],
      'author_stated_limitations':[{'text':'No patient samples were tested.','location':'Discussion'}],
      'source_access':{'level':'FULL_TEXT','figure_legends_read':True,'figure_images_inspected':False,'supplements_inspected':False}}
    return _wire_fill(json.loads((ROOT/'schemas/A05-KE.anthropic.schema.json').read_text()),value)

def test_complete_nonempty_extraction_reaches_real_independent_validation_input(tmp_path,monkeypatch):
    from litreview import orchestrator as orch,model_record
    ext=extraction(); validate('A05-KE',ext)
    shape,digest=structured.slim('A05-KE.schema.json','anthropic')
    jsonschema.validate(ext,shape)
    sections={'Results':ext['findings'][0]['span'],'Discussion':'No patient samples were tested.'}
    assert all(span_check.passed(g) for g in span_check.check_findings(ext,sections))
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path)
    monkeypatch.setattr(model_record,'RECORD',tmp_path/'model.jsonl')
    run=orch.Run('test');run.save_state({'stage':'validate','profile':'pilot7','counters':{}})
    run.save('spec_approved.json',{'central_question':'Measured drug concentrations?'})
    run.save('extractions/R0001.json',ext);run.save('fulltext/R0001.json',sections)
    run.save('source_access.json',{'R0001':ext['source_access']})
    run.budget.record('A05-KE','anthropic','claude-sonnet-5-5',100,50,step='A05-KE_R0001')
    seen=[]
    def agent(a,p,step,**kwargs):
        seen.append(p)
        assert kwargs['exclude_providers']==frozenset({'anthropic'})
        assert p['extraction']['contexts'][0]['fields']['comparator']=='VEHICLE'
        assert p['source_access']['figure_legends_read'] and not p['source_access']['figure_images_inspected']
        return {'agent_id':'A06-SV','prompt_version':'1.0','status':'COMPLETE','warnings':[],'limitations':[],
          'mode':'PER_PAPER','record_id':'R0001','validations':[{'finding_id':'F1','disposition':'SUPPORTED_WITH_CONSTRAINTS','gate1':'PASSED',
          'constraints':['Spiked plasma only.'],'plain_language_limit':'No post-administration or longitudinal evidence.'}]}
    monkeypatch.setattr(run,'agent',agent)
    run._validate_papers(['R0001'])
    assert seen and run.load('validations/R0001.json')['validations'][0]['disposition']=='SUPPORTED_WITH_CONSTRAINTS'

@pytest.mark.parametrize('mutate',[lambda e:e['findings'][0].update(subject_entity_id='UNKNOWN'),
    lambda e:e['contexts'][0]['fields'].pop('comparator'),lambda e:e['findings'][0].update(origin='SAME_SOURCE_IMPLICIT'),
    lambda e:e['source_access'].update(figure_images_inspected=True),lambda e:e['entities'].append(copy.deepcopy(e['entities'][0]))])
def test_bad_scientific_handoffs_are_rejected(mutate):
    e=extraction();mutate(e)
    with pytest.raises(jsonschema.ValidationError):validate('A05-KE',e)

@pytest.mark.parametrize('schema',[
 {'type':'object'}, {'type':'array'},
 {'type':'object','properties':{'x':{'type':'string'}},'required':['lost'],'additionalProperties':False},
 {'type':'object','properties':{'nested':{'type':'array','items':{'type':'object'}}},'additionalProperties':False},
 {'type':'object','properties':{'value':{'$ref':'#/$defs/bad'}},'additionalProperties':False,'$defs':{'bad':{'type':'array'}}},
 {'anyOf':[{'type':'object'}]}, {'oneOf':[{'type':'string'},{'type':'integer'}]}
])
def test_recursive_shape_problems_fail_before_dispatch(schema):
    with pytest.raises(structured_contract.SchemaCompatibilityError):contract.for_structured_output(schema,'anthropic')

def test_provider_requirements_do_not_universally_rewrite_optional_fields():
    schema={'type':'object','properties':{'optional':{'type':'string'}},'additionalProperties':False}
    shape,_=contract.for_structured_output(schema,'anthropic')
    assert 'required' not in shape
    with pytest.raises(structured_contract.SchemaCompatibilityError):contract.for_structured_output(schema,'openai')
    assert 'required' not in schema

@pytest.fixture
def legacy_a02(tmp_path,monkeypatch):
    """The configured schemas with A02 reverted to an open, undefined contract (the shape the audit found)."""
    import shutil
    from litreview.paths import SCHEMAS_DIR
    d=tmp_path/'schemas';shutil.copytree(SCHEMAS_DIR,d)
    s=json.loads((d/'A02-SP.schema.json').read_text(encoding='utf-8'))
    s['properties']['readiness']={'type':'object'};s['properties']['assumptions']={'type':'array'};s['additionalProperties']=True
    (d/'A02-SP.schema.json').write_text(json.dumps(s),encoding='utf-8')
    monkeypatch.setattr(structured,'SCHEMAS_DIR',d)
    return d

def test_every_configured_schema_is_audited_and_legacy_gaps_are_blockers(legacy_a02):
    rows=structured.schema_inventory()
    assert len(rows)==15
    assert not next(r for r in rows if r['schema_file']=='A05-KE.schema.json')['problems']
    assert next(r for r in rows if r['schema_file']=='A02-SP.schema.json')['problems']
    with pytest.raises(structured_contract.SchemaCompatibilityError):structured.targets()

@pytest.mark.parametrize('provider,stop,text,accepted',[
 ('openai','stop','{"value":"x"}',True),('anthropic','end_turn','{"value":"x"}',True),
 ('anthropic','max_tokens','{"value":"x"}',False),('openai','length','{"value":"x"}',False),
 ('anthropic','refusal','{"value":"x"}',False),('openai','stop','{}',False),('anthropic',None,'{"value":"x"}',False)])
def test_smoke_requires_exact_shape_and_successful_stop(provider,stop,text,accepted):
    shape={'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}
    result=smoke_validation.inspect_response(provider,text,stop,shape,smoke_validation.schema_hash(shape))
    assert result['accepted'] is accepted

def test_submitted_hash_is_checked_not_only_the_record_key():
    assert not smoke_validation.inspect_response('openai','{}','stop',{},'wrong')['accepted']


@pytest.mark.provider_contract_guard
def test_actual_run_preflight_blocks_legacy_contract_before_paid_dispatch(tmp_path,monkeypatch,legacy_a02):
    from litreview import orchestrator as orch
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path)
    run=orch.Run('contract');run.save_state({'stage':'scope','profile':'pilot7','counters':{}})
    monkeypatch.setattr(run,'agent',lambda *a,**k:pytest.fail('paid dispatch'))
    with pytest.raises(orch.Pause,match='provider schema compatibility'):
        run.preflight_routing()
    assert run.load('schema_compatibility.json') and run.budget.spent()==0


@pytest.mark.provider_contract_guard
def test_direct_agent_schema_failure_occurs_before_a_provider_is_called(tmp_path,monkeypatch,legacy_a02):
    from litreview.agents import base
    from litreview.budget import BudgetTracker
    from litreview.provenance import ProvenanceLog
    monkeypatch.setattr(base,'complete',lambda *a,**k:pytest.fail('provider dispatch'))
    b=BudgetTracker(tmp_path)
    with pytest.raises(structured_contract.SchemaCompatibilityError):
        base.run_agent('A02-SP',{},tmp_path,'A02-fixture',b,ProvenanceLog(tmp_path))
    assert b.spent()==0 and not b.reservations()


def test_local_conditional_cannot_hide_an_undeclared_required_scientific_field():
    schema={'type':'object','properties':{'kind':{'type':'string'}},'additionalProperties':False,
            'allOf':[{'if':{'properties':{'kind':{'const':'x'}}},'then':{'required':['lost_scientific_field']}}]}
    with pytest.raises(structured_contract.SchemaCompatibilityError,match='lost_scientific_field'):
        contract.for_structured_output(schema,'anthropic')


def test_recursive_root_ref_is_provider_specific():
    shape={'type':'object','properties':{'children':{'type':'array','items':{'$ref':'#'}}},'required':['children'],'additionalProperties':False}
    assert not structured_contract.problems(shape,'openai')
    assert any('recursive' in e for e in structured_contract.problems(shape,'anthropic'))


def test_receipt_recovery_cannot_reapprove_a_wrong_model(tmp_path):
    shape={'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}
    p=tmp_path/'receipt.json'
    p.write_text(json.dumps({'provider':'openai','model':'requested','response_provider':'openai','response_model':'other',
       'submitted_schema':shape,'schema_sha256':smoke_validation.schema_hash(shape),'stop_reason':'stop','text':'{"value":"x"}'}))
    assert not smoke_validation.receipt_evidence(p)[1]['accepted']


def test_atomic_smoke_record_preserves_previous_file_on_interruption(tmp_path,monkeypatch):
    p=tmp_path/'record.json';p.write_text('{"old":true}')
    monkeypatch.setattr(structured.os,'replace',lambda *a: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):structured._write_json(p,{'new':True})
    assert json.loads(p.read_text())=={'old':True}


def test_authored_wire_contract_keeps_every_local_scientific_property():
    local=json.loads((ROOT/'schemas/A05-KE.schema.json').read_text())
    wire=json.loads((ROOT/'schemas/A05-KE.anthropic.schema.json').read_text())
    def paths(node,at='$'):
        result=set()
        if isinstance(node,dict):
            for key,child in node.get('properties',{}).items():
                result.add(at+'.'+key);result|=paths(child,at+'.'+key)
            if 'items' in node:result|=paths(node['items'],at+'[]')
            for key in ('anyOf','allOf'):
                for child in node.get(key,[]):result|=paths(child,at)
        return result
    assert paths(local)==paths(wire)
    shape,_=structured.slim('A05-KE.schema.json','anthropic')
    assert not structured_contract.problems(shape,'anthropic')


def test_documented_anthropic_complexity_limits_are_checked_offline():
    optional={'type':'object','properties':{str(i):{'type':'string'} for i in range(25)},'additionalProperties':False}
    with pytest.raises(structured_contract.SchemaCompatibilityError,match='optional parameter limit'):
        contract.for_structured_output(optional,'anthropic')
    unions={'type':'object','properties':{str(i):{'type':['string','null']} for i in range(17)},'required':[str(i) for i in range(17)],'additionalProperties':False}
    with pytest.raises(structured_contract.SchemaCompatibilityError,match='union parameter limit'):
        contract.for_structured_output(unions,'anthropic')


def test_definition_and_property_names_are_not_mistaken_for_keywords():
    schema={'type':'object','properties':{'result':{'$ref':'#/$defs/if'}},'required':['result'],'additionalProperties':False,
            '$defs':{'if':{'type':'object','properties':{'then':{'type':'string'}},'required':['then'],'additionalProperties':False}}}
    shape,_=contract.for_structured_output(schema,'anthropic')
    jsonschema.validate({'result':{'then':'scientific value'}},shape)
    assert 'if' in shape['$defs'] and 'then' in shape['$defs']['if']['properties']
