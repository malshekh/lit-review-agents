"""Identity and source-bound extraction invariants, complementary to schema and verbatim Gate 1."""
def check(output):
    problems=[]
    def ids(key,field):
        values=[x.get(field) for x in output.get(key,[])]
        if len(values)!=len(set(values)):problems.append('duplicate '+field)
        return set(values)
    entities=ids('entities','entity_id'); contexts=ids('contexts','context_id'); ids('findings','finding_id')
    for f in output.get('findings',[]):
        if f.get('subject_entity_id') not in entities:problems.append('unknown finding subject')
        if f.get('object_entity_id') is not None and f['object_entity_id'] not in entities:problems.append('unknown finding object')
        if f.get('context_id') not in contexts:problems.append('unknown finding context')
        if not str(f.get('span') or '').strip():problems.append('empty finding span')
        if f.get('origin')=='SAME_SOURCE_IMPLICIT' and (not f.get('premise_spans') or not f.get('bridge')):
            problems.append('implicit finding needs premise spans and bridge')
    access=output.get('source_access') or {}
    if access and access.get('level')!=output.get('content_level'):problems.append('source-access level mismatch')
    if output.get('content_level')=='ABSTRACT' and (access.get('figure_legends_read') or access.get('supplements_inspected')):
        problems.append('abstract cannot establish legends or supplement access')
    return problems
