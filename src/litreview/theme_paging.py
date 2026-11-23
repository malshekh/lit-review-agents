"""A06 PER_THEME in bounded packets, then one reconciliation across the whole theme.

One PER_THEME call used to carry every finding of its theme. At 120 papers that is about 300,000 input tokens and
more output than the cap allows, so it would have been truncated. Splitting alone is not safe either: a
contradiction, a study reported twice or a qualifying result can sit in two different packets. So the pass has
two levels, and code checks both:

  1. PACKET   Each packet audits a bounded set of findings in full. It also receives a compact index of EVERY
              finding in the theme, so it can name findings outside its packet that look like a conflict, the same
              study, or a qualification (`cross_packet_candidates`). It decides nothing about them.
  2. RECONCILE  One call receives every packet's result, the same global index, and the full original findings
              named in any packet conflict or cross-packet candidate. It may ask for more originals
              (`retrieval_requests`), bounded by validation.theme_paging.max_retrieval_rounds. It returns the
              ordinary PER_THEME record for the whole theme.

Packets are sized by estimated input tokens and expected output tokens, never by a count of papers or findings,
and never by dropping content: every finding of the theme is in exactly one packet (checked), a single finding
too large for a packet stops the run, and every conflict a packet recorded must reappear in the reconciled
record or be listed there with the reason it was not retained (checked).
"""
from __future__ import annotations

import json
import re

INDEX_FIELDS = ("finding_id", "record_id", "subthemes", "subject", "predicate", "object", "polarity", "direction",
                "modality", "assertion_type", "disposition")
CONTEXT_FIELDS = ("evidence_system", "species", "cell_line_or_type", "agent", "comparator", "readout", "population")
PACKET_TASK = ("This is one packet of a theme that is audited in several packets. Audit the findings in "
               "`validated_findings` exactly as in PER_THEME. `theme_index` lists every finding of the theme in "
               "compact form, including those in other packets: you cannot assess them, but when one looks like a "
               "conflict with, the same study as, or a qualification of a finding in this packet, name the pair in "
               "`cross_packet_candidates` ([{finding_ids, kind: POSSIBLE_CONFLICT | POSSIBLE_SAME_STUDY | QUALIFIES, "
               "reason}]). Report conflicts, independence and evidence_reach for this packet's findings only.")
RECONCILE_TASK = ("Reconcile the packet results into ONE PER_THEME record for the whole theme. `packet_results` are the "
                  "packet audits; `theme_index` lists every finding; `validated_findings` holds the full originals of "
                  "every finding named in a packet conflict or cross-packet candidate. Decide each cross-packet "
                  "candidate from the originals. Keep every packet conflict, or list it in "
                  "`packet_conflicts_not_retained` ([{finding_ids, reason}]). Merge independence counts across packets: "
                  "the same study in two packets is one study. If you need the full text of a finding that is only in "
                  "the index, return its ID in `retrieval_requests` and decide nothing about it yet.")


class PagingError(ValueError):
    """The theme cannot be paged without losing content; the run stops for the researcher."""


def settings(cfg: dict) -> dict | None:
    s = ((cfg.get("validation") or {}).get("theme_paging") or {})
    return s if s.get("enabled") else None


def est_tokens(obj, bytes_per_token: float) -> int:
    return int(len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) / bytes_per_token) + 1


def index_entry(f: dict) -> dict:
    ctx = f.get("context") or {}
    out = {k: f.get(k) for k in INDEX_FIELDS if f.get(k) not in (None, [], "")}
    out.update({k: ctx[k] for k in CONTEXT_FIELDS if ctx.get(k) not in (None, "", "NOT_REPORTED")})
    return out


def packets(findings: list[dict], s: dict, output_cap: int, overhead_tokens: int) -> list[list[dict]]:
    """Findings in packets that each fit the input budget and the expected-output budget. Findings of one paper
    stay adjacent (order: record, then finding), which keeps a study's own results together where they fit."""
    bpt = float(s.get("bytes_per_token", 2.1))
    room_in = int(s["max_input_tokens"]) - overhead_tokens
    room_out = int(output_cap * float(s.get("output_share_of_cap", 0.6)))
    per_out = float(s.get("output_tokens_per_finding", 165))
    if room_in <= 0:
        raise PagingError(f"the theme's fixed inputs alone ({overhead_tokens:,} tokens: prompt, index, records) exceed "
                          f"validation.theme_paging.max_input_tokens ({s['max_input_tokens']:,})")
    ordered = sorted(findings, key=lambda f: (str(f.get("record_id")), str(f.get("finding_id"))))
    out: list[list[dict]] = []
    current, used_in, used_out = [], 0, 0.0
    for f in ordered:
        size = est_tokens(f, bpt)
        if size > room_in:
            raise PagingError(f"finding {f.get('finding_id')} alone is about {size:,} tokens, more than a packet can "
                              f"hold ({room_in:,}); it is not truncated or dropped. Raise max_input_tokens or review it.")
        if current and (used_in + size > room_in or used_out + per_out > room_out):
            out.append(current)
            current, used_in, used_out = [], 0, 0.0
        current.append(f)
        used_in += size
        used_out += per_out
    if current:
        out.append(current)
    return out


def needs_paging(findings: list[dict], s: dict, output_cap: int, overhead_tokens: int) -> bool:
    return len(packets(findings, s, output_cap, overhead_tokens)) > 1


def slug(theme: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", theme)[:40]


def check_packet(out: dict, packet_ids: set[str], theme_ids: set[str]) -> None:
    for c in out.get("conflicts") or []:
        if not c.get("finding_ids") or set(c["finding_ids"]) - packet_ids:
            raise PagingError("a packet recorded a conflict that names a finding outside its packet; cross-packet "
                              "pairs belong in cross_packet_candidates")
    for c in out.get("cross_packet_candidates") or []:
        ids = set(c.get("finding_ids") or [])
        if len(ids) < 2 or ids - theme_ids or not (ids & packet_ids):
            raise PagingError("a cross-packet candidate must name at least two findings of this theme, one of them in the packet")


def candidate_ids(results: list[dict]) -> list[str]:
    ids: list[str] = []
    for r in results:
        for c in (r.get("conflicts") or []) + (r.get("cross_packet_candidates") or []):
            ids += c.get("finding_ids") or []
    return list(dict.fromkeys(ids))


def check_reconciled(out: dict, results: list[dict], theme_ids: set[str]) -> None:
    """Nothing a packet found disappears: each packet conflict is in the reconciled conflicts (same findings, or a
    superset) or is listed as not retained with a reason."""
    kept = [set(c.get("finding_ids") or []) for c in out.get("conflicts") or []]
    dropped = [(set(c.get("finding_ids") or []), str(c.get("reason") or "").strip())
               for c in out.get("packet_conflicts_not_retained") or []]
    for ids, reason in dropped:
        if ids - theme_ids or not reason:
            raise PagingError("packet_conflicts_not_retained entries need findings of this theme and a reason")
    for r in results:
        for c in r.get("conflicts") or []:
            ids = set(c["finding_ids"])
            if not any(ids <= k for k in kept) and not any(ids == d for d, _ in dropped):
                raise PagingError(f"the reconciled theme record lost a conflict a packet recorded "
                                  f"({', '.join(sorted(ids))}): it must be kept or listed with the reason it was not")


def run(th: str, findings: list[dict], base_payload: dict, s: dict, output_cap: int, overhead_tokens: int, call,
        save=None) -> dict:
    """The paged pass for one theme. call(step_suffix, payload) -> A06 output. Returns the reconciled record."""
    bpt = float(s.get("bytes_per_token", 2.1))
    theme_ids = {f["finding_id"] for f in findings}
    by_id = {f["finding_id"]: f for f in findings}
    index = [index_entry(f) for f in sorted(findings, key=lambda f: str(f["finding_id"]))]
    parts = packets(findings, s, output_cap, overhead_tokens + est_tokens(index, bpt))
    covered = [f["finding_id"] for p in parts for f in p]
    if sorted(covered) != sorted(theme_ids) or len(covered) != len(theme_ids):
        raise PagingError("packet coverage is not exactly the theme's findings")
    n = len(parts)
    results = []
    for i, part in enumerate(parts, 1):
        ids = [f["finding_id"] for f in part]
        out = call(f"P{i:03d}of{n:03d}", {**base_payload, "validated_findings": part, "theme_index": index,
                                          "theme_packet": {"packet": i, "of": n, "finding_ids": ids, "task": PACKET_TASK}})
        check_packet(out, set(ids), theme_ids)
        results.append({"packet": i, "finding_ids": ids, **{k: out.get(k) or [] for k in
                                                           ("conflicts", "independence", "cross_packet_candidates")},
                        "evidence_reach": out.get("evidence_reach") or {}})
    originals = candidate_ids(results)
    rounds = int(s.get("max_retrieval_rounds", 2))
    record, asked = None, []
    for attempt in range(rounds + 1):
        supplied = [by_id[i] for i in dict.fromkeys(originals + asked) if i in by_id]
        payload = {**base_payload, "validated_findings": supplied, "theme_index": index, "packet_results": results,
                   "theme_reconcile": {"packets": n, "retrieval_round": attempt, "retrieval_rounds_left": rounds - attempt,
                                       "task": RECONCILE_TASK}}
        if est_tokens(payload, bpt) + overhead_tokens > int(s.get("reconcile_max_input_tokens") or 2 * int(s["max_input_tokens"])):
            raise PagingError(f"the reconciliation of theme {th} needs more originals than fit one request; review "
                              "the theme's conflicts by hand or split the theme (litreview revise-framework)")
        record = call("reconcile" + (f"_r{attempt}" if attempt else ""), payload)
        wanted = [i for i in record.get("retrieval_requests") or [] if i in by_id and i not in originals + asked]
        unknown = [i for i in record.get("retrieval_requests") or [] if i not in by_id]
        if unknown:
            raise PagingError(f"the reconciliation asked for findings that are not in theme {th}: {', '.join(unknown[:5])}")
        if not wanted:
            break
        if attempt == rounds:
            raise PagingError(f"the reconciliation of theme {th} still asks for evidence after {rounds} retrieval rounds")
        asked += wanted
    check_reconciled(record, results, theme_ids)
    proof = {"theme": th, "packets": n, "packet_finding_ids": [r["finding_ids"] for r in results],
             "findings": len(theme_ids), "originals_supplied_to_reconcile": len(dict.fromkeys(originals + asked)),
             "retrieval_rounds_used": attempt if asked else 0, "coverage": "every finding in exactly one packet"}
    if save:
        save(proof)
    return {**record, "theme_paging": proof}
