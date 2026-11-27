"""Replay the unedited v40 output under the sealed and candidate validators, with no transport."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from unittest.mock import patch

root=Path.cwd()
repo=Path(__file__).resolve().parents[1]
outdir=Path(sys.argv[1]).resolve()
assert not outdir.is_relative_to(root) and sys.flags.isolated
sys.path[:0]=[str(root/'src'),str(root/'vendor')]
from litreview import orchestrator
from litreview.agents.base import parse_json,validate
from litreview.runtime_integrity import sha,verify
from litreview.synthesis_job import JobStopped
from litreview.synthesis_registry import fingerprint

turn='RECONCILE_1102'
run_id='20261123-214928'
target='8e6dec8625b8d60eceb02217b0c7f29bcfd621c0b9e4fab2cc58faccbdbd294c'
live=root/'runs'/run_id

def read(p): return json.loads(p.read_bytes())

def candidate(name):
    spec=importlib.util.spec_from_file_location('litreview.'+name,repo/'src/litreview'/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module

def rehearse(tmp):
    manifest=root/'frozen_runtime_manifest.json'
    assert sha(manifest)=='437bcca20bb0f942ef84d0763591fcec9458a768229a566abf37c1531060bf34'
    verify(root,read(manifest))
    orchestrator.RUNS_DIR=tmp/'runs'
    shutil.copytree(live,orchestrator.RUNS_DIR/run_id)
    run=orchestrator.Run(run_id)
    job,tag=run._synthesis_job()
    step='A07-SYN_job'+tag+'_'+turn+'_LOOKUP0'
    saved=run.dir/'outputs'/(step+'.json')
    assert sha(saved)==target
    response=saved.read_bytes()
    assert parse_json(saved.with_suffix('.raw0.txt').read_text(encoding='utf8'))==json.loads(response)
    validate('A07-SYN', json.loads(response),'A07-SYN.bounded-reconcile.schema.json')
    sent=run.load('agent_inputs/'+step+'.json')['payload']
    ids=sorted(sent['prefill_finding_ids'])
    assert len(ids)==29 and len(sent['focus'])==21
    assert job.registry.details(ids)==sent['retrieved_evidence']
    def replay(doc):
        def supply(mode,p,name):
            assert mode=='RECONCILE' and name==turn+'_LOOKUP0'
            assert all(sent[k]==v for k,v in p.items())
            return json.loads(doc)
        job.call=supply
        job.served_by=lambda:'offline v40 byte replay only'
        job.reconcile(only_turn=turn)
    failures={}
    def reject(name,doc,expected):
        try:replay(doc)
        except JobStopped as e:
            assert expected in str(e),str(e)
            failures[name]=str(e)
        else:raise AssertionError(name+' unexpectedly accepted')
    reject('original rejection',response,'unexpected Israel interpretation')
    candidate('reconciliation_links')
    job.__class__=candidate('synthesis_bounded').RegistrySynthesisJob
    obj=json.loads(response)
    sentence=next(r['rationale'] for r in obj['reviews'] if r['proposition_id']=='GROUP_G0003.P5')
    for name,txt in [('swapped scores',sentence.replace('100%','TEMP').replace('50%','100%').replace('TEMP','50%')),
                     ('conflated settings',sentence.replace('intermediate-concentration test set','three-fold cross-validation')),
                     ('unsupported cause',sentence+' Model choice explains the SVM decline.')]:
        changed=copy.deepcopy(obj)
        next(r for r in changed['reviews'] if r['proposition_id']=='GROUP_G0003.P5')['rationale']=txt
        reject(name,json.dumps(changed).encode(),'unexpected Israel interpretation')
    replay(response)
    accepted=job._committed(turn)
    assert len(accepted['reviews'])==21 and len(accepted['issues'])==6 and sha(saved)==target
    props={p['proposition_id']:p for p in job._all_props()}
    findings=job.registry.findings
    citations=props['GROUP_G0003.P11']['evidence']
    assert all(e['finding_id'] in ids for e in citations)
    result={'input_sha256':target,'raw_text_sha256':sha(saved.with_suffix('.raw0.txt')),
            'receipt_sha256':sha(saved.with_suffix('.provider.receipt0.json')),'checks':failures,
            'schema_and_production_replay':'passed on disposable copy','scientific_disposition':'pending researcher decision; no import',
            'actual_offline_cost_usd':0,'original_charge_usd':0.4622565,
            'reviews':[{'review':r,'proposition':props[r['proposition_id']]['assertion'],
                        'frozen_links':props[r['proposition_id']]['evidence']} for r in obj['reviews']],
            'issues':obj['issues'],'P11_records':{e['finding_id']:{k:findings[e['finding_id']].get(k) for k in
                ('record_id','context_id','span','plain_language_limit')} for e in citations},
            'F13_F14':{i:findings[i]['span'] for i in ('R0078:F13','R0078:F14')}}
    return result

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as t,patch.object(socket.socket,'connect',side_effect=AssertionError('offline')):
        before={p.relative_to(live):sha(p) for p in live.rglob('*') if p.is_file()}
        result=rehearse(Path(t))
        assert before=={p.relative_to(live):sha(p) for p in live.rglob('*') if p.is_file()}
        result['unchanged_live_files']=len(before)
        outdir.mkdir(parents=True,exist_ok=True)
        (outdir/'replay.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
        print(result['checks'],len(before))
