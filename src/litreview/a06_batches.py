"""Bounded A06 PER_PAPER audits with complete, durable finding dispositions."""
import copy
import dataclasses
import hashlib
import json
import math
from .agents.base import validate,build_system_prompt,AgentError
from .scientific_validation import require_complete
from .synthesis_registry import fingerprint
from .tools import span_check

SIZE=15
TRUNCATION_RETRIES=1


def enabled(run,payload):
    return bool((run.cfg.get('validation') or {}).get('findings_per_call')) and payload.get('mode')=='PER_PAPER' and not payload.get('a06_validation_batch') and len(payload.get('extraction',{}).get('findings',[]))>int(run.cfg['validation']['findings_per_call'])


def _refs(value,suffix):
    found=set()
    if isinstance(value,dict):
        for k,v in value.items():
            if k.endswith(suffix) and isinstance(v,str):found.add(v)
            else:found.update(_refs(v,suffix))
    elif isinstance(value,list):
        for v in value:found.update(_refs(v,suffix))
    return found


def batches(payload,size=SIZE):
    if not isinstance(size,int) or not 1<=size<=SIZE:raise ValueError('A06 batch size must be between 1 and 15')
    ext=payload['extraction'];findings=ext['findings'];ids=[f['finding_id'] for f in findings]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate input finding IDs')
    entities={e['entity_id']:e for e in ext.get('entities',[])}
    index=[{**{k:f.get(k) for k in ('finding_id','span_location','predicate')},
            'subject_mention':entities.get(f.get('subject_entity_id'),{}).get('mention'),
            'object_mention':entities.get(f.get('object_entity_id'),{}).get('mention')} for f in findings]
    result=[]
    for start in range(0,len(findings),size):
        selected=findings[start:start+size];sub={k:copy.deepcopy(v) for k,v in ext.items() if not k.startswith('_') and k not in ('entities','contexts','findings')}
        context_ids=_refs(selected,'context_id');sub['contexts']=[copy.deepcopy(c) for c in ext.get('contexts',[]) if c.get('context_id') in context_ids]
        entity_ids=_refs(selected,'entity_id')|_refs(sub['contexts'],'entity_id')
        while True:
            more=set().union(*(_refs(entities[e],'entity_id') for e in entity_ids if e in entities)) if entity_ids else set()
            if more<=entity_ids:break
            entity_ids.update(more)
        if entity_ids-set(entities):raise ValueError('A06 input has dangling entity references')
        sub['entities']=[copy.deepcopy(e) for e in ext.get('entities',[]) if e['entity_id'] in entity_ids]
        sub['findings']=copy.deepcopy(selected)
        value={**payload,'extraction':sub,'gate1_results':span_check.check_findings(sub,payload['paper_text']),
               'paper_finding_index':index,
               'a06_validation_batch':{'version':1,'finding_ids':[f['finding_id'] for f in selected],
                 'instruction':'Audit exactly these finding IDs using the full supplied paper. Return one disposition per requested ID. Preserve source inconsistencies and normalization conflicts, including relationships to other IDs in paper_finding_index; never infer that separate audit batches are independent studies.'}}
        result.append(value)
    return result


def validate_batch(output,part,whole):
    validate('A06-SV',output)
    # Finding dispositions are local; scientific annotations may relate to any known paper finding.
    local={**output,'source_inconsistencies':[],'normalization_conflicts':[]}
    require_complete(local,part['extraction'],whole['extraction']['record_id'])
    all_ids={f['finding_id'] for f in whole['extraction']['findings']}
    entities={e['entity_id'] for e in whole['extraction'].get('entities',[])}
    for field in ('source_inconsistencies','normalization_conflicts'):
        values=output.get(field,[])
        if not isinstance(values,list):raise ValueError('Malformed A06 batch annotations')
        for value in values:
            if not isinstance(value,dict) or set(value.get('finding_ids',[]))-all_ids:raise ValueError('Unknown cross-batch finding reference')
            if field=='normalization_conflicts' and value.get('entity_id') not in entities:raise ValueError('Unknown normalization entity')


def merge(payload,parts,outputs):
    if len(outputs)!=len(parts):raise ValueError('Incomplete A06 batch coverage')
    result={'agent_id':'A6-SV','prompt_version':outputs[0]['prompt_version'] if outputs else 'unknown',
            'status':'COMPLETE_WITH_WARNINGS','mode':'PER_PAPER','record_id':payload['extraction']['record_id'],
            'validations':[],'warnings':[],'limitations':[],'defect_reports':[],'source_inconsistencies':[],'normalization_conflicts':[]}
    rows={};metadata=[]
    for part,out in zip(parts,outputs):
        validate_batch(out,part,payload)
        for v in out['validations']:
            if v['finding_id'] in rows:raise ValueError('Duplicate merged disposition')
            rows[v['finding_id']]=copy.deepcopy(v)
        for field in ('warnings','limitations','defect_reports','source_inconsistencies','normalization_conflicts'):
            for item in out.get(field,[]):
                if item not in result[field]:result[field].append(copy.deepcopy(item))
        metadata.append({k:copy.deepcopy(v) for k,v in out.items() if k not in result and k!='defect_count' and not k.startswith('_')})
    result['validations']=[rows[f['finding_id']] for f in payload['extraction']['findings']]
    result['defect_count']=len(result['defect_reports']);result['batch_metadata']=metadata
    require_complete(result,payload['extraction'],result['record_id']);validate('A06-SV',result)
    return result


def manifest_for(run,payload,root_step,model,parts):
    manifest={'version':1,'root_step':root_step,'input_fingerprint':fingerprint(payload),
              'model':dataclasses.asdict(model),'system_sha256':hashlib.sha256(build_system_prompt('A06-SV').encode()).hexdigest(),
              'schema_sha256':hashlib.sha256((run.dir.parent.parent/'schemas/A06-SV.schema.json').read_bytes()).hexdigest()
                 if (run.dir.parent.parent/'schemas/A06-SV.schema.json').is_file() else None,
              'parts':[{'batch':i+1,'finding_ids':p['a06_validation_batch']['finding_ids'],'payload_fingerprint':fingerprint(p)} for i,p in enumerate(parts)]}
    manifest=json.loads(json.dumps(manifest))
    return manifest


def audit(run,payload,root_step,overrides=None,schema_file=None,exclude=frozenset()):
    if schema_file is not None:raise ValueError('A06 batching requires the approved scientific schema')
    if int(run.cfg['validation'].get('truncation_retries',1))!=TRUNCATION_RETRIES:raise ValueError('Only one truncation retry is authorized per A06 batch')
    rid=payload['extraction']['record_id']
    if payload['paper_text']!=run.load('fulltext/'+rid+'.json'):raise ValueError('A06 batch source differs from cached paper')
    size=int(run.cfg['validation']['findings_per_call']);parts=batches(payload,size)
    model=run.route('A06-SV',exclude)
    if overrides:model=dataclasses.replace(model,**overrides)
    manifest=manifest_for(run,payload,root_step,model,parts)
    digest=fingerprint(manifest);base='a06_batches/'+root_step+'_'+digest[:16]+'/'
    existing=run.load(base+'manifest.json')
    if existing is not None and existing!=manifest:raise ValueError('A06 batch manifest changed')
    run.save(base+'manifest.json',manifest)
    outputs=[];accepted=[]
    for i,part in enumerate(parts,1):
        receipt=run.load(base+str(i)+'.json');first=receipt['attempt'] if receipt else 1
        if receipt is None:
            while run.load(base+str(i)+'_truncated_'+str(first)+'.json') is not None:first+=1
            if first>TRUNCATION_RETRIES+1:raise ValueError('A06 batch exhausted its one truncation retry; accepted batches remain saved')
        out=None
        for attempt in range(first,TRUNCATION_RETRIES+2):
            step=root_step+'_B'+str(i).zfill(3)+'_'+digest[:10]+'_try'+str(attempt)
            try:
                out=run.agent('A06-SV',part,step,overrides=overrides,exclude_providers=exclude,repair_limit=0)
            except AgentError as exc:
                if 'Output was truncated at max_tokens' not in str(exc):raise
                raw=run.dir/'outputs'/(step+'.raw0.txt')
                run.save(base+str(i)+'_truncated_'+str(attempt)+'.json',{'step':step,'status':'TRUNCATED',
                         'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest() if raw.exists() else None})
                if attempt>TRUNCATION_RETRIES:raise
                continue
            run._agent_human_review('A06-SV',step,out)
            validate_batch(out,part,payload)
            value={'batch':i,'finding_ids':part['a06_validation_batch']['finding_ids'],'attempt':attempt,
                   'step':step,'payload_fingerprint':fingerprint(part),'output_fingerprint':fingerprint(out),'status':'ACCEPTED'}
            if receipt is not None and value!=receipt:raise ValueError('Accepted A06 batch changed')
            run.save(base+str(i)+'.json',value);accepted.append(value);break
        outputs.append(out)
    result=merge(payload,parts,outputs)
    proof={'root_step':root_step,'manifest_fingerprint':digest,'input_fingerprint':fingerprint(payload),
           'status':'COMPLETE','finding_ids':[v['finding_id'] for v in result['validations']],
           'batches':accepted,'output_fingerprint':fingerprint(result),'model':model.model,'provider':model.provider}
    previous=run.load('a06_batch_receipts/'+root_step+'.json')
    if previous is not None and previous!=proof:raise ValueError('A06 merged receipt changed')
    run.save('a06_batch_receipts/'+root_step+'.json',proof)
    if previous is None:run.prov.tool_run('A06_batch_merge',root_step,{'finding_count':len(result['validations']),'batch_count':len(parts),'new_agent_execution':False})
    return result


def forecast_increment(run,in_flight=frozenset()):
    """Explicit batch overhead using measured input density and historical A06 output cost.

    Each actual attempt still reserves its full 64k output cap and byte-bound input.
    These are modeled remaining costs, never a substitute for per-call admission.
    """
    policy_path=run.dir/'input/a06_batch_recovery.json'
    if not policy_path.is_file() or not (run.cfg.get('validation') or {}).get('findings_per_call'):return 0.,0
    policy=json.loads(policy_path.read_text(encoding='utf8'));rid=policy['record_id']
    if run.state()['stage']!='validate':return 0.,0
    from .agents.base import user_parts
    from .synthesis_registry import offline_tokens
    from .tools import cost_projection as cp
    saved=run.load('a06_inputs/'+rid+'.json')
    if not saved:raise ValueError('Missing exact A06 recovery input')
    payload=saved['payload'];parts=batches(payload,int(run.cfg['validation']['findings_per_call']))
    model=run.route('A06-SV',frozenset({run._extraction_vendor(rid)}));rates=cp.load_rates();original=rates['per_paper']['FULL_TEXT']['a06_p90_usd']
    scenario=run.cfg['forecast']['scenarios']['baseline'];label=policy.get('forecast_calibration','measured')
    modeled=0.;count=0;replaced=0.
    phases=[]
    if not run.load('validations/'+rid+'.json'):phases.append(policy['root_step'])
    val=run.load('validations/'+rid+'.json')
    repeat_needed=(not val or any(str(x.get('disposition','')).startswith('BLOCKED') for x in val.get('validations',[])))
    if run.cfg['validation'].get('instability_test') and repeat_needed and not run.load('validation_repeats/'+rid+'.json'):
        phases.append('A06-SV_'+rid+'_repeat')
    for root in phases:
        remaining=[]
        manifest=manifest_for(run,payload,root,model,parts)
        folder='a06_batches/'+root+'_'+fingerprint(manifest)[:16]+'/'
        for i,part in enumerate(parts,1):
            receipt=run.load(folder+str(i)+'.json')
            if receipt and receipt.get('payload_fingerprint')==fingerprint(part):continue
            if any(step.startswith(root+'_B'+str(i).zfill(3)+'_') for step in in_flight):continue
            remaining.append(part)
        if not remaining:continue
        replaced+=original
        for part in remaining:
            bound=offline_tokens(build_system_prompt('A06-SV'))+offline_tokens(user_parts(part,model.cache_payload))
            if float(scenario['output'])<=.5:
                tokens=math.ceil(bound*policy['observed_input_tokens']/policy['observed_input_byte_bound'])
                output_cost=rates['per_paper']['ABSTRACT']['a06_p90_usd']
                input_cost=run.budget.cost(model.model,0,0,cache_write_tokens=tokens)
                cost=input_cost+output_cost
            else:
                tokens=math.ceil(bound/float(scenario['bytes_per_token']))
                cost=run.budget.cost(model.model,0,int(model.max_tokens*float(scenario['output'])),cache_write_tokens=tokens)
            if cost is None:raise ValueError('Unpriced A06 batch')
            modeled+=cost;count+=1
    return max(0.,modeled-replaced),count
