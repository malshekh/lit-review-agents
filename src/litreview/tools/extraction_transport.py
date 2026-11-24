"""Lossless A05-only nullable string transport; all scientific validation follows decoding."""
import copy,json
import jsonschema
from ..paths import SCHEMAS_DIR


def decode(output):
    wire=json.loads((SCHEMAS_DIR/"A05-KE.anthropic.schema.json").read_text(encoding="utf-8"))
    local=json.loads((SCHEMAS_DIR/"A05-KE.schema.json").read_text(encoding="utf-8"))
    # Full transport validation enforces zero-or-one arity; never discard extra values.
    jsonschema.validate(output,wire)
    changes=[]
    def walk(value,w,c,path):
        if c.get("type")==["string","null"] and w.get("type")=="array" and w.get("maxItems")==1:
            changes.append(path)
            return value[0] if value else None
        if isinstance(value,dict):
            return {k:walk(v,w.get("properties",{}).get(k,{}),c.get("properties",{}).get(k,{}),path+"."+k) for k,v in value.items()}
        if isinstance(value,list):
            return [walk(v,w.get("items",{}),c.get("items",{}),path+f"[{i}]") for i,v in enumerate(value)]
        return copy.deepcopy(value)
    return walk(output,wire,local,"$"),changes
