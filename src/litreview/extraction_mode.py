"""A05-only canonical ordinary JSON. No provider grammar; full scientific checks remain mandatory."""
from __future__ import annotations
import copy, hashlib, json
from pathlib import Path
import jsonschema
from . import config
from .paths import SCHEMAS_DIR

MODE = "ordinary_json_local_v1"
CONTRACT_VERSION = "A05-KE-canonical-0.9"
ACCEPTANCE_VERSION = 1


def active(agent_id="A05-KE"):
    mode=(config.load("pipeline").get("extraction") or {}).get("generation_mode", "anthropic_strict_legacy")
    if mode not in (MODE,"anthropic_strict_legacy"):
        raise ValueError("Unknown explicit A05 generation mode: "+str(mode))
    return agent_id=="A05-KE" and mode==MODE


def identity():
    shape=(SCHEMAS_DIR/"A05-KE.schema.json").read_bytes()
    return {"generation_mode": MODE if active() else "anthropic_strict_legacy",
            "contract_version":CONTRACT_VERSION,"canonical_schema_sha256":hashlib.sha256(shape).hexdigest(),
            "acceptance_version":ACCEPTANCE_VERSION,"provider_schema_submitted":False if active() else True}


def strict_object(text):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError("Duplicate JSON key: "+k)
            out[k]=v
        return out
    def nonfinite(value):raise ValueError("Non-finite JSON constant: "+value)
    try:
        value=json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)
        if not isinstance(value,dict):raise ValueError("Extraction root must be an object")
        return value
    except (ValueError,TypeError) as exc:
        raise jsonschema.ValidationError("Strict A05 JSON: "+str(exc)) from exc


def trusted_metadata(payload):
    record=payload.get("record") or {}
    sections=record.get("content") or {}
    level=payload.get("content_level")
    if not record.get("record_id") or level not in ("ABSTRACT","FULL_TEXT") or not sections:
        raise jsonschema.ValidationError("A05 needs trusted record ID, source level and supplied sections")
    access=payload.get("source_access") or {}
    reported_level=access.get("level",level)
    if reported_level!=level:raise jsonschema.ValidationError("Trusted retrieval level mismatch")
    # Retrieval availability is not a claim that figures or supplements were inspected.
    result={"level":level,"figure_images_inspected":False,
            "figure_legends_read":bool(access.get("figure_legends_read",False)),
            "supplements_inspected":bool(access.get("supplements_inspected",False))}
    if access.get("note") or access.get("meaning"):result["note"]=access.get("note") or access["meaning"]
    if level=="ABSTRACT" and (result["figure_legends_read"] or result["supplements_inspected"]):
        raise jsonschema.ValidationError("Abstract cannot establish legends/supplement access")
    return {"record_id":record["record_id"],"content_level":level,"source_access":result}


def accept(text,payload):
    from .agents.base import validate
    from .tools import span_check
    output=strict_object(text)
    trusted=trusted_metadata(payload)
    # Trusted facts may be omitted by the model, but contrary model claims fail rather than being concealed.
    for key,value in trusted.items():
        if key in output:
            if isinstance(value,dict):
                if not isinstance(output[key],dict):raise jsonschema.ValidationError("Invalid source-access object")
                for k,v in output[key].items():
                    if k in value and v!=value[k]:raise jsonschema.ValidationError("A05 contradicts trusted "+key+"."+k)
            elif output[key]!=value:raise jsonschema.ValidationError("A05 contradicts trusted "+key)
        output[key]=copy.deepcopy(value)
    validate("A05-KE",output)
    sections=payload["record"]["content"]
    if not isinstance(output.get("sections_inspected"),list):
        raise jsonschema.ValidationError("A05 needs explicit inspected section names")
    if not set(output["sections_inspected"])<=set(sections):
        raise jsonschema.ValidationError("A05 claims an unavailable section")
    gates=span_check.check_findings(output,sections)
    if any(not span_check.passed(g) for g in gates):
        raise jsonschema.ValidationError("A05 failed source span/location or reported quantity/unit check")
    for finding in output["findings"]:
        if not isinstance(finding.get("span_location"),dict) or not finding["span_location"].get("section"):
            raise jsonschema.ValidationError("A05 needs an explicit source section for each finding")
        section=finding["span_location"]["section"]
        if finding["span"] not in sections.get(section,""):
            raise jsonschema.ValidationError("A05 quotation is not an exact substring of its stated section")
        for premise in finding.get("premise_spans",[]):
            if not any(premise in t for t in sections.values()):raise jsonschema.ValidationError("Unlocated premise quotation")
    return output


def record_identity(run_dir):
    path=Path(run_dir)/"input/extraction_generation.json"
    value=identity();encoded=json.dumps(value,sort_keys=True).encode()
    value={**value,"fingerprint":hashlib.sha256(encoded).hexdigest()}
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))!=value:
        raise ValueError("A05 mode/contract changed: explicit audited continuation required")
    if not path.exists():path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")
    return value
