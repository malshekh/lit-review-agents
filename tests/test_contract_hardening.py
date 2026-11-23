"""Offline schema and financial refusal regressions; no providers or live runs."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from litreview.agents.base import validate
from litreview.writing_admission import quote_call, require_hold
from litreview.admission import AdmissionRefused
from litreview.budget import BudgetTracker
ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=json.loads((ROOT/'docs/a07_a12_contract_hardening/schema_examples.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('name',sorted(EXAMPLES))
def test_real_schema_good_and_missing_required_bad(name):
    import jsonschema
    good=copy.deepcopy(EXAMPLES[name])
    validate(name.split('.')[0],good,name)
    schema=json.loads((ROOT/'schemas'/name).read_text(encoding='utf-8'))
    bad=copy.deepcopy(good);bad.pop(schema['required'][0])
    with pytest.raises(jsonschema.ValidationError):validate(name.split('.')[0],bad,name)

@pytest.mark.parametrize('kind',['missing_mode','long_rationale','long_proposal','fifteen_ids','array_unresolved'])
def test_v10_violation_types_fail_production_validator(kind):
    import jsonschema
    name='A07-SYN.bounded-plan.schema.json';p=copy.deepcopy(EXAMPLES[name])
    if kind=='missing_mode':p.pop('mode')
    elif kind=='array_unresolved':p['unresolved_questions']=[{'theme_id':'T1','questions':'["a list written inside a string"]'}]
    else:
        q={'proposal':'Formatting fixture','rationale':'Formatting fixture','finding_ids':['R0001:F1']}
        if kind=='long_rationale':q['rationale']='x'*481
        if kind=='long_proposal':q['proposal']='x'*481
        if kind=='fifteen_ids':q['finding_ids']=['R0001:F'+str(i) for i in range(15)]
        p['theme_change_proposals']=[q]
    with pytest.raises(jsonschema.ValidationError):validate('A07-SYN',p,name)

def test_real_reserve_blocks_subcap_before_send(tmp_path):
    b=BudgetTracker(tmp_path);b.operational_ceiling=.01
    model=SimpleNamespace(provider='anthropic',model='claude-opus-5',max_tokens=12000)
    amount=quote_call('system',[{'text':'payload','cache':False}],model,{'reasoning_reserve_tokens':{'anthropic':0}},b)
    sent=[]
    ok,_=b.reserve('synthetic-only',amount,'A07-SYN')
    if ok:sent.append('provider would run')
    assert not ok and not sent and not b.reservations()

def test_actual_hold_check_and_settlement(tmp_path):
    b=BudgetTracker(tmp_path);b.operational_ceiling=1
    assert b.reserve('synthetic-only',.5,'A09-WRI')[0]
    require_hold(b,'synthetic-only',.5)
    with pytest.raises(AdmissionRefused):require_hold(b,'synthetic-only',.51)
    b.record('A09-WRI','anthropic','claude-opus-5',10,10,step='synthetic',reservation_key='synthetic-only')
    b.release('synthetic-only')
    assert not b.reservations() and b.spent()>0


def test_private_provider_audit_retains_all_blocks_without_overwrite(tmp_path,monkeypatch):
    from litreview.llm import anthropic_client
    folder=tmp_path/'private';folder.mkdir()
    monkeypatch.setattr(anthropic_client.config,'load',lambda _: {'providers':{'anthropic':{'writing_response_audit_dir':str(folder)}}})
    raw={'id':'synthetic','stop_reason':'end_turn','usage':{'output_tokens':17,'output_tokens_details':{'thinking_tokens':7}},'content':[{'type':'thinking','thinking':'synthetic private fixture'},{'type':'text','text':'{}'},{'type':'redacted_thinking','data':'synthetic'}]}
    response=SimpleNamespace(model_dump=lambda **kw:raw)
    trace={'run_id':'offline','step':'A09-WRI_section','attempt':0}
    path,meta=anthropic_client._preserve_plan_response(response,trace)
    assert json.loads(Path(path).read_text(encoding='utf-8'))==raw
    assert meta['content_block_types']==['thinking','text','redacted_thinking']
    assert meta['usage']['output_tokens_details']['thinking_tokens']==7
    with pytest.raises(ValueError,match='overwrite'):anthropic_client._preserve_plan_response(response,trace)


def test_native_writing_reservation_holds_margin_and_blocks_subcap(tmp_path,monkeypatch):
    from litreview.orchestrator import Run
    from litreview import pilot_authorization
    monkeypatch.setattr(pilot_authorization,'enabled',lambda _:False)
    b=BudgetTracker(tmp_path);b.operational_ceiling=.12
    r=SimpleNamespace(budget=b)
    assert Run._reserve(r,'too-large',.1,'A07-SYN')[0] is False
    b.operational_ceiling=.14
    assert Run._reserve(r,'fits',.1,'A09-WRI')[0]
    assert b.reservations()['fits']['usd']==.13
    b.release('fits')


MODE_EXAMPLES=json.loads((ROOT/'docs/a07_a12_contract_hardening/mode_examples.json').read_text())
@pytest.mark.parametrize('row',MODE_EXAMPLES,ids=lambda row:row['schema']+':'+row['mode'])
def test_every_a10_a12_mode_shape(row):
    validate(row['schema'].split('.')[0],row['payload'],row['schema'])
