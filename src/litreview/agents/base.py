"""Run one agent call: build the prompt, call the model, parse and validate JSON, log cost and provenance.

System prompt = prompts/shared/core_rules.md
              + prompts/shared/language_policy.md   (writing-side agents only)
              + prompts/agents/<agent>.md
User message  = the task payload as JSON.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from .. import config
from ..budget import BudgetTracker
from ..llm import complete
from ..paths import AGENT_PROMPTS_DIR, SCHEMAS_DIR, SHARED_PROMPTS_DIR
from ..provenance import ProvenanceLog
from .registry import AGENTS


class AgentError(RuntimeError):
    pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def prompt_version(agent_id: str) -> str:
    text = _read(AGENT_PROMPTS_DIR / AGENTS[agent_id].prompt_file)
    m = re.search(r"Version:\s*([0-9.]+)", text)
    return m.group(1) if m else "unknown"


def build_system_prompt(agent_id: str) -> str:
    spec = AGENTS[agent_id]
    parts = [_read(SHARED_PROMPTS_DIR / "core_rules.md")]
    if spec.uses_language_policy:
        parts.append(_read(SHARED_PROMPTS_DIR / "language_policy.md"))
    parts.append(_read(AGENT_PROMPTS_DIR / spec.prompt_file))
    return "\n\n---\n\n".join(parts)


def parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating Markdown fences or stray text around it."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def validate(agent_id: str, output: dict) -> None:
    schema_path = SCHEMAS_DIR / AGENTS[agent_id].schema_file
    schema = json.loads(_read(schema_path))
    jsonschema.validate(output, schema)


def run_agent(agent_id: str, payload: dict, run_dir: Path, step: str,
              budget: BudgetTracker, provenance: ProvenanceLog) -> dict:
    """Call an agent and return its validated JSON output. Output is saved to runs/<id>/outputs/."""
    if agent_id not in AGENTS:
        raise AgentError(f"Unknown agent {agent_id}")
    m = config.agent_model(agent_id)
    budget.check_priced(m.model)
    max_repairs = int(config.load("pipeline")["loops"].get("max_json_repair_attempts", 1))

    system = build_system_prompt(agent_id)
    user = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))   # compact: large payloads near context limits
    out_dir = Path(run_dir) / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{step}.json"

    last_error = ""
    for attempt in range(max_repairs + 1):
        budget.ensure_headroom()
        message = user if attempt == 0 else (
            user + "\n\nYour previous reply was not valid against the required output schema:\n"
            + last_error + "\nReturn only the corrected JSON object.")
        try:
            resp = complete(m.provider, system=system, user=message, model=m.model,
                            max_tokens=m.max_tokens, temperature=m.temperature, effort=m.effort,
                            trace={"agent": agent_id, "step": step, "run_id": Path(run_dir).name,
                                   "attempt": attempt, "prompt_version": prompt_version(agent_id)})
        except Exception as exc:  # noqa: BLE001 — any provider/API error fails the run cleanly, with a status
            provenance.agent_call(agent_id, step, m.model, prompt_version(agent_id), "", "FAILED")
            raise AgentError(f"{agent_id} ({step}): API error: {type(exc).__name__}: {str(exc)[:400]}") from exc
        for model, tin, tout in resp.usage_parts or [(resp.model, resp.input_tokens, resp.output_tokens)]:
            budget.record(agent_id, resp.provider, model, tin, tout, step=step)
        (out_dir / f"{step}.raw{attempt}.txt").write_text(resp.text, encoding="utf-8")
        if resp.stop_reason == "refusal":
            # a policy decline, not a formatting error: re-asking for JSON would only spend money
            provenance.agent_call(agent_id, step, resp.model, prompt_version(agent_id), "", "REFUSED")
            raise AgentError(
                f"{agent_id} ({step}): {resp.model} declined the request (safety classifier category: "
                f"{resp.refusal_category or 'unspecified'}), after any configured fallback. Rephrasing the "
                "topic or notes, or moving this agent to another model in config/pipeline.yaml, may help.")
        if resp.stop_reason in ("max_tokens", "length"):
            last_error = "Output was truncated at max_tokens. Increase max_tokens in config/pipeline.yaml."
            break
        try:
            output = parse_json(resp.text)
            validate(agent_id, output)
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            last_error = str(exc)[:2000]
            continue
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        provenance.agent_call(agent_id, step, m.model, prompt_version(agent_id),
                              str(out_file.relative_to(run_dir)), output.get("status", "UNKNOWN"))
        return output

    provenance.agent_call(agent_id, step, m.model, prompt_version(agent_id), "", "FAILED")
    raise AgentError(f"{agent_id} ({step}) failed: {last_error}")
