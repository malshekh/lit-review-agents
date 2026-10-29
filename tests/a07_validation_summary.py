"""Summarize persisted audit measurements; no APIs."""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from litreview import config
from litreview.budget import BudgetTracker
from litreview.tools.cost_projection import downstream
from a07_capacity_simulation import workload
from litreview.synthesis_registry import EvidenceRegistry
import tempfile

d=json.loads((ROOT/'docs/a07_validation/measurements.json').read_text())
summary=[]
for r in d['rows']:
    c=[x for x in d['counts'] if x['papers']==r['papers'] and 'input_tokens' in x]
    groups=r['groups']
    by_mode={m:{'calls':sum(x['mode']==m for x in c),
        'input':sum(x['input_tokens'] for x in c if x['mode']==m),
        'max_input':max(x['input_tokens'] for x in c if x['mode']==m),
        'output_cap':sum(x['output_allowance'] for x in c if x['mode']==m)} for m in r['calls']}
    inp=sum(x['input_tokens'] for x in c)
    cap=sum(x['output_allowance'] for x in c)
    raw=sum(x['fixture_output_byte_bound'] for x in c)
    p=config.load('prices')[d['model']]
    def cost(output):return (inp*p['input']+output*p['output'])/1e6
    gc=[x['input_tokens'] for x in c if x['mode']=='GROUP']
    row={'papers':r['papers'],'by_mode':by_mode,'outside_selected':len(r['theme_record_references_outside_selected']),
        'groups':len(groups),'empty_groups':sum(g['findings']==0 for g in groups),
        'unmapped_groups':sum(g['theme']=='UNMAPPED' for g in groups),
        'findings_distribution':dict(Counter(g['findings'] for g in groups)),
        'items_distribution':dict(Counter(g['items'] for g in groups)),
        'group_input_distribution':{'min':min(gc),'median':statistics.median(gc),'max':max(gc),'total':sum(gc)},
        'costs':{'input_only':cost(0),'illustrative_fixture_bytes_div3_plus_25pct_cap':cost(raw/3+cap*.25),
            '25pct_output_cap':cost(cap*.25),'50pct_output_cap':cost(cap*.5),'100pct_output_cap':cost(cap),
            'all_input_1h_write_all_output_cap':(inp*p['cache_write_1h']+cap*p['output'])/1e6},
        'all_provider_counts_plus_cap_admitted':all(x['input_tokens']+x['output_allowance']<=900000 for x in c)}
    summary.append(row)
    # Exact group data: one row per GROUP call, including provider tokens.
    lookup={g['id']:g for g in groups}
    for x in c:
        if x['mode']=='GROUP':x['group']=lookup[x['turn'].split('_LOOKUP')[0].removeprefix('GROUP_')]
    (ROOT/f'docs/a07_validation/groups_{r["papers"]}.json').write_text(json.dumps([x for x in c if x['mode']=='GROUP'],indent=2)+'\n')

with tempfile.TemporaryDirectory() as temp:
    lines=downstream(BudgetTracker(Path(temp)),config.agent_model,config.load('pipeline'),1996)[1:]
rates=json.loads((ROOT/'records/cost_rates.json').read_text())
mix=11/28
paper=120*((1-mix)*rates['per_paper']['ABSTRACT']['mean_usd']+mix*rates['per_paper']['FULL_TEXT']['mean_usd'])/2
repeat=120*((1-mix)*rates['per_paper']['ABSTRACT']['a06_p90_usd']+mix*rates['per_paper']['FULL_TEXT']['a06_p90_usd'])/2
themes=120*rates['themes_per_paper']*rates['per_theme']['mean_usd']
other={'discovery_assumption':4,'A05_A06_batch_mean':paper,'repeat_A06_batch_p90_all_papers':repeat,
    'thematic_validation':themes,'A08_A12':lines}
other['total']=4+paper+repeat+themes+sum(x['usd'] for x in lines)
other['a07_allowance_under_150']=150-other['total']
# Quantify avoidable overflow without changing production grouping.
r=EvidenceRegistry(workload(120)); packets=r.packets(); misses=[]
for packet in packets:
    if packet['primary_theme_id']!='UNMAPPED':continue
    for iid in packet['manifest_item_ids']:
        anchors=r.item_findings(iid)
        alternatives=[p for p in packets if p['primary_theme_id']!='UNMAPPED'
            and anchors & set(p['finding_ids']) and len(p['manifest_item_ids'])<8]
        if alternatives:misses.append(iid)
result={'capacity':summary,'other_pipeline_cost_scenario':other,
    'overflow_items_with_existing_nonfull_anchor_packet':len(misses)}
(ROOT/'docs/a07_validation/summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
