"""Evaluation-only artifacts never enter a publication workflow.

A run used to test the architecture (run 20261025-100039: synthesis on a corpus whose output was agreed in
advance to be unusable scientifically) is marked evaluation-only. Every synthesis it produces carries an
`evaluation_only` stamp in its own data, so the restriction travels with the artifact: a copied package is
still stamped. Every publication stage (CP3, outline, drafting, verification, critique, finalization)
refuses a stamped package, in this run or any other, instead of relying on a warning in a report that
another agent could load as genuine evidence.
"""
from __future__ import annotations

import time

MARK = "evaluation_only"


class EvaluationOnly(Exception):
    """An evaluation-only artifact was offered as input to a publication stage."""


def stamp(doc: dict, reason: str, run_id: str) -> dict:
    return {**doc, MARK: {"reason": reason, "run_id": run_id, "stamped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "rule": "evaluation only: refused as input to any publication workflow"}}


def refuse(doc, what: str):
    """Return `doc` unchanged, or raise if it is stamped evaluation-only."""
    if isinstance(doc, dict) and doc.get(MARK):
        m = doc[MARK]
        raise EvaluationOnly(f"{what} is evaluation-only (run {m.get('run_id')}: {m.get('reason')}); it cannot be "
                             "used as input to any publication workflow")
    return doc
