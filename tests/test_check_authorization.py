import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from litreview import a05_functional,structured
from litreview.check_authorization import require

@pytest.fixture
def authorized(tmp_path,monkeypatch):
    reviewed=json.loads((Path(__file__).resolve().parents[1]/'docs/pilot7/a05_functional/prepared_plan.json').read_text())
    p=tmp_path/'docs/pilot7/a05_functional';p.mkdir(parents=True);(p/'prepared_plan.json').write_text(json.dumps(reviewed))
    auth={'run_id':'run','fingerprint':'reviewed','functional_cap_usd':0.594,'strict_cap_usd':0.118374,
          'baseline_spend_usd':0.0690631,'baseline_hold_usd':0.099409,'additional_cap_usd':0.712374,'smoke_cap_usd':1,'pilot_cap_usd':50}
    (tmp_path/'pilot_check_authorization.json').write_text(json.dumps(auth))
    values={'spent':0.0690631,'held':0.099409,'functional':0.594,'strict':0.118374}
    budget=SimpleNamespace(spent=lambda:values['spent'],reserved=lambda:values['held'])
    run=SimpleNamespace(id='run',budget=budget)
    monkeypatch.setattr(a05_functional,'fingerprint',lambda:'reviewed')
    monkeypatch.setattr(a05_functional,'smoke_spent',lambda b:values['spent'])
    monkeypatch.setattr(a05_functional,'plan',lambda b:{'functional_worst_case_usd':values['functional'],'strict_remaining_worst_case_usd':values['strict']})
    targets=[{**r,'already_verified':True} for r in reviewed['prior_successes_still_matching']]
    targets.extend({'schema_file':n,'schema_sha256':'new','already_verified':False} for n in reviewed['strict_checks_remaining'])
    monkeypatch.setattr(structured,'targets',lambda:targets)
    return run,tmp_path,values,targets


def test_authorized_ceiling_counts_all_historical_holds(authorized):
    run,root,values,targets=authorized
    require(run,root)
    assert run.budget.operational_ceiling==pytest.approx(0.8808461)

@pytest.mark.parametrize('change',['hold','functional_bound','strict_bound','spent','lost_success'])
def test_new_hold_cost_change_or_lost_approval_stops_before_dispatch(authorized,change):
    run,root,values,targets=authorized
    if change=='hold':values['held']+=0.001
    elif change=='functional_bound':values['functional']+=0.00001
    elif change=='strict_bound':values['strict']+=0.00001
    elif change=='spent':values['spent']+=0.712375
    else:targets[0]['already_verified']=False
    with pytest.raises(ValueError):require(run,root)
