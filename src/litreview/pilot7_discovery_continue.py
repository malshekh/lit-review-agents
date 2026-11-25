"""Record the explicit CP1 decision; discover and stop at provisional CP2."""
from __future__ import annotations
import copy,hashlib,json,time
from pathlib import Path
from . import checkpoints,config,structured,model_record
from .approved_scope import screening_details


def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def decision(run,guide):
    original=copy.deepcopy(run.load('spec.json')['selection_criteria'])
    for item in original.get('inclusion',[]):
        if 'For core empirical coverage' in item.get('criterion',''):
            item['criterion']='Use the approved SENSOR_DESIGN and SENSOR_INTERPRETATION routes. A computational sensing-design proposal is eligible as design evidence even when not built; claims of improved physical sensing performance require experimental evidence. For interpretation, require a nanoscale recognition/signal role and a learned model using measured responses. Conventional calibration and reference methods remain eligible comparators/context.'
            item['reason']='The researcher explicitly separates design proposals, experimental performance and measured-response interpretation.'
    original['significance_signals_definition']='Relevance, independent evidence and contribution signals for ranking eligible records; statistical significance and result direction do not determine eligibility.'
    original['exclusion']=[x for x in original['exclusion'] if 'deprioritize redundant' not in x.get('criterion','').lower()]
    original['exclusion_reason_vocabulary']=[x for x in original.get('exclusion_reason_vocabulary',[]) if x!='LOWER_SIGNIFICANCE_THAN_ALTERNATIVES']
    original['redundancy_policy']=guide['selection_policy']['redundancy_rule']
    original['pilot_selection_policy']=guide['selection_policy']
    original['eligibility_routes']=guide['eligibility_routes']
    original['evidence_roles']=guide['evidence_roles']
    original['out_of_scope']=guide['exclusions']
    return {'selected_option_id':'P1','edited_angle':guide['organizing_question'],'approve_selection_criteria':True,
            'edited_selection_criteria':original,'edited_theme_framework':None,'scope_guide':guide,
            'answers_to_questions':{'chapter_word_allocation':'Approximately 800 words per chapter, excluding headings and references, with flexible subsection allocations.'},
            'confirm_corpus_policy':True,'corpus_policy_fingerprint':run.state()['corpus_policy_fingerprint'],
            'notes':'Explicit researcher CP1 approval: P1, eight outline-defined themes, corrected eligibility/redundancy policy, six manuscript subheadings, OPEN_CORPUS broad discovery and citation expansion; no seed papers. Discovery has no lower date cutoff or language restriction; record actual date and translation limitations, flag preprints and link versions. Continue under $50 with $25/$48 review pauses. Stop at CP2 before freezing or paid extraction.'}


def report_cp2(run):
    records=run.load('records.json',[]);by_id={r['record_id']:r for r in records}
    quals={q['record_id']:q for q in run.load('qualifications.json',[])}
    proposed=run.load('selection_proposal.json',{}).get('proposed',[])
    ids=[p['record_id'] for p in proposed]
    if ids:
        review=run._cp2_review_selection(ids,by_id,quals)
        run.save('corpus_manifest.provisional.json',review['manifest']);run.save('cost_projection.provisional.json',review['projection'])
        run._write_cp2_selection_review(review,approved=False)
    else:review={'problems':['No eligible selection proposed'],'manifest':{'papers':[]},'projection':{},'accounts':{}}
    guide=run.load('spec_approved.json')['researcher_decision']['scope_guide']
    theme_to_heading={t:m['heading'] for m in guide['six_heading_map'] for t in m['themes']}
    access=run.load('retrieval_log.json',{})
    table=[]
    for p in proposed:
        rid=p['record_id'];r=by_id[rid];q=quals[rid];d=screening_details(q)
        table.append({'record_id':rid,'citation':{'title':r['title'],'authors':r.get('authors',[]),'year':r.get('year'),'venue':r.get('venue'),'doi':r.get('doi'),'pmid':r.get('pmid')},
                      'themes':q.get('themes',[]),'subsections':sorted({theme_to_heading[t] for t in q.get('themes',[]) if t in theme_to_heading}),
                      'selection_reason':p['reason'],'screening_details':d,'actual_access':access.get(rid),
                      'is_contrary_evidence':q.get('is_contrary_evidence'),'preprint':r.get('is_preprint',False)})
    covered={t for row in table for t in row['themes']}
    yield_rows=[]
    for r in run.load('search_log.json',[]):
        yield_rows.append({k:r.get(k) for k in ('family_id','section_ids','source','query','hit_count','returned','error','searched_at')})
    selected=set(ids)
    eligible_left=[q['record_id'] for q in quals.values() if q.get('disposition')=='QUALIFIED' and q['record_id'] not in selected]
    pilot_left=eligible_left if len(ids)>=guide['selection_policy']['max_publications'] else []
    result={'run_id':run.id,'status':'CP2_PROVISIONAL_NOT_FROZEN','proposed_papers':table,
            'uncovered_themes':[t for t in ('T1','T2','T3','T4','T5','T6','T7','T8') if t not in covered],
            'eligible_not_selected_pilot_limit':pilot_left,'other_eligible_not_proposed':[rid for rid in eligible_left if rid not in pilot_left],
            'scientifically_excluded':[q['record_id'] for q in quals.values() if q.get('disposition')=='EXCLUDED' and q.get('exclusion_code')!='DUPLICATE'],
            'duplicate_or_version_screening_exclusions':[q['record_id'] for q in quals.values() if q.get('disposition')=='EXCLUDED' and q.get('exclusion_code')=='DUPLICATE'],
            'unresolved_screening':[q['record_id'] for q in quals.values() if q.get('disposition') not in ('QUALIFIED','EXCLUDED')],
            'eligible_contrary':[q['record_id'] for q in quals.values() if q.get('disposition')=='QUALIFIED' and q.get('is_contrary_evidence')],
            'query_yield_by_theme':yield_rows,'search_record_count':len(records),'screened_record_count':len(quals),
            'projection':review['projection'],'projection_problems':review['problems'],'accounts':review['accounts'],
            'actual_recorded_spend_usd':run.budget.spent(),'held_usd':run.budget.reserved(),
            'any_full_text_obtained':any(a.get('level_read')=='FULL_TEXT' for a in access.values()),'full_text_extraction_tested':False,
            'cp2_approved':False,'corpus_frozen':False,'paid_extraction_started':False}
    run.save('cp2_pilot_report.json',result)
    def clean(x):return str(x if x is not None else 'unknown').replace('|','/').replace('\n',' ')
    lines=['# CP2 ? provisional seven-publication pilot','', 'No corpus is frozen and no paid extraction has started. Screening details marked unknown remain for extraction.','',
           '| Record and citation | Subsection / evidence role | Target / matrix / inferred output | Reference or comparator known at screening | Selection reason | Actual source access | Contrary |',
           '|---|---|---|---|---|---|---|']
    for row in table:
        c=row['citation'];d=row['screening_details'];a=row['actual_access'] or {}
        citation=f"{row['record_id']}: {c['title']} ({c.get('year')}); DOI {c.get('doi') or 'unknown'}; PMID {c.get('pmid') or 'unknown'}"
        refs='; '.join(f"{k}: {d.get(k) or 'unknown'}" for k in ('target_reference','analytical_reference','ai_baseline'))
        vals=[citation,', '.join(row['subsections'])+' / '+str(d.get('evidence_role') or 'unknown'),
              ' / '.join(str(d.get(k) or 'unknown') for k in ('target','matrix','inferred_output')),refs,row['selection_reason'],
              str(a.get('level_read') or 'UNRESOLVED')+' ? '+str(a.get('category') or 'not checked'),row['is_contrary_evidence']]
        lines.append('| '+' | '.join(clean(v) for v in vals)+' |')
    lines+=['','## Coverage and screening',f"Uncovered themes in the proposed selection: {', '.join(result['uncovered_themes']) or 'none'}. These are selected-corpus limits, not field-wide evidence gaps.",
            f"Discovered unique records: {len(records)}; screened: {len(quals)}; eligible not selected because of pilot limit: {len(pilot_left)}; scientifically excluded: {len(result['scientifically_excluded'])}; unresolved: {len(result['unresolved_screening'])}.",
            'Eligible contrary findings: '+(', '.join(result['eligible_contrary']) or 'none identified by screening; not evidence that none exist.'),
            '', '## Revised projection (provisional)', '```json',json.dumps({'projection':review['projection'],'problems':review['problems'],'accounts':review['accounts']},indent=2),'```',
            '', 'Full-text extraction remains untested. '+('Full text was obtained for at least one proposed paper.' if result['any_full_text_obtained'] else 'No full text was obtained: pause for the researcher decision; full-text extraction remains untested.'),
            '', 'Complete per-query yields, access failures/routes, screening fields and eligibility categories are in data/cp2_pilot_report.json.']
    (checkpoints.cp_dir(run.dir)/'CP2_pilot_table.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


def main(root,run_id,action):
    from .orchestrator import Run
    from .runtime_integrity import verify,sha
    from .runtime_identity import require_execution_context
    from .preflight import require_clean_endpoints
    from .retained_hold import blocking_holds
    root=Path(root);require_execution_context();require_clean_endpoints()
    verify(root,json.loads((root/'frozen_runtime_manifest.json').read_text()))
    run=Run(run_id);structured.RECORD=run.dir/'structured_output.json';model_record.RECORD=run.dir/'model_record.jsonl'
    assert run.budget.cap==50 and run.budget.review_points==[25,48] and not config.load('pipeline')['routing']['alternates']
    assert json.loads((run.dir/'input/runtime_pin.json').read_text())['manifest_sha256']==sha(root/'frozen_runtime_manifest.json')
    if blocking_holds(run.budget,root/'pilot_retained_hold_authorization.json'):raise ValueError('New unresolved hold; stop')
    auth=json.loads((root/'pilot_discovery_authorization.json').read_text());assert auth['run_id']==run_id and auth['stop_at']=='CP2'
    guide=json.loads((root/'docs/pilot7/cp1_scope_guide/approved_scope_guide.json').read_text())
    assert sha(root/'docs/pilot7/cp1_scope_guide/approved_scope_guide.json')==auth['scope_guide_sha256']
    assert not [x for x in (run.dir/'input/seeds.txt').read_text().splitlines() if x.strip()]
    if action=='audit':
        return {'state':run.state(),'effective_screening_batch_size':run.cfg['loops']['cq_batch_size'],
                'expected_screening_batch_size':auth.get('expected_screening_batch_size'),
                'spend_cap_usd':run.budget.cap,'review_points_usd':run.budget.review_points,
                'spent_usd':run.budget.spent(),'held_usd':run.budget.reserved(),
                'models':{a:{'provider':config.agent_model(a).provider,'model':config.agent_model(a).model,'max_tokens':config.agent_model(a).max_tokens} for a in ('A03-LM','A04-CQ')}}
    if auth.get('expected_screening_batch_size') is not None and run.cfg['loops']['cq_batch_size']!=auth['expected_screening_batch_size']:
        raise ValueError('Effective screening batch size differs from the sealed authorization; no dispatch')
    if action=='approve-cp1':
        assert run.state()['stage']=='cp1'
        if not checkpoints.approved(run.dir,'CP1'):
            write(checkpoints.cp_dir(run.dir)/'CP1_decision.json',decision(run,guide))
            checkpoints.approve(run.dir,'CP1',run.prov)
        return {'CP1':'approved by explicit researcher decision','P1':True,'eight_themes':True,'guide_sha256':auth['scope_guide_sha256']}
    if action=='report-cp2':
        assert run.state()['stage']=='cp2' and not checkpoints.approved(run.dir,'CP2')
        return report_cp2(run)
    assert action=='discover-to-cp2' and checkpoints.approved(run.dir,'CP1')
    if run.state()['stage'] not in ('cp1','search','qualify','expand','cp2'):raise ValueError('CP2-only boundary refused')
    if checkpoints.approved(run.dir,'CP2'):raise ValueError('CP2 is already approved; no further execution here')
    run.run(until='extract')
    if run.state()['stage']=='cp2' and 'CP2' in run.state().get('status',''):
        return report_cp2(run)
    return {'state':run.state(),'spent_usd':run.budget.spent(),'held_usd':run.budget.reserved()}
