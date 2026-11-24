import dataclasses
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from litreview import config, plan_retry as pr, synthesis_bounded as bounded
from litreview.llm import anthropic_client as anth, router
from litreview.agents import base
from litreview.llm.base import LLMResponse
from litreview.orchestrator import Run, Pause

pytestmark=pytest.mark.projection_guard


def test_adaptive_medium_request_has_no_manual_budget():
    body=anth.message_params("system","synthetic", "claude-opus-5",32000,0.3,effort="high",trace={"agent":"A07-SYN","step":"synthetic_PLAN"})
    assert body["thinking"]=={"type":"adaptive"} and "budget_tokens" not in body["thinking"]
    assert body["max_tokens"]==32000 and body["output_config"]=={"effort":"medium"}


def message():
    from anthropic.types import Message
    return Message.model_validate({"id":"synthetic","type":"message","role":"assistant",
      "model":"claude-opus-5","stop_reason":"max_tokens","stop_sequence":None,
      "content":[{"type":"thinking","thinking":"synthetic only","signature":"synthetic"},
                 {"type":"text","text":"{partial"}],
      "usage":{"input_tokens":100,"output_tokens":32000}})


@pytest.mark.parametrize("plan",[True,False])
def test_full_raw_preserved_only_for_plan(monkeypatch,plan,tmp_path):
    import copy
    original=config.load
    cfg=copy.deepcopy(original("pipeline"));cfg["providers"]["anthropic"]["plan_response_audit_dir"]=str(tmp_path)
    monkeypatch.setattr(config,"load",lambda name:cfg if name=="pipeline" else original(name))
    class Stream:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def get_final_message(self):return message()
    monkeypatch.setattr(anth,"_get_client",lambda:SimpleNamespace(messages=SimpleNamespace(stream=lambda **k:Stream())))
    out=anth.complete("system","synthetic","claude-opus-5",32000,.3,
        trace={"agent":"A07-SYN","run_id":"synthetic","step":"synthetic_PLAN" if plan else "synthetic_GROUP"})
    if plan:
        from pathlib import Path
        raw=json.loads(Path(out.raw_provider_response_path).read_text())
        assert [b["type"] for b in raw["content"]]==["thinking","text"]
        assert raw["usage"]["output_tokens"]==32000 and raw["stop_reason"]=="max_tokens"
        assert out.raw_provider_response is None
    else:assert out.raw_provider_response is None


def test_raw_saved_and_charge_recorded_before_truncation_rejection(tmp_path,monkeypatch):
    raw=message().model_dump(mode="json")
    private=tmp_path/"private";private.mkdir();full=private/"response.json";full.write_text(json.dumps(raw))
    out=LLMResponse("{partial","anthropic","claude-opus-5",100,32000,"max_tokens",
                    raw_provider_response_path=str(full),provider_response_metadata={"stop_reason":"max_tokens","usage":raw["usage"],"content_block_types":["thinking","text"]})
    monkeypatch.setattr(base,"complete",lambda *a,**k:out)
    charges=[]
    b=SimpleNamespace(check_priced=lambda *a:None,ensure_headroom=lambda *a:None,record=lambda *a,**k:charges.append((a,k)))
    prov=SimpleNamespace(agent_call=lambda *a,**k:None)
    model=dataclasses.replace(config.agent_model("A07-SYN"),max_tokens=32000)
    with pytest.raises(base.AgentError,match="truncated"):
        base.run_agent("A07-SYN",{"mode":"PLAN"},tmp_path,"synthetic_PLAN",b,prov,model=model,repair_limit=0,
                       truncation_retries=0)   # the controlled PLAN retry is authorized for exactly one attempt
    assert json.loads((tmp_path/"outputs/synthetic_PLAN.truncated0.json").read_text())["partial_output"]=="synthetic_PLAN.raw0.txt"
    saved=json.loads((tmp_path/"outputs/synthetic_PLAN.provider.receipt0.json").read_text())
    assert saved["private_raw_response_path"]==str(full) and json.loads(full.read_text())==raw and len(charges)==1
    assert not (tmp_path/"outputs/synthetic_PLAN.provider.raw0.json").exists()
    assert not (tmp_path/"outputs/synthetic_PLAN.json").exists()


def test_job_stops_immediately_after_plan():
    obj=pr.PlanOnlyJob.__new__(pr.PlanOnlyJob);calls=[]
    obj.plan=lambda:calls.append("PLAN")
    obj.group=lambda *a:pytest.fail("GROUP not allowed")
    with pytest.raises(bounded.AlignmentRequired,match="PLAN-only"):
        obj.run()
    assert calls==["PLAN"]


@pytest.mark.parametrize("mode",["GROUP","RECONCILE","FINAL"])
def test_agent_guard_rejects_other_modes(mode):
    r=pr.PlanRetryRun.__new__(pr.PlanRetryRun);r.retry={"allowed_step":"synthetic_PLAN"}
    with pytest.raises(Pause):r.agent("A07-SYN",{"mode":mode},"synthetic_PLAN",overrides={"max_tokens":32000})


def guard_run(tmp_path):
    (tmp_path/"data").mkdir()
    kwargs=provider_kwargs()
    body=anth.message_params(kwargs["system"],kwargs["user"],kwargs["model"],kwargs["max_tokens"],kwargs["temperature"],kwargs["effort"],False,"5m",kwargs["trace"])
    import hashlib
    digest=hashlib.sha256(json.dumps(body,ensure_ascii=True,sort_keys=True,separators=(",", ":")).encode("ascii")).hexdigest()
    return SimpleNamespace(dir=tmp_path,id="run",retry={"allowed_step":"synthetic_PLAN","request_sha256":digest})


def provider_kwargs():
    return dict(provider="anthropic",system="system",user="synthetic",model="claude-opus-5",max_tokens=32000,
                temperature=.3,effort="high",trace={"agent":"A07-SYN","step":"synthetic_PLAN","run_id":"run"})


@pytest.mark.parametrize("failure",[False,True])
def test_single_paid_dispatch_even_after_unknown_error(tmp_path,monkeypatch,failure):
    calls=[]
    def fake(**k):
        calls.append(1)
        if failure:raise OSError("Synthetic unknown outcome")
        return "saved"
    monkeypatch.setattr(router,"_PROVIDERS",{"anthropic":fake,"openai":fake,"kimi":fake})
    pr.install_one_dispatch(guard_run(tmp_path))
    if failure:
        with pytest.raises(OSError):router._PROVIDERS["anthropic"](**provider_kwargs())
    else:assert router._PROVIDERS["anthropic"](**provider_kwargs())=="saved"
    with pytest.raises(Pause,match="already started"):
        router._PROVIDERS["anthropic"](**provider_kwargs())
    assert len(calls)==1 and (tmp_path/"data/plan_retry_dispatch_intent.json").exists()
    with pytest.raises(Pause):router._PROVIDERS["openai"](**provider_kwargs())


def test_margin_reserved_once_not_twice(monkeypatch):
    r=pr.PlanRetryRun.__new__(pr.PlanRetryRun);r.quote_only=False;r.baseline=Decimal("7.3163356")
    r.retry={"allowed_step":"synthetic_PLAN","cold_plan_usd":1.624021,"reservation_with_margin_usd":2.111228}
    r.budget=SimpleNamespace(spent=lambda:7.6957206,reserved=lambda:0)
    calls=[]
    monkeypatch.setattr(Run,"_reserve",lambda self,key,usd,*a,**k:calls.append(usd) or (True,14))
    r._reserve("key",1.62402,"A07-SYN",steps=["synthetic_PLAN"])
    assert calls==[2.111228]
    r.budget.spent=lambda:21.3163356
    with pytest.raises(Pause,match="sub-cap"):
        r._reserve("key",1.62402,"A07-SYN",steps=["synthetic_PLAN"])
    assert len(calls)==1


def test_financial_projection_removes_candidate_before_margin(tmp_path):
    (tmp_path/"input").mkdir()
    a={"version":pr.VERSION,"run_id":"run","authorized_mode":"PLAN","max_attempts":1,"max_tokens":32000,
       "explicit_thinking_enabled":True,"thinking_mode":"adaptive","effort":"medium","original_evaluation_baseline_usd":7.3163356,
       "original_failed_step":"old","allowed_step":"synthetic_PLAN","cold_plan_usd":1.624021,
       "reservation_with_margin_usd":2.111228}
    (tmp_path/"input/plan_retry_authority.json").write_text(json.dumps(a))
    b=SimpleNamespace(entries=lambda:[{"step":"old","cost_usd":.379385}],spent=lambda:7.6957206,reservations=lambda:{})
    r=SimpleNamespace(dir=tmp_path,id="run",cfg={"synthesis":{"output_limits":{"PLAN":32000},"plan_request":{"thinking":{"type":"adaptive"},"effort":"medium"}}},budget=b,state=lambda:{"stage":"synthesize"})
    pending=pr.projection(r,"STAGE_1_AUTHORIZED")
    assert pending["retry_share"]==0 and pending["lines"][0]["calls"]==1
    candidate=pr.projection(r,"STAGE_1_AUTHORIZED",candidate=("A07-SYN",2.111228))
    assert candidate["uncommitted_future_usd"]==0
    assert candidate["projected_total_usd"]==pytest.approx(7.6957206+2.111228)


def test_plan_limits_and_post_pilot_caps():
    """The controlled PLAN keeps its approved request (32k, adaptive thinking, medium effort). Every other cap
    was resized after the pilot (2026-11-23): no call leaves less than 12k for thinking plus output, and no agent
    default is above 48k (the old 64k-128k defaults priced every worst case at an output nobody produced)."""
    new=config.load("pipeline")
    assert new["synthesis"]["output_limits"]=={"PLAN":32000,"GROUP":12000,"RECONCILE":16000,"FINAL":16000}
    assert new["synthesis"]["plan_request"]=={"thinking":{"type":"adaptive"},"effort":"medium"}
    assert new["scientific_verification"]["output_limits"]=={"LOCAL":16000,"GLOBAL":16000}
    caps={a:v["max_tokens"] for a,v in new["agents"].items()}
    assert max(caps.values())<=48000 and min(caps.values())>=12000
    assert all(new["agents"][a].get("effort")=="medium" for a in ("A07-SYN","A09-WRI","A10-RV"))
    assert "on" in new["notify"] and True not in new["notify"]


def test_token_split_is_not_inferred_from_block_characters(tmp_path,monkeypatch):
    private=tmp_path/"private";private.mkdir();raw=private/"raw.json"
    raw.write_text(json.dumps({"stop_reason":"max_tokens","usage":{"output_tokens":32000},
       "content":[{"type":"thinking","thinking":"short summary"},{"type":"text","text":"{}"}]}))
    directory=tmp_path/"run";(directory/"outputs").mkdir(parents=True)
    step="A07-SYN_jobsynthetic_PLAN"
    (directory/"outputs"/(step+".provider.receipt0.json")).write_text(json.dumps({"private_raw_response_path":str(raw)}))
    monkeypatch.setattr(pr,"authority",lambda r:{"allowed_step":step})
    r=SimpleNamespace(dir=directory,id="run",baseline=Decimal("7.3163356"),
        budget=SimpleNamespace(entries=lambda:[{"step":step,"cost_usd":.5}],spent=lambda:8.1957206,reservations=lambda:{}),state=lambda:{"stage":"synthesize"})
    result=pr.report(r)
    assert result["provider_reported_thinking_tokens"] is None
    assert result["provider_reported_text_tokens"] is None
    assert result["provider_usage"]["output_tokens"]==32000
    payload=json.loads(raw.read_text());payload["usage"]["output_tokens_details"]={"thinking_tokens":12000}
    raw.write_text(json.dumps(payload))
    result=pr.report(r)
    assert result["provider_reported_thinking_tokens"]==12000
    assert result["provider_reported_text_tokens"] is None  # Never subtract to invent a text count.


def test_plan_response_is_never_exported_to_external_tracing(monkeypatch):
    from litreview.llm import tracing
    monkeypatch.setattr(tracing,"traced_call",lambda *a,**k:pytest.fail("PLAN external tracing forbidden"))
    monkeypatch.setattr(router,"_PROVIDERS",{"anthropic":lambda **k:"private-result"})
    assert router.complete("anthropic",trace={"agent":"A07-SYN","step":"synthetic_PLAN"},model="claude-opus-5")=="private-result"


def test_actual_sdk_serializes_supported_opus5_parameters_without_network():
    import httpx2 as httpx
    from anthropic import Anthropic
    captured=[]
    def handle(request):
        wire=json.loads(request.content)
        captured.append(wire)
        assert wire["model"]=="claude-opus-5" and wire["max_tokens"]==32000
        assert wire["thinking"]=={"type":"adaptive"} and wire["output_config"]=={"effort":"medium"}
        assert "budget_tokens" not in json.dumps(wire)
        events=[{"type":"message_start","message":{"id":"synthetic-sdk","type":"message","role":"assistant",
                 "model":"claude-opus-5","content":[],"stop_reason":None,"stop_sequence":None,"usage":{"input_tokens":10,"output_tokens":0}}},
                {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}},
                {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"synthetic"}},
                {"type":"content_block_stop","index":0},
                {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":None},"usage":{"output_tokens":2}},
                {"type":"message_stop"}]
        data="".join("event: "+e["type"]+"\ndata: "+json.dumps(e)+"\n\n" for e in events)
        return httpx.Response(200,headers={"content-type":"text/event-stream"},content=data.encode())
    http=httpx.Client(transport=httpx.MockTransport(handle))
    client=Anthropic(api_key="synthetic-not-a-credential",http_client=http,max_retries=0)
    try:
        body=anth.message_params("system","synthetic","claude-opus-5",32000,.3,effort="high",
                    trace={"agent":"A07-SYN","step":"synthetic_PLAN"})
        with client.messages.stream(**body) as stream:
            result=stream.get_final_message()
        assert result.stop_reason=="end_turn" and len(captured)==1 and captured[0]["stream"] is True
    finally:client.close()
