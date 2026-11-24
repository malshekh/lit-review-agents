"""Sealed operational launcher. Execute through bootstrap.py under the current non-admin account.

No checkpoint approvals, model substitution, or limit changes are implemented here.
"""
from pathlib import Path
import argparse, json, os, sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    from litreview import structured, model_record, config, orchestrator, preflight
    from litreview.runtime_integrity import verify, sha
    ap=argparse.ArgumentParser(); ap.add_argument('action',choices=['availability','audit','schema-preflight','smoke','functional','scope']); ap.add_argument('run_id')
    args=ap.parse_args()
    manifest=json.loads((ROOT/'frozen_runtime_manifest.json').read_text(encoding='utf-8'))
    verify(ROOT,manifest)
    run=orchestrator.Run(args.run_id)
    from litreview.runtime_identity import require_execution_context
    security={"execution":require_execution_context(),
              "keys":{name:bool(os.environ.get(name)) for name in ['ANTHROPIC_API_KEY','OPENAI_API_KEY','MOONSHOT_API_KEY']}}
    (run.dir/'input/execution_context.json').write_text(json.dumps(security,indent=2),encoding='utf-8')
    pin=json.loads((run.dir/'input/runtime_pin.json').read_text(encoding='utf-8'))
    assert pin['manifest_sha256']==sha(ROOT/'frozen_runtime_manifest.json')
    assert run.state()['profile']=='pilot7' and run.budget.cap==50
    assert run.budget.review_points==[25,48] and not config.load('pipeline')['routing']['alternates']
    preflight.require_clean_endpoints()
    # Provider credentials are process environment only. No .env or secret value is read or serialized.
    model_record.RECORD=run.dir/'model_record.jsonl'
    structured.RECORD=run.dir/'structured_output.json'
    from litreview.retained_hold import blocking_holds
    authorization=ROOT/'pilot_retained_hold_authorization.json'
    auth=json.loads(authorization.read_text(encoding='utf-8'))
    assert auth['run_id']==run.id and auth['total_cap_usd']==50 and auth['smoke_allowance_usd']==1
    if blocking_holds(run.budget,authorization):raise SystemExit('BLOCKED: an additional unresolved dispatch exists')
    if args.action=='audit':
        structured.recover_smoke_receipts(run.budget)
        amount,todo=structured.smoke_estimate(run.budget)
        print(json.dumps({'inventory':structured.schema_inventory(),'remaining_checks':len(todo),'worst_case_usd':amount,
             'spent_usd':run.budget.spent(),'held_usd':run.budget.reserved()},indent=2))
        return 0
    if args.action=='schema-preflight':
        import requests, hashlib
        folder=run.dir/'input/schema_preflight';folder.mkdir(exist_ok=True)
        pcfg=config.load('pipeline')['providers']['anthropic']
        assert pcfg['base_url'].rstrip('/')=='https://api.anthropic.com'
        headers={'x-api-key':os.environ[pcfg['key_env']],'anthropic-version':'2023-06-01'}
        def probe(label,model,shape):
            body={'model':model,'system':structured.SMOKE_SYSTEM,'messages':[{'role':'user','content':'Return the object now.'}],
                  'output_config':{'format':{'type':'json_schema','schema':shape}}}
            path=folder/(label+'.json')
            if path.exists():return json.loads(path.read_text())
            result={'label':label,'endpoint':'/v1/messages/count_tokens','model':model,
                    'schema_sha256':hashlib.sha256(json.dumps(shape,sort_keys=True).encode()).hexdigest(),
                    'inference_sent':False,'billed_usd':0,'billing_basis':'Official token-counting endpoint is free; no message generated.'}
            response=requests.post('https://api.anthropic.com/v1/messages/count_tokens',headers=headers,json=body,timeout=210)
            result.update(http_status=response.status_code,response=response.json(),request_id=response.headers.get('request-id'))
            path.write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result),flush=True)
            return result
        failed=json.loads((run.dir/'smoke_receipts/smoke-cf915e7cd207476399c034b44c539d2a.json').read_text())
        control=probe('known_rejected_a05',failed['model'],failed['submitted_schema'])
        reproduced=control['http_status']==400 and 'grammar' in json.dumps(control['response']).lower()
        results=[]
        for target in structured.targets():
            if target['provider']=='anthropic':results.append(probe(target['schema_file'],target['model'],target['schema']))
        report={'known_rejection_reproduced':reproduced,'compiler_validation_established':reproduced,
                'limitation':'A token-count success is not live smoke acceptance; if the negative control passes, compiler validation is not established.',
                'results':results}
        (folder/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'known_rejection_reproduced':reproduced,'statuses':[r['http_status'] for r in results]}))
        return 0 if all(r['http_status']==200 for r in results) else 2
    if args.action=='availability':
        import requests
        models={}
        for aid in config.load('pipeline')['agents']:
            m=config.agent_model(aid); models.setdefault(m.provider,set()).add(m.model)
        report=[]
        for provider,wanted in models.items():
            c=config.load('pipeline')['providers'][provider]
            key=os.environ.get(c['key_env'])
            if not key:
                report.append({'provider':provider,'status':'MISSING_SESSION_KEY','configured':sorted(wanted)}); continue
            headers={'x-api-key':key,'anthropic-version':'2023-06-01'} if provider=='anthropic' else {'Authorization':'Bearer '+key}
            url=c['base_url'].rstrip('/')+('/v1/models' if provider=='anthropic' else '/models')
            try:
                response=requests.get(url,headers=headers,timeout=30)
                listed={x['id'] for x in response.json().get('data',[])} if response.status_code==200 else set()
                report.append({'provider':provider,'http_status':response.status_code,'configured':sorted(wanted),
                               'available':sorted(wanted & listed),'missing':sorted(wanted-listed)})
            except Exception as exc:report.append({'provider':provider,'status':type(exc).__name__})
        (run.dir/'input/model_availability.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
        return 0 if all(r.get('http_status')==200 and not r.get('missing') for r in report) else 2
    availability=json.loads((run.dir/'input/model_availability.json').read_text(encoding='utf-8'))
    if not all(r.get('http_status')==200 and not r.get('missing') for r in availability):
        raise SystemExit('BLOCKED: configured model availability has not passed')
    if args.action in ('smoke','functional'):
        from litreview.check_authorization import require as require_check_authorization
        check_auth=require_check_authorization(run,ROOT)
    if args.action=='functional':
        from litreview import a05_functional
        result=a05_functional.execute(run,check_auth['functional_cap_usd'],check_auth['approved_by'],check_auth)
        print(json.dumps(result,indent=2))
        return 0
    if args.action=='smoke':
        structured.recover_smoke_receipts(run.budget)
        from litreview.a05_functional import smoke_spent as combined_smoke_spent
        smoke_spent=combined_smoke_spent(run.budget)
        remaining=1-smoke_spent
        assert remaining>=0
        # Exact additional authorization ceiling was installed above; do not widen it to unused smoke room.
        estimate,todo=structured.smoke_estimate(run.budget)
        assert len(todo)<=auth['approved_checks'] and estimate+run.budget.reserved()<=remaining
        if not any(t['schema_file']=='A06-SV.schema.json' and t['already_verified'] for t in structured.targets()):
            assert todo and todo[0]['schema_file']=='A06-SV.schema.json', 'A06 strict check must precede functional extraction'
        result=structured.smoke_test(run.budget,remaining,auth['authorized_by'],retained_hold_authorization=authorization)
        result['total_run_spend_usd']=run.budget.spent(); result['unsettled_usd']=run.budget.reserved()
        (run.dir/'smoke_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        return 0 if result['tested']==result['accepted'] and all(t['already_verified'] for t in structured.targets()) and not blocking_holds(run.budget,authorization) else 2
    from litreview import extraction_mode,a05_functional
    if extraction_mode.active() and not a05_functional.verified(run.dir):raise SystemExit('BLOCKED: A05 ordinary JSON nonempty functional check has not passed')
    smoke=json.loads((run.dir/'smoke_result.json').read_text(encoding='utf-8'))
    if smoke['tested']!=smoke['accepted'] or blocking_holds(run.budget,authorization) or not all(t['already_verified'] for t in structured.targets()):raise SystemExit('BLOCKED: smoke test failed or unsettled')
    if run.state()['stage'] not in ['scope','cp1']:raise SystemExit('BLOCKED: this launch stops at CP1; later continuation requires the researcher')
    if (run.dir/'checkpoints/CP1_approved.json').exists():
        raise SystemExit('BLOCKED: CP1 is already approved; this command is only for the initial CP1 handoff')
    result=run.run(until='search')  # writes CP1 review files and pauses; never enters paid discovery
    print(result)
    print(json.dumps({'run_id':run.id,'state':run.state(),'spent_usd':run.budget.spent(),'reserved_usd':run.budget.reserved()},indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
