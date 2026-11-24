import json
from pathlib import Path
from litreview import corpus_policy, evaluation_budget


def authority(path, prior_events=None, prior_ledgers=None):
    value = {"evaluation_id": "synthetic-evaluation", "reviewed_by": "Synthetic human", "cap_usd":35,
             "review_usd":25, "future_margin":.30, "prior_events":prior_events or [],
             "prior_ledgers":prior_ledgers or [], "new_independent_evaluation_approved":not bool(prior_ledgers)}
    Path(path).write_text(json.dumps(value),encoding="utf8")
    return Path(path)


def install(run):
    fp=corpus_policy.initialize(run.dir)
    path=authority(run.dir.parent/('authority-'+run.id+'.json'))
    (run.dir/'input/evaluation_budget.json').write_text(json.dumps(evaluation_budget.prepare(path)),encoding='utf8')
    run.save_state({**run.state(), "corpus_policy_fingerprint":fp})
    return fp
