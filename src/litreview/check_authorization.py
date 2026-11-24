"""Exact financial authorization for the already reviewed smoke and functional continuation."""
import json,math
from pathlib import Path
from . import a05_functional,structured


def require(run,root):
    auth=json.loads((Path(root)/'pilot_check_authorization.json').read_text(encoding='utf-8'))
    reviewed=json.loads((Path(root)/'docs/pilot7/a05_functional/prepared_plan.json').read_text(encoding='utf-8'))
    if auth['run_id']!=run.id or auth['fingerprint']!=a05_functional.fingerprint():
        raise ValueError('Reviewed functional identity changed; no dispatch')
    proposal=a05_functional.plan(run.budget)
    if not math.isclose(proposal['functional_worst_case_usd'],auth['functional_cap_usd'],abs_tol=1e-9):
        raise ValueError('Reviewed functional cost bound changed; no dispatch')
    expected={r['schema_file']:r for r in reviewed['prior_successes_still_matching']}
    if any(t['schema_file'] in expected and (t['schema_sha256']!=expected[t['schema_file']]['schema_sha256'] or not t['already_verified']) for t in structured.targets()):
        raise ValueError('One of the nine prior matching successes changed or disappeared')
    remaining=[t for t in structured.targets() if not t['already_verified']]
    if set(t['schema_file'] for t in remaining)-set(reviewed['strict_checks_remaining']):
        raise ValueError('Reviewed strict check list changed; no dispatch')
    if proposal['strict_remaining_worst_case_usd']>auth['strict_cap_usd']+1e-9:
        raise ValueError('Reviewed strict cost bound increased; no dispatch')
    actual=run.budget.spent()-auth['baseline_spend_usd']
    if actual>auth['additional_cap_usd']+1e-9:raise ValueError('Additional authorized spend exceeded')
    if not math.isclose(run.budget.reserved(),auth['baseline_hold_usd'],abs_tol=1e-9):
        raise ValueError('Existing holds changed or a new unresolved hold arose; stop')
    if a05_functional.smoke_spent(run.budget)+run.budget.reserved()>auth['smoke_cap_usd']+1e-9:
        raise ValueError('Cumulative smoke allowance exceeded')
    run.budget.operational_ceiling=min(auth['pilot_cap_usd'],auth['smoke_cap_usd'],
        auth['baseline_spend_usd']+auth['baseline_hold_usd']+auth['additional_cap_usd'])
    return auth
