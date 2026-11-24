import hashlib
import json
import pytest
from litreview import structured
from litreview.budget import BudgetTracker
from litreview.retained_hold import blocking_holds

@pytest.fixture
def retained(tmp_path, monkeypatch):
    b=BudgetTracker(tmp_path)
    key="smoke-existing"
    assert b.reserve(key,0.019586,"smoke-test","uncertain")[0]
    receipt={"state":"DISPATCHED","reservation":key,"target":"A05-KE.schema.json"}
    p=tmp_path/"smoke_receipts"/(key+".json");p.parent.mkdir();p.write_text(json.dumps(receipt))
    row={"time":b.reservations()[key]["reserved_at"],"schema_file":receipt["target"],"provider":"anthropic",
         "model":"model","schema_sha256":"old","accepted":False,"error":"Error code: 400 request_old"}
    (tmp_path/"smoke_tests.jsonl").write_text(json.dumps(row)+"\n")
    auth={"run_id":tmp_path.name,"authorized_by":"researcher explicit chat","decision":"CONTINUE_WITH_UNRESOLVED_HOLD",
          "release_hold":False,"reservation":key,"receipt_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
          "held_usd":0.019586,"provider":"anthropic","model":"model","rejected_schema_sha256":"old","provider_request_id":"request_old"}
    a=tmp_path/"authorization.json";a.write_text(json.dumps(auth))
    monkeypatch.setattr(structured,"slim",lambda *args: ({},"new"))
    return b,a,p

def test_authorized_continuation_preserves_unknown_billing(retained):
    b,a,p=retained
    before=(b.reservations_path.read_bytes(),p.read_bytes(),b.entries())
    assert blocking_holds(b)==["smoke-existing"]
    assert blocking_holds(b,a)==[]
    assert b.reserved()==0.019586
    assert before==(b.reservations_path.read_bytes(),p.read_bytes(),b.entries())
    b.reserve("smoke-new",0.1,"smoke-test","uncertain")
    assert blocking_holds(b,a)==["smoke-new"]

@pytest.mark.parametrize("change",["missing_error","ambiguous","changed_receipt","changed_hold","wrong_run","release"])
def test_retained_authorization_fails_closed(retained,change):
    b,a,p=retained
    if change in ("wrong_run","release"):
        v=json.loads(a.read_text());v["run_id" if change=="wrong_run" else "release_hold"]="wrong";a.write_text(json.dumps(v))
    elif change=="changed_receipt":p.write_text("{}")
    elif change=="changed_hold":
        v=json.loads(b.reservations_path.read_text());v["smoke-existing"]["usd"]=0.02;b.reservations_path.write_text(json.dumps(v))
    else:
        log=p.parent.parent/"smoke_tests.jsonl";log.write_text("" if change=="missing_error" else log.read_text()*2)
    with pytest.raises(ValueError):blocking_holds(b,a)
    assert b.reserved()>0 and not b.entries()

def test_same_rejected_schema_cannot_repeat(retained,monkeypatch):
    b,a,p=retained;monkeypatch.setattr(structured,"slim",lambda *args: ({},"old"))
    with pytest.raises(ValueError,match="unchanged"):blocking_holds(b,a)
