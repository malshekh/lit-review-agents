"""Offline 5,000-word evaluation fixture, never a scientific manuscript or model call."""
import copy
import gzip
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from litreview import config
from litreview.agents.base import build_system_prompt,user_parts
from litreview.synthesis_registry import EvidenceRegistry,offline_tokens,fingerprint
from litreview.synthesis_bounded import RegistrySynthesisJob
from litreview.verification_job import VerificationJob
from litreview.llm.openai_compatible import chat_params
from litreview.tools import tags,verification_scope
from a07_capacity_simulation import workload
from test_synthesis_bounded import FixtureModel
from test_verification_job import ScriptedVerifier


def fixture(registry,package):
    props=package['propositions']
    def binding(record):
        prop=next((p for p in props if any(registry.record_of[e['finding_id']]==record for e in p['evidence'])),None)
        if prop:return prop['proposition_id']
        gap=next(g for g in package['knowledge_gaps'] if record in g.get('citation_record_ids',[]))
        return gap['gap_id']
    lines=[]
    for i in range(200):
        record=list(registry.records)[i%len(registry.records)]
        pid=binding(record)
        lines.append(' '.join(['Evaluation']*20+['fixture','occurrence',str(i),'only',f'[@{record}]'])+' ⟦'+pid+'⟧.')
    manuscript={'title':'Structural evaluation fixture','abstract':'Evaluation input only',
        'sections':[{'section_id':'S1','heading':'Evaluation introduction','text_markdown':' '.join(lines[:100])},
                    {'section_id':'S2','heading':'Evaluation conclusion','text_markdown':' '.join(lines[100:])}]}
    table={'kind':'TABLE','display_id':'T1','caption':'Structural comparative evidence table fixture',
        'columns':['Source','Model','Exposure','Finding'],'rows':[]}
    for i in range(12):
        record=list(registry.records)[i]
        pid=binding(record)
        table['rows'].append([f'[@{record}]','Evaluation model','Evaluation exposure','Evaluation input ⟦'+pid+'⟧'])
    return manuscript,[table]


def main():
    output=ROOT/'docs/a10_capacity'
    output.mkdir(exist_ok=True)
    cfg=config.load('pipeline')['scientific_verification']
    system=build_system_prompt('A10-RV')
    count=lambda p:offline_tokens(system)+offline_tokens(user_parts(p))
    model=config.agent_model('A10-RV')
    captures=[]
    with tempfile.TemporaryDirectory(prefix='a10-capacity-') as temp:
        root=Path(temp)
        registry=EvidenceRegistry(workload(120))
        synthesis=RegistrySynthesisJob(root/'a07',registry,FixtureModel(registry),offline_tokens,
            config.load('pipeline')['synthesis'],{'fixture':True},lambda *_:True).run()
        manuscript,tables=fixture(registry,synthesis)
        base=ScriptedVerifier()
        def call(mode,payload,name):
            out=base(mode,payload,name)
            params=chat_params(system,user_parts(payload),model.model,cfg['output_limits'][mode],model.temperature,model.provider)
            captures.append({'mode':mode,'name':name,'input_upper_tokens':count(payload),
                'output_allowance':cfg['output_limits'][mode],'response_upper_tokens':offline_tokens(out),
                'params':params,'request_sha256':fingerprint(params)})
            return out
        j=VerificationJob(root/'a10',manuscript,{},synthesis,registry,tables,cfg,call,count,{'prompt':system})
        report=j.run('DRAFT')
        first=list(captures)
        captures.clear()
        edited=copy.deepcopy(manuscript)
        edited['sections'][1]['text_markdown']=edited['sections'][1]['text_markdown'].replace('Evaluation','ChangedEvaluation',1)
        second=VerificationJob(root/'a10-edit',edited,{},synthesis,registry,tables,cfg,call,count,{'prompt':system},
            cache_directory=j.cache_dir,prior_report=report)
        after=second.run('FINAL')
        revised=list(captures)
        findings=[{**f,'context':registry.contexts.get(f.get('context_id'))} for f in registry.findings.values()]
        full,index,_=verification_scope.scope(manuscript,{},synthesis,findings)
        legacy={'pass':'DRAFT','manuscript':manuscript,'manuscript_plan':{},'synthesis_package':synthesis,
                'validated_findings':full,'contradiction_index':index,'deterministic_report':{},'changed_passages':None}
        old_prompt=(ROOT/'docs/a10_capacity/legacy_system_prompt.txt').read_text(encoding='utf-8')
        old_input=offline_tokens(old_prompt)+offline_tokens(user_parts(legacy))
        def metrics(calls):
            inp=sum(c['input_upper_tokens'] for c in calls);cap=sum(c['output_allowance'] for c in calls)
            prices=config.load('prices')[model.model]
            return {'calls':dict(Counter(c['mode'] for c in calls)),'total_calls':len(calls),
                'input_upper_tokens':inp,'output_allowance':cap,'max_input_plus_output':max(c['input_upper_tokens']+c['output_allowance'] for c in calls),
                'cost_input_bytes_div3_output25pct':(inp/3*prices['input']+cap*.25*prices['output'])/1e6,
                'cost_all_input_byte_bound_all_output_caps':(inp*prices['input']+cap*prices['output'])/1e6,
                'per_request':[{k:v for k,v in c.items() if k!='params'} for c in calls]}
        result={'method':'offline production request builders; UTF8-byte input upper bounds, mocked judgments; no provider token counts or paid calls',
            'papers':len(registry.records),'findings':len(registry.findings),'word_count':sum(len(tags.strip_tags(s['text_markdown']).split()) for s in manuscript['sections']),
            'occurrences':len(j.occurrences),'table_occurrences':sum(o['path'][0]=='built_tables' for o in j.occurrences),
            'coverage':report['coverage'],'global_finding_coverage':len(set(registry.findings)&set(report['global_index_ids_reviewed'])),
            'status':report['verification_execution'],'first':metrics(first),'one_edit':metrics(revised),
            'legacy_same_fixture_input_upper':old_input,'legacy_output_allowance':config.agent_model('A10-RV').max_tokens,
            'single_edit_coverage':after['coverage'],'unchanged_A07_registry':registry.digest}
        (output/'measurements.json').write_text(json.dumps(result,indent=2)+'\n')
        with gzip.open(output/'requests.jsonl.gz','wt',encoding='utf-8') as f:
            for phase,calls in [('first',first),('one_edit',revised)]:
                for c in calls:f.write(json.dumps({'phase':phase,**c},ensure_ascii=False)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ('first','one_edit')},indent=2),flush=True)
        print(json.dumps({key:{k:v for k,v in result[key].items() if k!='per_request'} for key in ('first','one_edit')},indent=2))


if __name__=='__main__':main()
