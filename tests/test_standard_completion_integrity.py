"""Replay the four reconciled v33 dispatch chains, then a fifth completion on restart."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from litreview.runtime_integrity import IntegrityError, verify
from scripts.build_pilot7_cp_syn_runtime import POLICY


def write_rows(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b''.join(json.dumps(r).encode()+b'\n' for r in rows))


@pytest.fixture
def replay(tmp_path):
    rows=json.loads((Path(__file__).parent/'fixtures/v33_completion_chains.json').read_bytes())
    policy=copy.deepcopy(POLICY)
    run=tmp_path/'runs'/policy['run_id']
    (run/'outputs').mkdir(parents=True)
    (run/'state.json').write_text('{"execution_mode":"STANDARD"}')
    prefix=b'baseline\n'
    baseline=tmp_path/'candidate/baseline.jsonl'
    baseline.parent.mkdir()
    baseline.write_bytes(prefix)
    telemetry=tmp_path/'records/model_record.jsonl'
    telemetry.parent.mkdir()
    def materialize():
        write_rows(run/'data/job_ledger.jsonl',[e for row in rows for e in row['events']])
        write_rows(run/'costs.jsonl',[row['charge'] for row in rows])
        for row in rows:
            step=row['event']['step']
            (run/'outputs'/f'{step}.response0.json').write_text(json.dumps(row['response']),encoding='utf8')
            (run/'outputs'/f'{step}.raw0.txt').write_text(row['response']['text'],encoding='utf8')
        telemetry.write_bytes(prefix+b''.join(json.dumps(row['event']).encode()+b'\n' for row in rows))
    materialize()
    policy.update(inherited_bytes=telemetry.stat().st_size,inherited_sha256=hashlib.sha256(telemetry.read_bytes()).hexdigest())
    manifest={'files':{'candidate/baseline.jsonl':hashlib.sha256(prefix).hexdigest()},
              'mutable_telemetry':{'baseline':'candidate/baseline.jsonl','standard_completions':policy}}
    return tmp_path,manifest,rows,materialize,telemetry


def test_original_four_and_next_completion_across_restart(replay):
    root,manifest,rows,save,_=replay
    assert verify(root,manifest)['telemetry_appends_verified']==4
    new=copy.deepcopy(rows[-1])
    # Simulated first newly authorized abstract extraction, using a distinct attempt and charge.
    fields={'step':'A05-KE_R0058','model':'claude-sonnet-5-5','agent':'A05-KE','provider':'anthropic',
            'reservation_key':'call-next','reservation':'call-next','request_id':'a'*64}
    for obj in [new['event'],new['charge'],*new['events'],new['response'],new['response']['request']]:
        obj.update({k:v for k,v in fields.items() if k in obj})
    new['response']['stop_reason']='end_turn'
    rows.append(new)
    save()
    for _ in range(2):
        assert verify(root,manifest)['telemetry_appends_verified']==5


@pytest.mark.parametrize('change',['duplicate','unmatched','prefix','charge','receipt','dispatch','request'])
def test_invalid_completion_chain_refused(replay,change):
    root,manifest,rows,save,telemetry=replay
    if change in ('duplicate','unmatched'):
        event=dict(rows[0]['event'])
        if change=='unmatched':event['step']='A06-SV_R0039_v1'
        with telemetry.open('ab') as file:file.write(json.dumps(event).encode()+b'\n')
    elif change=='prefix':
        telemetry.write_bytes(b'X'+telemetry.read_bytes()[1:])
    else:
        if change=='charge':rows[0]['charge']['cost_usd']+=1
        if change=='receipt':rows[0]['response']['output_tokens']+=1
        if change=='dispatch':rows[0]['events']=[x for x in rows[0]['events'] if x['state']!='DISPATCHED']
        if change=='request':rows[0]['response']['request']['request_id']='different'
        save()
    with pytest.raises(IntegrityError):verify(root,manifest)

