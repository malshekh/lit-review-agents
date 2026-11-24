import json
import pytest
from litreview import runtime_integrity as ri

@pytest.fixture
def bundle(tmp_path):
    (tmp_path/'src').mkdir();(tmp_path/'src/code.py').write_text('pass\n')
    (tmp_path/'records').mkdir();(tmp_path/'records/model_record.baseline.jsonl').write_bytes(b'')
    (tmp_path/'records/model_record.jsonl').write_bytes(b'')
    files={p.relative_to(tmp_path).as_posix():ri.sha(p) for p in tmp_path.rglob('*') if p.is_file() and p.name!='model_record.jsonl'}
    return tmp_path,{'files':files,'mutable_telemetry':{'baseline':'records/model_record.baseline.jsonl'}}

def test_immutable_inventory_passes(bundle):
    assert ri.verify(*bundle)['immutable_files_verified']==2

@pytest.mark.parametrize('kind',['changed','extra','removed'])
def test_code_tampering_is_detected(bundle,kind):
    root,m=bundle
    if kind=='changed':(root/'src/code.py').write_text('changed')
    elif kind=='extra':(root/'src/extra.py').write_text('pass')
    else:(root/'src/code.py').unlink()
    with pytest.raises(ri.IntegrityError):ri.verify(root,m)

def append(root,logged=True):
    run=root/'runs/synthetic';run.mkdir(parents=True)
    (run/'state.json').write_text(json.dumps({'execution_mode':'STAGED_PILOT'}))
    event={'time':'synthetic','model':'synthetic','agent':'A03-LM','family':'synthetic','outcome':'COMPLETED','category':None,'run_id':'synthetic','step':'synthetic'}
    (run/'costs.jsonl').write_text(json.dumps(event)+'\n' if logged else '')
    (root/'records/model_record.jsonl').write_text(json.dumps(event)+'\n')

def test_legitimate_logging_is_mutable_without_manifest_change(bundle):
    root,m=bundle;append(root)
    assert ri.verify(root,m)['telemetry_appends_verified']==1

@pytest.mark.parametrize('kind',['unlogged','prefix','truncated'])
def test_unapproved_telemetry_is_detected(bundle,kind):
    root,m=bundle;append(root,logged=kind!='unlogged')
    if kind=='prefix':
        seed=root/'records/model_record.baseline.jsonl';seed.write_bytes(b'original\n');m['files'][seed.relative_to(root).as_posix()]=ri.sha(seed)
    elif kind=='truncated':
        p=root/'records/model_record.jsonl';p.write_bytes(p.read_bytes().rstrip(b'\n'))
    with pytest.raises(ri.IntegrityError):ri.verify(root,m)
