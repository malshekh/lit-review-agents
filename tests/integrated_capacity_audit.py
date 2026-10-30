"""Offline integrated probe. Only new audit artifacts and temporary run state are written."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
from litreview import orchestrator as orch, config
from litreview.agents.base import build_system_prompt, user_parts
from litreview.synthesis_registry import offline_tokens
from litreview.llm.openai_compatible import chat_params
from litreview.llm.anthropic_client import message_params

OUTPUT = ROOT/'docs/integrated_validation'


def capture_handoffs(root, registry, package, manuscript, tables):
    old = orch.RUNS_DIR
    orch.RUNS_DIR = root/'runs'
    try:
        run = orch.Run('offline-integration')
        plan = {'sections': [{'section_id': 'S1', 'ordered_items': package['propositions']}],
                'display_items': [{'display_id': 'T1', 'kind': 'TABLE'}]}
        for name, value in [('manuscript_plan.json', plan), ('synthesis_approved.json', package),
                            ('selected_corpus.json', list(registry.records.values())),
                            ('rv_latest.json', {'findings': [], 'verification_execution': 'COMPLETE'})]:
            run.save(name, value)
        run._current = lambda: manuscript
        run._verification_current = lambda *a: True
        run._prose_vendors = lambda *a: frozenset({'anthropic'})
        rows = []
        class Captured(Exception): pass
        def capture(agent, payload, **kwargs):
            model = config.agent_model(agent)
            system = build_system_prompt(agent)
            user = user_parts(payload)
            if model.provider == 'anthropic':
                params = message_params(system,user,model.model,model.max_tokens,model.temperature,
                    effort=model.effort)
            else:
                params = chat_params(system,user,model.model,model.max_tokens,model.temperature,model.provider)
            rows.append({'agent':agent, 'input_byte_bound':offline_tokens(system)+offline_tokens(user),
                'output_allowance':model.max_tokens,'params':params})
            raise Captured()
        run.agent = capture
        for stage in (run.stage_outline, run.stage_draft, run.stage_review_loop, run.stage_finish_edit):
            try: stage({'counters':{}})
            except Captured: pass
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with gzip.open(OUTPUT/'handoff_requests.jsonl.gz','wt',encoding='utf-8') as f:
            for row in rows: f.write(json.dumps(row,ensure_ascii=False)+'\n')
        result = {'method':'actual stage payload builders; synthetic full-proposition plan; no model calls',
            'handoffs':[{k:v for k,v in r.items() if k!='params'} for r in rows],
            'source_items':len(package.get('source_items',{})),
            'propositions':len(package['propositions']), 'gaps':len(package['knowledge_gaps']),
            'reconciliation_issues':len(package.get('reconciliation',[])),
            'A07_status':package['status'], 'global_independence':package['global_independence']}
        (OUTPUT/'handoffs.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    finally: orch.RUNS_DIR = old


if __name__ == '__main__':
    p = ROOT/'tests/a10_capacity_simulation.py'
    source = p.read_text(encoding='utf-8')
    source = source.replace("output=ROOT/'docs/a10_capacity'", "output=ROOT/'docs/integrated_validation/a10'")
    source = source.replace('output.mkdir(exist_ok=True)', 'output.mkdir(parents=True,exist_ok=True)')
    source = source.replace('manuscript,tables=fixture(registry,synthesis)',
        'manuscript,tables=fixture(registry,synthesis)\n        capture_handoffs(root,registry,synthesis,manuscript,tables)')
    exec(compile(source,str(p),'exec'), {'__file__':str(p),'__name__':'__main__',
                                       'capture_handoffs':capture_handoffs})
