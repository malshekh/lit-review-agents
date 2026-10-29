"""Entity normalization for A05-KE mentions.

The agent never writes identifiers (A05-KE §6.8); this module fills them from authoritative
lookups and records how each was resolved:

| Entity type (A05-KE §6)                         | Lookup                                     |
|-------------------------------------------------|--------------------------------------------|
| GENE, PROTEIN, ENZYME, RECEPTOR, ION_CHANNEL,   | HGNC (human), MyGene.info (mouse, rat,     |
| TRANSPORTER, PROTEIN_COMPLEX, TRANSCRIPT        | others); UniProt accession + EC numbers    |
| APPROVED_DRUG, INVESTIGATIONAL_DRUG,            | ChEMBL (ID + max clinical phase -> verifies|
| TOOL_COMPOUND                                   | approval status), PubChem CID              |
| NATURAL_PRODUCT, ENDOGENOUS_METABOLITE,         | PubChem CID, ChEBI (via OLS4)              |
| ENVIRONMENTAL_CHEMICAL                          |                                            |
| CELL_LINE                                       | Cellosaurus (RRID, species of origin,      |
|                                                 | problematic / misidentified flag)          |
| DISEASE, PHENOTYPE, CELL_TYPE, TISSUE_OR_ORGAN, | EBI OLS4: MONDO, HP, CL, UBERON, GO,       |
| BIOLOGICAL_PROCESS, ORGANISM                    | NCBITaxon                                  |

States: RESOLVED · AMBIGUOUS (several plausible candidates; listed) · UNRESOLVED (lookup ran; nothing, or
only incompatible or weak candidates) · CONFLICT (the source and the identity contradict; the identity is
stripped and kept only in the run's conflict registry) · LOOKUP_FAILED (technical failure — never read as
"does not exist") · NOT_APPLICABLE. Results are cached per run in data/normalization_cache.json.

Normalization status says nothing about whether a finding is supported, and a finding's validity says
nothing about its identifiers: the two are checked separately (evidence.py). An abbreviation resolves only
through the source's own expansion of it; without one it is never RESOLVED. An unresolved entity keeps its
source mention and nothing else.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

from .. import config

TIMEOUT = 20

GENE_TYPES = {"GENE", "PROTEIN", "ENZYME", "RECEPTOR", "ION_CHANNEL", "TRANSPORTER", "PROTEIN_COMPLEX",
              "TRANSCRIPT"}
PROTEIN_TYPES = {"PROTEIN", "ENZYME", "RECEPTOR", "ION_CHANNEL", "TRANSPORTER"}
DRUG_TYPES = {"APPROVED_DRUG", "INVESTIGATIONAL_DRUG", "TOOL_COMPOUND", "DRUG_STATUS_UNVERIFIED"}
CHEM_TYPES = {"NATURAL_PRODUCT", "ENDOGENOUS_METABOLITE", "ENVIRONMENTAL_CHEMICAL"}
OLS_TYPES = {"DISEASE": "mondo", "PHENOTYPE": "hp", "CELL_TYPE": "cl", "TISSUE_OR_ORGAN": "uberon",
             "BIOLOGICAL_PROCESS": "go", "CELLULAR_COMPONENT": "go", "ORGANISM": "ncbitaxon"}

SPECIES = {  # keyword -> (NCBI taxon, MyGene species name)
    "human": (9606, "human"), "homo sapiens": (9606, "human"), "patient": (9606, "human"),
    "mouse": (10090, "mouse"), "murine": (10090, "mouse"), "mus musculus": (10090, "mouse"),
    "rat": (10116, "rat"), "rattus": (10116, "rat"),
    "zebrafish": (7955, "zebrafish"), "danio": (7955, "zebrafish"),
    "drosophila": (7227, "fruitfly"), "fly": (7227, "fruitfly"),
    "c. elegans": (6239, "nematode"), "caenorhabditis": (6239, "nematode"),
    "yeast": (559292, "yeast"), "saccharomyces": (559292, "yeast"),
}


def species_of(text: str | None) -> tuple[int, str] | None:
    t = (text or "").lower()
    for k, v in SPECIES.items():
        if re.search(rf"\b{re.escape(k)}\b", t):
            return v
    return None


def _get(url: str, params: dict | None = None) -> dict | list | None:
    """GET JSON. Returns None for 404 (no record); raises on network or server errors."""
    r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _result(state: str, source: str, **extra) -> dict:
    return {"normalization_state": state, "normalization_source": source, **extra}


# ------------------------------------------------------------------ genes and proteins
def hgnc(symbol: str) -> dict:
    for field in ("symbol", "alias_symbol", "prev_symbol"):
        data = _get(f"https://rest.genenames.org/fetch/{field}/{requests.utils.quote(symbol)}")
        docs = ((data or {}).get("response") or {}).get("docs", [])
        if len(docs) == 1:
            d = docs[0]
            return _result("RESOLVED", f"HGNC ({field})", normalized_id=d.get("hgnc_id"),
                           approved_symbol=d.get("symbol"), approved_name=d.get("name"))
        if len(docs) > 1:
            return _result("AMBIGUOUS", f"HGNC ({field})", normalized_id=None,
                           candidates=[f"{d.get('hgnc_id')} {d.get('symbol')}" for d in docs[:5]])
    return _result("UNRESOLVED", "HGNC", normalized_id=None)


def mygene(mention: str, species: str) -> dict:
    for q in (f"symbol:{mention}", f"alias:{mention}"):
        data = _get("https://mygene.info/v3/query",
                    {"q": q, "species": species, "fields": "symbol,name,entrezgene,MGI,RGD,HGNC", "size": 5})
        hits = (data or {}).get("hits", [])
        if len(hits) == 1:
            h = hits[0]
            nid = h.get("MGI") or h.get("RGD") or (f"HGNC:{h['HGNC']}" if h.get("HGNC") else None) \
                or (f"NCBIGene:{h['entrezgene']}" if h.get("entrezgene") else None)
            return _result("RESOLVED", f"MyGene.info ({species}, {q.split(':')[0]})", normalized_id=nid,
                           approved_symbol=h.get("symbol"), approved_name=h.get("name"),
                           ncbi_gene=h.get("entrezgene"))
        if len(hits) > 1:
            return _result("AMBIGUOUS", f"MyGene.info ({species})", normalized_id=None,
                           candidates=[f"{h.get('symbol')} ({h.get('name')})" for h in hits[:5]])
    return _result("UNRESOLVED", f"MyGene.info ({species})", normalized_id=None)


def uniprot(symbol: str, taxon: int) -> dict:
    data = _get("https://rest.uniprot.org/uniprotkb/search",
                {"query": f"gene_exact:{symbol} AND organism_id:{taxon} AND reviewed:true",
                 "fields": "accession,gene_primary,ec", "format": "json", "size": 1})
    res = (data or {}).get("results", [])
    if not res:
        return {}
    r = res[0]
    rec_name = (r.get("proteinDescription") or {}).get("recommendedName") or {}
    ecs = [e.get("value") for e in rec_name.get("ecNumbers", []) if e.get("value")]
    return {"uniprot": r.get("primaryAccession"), "ec_numbers": ecs}


def normalize_gene(entity: dict) -> dict:
    construct = entity.get("construct") if isinstance(entity.get("construct"), dict) else {}
    sp = species_of(entity.get("molecule_species")) or species_of(construct.get("species_of_construct"))
    if not sp:
        return _result("UNRESOLVED", "none", normalized_id=None,
                       note="Species of the molecule not reported; gene symbols collide across species, "
                            "so no lookup was made.")
    taxon, species = sp
    mention = entity.get("mention", "").strip()
    res = hgnc(mention) if taxon == 9606 else mygene(mention, species)
    if taxon == 9606 and res["normalization_state"] == "UNRESOLVED":
        res = mygene(mention, species)   # protein names such as "p53" resolve via MyGene aliases
    if res["normalization_state"] == "RESOLVED" and entity.get("type") in PROTEIN_TYPES:
        res.update(uniprot(res.get("approved_symbol") or mention, taxon))
    res["taxon"] = f"NCBITaxon:{taxon}"
    return res


# ------------------------------------------------------------------ chemicals and drugs
def chembl(name: str) -> dict:
    data = _get("https://www.ebi.ac.uk/chembl/api/data/molecule/search.json", {"q": name, "limit": 5})
    mols = (data or {}).get("molecules", [])

    def names(m: dict) -> set[str]:
        syns = {(s.get("molecule_synonym") or "").lower() for s in m.get("molecule_synonyms") or []}
        return syns | {(m.get("pref_name") or "").lower()}

    exact = [m for m in mols if name.lower() in names(m)]
    if len(exact) == 1:
        m = exact[0]
        phase = float(m.get("max_phase") or 0)
        return _result("RESOLVED", "ChEMBL", normalized_id=m.get("molecule_chembl_id"),
                       approved_name=m.get("pref_name"), max_clinical_phase=phase,
                       drug_status_verified="APPROVED" if phase >= 4 else
                       ("INVESTIGATIONAL" if phase > 0 else "NOT_IN_CLINICAL_DEVELOPMENT"))
    if len(exact) > 1:
        return _result("AMBIGUOUS", "ChEMBL", normalized_id=None,
                       candidates=[f"{m.get('molecule_chembl_id')} {m.get('pref_name')}" for m in exact])
    return _result("UNRESOLVED", "ChEMBL", normalized_id=None)


def pubchem(name: str) -> dict:
    data = _get(f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{requests.utils.quote(name)}/cids/JSON")
    cids = ((data or {}).get("IdentifierList") or {}).get("CID", [])
    if len(cids) == 1:
        return _result("RESOLVED", "PubChem", normalized_id=f"PubChem CID:{cids[0]}")
    if len(cids) > 1:
        return _result("AMBIGUOUS", "PubChem", normalized_id=None, candidates=[f"CID:{c}" for c in cids[:5]])
    return _result("UNRESOLVED", "PubChem", normalized_id=None)


# ------------------------------------------------------------------ DrugBank (optional, licensed)
def drugbank_settings() -> dict | None:
    """DrugBank settings if enabled in config/sources.yaml and a key is set, else None."""
    cfg = (config.load("sources").get("normalization_services") or {}).get("drugbank") or {}
    key = os.environ.get(cfg.get("key_env") or "DRUGBANK_API_KEY")
    if not cfg.get("enabled") or not key:
        return None
    return {"key": key, "base_url": (cfg.get("base_url") or "https://api.drugbank.com/v1").rstrip("/"),
            "region": cfg.get("region")}


def _dicts_with(obj, key):
    """Yield every dict anywhere in a nested JSON object that has `key`."""
    if isinstance(obj, dict):
        if key in obj:
            yield obj
        for v in obj.values():
            yield from _dicts_with(v, key)
    elif isinstance(obj, list):
        for x in obj:
            yield from _dicts_with(x, key)


def _drugbank_get(s: dict, path: str, params: dict | None = None):
    r = requests.get(f"{s['base_url']}{path}", params=params, timeout=TIMEOUT,
                     headers={"Authorization": s["key"], "Accept": "application/json"})
    if r.status_code == 404:
        return None
    r.raise_for_status()   # 401/403 (bad key) and 5xx are technical failures, never "no such drug"
    return r.json()


def drugbank(name: str, s: dict | None = None) -> dict:
    """Drug name search, then the drug record for its approval groups.

    Response parsing is deliberately loose (any nested object carrying `drugbank_id`), because
    the exact JSON shape depends on the DrugBank product licensed. Check with
    `litreview check --apis` after enabling.
    """
    s = s or drugbank_settings()
    if not s:
        return {"drugbank_state": "NOT_ENABLED"}
    params = {"q": name, **({"region": s["region"]} if s.get("region") else {})}
    hits = list(_dicts_with(_drugbank_get(s, "/drug_names", params) or {}, "drugbank_id"))
    exact = {h["drugbank_id"] for h in hits if (h.get("name") or "").lower() == name.lower()}
    ids = exact or {h["drugbank_id"] for h in hits}
    if not ids:
        return {"drugbank_state": "UNRESOLVED"}
    if len(ids) > 1:
        return {"drugbank_state": "AMBIGUOUS", "drugbank_candidates": sorted(ids)[:5]}
    dbid = ids.pop()
    drug = _drugbank_get(s, f"/drugs/{dbid}") or {}
    groups = [str(g).lower() for g in drug.get("groups") or []] if isinstance(drug, dict) else []
    return {"drugbank_state": "RESOLVED", "drugbank_id": dbid, "drugbank_groups": groups or None}


def _drugbank_crosscheck(res: dict, name: str) -> dict:
    """Add DrugBank fields to a ChEMBL result. ChEMBL stays the source of drug_status_verified;
    a disagreement is flagged for the reader, never resolved here."""
    s = drugbank_settings()
    if not s:
        return res
    try:
        db = drugbank(name, s)
    except (requests.RequestException, ValueError) as exc:
        return {**res, "drugbank_state": "LOOKUP_FAILED", "drugbank_note": str(exc)[:200]}
    res = {**res, **db}
    groups = db.get("drugbank_groups")
    if groups and res.get("drug_status_verified"):
        db_approved = "approved" in groups
        if db_approved != (res["drug_status_verified"] == "APPROVED"):
            res["drug_status_conflict"] = (f"ChEMBL: {res['drug_status_verified']} (max phase "
                                           f"{res.get('max_clinical_phase')}); DrugBank groups: {', '.join(groups)}")
        if "withdrawn" in groups:
            res["drug_status_conflict"] = (res.get("drug_status_conflict", "") + " DrugBank lists it as withdrawn.").strip()
    return res


def normalize_chemical(entity: dict) -> dict:
    name = entity.get("mention", "").strip()
    if entity.get("type") in DRUG_TYPES:
        res = chembl(name)
        if res["normalization_state"] == "RESOLVED":
            pc = pubchem(name)
            if pc.get("normalized_id"):
                res["pubchem"] = pc["normalized_id"]
            return _drugbank_crosscheck(res, name)
    res = pubchem(name)
    if res["normalization_state"] != "RESOLVED":
        chebi = ols(name, "chebi")
        if chebi["normalization_state"] == "RESOLVED":
            return chebi
    return res


# ------------------------------------------------------------------ names and abbreviations
def _squash(s: str | None) -> str:
    """Comparison form of a name: case, hyphens, slashes, underscores and spacing ignored."""
    return " ".join(re.sub(r"[-_/,]+", " ", str(s or "").lower()).split())


def _tight(s: str | None) -> str:
    """Cell-line comparison form: also ignores spaces and dots (U-251 MG == U251MG)."""
    return re.sub(r"[\s\-_./]+", "", str(s or "").lower())


def is_abbreviation(mention: str) -> bool:
    """A short token written mostly in capitals (DSF, DTC, ORR, CuET): a string an ontology may list as an
    exact synonym of several unrelated things, so an exact hit on it identifies nothing by itself."""
    m = (mention or "").strip()
    letters = [c for c in m if c.isalpha()]
    upper = sum(c.isupper() for c in letters)
    if sum(c.isdigit() for c in m) >= 3:     # a code name (BI-2536, LY364947, NCT-501) is an identifier
        return False
    return 2 <= len(m) <= 10 and " " not in m and upper >= 2 and upper * 2 >= len(letters)


def split_self_expanded(mention: str) -> tuple[str, str] | None:
    """'glioblastoma (GBM)' -> ('glioblastoma', 'GBM'): a mention that carries its own abbreviation, which
    abbreviates the head. The head is what gets looked up."""
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", (mention or "").strip())
    if not m or not is_abbreviation(m.group(2).strip()):
        return None
    head, abbr = m.group(1).strip(), m.group(2).strip()
    lf = _long_form(abbr, head)
    return (head, abbr) if lf and _squash(lf) == _squash(head[-len(lf):]) else None


def _long_form(sf: str, before: str) -> str | None:
    """Schwartz-Hearst: the shortest run of words ending at `before` whose characters cover the short form
    in order, with the first character starting a word."""
    s, i = len(sf) - 1, len(before) - 1
    while s >= 0:
        c = sf[s].lower()
        if not c.isalnum():
            s -= 1
            continue
        while i >= 0 and (before[i].lower() != c or (s == 0 and i > 0 and before[i - 1].isalnum())):
            i -= 1
        if i < 0:
            return None
        i -= 1
        s -= 1
    lf = before[before.rfind(" ", 0, i + 1) + 1:].strip(" ,;:([")
    return lf if len(lf) > len(sf) and " " not in sf else None


def source_text(sections) -> str:
    if isinstance(sections, dict):
        return "\n".join(source_text(v) for v in sections.values())
    if isinstance(sections, list):
        return "\n".join(source_text(v) for v in sections)
    return str(sections or "")


def find_expansion(abbr: str, text: str) -> dict | None:
    """The source's own expansion of an abbreviation, from "long form (ABBR)" patterns. Several different
    expansions in one paper -> {"conflicting_long_forms": [...]}; none -> None."""
    found: dict[str, dict] = {}
    for m in re.finditer(r"\(\s*" + re.escape(abbr) + r"\s*[);,]", text or ""):
        before = (text[max(0, m.start() - 200):m.start()]).rstrip()
        words = before.split()[-min(len(abbr) + 5, len(abbr) * 2):]
        lf = _long_form(abbr, " ".join(words))
        if lf:
            f = found.setdefault(_squash(lf), {"long_form": lf, "count": 0,
                                               "source_span": (text[max(0, m.start() - 80):m.end()]).strip()})
            f["count"] += 1
    if not found:
        return None
    if len(found) > 1:
        return {"abbreviation": abbr, "conflicting_long_forms": sorted(f["long_form"] for f in found.values())}
    f = next(iter(found.values()))
    return {"abbreviation": abbr, "long_form": f["long_form"], "occurrences": f["count"], "source_span": f["source_span"]}


# ------------------------------------------------------------------ cell lines
def _walk(obj, key):
    """Yield every value stored under `key` anywhere in a nested JSON object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk(x, key)


def _primary_acc(line: dict) -> str | None:
    for accs in _walk(line, "accession-list"):
        for a in accs:
            if a.get("type") == "primary":
                return a.get("value")
    return None


def _line_names(line: dict) -> tuple[str | None, list[str]]:
    names = [n for nl in _walk(line, "name-list") for n in nl if isinstance(n, dict)]
    ident = next((n.get("value") for n in names if n.get("type") == "identifier"), None)
    return ident, [n.get("value") for n in names if n.get("value")]


def _problems(line: dict) -> list[str]:
    return [c.get("value") for cl in _walk(line, "comment-list") for c in cl
            if "problematic" in str(c.get("category", "")).lower()]


CELLOSAURUS_ROWS = 200   # derivative lines (-Luc, -GFP, knockouts) outrank their parent; never truncate to a few


def cellosaurus(name: str) -> dict:
    """A cell line by exact name. Every line whose identifier or synonym matches the mention exactly
    (ignoring case, spaces, hyphens and dots) is a candidate; nothing else is. One candidate -> RESOLVED;
    several -> AMBIGUOUS, each candidate listed with its own problematic-line note and an overall warning
    that misidentification is possible (never that the stock was misidentified); none -> UNRESOLVED. A
    derivative (U251MG-Luc) and its parent (U-251MG) never stand in for each other: their names differ."""
    lines: dict[str, dict] = {}
    for q in (f'id:"{name}"', f'sy:"{name}"'):
        data = _get("https://api.cellosaurus.org/search/cell-line",
                    {"q": q, "format": "json", "rows": CELLOSAURUS_ROWS})
        for line in (next(_walk(data, "cell-line-list"), []) if data else []):
            acc = _primary_acc(line)
            if acc:
                lines.setdefault(acc, line)
    want = _tight(name)
    exact = {acc: line for acc, line in lines.items() if want in {_tight(x) for x in _line_names(line)[1]}}
    if len(exact) == 1:
        acc, line = next(iter(exact.items()))
        problems = _problems(line)
        species = [s.get("label") or s.get("value") for sl in _walk(line, "species-list") for s in sl]
        return _result("RESOLVED", "Cellosaurus", normalized_id=f"RRID:{acc}", approved_name=_line_names(line)[0],
                       species_of_origin=species, problematic_cell_line=bool(problems),
                       problem_note=problems[0] if problems else None,
                       identity_warnings=[f"{_line_names(line)[0]} ({acc}) is listed by Cellosaurus as a problematic "
                                          f"cell line: {problems[0]}"] if problems else [])
    if len(exact) > 1:
        details = []
        for acc, line in sorted(exact.items()):
            problems = _problems(line)
            details.append({"accession": acc, "name": _line_names(line)[0], "problematic": bool(problems),
                            "problem_note": problems[0] if problems else None})
        warnings = [f"Misidentification possible: candidate {d['name']} ({d['accession']}) is listed by "
                    f"Cellosaurus as a problematic cell line ({d['problem_note']}). The source does not say which "
                    f"line was used; this does not establish that the stock was misidentified."
                    for d in details if d["problematic"]]
        return _result("AMBIGUOUS", "Cellosaurus", normalized_id=None, candidates=[d["accession"] for d in details],
                       candidate_details=details, identity_warnings=warnings)
    return _result("UNRESOLVED", "Cellosaurus", normalized_id=None,
                   note=f"no line named exactly '{name}'" + (f" among {len(lines)} search hits" if lines else ""))


# ------------------------------------------------------------------ ontologies (OLS4)
def _ols_docs(term: str, ontology: str) -> list[dict]:
    """Exact hits on a term's label or synonyms only. Descriptions, annotations and cross-references are
    not searched: they produced matches such as ORR -> 'Exacerbated by opiate medication'."""
    data = _get("https://www.ebi.ac.uk/ols4/api/search",
                {"q": term, "ontology": ontology, "exact": "true", "queryFields": "label,synonym", "type": "class",
                 "fieldList": "obo_id,label,synonym,is_defining_ontology", "rows": 25})
    return ((data or {}).get("response") or {}).get("docs", [])


def _native(docs: list[dict], ontology: str) -> list[dict]:
    """Terms defined by the ontology searched (MONDO imports HP terms, ChEBI is not the source of GO)."""
    pre = ontology.upper() + ":"
    return [d for d in docs if (d.get("obo_id") or "").upper().startswith(pre)]


def _syns(d: dict) -> set[str]:
    s = d.get("synonym") or []
    return {_squash(x) for x in (s if isinstance(s, list) else [s])}


def ols(term: str, ontology: str) -> dict:
    """RESOLVED only for a unique exact label in the ontology's own terms. Exact synonym hits are plausible,
    not proven (an abbreviation can be an exact synonym of unrelated terms): AMBIGUOUS. Hits outside the
    ontology only: UNRESOLVED, listed as weak candidates."""
    docs = _ols_docs(term, ontology)
    src = f"OLS4/{ontology.upper()}"
    t = _squash(term)
    native = _native(docs, ontology)
    label = [d for d in native if _squash(d.get("label")) == t]
    syn = [d for d in native if d not in label and t in _syns(d)]
    if len(label) == 1:
        d = label[0]
        return _result("RESOLVED", src, normalized_id=d.get("obo_id"), approved_name=d.get("label"), match="EXACT_LABEL")
    if label or syn:
        return _result("AMBIGUOUS", src, normalized_id=None,
                       candidates=[f"{d.get('obo_id')} {d.get('label')}" for d in label + syn],
                       match="EXACT_LABEL" if len(label) > 1 else "EXACT_SYNONYM_ONLY")
    if docs:
        return _result("UNRESOLVED", src, normalized_id=None,
                       weak_candidates=[f"{d.get('obo_id')} {d.get('label')}" for d in docs[:5]],
                       note="only terms defined outside this ontology matched")
    return _result("UNRESOLVED", src, normalized_id=None)


def abbreviation_candidates(abbr: str, entity_type: str) -> list[dict]:
    """What an ontology says the bare abbreviation could be: terms carrying it as an exact label or synonym."""
    out = []
    if entity_type in DRUG_TYPES or entity_type in CHEM_TYPES:
        ontology = "chebi"
    elif entity_type in OLS_TYPES:
        ontology = OLS_TYPES[entity_type]
    else:
        return out
    a = _squash(abbr)
    for d in _native(_ols_docs(abbr, ontology), ontology):
        if a == _squash(d.get("label")) or a in _syns(d):
            out.append({"id": d.get("obo_id"), "label": d.get("label"), "names": sorted(_syns(d) | {_squash(d.get("label"))})})
    return out


# ------------------------------------------------------------------ dispatcher
IDENTITY_FIELDS = ("normalized_id", "approved_name", "approved_symbol", "pubchem", "max_clinical_phase",
                   "drug_status_verified", "drug_status_conflict", "drugbank_id", "drugbank_groups", "drugbank_state",
                   "drugbank_candidates", "drugbank_note", "uniprot", "ec_numbers", "ncbi_gene", "species_of_origin",
                   "problematic_cell_line", "problem_note", "candidates", "candidate_details", "identity_warnings",
                   "weak_candidates", "match", "expansion", "resolved_from", "abbreviation_candidates_overridden",
                   "conflict", "note", "normalization_state", "normalization_source")
ABBR_TYPES = DRUG_TYPES | CHEM_TYPES | set(OLS_TYPES)


def _lookup(entity: dict, mention: str) -> dict:
    t = entity.get("type", "")
    if t in DRUG_TYPES or t in CHEM_TYPES:
        return normalize_chemical({**entity, "mention": mention})
    return ols(mention, OLS_TYPES[t])


def _abbreviation(entity: dict, text: str | None) -> dict:
    """An abbreviation is resolved only through its source-supported expansion; the expansion takes
    precedence over any ontology hit on the abbreviation itself. Without one it is never RESOLVED."""
    abbr, t = entity["mention"].strip(), entity.get("type", "")
    exp = find_expansion(abbr, text or "")
    if exp and exp.get("long_form"):
        res = _lookup(entity, exp["long_form"])
        res = {**res, "expansion": exp, "resolved_from": "SOURCE_EXPANSION"}
        cands = abbreviation_candidates(abbr, t)
        lf = _squash(exp["long_form"])
        if res["normalization_state"] == "RESOLVED":
            others = [f"{c['id']} {c['label']}" for c in cands if c["id"] != res.get("normalized_id") and lf not in c["names"]]
            if others:
                res["abbreviation_candidates_overridden"] = others
            return res
        agreeing = [c for c in cands if lf in c["names"]]
        if len(agreeing) == 1:
            c = agreeing[0]
            return _result("RESOLVED", f"OLS4 via source expansion", normalized_id=c["id"], approved_name=c["label"],
                           expansion=exp, resolved_from="SOURCE_EXPANSION", match="EXPANSION_IS_SYNONYM")
        contradicting = [c for c in cands if lf not in c["names"]]
        if contradicting and not agreeing:
            return _result("CONFLICT", "source expansion vs ontology", normalized_id=None, expansion=exp,
                           conflict={"raised_by": "CODE", "source_expansion": exp["long_form"],
                                     "conflicting_ids": [c["id"] for c in contradicting],
                                     "conflicting_names": [c["label"] for c in contradicting]})
        return res
    cands = abbreviation_candidates(abbr, t)
    reason = ("the source expands it inconsistently: " + "; ".join(exp["conflicting_long_forms"])
              if exp else "abbreviation without an expansion in the source")
    if cands:
        return _result("AMBIGUOUS", "abbreviation", normalized_id=None, note=reason,
                       candidates=[f"{c['id']} {c['label']}" for c in cands], match="ABBREVIATION_ONLY")
    return _result("UNRESOLVED", "abbreviation", normalized_id=None, note=reason)


def normalize_one(entity: dict, text: str | None = None) -> dict:
    t = entity.get("type", "")
    mention = (entity.get("mention") or "").strip()
    if not mention:
        return _result("UNRESOLVED", "none", normalized_id=None)
    if t in GENE_TYPES:
        return normalize_gene(entity)
    if t == "CELL_LINE":
        return cellosaurus(mention)
    if t in ABBR_TYPES and is_abbreviation(mention):
        return _abbreviation(entity, text)
    split = split_self_expanded(mention) if t in ABBR_TYPES else None
    if split:
        res = _lookup(entity, split[0])
        return {**res, "expansion": {"abbreviation": split[1], "long_form": split[0], "source_span": mention},
                "resolved_from": "MENTION_HEAD"}
    if t in DRUG_TYPES or t in CHEM_TYPES:
        return normalize_chemical(entity)
    if t in OLS_TYPES:
        return ols(mention, OLS_TYPES[t])
    return _result("NOT_APPLICABLE", "none", normalized_id=None)


CACHE_VERSION = "v3"   # earlier entries (exact hit on any field, first three Cellosaurus rows) are never reused


def _cache_key(e: dict, text: str | None = None) -> str:
    exp = ""
    if e.get("type") in ABBR_TYPES and is_abbreviation(e.get("mention") or ""):
        x = find_expansion((e.get("mention") or "").strip(), text or "") or {}
        exp = x.get("long_form") or ("|".join(x.get("conflicting_long_forms") or []))
    return "|".join([CACHE_VERSION] + [str(e.get(k) or "") for k in ("type", "mention", "molecule_species")] + [exp])


def usable_identity(entity: dict) -> dict:
    """The identity fields a consumer may use: only for a RESOLVED entity. AMBIGUOUS, UNRESOLVED and
    CONFLICT entities are known by their source mention alone; candidate-level warnings travel with them."""
    if entity.get("normalization_state") != "RESOLVED":
        return {k: entity[k] for k in ("identity_warnings",) if entity.get(k)}
    return {k: entity.get(k) for k in ("normalized_id", "approved_name", "approved_symbol", "drug_status_verified",
                                       "drug_status_conflict", "drugbank_id", "problematic_cell_line",
                                       "identity_warnings") if entity.get(k) not in (None, [], "")}


def conflict_entity(entity: dict, raised_by: str, reason: str, record_id: str | None,
                    spans: list[str]) -> dict:
    """Make a code-attached identity unusable: strip every identity field from the entity, keep its source
    mention, set CONFLICT. Returns the audit record (the only place the conflicting ID is kept)."""
    audit = {"record_id": record_id, "entity_id": entity.get("entity_id"), "mention": entity.get("mention"),
             "type": entity.get("type"),
             "conflicting_id": entity.get("normalized_id") or (entity.get("conflict") or {}).get("conflicting_ids"),
             "conflicting_name": entity.get("approved_name") or (entity.get("conflict") or {}).get("conflicting_names"),
             "normalization_source": entity.get("normalization_source"), "expansion": entity.get("expansion"),
             "raised_by": raised_by, "reason": reason, "source_spans": spans}
    for k in IDENTITY_FIELDS:
        entity.pop(k, None)
    entity.update(normalization_state="CONFLICT", normalization_source=f"conflict ({raised_by})", normalized_id=None)
    return audit


def _spans_for(extraction: dict, entity_id: str) -> list[str]:
    return [f.get("span") for f in extraction.get("findings", [])
            if entity_id in (f.get("subject_entity_id"), f.get("object_entity_id")) and f.get("span")][:10]


def load_conflicts(path: Path | None) -> set[str]:
    if not path or not Path(path).exists():
        return set()
    return {str(c.get("conflicting_id")) for c in json.loads(Path(path).read_text(encoding="utf-8"))
            if c.get("conflicting_id")}


def register_conflicts(path: Path | None, audits: list[dict]) -> None:
    """Append to the run's conflict registry: one row per conflicting ID. Every later normalization in the
    run rejects these IDs, whatever mention they come back for."""
    if not path or not audits:
        return
    rows = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else []
    for a in audits:
        ids = a["conflicting_id"] if isinstance(a["conflicting_id"], list) else [a["conflicting_id"]]
        rows += [{**a, "conflicting_id": i} for i in ids if i]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


def normalize_entities(extraction: dict, cache_path: Path | None = None, sections=None,
                       conflicts_path: Path | None = None, record_id: str | None = None) -> dict:
    """Fill normalization fields on every entity of an A05-KE output, in place. `sections` (the paper text)
    supplies abbreviation expansions; `conflicts_path` is the run's conflict registry (data/
    normalization_conflicts.json): an identity in it, or a source-vs-ontology contradiction found here, is
    stripped (CONFLICT) and recorded there with the mention and its source spans. Re-normalizing replaces
    every identity field; nothing from an earlier identity survives on the entity."""
    cache: dict = {}
    if cache_path and Path(cache_path).exists():
        cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    text = source_text(sections) if sections is not None else None
    rejected = load_conflicts(conflicts_path)
    audits = []
    for e in extraction.get("entities", []):
        key = _cache_key(e, text)
        if key not in cache:
            try:
                cache[key] = normalize_one(e, text)
            except (requests.RequestException, ValueError) as exc:
                # technical failure: not cached, so the next run retries; never read as absence
                for k in IDENTITY_FIELDS:
                    e.pop(k, None)
                e.update(_result("LOOKUP_FAILED", "error", normalized_id=None, note=str(exc)[:200]))
                continue
        for k in IDENTITY_FIELDS:
            e.pop(k, None)
        e.update(cache[key])
        if cache[key].get("drugbank_state") == "LOOKUP_FAILED":
            del cache[key]   # keep the ChEMBL result on the entity, but retry DrugBank next time
        if e.get("normalization_state") == "CONFLICT":
            audits.append(conflict_entity(e, "CODE", "source expansion contradicts the ontology's reading of the "
                                          "abbreviation", record_id, _spans_for(extraction, e.get("entity_id"))))
        elif e.get("normalized_id") and str(e["normalized_id"]) in rejected:
            audits.append(conflict_entity(e, "REGISTRY", "identity previously found to contradict a source in this run",
                                          record_id, _spans_for(extraction, e.get("entity_id"))))
    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(json.dumps(cache, indent=1), encoding="utf-8")
    register_conflicts(conflicts_path, [a for a in audits if a["raised_by"] != "REGISTRY"])
    if audits:
        extraction.setdefault("_normalization_audit", []).extend(audits)
    return extraction
