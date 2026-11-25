import copy,json
from pathlib import Path
import pytest
from litreview import approved_scope,orchestrator as orch,model_record,run_spec
from litreview.pilot7_discovery_continue import decision
from litreview.tools.literature import Record,SearchResult

ROOT=Path(__file__).resolve().parents[1]
GUIDE=json.loads((ROOT/'docs/pilot7/cp1_scope_guide/approved_scope_guide.json').read_text())
OUTLINE=json.loads((ROOT/'docs/pilot7/outline.json').read_text())

@pytest.fixture
def run(tmp_path,monkeypatch):
    monkeypatch.setattr(orch,'RUNS_DIR',tmp_path)
    monkeypatch.setattr(model_record,'RECORD',tmp_path/'models.jsonl')
    r=orch.Run('delivery');r.save_state({'stage':'cp1','profile':'pilot7','status':'READY','counters':{},'corpus_policy_fingerprint':'test'})
    r.save('spec_approved.json',{'researcher_decision':{'scope_guide':GUIDE}})
    r.save('spec.json',{'selection_criteria':{'inclusion':[],'exclusion':[{'criterion':'After relevance screening, deprioritize redundant studies only with a documented significance-based reason independent of result direction.'}],'exclusion_reason_vocabulary':['DUPLICATE','LOWER_SIGNIFICANCE_THAN_ALTERNATIVES']}})
    (r.dir/'input').mkdir(exist_ok=True);(r.dir/'input/outline.json').write_text(json.dumps(OUTLINE))
    return r

@pytest.mark.parametrize('agent',['A03-LM','A04-CQ','A08-OL','A09-WRI'])
def test_actual_agent_boundary_receives_guide_and_writers_receive_six_map(run,monkeypatch,agent):
    seen=[]
    def call(a,p,*args,**kwargs):seen.append(copy.deepcopy(p));return {'agent_id':a}
    monkeypatch.setattr(orch,'run_agent',call)
    for name in ('_require_projection','_check_worst_case_line','_spend_review','_context_actual','_receipt_save'):
        monkeypatch.setattr(run,name,lambda *a,**k:None)
    monkeypatch.setattr(run,'_receipt_reuse',lambda *a,**k:None)
    monkeypatch.setattr(run,'_context_check',lambda *a:{'input_counted':1,'input_byte_bound':1,'output_reserve':1,'step':'delivery'})
    run.agent(agent,{'mode':'PER_PAPER','record':{'record_id':'R1'}},'delivery-'+agent)
    p=seen[0]
    assert p['approved_scope_guide']['eligibility_routes']==GUIDE['eligibility_routes']
    assert p['approved_scope_guide']['search_rules']['candidate_papers_in_search_inputs'] is False
    if agent in ('A08-OL','A09-WRI'):
        assert p['six_heading_map']==GUIDE['six_heading_map']
        assert p['chapter_word_targets']['chapter_1']==800
    saved=run.load('agent_inputs/delivery-'+agent+'.json')
    assert saved['payload']==p


def test_outline_view_merges_writing_headings_but_preserves_eight_discovery_themes(run,monkeypatch):
    from litreview import bridge
    monkeypatch.setattr(bridge,'outline_payload',lambda *a:{})
    p=run._outline_payload({},[],{}, {},{},[])
    assert p['six_heading_map']==GUIDE['six_heading_map']
    writing=p['researcher_outline']
    assert len(writing['sections'])==8
    assert len([x for x in writing['sections'] if x.get('parent_section_id')])==6
    assert len(run_spec.framework_from_outline(OUTLINE)['primary_themes'])==8
    brief=run._outline_input()['researcher_outline']
    assert len(brief['sections'])==10
    written=[{'section_id':m['section_id'],'text_markdown':'x '*n} for m,n in zip(GUIDE['six_heading_map'],[200,400,200,300,200,300])]
    assert [x['written'] for x in run_spec.chapter_word_report(writing,written,lambda t:len(t.split()))]==[800,800]
    plan={'sections':[{k:m[k] for k in ('section_id','heading')} for m in GUIDE['six_heading_map']]}
    assert not approved_scope.heading_problems(run,plan)
    plan['sections'].pop();assert approved_scope.heading_problems(run,plan)


def test_cp1_decision_records_clarification_without_creating_cp2_approval(run):
    d=decision(run,GUIDE)
    assert d['selected_option_id']=='P1' and d['confirm_corpus_policy']
    criteria=d['edited_selection_criteria']
    assert 'Statistical significance and direction' in criteria['redundancy_policy']
    assert not criteria['exclusion']
    assert 'LOWER_SIGNIFICANCE_THAN_ALTERNATIVES' not in criteria['exclusion_reason_vocabulary']
    assert criteria['pilot_selection_policy']['eligible_unselected_code']=='ELIGIBLE_NOT_SELECTED_PILOT_LIMIT'
    assert '800 words per chapter' in d['answers_to_questions']['chapter_word_allocation']
    assert not (run.dir/'checkpoints/CP2_approved.json').exists()


def test_query_result_is_durable_and_reused_without_retrieval_repetition(run,monkeypatch):
    calls=[]
    def search(*args):
        calls.append(args)
        return SearchResult('pubmed','Q1','sensor',1,[Record('pubmed','Measured sensor study',pmid='123')])
    monkeypatch.setattr(orch,'search',search)
    plan={'query_families':[{'family_id':'Q1','purpose':'THEME','sources':['pubmed'],'section_ids':['S1.1'],'compiled':{'pubmed':'sensor'},'max_records':3}]}
    first=run._execute_plan(plan,{'pubmed':{}});second=run._execute_plan(plan,{'pubmed':{}})
    assert len(calls)==1 and first==second
    assert first[0]['section_ids']==['S1.1'] and first[0]['searched_at']


def test_open_registry_additions_allowed_but_identity_replacement_stops():
    old=[{'record_id':'R1','pmid':'1','doi':None,'in_fixed_corpus':None}]
    new=old+[{'record_id':'R2','pmid':'2','doi':'10/x','in_fixed_corpus':None}]
    assert approved_scope.registry_extension(old,new)
    bad=copy.deepcopy(new);bad[0]['pmid']='9';assert not approved_scope.registry_extension(old,bad)


def test_unknown_screening_details_stay_unknown():
    assert approved_scope.screening_details({'reason':'Not reported'})['evidence_role'] is None


def test_paper_can_inform_multiple_approved_themes_without_inventing_one(run):
    fw=run_spec.framework_from_outline(OUTLINE)
    q={'R1':{'record_id':'R1','disposition':'QUALIFIED','primary_theme_id':'T5','reason':json.dumps({'informs_themes':['T2','T5','T99']})}}
    approved_scope.extend_screened_themes(run,q,fw)
    assert q['R1']['themes']==['T2','T5']


def test_search_repair_retains_prior_successful_discovery_and_yields(run,monkeypatch):
    plans=iter([{'query_families':[]},{'query_families':[]}])
    monkeypatch.setattr(approved_scope,'search_plan',lambda *a,**k:next(plans))
    rows=[]
    for i in (1,2):
        record=Record('pubmed','Independent sensor '+str(i),pmid=str(i),query_family_id='Q'+str(i)).to_dict()
        rows.append([{'source':'pubmed','family_id':'Q'+str(i),'purpose':'THEME','query':'query'+str(i),'hit_count':1,'returned':1,'error':None,'records':[record]}])
    execution=iter(rows)
    monkeypatch.setattr(run,'_execute_plan',lambda *a:next(execution))
    monkeypatch.setattr(run,'_execution_report',lambda p,r,s:{'problems':[1] if r[0]['family_id']=='Q1' else [],'families':[],'seed_recall':[]})
    assert run.stage_search(run.state())=='qualify'
    assert len(run.load('records.json'))==2
    assert [r['family_id'] for r in run.load('search_log.json')]==['Q1','Q2']


def test_bounded_question_planning_merges_all_eight_without_resending_old_failure(run,monkeypatch):
    seen=[]
    def agent(a,p,step):
        seen.append((p,step));sid=p['planning_unit']['section_id']
        return {'agent_id':'A03-LM','prompt_version':'0.7','status':'COMPLETE','warnings':[],'limitations':[],
                'mode':p['mode'],'spec_version':'0.1','plan_version':'unit','concept_blocks':[],
                'query_families':[{'family_id':'Q1','purpose':'THEME','theme_or_position':sid,'section_ids':[sid],
                  'logic':'sensing and task','sources':['pubmed'],'routing_reason':'biomedical','compiled':[{'source':'pubmed','query':'sensor learning'}],
                  'context_blocks_applied':[],'filters':{'date_from':None,'date_to':None,'languages':[],'publication_types_excluded':[]},
                  'not_terms':[],'max_records':3,'expected_failure_modes':[]}],
                'citation_expansion_seed_families':['Q1'],'repairs':[],'seeds_not_recalled':[]}
    monkeypatch.setattr(run,'agent',agent)
    spec=run.load('spec_approved.json');budget={'max_records_total':150,'max_records_per_family':60}
    plan=approved_scope.search_plan(run,spec,{'pubmed':{}},budget)
    assert len(seen)==8 and len(plan['query_families'])==8
    assert len({f['family_id'] for f in plan['query_families']})==8
    assert all(len(p['researcher_outline']['sections'])==1 and p['budget']['max_records_total']==18 for p,step in seen)
    assert all(step!='A03-LM_plan' for p,step in seen)
    assert all('scope_guide' not in p['review_spec'].get('researcher_decision',{}) for p,step in seen)
    reports={'families':[{'family_id':f['family_id'],'returned':1,'error':None} for f in plan['query_families']]}
    # An unavailable source is preserved, not an excuse to repeat all paid unit plans.
    reports['families'][0].update(returned=0,error='SOURCE_UNAVAILABLE')
    approved_scope.search_plan(run,spec,{'pubmed':{}},budget,mode='REPAIR',execution=reports,repair_number=1)
    assert len(seen)==8


def test_duplicate_guide_copies_removed_without_losing_unique_rules_or_mutating_source(run):
    spec={'central_question':'unchanged','approved_scope_guide':copy.deepcopy(GUIDE),
          'researcher_decision':{'selected_option_id':'P1','scope_guide':copy.deepcopy(GUIDE)},
          'selection_criteria':{'rule':'Statistical significance must not decide eligibility.'},'researcher_outline':{'sections':['a']}}
    original=copy.deepcopy(spec)
    payload=approved_scope.enrich(run,'A04-CQ',{'review_spec':spec,'researcher_outline':{'sections':['a']}})
    assert payload['approved_scope_guide']==GUIDE and spec==original
    assert 'approved_scope_guide' not in payload['review_spec']
    assert 'scope_guide' not in payload['review_spec']['researcher_decision']
    assert payload['review_spec']['selection_criteria']==original['selection_criteria']
    other=copy.deepcopy(spec);other['approved_scope_guide']={'distinct':'retain'}
    assert approved_scope.enrich(run,'A04-CQ',{'review_spec':other})['review_spec']['approved_scope_guide']=={'distinct':'retain'}


@pytest.mark.parametrize("batch_size", [1, 4])
def test_screening_batch_override_is_at_the_effective_profile_level(batch_size):
    from litreview import config
    import yaml
    import copy
    pipeline=yaml.safe_load((ROOT/'config/pipeline.yaml').read_text(encoding='utf-8'))
    pipeline=copy.deepcopy(pipeline)
    pipeline['profiles']['pilot7'].setdefault('overrides',{}).setdefault('loops',{})['cq_batch_size']=batch_size
    effective=config._merge(pipeline,pipeline['profiles']['pilot7']['overrides'])
    assert effective['loops']['cq_batch_size']==batch_size
    assert effective['agents']['A04-CQ']['max_tokens']==pipeline['agents']['A04-CQ']['max_tokens']==16000
    assert effective['agents']['A04-CQ']['model']==pipeline['agents']['A04-CQ']['model']


def test_writing_dispatch_units_follow_plan_not_eight_themes(run, monkeypatch):
    from litreview import bridge
    writing=approved_scope.writing_outline(run,OUTLINE)
    ids=[s["section_id"] for s in writing["sections"]]
    assert len(ids)==8 and len([s for s in writing["sections"] if s.get("parent_section_id")])==6
    seen=[]
    monkeypatch.setattr(bridge,"writer_payload",lambda *args,**kwargs:{})
    monkeypatch.setattr(bridge,"check_section",lambda *args:[])
    def call(agent,payload,step,**kwargs):
        sid=step.split("_draft_",1)[1].rsplit("_r",1)[0];seen.append(sid)
        return {"status":"COMPLETE","section":{"section_id":sid,"heading":"Heading","text_markdown":"Organizing text."}}
    monkeypatch.setattr(run,"_admitted",call)
    ps={"plan":{"writing_order":ids},"packets":{sid:{} for sid in ids},"pv":"test-plan-version",
        "ev":"test-evidence","pkg":{},"findings":[],"amap":{},"journal":{}}
    assert len(run._write_sections(ps,"draft"))==8 and seen==ids


def test_outline_word_target_sizes_downstream_forecast_without_changing_units(run,monkeypatch):
    from litreview import config
    from litreview.tools import cost_projection as cp
    from litreview.tools import downstream_projection as dp
    seen=[];original=dp.requests
    def capture(route,cfg,n,inputs=None):
        seen.append(copy.deepcopy(inputs));return original(route,cfg,n,inputs)
    monkeypatch.setattr(dp,"requests",capture)
    p=cp.for_selection(cp.load_rates(),[{"record_id":"R1"}],run.dir,run.budget,config.agent_model,run.cfg)
    assert seen[0]["journal"]["limits"]["main_text_max_words"]==1600
    assert config.load("journal_scirev")["limits"]["main_text_max_words"]==5000
    a09=next(x for x in p["lines"] if x["stage"]=="A09-WRI")
    assert "8 sections assumed" in a09["detail"] and a09["calls"]==25
    assert cp._outline_words(run.dir)==1600


def test_access_cache_cannot_budget_wrong_publication_as_fulltext(run,monkeypatch):
    from litreview.tools.fulltext import FullTextUnavailable
    rec={"record_id":"R0115","pmid":"41324706","doi":"10.1007/s00216-025-06241-z",
         "pmcid":"PMC9421940","title":"Intended sensing publication","abstract":"Matched abstract."}
    run.save("retrieval_log.json",{"R0115":{"level_read":"FULL_TEXT","category":"FULL_TEXT_RETRIEVED"}})
    run.save("fulltext/R0115.json",{"Abstract":"Wrong article","Results":"Unrelated text"})
    def rejected(*a,**k):raise FullTextUnavailable("PMID mismatch")
    monkeypatch.setattr(orch,"fetch_verified_sections",rejected)
    entry=run._access_check(rec)
    assert entry["level_for_budget"]=="ABSTRACT" and entry["level_read"]=="ABSTRACT"
    assert run.load("identity_quarantine/R0115_access_cache.json")


def test_materialization_blocker_stops_before_extraction_source_handoff(run,monkeypatch):
    monkeypatch.setattr(run,"_access_check",lambda *a,**k:{"materialization_blocker":"Image-only Table 1"})
    with pytest.raises(orch.Pause,match="Image-only Table 1"):
        run._retrieve_discovered({"record_id":"R0078"})


def test_combined_stage_envelope_reports_excess_instead_of_clamping(run,monkeypatch):
    monkeypatch.setattr(run.budget,"reserved",lambda:.124671)
    monkeypatch.setattr(run.budget,"spent",lambda:2.0849717)
    a=run.accounts({"projected_remaining_usd":38.65,"lines":[]},{"total_usd":50.81})
    assert a["combined_maximum_exposure_usd"]>50 and a["unsettled_reservations_usd"]==.1247
