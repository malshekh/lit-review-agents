"""Output-contract text generated from a JSON Schema, and the structured-output form of a schema.

`summary(schema)` is the one-line contract printed in an agent prompt under the schema's name. It is generated,
never hand-written: a prompt that describes a different contract from the schema its reply is validated against
is how the pilot's PLAN came back complete and unusable. tests/test_contracts.py fails when a prompt's contract
line differs from what the schema generates (`python -m litreview.tools.contract --write` regenerates them).

`for_structured_output(schema)` returns a copy a provider's structured-output feature can accept: the constraints
delegated to the complete local validator (length and count limits, patterns, numeric ranges, conditionals) are removed and listed.
No object closure or required field is invented; provider-specific checks reject incomplete contracts before dispatch. The provider then guarantees shape, types, required keys and enumerations; the complete schema is still applied
locally to every reply, so nothing the provider ignores goes unchecked.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

LEAF_KEYS = ("const", "enum", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "pattern")
UNENFORCED = ("minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
              "exclusiveMaximum", "pattern", "format", "multipleOf", "uniqueItems", "minProperties", "maxProperties",
              "if", "then", "else", "not", "dependentRequired", "dependentSchemas", "contains")
HEADER_RE = re.compile(r"^\*\*([A-Za-z0-9\-.]+\.schema\.json)\*\*\s*$")


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _walk(node: dict, path: str, out: list[str], when: str = "") -> None:
    if not isinstance(node, dict):
        return
    pre = f"{when}{path}"
    if node.get("required"):
        out.append(f"{pre} required={_j(node['required'])}")
    if node.get("additionalProperties") is False and node.get("properties") and path == "$":
        out.append(f"{pre} additionalProperties=false")
    for key in LEAF_KEYS:
        if key in node:
            out.append(f"{pre} {key}={_j(node[key])}")
    kind = node.get("type")
    if kind and "const" not in node and "enum" not in node and kind not in ("object", "array") \
            and not (isinstance(kind, list) and ({"object", "array"} & set(kind))):
        out.append(f"{pre} type={kind if isinstance(kind, str) else '|'.join(kind)}")
    for name, child in (node.get("properties") or {}).items():
        _walk(child, f"{path}.{name}", out, when)
    if isinstance(node.get("items"), dict):
        _walk(node["items"], f"{path}[]", out, when)
    for combinator in ("anyOf", "oneOf"):
        for n, option in enumerate(node.get(combinator) or [], 1):
            _walk(option, path, out, f"{when}[{combinator} option {n}] ")
    for part in node.get("allOf") or []:
        if "if" in part and "then" in part:
            cond = "; ".join(f"{path}.{k} {kk}={_j(vv)}" for k, v in (part["if"].get("properties") or {}).items()
                             for kk, vv in v.items())
            _walk(part["then"], path, out, f"{when}[when {cond}] ")
            if "else" in part:
                _walk(part["else"], path, out, f"{when}[unless {cond}] ")
        else:
            _walk(part, path, out, when)


def summary(schema: dict) -> str:
    out: list[str] = []
    _walk(schema, "$", out)
    return "; ".join(out)


def for_structured_output(schema: dict, provider: str = "anthropic") -> tuple[dict, list[str]]:
    """(schema with locally enforced constraints omitted; undefined/unsafe shapes fail closed, the JSON paths of what was removed)."""
    from .structured_contract import source_problems, SchemaCompatibilityError
    invalid = source_problems(schema)
    removed: list[str] = []

    def strip(node, path):
        if isinstance(node, list):
            return [strip(x, f"{path}[{i}]") for i, x in enumerate(node)]
        if not isinstance(node, dict):
            return node
        out = {}
        for k, v in node.items():
            if k in UNENFORCED:
                removed.append(f"{path}.{k}")
                continue
            if k in ("$schema", "title", "$id"):
                continue
            if k in ("properties", "$defs", "definitions"):
                out[k] = {name: strip(child, f"{path}.{name}") for name, child in v.items()}
            elif k == "allOf":
                kept = [strip(x, f"{path}.allOf[{i}]") for i, x in enumerate(v)]
                kept = [x for x in kept if x]
                if kept:
                    out[k] = kept
            else:
                out[k] = strip(v, f"{path}.{k}") if isinstance(v, (dict, list)) else v
        # Anthropic rejects enum + a list-valued type, even for a valid nullable string enum.
        # Encode exactly the same allowed values as typed branches; do not relax or drop an enum.
        if provider == "anthropic" and isinstance(out.get("type"), list) and "enum" in out:
            if set(out["type"]) != {"string", "null"} or set(out) - {"type", "enum", "description", "default"}:
                raise SchemaCompatibilityError(path + ": unsupported enum/type union; author explicit typed branches")
            values=out["enum"]
            if any(v is not None and not isinstance(v,str) for v in values):
                raise SchemaCompatibilityError(path + ": enum values do not match nullable string type")
            branches=[]
            strings=[v for v in values if v is not None]
            if strings:branches.append({"type":"string","enum":strings})
            if None in values:branches.append({"type":"null"})
            out={**{k:v for k,v in out.items() if k not in ("type","enum")},"anyOf":branches}
        if provider == "anthropic" and out.get("type") in (["string", "null"], ["null", "string"]):
            rest={k:v for k,v in out.items() if k!="type"}
            out={"anyOf":[{"type":"string",**rest},{"type":"null"}]}
        return out
    result = strip(copy.deepcopy(schema), "$")
    from .structured_contract import problems
    invalid += problems(result, provider)
    if invalid:raise SchemaCompatibilityError("; ".join(sorted(set(invalid))))
    return result, removed


def regenerate(prompt_text: str, schemas_dir: Path) -> tuple[str, list[str]]:
    """The prompt with every contract line (the line after a `**<name>.schema.json**` header) regenerated from its
    schema. Returns (text, the schema names whose line changed)."""
    lines = prompt_text.split("\n")
    changed = []
    for i, line in enumerate(lines[:-1]):
        m = HEADER_RE.match(line)
        if m and lines[i + 1].startswith("$"):
            schema = json.loads((Path(schemas_dir) / m.group(1)).read_text(encoding="utf-8"))
            new = summary(schema)
            if lines[i + 1] != new:
                lines[i + 1] = new
                changed.append(m.group(1))
    return "\n".join(lines), changed


def main(argv: list[str] | None = None) -> int:
    import argparse
    from ..paths import AGENT_PROMPTS_DIR, SCHEMAS_DIR
    ap = argparse.ArgumentParser(description="Check or regenerate the schema contract lines in the agent prompts.")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    stale = 0
    for prompt in sorted(AGENT_PROMPTS_DIR.glob("*.md")):
        text = prompt.read_text(encoding="utf-8")
        new, changed = regenerate(text, SCHEMAS_DIR)
        if changed:
            stale += len(changed)
            print(f"{prompt.name}: {'regenerated' if args.write else 'STALE'} {', '.join(changed)}")
            if args.write:
                prompt.write_text(new, encoding="utf-8")
    print("contracts match the schemas" if not stale else f"{stale} contract line(s) {'rewritten' if args.write else 'out of date'}")
    return 0 if (args.write or not stale) else 1


if __name__ == "__main__":
    raise SystemExit(main())
