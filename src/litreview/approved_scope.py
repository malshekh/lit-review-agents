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
