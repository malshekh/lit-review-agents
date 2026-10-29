"""Reproducible A07 audit: mocked generation and FREE token counting only.

Never calls messages.create/stream. Existing run artifacts are read-only.
"""
import concurrent.futures
import hashlib
import gzip
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from dotenv import load_dotenv
from a07_capacity_simulation import workload, simulate
from test_synthesis_bounded import FixtureModel
from litreview import config
from litreview.agents.base import build_system_prompt, user_parts
from litreview.llm.anthropic_client import request_body, message_params, count_tokens
from litreview.synthesis_registry import EvidenceRegistry, offline_tokens, canonical
from litreview.synthesis_bounded import RegistrySynthesisJob


def main():
    load_dotenv(ROOT / '.env')
    # Bounded free-counter network waits; no generation endpoint is used.
    import anthropic
    import os
    from litreview.llm import anthropic_client
    anthropic_client._client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=45, max_retries=0)
    settings = config.load('pipeline')['synthesis']
    model = config.agent_model('A07-SYN')
    system = build_system_prompt('A07-SYN')
    outdir = ROOT / 'docs/a07_validation'
    if '--retrieval' in sys.argv:
        outdir = outdir / 'retrieval'
    outdir.mkdir(exist_ok=True, parents=True)
    captures = []
    rows = []
    if '--recount' in sys.argv:
        with gzip.open(outdir/'requests.jsonl.gz','rt',encoding='utf-8') as source:
            captures=[json.loads(line) for line in source]
        rows=json.loads((outdir/'measurements.json').read_text(encoding='utf-8'))['rows']
    with tempfile.TemporaryDirectory(prefix='a07-validation-') as temp:
        for n in (() if captures else ((4,) if '--retrieval' in sys.argv else (40, 80, 120))):
            from test_a07_validation_audit import adversarial
            from test_synthesis_bounded import header
            r = EvidenceRegistry(adversarial() if '--retrieval' in sys.argv else workload(n))
            fixture = FixtureModel(r)
            def call(mode, payload, turn):
                cap = settings['output_limits'][mode]
                response = fixture(mode, payload, turn)
                if '--retrieval' in sys.argv and mode in ('GROUP','RECONCILE'):
                    if turn.endswith(('LOOKUP0','LOOKUP1')):
                        response={**header(mode),'status':'NEEDS_EVIDENCE',
                            'retrieval_requests':[{'finding_ids':['R0001:F1'] if turn.endswith('LOOKUP0') else ['R0002:F1']}],
                            **({'reviews':[],'issues':[]} if mode=='RECONCILE' else
                               {'propositions':[],'knowledge_gaps':[],'findings_not_used':[]})}
                    elif mode=='RECONCILE':
                        pids=[p['proposition_id'] for p in payload['global_proposition_index'][:2]]
                        response['issues']=[{'kind':'SHARED_EVIDENCE','proposition_ids':pids,
                            'finding_ids':['R0001:F1','R0002:F1'],'limitation':'Supplied shared-study relationship; preservation only'}]
                        for review in response['reviews']:
                            if review['proposition_id'] in pids:review['outcome']='ISSUES_IDENTIFIED'
                params = message_params(system, user_parts(payload), model.model, cap,
                    model.temperature, model.effort, True, settings['cache_ttl'])
                captures.append({'papers': n, 'mode': mode, 'turn': turn, 'params': params,
                    'byte_input_bound': offline_tokens(system)+offline_tokens(user_parts(payload)),
                    'fixture_output_byte_bound': offline_tokens(response),
                    'group': payload.get('group')})
                return response
            job = RegistrySynthesisJob(Path(temp)/str(n), r, call,
                lambda p: offline_tokens(system)+offline_tokens(user_parts(p)), settings,
                {'prompt': system}, lambda *_: True)
            pkg = job.run()
            packets = job.packets
            selected = set(r.records)
            outside = sorted(set(__import__('re').findall(r'\bR\d{4}\b', canonical(r.corpus['theme_records']))) - selected)
            rows.append({'papers': n, 'findings': len(r.findings), 'mandatory_items': len(r.items),
                'status':pkg['status'], 'pending':pkg['coverage_incomplete_item_ids'],
                'unaccounted':pkg['findings_unaccounted'], 'calls':dict(Counter(x['mode'] for x in captures if x['papers']==n)),
                'groups': [{'id':p['group_id'],'theme':p['primary_theme_id'],
                    'findings':len(p['finding_ids']),'items':len(p['manifest_item_ids'])} for p in packets],
                'theme_record_references_outside_selected':outside,
                'previous_cost_reproduction': None if '--retrieval' in sys.argv else simulate(n, Path(temp)/f'cost{n}')})
    # Persist exact requests locally for reproducibility, never responses from a paid model.
    with gzip.open(outdir/'requests.jsonl.gz','wt',encoding='utf-8') as target:
        for x in captures:target.write(json.dumps(x,ensure_ascii=False)+'\n')
    def count_one(x):
        try:
            params=x['params']
            count_params={k:v for k,v in params.items() if k in
                ('model','messages','system','tools','tool_choice','thinking','output_config')}
            tokens=anthropic_client._client.messages.count_tokens(**count_params).input_tokens
            return {'papers':x['papers'],'turn':x['turn'],'mode':x['mode'],
                'input_tokens':tokens,'output_allowance':params['max_tokens'],
                'byte_input_bound':x['byte_input_bound'],
                'fixture_output_byte_bound':x['fixture_output_byte_bound'],
                'request_sha256':hashlib.sha256(canonical(params).encode()).hexdigest()}
        except Exception as exc:
            # Do not serialize credentials, headers or request content in exception messages.
            return {'papers':x['papers'],'turn':x['turn'],'mode':x['mode'],
                    'error_type':type(exc).__name__, 'error_status':getattr(exc,'status_code',None)}
    # Probe first; avoid hundreds of identical authorization/model/network failures.
    first=count_one(captures[0])
    counts=[first]
    if 'input_tokens' in first:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(count_one,captures[1:]):
                counts.append(result)
                if len(counts)%25==0: print(f'Counted {len(counts)}/{len(captures)}',flush=True)
    else:
        print('Free token-count probe failed: '+json.dumps(first),flush=True)
    result={'model':model.model,'method':'mocked generation; exact production message_params; free input token counts only',
        'system_byte_bound':offline_tokens(system),'rows':rows,'counts':counts,
        'captured_requests':len(captures),'counted_requests':sum('input_tokens' in c for c in counts)}
    (outdir/'measurements.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'captured':len(captures),'counted':result['counted_requests'], 'model':model.model}),flush=True)


if __name__=='__main__':main()
