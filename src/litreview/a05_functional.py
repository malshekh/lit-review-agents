"""A bounded nonempty A05 task check and the actual independent A06 handoff. Planning is offline."""
from __future__ import annotations
import copy, dataclasses, hashlib, json
from pathlib import Path
import jsonschema
from . import config, extraction_mode
from .paths import REPO_ROOT

SOURCE=REPO_ROOT/"docs/pilot7/a05_functional/source_and_expectations.json"
A05_OUTPUT_TOKENS=4000
A06_OUTPUT_TOKENS=2500
A05_INPUT_BYTES=52000
A06_INPUT_BYTES=64000
CHECK_VERSION=1


def fixture():return json.loads(SOURCE.read_text(encoding="utf-8"))


def require_expected(ext,expected):
    entities={e['entity_id']:e for e in ext.get('entities',[])}
    contexts={c['context_id']:c['fields'] for c in ext.get('contexts',[])}
    findings=ext.get('findings',[])
    if len(findings)<expected['min_findings']:raise jsonschema.ValidationError("Functional omission: nonempty expected findings are missing")
    for requirement in expected['requirements']:
        def matches(f):
            subject=entities.get(f['subject_entity_id'],{}).get('mention','').lower()
            analyte=requirement.get('analyte_contains','').lower()
            if analyte=='dsf':
                if not any(x in subject for x in ('dsf','disulfiram')):return False
            elif analyte not in subject:return False
            context=contexts[f['context_id']]
            if requirement.get('matrix') and requirement['matrix'].rstrip('s').lower()!=str(context.get('matrix','')).rstrip('s').lower():return False
            if f.get('predicate')!=requirement['predicate'] or f.get('polarity')!=requirement['polarity']:return False
            if f['span']!=requirement['quote']:return False
            if context.get('comparator')!='NONE_REPORTED':return False
            if 'raw_value' in requirement:
                if not any(q.get('raw_value')==requirement['raw_value'] and q.get('raw_unit')==requirement['raw_unit'] for q in f.get('quantities',[])):return False
            elif f.get('quantities'):return False  # Detection sentence reports no numeric concentration.
            if requirement['task']=='presence_detection' and any(x in str(context.get('readout','')).lower() for x in ('numerical','regression','estimate')):return False
            return True
        if not any(matches(f) for f in findings):raise jsonschema.ValidationError('Functional omission or incorrect scientific reading: '+str(requirement))
    return True


def check_identity():
    from .agents.base import build_system_prompt
    from . import structured
    return {**extraction_mode.identity(),'functional_check_version':CHECK_VERSION,
            'source_expectations_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'models':{a:dataclasses.asdict(config.agent_model(a)) for a in ('A05-KE','A06-SV')},
            'prompts':{a:hashlib.sha256(build_system_prompt(a).encode()).hexdigest() for a in ('A05-KE','A06-SV')},
            'a06_submitted_schema_sha256':structured.slim('A06-SV.schema.json','openai')[1],
            'caps':{'A05':A05_OUTPUT_TOKENS,'A06':A06_OUTPUT_TOKENS,'input_bytes_A05':A05_INPUT_BYTES,'input_bytes_A06':A06_INPUT_BYTES,
                    'framing_reserve_tokens':1024,'cache_system':False,'cache_payload':False,'format_repairs_per_agent':1,'truncation_retries':0}}


def fingerprint():return hashlib.sha256(json.dumps(check_identity(),sort_keys=True).encode()).hexdigest()


def verified(run_dir):
    p=Path(run_dir)/'functional_checks/a05_canonical_json/result.json'
    if not p.exists():return False
    doc=json.loads(p.read_text(encoding='utf-8'))
    if not doc.get('accepted') or doc.get('fingerprint')!=fingerprint():return False
    # Exact original raw responses and canonical handoff artifacts must still be present.
    return bool(doc.get('artifacts')) and all((Path(run_dir)/name).is_file() and hashlib.sha256((Path(run_dir)/name).read_bytes()).hexdigest()==digest for name,digest in doc['artifacts'].items())


def handoff(run,ext,source):
    """Uses Run._validate_papers and its real preparation, gate/batching, vendor exclusion and saving."""
    from .agents.base import validate
    validate('A05-KE',ext)
    rid=ext['record_id']
    run.save('spec_approved.json',source['payload']['review_spec'])
    run.save('extractions/'+rid+'.json',ext)
    run.save('fulltext/'+rid+'.json',source['payload']['record']['content'])
    run.save('source_access.json',{rid:ext['source_access']})
    run._validate_papers([rid])
    result=run.load('validations/'+rid+'.json')
    wanted={f['finding_id'] for f in ext['findings']}
    rows=result.get('validations',[])
    if {r['finding_id'] for r in rows}!=wanted:raise ValueError('Incomplete independent A06 coverage')
    if any(r['gate1']!='PASSED' or r['disposition'] not in ('SUPPORTED','SUPPORTED_WITH_CONSTRAINTS','SUPPORTED_FOR_OBSERVATION') for r in rows):
        raise ValueError('Functional scientific validation failed; independent validator did not support all expected readings')
    return result


def plan(budget):
    from .agents.base import build_system_prompt,user_parts
    from . import structured
    payload=fixture()['payload']
    prompt=build_system_prompt('A05-KE');m=config.agent_model('A05-KE')
    actual=len(prompt.encode())+sum(len(x['text'].encode()) for x in user_parts(payload,m.cache_payload))
    if actual>A05_INPUT_BYTES:raise ValueError('Functional A05 input exceeds its fixed bound')
    # Input byte limits are enforced before each send, including a format repair. One byte/token is conservative.
    costs={a:budget.cost(config.agent_model(a).model,inp,out)*2 for a,inp,out in
           [('A05-KE',A05_INPUT_BYTES,A05_OUTPUT_TOKENS),('A06-SV',A06_INPUT_BYTES,A06_OUTPUT_TOKENS)]}
    strict_usd,todo=structured.smoke_estimate(budget)
    from . import smoke_validation
    run_dir=budget.log_path.parent
    enrichment_path=run_dir/'smoke_receipt_enrichment.json'
    enrichment=json.loads(enrichment_path.read_text(encoding='utf-8')) if enrichment_path.exists() else {}
    reusable={}
    targets={(t['provider'],t['model'],t['schema_sha256']):t for t in structured.targets()}
    for receipt_path in sorted((run_dir/'smoke_receipts').glob('*.json')):
        raw=json.loads(receipt_path.read_text(encoding='utf-8'))
        if raw.get('state')!='RECEIVED':continue
        receipt,assessment=smoke_validation.receipt_evidence(receipt_path,enrichment)
        key=(receipt['provider'],receipt['model'],receipt['schema_sha256'])
        if assessment['accepted'] and key in targets:
            target=targets[key]
            reusable[key]={'provider':key[0],'model':key[1],'schema_sha256':key[2],'schema_file':target['schema_file'],
                           'receipt':receipt_path.name,'receipt_sha256':assessment['receipt_sha256'],'exact_response_validation':True}
    return {'status':'PREPARED_NOT_DISPATCHED','fingerprint':fingerprint(),'identity':check_identity(),
            'mode':extraction_mode.MODE,'provider_strict_schema_submitted':False,
            'source':fixture()['source'],'expected_findings':fixture()['expected'],
            'functional_worst_case_usd':round(sum(costs.values()),7),'separate_worst_case_usd':costs,
            'basis':'At most one primary and one saved-response format repair for each agent, fixed output caps, hard byte bound on every request, bytes as input-token upper bound; no automatic truncation retry or model change.',
            'actual_a05_input_bytes':actual,'per_request_overhead_token_reserve':1024,'strict_checks_remaining':[t['schema_file'] for t in todo],
            'strict_remaining_worst_case_usd':strict_usd,'prior_successes_still_matching':list(reusable.values()),'prior_success_count':len(reusable),'combined_remaining_worst_case_usd':round(sum(costs.values())+strict_usd,7),
            'recorded_spend_usd':budget.spent(),'held_usd':budget.reserved(),
            'smoke_remaining_after_spend_and_holds_usd':round(1-smoke_spent(budget)-budget.reserved(),7),
            'paid_dispatch_authorized':False,'pending_decisions':['Newest $0.041668 hold','New A05 ordinary JSON functional check'],
            'pilot_caps':{'total':50,'smoke':1},'pilot_scientific_outputs_carried_over':False}


def smoke_spent(budget):
    return sum(e.get('cost_usd') or 0 for e in budget.entries()
               if e.get('agent')=='smoke-test' or 'FUNCTIONAL_SOURCE_1' in e.get('step',''))


def dispatch_guard(budget,agent,step):
    """Used by the prepared functional task: fixed byte/output bounds and at most one saved-reply repair."""
    from .budget import BudgetExceeded
    max_input=A05_INPUT_BYTES if agent=='A05-KE' else A06_INPUT_BYTES
    max_output=A05_OUTPUT_TOKENS if agent=='A05-KE' else A06_OUTPUT_TOKENS
    configured=config.agent_model(agent)
    def guard(attempt,system,message,model):
        if attempt not in (0,1):raise ValueError('Functional check permits only one primary and one format repair')
        if model.provider!=configured.provider or model.model!=configured.model:raise ValueError('Functional model substitution refused')
        from . import structured
        shape=structured.response_schema(agent,None,model.provider,model.model)
        schema_bytes=len(json.dumps(shape).encode()) if shape else 0
        n=len(system.encode())+sum(len(p['text'].encode()) for p in message)+schema_bytes+1024
        if n>max_input or model.max_tokens>max_output or model.cache_system or any(p.get('cache') for p in message):
            raise ValueError('Functional request exceeds its reviewed input/output bounds or enables unpriced caching')
        key='functional-'+hashlib.sha256((fingerprint()+step+str(attempt)).encode()).hexdigest()[:24]
        if key in budget.reservations():raise ValueError('Unsettled functional dispatch; reconcile before any retry')
        if any(e.get('reservation_key')==key for e in budget.entries()):raise ValueError('Functional attempt already paid; recover its receipt or request a new reviewed attempt')
        worst=budget.cost(model.model,n,model.max_tokens)
        if smoke_spent(budget)+budget.reserved()+worst>1:raise BudgetExceeded('Combined smoke and functional allowance exceeded')
        ok,_=budget.reserve(key,worst,agent,'Bounded A05 mode functional check; unknown billing retains hold')
        if not ok:raise BudgetExceeded('Functional check does not fit combined pilot cap')
        return key
    return guard


def execute(parent_run,approve_usd,by,decision):
    """Prepared execution entry point. Requires a future hash-bound decision and the fourth-hold authorization.
    This function is never called by planning, tests without scripted models, or generic schema smoke.
    """
    from .orchestrator import Run
    from .agents.base import run_agent
    from .job_ledger import Ledger,RunLock
    from .retained_hold import blocking_holds
    from .runtime_identity import require_execution_context
    from .runtime_integrity import verify
    from .paths import REPO_ROOT
    require_execution_context()
    seal=json.loads((REPO_ROOT/'frozen_runtime_manifest.json').read_text(encoding='utf-8'));verify(REPO_ROOT,seal)
    if not by or decision.get('fingerprint')!=fingerprint() or decision.get('approved_by')!=by:
        raise ValueError('New functional mode needs explicit fingerprint-bound researcher approval')
    if blocking_holds(parent_run.budget,REPO_ROOT/'pilot_retained_hold_authorization.json',operation='functional'):
        raise ValueError('Unapproved billing hold remains; no functional dispatch')
    from . import structured
    validator=config.agent_model('A06-SV')
    if structured.response_schema('A06-SV',None,validator.provider,validator.model) is None:
        raise ValueError('Complete the outstanding exact A06 schema smoke before the functional task; no A05 dispatch')
    proposal=plan(parent_run.budget)
    if approve_usd<proposal['functional_worst_case_usd']:raise ValueError('Functional check exceeds explicit approved amount')
    if proposal['functional_worst_case_usd']+smoke_spent(parent_run.budget)+parent_run.budget.reserved()>1:
        raise ValueError('Functional check exceeds remaining $1 smoke allowance')
    class FunctionalRun(Run):
        def agent(self,aid,payload,step,exclude_providers=frozenset(),**kwargs):
            m=config.agent_model(aid)
            if m.provider in exclude_providers:raise ValueError('Independent validator must use another provider')
            m=dataclasses.replace(m,max_tokens=A05_OUTPUT_TOKENS if aid=='A05-KE' else A06_OUTPUT_TOKENS,
                                  cache_system=False,cache_payload=())
            output=run_agent(aid,payload,self.dir,step,self.budget,self.prov,model=m,repair_limit=1,
                truncation_retries=0,dispatch_guard=dispatch_guard(self.budget,aid,step),ledger=Ledger(self.dir),
                request_id=hashlib.sha256((fingerprint()+step).encode()).hexdigest())
            self.last_model=m.model
            return output
    with RunLock(parent_run.dir):
        if verified(parent_run.dir):return json.loads((parent_run.dir/'functional_checks/a05_canonical_json/result.json').read_text())
        work=FunctionalRun(parent_run.id+'/functional_checks/a05_canonical_json/work')
        work.budget=parent_run.budget
        work.save_state({'profile':'pilot7','stage':'validate','status':'ENGINEERING_FUNCTIONAL_ONLY','counters':{}})
        source=fixture();payload=source['payload']
        step='A05-KE_FUNCTIONAL_SOURCE_1'
        out_file=work.dir/'outputs'/f'{step}.json'
        if out_file.exists():ext=extraction_mode.accept(out_file.read_text(encoding='utf-8'),payload)
        else:ext=work.agent('A05-KE',payload,step)
        require_expected(ext,source['expected'])
        handoff(work,ext,source)
        artifacts={p.relative_to(parent_run.dir).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                   for folder in ('outputs','data/a06_inputs','data/validations') for p in (work.dir/folder).glob('*') if p.is_file()}
        result={'accepted':True,'fingerprint':fingerprint(),'identity':check_identity(),'artifacts':artifacts,
                'scientific_checkpoint_approved':False,'full_text_extraction_tested':False,
                'costs_usd':{a:sum(e.get('cost_usd') or 0 for e in parent_run.budget.entries() if e.get('agent')==a and 'FUNCTIONAL_SOURCE_1' in e.get('step',''))
                             for a in ('A05-KE','A06-SV')}}
        path=parent_run.dir/'functional_checks/a05_canonical_json/result.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        return result
