"""Continuation preserves accounting and receipt bytes, even when a previous smoke approval is incompatible."""
import copy,json
from pathlib import Path
import pytest,yaml
from litreview import config,structured,smoke_validation
from litreview.smoke_migration import migrate,inventory
from litreview.runtime_integrity import sha

def seal(path,commit):
    (path/'records').mkdir(exist_ok=True);(path/'candidate').mkdir(exist_ok=True)
    (path/'records/model_record.jsonl').write_text('');(path/'candidate/model_record_baseline.jsonl').write_text('')
    manifest={'git_commit':commit,'files':{p.relative_to(path).as_posix():sha(p) for p in path.rglob('*') if p.is_file() and 'runs' not in p.relative_to(path).parts[:1] and p.relative_to(path).as_posix()!='records/model_record.jsonl'},'mutable_telemetry':{'baseline':'candidate/model_record_baseline.jsonl'}}
    (path/'frozen_runtime_manifest.json').write_text(json.dumps(manifest))
    return sha(path/'frozen_runtime_manifest.json')

def test_migration_preserves_the_spend_unknown_hold_and_receipts(tmp_path):
    source=tmp_path/'source';dest=tmp_path/'dest';source.mkdir();dest.mkdir()
    cfg=copy.deepcopy(config.load('pipeline'));cfg['profiles']['pilot7'].update(spend_cap_usd=50,smoke_test_allowance_usd=1,spend_review_points_usd=[25,48]);cfg['routing']['alternates']={}
    for root in [source,dest]:
        (root/'config').mkdir();(root/'config/pipeline.yaml').write_text(yaml.safe_dump(cfg))
    (source/'src/litreview/tools').mkdir(parents=True)
    (source/'src/litreview/tools/contract.py').write_text('def for_structured_output(schema): return schema, []\n')
    (source/'schemas').mkdir()
    name='A07-SYN.bounded-plan.schema.json';shape,digest=structured.slim(name,'anthropic')
    (source/'schemas'/name).write_text(json.dumps(shape))
    r=source/'runs/test';r.mkdir(parents=True);(r/'input').mkdir();(r/'smoke_receipts').mkdir()
    (r/'state.json').write_text(json.dumps({'profile':'pilot7','stage':'scope','status':'READY'}))
    (r/'input/runtime_pin.json').write_text('{}')
    examples=json.loads((Path(__file__).resolve().parents[1]/'docs/a07_a12_contract_hardening/schema_examples.json').read_text(encoding='utf-8'))
    receipt={'state':'RECEIVED','reservation':'smoke-good','provider':'anthropic','model':'claude-opus-5','schema_sha256':digest,'input_tokens':1,'output_tokens':1,'text':json.dumps(examples[name])}
    (r/'smoke_receipts/good.json').write_text(json.dumps(receipt))
    (r/'smoke_receipts/unknown.json').write_text(json.dumps({'state':'DISPATCHED','reservation':'smoke-unknown','target':'A05-KE.schema.json'}))
    (r/'smoke_tests.jsonl').write_text(json.dumps({'provider':'anthropic','model':'claude-opus-5','schema_sha256':digest,'schema_file':name,'accepted':True,'stop_reason':'end_turn'})+'\n')
    (r/'costs.jsonl').write_text(json.dumps({'agent':'smoke-test','step':'smoke-good','provider':'anthropic','model':'claude-opus-5','cost_usd':0.01})+'\n')
    (r/'reservations.json').write_text(json.dumps({'smoke-unknown':{'usd':0.019586,'agent':'smoke-test'}}))
    (r/'structured_output.json').write_text(json.dumps({'incompatible-old-approval':{'accepted':True}}))
    source_pin=seal(source,'old');dest_pin=seal(dest,'new');before=inventory(r)
    report=migrate(source,dest,'test',source_pin,dest_pin)
    assert report['recorded_spend_usd']==0.01 and report['eligible_reuse_count']==1
    assert report['outstanding_reservations']['smoke-unknown']['usd']==0.019586
    target=dest/'runs/test'
    assert inventory(r)==before
    for filename in ['costs.jsonl','reservations.json','smoke_receipts/good.json','smoke_receipts/unknown.json']:
        assert (r/filename).read_bytes()==(target/filename).read_bytes()
    records=json.loads((target/'structured_output.json').read_text())
    assert 'incompatible-old-approval' not in records
    assert list(records.values())[0]['validation_version']==2
    assert (target/'migration/v15_original/structured_output.json').read_bytes()==(r/'structured_output.json').read_bytes()
    assert migrate(source,dest,'test',source_pin,dest_pin)['destination_commit']=='new'
    with pytest.raises(ValueError,match='pinned manifest'):
        migrate(source,dest,'test','wrong',dest_pin)


@pytest.mark.parametrize("good_name,bad_name",[("a","z"),("z","a")])
def test_recovery_preserves_valid_success_regardless_of_receipt_filename_order(tmp_path,monkeypatch,good_name,bad_name):
    from litreview.budget import BudgetTracker
    shape={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    digest=smoke_validation.schema_hash(shape)
    monkeypatch.setattr(structured,"slim",lambda *args:(shape,digest))
    monkeypatch.setattr(structured,"RECORD",tmp_path/"structured_output.json")
    folder=tmp_path/"smoke_receipts";folder.mkdir()
    costs=[]
    for name,body in [(good_name,'{"ok":true}'),(bad_name,'{}')]:
        key="smoke-"+name
        (folder/(name+".json")).write_text(json.dumps({"state":"RECEIVED","reservation":key,"provider":"openai","model":"gpt-6.1-sol",
            "schema_file":"fixture.json","schema_sha256":digest,"submitted_schema":shape,"stop_reason":"stop","text":body,"input_tokens":1,"output_tokens":1}))
        costs.append({"step":key,"agent":"smoke-test","cost_usd":0.01})
    (tmp_path/"costs.jsonl").write_text("\n".join(map(json.dumps,costs))+"\n")
    before={p:p.read_bytes() for p in folder.iterdir()}
    b=BudgetTracker(tmp_path)
    structured.recover_smoke_receipts(b)
    assert structured.verified()[structured._key("openai","gpt-6.1-sol",digest)]["accepted"]
    assert b.spent()==0.02 and len(b.entries())==2
    assert all(p.read_bytes()==raw for p,raw in before.items())
