"""Validate a smoke response against the exact submitted shape, including its successful stop reason."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import jsonschema

VERSION=2

def schema_hash(schema: dict) -> str:
    # Retain v15's canonicalization so identical actual submitted schemas can be reused.
    return hashlib.sha256(json.dumps(schema,sort_keys=True).encode('utf-8')).hexdigest()

def inspect_response(provider: str, text: str, stop_reason: str | None, schema: dict, expected_hash: str) -> dict:
    errors=[]
    if schema_hash(schema)!=expected_hash:errors.append('submitted-schema hash mismatch')
    successful={'anthropic':{'end_turn'},'openai':{'stop'},'kimi':{'stop'}}
    if stop_reason not in successful.get(provider,set()):errors.append('unsuccessful or missing stop reason')
    try:
        value=json.loads(text)
        jsonschema.Draft202012Validator(schema).validate(value)
        if not isinstance(value,dict):errors.append('root is not an object')
    except (ValueError,TypeError,jsonschema.ValidationError,jsonschema.SchemaError) as exc:
        errors.append(type(exc).__name__+': '+str(exc).split('\n',1)[0][:200])
    return {'accepted':not errors,'validation_version':VERSION,'problems':errors,
            'submitted_schema_sha256':expected_hash,'stop_reason':stop_reason}

def receipt_evidence(path: Path, enrichment: dict | None=None) -> tuple[dict,dict]:
    raw=path.read_bytes(); receipt=json.loads(raw)
    digest=hashlib.sha256(raw).hexdigest()
    extra=(enrichment or {}).get(digest,{})
    schema=receipt.get('submitted_schema',extra.get('submitted_schema'))
    stop=receipt.get('stop_reason',extra.get('stop_reason'))
    if schema is None:
        return receipt,{'accepted':False,'validation_version':VERSION,'problems':['exact submitted schema unavailable'],
                        'receipt_sha256':digest}
    check=inspect_response(receipt['provider'],receipt['text'],stop,schema,receipt['schema_sha256'])
    if receipt.get('response_provider',receipt['provider'])!=receipt['provider'] or receipt.get('response_model',receipt['model'])!=receipt['model']:
        check['accepted']=False
        check['problems'].append('response provider/model differs from submitted request')
    check['receipt_sha256']=digest
    return receipt,check
