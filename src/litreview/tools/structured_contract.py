"""Provider-specific, fail-closed compatibility checks; JSON Schema validation remains local."""
from __future__ import annotations

import copy
import jsonschema


class SchemaCompatibilityError(ValueError):
    pass


def problems(schema: dict, provider: str) -> list[str]:
    """Walk actual schema positions, not arbitrary property names; resolve local refs and compositions."""
    if provider not in ('anthropic','openai'):
        return [f'unsupported structured-output provider: {provider}']
    errors=[]
    try:jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:errors.append('invalid JSON Schema: '+exc.message)
    def walk(node,path='$',refs=(),declared=frozenset()):
        if not isinstance(node,dict):
            errors.append(path+': boolean or unspecified schema is not a supported output shape');return
        ref=node.get('$ref')
        if ref:
            if ref != '#' and not ref.startswith('#/'):
                errors.append(path+': external reference unsupported');return
            if ref in refs:
                if provider=='anthropic':errors.append(path+': recursive reference unsupported by anthropic')
                return
            try:
                target=schema
                for part in ([] if ref == '#' else ref[2:].split('/')):target=target[part.replace('~1','/').replace('~0','~')]
            except (KeyError,TypeError):errors.append(path+': unresolved reference '+ref);return
            walk(target,path+'->'+ref,refs+(ref,))
        allowed={'type','properties','required','additionalProperties','items','anyOf','allOf','oneOf','enum','const','$ref','$defs','definitions','description','default','format','minItems'}
        for key in set(node)-allowed:
            errors.append(path+': unsupported keyword '+key+' for '+provider)
        if path=='$' and node.get('type')!='object' and '$ref' not in node:
            errors.append(path+': root must be an object')
        props=node.get('properties',{})
        known=declared|set(props)
        missing=set(node.get('required',[]))-known
        if missing:errors.append(path+': undeclared required fields '+','.join(sorted(missing)))
        types=node.get('type',[]); types=[types] if isinstance(types,str) else types
        if 'object' in types or 'properties' in node:
            if not props:errors.append(path+': unspecified/empty object; define useful fields explicitly')
            if node.get('additionalProperties') is not False:errors.append(path+': object closure must explicitly be false')
            if provider=='openai' and set(node.get('required',[]))!=set(props):
                errors.append(path+': openai strict output requires every property in required (model optionality explicitly)')
        if 'array' in types and not isinstance(node.get('items'),dict):errors.append(path+': array requires an item schema')
        unsupported={'oneOf','not','if','then','else','patternProperties','unevaluatedProperties','prefixItems','dependentRequired','dependentSchemas','contains'}
        if provider=='openai':unsupported.add('allOf')
        for k in unsupported & set(node):errors.append(path+': unsupported '+k+' for '+provider)
        if provider=='anthropic' and 'anyOf' in node and ({'type','properties','$ref'} & set(node)):
            errors.append(path+': anthropic anyOf cannot share shape keywords')
        branch_types=[set([n['type']] if isinstance(n.get('type'),str) else n.get('type',[])) for n in node.get('allOf',[]) if 'type' in n]
        if branch_types and not set.intersection(*branch_types):errors.append(path+': conflicting allOf types')
        if provider=='anthropic' and len(node.get('allOf',[]))>1 and any({'$ref','anyOf','allOf'} & set(n) for n in node['allOf']):
            errors.append(path+': unsupported anthropic allOf composition')
        for name,child in props.items():walk(child,path+'.'+name,refs)
        if isinstance(node.get('items'),dict):walk(node['items'],path+'[]',refs)
        for defs in ('$defs','definitions'):
            for name,child in node.get(defs,{}).items():walk(child,path+'.'+defs+'.'+name,refs)
        for key in ('anyOf','oneOf','allOf'):
            for i,child in enumerate(node.get(key,[])):walk(child,path+f'.{key}[{i}]',refs,known)
    walk(schema)
    return sorted(set(errors))


def require(schema: dict, provider: str) -> None:
    errors=problems(schema,provider)
    if errors:raise SchemaCompatibilityError('; '.join(errors))


def source_problems(schema: dict) -> list[str]:
    """Catch impossible required fields even in local-only branches omitted from the provider subset."""
    errors=[]
    def walk(node,path='$',inherited=frozenset()):
        if not isinstance(node,dict):return
        known=inherited|set(node.get('properties',{}))
        missing=set(node.get('required',[]))-known
        if missing:errors.append(path+': undeclared required fields '+','.join(sorted(missing)))
        for name,child in node.get('properties',{}).items():walk(child,path+'.'+name)
        if isinstance(node.get('items'),dict):walk(node['items'],path+'[]')
        for key in ('$defs','definitions'):
            for name,child in node.get(key,{}).items():walk(child,path+'.'+key+'.'+name)
        for key in ('anyOf','allOf','oneOf'):
            for i,child in enumerate(node.get(key,[])):walk(child,path+f'.{key}[{i}]',known)
        for key in ('if','then','else','not'):walk(node.get(key),path+'.'+key,known)
    walk(schema)
    return errors
