import json

from litreview.agents import AGENTS
from litreview.agents.base import build_system_prompt, parse_json, prompt_version
from litreview.paths import AGENT_PROMPTS_DIR, SCHEMAS_DIR


def test_every_agent_has_prompt_and_schema():
    for spec in AGENTS.values():
        assert (AGENT_PROMPTS_DIR / spec.prompt_file).exists(), spec.prompt_file
        json.loads((SCHEMAS_DIR / spec.schema_file).read_text())


def test_system_prompt_includes_shared_rules():
    sp = build_system_prompt("A09-WRI")
    assert "Shared Core Rules" in sp and "Language Policy" in sp
    assert "Language Policy" not in build_system_prompt("A05-KE")


def test_prompt_versions_parse():
    for aid in AGENTS:
        assert prompt_version(aid) != "unknown"


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": 2} thanks') == {"a": 2}
