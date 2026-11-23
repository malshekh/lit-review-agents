"""One explicitly authorized A07 PLAN attempt; no later synthesis/writing dispatch."""
from __future__ import annotations
import hashlib
import json
import math
import os
from decimal import Decimal, ROUND_CEILING

from . import pilot_authorization as pilot, synthesis_bounded as bounded
from .orchestrator import Run, Pause
from .singlepaper_eval import WritingRun

VERSION = "a07-plan-adaptive-one-retry-v2"


class QuoteCaptured(Exception):
    pass


def upper(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError("Invalid PLAN quote")
    return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def authority(run, preparing=False):
    path = run.dir / "input/plan_retry_authority.json"
    if not path.exists():
        return None
    a = json.loads(path.read_text(encoding="utf-8"))
    if (a.get("version") != VERSION or a.get("run_id") != run.id
            or a.get("authorized_mode") != "PLAN" or a.get("max_attempts") != 1
            or a.get("max_tokens") != 32000 or a.get("explicit_thinking_enabled") is not True
            or a.get("thinking_mode") != "adaptive" or a.get("effort") != "medium"
            or "thinking_budget" in a
            or run.cfg["synthesis"]["output_limits"]["PLAN"] != 32000
            or run.cfg["synthesis"].get("plan_request") != {"thinking":{"type":"adaptive"},"effort":"medium"}
            or a.get("original_evaluation_baseline_usd") != 7.3163356):
        raise pilot.AuthorizationRequired("Invalid controlled PLAN-only authority")
    old = [e for e in run.budget.entries() if e.get("step") == a["original_failed_step"]]
    if len(old) != 1 or Decimal(str(old[0]["cost_usd"])) != Decimal("0.379385"):
        raise pilot.AuthorizationRequired("Original failed PLAN charge not preserved exactly once")
    if not preparing:
        if not a.get("allowed_step") or not a["allowed_step"].endswith("_PLAN"):
            raise pilot.AuthorizationRequired("Missing new PLAN identity")
        q, held = upper(a["cold_plan_usd"]), upper(a["reservation_with_margin_usd"])
        if q <= 0 or held < q * Decimal("1.30"):
            raise pilot.AuthorizationRequired("Full cold quote plus 30% margin required")
    return a


def projection(run, stage, candidate=None):
    a = authority(run)
    if stage != pilot.STAGE_1 or run.state()["stage"] != "synthesize":
        raise pilot.AuthorizationRequired("This authorization is PLAN only")
    if run.budget.reservations():
        raise pilot.AuthorizationRequired("Reconcile existing PLAN reservation before authorization")
    paid = [e for e in run.budget.entries() if e.get("step") == a["allowed_step"]]
    future = float(a["cold_plan_usd"]) if not paid else 0.0
    committed = 0.0
    if candidate:
        agent, committed = candidate
        if agent != "A07-SYN" or abs(committed-float(a["reservation_with_margin_usd"])) > 1e-8:
            raise pilot.AuthorizationRequired("Unapproved PLAN reservation")
        future = 0.0  # Candidate ALREADY includes margin; never charge it twice.
    out = pilot.admit(run.budget.spent(), committed, future)
    if Decimal(str(run.budget.spent()))-Decimal("7.3163356")+Decimal(str(committed))+Decimal(str(future))*Decimal("1.30") > 15:
        raise pilot.AuthorizationRequired("PLAN exceeds remaining $15 evaluation envelope")
    return {**out, "scope":stage, "authorized_mode":"PLAN", "max_attempts":1,
            "lines":[{"stage":"A07-SYN", "usd":future, "calls":int(bool(future)),
                      "basis":"BYTE_BOUND_COLD_1H_WRITE_FULL_OUTPUT"}],
            "projected_remaining_usd":1.3*future, "papers":1, "retry_share":0.0}


class PlanOnlyJob(bounded.RegistrySynthesisJob):
    def run(self):
        self.plan()
        # Existing native alignment-stop handling writes the job report without
        # declaring synthesis complete or dispatching a GROUP.
        raise bounded.AlignmentRequired("Authorized PLAN-only attempt accepted; stopped before GROUP/RECONCILE/FINAL")


class PlanRetryRun(WritingRun):
    def __init__(self, run_id, preparing=False):
        super().__init__(run_id)
        self.retry = authority(self, preparing=preparing)
        if self.retry is None:
            raise Pause("Controlled PLAN authority required")
        self.quote_only = preparing

    def _reserve(self, key, usd, agent_id, note="", steps=()):
        if agent_id != "A07-SYN" or len(steps) != 1 or not steps[0].endswith("_PLAN"):
            raise Pause("Only the controlled PLAN request is authorized")
        if self.quote_only:
            q = upper(usd)
            self.captured_quote = {"key":key,"step":steps[0],"cold_plan_usd":float(q),
                                   "reservation_with_margin_usd":float(upper(q*Decimal("1.30")))}
            return True, 15.0  # Offline only: agent() captures exact wire body and stops before dispatch.
        if list(steps) != [self.retry["allowed_step"]] or Decimal(str(usd)) > upper(self.retry["cold_plan_usd"]):
            raise Pause("PLAN identity/quote changed; fresh review required")
        total = float(self.retry["reservation_with_margin_usd"])
        if (Decimal(str(self.budget.spent()))-self.baseline+Decimal(str(self.budget.reserved()))+Decimal(str(total))) > 15:
            raise Pause("PLAN exceeds $15 sub-cap")
        # Native reserve enforces BOTH ceilings atomically; this amount includes
        # the complete 30% margin, not just an admission-only comparison.
        return Run._reserve(self,key,total,agent_id,"PLAN cold full-output quote plus 30% margin",steps,
                            margin_included=True)

    def agent(self, agent_id, payload, step, **kwargs):
        if agent_id != "A07-SYN" or payload.get("mode") != "PLAN":
            raise Pause("Only A07 PLAN is authorized, including during offline quote preparation")
        if self.quote_only:
            import dataclasses
            from .agents.base import build_system_prompt, user_parts
            from .llm.anthropic_client import message_params
            m = dataclasses.replace(self.route(agent_id), **(kwargs.get("overrides") or {}))
            trace = {"agent":agent_id,"step":step,"run_id":self.id,"attempt":0}
            body = message_params(build_system_prompt(agent_id),user_parts(payload,m.cache_payload),m.model,
                                  m.max_tokens,m.temperature,m.effort,m.cache_system,m.cache_ttl,trace)
            serialized = json.dumps(body,ensure_ascii=True,sort_keys=True,separators=(",", ":")).encode("ascii")
            byte_bound = len(serialized)+4096  # Whole wire body plus framing; never predicts thinking/output.
            if byte_bound+m.max_tokens > self.cfg["synthesis"]["context_ceiling_tokens"]:
                raise Pause("Serialized PLAN does not fit context ceiling")
            cold = self.budget.cost(m.model,0,m.max_tokens,0,0,byte_bound)
            q = max(upper(cold),upper(self.captured_quote["cold_plan_usd"]))
            self.captured_quote.update(cold_plan_usd=float(q),reservation_with_margin_usd=float(upper(q*Decimal("1.30"))),
                    input_byte_bound=byte_bound,serialized_request_bytes=len(serialized),framing_allowance_bytes=4096,
                    request_sha256=hashlib.sha256(serialized).hexdigest(),effective_parameters={"model":body["model"],
                    "max_tokens":body["max_tokens"],"thinking":body["thinking"],"output_config":body["output_config"]})
            raise QuoteCaptured()
        if agent_id != "A07-SYN" or payload.get("mode") != "PLAN" or step != self.retry["allowed_step"]:
            raise Pause("No other agent, mode or attempt is authorized")
        if (kwargs.get("overrides") or {}).get("max_tokens") != 32000:
            raise Pause("Unexpected PLAN output cap")
        return super().agent(agent_id,payload,step,**kwargs)

    def continue_evaluation(self):
        if self.state()["stage"] != "synthesize":
            raise Pause("PLAN-only retry requires synthesize stage")
        original = bounded.RegistrySynthesisJob
        bounded.RegistrySynthesisJob = PlanOnlyJob
        try:
            return super().continue_evaluation()
        finally:
            bounded.RegistrySynthesisJob = original


def install_one_dispatch(run):
    """Durable single-attempt guard at the paid-provider boundary, not at startup."""
    from .llm import router, anthropic_client
    original = router._PROVIDERS["anthropic"]
    marker = run.dir / "data/plan_retry_dispatch_intent.json"
    def guarded(**kwargs):
        trace = kwargs.get("trace") or {}
        if (trace.get("agent") != "A07-SYN" or trace.get("run_id") != run.id
                or trace.get("step") != run.retry["allowed_step"] or kwargs.get("max_tokens") != 32000):
            raise Pause("Provider boundary refused unauthorized request")
        body = anthropic_client.message_params(kwargs["system"],kwargs["user"],kwargs["model"],
                    kwargs["max_tokens"],kwargs["temperature"],kwargs.get("effort"),
                    kwargs.get("cache_system",False),kwargs.get("cache_ttl","5m"),trace)
        if body.get("thinking") != {"type":"adaptive"} or body.get("output_config") != {"effort":"medium"}:
            raise Pause("Only adaptive thinking / medium PLAN is authorized; no manual budget")
        raw = json.dumps(body,ensure_ascii=True,sort_keys=True,separators=(",", ":")).encode("ascii")
        if hashlib.sha256(raw).hexdigest() != run.retry.get("request_sha256"):
            raise Pause("Serialized PLAN differs from the financially approved request")
        try: fd = os.open(marker,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError: raise Pause("Controlled PLAN attempt already started; no automatic repeat")
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump({"version":VERSION,"step":trace["step"],"request_sha256":hashlib.sha256(raw).hexdigest(),
                       "max_tokens":32000,"thinking":{"type":"adaptive"},"effort":"medium","max_attempts":1},stream)
            stream.flush();os.fsync(stream.fileno())
        return original(**kwargs)
    def denied(**kwargs):
        raise Pause("No other paid provider is authorized for this PLAN attempt")
    router._PROVIDERS.update(anthropic=guarded,openai=denied,kimi=denied)


def report(run):
    a = authority(run)
    step = a["allowed_step"]
    rows = [e for e in run.budget.entries() if e.get("step") == step]
    receipt_path = run.dir / "outputs" / (step+".provider.receipt0.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
    rawpath = __import__("pathlib").Path(receipt["private_raw_response_path"]) if receipt.get("private_raw_response_path") else None
    raw = json.loads(rawpath.read_text(encoding="utf-8")) if rawpath and rawpath.exists() else {}
    usage = raw.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    tag = step.split("_job",1)[1].rsplit("_PLAN",1)[0]
    plan = run.dir / "data" / ("synthesis_job_"+tag) / "turns/PLAN.json"
    total = run.budget.spent()
    writing = total-float(run.baseline)
    return {"phase":"PLAN_ATTEMPT_FINISHED" if rows else "NO_SETTLED_MODEL_CALL",
            "run_id":run.id,"step":step,"thinking_configuration":{"type":"adaptive"},"effort":"medium","max_tokens":32000,
            "new_paid_calls_recorded":len(rows),"plan_accepted":plan.exists(),
            "stop_reason":raw.get("stop_reason"),"provider_usage":usage,
            "provider_reported_thinking_tokens":usage.get("thinking_tokens",details.get("thinking_tokens",details.get("reasoning_tokens"))),
            "provider_reported_text_tokens":usage.get("text_tokens",details.get("text_tokens")),
            "token_split_note":"Do not infer token counts from characters or subtract hidden non-text usage; missing provider fields remain null.",
            "content_blocks":[{"type":c.get("type"),"text_characters":len(c.get("text", "")),
                               "thinking_characters":len(c.get("thinking", ""))} for c in raw.get("content",[])],
            "call_cost_usd":sum(e["cost_usd"] for e in rows) if rows else None,
            "original_failed_charge_usd":.379385,"evaluation_spent_usd":round(writing,9),
            "remaining_subcap_usd":round(15-writing,9),"cumulative_spent_usd":round(total,9),
            "remaining_pilot_cap_usd":round(35-total,9),"active_reservations":run.budget.reservations(),
            "accepted_plan_path":str(plan) if plan.exists() else None,
            "provider_response_path":str(rawpath) if rawpath and rawpath.exists() else None,
            "state":run.state(),"later_modes_authorized":False}
