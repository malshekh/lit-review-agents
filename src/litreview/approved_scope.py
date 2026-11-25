"""Researcher-approved scope delivery; no provider-facing schema changes."""
from __future__ import annotations
import copy,hashlib,json
from pathlib import Path


def guide(run):
    if not hasattr(run, 'dir'):return {}
    decision=(run.load('spec_approved.json',{}) or {}).get('researcher_decision',{})
    return decision.get('scope_guide') or {}


def enrich(run,agent,payload):
    scope=guide(run)
    if not scope:return payload
    out={**payload,'approved_scope_guide':copy.deepcopy(scope)}
    if agent in ('A08-OL','A09-WRI','A10-RV','A11-RC','A12-EDI'):
        out['six_heading_map']=copy.deepcopy(scope['six_heading_map'])
        out['chapter_word_targets']=copy.deepcopy(scope['word_policy'])
    return out


def writing_outline(run,outline):
    scope=guide(run)
    if not scope:return outline
    by_id={s['section_id']:s for s in outline['sections']}
    result=copy.deepcopy(outline);result['sections']=[copy.deepcopy(s) for s in outline['sections'] if not s.get('parent_section_id')]
    for mapping in scope['six_heading_map']:
        originals=[by_id[s] for s in mapping['discovery_sections']]
        entry=copy.deepcopy(originals[0]);entry.update({k:copy.deepcopy(v) for k,v in mapping.items() if k in ('section_id','parent_section_id','heading')})
        for key in ('questions','guidance','avoid'):
            entry[key]=[value for original in originals for value in original.get(key,[])]
        entry['scope']={key:[value for original in originals for value in original.get('scope',{}).get(key,[])] for key in ('includes','excludes')}
        entry['intended_contribution']=' '.join(original.get('intended_contribution','') for original in originals)
        entry['word_budget']=sum(s['word_budget'] for s in originals)
        result['sections'].append(entry)
    result['global_instructions']=list(result.get('global_instructions',[]))+[scope['writing_rules'],'Use the six approved manuscript subheadings; the eight themes organize discovery and extraction. Reference counts are full-review planning targets.']
    return result


def screening_details(qualification):
    try:value=json.loads(qualification.get('reason',''))
    except (TypeError,ValueError):return {'rationale':qualification.get('reason'),'evidence_role':None}
    return value if isinstance(value,dict) else {'rationale':qualification.get('reason'),'evidence_role':None}


def save_delivery(run,agent,step,payload):
    if not guide(run):return
    run.save('agent_inputs/'+step+'.json',{'agent':agent,'payload':payload,'payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()})


def registry_extension(prior,current):
    """OPEN_CORPUS discovery may add records or fill missing identifiers, not replace them."""
    after={r['record_id']:r for r in current}
    if len(after)!=len(current):return False
    for old in prior:
        new=after.get(old['record_id'])
        if new is None:return False
        for key in ('pmid','doi'):
            if old.get(key) and str(old[key]).lower()!=str(new.get(key) or '').lower():return False
        if old.get('in_fixed_corpus')!=new.get('in_fixed_corpus'):return False
    return True


def heading_problems(run,plan):
    scope=guide(run)
    if not scope:return []
    planned={s.get('section_id'):s.get('heading') for s in plan.get('sections',[])}
    return ['Approved manuscript heading missing or changed: '+m['section_id'] for m in scope['six_heading_map'] if planned.get(m['section_id'])!=m['heading']]


def extend_screened_themes(run,qualifications,framework):
    if not guide(run):return
    from . import theme_framework
    valid=theme_framework.ids(framework)
    for rid,q in list(qualifications.items()):
        if q.get('disposition')!='QUALIFIED':continue
        q=theme_framework.normalize(q,framework)
        extra=screening_details(q).get('informs_themes') or []
        if not isinstance(extra,list):extra=[]
        q['themes']=sorted(set(q.get('themes',[]))|{t for t in extra if isinstance(t,str) and t in valid})
        qualifications[rid]=q


def search_plan(run,spec,sources,budget,mode='PLAN',previous=None,execution=None,repair_number=0):
    """One approved question per request; unchanged model, schema and output cap.

    A failed monolithic planning receipt is never reused as a valid plan, erased,
    or resent. Each bounded unit has its own durable request identity.
    """
    from . import run_spec
    outline,_=run_spec.load(run.dir)
    questions=[s for s in outline['sections'] if s.get('parent_section_id')]
    plans=[]
    for question in questions:
        sid=question['section_id']
        old=run.load('search_units/'+sid+'.json')
        reports=[r for r in (execution or {}).get('families',[]) if str(r.get('family_id','')).startswith(sid+'_')]
        # A source/authorization outage is not repaired by repeating the same
        # scientific planning call. Preserve its error; repair genuine zero-yield
        # queries only, with the existing max_search_repairs bound.
        needs=mode=='PLAN' or any(not r.get('error') and not r.get('returned') for r in reports)
        if mode=='REPAIR' and not needs and old is not None:
            plans.append(old);continue
        compact={k:copy.deepcopy(spec.get(k)) for k in ('spec_version','central_question','selection_criteria','scope','audience')}
        compact['approved_perspective']='P1'
        compact['word_count_answer']=spec.get('researcher_decision',{}).get('answers_to_questions',{})
        unit_budget={**budget,'max_records_total':max(1,int(budget['max_records_total'])//len(questions))}
        payload={'mode':mode,'review_spec':compact,'sources_enabled':sources,'budget':unit_budget,
                 'corpus_policy':__import__('litreview.corpus_policy',fromlist=['resolve']).resolve(run),
                 'researcher_outline':{'review_question':outline['review_question'],'scope_statement':outline['scope_statement'],
                    'global_instructions':outline.get('global_instructions',[]),'sections':[question]},
                 'planning_unit':{'section_id':sid,'covers_only_this_question':True,
                     'instruction':'Plan ONLY this one question now. Code combines all eight units. Return one THEME family and at most one contrary or review family, each tied only to this section. Keep concept blocks to at most four with at most three terms each. Use short phrases and one-sentence rationales. Do not plan the entire review. No literature claims, novelty assessment or exhaustive vocabulary are needed. Use plain terms and no controlled vocabulary unless supplied. Do not name seed publications. Keep the sum of max_records over compiled sources/families within this unit budget. Actual discovery and citations occur in code.'}}
        if mode=='REPAIR':payload.update(previous_plan=old,execution_report=reports,seed_recall=[])
        step='A03-LM_'+('unit_plan' if mode=='PLAN' else 'unit_repair'+str(repair_number))+'_'+sid.replace('.','_')
        plan=run.agent('A03-LM',payload,step=step)
        run._agent_human_review('A03-LM',step,plan)
        old_ids={f['family_id']:sid+'_'+f['family_id'].removeprefix(sid+'_') for f in plan.get('query_families',[])}
        for family in plan.get('query_families',[]):
            if family.get('section_ids') and set(family['section_ids'])!={sid}:raise ValueError('Planning unit changed its approved question')
            family['family_id']=old_ids[family['family_id']];family['section_ids']=[sid]
        plan['citation_expansion_seed_families']=[old_ids.get(f,f) for f in plan.get('citation_expansion_seed_families',[])]
        for repair in plan.get('repairs',[]):repair['family_id']=old_ids.get(repair['family_id'],repair['family_id'])
        run.save('search_units/'+sid+'.json',plan);plans.append(plan)
    merged=copy.deepcopy(plans[0])
    for key in ('concept_blocks','query_families','citation_expansion_seed_families','repairs','seeds_not_recalled','warnings','limitations'):
        merged[key]=[value for plan in plans for value in plan.get(key,[])]
    merged.update(mode=mode,plan_version='approved-question-units-1',status='COMPLETE_WITH_WARNINGS' if merged['warnings'] else 'COMPLETE')
    from .agents.base import validate
    validate('A03-LM',merged)
    return merged
