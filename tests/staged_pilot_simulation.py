"""Offline historical replay of the pinned pilot through production A07 builders.
No generation, no key approval, no repository/historical writes; diagnostics go to a fresh temporary directory.
Run: python -B tests/staged_pilot_simulation.py
A02-A06 are priced from historical calibration, not executed or scientifically re-evaluated.
"""
import sys,json,tempfile,collections,copy
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root/'src'),str(root/'tests')]
from litreview import config,orchestrator,pilot_authorization as pa
from litreview.synthesis_registry import EvidenceRegistry,offline_tokens,canonical
from litreview.synthesis_bounded import RegistrySynthesisJob
from litreview.agents.base import build_system_prompt,user_parts
from test_synthesis_bounded import FixtureModel
import pilot_scale_measure as pm
import a07_capacity_simulation as sim
path=Path(tempfile.mkdtemp(prefix='task5-offline-'));sim.ROOT=pm.staged(path,['R0030','R0159','R0040']);reg=EvidenceRegistry(sim.workload(3));model=FixtureModel(reg)
system=build_system_prompt('A07-SYN');count=lambda p:offline_tokens(system)+offline_tokens(user_parts(p));cfg=config.load('pipeline')
job=RegistrySynthesisJob(path/'a07',reg,model,count,cfg['synthesis'],{'evaluation':'Task5 offline historical replay, not a scientific pilot'},lambda *_:True);pkg=job.run()
measure=collections.defaultdict(lambda:{'calls':0,'byte_input_bound':0,'output_allowance':0})
for mode,p,name in model.calls:
 row=measure[mode];row['calls']+=1;row['byte_input_bound']+=count(p);row['output_allowance']+=job.limit(mode)
(path/'requests.json').write_text(json.dumps([{'mode':m,'name':n,'payload':p} for m,p,n in model.calls],ensure_ascii=False),encoding='utf-8')
orchestrator.RUNS_DIR=path/'financial-runs';r=orchestrator.Run('offline-finance');r.save_state({'stage':'scope','status':'READY','counters':{},'execution_mode':'STAGED_PILOT'})
runtime=pa.project(r,pa.STAGE_1)
prices=r.budget._rates(r.route('A07-SYN').model,0);s=cfg['forecast']['scenarios']['baseline'];a07=0;calls=0
for mode,row in measure.items():
 w=1+s['a07_retrieval'] if mode in ['GROUP','RECONCILE'] else 1
 a07+=(row['byte_input_bound']/s['bytes_per_token']*w+(row['calls']*s['a07_retrieval']*15600 if w>1 else 0))*prices['input']/1e6+row['output_allowance']*.5*w*prices['output']/1e6;calls+=row['calls']*w
cache=calls*5800*(prices['cache_write_1h']-prices['input'])/1e6
base_lines=[x for x in runtime['lines'] if not x['stage'].startswith('A07')];base=sum(x['usd'] for x in base_lines)+a07+cache
res={'notice':'OFFLINE STRUCTURAL EVALUATION ONLY. Historical accepted evidence and scripted responses; not new scientific extraction or synthesis.',
 'temporary_directory':str(path),'historical_records':['R0030','R0159','R0040'],'papers':pa.PAPERS,
 'findings':len(reg.findings),'mandatory_items':len(reg.items),'legacy_theme_records':len(reg.corpus['theme_records']),
 'status':pkg['status'],'all_admitted':all(count(p)+job.limit(m)<=cfg['synthesis']['context_ceiling_tokens'] for m,p,n in model.calls),
 'a07':dict(measure),'a07_cost_modeled_input_bytes_div_2_1':a07,'system_cache_miss_premium':cache,
 'runtime_initial_projection':runtime,'production_builder_projection':{'lines_before_a07':base_lines,'baseline_including_5pct_retry':base*1.05,'admission_with_30pct_future_margin':base*1.05*1.3},
 'generation_calls':0,'actual_pilot_key_approved':False,'limitations':['No fresh A02-A06 generation; their costs use saved calibration and explicit pre-CP2 allowance.','A07 retains legacy thematic obligations; not a researcher-approved new three-paper thematic framework.','GPT/Claude tokens here modeled from byte bounds, not fresh provider counts.','Human key metadata and stage authorizations are not created for any real run.']}
(path/'summary.json').write_text(json.dumps(res,indent=2),encoding='utf-8');print(json.dumps(res,indent=2))
