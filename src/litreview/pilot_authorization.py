"""Stage-scoped pilot finance. Metadata only; the human key never becomes an agent input.

Legacy runs retain their recorded execution mode. New runs default to the staged pilot.
Financial approval does not replace any scientific checkpoint.
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
from . import config, checkpoints
from .paths import REPO_ROOT
from .synthesis_registry import fingerprint
from .tools import cost_projection as cp
from .tools import forecast

STAGE_1 = 'STAGE_1_AUTHORIZED'
STAGE_2 = 'FULL_PIPELINE_AUTHORIZED'
FIRST = frozenset(('A02-SP','A03-LM','A04-CQ','A05-KE','A06-SV','A07-SYN'))
SECOND = frozenset(('A08-OL','A09-WRI','A10-RV','A11-RC','A12-EDI'))
PAPERS = [{'pmid':'34638842','content_level':'FULL_TEXT'},
          {'pmid':'27006494','content_level':'ABSTRACT'},
          {'pmid':'30771200','content_level':'ABSTRACT'}]

class AuthorizationRequired(ValueError): pass

def enabled(run):
    if not (run.dir/'state.json').exists():return False  # legacy unit harnesses; Run.run itself requires a state
    return run.state().get('execution_mode') == 'STAGED_PILOT'

def atomic(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp,path)

def journal(run):
    import copy
    result=copy.deepcopy(config.load('journal_scirev'))
    if enabled(run): result['limits']['main_text_max_words']=1500
    return result

def key_metadata(run):
    m=run.load('pilot_reference_approval.json') or {}
    needed=('version','sha256','commit','verified_by','approved_at','store_path')
    if m.get('human_verified') is not True or not all(isinstance(m.get(k),str) and m[k].strip() for k in needed):
        raise AuthorizationRequired('Missing approved human reference-key version/fingerprint and verification record')
    path=Path(m['store_path']).resolve()
    # This path is read only for a binary hash, never by payload/retrieval construction.
    if path.is_relative_to(REPO_ROOT.parent.resolve()) or path.is_relative_to(run.dir.resolve()):
        raise AuthorizationRequired('Reference key must be outside the repository and run retrieval paths')
    if len(m['sha256'])!=64 or any(c not in '0123456789abcdef' for c in m['sha256']):
        raise AuthorizationRequired('Invalid reference-key SHA-256')
    try: actual=hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc: raise AuthorizationRequired('Approved external reference key unavailable') from exc
    if actual != m['sha256']: raise AuthorizationRequired('Approved reference key changed; version and affected evaluations must be renewed')
    return {k:m[k] for k in (*needed,'human_verified')}

def record_key(run, metadata):
    allowed={'version','sha256','commit','verified_by','approved_at','store_path','human_verified'}
    if set(metadata)-allowed: raise AuthorizationRequired('Reference approval accepts metadata only, never key contents')
    # Validate before persisting. No assertion of scientific verification is made by this code.
    old=run.load('pilot_reference_approval.json')
    atomic(run.data('pilot_reference_approval.json'),metadata)
    try: key_metadata(run)
    except Exception:
        if old is None: run.data('pilot_reference_approval.json').unlink()
        else: atomic(run.data('pilot_reference_approval.json'),old)
        raise
    run.prov.human_decision('PILOT_REFERENCE_METADATA', {k:v for k,v in metadata.items() if k!='store_path'}, 'Human attestation; no scientific verification by software')

def selection(run, records=None):
    records=run.load('selected_corpus.json') if records is None else records
    if records is not None:
        got=sorted((str(r.get('pmid')),cp.content_level(r,run.dir)) for r in records)
        want=sorted((p['pmid'],p['content_level']) for p in PAPERS)
        if got!=want: raise AuthorizationRequired('Selected papers/source types differ from the authorized three-paper pilot')
        return records
    return [{'record_id':'PILOT'+p['pmid'],'pmid':p['pmid'],**({'pmcid':'PMC8508702'} if p['content_level']=='FULL_TEXT' else {})} for p in PAPERS]

def scientific_ready(run):
    from .scientific_validation import require_package
    from .synthesis_registry import fingerprint as fp
    decision=checkpoints.approved(run.dir,'CP3')
    pkg=run.load('synthesis_approved.json')
    raw=run.load('synthesis_package.json')
    if not decision or not pkg or not raw or decision.get('synthesis_fingerprint')!=fp(raw):
        raise AuthorizationRequired('Stage 2 requires current CP3 scientific approval and approved synthesis')
    if pkg.get('status')!='COMPLETE' or pkg.get('findings_unaccounted') or pkg.get('coverage_incomplete_item_ids'):
        raise AuthorizationRequired('Stage 1 evidence accounting incomplete')
    # Reuse the existing scientific/provenance/eligibility boundary, not a financial substitute.
    run._bridge_inputs()
    require_package(pkg,run._findings() or [])
    return pkg

def _files_digest(paths):
    return {str(p.relative_to(REPO_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}

def identity(run,stage):
    sources=[p for folder in ('src','prompts','schemas','config') for p in sorted((REPO_ROOT/folder).rglob('*'))
             if p.is_file() and p.suffix in ('.py','.md','.json','.yaml')]
    upstream=('spec_approved.json','theme_framework.json','selected_corpus.json','validated_findings.json','theme_records.json')
    if stage==STAGE_2: upstream+=('synthesis_package.json','synthesis_approved.json','manuscript_plan.json','allocation_ledger.json')
    return {'run_id':run.id,'stage':stage,'papers':selection(run),'reference':key_metadata(run),
            'config':json.loads(json.dumps(run.cfg)),'prices':run.budget.prices,'versions':_files_digest(sources),
            'routes':{a:dataclasses.asdict(run.route(a)) for a in sorted(FIRST if stage==STAGE_1 else SECOND)},
            'input':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((run.dir/'input').glob('*')) if p.is_file()},
            'upstream':{name:fingerprint(run.load(name)) for name in upstream},
            'evidence':{str(p.relative_to(run.dir)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for folder in ('fulltext','extractions','validations') for p in sorted((run.dir/'data'/folder).glob('*.json'))},
            'plan':run.load('pilot_financial_plan.json'),'calibration':cp.load_rates()}

def work_basis(run):
    """Only reusable work on the current scientific plan receives a forecast credit."""
    versions=[p for folder in ('src','prompts','schemas','config') for p in sorted((REPO_ROOT/folder).rglob('*'))
              if p.is_file() and p.suffix in ('.py','.md','.json','.yaml')]
    return fingerprint({'evidence':[run.load(n) for n in ('synthesis_approved.json','validated_findings.json','manuscript_plan.json','allocation_ledger.json')],
                        'configuration':json.loads(json.dumps(run.cfg)),'prices':run.budget.prices,'versions':_files_digest(versions)})


def completed_credit(run,agent):
    total=0.0
    logged={e['step'] for e in run.budget.entries()};basis=work_basis(run)
    for step,receipt in run.load('pilot_requests.json',{}).items():
        if receipt.get('agent')!=agent or receipt.get('projection_basis')!=basis or step not in logged:continue
        path=run.dir/'outputs'/f'{step}.json'
        if not path.exists():continue
        obj=json.loads(path.read_text(encoding='utf-8'))
        if fingerprint(obj)!=receipt.get('output_hash'):raise AuthorizationRequired('Accepted output changed; no forecast credit allowed')
        credit=float(receipt.get('forecast_usd',0))
        if not math.isfinite(credit) or credit<0:raise AuthorizationRequired('Invalid completed-work forecast credit')
        total+=credit
    return total


def stage_for(run,agent):
    if agent in FIRST: return STAGE_1
    if agent in SECOND: return STAGE_2
    raise AuthorizationRequired('Agent is outside pilot authorization scope')

def admit(spent,commitments,future,cap=35.0):
    from decimal import Decimal
    values=[Decimal(str(x)) for x in (spent,commitments,future,cap)]
    if any(not x.is_finite() or x<0 for x in values): raise AuthorizationRequired('Invalid financial amount')
    total=values[0]+values[1]+Decimal('1.30')*values[2]
    return {'spent_usd':float(values[0]),'committed_usd':float(values[1]),'uncommitted_future_usd':float(values[2]),
            'projected_total_usd':float(total),'cap_usd':float(values[3]),'verdict':'WITHIN_CAP' if total<=values[3] else 'OVER_CAP'}

def project(run,stage,records=None,in_flight=frozenset(),candidate=None):
    """Remaining forecast: no contingency on already spent/reserved work. Unknown commitments fail closed."""
    from .orchestrator import STAGES
    if run.budget.cap!=35 or run.cfg['run'].get('spend_review_usd')!=25:
        raise AuthorizationRequired('Pilot requires unchanged $35 cap and $25 spending-review checkpoint')
    if float(run.cfg['forecast']['uncertainty_margin'])!=.30: raise AuthorizationRequired('Pilot requires 30% future-work admission margin')
    records=selection(run,records);at=STAGES.index(run.state()['stage']); lines=[]
    if stage==STAGE_1:
        if at>STAGES.index('cp3'): raise AuthorizationRequired('Stage 1 cannot authorize manuscript stages')
        rates=cp.load_rates()
        pre=sum(e['cost_usd'] or 0 for e in run.budget.entries() if e['agent'] in {'A02-SP','A03-LM','A04-CQ'})
        if at<=STAGES.index('expand'):
            lines.append({'stage':'A02-A04 (pre-CP2)','usd':max(0,float(run.cfg['forecast']['scenarios']['baseline']['pre_cp2'])-pre),'calls':26})
        if at<=STAGES.index('cp2'):
            for lv in ('ABSTRACT','FULL_TEXT'):
                n=sum(cp.content_level(r,run.dir)==lv for r in records)
                lines.append({'stage':'A05+A06 '+lv,'usd':n*rates['per_paper'][lv]['p90_usd'],'calls':n})
            if run.cfg.get('validation',{}).get('instability_test'):
                lines.append({'stage':'A06 instability repeats','usd':sum(rates['per_paper'][cp.content_level(r,run.dir)]['a06_p90_usd'] for r in records),'calls':len(records)})
            count=max(1,len((run.load('theme_framework.json') or {}).get('primary_themes',[])) or 8)
            lines.append({'stage':'A06 per theme','usd':count*rates['per_theme']['p90_usd'],'calls':count})
            F=sum(math.ceil(rates['per_paper'][cp.content_level(r,run.dir)]['findings_p90']) for r in records)
        elif at<=STAGES.index('validate'):
            import copy
            proxy=copy.copy(run);proxy.cfg=copy.deepcopy(run.cfg);proxy.cfg['batch']['enabled']=False
            lines,F=cp._per_paper_remaining(proxy,rates,in_flight)
        else: F=len(run.load('validated_findings.json') or [])
        if at<=STAGES.index('synthesize'):
            done=0
            from .synthesis_job import Ledger
            jobs=sorted(run.dir.glob('data/synthesis_job_*/ledger.jsonl'),key=lambda p:p.stat().st_mtime)
            if jobs: done=len(Ledger(jobs[-1]).state()['committed'])
            s=run.cfg['forecast']['scenarios']['baseline'];cost,calls=forecast.a07(F,run.cfg,run.budget,run.route,s)
            expected=2+forecast.A07_GROUP_CALLS(F)+math.ceil(forecast.A07_PROPOSITIONS_PER_FINDING*F/run.cfg['synthesis']['reconcile_page_size'])
            left=max(0,1-done/max(1,expected))
            lines.append({'stage':'A07-SYN','usd':cost*left,'calls':max(0,expected-done)})
            rr=run.budget._rates(run.route('A07-SYN').model,0)
            lines.append({'stage':'A07 cache writes','usd':calls*5800*(rr['cache_write_1h']-rr['input'])/1e6*left,'calls':0})
    elif stage==STAGE_2:
        scientific_ready(run)
        from .tools.downstream_projection import requests,_price,_weight
        pkg=run.load('synthesis_approved.json');F=len(run.load('validated_findings.json') or [])
        inputs={'pkg':pkg,'findings':run.load('validated_findings.json'),'corpus':records,'plan':run.load('manuscript_plan.json'),
                'ledger':run.load('allocation_ledger.json'),'journal':journal(run)}
        req=requests(run.route,run.cfg,F,inputs);s=run.cfg['forecast']['scenarios']['baseline']
        from .orchestrator import AGENT_LAST_STAGE
        for agent in sorted(SECOND):
            if STAGES.index(AGENT_LAST_STAGE[agent])<at:continue
            if agent=='A10-RV': cost,calls=forecast.a10(F,run.cfg,run.budget,run.route,s)
            else:
                rr=req[agent][0];calls=len(rr)
                cost=0;long_calls=0
                for bound,kind,tag in rr:
                    price,used,_,_=_price(agent,bound,kind,run.budget,run.route,run.cfg['admission'],run.cfg['bridge'],s)
                    model=run.route(agent)
                    threshold=(run.budget.prices.get(model.model) or {}).get('long_context_threshold')
                    if threshold and bound>threshold:
                        # Preserve the existing conservative byte-bound pricing-threshold gate.
                        rates=run.budget._rates(model.model,bound)
                        price=(bound/float(s['bytes_per_token'])*rates['input']+used*rates['output'])/1e6
                        long_calls+=1
                    cost+=_weight(tag,s)*price
            credit=completed_credit(run,agent)
            lines.append({'stage':agent,'basis':'STAGED_FORECAST','usd':max(0,cost-credit),'calls':calls,
                          'long_context_calls':0 if agent=='A10-RV' else long_calls,
                          'completed_forecast_usd':credit,'gross_forecast_usd':cost})
    else: raise AuthorizationRequired('Unknown pilot stage')
    # A pending interactive/A07/A10 submission must be reconciled before generating another request.
    # Batches carry their exact steps; _per_paper_remaining excludes them above.
    reservations=run.budget.reservations()
    batches=[r for p in (run.dir/'data'/'batches').glob('*.json') for r in json.loads(p.read_text(encoding='utf-8'))]
    covered={r['submission_id'] for r in batches if set(r['steps'])<=set(in_flight)}
    own=run.load('pilot_reservations.json',{})
    covered.update(k for k in reservations if k in own and set(own[k].get('steps',[])) and set(own[k]['steps'])<=set(in_flight))
    if set(reservations)-covered:
        raise AuthorizationRequired('Unsettled request reservation: reconcile accepted output/provider billing before new authorization or dispatch')
    if candidate:
        # Candidate work is removed from the forecast, then counted once at its strict commitment.
        agent,amount=candidate
        match=next((x for x in lines if x['stage']==agent),None)
        if match and match['calls']:
            units=match['calls']
            if agent=='A07-SYN':
                for extra in lines:
                    if extra['stage']=='A07 cache writes':extra['usd']=max(0,extra['usd']-extra['usd']/units)
            match['usd']=max(0,match['usd']-match['usd']/units);match['calls']-=1
        # Paper batches already excluded by in_flight, pre-CP2 budget is an unspent envelope.
        elif agent in {'A02-SP','A03-LM','A04-CQ'}:
            for x in lines:
                if x['stage']=='A02-A04 (pre-CP2)':x['usd']=max(0,x['usd']-amount)
        elif not in_flight:
            # Explicitly exclude the current paper unit via the established remaining builder.
            raise AuthorizationRequired('Candidate work must be identified in the remaining-work projection')
    retry_share=float(run.cfg['forecast']['scenarios']['baseline']['retries'])
    future=sum(x['usd'] for x in lines)*(1+retry_share)  # explicit future retry allowance; never added to actual billing
    commitments=run.budget.reserved()+(candidate[1] if candidate else 0)
    out=admit(run.budget.spent(),commitments,future)
    return {**out,'scope':stage,'lines':lines,'projected_remaining_usd':1.3*future,'papers':len(records),'retry_share':retry_share}

def request(run,stage):
    if not enabled(run): raise AuthorizationRequired('Run is not a staged pilot; prepare a new staged run')
    if stage==STAGE_2: scientific_ready(run)
    p=project(run,stage);context=identity(run,stage)
    if stage==STAGE_2 and p['verdict']!='WITHIN_CAP':partial(run,'Stage 2 forecast exceeds remaining authorized budget')
    review={'scope':stage,'context':context,'projection':p,'fingerprint':fingerprint([context,p])}
    atomic(run.data('pilot_pending_authorization.json'),review)
    return review

def approve(run,stage,digest,reviewer):
    if not reviewer.strip():raise AuthorizationRequired('Named human reviewer required')
    pending=run.load('pilot_pending_authorization.json') or {}
    if pending.get('scope')!=stage or pending.get('fingerprint')!=digest:raise AuthorizationRequired('No matching stage-specific pending projection')
    current=request(run,stage)
    if current['fingerprint']!=digest:raise AuthorizationRequired('Projection/state changed; review the fresh projection')
    if current['projection']['verdict']!='WITHIN_CAP':
        if stage==STAGE_2:partial(run,'Stage 2 forecast exceeds remaining authorized budget')
        raise AuthorizationRequired('Stage forecast exceeds $35 admission cap')
    approved={**current,'reviewer':reviewer,'status':stage}
    if stage==STAGE_2:
        st=run.state();st.pop('evaluation_result',None);st.pop('partial_reason',None);run.save_state(st)
    atomic(run.data('pilot_'+stage+'.json'),approved)
    run.prov.human_decision(stage,{'fingerprint':digest,'reviewer':reviewer},'Stage-specific financial approval; scientific checkpoints remain required')
    return approved

def partial(run,reason):
    st=run.state();st['evaluation_result']='COMPLETED_STAGE_1_PARTIAL_EVALUATION';st['partial_reason']=reason
    run.save_state(st)

def require(run,agent, financial=True):
    if not enabled(run):return
    stage=stage_for(run,agent)
    if agent in SECOND: scientific_ready(run)
    a=run.load('pilot_'+stage+'.json') or {}
    if (a.get('status')!=stage or fingerprint(a.get('context'))!=fingerprint(identity(run,stage))
            or a.get('fingerprint')!=fingerprint([a.get('context'),a.get('projection')])):
        if agent in SECOND:partial(run,'Stage 2 requires separate current human financial authorization')
        raise AuthorizationRequired('Missing/stale '+stage+'; project and obtain fresh human approval')
    pending=run.load('pilot_pending_authorization.json') or {}
    if pending.get('scope')==stage and pending.get('fingerprint')!=a['fingerprint']:
        raise AuthorizationRequired('Revised projection requires fresh stage approval')
    if not financial:return
    p=project(run,stage)
    if p['verdict']!='WITHIN_CAP':
        if agent in SECOND:partial(run,'Stage 2 exceeds remaining budget')
        raise AuthorizationRequired('Stage forecast exceeds $35 admission cap')
    atomic(run.data('pilot_live_projection.json'),p)
