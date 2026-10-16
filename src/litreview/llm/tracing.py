"""Optional LangSmith tracing of every model call.

Enabled when LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set in .env.
Each call appears in LangSmith as an LLM run named "<agent> · <model>" with token usage,
tagged with the run ID and pipeline step. If langsmith is not installed or tracing is off,
calls run untraced. Traces contain prompts and paper text — keep the project private.
"""
from __future__ import annotations

import os
from typing import Callable

from .base import LLMResponse


def enabled() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and bool(os.environ.get("LANGSMITH_API_KEY"))


def traced_call(fn: Callable[[], LLMResponse], *, name: str, provider: str, model: str,
                metadata: dict) -> LLMResponse:
    if not enabled():
        return fn()
    try:
        from langsmith import traceable
    except ImportError:
        return fn()

    @traceable(run_type="llm", name=name,
               metadata={**metadata, "ls_provider": provider, "ls_model_name": model},
               tags=[metadata.get("agent", ""), provider])
    def _run(**_inputs) -> dict:
        r = fn()
        return {"content": r.text, "stop_reason": r.stop_reason, "_response": r,
                "usage_metadata": {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                                   "total_tokens": r.input_tokens + r.output_tokens}}

    out = _run(agent=metadata.get("agent"), step=metadata.get("step"))
    return out["_response"]
