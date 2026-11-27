import copy,json
from pathlib import Path
from litreview.pilot7_semantics_continue import scientific_assessment,prepared,structure_only_repair,STEP


def response():
    r=json.loads((Path(__file__).parent/'fixtures/functional_v2/a06.json').read_text())
    r['warnings'] += ['LABEL_ASSESSMENT|E1|ENDOGENOUS_METABOLITE|UNSUPPORTED|The excerpt establishes proposed activity, not endogenous origin.',
                      'LABEL_ASSESSMENT|E4|APPROVED_DRUG|INSUFFICIENT_EVIDENCE|The excerpt gives no approval evidence.']
    return r


def test_independent_assessment_requires_three_findings_and_both_label_decisions():
    r=response();assert scientific_assessment(r)['accepted']
    for change in [lambda x:x['warnings'].pop(),lambda x:x['validations'].pop(),lambda x:x['validations'][0].update(disposition='DOES_NOT_ESTABLISH'),
                   lambda x:x['warnings'].__setitem__(-1,x['warnings'][-1].replace('INSUFFICIENT_EVIDENCE','SUPPORTED'))]:
        bad=copy.deepcopy(r);change(bad);assert not scientific_assessment(bad)['accepted']


def test_reviewed_payload_stays_exact():
    root=Path(__file__).resolve().parents[1]
    p,r=prepared(root)
    from litreview.source_semantics import digest
    assert digest(p)=='1cb1af9df9d9767aec4b22fc23fb3b97c64d509f12ca78a08efcb8e220259056'
    assert r['verification_plan']['a06_only_worst_case_usd']==0.37


def test_format_repair_cannot_change_scientific_dispositions(tmp_path):
    import pytest
    folder=tmp_path/'outputs';folder.mkdir();r=response()
    (folder/(STEP+'.raw0.txt')).write_text(json.dumps(r))
    (folder/(STEP+'.repair.audit.json')).write_text('{}')
    after=copy.deepcopy(r);after['validations'][0]['disposition']='DOES_NOT_ESTABLISH'
    (folder/(STEP+'.json')).write_text(json.dumps(after))
    with pytest.raises(ValueError,match='scientific assessment'):structure_only_repair(tmp_path)
    (folder/(STEP+'.json')).write_text(json.dumps(r));structure_only_repair(tmp_path)
