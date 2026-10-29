"""Compare preserved baseline with optimized requests; optional FREE prefix calibration."""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from litreview import config
from litreview.agents.base import build_system_prompt

OUT=ROOT/'docs/a07_efficiency'
if '--count-prefix' in sys.argv:
    import os
    import anthropic
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    client=anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'),timeout=45,max_retries=0)
    m=config.agent_model('A07-SYN')
    params={'model':m.model,'messages':[{'role':'user','content':'Calibration'}],
            'output_config':{'effort':m.effort}}
    without=client.messages.count_tokens(**params).input_tokens
    with_system=client.messages.count_tokens(**params,system=build_system_prompt('A07-SYN')).input_tokens
    (OUT/'prefix_count.json').write_text(json.dumps({'without_system':without,'with_system':with_system,
        'system_prefix_delta':with_system-without,'method':'free input-count difference; estimated cacheable prefix, not cache usage'},indent=2)+'\n')


def requests(directory):
    with gzip.open(directory/'requests.jsonl.gz','rt',encoding='utf-8') as f:
        return [json.loads(line) for line in f]


def payload(x):
    return json.loads(x['params']['messages'][0]['content'][0]['text'])


def scientific_content(reqs,n):
    findings,contexts,entities,sources={},{},{},{}
    for x in reqs:
        if x['papers']!=n or x['mode']!='GROUP':continue
        p=payload(x)
        findings.update({f['finding_id']:f for f in p['findings']})
        contexts.update(p['contexts']);entities.update(p['source_entity_attributes'])
        for iid,unit in p['source_items'].items():
            item={k:v for k,v in unit['item'].items() if k!='original_item_id'}
            source=unit.get('source',unit['item'])
            if item['kind']=='SYSTEM_GAP':source={k:v for k,v in source.items() if k!='original_item_id'}
            assert iid not in sources, 'duplicate mandatory owner'
            sources[iid]={'item':item,'source':source}
    return {'findings':findings,'contexts':contexts,'entities':entities,'sources':sources}


old_dir=ROOT/'docs/a07_validation'
before=json.loads((old_dir/'measurements.json').read_text())
after=json.loads((OUT/'measurements.json').read_text())
old_requests,new_requests=requests(old_dir),requests(OUT)
prefix=json.loads((OUT/'prefix_count.json').read_text())['system_prefix_delta'] if (OUT/'prefix_count.json').exists() else None
rates=config.load('prices')[after['model']]


def metrics(d,reqs,n):
    row=next(r for r in d['rows'] if r['papers']==n)
    counts=[c for c in d['counts'] if c['papers']==n]
    assert all('input_tokens' in c for c in counts), 'Incomplete free counts'
    input_total=sum(c['input_tokens'] for c in counts)
    caps=sum(c['output_allowance'] for c in counts)
    raw=sum(c['fixture_output_byte_bound'] for c in counts)
    by_mode={}
    for mode in row['calls']:
        c=[x for x in counts if x['mode']==mode]
        by_mode[mode]={'calls':len(c),'input':sum(x['input_tokens'] for x in c),
            'output_cap':sum(x['output_allowance'] for x in c),'max_input':max(x['input_tokens'] for x in c),
            'max_input_plus_output':max(x['input_tokens']+x['output_allowance'] for x in c),
            'max_byte_input_plus_output':max(x['byte_input_bound']+x['output_allowance'] for x in c)}
    nc=len(counts)
    group_counts=[c for c in counts if c['mode']=='GROUP']
    gc={c['turn'].split('_LOOKUP')[0].removeprefix('GROUP_'):c for c in group_counts}
    groups=[{**g,'input_tokens':gc[g['id']]['input_tokens'],'output_cap':gc[g['id']]['output_allowance']} for g in row['groups']]
    cost=lambda out:(input_total*rates['input']+out*rates['output'])/1e6
    return {'papers':n,'calls':nc,'by_mode':by_mode,'input':input_total,'output_cap':caps,
        'status':row['status'],'pending':len(row['pending']),'unaccounted':len(row['unaccounted']),
        'empty_groups':sum(g['findings']==0 for g in groups),'groups':groups,
        'group_distribution':{'findings':dict(Counter(g['findings'] for g in groups)),
            'items':dict(Counter(g['items'] for g in groups)),
            'input_min':min(c['input_tokens'] for c in group_counts),
            'input_median':median(c['input_tokens'] for c in group_counts),'input_max':max(c['input_tokens'] for c in group_counts)},
        'costs':{'input_only':cost(0),'25pct_cap':cost(caps*.25),'50pct_cap':cost(caps*.5),
            'full_caps':cost(caps),'fixture_bytes_div3_plus_25pct_cap':cost(raw/3+caps*.25),
            'full_caps_40pct_proportional_retry_retrieval':cost(caps)*1.4,
            'all_input_as_cache_write_full_caps':(input_total*rates['cache_write_1h']+caps*rates['output'])/1e6,
            'all_system_miss_input_premium':None if prefix is None else nc*prefix*(rates['cache_write_1h']-rates['input'])/1e6,
            'ideal_system_cache_input_saving':None if prefix is None else
                (nc*prefix*rates['input']-prefix*rates['cache_write_1h']-(nc-1)*prefix*rates['cached_input'])/1e6},
        'all_admitted':all(c['input_tokens']+c['output_allowance']<=900000 for c in counts)}


rows=[]
for n in (40,80,120):
    a,b=metrics(before,old_requests,n),metrics(after,new_requests,n)
    old_science,new_science=scientific_content(old_requests,n),scientific_content(new_requests,n)
    assert old_science==new_science, 'Source or detailed evidence changed'
    old_plan=next(payload(x) for x in old_requests if x['papers']==n and x['mode']=='PLAN')
    new_plan=next(payload(x) for x in new_requests if x['papers']==n and x['mode']=='PLAN')
    for key in ('evidence_index','context_index','theme_framework'):
        assert old_plan[key]==new_plan[key],key
    rows.append({'papers':n,'before':a,'after':b,'scientific_input_equivalent':True,
                 'mandatory_units':len(new_science['sources']),'findings':len(new_science['findings'])})

# Root causes: classify the OLD finding-empty packets, not the optimized replacement.
empty_units=[]
for x in old_requests:
    if x['papers']==120 and x['mode']=='GROUP':
        p=payload(x)
        if not p['group']['finding_ids']:empty_units.extend(p['source_items'].values())
other=json.loads((old_dir/'summary.json').read_text())['other_pipeline_cost_scenario']
result={'method':'free provider-counted input; mocked output; same scientific corpus, no historical mutation',
    'baseline_unique_count_requests':before['captured_requests'],
    'optimized_unique_count_requests':after['captured_requests'],
    'prefix_calibration':None if prefix is None else prefix,
    'old_empty_item_kinds':dict(Counter(u['item']['kind'] for u in empty_units)),
    'other_stage_scenario':other,'rows':rows}
(OUT/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
for r in rows:
    print(json.dumps({'papers':r['papers'],'before_calls':r['before']['calls'],
        'after_calls':r['after']['calls'],'after_input':r['after']['input'],
        'after_costs':r['after']['costs'],'after_by_mode':r['after']['by_mode'],
        'group_distribution':r['after']['group_distribution']}))
