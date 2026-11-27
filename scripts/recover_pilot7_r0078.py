"""One-time offline recovery of R0078. Run with v33's src and vendor on sys.path."""
import copy
import hashlib
import json
import re


def legends(sections):
    keys = [f"Figure legend {n}" for n in range(1, 7)]
    for n, key in enumerate(keys, 1):
        row = json.loads(sections[key])
        if (row["id"] != f"fig{n}" or row["label"] != str(n)
                or not row["legend"] or row["legend"] != sections[f"Verbatim figure legend {n}"]):
            raise ValueError("Unverified legend " + key)
    return keys


def restore_quote(quote, section):
    # Only two missing private-use characters at these literal joins are in scope.
    pattern = re.escape(quote).replace("structurespecifically", "structure\ue5f8specifically").replace(
        "idarubicinwhich", "idarubicin\ue5f8which")
    matches = list(re.finditer(pattern, section))
    if len(matches) != 1 or matches[0].group().count("\ue5f8") != 2:
        raise ValueError("Missing or ambiguous exact F25 source")
    return matches[0].group(), list(matches[0].span())


def pca_cell(sections):
    location = "Table 1 | Daunorubicin | Concentration-based PCA"
    expected = "Daunorubicin | Concentration-based PCA | (TAT)\u2086-(10,2) | red | wavelength shift"
    if sections[location] != expected:
        raise ValueError("Wrong Table 1 row, column, sensor or signal")
    return location, sections[location]


def recover(run):
    from litreview import approved_scope, decisions, run_spec, extraction_mode
    from litreview.tools import span_check, fulltext, extraction_checks
    from litreview.runtime_integrity import sha
    from litreview.paths import SCHEMAS_DIR
    from jsonschema.validators import validator_for
    rid = "R0078"
    rec = next(r for r in run.load("selected_corpus.json") if r["record_id"] == rid)
    sections, access = run._retrieve_discovered(rec)
    outline = run_spec.load(run.dir)[0]
    payload = {"review_spec": run.load("spec_approved.json"), "theme_framework": run.load("theme_framework.json"),
               "content_level":"FULL_TEXT","record":{**rec,"content":sections},"source_access":access,
               "outline_questions":[{"section_id":s["section_id"],"heading":s["heading"],"questions":s["questions"],
                                     "guidance":s.get("guidance") or []} for s in outline["sections"]]}
    payload = decisions.attach(run.dir,"A05-KE",approved_scope.enrich(run,"A05-KE",payload))
    step = "A05-KE_R0078"
    out = run.dir/"outputs"
    paths = [out/(step+suffix) for suffix in (".raw0.txt",".raw1.txt",".response0.json",".response1.json")]
    hashes = {p.name:sha(p) for p in paths}
    request = run._receipt_request("A05-KE",payload,run.route("A05-KE"),None)
    if request != json.loads(paths[2].read_bytes())["request"]["request_id"]:
        raise ValueError("Reconstructed production payload does not match original receipt")
    raw = extraction_mode.strict_object(paths[0].read_text(encoding="utf8"))
    candidate = copy.deepcopy(raw)
    gates = span_check.check_findings(raw,sections)
    audit = {"original_hashes":hashes,"request_id":request,"sections_sha256":fulltext._digest(sections),
             "field_failures":[],"raw_finding_checks":gates,"verified_legends":legends(sections)}
    enriched = {**raw,**extraction_mode.trusted_metadata(payload)}
    schema = json.loads((SCHEMAS_DIR/"A05-KE.schema.json").read_bytes())
    audit["schema_errors"] = [str(e) for e in validator_for(schema)(schema).iter_errors(enriched)]
    audit["semantic_errors"] = extraction_checks.check(enriched)
    assert not audit["schema_errors"] and not audit["semantic_errors"]
    assert len(raw["findings"]) == 27 and len({f["finding_id"] for f in raw["findings"]}) == 27
    assert set(raw["sections_inspected"])-sections.keys()=={"Figure legends 1-6"}
    audit["field_failures"].append({"field":"sections_inspected[10]","reason":"Unavailable range alias Figure legends 1-6"})
    i=candidate["sections_inspected"].index("Figure legends 1-6")
    candidate["sections_inspected"][i:i+1]=audit["verified_legends"]
    for f in candidate["findings"]:
        section=sections[f["span_location"]["section"]]
        assert all(any(p in s for s in sections.values()) for p in f.get("premise_spans",[]))
        if f["span"] not in section:
            assert f["finding_id"]=="F25"
            f["span"],offsets=restore_quote(f["span"],section)
            audit["field_failures"].append({"finding_id":"F25","field":"span","checks":["span_found","location_matches","exact_substring"],"offsets":offsets,"restored":f["span"]})
    assert [g["finding_id"] for g in gates if not span_check.passed(g)]==["F25"]
    assert all(any(p in text for text in sections.values()) for c in raw["contexts"] for p in c.get("context_spans",[]))
    c1=next(c for c in candidate["contexts"] if c["context_id"]=="C1")["fields"]
    assert c1.pop("measured_at")=="PROTEIN_ACTIVITY"
    audit["field_failures"].append({"field":"C1.fields.measured_at","affected_findings":[f["finding_id"] for f in raw["findings"] if f["context_id"]=="C1"],"issue":"Optical readout, unsupported protein activity label removed"})
    f25=next(f for f in candidate["findings"] if f["finding_id"]=="F25")
    assert f25["modality"]=="HEDGED" and f25["assertion_type"]=="AUTHORS_INTERPRETATION"
    audit["field_failures"].append({"finding_id":"F25","field":"predicate_detail","issue":"Ends in relative to; incomplete. Held for review as an author hypothesis."})
    audit["first_pass"]={"candidate_findings":27,"exact_source_locations":26,"requested_pca_cell":0,"accepted_records":0,
                         "blue_dissociation_cell":"F8 cites body result GGACGC-(8,7), intensity modulation"}
    location,span=pca_cell(sections)
    assert "F28" not in [f["finding_id"] for f in raw["findings"]]
    new=copy.deepcopy(next(f for f in raw["findings"] if f["finding_id"]=="F8"))
    new.update(finding_id="F28",predicate="OTHER_SPECIFIED",predicate_detail="has a concentration-based PCA sensor feature",
               object_entity_id="E13",context_id="C3",span=span,span_location={"section":location,"figure_or_table":"Table 1"},
               quantities=[],warrant_note="Source-derived offline recovery from visually verified Table 1. Omitted by first-pass A05. Red identifies wavelength shift for this sensor combination.",
               subthemes=["concentration category","spectral feature selection"])
    candidate["findings"].append(new)
    candidate["warnings"].append("Offline source recovery: F28 was omitted by A05. F25 is pending because its predicate description is incomplete; do not use as an established mechanism.")
    full=extraction_mode.accept(json.dumps(candidate),payload)
    handoff=copy.deepcopy(full)
    handoff["findings"]=[f for f in handoff["findings"] if f["finding_id"]!="F25"]
    handoff=extraction_mode.accept(json.dumps(handoff),payload)
    audit["after_recovery"]={"original_candidates":27,"exact_source_locations":27,"pending":["F25"],"source_derived_additions":["F28"],"A06_candidates":len(handoff["findings"])}
    dest="offline_recovery/R0078/"
    for name,obj in [("audit",audit),("candidate",full),("pending_F25",f25),("handoff",handoff)]:
        run.save(dest+name+".json",obj)
    assert {p.name:sha(p) for p in paths}==hashes
    return handoff

