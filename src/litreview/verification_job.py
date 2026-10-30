"""Bounded A10 verification over A07's registry; no second evidence store.

Every nonempty reader-facing text occurrence is reviewed, including uncited text.
Classification/entailment remain model judgments, never inferred from tag validity.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import jsonschema

from . import evidence
from .paths import SCHEMAS_DIR
from .synthesis_registry import canonical, fingerprint, offline_tokens, compact_proposition
from .synthesis_job import JobStopped
from .tools import tags, verification_scope as scope

CHECKS = ['SOURCE', 'NUMBERS_UNITS', 'MECHANISM_CAUSALITY', 'CERTAINTY', 'CHEMICAL_IDENTITY',
          'MODEL_GBM', 'CLINICAL_REACH', 'COUNTER_EVIDENCE', 'ATTRIBUTION_INDEPENDENCE', 'CITATION']
SURFACES = ('title', 'abstract', 'sections', 'introduction', 'conclusion', 'keywords',
            'figure_legends', 'table_captions', 'captions', 'legends', 'tables', 'display_items')
META = {'section_id', 'display_id', 'item_id', 'kind', 'type', 'origin', 'level', 'path',
        'source_proposition_ids', 'proposition_ids', 'citation_record_ids', 'warnings'}


def inventory(manuscript, tables=()):
    """Conservative text inventory: no heuristic may discard a scientific assertion.

    Sentences/cells are review units, not a claim of perfect linguistic atomization.
    Offsets and paths distinguish identical tags/text at different occurrences.
    """
    out = []
    def walk(obj, path):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key not in META and not key.endswith(('_ids', '_id')):
                    walk(value, path + [key])
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):walk(value, path + [i])
        elif isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
            text = str(obj)
            start = 0
            ordinal = 0
            boundaries = list(re.finditer(r'(?<=[.!?])\s+(?!⟦)|(?<=⟧)\s+|\n+', text))
            for match in [*boundaries, None]:
                end = match.start() if match else len(text)
                raw = text[start:end]
                if raw.strip():
                    oid = 'OC-' + fingerprint({'path': path, 'ordinal': ordinal, 'text': raw})[:20]
                    ids = [i.strip() for m in tags.TAG_RE.finditer(raw) for i in m.group(1).split(',') if i.strip()]
                    out.append({'occurrence_id': oid, 'path': path, 'start': start, 'end': end,
                                'ordinal':ordinal,
                                'text': raw, 'item_ids': sorted(set(ids)-{'ORG'}),
                                'citation_record_ids': tags.cited_records(raw)})
                    ordinal += 1
                if match:start = match.end()
    for key in SURFACES:
        if key in manuscript:walk(manuscript[key], ['manuscript', key])
    walk(list(tables), ['built_tables'])
    roots={'manuscript':manuscript,'built_tables':list(tables)}
    for o in out:
        path=o['path']
        if 'rows' not in path:continue
        pos=path.index('rows')
        table=roots
        for key in path[:pos]:table=table[key]
        row=table['rows'][path[pos+1]]
        text=canonical(row)
        o['citation_record_ids']=sorted(set(o['citation_record_ids'])|set(tags.cited_records(text)))
        o['item_ids']=sorted(set(o['item_ids'])|{i.strip() for m in tags.TAG_RE.finditer(text)
                                               for i in m.group(1).split(',') if i.strip() and i.strip()!='ORG'})
        o['surface_context']={'caption':table.get('caption'),'columns':table.get('columns',[]),'row':row}
    return out


def version(manuscript, plan, package, registry, tables=()):
    return fingerprint({'manuscript': manuscript, 'plan': plan, 'synthesis': package,
                        'registry': registry.digest, 'tables': list(tables)})


def policy_hash(cfg):
    from .agents.base import build_system_prompt
    return fingerprint({'prompt':build_system_prompt('A10-RV'),'settings':cfg,
                        'schema':(SCHEMAS_DIR/'A10-RV.bounded.schema.json').read_text(),
                        'implementation':Path(__file__).read_text(encoding='utf-8')})


def current(report, digest, policy=None):
    identity_ok = (report.get('verification_fingerprint') == digest and not report.get('stale')
            and report.get('verification_execution') == 'COMPLETE'
            and (policy is None or report.get('verification_policy_fingerprint')==policy))
    if not identity_ok:return False
    occurrences = report.get('occurrence_inventory', [])
    verdicts = report.get('verdicts', [])
    coverage = report.get('coverage', {})
    ids = [o.get('occurrence_id') for o in occurrences]
    reviewed = [v.get('occurrence_id') for v in verdicts]
    global_ids = report.get('global_index_ids_reviewed', [])
    return (bool(ids) and None not in ids and len(ids)==len(set(ids))
            and len(reviewed)==len(ids) and set(reviewed)==set(ids)
            and coverage.get('occurrences_total')==len(ids)
            and coverage.get('occurrences_reviewed')==len(ids)
            and coverage.get('inventory_fingerprint')==fingerprint(occurrences)
            and len(global_ids)==len(set(global_ids))
            and coverage.get('global_index_entries_reviewed')==len(global_ids)
            and all(v.get('verdict')=='NON_SCIENTIFIC' or set(v.get('checks',[]))==set(CHECKS)
                    for v in verdicts))


class VerificationJob:
    def __init__(self, directory, manuscript, plan, package, registry, tables, cfg, call, count,
                 execution_identity, cache_directory=None, prior_report=None):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manuscript, self.plan, self.package, self.registry = manuscript, plan, package, registry
        self.tables, self.cfg, self.call, self.count = list(tables), cfg, call, count
        self.occurrences = inventory(manuscript, tables)
        if not self.occurrences:raise JobStopped('empty verification inventory')
        self.digest = version(manuscript, plan, package, registry, tables)
        self.inventory_hash = fingerprint(self.occurrences)
        self.policy = policy_hash(cfg)
        # Local results may survive an unrelated edit, but never evidence/plan/prompt/settings changes.
        self.dependencies = fingerprint({'registry': registry.digest, 'package': package, 'plan': plan,
                                         'settings': cfg, 'execution': execution_identity,'policy':self.policy})
        self.identity = fingerprint([self.digest, self.dependencies])
        self.cache_dir = Path(cache_directory) if cache_directory else self.dir / 'cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        ipath = self.dir / 'identity.json'
        if ipath.exists() and json.loads(ipath.read_text())['identity'] != self.identity:
            raise JobStopped('stale A10 job: manuscript or verification dependencies changed')
        self.atomic(ipath, {'identity': self.identity})
        self.idx = scope._index(package, plan)
        self.evidence_idx = evidence._named(package, plan)
        self.by_occurrence = {o['occurrence_id']: o for o in self.occurrences}
        self.metrics, self.code_flags = [], []
        prior_path = self.dir / 'prior_report.json'
        if prior_path.exists():prior_report=json.loads(prior_path.read_text(encoding='utf-8'))
        else:
            prior_report=prior_report or {}
            self.atomic(prior_path,{k:prior_report[k] for k in ('verification_fingerprint','occurrence_inventory','findings') if k in prior_report})
        old_paths = {o['occurrence_id']:o['path'] for o in prior_report.get('occurrence_inventory', [])}
        self.prior_fingerprint = prior_report.get('verification_fingerprint')
        self.corrections = [{**i,'prior_paths':[old_paths[oid] for oid in i.get('occurrence_ids', []) if oid in old_paths]}
                            for i in prior_report.get('findings', [])]

    @staticmethod
    def atomic(path, obj):
        tmp = path.with_suffix('.tmp')
        tmp.write_text(canonical(obj), encoding='utf-8')
        os.replace(tmp, path)

    def cap(self, mode):return self.cfg['output_limits'][mode]

    def admitted(self, mode, payload):
        if 'retrieved_evidence' not in payload:
            payload={**payload,'retrieved_evidence':{**self.registry.details([]),'source_items':{},'propositions':[]}}
        return self.count(payload) + self.cap(mode) <= self.cfg['context_ceiling_tokens']

    def turn(self, mode, name, payload):
        digest = fingerprint({'identity': self.identity, 'payload': payload, 'mode': mode})
        path = self.dir / f'{name}.json'
        if path.exists():
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved['request'] != digest or fingerprint(saved['output']) != saved['sha256']:
                raise JobStopped('A10 accepted response hash mismatch')
            return saved['output']
        if not self.admitted(mode, payload):raise JobStopped(f'A10 {name}: context admission exceeded')
        out = self.call(mode, payload, name)
        schema = json.loads((SCHEMAS_DIR / 'A10-RV.bounded.schema.json').read_text())
        try:jsonschema.validate(out, schema)
        except jsonschema.ValidationError as exc:raise JobStopped('A10 invalid/incomplete response: '+exc.message) from exc
        if out['mode'] != mode:raise JobStopped('A10 response mode mismatch')
        if offline_tokens(out) > self.cap(mode):raise JobStopped('A10 response exceeds output allowance')
        if out['status'] == 'NEEDS_EVIDENCE':
            if out['verdicts'] or out['issues'] or not out['retrieval_requests']:
                raise JobStopped('A10 retrieval response contains premature judgments')
        elif out['retrieval_requests']:
            raise JobStopped('A10 completed with unresolved retrieval')
        # Only a response cache, not coverage. Full local/global validation happens before acceptance.
        self.atomic(path, {'request': digest, 'output': out, 'sha256': fingerprint(out)})
        self.metrics.append({'turn': name, 'mode': mode, 'input_upper_tokens': self.count(payload),
                             'output_cap': self.cap(mode), 'response_upper_tokens': offline_tokens(out)})
        return out

    def retrieve(self, requests):
        fids, sources, props = set(), {}, {}
        for request in requests:
            if request.get('finding_ids') or request.get('query'):
                fids.update(self.registry.retrieve([request], self.cfg['retrieval_limit']))
            for iid in request.get('source_item_ids', []):
                if iid not in self.package.get('source_items', {}):raise JobStopped('unknown A10 source item')
                sources[iid] = self.package['source_items'][iid]
            for pid in request.get('proposition_ids', []):
                found = [p for p in self.package.get('propositions', []) if p['proposition_id'] == pid]
                if not found:raise JobStopped('unknown A10 proposition')
                props[pid] = found[0]
        if len(fids)+len(sources)+len(props) > self.cfg['retrieval_limit']:
            raise JobStopped('A10 retrieval too broad; narrow request')
        return fids, sources, props

    def with_retrieval(self, mode, name, payload):
        fids, sources, props = set(), {}, {}
        for n in range(self.cfg['max_retrieval_rounds']+1):
            request = {**payload, 'retrieved_evidence': {**self.registry.details(sorted(fids)),
                       'source_items': sources, 'propositions': list(props.values())}}
            out = self.turn(mode, f'{name}_R{n}', request)
            if out['status'] == 'COMPLETE':return out, {'finding_ids':sorted(fids),'source_item_ids':sorted(sources)}
            if n == self.cfg['max_retrieval_rounds']:raise JobStopped('A10 retrieval unresolved at round limit')
            try:new, s, p = self.retrieve(out['retrieval_requests'])
            except ValueError as exc:raise JobStopped(str(exc)) from exc
            fids.update(new);sources.update(s);props.update(p)
        raise AssertionError('unreachable')

    def bound(self, occurrence):
        ids = set(occurrence['item_ids'])
        path = occurrence['path']
        # Plan bindings supplement title/abstract/heading/display occurrences, never replace text review.
        if path[:2] == ['manuscript','title']:
            ids.update((self.plan.get('title') or {}).get('proposition_ids', []) if isinstance(self.plan.get('title'),dict) else [])
        if path[:2] == ['manuscript','abstract']:
            ids.update(scope.seeds({}, {'abstract': self.plan.get('abstract_plan', {})}))
        if 'sections' in path and path[-1] in ('heading','title'):
            sec = self.manuscript['sections'][path[2]]
            ids.update(p for s in self.plan.get('sections', []) if s.get('section_id') == sec.get('section_id')
                       for p in s.get('heading_proposition_ids', []))
        links = [x for i in sorted(ids) for x in evidence._links_behind(i, self.evidence_idx)]
        fids = scope.bound_findings(ids, self.idx)
        # Citation-only occurrences also need their paper's evidence, not a silent omission.
        bound_records={self.registry.record_of[f] for f in fids if f in self.registry.record_of}
        unresolved_citations=set(occurrence['citation_record_ids'])-bound_records
        fids.update(fid for fid, f in self.registry.findings.items() if f['record_id'] in unresolved_citations)
        fids.update(x['finding_id'] for x in links)
        missing = fids - set(self.registry.findings)
        if missing:raise JobStopped('A10 binding references missing registry findings')
        # Follow the same reference chain as finding/role binding. Preserve the full
        # proposition, including qualifications added by synthesis or human review.
        reachable, queue = set(), list(ids)
        while queue:
            i = queue.pop()
            if i in reachable:continue
            reachable.add(i)
            for obj in self.idx.get(i, []):
                for key,value in obj.items():
                    if scope._follows(key):
                        queue.extend(x for x in (value if isinstance(value,list) else [value])
                                     if isinstance(x,str) and x in self.idx)
        props = {i: [dict(p)
                    for p in self.idx.get(i, []) if 'proposition_id' in p or 'statement' in p]
                 for i in sorted(reachable) if i in self.idx}
        appraisals = [{**x, 'binding_id': occurrence['occurrence_id']+':A'+str(n)+':'+x['finding_id']}
                      for n,x in enumerate(links) if x.get('role') == 'SUBJECT_OF_APPRAISAL']
        bad = [x for x in links if not evidence.role_allowed(self.registry.findings.get(x['finding_id']), x.get('role'))]
        if bad:self.flag(occurrence['occurrence_id'], 'INELIGIBLE_EVIDENCE_CITED', 'BLOCKING', 'Remove or correct forbidden evidence roles')
        if set(occurrence['item_ids']) - set(self.idx):
            self.flag(occurrence['occurrence_id'], 'UNKNOWN_BINDING', 'BLOCKING', 'Repair unresolved proposition bindings')
        for rid in occurrence['citation_record_ids']:
            if rid not in self.registry.records:self.flag(occurrence['occurrence_id'], 'UNKNOWN_CITATION', 'BLOCKING', 'Correct citation identity')
        return {**occurrence, 'propositions': props, 'evidence_roles': links,
                'appraisal_bindings': appraisals,
                'prior_corrections':[{'code':i['code'],'correction':i['correction']} for i in self.corrections
                                     if occurrence['path'] in i['prior_paths']]}, fids

    def flag(self, oid, code, severity, correction):
        f = {'occurrence_ids':[oid], 'code':code, 'severity':severity, 'rationale':code,
             'correction':correction, 'responsible_stage':'A09-WRI/A12-EDI'}
        if f not in self.code_flags:self.code_flags.append(f)

    def local_payload(self, occurrences):
        bound, fids = [], set()
        for o in occurrences:
            b, fs = self.bound(o);bound.append(b);fids.update(fs)
        details = self.registry.details(sorted(fids))
        records = {self.registry.record_of[f] for f in fids} | {r for o in occurrences for r in o['citation_record_ids']}
        return {'mode':'LOCAL', 'occurrences':bound, **details,
                'source_records':{r:self.registry.records[r] for r in sorted(records) if r in self.registry.records},
                'synthesis_source_items':{i:self.package['source_items'][i] for b in bound
                    for p in b['propositions'].values() for obj in p for i in obj.get('source_item_ids', [])
                    if i in self.package.get('source_items', {})},
                'retrieval':{'available':True,'operations':['finding_ids','query','source_item_ids','proposition_ids']}}

    def packets(self):
        # Fixed outer boundaries prevent one longer edited sentence repacking every later claim.
        size=self.cfg['max_occurrences_per_packet']
        for start in range(0,len(self.occurrences),size):
            packet=[]
            for o in self.occurrences[start:start+size]:
                trial=packet+[o]
                if not self.admitted('LOCAL',self.local_payload(trial)):
                    if not packet:raise JobStopped('single A10 occurrence exceeds admission; inspect broad claim/bindings')
                    yield packet;packet=[o]
                    if not self.admitted('LOCAL',self.local_payload(packet)):raise JobStopped('single A10 occurrence exceeds admission')
                else:packet=trial
            if packet:yield packet

    def local(self, packet):
        payload = self.local_payload(packet)
        cache_payload={**payload,'occurrences':[{k:v for k,v in o.items() if k not in ('start','end')}
                                               for o in payload['occurrences']]}
        cache_key = fingerprint([self.dependencies, cache_payload])
        cache = self.cache_dir / f'{cache_key}.json'
        if cache.exists():
            saved = json.loads(cache.read_text(encoding='utf-8'))
            if fingerprint(saved['output']) != saved['sha256']:raise JobStopped('A10 local cache hash mismatch')
            out, retrieved = saved['output'], saved['retrieved']
        else:out, retrieved = self.with_retrieval('LOCAL', 'LOCAL_'+cache_key[:20], payload)
        expected = {o['occurrence_id'] for o in packet}
        got = [v['occurrence_id'] for v in out['verdicts']]
        if set(got)!=expected or len(got)!=len(expected):raise JobStopped('A10 omitted or duplicated occurrence verdict')
        visible = {f['finding_id'] for f in payload['findings']} | set(retrieved['finding_ids'])
        visible_sources = set(payload['synthesis_source_items']) | set(retrieved['source_item_ids'])
        for v in out['verdicts']:
            if v['verdict'] != 'NON_SCIENTIFIC' and set(v['checks']) != set(CHECKS):
                raise JobStopped('A10 incomplete scientific checks')
            occurrence = self.by_occurrence[v['occurrence_id']]
            if v['verdict'] != 'NON_SCIENTIFIC' and not occurrence['citation_record_ids']:
                self.flag(v['occurrence_id'], 'UNCITED_SCIENTIFIC_ASSERTION', 'MAJOR', 'Supply a supporting citation or qualify/remove assertion')
            needed = [a for b in payload['occurrences'] if b['occurrence_id']==v['occurrence_id'] for a in b['appraisal_bindings']]
            checked = {a['binding_id']:a for a in v['appraisal_checks']}
            if set(checked)!={a['binding_id'] for a in needed} or len(checked)!=len(v['appraisal_checks']):
                raise JobStopped('A10 appraisal occurrence unchecked')
            for a in checked.values():
                if not a['preserved']:self.flag(v['occurrence_id'],'APPRAISED_CLAIM_PROMOTED','BLOCKING','Restore attribution and critical appraisal; do not assert as fact')
            if set(v['evidence_finding_ids'])-visible or set(v['source_item_ids'])-visible_sources:
                raise JobStopped('A10 verdict cites unseen evidence')
            if v['verdict']=='VERIFIED':
                if not v['evidence_finding_ids'] and not v['source_item_ids']:
                    self.flag(v['occurrence_id'],'UNBACKED_VERIFICATION','BLOCKING','Retrieve evidence or return UNRESOLVED')
                for fid in v['evidence_finding_ids']:
                    f=self.registry.findings[fid]
                    appraised=any(a['finding_id']==fid and checked[a['binding_id']]['preserved'] for a in needed)
                    if not evidence.role_allowed(f,'SUPPORTING') and not appraised:
                        self.flag(v['occurrence_id'],'INELIGIBLE_EVIDENCE_CITED','BLOCKING','Cannot verify from ineligible evidence')
                    if not f.get('span'):
                        self.flag(v['occurrence_id'],'SOURCE_PASSAGE_MISSING','BLOCKING','Inspect the original source passage before verifying')
            if v['verdict']=='UNRESOLVED':self.flag(v['occurrence_id'],'UNRESOLVED_SCIENTIFIC_ASSERTION','BLOCKING',v['rationale'])
            if v['verdict']=='DEFECT' and not any(v['occurrence_id'] in i['occurrence_ids'] for i in out['issues']):
                raise JobStopped('A10 defect verdict without correction issue')
        self.validate_issues(out['issues'], expected, visible)
        self.atomic(cache, {'output':out,'retrieved':retrieved,'sha256':fingerprint(out)})
        return out

    def validate_issues(self, issues, allowed, visible):
        for i in issues:
            if i['code'] in evidence.SEVERITY_FLOOR:i['severity']=evidence.SEVERITY_FLOOR[i['code']]
            if not i['occurrence_ids'] or set(i['occurrence_ids'])-allowed:
                raise JobStopped('A10 issue references unseen occurrence')
            if set(i['finding_ids'])-visible:raise JobStopped('A10 issue references unseen evidence')

    def global_payload(self, page, verdicts):
        return {'mode':'GLOBAL','manuscript':{k:self.manuscript[k] for k in SURFACES if k in self.manuscript},
            'built_tables':self.tables,'inventory_fingerprint':self.inventory_hash,
            'prior_corrections':[{'code':i['code'],'correction':i['correction'],'prior_paths':i['prior_paths']} for i in self.corrections],
            'claim_verification_index':[{'occurrence_id':v['occurrence_id'],'verdict':v['verdict'],
                'path':self.by_occurrence[v['occurrence_id']]['path'],
                'text':self.by_occurrence[v['occurrence_id']]['text'],
                'issue_codes':[i['code'] for i in getattr(self,'local_issues',[]) if v['occurrence_id'] in i['occurrence_ids']]}
                for v in verdicts],
            'evidence_index_page':page,
            'global_independence':{k:v for k,v in self.registry.independence(self.registry.findings).items()
                                   if k!='identity_unknown_findings'},
            'identity_unknown_findings_count':sum(not any(self.registry.study_identity(f).values()) for f in self.registry.findings),
            'retrieval':{'available':True,'operations':['finding_ids','query','source_item_ids','proposition_ids']}}

    def global_pages(self, verdicts):
        entries = [{'id':fid,'kind':'FINDING','value':self.registry.index_line(fid)} for fid in self.registry.findings]
        entries += [{'id':p['proposition_id'],'kind':'PROPOSITION','value':compact_proposition(p)} for p in self.package.get('propositions', [])]
        entries += [{'id':'RECONCILIATION:'+str(n),'kind':'RECONCILIATION','value':p} for n,p in enumerate(self.package.get('reconciliation', []))]
        entries += [{'id':g['gap_id'],'kind':'GAP','value':{k:g[k] for k in ('gap_id','statement','source_item_ids','established_by') if k in g}} for g in self.package.get('knowledge_gaps', [])]
        page=[]
        for entry in entries:
            trial=page+[entry]
            if len(trial)>self.cfg.get('max_global_entries_per_page',128) or not self.admitted('GLOBAL',self.global_payload(trial,verdicts)):
                if not page:raise JobStopped('A10 global manuscript/index base exceeds admission')
                yield page;page=[entry]
                if not self.admitted('GLOBAL',self.global_payload(page,verdicts)):raise JobStopped('single global evidence unit exceeds admission')
            else:page=trial
        yield page

    def run(self, pass_='FINAL'):
        results=[self.local(p) for p in self.packets()]
        verdicts=[v for r in results for v in r['verdicts']]
        issues=[i for r in results for i in r['issues']]
        self.local_issues=issues+self.code_flags
        covered=[]
        for n,page in enumerate(self.global_pages(verdicts)):
            payload=self.global_payload(page,verdicts)
            cache=self.cache_dir/('global-'+fingerprint([self.dependencies,payload])+'.json')
            if cache.exists():
                saved=json.loads(cache.read_text(encoding='utf-8'))
                if fingerprint(saved['output'])!=saved['sha256']:raise JobStopped('A10 global cache hash mismatch')
                out,retrieved=saved['output'],saved['retrieved']
            else:out, retrieved=self.with_retrieval('GLOBAL',f'GLOBAL_{n:04d}',payload)
            ids=[p['id'] for p in page]
            if out['inventory_fingerprint']!=self.inventory_hash or out['reviewed_index_ids']!=ids:
                raise JobStopped('A10 global review incomplete or mismatched inventory')
            if out['verdicts']:raise JobStopped('global pass cannot replace local verdicts')
            self.validate_issues(out['issues'],set(self.by_occurrence),set(retrieved['finding_ids']))
            self.atomic(cache,{'output':out,'retrieved':retrieved,'sha256':fingerprint(out)})
            issues.extend(out['issues']);covered.extend(ids)
        all_issues=issues+self.code_flags
        severity=max(({'MINOR':1,'MAJOR':2,'BLOCKING':3}[i['severity']] for i in all_issues),default=0)
        findings=[{**i,'id':'A10-'+fingerprint(i)[:16], 'pass':pass_,
                   'locations':[{k:self.by_occurrence[oid][k] for k in ('occurrence_id','path','text','start','end')}
                                for oid in i['occurrence_ids']],
                   'responsible_stage':'A09-WRI' if pass_=='DRAFT' else 'A12-EDI'} for i in all_issues]
        return {'agent_id':'A10-RV','prompt_version':'2.0','status':'COMPLETE', 'pass':pass_,
            'warnings':[],'limitations':['Structural coverage is not proof of semantic accuracy'],
            'verification_fingerprint':self.digest,'execution_fingerprint':self.identity,
            'verification_policy_fingerprint':self.policy,
            'verification_execution':'COMPLETE','finding_severity':['NONE','MINOR','MAJOR','BLOCKING'][severity],
            'release_disposition':'HOLD_FOR_REVISION' if severity>=2 else 'APPROVED_WITH_MINOR_FINDINGS' if severity else 'APPROVED',
            'coverage':{'occurrences_total':len(self.occurrences),'occurrences_reviewed':len(verdicts),
                        'global_index_entries_reviewed':len(covered),'inventory_fingerprint':self.inventory_hash},
            'occurrence_inventory':self.occurrences,'verdicts':verdicts,'findings':findings,
            'prior_verification_fingerprint':self.prior_fingerprint,'correction_trace':self.corrections,
            'global_index_ids_reviewed':covered,'request_metrics':self.metrics}
