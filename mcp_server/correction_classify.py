"""Mechanically classify the verdict moves a correction caused.

The correction gate reports a `changed` map: predicate -> [before, after]. As
originally designed, the gate REFUSED whenever that map held anything the
caller had not declared in advance. Measured across every governing decision in
the cattrs reference, that refused four governing corrections in five
(`docs/FINDINGS_CORRECTION_GATE_CHARACTERIZATION_V1.md`), because nobody — human
or agent — can predict the map. The demand was impossible, so the workflow, not
the gate, was wrong.

This module is the replacement for that demand, and it is deliberately
**mechanical**: no model, no engine, no network. It partitions the map into
classes whose disposition is fixed in advance, so that whoever acknowledges the
report can never be the thing that decides *what is decidable*.

Two properties carry the safety argument:

1. **Direction is the safety axis.** A move toward GOVERNED can launder
   authority into the graph; a move away from it cannot. Every move toward
   GOVERNED is CARDINAL and escalates, with no interpreter — human or model —
   able to wave it through inline. Overnight, 2 of 11 corrections produced one,
   and both were two hops from the edited node.

2. **Intent is declared before the report exists.** The proposer states what the
   correction is *for* at submission; the gate then runs. Accepting a move
   because it matches a pre-stated intent is therefore not the gate approving
   its own findings — the acceptance rule was fixed before the finding existed.
   Copying `changed` into `declared_changes` with no such rule IS the gate
   approving itself, and remains refused.

What is auto-acceptable is intentionally narrow. Withdrawing a rule's force is
expected to cost coverage on the rule itself and on the antecedents that only
reached governance *through* it. It is not expected to cost coverage on a
container or an architecture root — that is blast radius the author probably did
not intend, and it stays for an interpreter to judge.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: A move toward GOVERNED. Escalates mechanically; no interpreter may accept it
#: inline. This is the laundered-authority direction the gate exists to catch.
CARDINAL = "cardinal"
#: A probe the oracle could not evaluate (ABSENT on either side). Neither an
#: accept nor a refusal is honest, so the correction does not proceed.
UNEVALUABLE = "unevaluable"
#: Coverage loss on a corrected node, or on an antecedent whose route to
#: governance ran through one. Expected when the intent is to withdraw force.
WITHDRAWAL_LOCAL = "withdrawal_local"
#: Coverage loss somewhere the correction was not aimed — a container, a root.
#: The right direction, but wider than the stated intent. Needs an interpreter.
WITHDRAWAL_SPREADING = "withdrawal_spreading"
#: Anything the classes above do not cover. Never auto-acceptable.
OTHER = "other"

#: Intents a proposer may declare. Stated at submission, before the gate runs.
#: `withdraw_force` expects local coverage loss; `restate` expects nothing to
#: move at all, so any move whatsoever needs an interpreter.
INTENT_WITHDRAW_FORCE = "withdraw_force"
INTENT_RESTATE = "restate"
INTENTS = frozenset({INTENT_WITHDRAW_FORCE, INTENT_RESTATE})

#: How much authority each coverage verdict carries. A RANK, not a set — the
#: first version of this used `{GOVERNED, PARTIALLY_GOVERNED}` as a single
#: "governing side", which made PARTIALLY_GOVERNED -> GOVERNED read as no change
#: of direction at all. Strengthening partial authority to full authority is an
#: authority increase and must be cardinal; a set cannot express that.
_AUTHORITY_RANK = {"UNGOVERNED": 0, "PARTIALLY_GOVERNED": 1, "GOVERNED": 2}
#: Anything outside the coverage space (a ruling token, an unknown verdict) has
#: no rank, is never auto-acceptable, and always falls to an interpreter.
_GOVERNING_SIDE = frozenset({"GOVERNED", "PARTIALLY_GOVERNED"})
#: The oracle could not decide. Not a verdict — an absence of one.
_UNEVALUABLE = frozenset({"ABSENT", "", None})

#: Which classes a given intent may auto-accept. Everything else escalates.
#: CARDINAL appears in no row, by construction: no intent can license laundering.
_AUTO_ACCEPTABLE: dict[str, frozenset[str]] = {
    INTENT_WITHDRAW_FORCE: frozenset({WITHDRAWAL_LOCAL}),
    INTENT_RESTATE: frozenset(),
}


def authority_increase(before: Any, after: Any) -> bool:
    """Did this move add authority the graph did not have before?

    The single definition of the cardinal direction, so the gate that names a
    laundered flip and the classifier that refuses to auto-accept one cannot
    drift apart. A comparison written as `before in (None, "UNGOVERNED") and
    after == "GOVERNED"` misses PARTIALLY_GOVERNED -> GOVERNED entirely.
    """
    was, now = _AUTHORITY_RANK.get(before), _AUTHORITY_RANK.get(after)
    return was is not None and now is not None and now > was


def classify_move(
    predicate: str,
    before: Any,
    after: Any,
    corrected_ids: Iterable[str],
    antecedents: Iterable[str],
) -> str:
    """Classify one verdict move. Pure: no graph, no model, no I/O."""
    if before in _UNEVALUABLE or after in _UNEVALUABLE:
        return UNEVALUABLE
    was, now = _AUTHORITY_RANK.get(before), _AUTHORITY_RANK.get(after)
    if was is None or now is None:
        return OTHER
    if now > was:
        return CARDINAL
    if now < was:
        # Identity is NOT a blanket exemption — a "correction" that promoted the
        # node it edits is caught above, by direction, before it gets here.
        if predicate in set(corrected_ids) or predicate in set(antecedents):
            return WITHDRAWAL_LOCAL
        return WITHDRAWAL_SPREADING
    return OTHER


def classify_moves(
    changed: Mapping[str, Any],
    corrected_ids: Iterable[str],
    antecedents: Iterable[str] = (),
    *,
    intent: str = INTENT_RESTATE,
) -> dict[str, Any]:
    """Partition a gate report's `changed` map into dispositions.

    `antecedents` are nodes that reach governance *through* a corrected node —
    supplied by the caller (see `antecedents_of`) rather than derived here, so
    this stays a pure function that can be tested without a database.

    Returns the classification plus two sets that drive the workflow:
    `auto_accepted` (what the mechanism itself affirms, given the pre-stated
    intent) and `needs_interpreter` (what it will not).
    """
    if intent not in INTENTS:
        raise ValueError(f"unknown correction intent: {intent!r}")
    corrected = set(corrected_ids)
    antecedent = set(antecedents) - corrected
    acceptable = _AUTO_ACCEPTABLE[intent]

    classes: dict[str, str] = {}
    for predicate, move in (changed or {}).items():
        # Any sequence, deliberately. `edit_gate` builds these as TUPLES while
        # the frozen replay corpus round-trips them through JSON as LISTS —
        # accepting only one shape made the corpus pass while the live path
        # classified every move as unevaluable.
        pair = list(move) if isinstance(move, (list, tuple)) else []
        before, after = (pair + [None, None])[:2]
        classes[predicate] = classify_move(
            predicate, before, after, corrected, antecedent)

    auto = sorted(p for p, k in classes.items() if k in acceptable)
    escalate = sorted(p for p, k in classes.items() if k not in acceptable)
    return {
        "intent": intent,
        "classes": classes,
        "auto_accepted": auto,
        "needs_interpreter": escalate,
        "cardinal": sorted(p for p, k in classes.items() if k == CARDINAL),
        "unevaluable": sorted(p for p, k in classes.items() if k == UNEVALUABLE),
        # An interpreter may refuse anything, but may accept only from here.
        # CARDINAL and UNEVALUABLE are absent by construction.
        "interpretable": sorted(
            p for p, k in classes.items()
            if k not in acceptable and k not in (CARDINAL, UNEVALUABLE)),
        "clears_mechanically": not escalate,
    }


def permitted(classification: Mapping[str, Any],
              interpreter_accepts: Iterable[str] = ()) -> dict[str, Any]:
    """Compose the mechanical floor with an interpreter's acceptances.

    The interpreter — agent or human — may only ever narrow. Anything it accepts
    outside `interpretable` is discarded and named in `refused_overreach`, so an
    interpreter cannot license a cardinal flip by asserting one. This is the
    invariant that makes the acknowledger's species a configuration choice
    rather than a safety property: a weak interpreter yields needless
    escalations, never a laundered rule.
    """
    interpretable = set(classification.get("interpretable") or ())
    # Re-affirming what the mechanism already accepted is redundant, not
    # overreach — an interpreter that restates the whole map should be told off
    # only for the part it had no standing to accept.
    already = set(classification.get("auto_accepted") or ())
    claimed = set(interpreter_accepts)
    honoured = claimed & interpretable
    overreach = sorted(claimed - interpretable - already)
    outstanding = sorted(
        set(classification.get("needs_interpreter") or ()) - honoured)
    return {
        "declared": sorted(set(classification.get("auto_accepted") or ()) | honoured),
        "refused_overreach": overreach,
        "outstanding": outstanding,
        "commits": not outstanding and not overreach,
    }


#: Gate outcomes that are NOT a verdict comparison, and so must never be handed
#: to the classifier. `unevaluable_probe` and `region_exceeds_probe_cap` both
#: return before any before/after map exists, so their `changed` is empty — and
#: an empty map classifies as "nothing moved", which would read a refusal as a
#: clean pass. Precedence, not classification, is what keeps these safe.
_NON_COMPARISON_REFUSALS = (
    "unevaluable_probe",
    "region_exceeds_probe_cap",  # legacy reason; retained for frozen corpora
    "universe_exceeds_probe_cap",
    "no_probes_available_for_governing_correction",
)


def dispose_report(report: Mapping[str, Any], corrected_ids: Iterable[str],
                   antecedents: Iterable[str] = (), *,
                   intent: str = INTENT_RESTATE,
                   independent_probe: bool = True) -> dict[str, Any]:
    """Turn a raw gate report into a disposition, refusals taking precedence.

    A gate that refused *without comparing* carries an empty `changed` map. Left
    to the classifier that is indistinguishable from "nothing moved", so it is
    short-circuited here instead — the same silent-permission shape the probe
    cap already refuses rather than truncates.

    `independent_probe` is False when the region around the correction contains
    nothing but the corrected nodes themselves, so the gate compared the edit
    only against its own target. That is a probe suite of size one holding
    exactly what the caller declared they were changing — the circularity
    region-derived probes exist to avoid, arrived at through sparsity instead of
    through a declaration. It is a real condition, not a hypothetical: on a
    Kubernetes KEP graph at 0.35 edges per node, 5 of 14 governing nodes have
    one. Such a correction can still proceed, but never on the mechanism's own
    authority — somebody has to affirm that nothing was checkable.
    """
    reason = str(report.get("reason") or "")
    if any(reason.startswith(prefix) for prefix in _NON_COMPARISON_REFUSALS):
        return {"disposition": "refused", "reason": reason, "compared": False,
                "auto_accepted": [], "needs_interpreter": [],
                "interpretable": [], "clears_mechanically": False}
    if not report.get("ran"):
        return {"disposition": "skipped", "reason": reason, "compared": False,
                "auto_accepted": [], "needs_interpreter": [],
                "interpretable": [], "clears_mechanically": True}
    classification = classify_moves(
        report.get("changed") or {}, corrected_ids, antecedents, intent=intent)
    if not independent_probe:
        # The mechanism checked nothing it did not already know about. It may
        # not then certify the result as clear on its own authority.
        classification = {**classification, "clears_mechanically": False,
                          "no_independent_probe": True,
                          "interpretable": sorted(
                              set(classification["interpretable"])
                              | set(classification["auto_accepted"])),
                          "needs_interpreter": sorted(
                              set(classification["needs_interpreter"])
                              | set(classification["auto_accepted"])),
                          "auto_accepted": []}
        if not classification["needs_interpreter"]:
            # Nothing moved at all AND nothing was checkable — still not a pass
            # the mechanism can grant, so surface it for affirmation.
            classification["interpretable"] = []
        return {"disposition": "uncheckable", "reason": reason, "compared": True,
                **classification}
    if classification["unevaluable"]:
        disposition = "refused"
    elif classification["clears_mechanically"]:
        disposition = "clears"
    elif classification["cardinal"]:
        disposition = "escalate"
    else:
        disposition = "interpret"
    return {"disposition": disposition, "reason": reason, "compared": True,
            **classification}


def antecedents_of(db_path: Any, corrected_ids: Iterable[str]) -> list[str]:
    """Nodes whose route to governance may run through a corrected node.

    Structurally: the direct LEADSTO predecessors. On the cattrs reference these
    are the superseded and rejected decisions that a current decision replaced —
    they read as governed only because their successor governs, so neutralising
    the successor is *expected* to withdraw their coverage too.

    Keyed on the SST edge TYPE, not on the free-text label. `replaced_by` is
    level-two vocabulary, ungoverned and corpus-specific; a classifier that
    keyed on it would silently stop working on the next graph.

    READ ONLY — a probe that can write is not a probe.
    """
    import real_ladybug as lb

    ids = sorted(set(corrected_ids))
    if not ids:
        return []
    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    try:
        found: set[str] = set()
        res = conn.execute(
            "MATCH (a:Concept)-[:LEADSTO]->(b:Concept) WHERE b.id IN $ids "
            "RETURN a.id", {"ids": ids})
        while res.has_next():
            node = str(res.get_next()[0] or "")
            if node and node not in ids:
                found.add(node)
    finally:
        del conn, database
    return sorted(found)
