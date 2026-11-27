"""Offline import of the exact G0001 candidate approved by the researcher."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

RUN = '20261123-214928'
TAG = '30edcaaf8d90ed14'
CANDIDATE = 'b7c9595f254305d7327cd2a87b38b5d18c238022e8b71a10e732271f30773159'
PROOF = {
    'run_id': RUN, 'job': 'synthesis_job_' + TAG, 'group': 'G0001', 'candidate_sha256': CANDIDATE,
    'fingerprint': '4f5214ad2942f0d8566980846efd884ffa23803388d179899cda47a89db70016',
    'registry': '4617d5a45df44cfe56d421e766268b6e9ea1bb583b119a3931f9b10f0036e4a7',
    'plan_sha256': '3ba4356dab74cdfdad2710c5f44937768a81612ae63faf0c2756e01ad379ee7b',
    'cp_syn_approved_sha256': 'b172d2242036fedea260262b8a270f40a0224ca12214fa175d0ce5d7fb7bc6b8',
    'review_record_sha256': '243c5244f51b55918edd7e6588fe6f68b720f81e2c9d21c53709b5b5c6cb1cd3',
    'authorized_by': 'researcher', 'authorization': 'Import the reviewed G0001 candidate offline without a paid retry.'
}


def apply(test_copy=False):
    from litreview.orchestrator import Run
    from litreview.job_ledger import RunLock
    from litreview.runtime_integrity import sha
    from litreview.synthesis_job import JobStopped
    from litreview.tools.cost_projection import remaining_for_run
    r=Run(RUN)
    with RunLock(r.dir):
        job,tag=r._synthesis_job()
        assert tag == TAG
        folder=r.data('recovery/G0001_offline_candidate/validation.json').parent
        candidate=(folder/'candidate.json').read_bytes()
        assert sha(folder/'validation.json') == PROOF['review_record_sha256']
        reviews=json.loads((folder/'validation.json').read_bytes())
        assert reviews['candidate_sha256'] == CANDIDATE
        before=sha(r.dir/'costs.jsonl')
        if test_copy:
            for group, contents in [('G0002',candidate), ('G0001',candidate+b' ')]:
                try: job.import_group(group,contents,PROOF)
                except JobStopped as exc: assert 'identity mismatch' in str(exc)
                else: raise AssertionError('invalid candidate accepted')
            assert job._committed('GROUP_G0001') is None
        if job._committed('GROUP_G0001') is None:
            assert all(sha(r.dir/p)==h for p,h in reviews['original_hashes'].items())
            archive=folder/'first_pass'
            archive.mkdir(exist_ok=True)
            for p in [job.dir/'report.json',job.dir/'ledger.jsonl',r.dir/'state.json',r.data('cost_projection.json')]:
                backup=archive/p.name
                if backup.exists():assert sha(p)==sha(backup)
                else:shutil.copy2(p,backup)
        job.import_group('G0001',candidate,PROOF)
        job.import_group('G0001',candidate,PROOF)
        restart,_=Run(RUN)._synthesis_job()
        def no_charge(*args):raise AssertionError('unexpected dispatch on restart')
        restart.call=no_charge
        restart.group(restart.packets[0])
        events=[e for e in restart.ledger.events() if e.get('turn')=='GROUP_G0001']
        assert len(events)==1 and events[0]['event']=='TURN_IMPORTED_REPAIR' and events[0]['satisfied']==reviews['staged']
        assert sha(r.dir/'costs.jsonl')==before
        proj=remaining_for_run(r)
        assert proj['verdict']=='WITHIN_CAP'
        r.save('cost_projection.json',proj)
        print(json.dumps({'copy_test':test_copy,'commit_count':len(events),'zero_new_charges':True,'next_group':restart.packets[1]['group_id'],'forecast_usd':proj['projected_total_usd']}))


if __name__=='__main__':
    if sys.argv[1:] == ['--test-copy']:
        # New implementation; standard runtime dependencies, configuration and source evidence.
        root=Path.cwd()
        sys.path[:0]=[str(root/'src'),str(root/'vendor')]
        import litreview
        litreview.__path__.insert(0,str(Path(__file__).resolve().parents[1]/'src/litreview'))
        from litreview import paths
        for key in ('REPO_ROOT','PROMPTS_DIR','SHARED_PROMPTS_DIR','AGENT_PROMPTS_DIR','CONFIG_DIR','SCHEMAS_DIR','RECORDS_DIR'):
            setattr(paths,key,root/getattr(paths,key).relative_to(Path(__file__).resolve().parents[1]))
        from litreview import orchestrator
        with tempfile.TemporaryDirectory() as temp:
            orchestrator.RUNS_DIR=Path(temp)/'runs'
            shutil.copytree(root/'runs'/RUN,orchestrator.RUNS_DIR/RUN)
            apply(test_copy=True)
    elif not sys.argv[1:]:
        apply()
    else:
        raise SystemExit('unexpected arguments')
