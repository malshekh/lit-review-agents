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

States: RESOLVED · AMBIGUOUS (several candidates; listed) · UNRESOLVED (lookup ran, nothing
matched) · LOOKUP_FAILED (technical failure — never read as "does not exist") · NOT_APPLICABLE.
Results are cached per run in data/normalization_cache.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

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


def normalize_chemical(entity: dict) -> dict:
    name = entity.get("mention", "").strip()
    if entity.get("type") in DRUG_TYPES:
        res = chembl(name)
        if res["normalization_state"] == "RESOLVED":
            pc = pubchem(name)
            if pc.get("normalized_id"):
                res["pubchem"] = pc["normalized_id"]
            return res
    res = pubchem(name)
    if res["normalization_state"] != "RESOLVED":
        chebi = ols(name, "chebi")
        if chebi["normalization_state"] == "RESOLVED":
            return chebi
    return res


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


def cellosaurus(name: str) -> dict:
    lines: list = []
    for q in (f'id:"{name}"', f'sy:"{name}"'):
        data = _get("https://api.cellosaurus.org/search/cell-line", {"q": q, "format": "json", "rows": 3})
        lines = next(_walk(data, "cell-line-list"), []) if data else []
        if lines:
            break
    if not lines:
        return _result("UNRESOLVED", "Cellosaurus", normalized_id=None)
    if len(lines) > 1:
        return _result("AMBIGUOUS", "Cellosaurus", normalized_id=None,
                       candidates=[_primary_acc(line) for line in lines])
    line = lines[0]
    acc = _primary_acc(line)
    species = [s.get("label") or s.get("value") for sl in _walk(line, "species-list") for s in sl]
    problems = [c.get("value") for cl in _walk(line, "comment-list") for c in cl
                if "problematic" in str(c.get("category", "")).lower()]
    return _result("RESOLVED", "Cellosaurus", normalized_id=f"RRID:{acc}" if acc else None,
                   species_of_origin=species, problematic_cell_line=bool(problems),
                   problem_note=problems[0] if problems else None)


# ------------------------------------------------------------------ ontologies (OLS4)
def ols(term: str, ontology: str) -> dict:
    data = _get("https://www.ebi.ac.uk/ols4/api/search",
                {"q": term, "ontology": ontology, "exact": "true", "rows": 5})
    docs = ((data or {}).get("response") or {}).get("docs", [])
    src = f"OLS4/{ontology.upper()}"
    ids = {d.get("obo_id") for d in docs if d.get("obo_id")}
    label_exact = [d for d in docs if (d.get("label") or "").lower() == term.lower()]
    pick = docs[0] if len(ids) == 1 else (label_exact[0] if len(label_exact) == 1 else None)
    if pick:
        return _result("RESOLVED", src, normalized_id=pick.get("obo_id"), approved_name=pick.get("label"))
    if ids:
        return _result("AMBIGUOUS", src, normalized_id=None,
                       candidates=[f"{d.get('obo_id')} {d.get('label')}" for d in docs])
    return _result("UNRESOLVED", src, normalized_id=None)


# ------------------------------------------------------------------ dispatcher
def normalize_one(entity: dict) -> dict:
    t = entity.get("type", "")
    mention = (entity.get("mention") or "").strip()
    if not mention:
        return _result("UNRESOLVED", "none", normalized_id=None)
    if t in GENE_TYPES:
        return normalize_gene(entity)
    if t in DRUG_TYPES or t in CHEM_TYPES:
        return normalize_chemical(entity)
    if t == "CELL_LINE":
        return cellosaurus(mention)
    if t in OLS_TYPES:
        return ols(mention, OLS_TYPES[t])
    return _result("NOT_APPLICABLE", "none", normalized_id=None)


def _cache_key(e: dict) -> str:
    return "|".join(str(e.get(k) or "") for k in ("type", "mention", "molecule_species"))


def normalize_entities(extraction: dict, cache_path: Path | None = None) -> dict:
    """Fill normalization fields on every entity of an A05-KE output, in place."""
    cache: dict = {}
    if cache_path and Path(cache_path).exists():
        cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    for e in extraction.get("entities", []):
        key = _cache_key(e)
        if key not in cache:
            try:
                cache[key] = normalize_one(e)
            except (requests.RequestException, ValueError) as exc:
                # technical failure: not cached, so the next run retries; never read as absence
                e.update(_result("LOOKUP_FAILED", "error", normalized_id=None, note=str(exc)[:200]))
                continue
        e.update(cache[key])
    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return extraction
