"""NON-REPRESENTATIVE A07 -> A09 writing sample (Phase 1.5). Development code; nothing here is promoted.

What it adds, and nothing more:
  * import of a researcher-repaired A07 PLAN with full provenance, as TURN_IMPORTED_REPAIR (never a model
    acceptance), blocked from GROUP until the researcher approves that exact repaired SHA-256;
  * a sample scope: a researcher-chosen subset of the deterministic A07 packets. The subset must own EVERY
    mandatory manifest item, so mandatory coverage is never sampled away; findings in the excluded packets are
    labelled OUT_OF_SAMPLE_SCOPE, never silently dropped and never UNACCOUNTED;
  * a projection for the pilot's stage authorization that prices only the calls a sample can make
    (A07 GROUP/RECONCILE/FINAL, A08, A09 sections) at cold worst case; no A10-A12, no front matter;
  * a dry run that lists the next calls and their reservations with every provider route disabled.

The writing flow itself (CP3 -> A08 -> A09 sections -> COMPLETE_SAMPLE) lives in singlepaper_eval.WritingRun.
Per-call admission is unchanged: WritingRun._reserve (sub-cap with 30% margin) and Run._reserve (holds the
margin) run before every paid request. No schema or validator is weakened.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import re
import shutil
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from .paths import REPO_ROOT, SCHEMAS_DIR
from .synthesis_bounded import RegistrySynthesisJob, IMPORT_APPROVAL, ImportApprovalRequired
from .synthesis_job import JobStopped
from .synthesis_registry import canonical, fingerprint, offline_tokens, compact_proposition, chunks

VERSION = "a07-a09-sample-v1"
LABEL = "NON_REPRESENTATIVE_SAMPLE"
POLICY = "input/a07_a09_sample.json"
OUT_OF_SCOPE = "OUT_OF_SAMPLE_SCOPE"
MARGIN = Decimal("1.30")

# The v10 A07 PLAN attempt (failed schema validation) and May's proposed repair.
V10_PLAN_STEP = "A07-SYN_jobb306e8a74bd1952c_PLAN"
V10_RAW_SHA = "3d2f03ade43301a38548b73ecc40c2d0c38aee2880290ac23b93d067d8d74675"
V10_REPAIRED_SHA = "958ea8e00eabb8fafe93bd31a2f6758cc829b0113d107c945d10feac467f32db"

# Sample bounds. A09 caps below 8000 are refused: adaptive thinking shares max_tokens (see REPORT.md).
BOUNDS = {"max_sections": (1, 2), "words": (800, 1000), "a08_max_tokens": (4000, 16000),
          "a09_max_tokens": (8000, 16000), "efforts": ("low", "medium")}


class SampleRefused(RuntimeError):
    """The sample operation was refused before any write or call."""


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_runtime() -> bool:
    """True inside a promoted/frozen runtime (it carries a runtime manifest), i.e. a LIVE run."""
    return (REPO_ROOT / "frozen_runtime_manifest.json").exists() or "litreviewstage1" in str(REPO_ROOT).lower()


def guard_live(live: bool) -> None:
    if frozen_runtime() and not live:
        raise SampleRefused("this is a live runtime: run on a COPY, or pass --live only with the researcher's "
                            "explicit approval")


# ---------------------------------------------------------------- policy
def policy(run) -> dict | None:
    """The sample authority for this run, validated, or None when the run is not a sample."""
    path = run.dir / POLICY
    if not path.exists():
        return None
    p = json.loads(path.read_text(encoding="utf-8"))
    problems = _problems(p, run.id)
    if problems:
        raise SampleRefused("invalid sample authority: " + ", ".join(problems))
    return p


def _problems(p: dict, run_id: str) -> list[str]:
    problems = []
    if p.get("version") != VERSION or p.get("run_id") != run_id or p.get("label") != LABEL:
        problems.append("version/run/label")
    ids = p.get("group_ids")
    if (not isinstance(ids, list) or not ids or ids != sorted(set(ids))
            or any(not re.fullmatch(r"G\d{4}", str(g)) for g in ids)):
        problems.append("group_ids")
    lo, hi = BOUNDS["max_sections"]
    if not isinstance(p.get("max_sections"), int) or not lo <= p["max_sections"] <= hi:
        problems.append("max_sections")
    wlo, whi = BOUNDS["words"]
    if not (isinstance(p.get("min_words"), int) and isinstance(p.get("max_words"), int)
            and wlo <= p["min_words"] <= p["max_words"] <= whi):
        problems.append("words")
    for key in ("a08_max_tokens", "a09_max_tokens"):
        lo, hi = BOUNDS[key]
        if not isinstance(p.get(key), int) or not lo <= p[key] <= hi:
            problems.append(key)
    if p.get("a09_effort") not in BOUNDS["efforts"]:
        problems.append("a09_effort")
    if p.get("loops") != {"max_critique_cycles": 0, "max_redrafts": 0, "max_json_repair_attempts": 0}:
        problems.append("loops")
    return problems


def write_policy(run, group_ids, *, max_sections=2, min_words=800, max_words=1000, a08_max_tokens=8000,
                 a09_max_tokens=16000, a09_effort="medium", created_by="", live=False) -> dict:
    guard_live(live)
    path = run.dir / POLICY
    if path.exists():
        raise SampleRefused("sample authority already exists; refusing overwrite")
    p = {"version": VERSION, "run_id": run.id, "label": LABEL, "group_ids": sorted(group_ids),
         "max_sections": max_sections, "min_words": min_words, "max_words": max_words,
         "a08_max_tokens": a08_max_tokens, "a09_max_tokens": a09_max_tokens, "a09_effort": a09_effort,
         "loops": {"max_critique_cycles": 0, "max_redrafts": 0, "max_json_repair_attempts": 0},
         "excluded_calls": ["A07 retrieval lookups", "JSON repair", "A09 front matter", "A10-RV", "A11-RC", "A12-EDI"],
         "created_by": created_by, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    problems = _problems(p, run.id)
    if problems:
        raise SampleRefused("invalid sample authority: " + ", ".join(problems))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p, indent=2), encoding="utf-8")
    return p


def first_groups(packets: list[dict], n: int) -> list[str]:
    """The first n packets in the production builder's deterministic order."""
    if n < 1 or n > len(packets):
        raise SampleRefused(f"--max-groups must be between 1 and {len(packets)}")
    return [p["group_id"] for p in packets[:n]]


# ---------------------------------------------------------------- the sample job
class SampleSynthesisJob(RegistrySynthesisJob):
    """RegistrySynthesisJob over a researcher-chosen subset of its own packets. Every validator is the
    production one; only the packet list and the package's scope labelling differ."""

    def _packets(self):
        full = super()._packets()
        spec = self.cfg["sample"]
        wanted = set(spec["group_ids"])
        known = {p["group_id"] for p in full}
        if wanted - known:
            raise JobStopped(f"sample names unknown packets {sorted(wanted - known)}")
        chosen = [p for p in full if p["group_id"] in wanted]
        owned = {i for p in chosen for i in p["manifest_item_ids"]}
        missing = sorted(set(self.mandatory) - owned)
        if missing:
            need = sorted({p["group_id"] for p in full if set(p["manifest_item_ids"]) & set(missing)})
            raise JobStopped(f"sample would leave mandatory items unowned ({len(missing)}); include packets {need}")
        self.all_packets = full
        self.sample_finding_ids = {f for p in chosen for f in p["finding_ids"]}
        return chosen

    def sample_block(self) -> dict:
        excluded = [p for p in self.all_packets if p not in self.packets]
        return {"label": LABEL, "version": self.cfg["sample"]["version"],
                "selected_group_ids": [p["group_id"] for p in self.packets],
                "excluded_group_ids": [p["group_id"] for p in excluded],
                "excluded_finding_ids": sorted({f for p in excluded for f in p["finding_ids"]} - self.sample_finding_ids),
                "statement": "NON-REPRESENTATIVE SAMPLE: findings in excluded packets were not synthesised; every "
                             "mandatory manifest item remains in scope. Not a review of the corpus."}

    def run(self):
        from .synthesis_bounded import AlignmentRequired
        plan = self.plan()
        alignment = {**self.registry.alignment(self.packets), "planning": plan, "fingerprint": self.identity,
                     "sample": self.sample_block()}
        if not self.approve(self.identity, alignment):
            raise AlignmentRequired("CP_SYN thematic alignment approval required before GROUP calls (sample)")
        for packet in self.packets:
            self.group(packet)
        self.reconcile()
        self.final()
        pkg = self.assemble()
        if pkg["status"] != "COMPLETE":
            raise JobStopped("sample evidence accounting incomplete; CP3 blocked")
        return pkg

    def assemble(self):
        pkg = super().assemble()
        block = self.sample_block()
        out = set(block["excluded_finding_ids"])
        disp = pkg["finding_dispositions"]
        for fid in out:
            if disp.get(fid) == ["UNACCOUNTED"]:
                disp[fid] = [OUT_OF_SCOPE]
        pkg["findings_unaccounted"] = [f for f, u in disp.items() if u == ["UNACCOUNTED"]]
        st = self.ledger.state()
        completed = set(st["committed"])
        needed = {t for t, _ in self.reconciliation_payloads()} if pkg["propositions"] else set()
        done = "FINAL" in completed and needed <= completed
        pkg["status"] = ("COMPLETE" if done and not pkg["coverage_incomplete_item_ids"] and not pkg["findings_unaccounted"]
                         else "INCOMPLETE")
        pkg["sample"] = block
        pkg["warnings"] = [f"{LABEL}: {block['statement']}"] + [w for w in pkg["warnings"] if not w.startswith(LABEL)]
        return pkg


# ---------------------------------------------------------------- PLAN import
def _raw_json(text: str):
    try:
        return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return None


def repair_audit(raw, repaired) -> dict:
    """Field-level account of what the researcher repair changed (code-computed, not a judgment)."""
    changes = []

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    changes.append({"path": path + [k], "change": "ADDED", "repaired": b[k]})
                elif k not in b:
                    changes.append({"path": path + [k], "change": "REMOVED", "original": a[k]})
                else:
                    walk(a[k], b[k], path + [k])
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for n, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + [n])
        elif isinstance(a, list) and isinstance(b, list):
            changes.append({"path": path, "change": "LIST_LENGTH_CHANGED", "original_length": len(a),
                            "repaired_length": len(b), "removed": [x for x in a if x not in b],
                            "added": [y for y in b if y not in a]})
        elif a != b:
            changes.append({"path": path, "change": "CHANGED", "original": a, "repaired": b})
    if raw is None:
        return {"original_parsed": False, "changes": []}
    walk(raw, repaired, [])
    return {"original_parsed": True, "change_count": len(changes), "changes": changes}


def import_repaired_plan(run, *, source_step=V10_PLAN_STEP, raw_sha=V10_RAW_SHA, repaired_sha=V10_REPAIRED_SHA,
                         live=False) -> dict:
    """Import a researcher-repaired PLAN into this run's (sample) A07 job, through the production PLAN validators.
    Refuses on any hash mismatch, a changed evidence registry, an existing PLAN, or a live runtime without --live.
    The result is NOT approved: GROUP stays blocked until approve_plan_import."""
    guard_live(live)
    m = re.fullmatch(r"A07-SYN_job([0-9a-f]{16})_PLAN", source_step)
    if not m:
        raise SampleRefused("source step must be an A07 PLAN step")
    out_dir = run.dir / "outputs"
    raw_p, rep_p, rec_p = (out_dir / f"{source_step}.raw0.txt", out_dir / f"{source_step}.repaired.json",
                           out_dir / f"{source_step}.provider.receipt0.json")
    for p in (raw_p, rep_p, rec_p):
        if not p.exists():
            raise SampleRefused(f"missing {p.name}")
    got_raw, got_rep = sha256_file(raw_p), sha256_file(rep_p)
    if got_raw != raw_sha or got_rep != repaired_sha:
        raise SampleRefused(f"hash mismatch: raw0 {got_raw} (expected {raw_sha}), repaired {got_rep} "
                            f"(expected {repaired_sha}); nothing imported")
    receipt = json.loads(rec_p.read_text(encoding="utf-8"))
    private = receipt.get("private_raw_response_path")
    private_sha = sha256_file(private) if private and Path(private).is_file() else None
    if private_sha and receipt.get("raw_response_sha256") and private_sha != receipt["raw_response_sha256"]:
        raise SampleRefused("private provider response does not match its receipt hash")
    source_job = run.dir / "data" / f"synthesis_job_{m.group(1)}"
    if not (source_job / "registry.json").exists() or not (source_job / "identity.json").exists():
        raise SampleRefused("source A07 job snapshot missing")

    job, tag = run._synthesis_job()
    if fingerprint(json.loads((source_job / "registry.json").read_text(encoding="utf-8"))) != job.registry.digest:
        raise SampleRefused("evidence registry differs from the one the PLAN was generated against")
    repaired = json.loads(rep_p.read_text(encoding="utf-8"))
    audit = repair_audit(_raw_json(raw_p.read_text(encoding="utf-8")), repaired)
    audit_p = job.dir / "plan_repair_audit.json"
    if audit_p.exists():
        raise SampleRefused("repair audit already exists for this job; refusing overwrite")
    audit_p.write_text(canonical(audit), encoding="utf-8")
    from .agents.base import build_system_prompt
    manifest = REPO_ROOT / "frozen_runtime_manifest.json"
    rel = lambda p: str(Path(p).relative_to(run.dir)).replace("\\", "/")
    provenance = {
        "version": VERSION, "origin": "RESEARCHER_REPAIR_OF_MODEL_OUTPUT", "source_step": source_step,
        "source_job_tag": m.group(1),
        "source_identity_fingerprint": json.loads((source_job / "identity.json").read_text(encoding="utf-8"))["fingerprint"],
        "target_job_tag": tag, "target_identity_fingerprint": job.identity, "registry_digest": job.registry.digest,
        "original_raw_path": rel(raw_p), "original_raw_sha256": got_raw,
        "repaired_path": rel(rep_p), "repaired_sha256": got_rep,
        "receipt_path": rel(rec_p), "receipt_sha256": sha256_file(rec_p),
        "provider_response_id": receipt.get("id"), "provider_stop_reason": receipt.get("stop_reason"),
        "private_provider_response_path": private, "private_provider_response_sha256": private_sha,
        "repair_audit_path": rel(audit_p), "repair_audit_sha256": sha256_file(audit_p),
        "a07_prompt_sha256": hashlib.sha256(build_system_prompt("A07-SYN").encode("utf-8")).hexdigest(),
        "plan_schema_sha256": sha256_file(SCHEMAS_DIR / "A07-SYN.bounded-plan.schema.json"),
        "runtime_manifest_sha256": sha256_file(manifest) if manifest.exists() else None,
        "sample": (job.sample_block() if isinstance(job, SampleSynthesisJob) else None),
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "Prompt/schema of the running code may differ from the v10 prompt that produced the original; both "
                "identities are recorded. Import is not approval."}
    try:
        record = job.import_plan(repaired, provenance)
    except Exception:
        audit_p.unlink(missing_ok=True)
        raise
    run.prov.tool_run("plan_import", f"A07-SYN_job{tag}_PLAN",
                      {"repaired_sha256": got_rep, "original_raw_sha256": got_raw, "approved": False})
    return {"job_tag": tag, "record": record, "job_dir": str(job.dir)}


def approve_plan_import(run, repaired_sha: str, approved_by: str, live=False) -> dict:
    """The researcher's explicit approval of the imported repaired PLAN (exact SHA-256). Never run by code."""
    guard_live(live)
    if not approved_by.strip():
        raise SampleRefused("named approver required")
    job, tag = run._synthesis_job()
    marker = job._marker("PLAN")
    if not marker or marker["event"] != "TURN_IMPORTED_REPAIR":
        raise SampleRefused("no imported repaired PLAN in this job")
    if marker["repaired_sha256"] != repaired_sha:
        raise SampleRefused("approval names a different repaired PLAN")
    path = job.dir / IMPORT_APPROVAL
    if path.exists():
        raise SampleRefused("an approval already exists; refusing overwrite")
    approval = {"researcher_approved": True, "repaired_sha256": repaired_sha,
                "import_record_sha256": marker["import_record_sha256"], "approved_by": approved_by,
                "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "scope": "PLAN only; CP_SYN, CP3, CP_LEDGER and stage financial authorizations remain separate"}
    path.write_text(canonical(approval), encoding="utf-8")
    run.prov.human_decision("PLAN_IMPORT", {"repaired_sha256": repaired_sha, "approved_by": approved_by},
                            "Researcher-approved repaired PLAN; GROUP may proceed after CP_SYN")
    return approval


# ---------------------------------------------------------------- pricing
def worst_case_usd(budget, model, input_bound: int, output_reserve: int) -> float:
    """Cold worst case: every input token at the cache-WRITE rate (1h for Anthropic, which is above the input
    rate; OpenAI's cache write is also above input), every output token at the output rate."""
    from .writing_admission import worst_case_usd as shared
    usd = shared(budget, model, input_bound, output_reserve)
    if usd is None:
        raise SampleRefused(f"unpriced model {model.model}")
    return usd


def a07_group_limit(job) -> int:
    """Bytes an ACCEPTED GROUP output can occupy: _run_turn refuses offline_tokens(out) > the GROUP cap."""
    return job.limit("GROUP") - 1024


def a07_envelopes(job, n_groups_left: list[dict]) -> list[dict]:
    """Strict-by-construction input bounds for RECONCILE and FINAL before the GROUP outputs exist.

    Each accepted GROUP output is at most limit-1024 bytes (the output-allowance guard), and every byte of a
    compact proposition or gap index comes from that output plus code-added identifiers. Registry-derived
    parts (global independence, conflict index, theme framework) are serialized exactly."""
    committed = [t for t in job.ledger.state()["committed"] if t.startswith("GROUP_") and "_LOOKUP" not in t]
    real = [compact_proposition(p) for p in job._all_props()]
    groups_total = len(committed) + len(n_groups_left)
    pad = len(n_groups_left) * (a07_group_limit(job) + 12 * 160)   # 160 B/proposition of code-added IDs
    max_props = len(real) + 12 * len(n_groups_left)
    pages = max(1, math.ceil(max_props / int(job.cfg.get("reconcile_page_size", 32))))
    exact = {"global_independence": job.registry.independence(sorted(job.finding_ids)),
             "mandatory_conflict_index": [{"item_id": i, "findings": sorted(job.registry.item_findings(i))}
                                          for i in job.mandatory if job.mandatory[i]["kind"] == "CONFLICT"],
             "retrieval": {"available": True, "operations": ["finding_ids", "query"]}}
    index_bytes = len(canonical(real).encode("utf-8")) + pad
    gap_bytes = len(canonical([{k: g.get(k) for k in ("gap_id", "statement", "source_item_ids", "established_by")}
                               for g in job._gaps()]).encode("utf-8"))
    issue_bytes = len(canonical(job._issues()).encode("utf-8"))
    rows = []
    for n in range(1, pages + 1):
        payload = {"mode": "RECONCILE", "focus": [], "global_proposition_index": [], **exact}
        bound = job.count(payload) + 2 * index_bytes   # focus is a subset of the global index
        rows.append({"turn": f"RECONCILE_{n:04d}", "mode": "RECONCILE", "input_bound": bound,
                     "basis": f"ENVELOPE: exact registry parts + 2 x index bound ({groups_total} groups, <= {max_props} propositions)"})
    rec_out = pages * (job.limit("RECONCILE") - 1024)
    final_payload = {"mode": "FINAL", "proposition_index": [], "reconciliation": [], "coverage_pending": [],
                     "theme_framework": job.registry.framework, "knowledge_gap_index": []}
    rows.append({"turn": "FINAL", "mode": "FINAL",
                 "input_bound": job.count(final_payload) + index_bytes + gap_bytes + issue_bytes + rec_out,
                 "basis": "ENVELOPE: exact framework + proposition/gap index bound + all RECONCILE output bounds"})
    return rows


@contextlib.contextmanager
def no_network():
    """Every provider route, SDK client and socket connect raises. Used by the dry run (and its test)."""
    import socket
    from .llm import router, anthropic_client, openai_compatible
    saved_p = dict(router._PROVIDERS)
    saved_a, saved_o = anthropic_client._get_client, openai_compatible._get_client
    saved_c = socket.socket.connect

    def refuse(*a, **k):
        raise SampleRefused("dry run: provider access refused")
    try:
        for k in list(router._PROVIDERS):
            router._PROVIDERS[k] = refuse
        anthropic_client._get_client = refuse
        openai_compatible._get_client = refuse
        socket.socket.connect = refuse
        yield
    finally:
        router._PROVIDERS.clear()
        router._PROVIDERS.update(saved_p)
        anthropic_client._get_client, openai_compatible._get_client = saved_a, saved_o
        socket.socket.connect = saved_c


def scratch_clone(run):
    """A throwaway copy of the run folder, re-pointed, so a dry run never writes to the real run."""
    from .budget import BudgetTracker
    from .provenance import ProvenanceLog
    tmp = Path(tempfile.mkdtemp(prefix="a07-sample-dry-"))
    target = tmp / run.dir.name
    shutil.copytree(run.dir, target)
    clone = copy.copy(run)
    clone.dir, clone.budget, clone.prov = target, BudgetTracker(target), ProvenanceLog(target)
    clone.budget.prices = run.budget.prices
    if getattr(run.budget, "operational_ceiling", None) is not None:
        clone.budget.operational_ceiling = run.budget.operational_ceiling
    return clone, tmp


def a07_rows(run, job) -> list[dict]:
    """Remaining A07 calls of this (sample) job: exact GROUP requests; RECONCILE/FINAL exact once their inputs
    exist, else envelopes. Retrieval lookups are excluded (contingency, never automatic in the base path)."""
    state = job.ledger.state()["committed"]
    rows = []
    left = [p for p in job.packets if f"GROUP_{p['group_id']}" not in state]
    for p in left:
        payload = job.registry.packet_payload(p)
        rows.append({"turn": f"GROUP_{p['group_id']}", "mode": "GROUP", "input_bound": job.count(payload),
                     "basis": "EXACT: serialized request byte bound (production packet builder)"})
    if not left:
        for turn, payload in job.reconciliation_payloads():
            if turn not in state:
                rows.append({"turn": turn, "mode": "RECONCILE", "input_bound": job.count(payload),
                             "basis": "EXACT: serialized request byte bound"})
        recon_done = all(t in state for t, _ in job.reconciliation_payloads())
        if "FINAL" not in state:
            if recon_done:
                rows.append({"turn": "FINAL", "mode": "FINAL", "input_bound": job.count(job.final_payload()),
                             "basis": "EXACT: serialized request byte bound"})
            else:
                rows += [r for r in a07_envelopes(job, []) if r["mode"] == "FINAL"]
    else:
        rows += a07_envelopes(job, left)
    m = run.route("A07-SYN")
    for r in rows:
        cap = job.limit(r["mode"])
        r.update(step=f"A07-SYN_job{job.dir.name.split('_')[-1]}_{r['turn']}", agent="A07-SYN", model=m.model,
                 output_cap=cap, usd=worst_case_usd(run.budget, m, r["input_bound"], cap))
    return rows


def _envelope_section_payload(run, pkg, findings, corpus, words_before: int) -> dict:
    """A09 request for ONE section holding every element of the sample package (real bridge builders), plus
    `words_before` words of earlier prose. Any 1-2 section split of the same package sends a subset of these
    records and findings, so this is the conditional upper envelope before A08 has planned."""
    from . import bridge
    els = bridge.elements(pkg)
    kind = {"PROPOSITION": "PROPOSITION", "GAP": "GAP", "AUTHOR_INTERPRETATION": "AUTHOR_INTERPRETATION"}
    items = [{"item_id": e, "item_type": kind.get(els[e]["kind"], "PROPOSITION"), "group": None,
              "note_to_writer": None} for e in els]
    section = {"section_id": "S_ENVELOPE", "level": 1, "heading": "Envelope", "heading_kind": "DESCRIPTIVE",
               "heading_proposition_ids": [], "purpose": "pricing envelope", "word_budget": 1000, "theme_ids": [],
               "ordered_items": items, "display_item_ids": [], "transition_in": "", "transition_out": "",
               "wording_restrictions": []}
    plan = {"title": {"text": "", "proposition_ids": []}, "sections": [section], "writing_order": ["S_ENVELOPE"],
            "display_items": [], "abstract_plan": {"target_words": 0, "ordered_proposition_ids": [],
                                                    "contribution_statement": ""}, "keywords": []}
    ledger = [{"item_id": e, "outcome": "DISCUSSED", "section_id": "S_ENVELOPE", "grouped_with": [], "reason": None}
              for e in els]
    register = run._contrary_register(pkg, findings, plan, ledger)
    packet = bridge.section_packets(plan, ledger, pkg, findings, corpus, register)["S_ENVELOPE"]
    previous = [{"section_id": "S_PREV", "heading": "", "text_markdown": "x" * (8 * words_before)}] if words_before else []
    return bridge.writer_payload(plan, packet, previous, bridge.argument_map(pkg, corpus, findings), run._journal(), None)


def a08_a09_rows(run, sample: dict) -> list[dict]:
    """A08 outline and the sample's A09 sections, at cold worst case. Exact once their inputs exist; before
    A08/CP_LEDGER the A09 rows are a labelled conditional envelope; before CP3 everything is UNDETERMINED."""
    import dataclasses
    from . import admission, bridge
    from .agents.base import build_system_prompt
    from .orchestrator import Pause
    rows = []
    a_cfg = run.cfg.get("admission") or {}
    m8 = dataclasses.replace(run.route("A08-OL"), max_tokens=sample["a08_max_tokens"])
    m9 = dataclasses.replace(run.route("A09-WRI"), max_tokens=sample["a09_max_tokens"], effort=sample["a09_effort"])
    pkg = run.load("synthesis_approved.json")
    if pkg is None:
        rows.append({"step": "A08-OL_outline", "agent": "A08-OL", "model": m8.model, "undetermined": True,
                     "basis": "UNDETERMINED until CP3 approves the synthesis package"})
        for n in range(sample["max_sections"]):
            rows.append({"step": f"A09-WRI_sample1_S{n+1}", "agent": "A09-WRI", "model": m9.model, "undetermined": True,
                         "basis": "UNDETERMINED until A08 and CP_LEDGER"})
        return rows
    return priced_writing_rows(run, sample, pkg, m8, m9, a_cfg)


def priced_writing_rows(run, sample, pkg, m8, m9, a_cfg) -> list[dict]:
    from . import admission, bridge
    from .agents.base import build_system_prompt
    from .orchestrator import Pause
    rows = []
    findings, corpus = run._findings() or [], run.load("selected_corpus.json", [])
    plan = run.load("manuscript_plan.json")
    ps = None
    if plan is not None:
        try:
            ps = run._plan_state()
        except Pause:
            ps = None
    if plan is None:
        table = bridge.comparative_table(pkg, findings, corpus, int(run._bridge_cfg().get("table_max_rows", 25)))
        payload = run._outline_payload(pkg, corpus, run._journal(), table, run._bridge_cfg(), findings)
        inp = admission.input_bound(build_system_prompt("A08-OL"), payload)
        out = admission.output_reserve(m8, a_cfg)
        rows.append({"step": "A08-OL_outline", "agent": "A08-OL", "model": m8.model, "input_bound": inp,
                     "output_cap": out, "usd": worst_case_usd(run.budget, m8, inp, out),
                     "basis": "EXACT: serialized outline request byte bound"})
    out9 = admission.output_reserve(m9, a_cfg)
    if ps is None:
        for n in range(sample["max_sections"]):
            payload = _envelope_section_payload(run, pkg, findings, corpus, sample["max_words"] * n)
            inp9 = admission.input_bound(build_system_prompt("A09-WRI"), payload)
            rows.append({"step": f"A09-WRI_sample1_S{n+1}", "agent": "A09-WRI", "model": m9.model,
                         "input_bound": inp9, "output_cap": out9, "usd": worst_case_usd(run.budget, m9, inp9, out9),
                         "basis": "ENVELOPE: every element of the sample package in one section packet (real builders)"})
        return rows
    done_prose = []
    for sid in ps["plan"]["writing_order"]:
        payload = bridge.writer_payload(ps["plan"], ps["packets"][sid], done_prose, ps["amap"], ps["journal"], None)
        inp = admission.input_bound(build_system_prompt("A09-WRI"), payload)
        rows.append({"step": f"A09-WRI_sample1_{sid}_r0", "agent": "A09-WRI", "model": m9.model, "input_bound": inp,
                     "output_cap": out9, "usd": worst_case_usd(run.budget, m9, inp, out9),
                     "basis": "EXACT packet; earlier prose bounded at max_words x 8 bytes"})
        done_prose.append({"section_id": sid, "heading": "", "text_markdown": "x" * (sample["max_words"] * 8)})
    return rows


def projection(run, stage, candidate=None, in_flight=frozenset()):
    """Pilot stage projection for a sample run: only calls the sample can make, at cold worst case, with the
    pilot's 30% margin (pilot.admit). No retry allowance: the sample never retries automatically."""
    from . import pilot_authorization as pilot
    from .singlepaper_eval import WritingRun
    wr = run if isinstance(run, WritingRun) or getattr(run, "sample", None) else WritingRun(run.id)
    sample = policy(wr)
    if stage == pilot.STAGE_1:
        job, _ = wr._synthesis_job()
        lines = [r for r in a07_rows(wr, job)]
    elif stage == pilot.STAGE_2:
        lines = [r for r in a08_a09_rows(wr, sample)]
        if any(r.get("undetermined") for r in lines):
            raise pilot.AuthorizationRequired("Stage 2 sample projection is undetermined until CP3; authorize after CP3")
    else:
        raise pilot.AuthorizationRequired("Unknown pilot stage")
    if candidate:
        agent = candidate[0]
        mine = next((n for n, r in enumerate(lines) if r["agent"] == agent), None)
        if mine is None:
            raise pilot.AuthorizationRequired("Candidate call is not in the sample projection")
        lines = lines[:mine] + lines[mine + 1:]
    future = sum(Decimal(str(r["usd"])) for r in lines)
    committed = Decimal(str(run.budget.reserved())) + Decimal(str(candidate[1] if candidate else 0))
    out = pilot.admit(run.budget.spent(), committed, future)
    return {**out, "scope": stage, "basis": "SAMPLE_COLD_WORST_CASE", "label": LABEL,
            "lines": [{"stage": r["agent"], "step": r["step"], "usd": float(r["usd"]), "calls": 1,
                       "basis": r["basis"], "input_bound": r.get("input_bound"), "output_cap": r.get("output_cap")}
                      for r in lines],
            "projected_remaining_usd": float(MARGIN * future), "papers": 1, "retry_share": 0.0}


def dry_run(run, out=print) -> dict:
    """Lists the gates and the next paid calls with their reservations. No provider route is reachable and the
    real run folder is never written (everything runs on a scratch copy that is deleted afterwards)."""
    from . import checkpoints
    sample = policy(run)
    if sample is None:
        raise SampleRefused("not a sample run (no input/a07_a09_sample.json)")
    with no_network():
        clone, tmp = scratch_clone(run)
        try:
            job, tag = clone._synthesis_job()
            marker = job._marker("PLAN")
            gates = {"plan_imported": bool(marker and marker["event"] == "TURN_IMPORTED_REPAIR"),
                     "plan_import_approved": False, "cp_syn_approved": False}
            if gates["plan_imported"]:
                try:
                    job.require_import_approval(marker)
                    gates["plan_import_approved"] = True
                except ImportApprovalRequired:
                    pass
            d = checkpoints.approved(clone.dir, "CP_SYN")
            gates["cp_syn_approved"] = bool(d and d.get("fingerprint") == job.identity and d.get("approve_alignment") is True)
            rows = a07_rows(clone, job) + a08_a09_rows(clone, sample)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    spent = Decimal(str(run.budget.spent()))
    base = getattr(run, "baseline", None)
    sub_left = Decimal("15") - (spent - Decimal(str(base))) if base is not None else None
    pilot_left = Decimal("35") - spent
    out(f"{LABEL} dry run: job {tag}; groups {sample['group_ids']}; gates {gates}")
    cum = Decimal(0)
    for r in rows:
        if r.get("undetermined"):
            out(f"  {r['step']:<44} {r['model']:<16} {r['basis']}")
            continue
        held = Decimal(str(r["usd"])) * MARGIN
        cum += held
        r["usd_with_margin"], r["cumulative_with_margin"] = float(held), float(cum)
        out(f"  {r['step']:<44} {r['model']:<16} in<={r['input_bound']:>8,} cap {r['output_cap']:>6,} "
            f"${r['usd']:.4f} +30% ${held:.4f} cum ${cum:.4f}  [{r['basis']}]")
    out(f"  writing sub-cap left ${sub_left}; pilot cap left ${pilot_left}; "
        f"fits sub-cap: {sub_left is not None and cum <= sub_left}")
    return {"gates": gates, "rows": rows, "cumulative_with_margin": float(cum),
            "subcap_left": float(sub_left) if sub_left is not None else None, "pilot_left": float(pilot_left)}


def check_outline(plan: dict, sample: dict) -> list[str]:
    """The researcher-approved sample outline bounds (A08 must plan 1-2 sections and 800-1000 words)."""
    problems = []
    sections = plan.get("sections") or []
    if not 1 <= len(sections) <= sample["max_sections"]:
        problems.append(f"{len(sections)} sections planned; the sample allows 1-{sample['max_sections']}")
    words = sum(int(s.get("word_budget") or 0) for s in sections)
    if not sample["min_words"] <= words <= sample["max_words"]:
        problems.append(f"{words} words planned; the sample allows {sample['min_words']}-{sample['max_words']}")
    return problems
