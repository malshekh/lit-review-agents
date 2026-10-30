"""Complete synthetic source/validation inputs for tests unrelated to provenance failures."""
import copy


def seed_sources(run, findings):
    records = run.load('selected_corpus.json', [])
    by_record = {}
    for f in findings:by_record.setdefault(f['record_id'], []).append(f)
    known = {r['record_id'] for r in records}
    records += [{'record_id':r} for r in by_record if r not in known]
    run.save('selected_corpus.json', records)
    for rid, fs in by_record.items():
        ext = {'record_id':rid, 'findings':[], 'entities':[], 'contexts':[]}
        validations = []
        for f in fs:
            local = f['finding_id'].split(':')[-1]
            span = f.get('span') or 'Synthetic evaluation source ' + f['finding_id']
            ctx = f.get('context_id') or local + 'C'
            ctx = ctx.split(':')[-1]
            ext['contexts'].append({'context_id':ctx,'fields':copy.deepcopy(f.get('context') or {})})
            ext['findings'].append({**copy.deepcopy(f), 'finding_id':local, 'span':span, 'context_id':ctx,
                'subject_entity_id':f.get('subject'), 'object_entity_id':f.get('object')})
            validations.append({'finding_id':local,'disposition':f.get('disposition','SUPPORTED'),
                'constraints':f.get('constraints',[]), 'plain_language_limit':f.get('plain_language_limit') or span})
        run.save(f'extractions/{rid}.json', ext)
        run.save(f'fulltext/{rid}.json', {'Results':'\n'.join(f['span'] for f in ext['findings'])})
        run._save_validation(rid, {'record_id':rid,'validations':validations})
    result = run._validated_findings(records)
    run.save('validated_findings.json', result)
    return result
