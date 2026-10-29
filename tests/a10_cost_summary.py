"""Scenario arithmetic from saved exact requests. No API calls."""
import gzip
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'docs/a10_capacity'
d=json.loads((p/'measurements.json').read_text())
with gzip.open(p/'requests.jsonl.gz','rt',encoding='utf-8') as f:requests=[json.loads(line) for line in f]
def scenario(key):
    r=d[key];inp=r['input_upper_tokens'];out=r['output_allowance']
    relevant=[x for x in requests if x['phase']==('first' if key=='first' else 'one_edit')]
    global_requests=[x for x in relevant if x['mode']=='GLOBAL']
    stable=os.path.commonprefix([x['params']['messages'][1]['content'] for x in global_requests])
    prefix=len((global_requests[0]['params']['messages'][0]['content']+stable).encode())
    # Three bytes/token is an explicit scenario assumption, not an observed GPT token count.
    prefix_tokens=prefix/3
    n=len(global_requests)
    cache_saving=(n*prefix_tokens*2-prefix_tokens*2.5-(n-1)*prefix_tokens*.1)/1e6
    def cost(fraction):return (inp/3*2+out*fraction*10)/1e6
    return {'uncached_output25pct':cost(.25),'uncached_output50pct':cost(.5),
        'input2to4bytes_output25to50pct_sensitivity':[(inp/4*2+out*.25*10)/1e6,(inp/2*2+out*.5*10)/1e6],
        'global_prefix_bytes':prefix,'global_prefix_ideal_cache_saving':cache_saving,
        'ideal_cache_output25pct':cost(.25)-cache_saving,
        'every_input_byte_cache_write_full_output':(inp*2.5+out*10)/1e6,
        'finite_30pct_retrieval_10pct_retry_output50pct':cost(.5)*1.4,
        'caveat':'3 bytes/token; generated output fractions include reasoning; cache model assumes one write then hits; not billed measurements'}
first,edit=scenario('first'),scenario('one_edit')
old_other=json.loads((ROOT/'docs/a07_validation/summary.json').read_text())['other_pipeline_cost_scenario']['total']
other=old_other-25.5552
result={'first':first,'one_edit':edit,'other_stages_excluding_A07_A10':other,
    'pipeline_two_full25pct_A07_30_39':[other+2*first['uncached_output25pct']+a for a in (30,39)],
    'pipeline_first_plus_edit25pct_A07_30_39':[other+first['uncached_output25pct']+edit['uncached_output25pct']+a for a in (30,39)],
    'pipeline_first_plus_five_edits25pct_A07_30_39':[other+first['uncached_output25pct']+5*edit['uncached_output25pct']+a for a in (30,39)]}
(p/'cost_scenarios.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
