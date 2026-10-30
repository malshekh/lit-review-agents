"""Read-only telemetry/scenario arithmetic. No provider requests."""
import collections
import json
import re
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from litreview import config
from litreview.budget import BudgetTracker
from litreview.tools.cost_projection import downstream

out=ROOT/'docs/integrated_validation'
d=json.loads((out/'a10/measurements.json').read_text())
entries=[json.loads(x) for x in (ROOT/'runs/20261025-100039/costs.jsonl').read_text().splitlines()]
hist=collections.defaultdict(lambda:{'calls':0,'billed_usd':0})
for e in entries:
    hist[e['agent']]['calls']+=1
    hist[e['agent']]['billed_usd']+=e.get('cost_usd') or 0
paper={a:sum(e['cost_usd'] or 0 for e in entries if re.fullmatch(pattern,e['step']))/28*120/2
       for a,pattern in [('A05-KE',r'A05-KE_R\d+(_reextract)?'),('A06-SV',r'A06-SV_R\d+_v\d+')]}
legacy=json.loads((ROOT/'docs/a07_validation/summary.json').read_text())['other_pipeline_cost_scenario']
base={'A02-SP':.740857,'A03-LM':.957916,'A04-CQ':.36800675,
      'pre_CP2_growth_reserve':4-.740857-.957916-.36800675,
      'A05-KE_batch':paper['A05-KE'],'A06-SV_initial_batch':paper['A06-SV'],
      'A06-SV_repeat_batch_all_papers':legacy['repeat_A06_batch_p90_all_papers'],
      'A06-SV_themes':legacy['thematic_validation']}
for r in legacy['A08_A12']:
    if r['stage']!='A10-RV':base[r['stage']]=r['usd']
def a10(phase):
    r=d[phase];i=r['input_upper_tokens'];o=r['output_allowance']
    return {'input_byte_bound':i,'output_cap':o,'modeled_3bytes_output25pct':i/3*2/1e6+o*.25*10/1e6,
            'modeled_3bytes_output50pct':i/3*2/1e6+o*.5*10/1e6,
            'all_input_bytes_write_full_output':i*2.5/1e6+o*10/1e6}
first,edit=a10('first'),a10('one_edit')
other=sum(base.values())
band=[other+a+first['modeled_3bytes_output25pct']+edit['modeled_3bytes_output25pct'] for a in (30.32,39.12)]
conservative=4+2*paper['A05-KE']+2*paper['A06-SV']+2*legacy['repeat_A06_batch_p90_all_papers']+279*.0926
conservative+=78.24+first['all_input_bytes_write_full_output']+5*edit['all_input_bytes_write_full_output']
conservative+=sum(r['usd'] for r in legacy['A08_A12'] if r['stage']!='A10-RV')
with tempfile.TemporaryDirectory(prefix='integrated-cost-') as t:
    budget=BudgetTracker(Path(t))
    planning=downstream(budget,config.agent_model,config.load('pipeline'),1996)
result={'historical_billed_telemetry_not_a_new_run':dict(hist),
        'historical_total_spent':sum(e['cost_usd'] or 0 for e in entries),
        'historical_reservations_file_present':(ROOT/'runs/20261025-100039/reservations.json').exists(),
        'baseline_other_stages':base,'other_total':other,'A10_first':first,'A10_small_edit':edit,
        'compact_handoff_baseline_total_band':band,'margin_under_150':[150-x for x in band],
        'A07_remaining_allowance':150-other-first['modeled_3bytes_output25pct']-edit['modeled_3bytes_output25pct'],
        'first_plus_five_small_edits_band':[other+a+first['modeled_3bytes_output25pct']+5*edit['modeled_3bytes_output25pct'] for a in (30.32,39.12)],
        'finite_adverse_no_batch_full_A07_and_A10_write_caps_six_versions':conservative,
        'runtime_downstream_projection':planning,
        'caveats':['No new-run commitments; add spent and outstanding reservations for the actual chosen run.',
          'Historical A05/A06 costs include observed attempts; batch halves them only if eligible and completed; probes remain interactive.',
          'A08/A09/A11/A12 baseline figures are inherited projections, not measured live 120-paper costs; expansive handoff overflow is separately demonstrated.',
          'Reasoning included in modeled output fraction and cap; no extra overlapping thinking allowance.',
          'No cache hits assumed; adverse is finite scenario, not a bound on unlimited retries/fallbacks.']}
(out/'costs.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
