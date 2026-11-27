"""Execute exactly one reviewed reconciliation page, or quote FINAL offline."""
import json
import sys
from pathlib import Path

from litreview.orchestrator import Run
from litreview.synthesis_registry import fingerprint

PIN = '25fc19775a474a0f91d78067f4b03ddb40ad4976c24b819467cd0e0b22f5e9a6'
RUN = '20261123-214928'
TURNS = ['RECONCILE_1001','RECONCILE_1002','RECONCILE_1003']

def main(action):
    run = Run(RUN)
    data = run.dir/'data'
    plan = json.loads((data/'recovery/reconciliation_evidence_review/plan.json').read_bytes())
    if fingerprint(plan) != PIN:
        raise ValueError('reviewed plan fingerprint mismatch')
    approval = dict(approved=True, approved_by='researcher, explicit reconciliation-only decision',
                    job_tag='30edcaaf8d90ed14', plan_fingerprint=PIN, approved_turns=TURNS,
                    baseline_stage_usd=2.7465485, max_increment_usd=7.183020)
    if action == 'record':
        job, tag = run._synthesis_job()
        assert tag == approval['job_tag'] and job.registry.digest == plan['registry']
        assert all(job._committed('GROUP_G%04d'%i) for i in range(1,10))
        assert abs(run.budget.stage_committed('A07')-2.7465485)<1e-8
        assert len(run.budget.reservations())==5 and not job._committed('FINAL')
        for name, value in [('reconciliation_repair_plan.json',plan),('reconciliation_repair_approved.json',approval)]:
            existing = run.load(name)
            if existing is not None and existing != value:
                raise ValueError('existing authorization differs')
            run.save(name,value)
        print('Recorded researcher decision and verified the nine accepted groups.')
        return
    if run.load('reconciliation_repair_approved.json') != approval:
        raise ValueError('specific reconciliation authorization required')
    job, tag = run._synthesis_job()
    if action in TURNS:
        if any(not job._committed(t) for t in TURNS[:TURNS.index(action)]):
            raise ValueError('an earlier page is pending')
        job.reconcile(only_turn=action)
        page = job._committed(action)
        print(json.dumps(dict(page=action,reviews=len(page['reviews']),issues=len(page['issues']))))
    elif action == 'quote-final':
        assert all(job._committed(t) for t in TURNS) and not job._pending()
        from decimal import Decimal
        payload = {**job.final_payload(), 'cp_syn_researcher_decision':json.loads((run.dir/'checkpoints/CP_SYN_approved.json').read_bytes()),
                   'reviewed_organization_proposals':job._committed('PLAN')['theme_change_proposals']}
        tokens,limit,usd = run._a07_quote('FINAL',payload,job.count)
        print(json.dumps(dict(mode='FINAL',estimated_input=tokens,max_output=limit,hold_usd=str(Decimal(str(usd))*Decimal('1.30')),
                              payload_fingerprint=fingerprint(payload))))
    else:
        raise ValueError('unknown action')

if __name__=='__main__':
    main(sys.argv[1])

