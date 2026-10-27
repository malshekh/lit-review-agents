"""Checks behind `litreview check`: configuration, API keys, and (optionally) live connectivity."""
from __future__ import annotations

import os

from .. import config
from ..agents import AGENTS

OK, BAD, INFO = "✓", "✗", "·"


def config_lines() -> tuple[list[str], bool, set[str]]:
    lines, ok, providers = [], True, set()
    prices = config.load("prices")
    allow = config.load("pipeline")["run"].get("allow_unpriced_models", False)
    for aid in AGENTS:
        try:
            m = config.agent_model(aid)
        except ValueError as e:
            lines.append(f"  {BAD} {e}")
            ok = False
            continue
        providers.add(m.provider)
        p = prices.get(m.model) or {}
        priced = p.get("input") is not None and p.get("output") is not None
        price = f"${p['input']:.2f} / ${p['output']:.2f} per M" if priced else "no price in config/prices.yaml"
        lines.append(f"  {OK if priced or allow else BAD} {aid:8s} {m.provider:9s} {m.model:18s} {price}")
        ok &= priced or allow
    gaps = {}
    for aid in AGENTS:
        try:
            model = config.agent_model(aid).model
        except ValueError:
            continue
        missing = [k for k in ("cached_input", "cache_write") if (prices.get(model) or {}).get(k) is None]
        if missing:
            gaps[model] = missing
    for model, missing in sorted(gaps.items()):
        lines.append(f"  {INFO} {model:18s} no {' or '.join(missing)} rate: billed at the input price until set")
    from .. import model_record
    blocked = model_record.blocked()
    for family, models in sorted(model_record.summary().items()):
        refused = [f"{m} ({c['REFUSED']})" for m, c in sorted(models.items()) if c["REFUSED"]]
        lines.append(f"  {INFO} topic family '{family}': {sum(c['COMPLETED'] for c in models.values())} completed calls; "
                     f"refused: {', '.join(refused) or 'none'}"
                     + (f"; no qualified model recorded for {', '.join(blocked[family])}" if family in blocked else ""))
    return lines, ok, providers


def key_lines(providers: set[str]) -> tuple[list[str], bool]:
    lines, ok = [], True
    pcfg = config.load("pipeline")["providers"]
    for prov in sorted(providers):
        env = pcfg[prov]["key_env"]
        has = bool(os.environ.get(env))
        lines.append(f"  {OK if has else BAD} {env:20s} {'set' if has else 'missing in .env'}  ({prov})")
        ok &= has
    optional = {
        "NCBI_API_KEY": "PubMed/PubTator3 rate limit 3 -> 10 requests/s",
        "S2_API_KEY": "Semantic Scholar rate limit",
        "OPENALEX_EMAIL": "OpenAlex polite pool",
        "UNPAYWALL_EMAIL": "Unpaywall (open-access locations)",
        "SMTP_USER": "email notifications",
        "NOTIFY_EMAIL_TO": "email notifications",
    }
    for env, why in optional.items():
        lines.append(f"  {OK if os.environ.get(env) else INFO} {env:20s} "
                     f"{'set' if os.environ.get(env) else 'not set (optional)'} — {why}")
    db_cfg = (config.load("sources").get("normalization_services") or {}).get("drugbank") or {}
    if db_cfg.get("enabled"):
        has = bool(os.environ.get(db_cfg.get("key_env") or "DRUGBANK_API_KEY"))
        lines.append(f"  {OK if has else BAD} DRUGBANK_API_KEY     {'set' if has else 'missing'} "
                     "(DrugBank enabled in config/sources.yaml)")
        ok &= has
    else:
        lines.append(f"  {INFO} DrugBank             off (licensed; enable in config/sources.yaml)")
    tracing = os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
    if tracing:
        has = bool(os.environ.get("LANGSMITH_API_KEY"))
        lines.append(f"  {OK if has else BAD} LANGSMITH_API_KEY    {'set' if has else 'missing'} "
                     f"(tracing on, project: {os.environ.get('LANGSMITH_PROJECT', 'default')})")
        ok &= has
    else:
        lines.append(f"  {INFO} LangSmith tracing    off (set LANGSMITH_TRACING=true to enable)")
    return lines, ok


def ping_llms(providers: set[str]) -> tuple[list[str], bool]:
    """One tiny call per provider in use (a fraction of a cent each)."""
    from ..llm import complete
    lines, ok = [], True
    seen = set()
    targets = []   # (model, label): one per provider in use, plus every routing alternate
    for aid in AGENTS:
        m = config.agent_model(aid)
        if m.provider not in seen:
            seen.add(m.provider)
            targets.append((m, ""))
    pinged = {m.model for m, _ in targets}
    for aid in AGENTS:
        for alt in config.agent_candidates(aid)[1:]:
            if alt.model not in pinged:
                pinged.add(alt.model)
                targets.append((alt, f"  (alternate for {aid})"))
    for m, label in targets:
        try:
            r = complete(m.provider, system="Reply with the JSON object {\"ok\": true} and nothing else.",
                         user="ping", model=m.model, max_tokens=200, temperature=0.0, trace={"agent": "healthcheck"})
            good = "ok" in r.text
            lines.append(f"  {OK if good else BAD} {m.provider:9s} {m.model:18s} replied "
                         f"({r.input_tokens} in / {r.output_tokens} out tokens){label}")
            ok &= good
        except Exception as e:  # noqa: BLE001 — report any failure to the user
            lines.append(f"  {BAD} {m.provider:9s} {m.model:18s} {type(e).__name__}: {str(e)[:150]}{label}")
            ok = False
    return lines, ok


def ping_sources() -> tuple[list[str], bool]:
    from .literature import enabled_sources, search
    from .normalization import chembl, drugbank, drugbank_settings, hgnc, ols
    tests = {"pubmed": "biosensor[tiab]", "europepmc": "biosensor", "pubtator3": "@GENE_TP53",
             "openalex": "title_and_abstract.search:biosensor", "semanticscholar": "biosensor",
             "clinicaltrials": "cond:diabetes"}
    lines, ok = [], True
    for src in enabled_sources():
        res = search(src, tests.get(src, "biosensor"), "HEALTHCHECK", 1)
        good = not res.error and res.records
        lines.append(f"  {OK if good else BAD} {src:16s} "
                     f"{'reachable, ' + str(res.hit_count) + ' hits' if good else (res.error or 'no records')}")
        ok &= bool(good)
    for name, fn in (("HGNC", lambda: hgnc("TP53")), ("ChEMBL", lambda: chembl("aspirin")),
                     ("OLS4", lambda: ols("asthma", "mondo"))):
        try:
            r = fn()
            good = r["normalization_state"] == "RESOLVED"
            lines.append(f"  {OK if good else BAD} {name:16s} {r['normalization_state']} {r.get('normalized_id') or ''}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"  {BAD} {name:16s} {type(e).__name__}: {str(e)[:120]}")
            good = False
        ok &= good
    if drugbank_settings():
        try:
            r = drugbank("aspirin")
            good = r["drugbank_state"] == "RESOLVED"
            lines.append(f"  {OK if good else BAD} {'DrugBank':16s} {r['drugbank_state']} {r.get('drugbank_id') or ''}"
                         + ("" if r.get("drugbank_groups") else "  (no approval groups in response: "
                                                                 "check the API product/shape)" if good else ""))
        except Exception as e:  # noqa: BLE001
            lines.append(f"  {BAD} {'DrugBank':16s} {type(e).__name__}: {str(e)[:120]}")
            good = False
        ok &= good
    return lines, ok
