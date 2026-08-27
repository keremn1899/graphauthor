"""Binding a correction's acknowledgement to the report it answers.

The gate reports what a correction moved; something other than the gate then
affirms those moves; the correction is resubmitted carrying that affirmation and
commits. This module is the binding in the middle — it is what stops an
acknowledgement being reused against a different edit, a different graph, or a
different set of consequences.

Deliberately says nothing about WHO acknowledges. `acknowledged_by` is a free
string ("human:kerem", "agent:host", "mechanism") recorded for audit, and no
code here branches on it. Whether the happy path is owned by an operator or by
the host agent is a charter question, and building it in here would answer that
question by implementation instead of by decision.

Two layers, because one is not enough:

1. **The digest binds the edit.** It covers which nodes are corrected, what they
   said before, and what they will say after. If anything about the edit or its
   starting point moved, the acknowledgement is stale.
2. **The subset check binds the consequences.** The gate re-runs on
   resubmission, and the fresh `changed` map must not contain a move the
   acknowledgement never saw. The digest cannot catch this on its own: an edit
   to a *neighbour* leaves the corrected nodes' content untouched while changing
   what the correction does downstream.

Direction matters in the subset check. A re-run that finds FEWER moves proceeds
— the acknowledger affirmed a superset, and the oracle is measurably
nondeterministic (the observation that motivated a 2-hop sweep did not replicate
on a later run of the same node). A re-run that finds MORE voids the
acknowledgement and reports again. Requiring exact equality would make the
workflow fail on oracle noise; allowing supersets would let a real new
consequence ride in on a stale affirmation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: An acknowledgement is stale: the edit or its starting point changed.
STALE = "acknowledgement_stale"
#: The re-run surfaced a consequence the acknowledger never saw.
SUPERSEDED = "acknowledgement_superseded"
#: The acknowledger did not affirm everything that needs affirming.
INCOMPLETE = "acknowledgement_incomplete"
#: The acknowledger claimed something it had no standing to accept.
OVERREACH = "acknowledgement_overreach"
#: The report is not a comparison that can be affirmed (unevaluable, overflow).
NOT_ACKNOWLEDGEABLE = "not_acknowledgeable"


def corrected_node_shas(db_path: Path | str, ids: Iterable[str]) -> dict[str, str]:
    """Content hashes of the nodes a correction targets, as they stand now.

    READ ONLY, and scoped to the corrected ids rather than the whole graph.
    `history.extract_manifest` would also answer this, but it opens read-write
    and walks every node and edge — far too much machinery to bind one edit.
    """
    import real_ladybug as lb

    wanted = sorted(set(ids))
    if not wanted:
        return {}
    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    out: dict[str, str] = {}
    try:
        res = conn.execute(
            "MATCH (c:Concept) WHERE c.id IN $ids "
            "RETURN c.id, c.text_content, c.semantic_anchor", {"ids": wanted})
        while res.has_next():
            node_id, text, anchor = res.get_next()
            payload = f"{text or ''}\x00{anchor or ''}".encode("utf-8")
            out[str(node_id)] = hashlib.sha256(payload).hexdigest()[:16]
    finally:
        del conn, database
    return out


def report_digest(corrections: Sequence[Any], before_shas: Mapping[str, str]) -> str:
    """Bind an acknowledgement to this edit, from this starting point.

    Covers the incoming text as well as the outgoing state: an acknowledgement
    of "neutralise this rule" must not be redeemable against a resubmission that
    quietly rewrites the same node into something else.
    """
    payload = [
        {
            "id": corr.id,
            "before_sha": before_shas.get(corr.id, ""),
            "after_sha": hashlib.sha256(
                f"{corr.text_content}\x00{corr.semantic_anchor}".encode("utf-8")
            ).hexdigest()[:16],
            "intent": getattr(corr, "intent", ""),
            # Part of the edit, so part of what was affirmed. An acknowledgement
            # of a text fix must not be redeemable against a resubmission that
            # also retags the node as governing.
            "claim_kind": getattr(corr, "claim_kind", ""),
            "reason": getattr(corr, "reason", ""),
            "label": getattr(corr, "label", ""),
            "declared_changes": list(getattr(corr, "declared_changes", []) or []),
        }
        for corr in sorted(corrections, key=lambda c: c.id)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _normalise(moves: Mapping[str, Any] | None) -> dict[str, tuple]:
    return {k: tuple(v) if isinstance(v, (list, tuple)) else (v,)
            for k, v in (moves or {}).items()}


def verify(
    acknowledgement: Mapping[str, Any] | None,
    *,
    expected_digest: str,
    rerun_changed: Mapping[str, Any],
    classification: Mapping[str, Any],
) -> dict[str, Any]:
    """Decide whether an acknowledgement licenses this commit.

    Returns `ok` plus a typed `reason`. Never raises on a malformed
    acknowledgement — a caller supplying nonsense gets a refusal, not a stack
    trace, because this sits on the write path.
    """
    from mcp_server.correction_classify import permitted

    # A gate that never compared (unevaluable placeholder, universe overflow)
    # has nothing honest to affirm. Treating its empty `changed` as a clean
    # pass is the silent-permission failure the whole path exists to prevent.
    disposition = str(classification.get("disposition") or "")
    if disposition == "refused" or classification.get("compared") is False:
        return {"ok": False, "reason": NOT_ACKNOWLEDGEABLE, "detail": (
            "this report is not a verdict comparison that can be acknowledged; "
            f"disposition={disposition or 'unknown'}")}

    if not acknowledgement:
        return {"ok": False, "reason": INCOMPLETE,
                "detail": "no acknowledgement supplied for a correction that moved a verdict"}
    if str(acknowledgement.get("report_digest") or "") != expected_digest:
        return {"ok": False, "reason": STALE, "detail": (
            "this acknowledgement was issued against a different edit or a "
            "different starting state; re-run the report")}

    seen = _normalise(acknowledgement.get("moves"))
    fresh = _normalise(rerun_changed)
    # A move the acknowledger never saw, or saw differently. Either way it did
    # not affirm THIS consequence. A re-run that finds FEWER moves proceeds —
    # the acknowledger affirmed a superset, and the oracle is nondeterministic.
    unseen = sorted(k for k, v in fresh.items() if seen.get(k) != v)
    if unseen:
        return {"ok": False, "reason": SUPERSEDED, "superseded_by": unseen,
                "detail": (
                    "the gate re-ran and found moves the acknowledgement does "
                    f"not cover: {', '.join(unseen)}")}

    # Acceptances for moves that disappeared on the re-run are noise, not
    # overreach. Overreach remains reserved for affirming a still-present
    # cardinal / unevaluable / otherwise non-interpretable move.
    accepts = [
        a for a in (acknowledgement.get("accepts") or ())
        if a in fresh
        or a in set(classification.get("auto_accepted") or ())
        or a in set(classification.get("needs_interpreter") or ())
        or a in set(classification.get("cardinal") or ())
        or a in set(classification.get("unevaluable") or ())
    ]
    outcome = permitted(classification, accepts)
    if outcome["refused_overreach"]:
        return {"ok": False, "reason": OVERREACH,
                "refused_overreach": outcome["refused_overreach"],
                "detail": (
                    "the acknowledger accepted moves it has no standing to "
                    "accept (a cardinal flip or an unevaluable probe)")}
    if outcome["outstanding"]:
        return {"ok": False, "reason": INCOMPLETE,
                "outstanding": outcome["outstanding"],
                "detail": (
                    "these moves were neither mechanically acceptable nor "
                    f"affirmed: {', '.join(outcome['outstanding'])}")}
    return {"ok": True, "reason": "acknowledged",
            "declared": outcome["declared"],
            "acknowledged_by": str(acknowledgement.get("acknowledged_by") or "unattributed")}
