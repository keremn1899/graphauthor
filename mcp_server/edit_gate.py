"""Edit gate (construction charter §5 edit profile) — the only genuinely new
gate, built last and alone.

Edits (replace/remove/supersede) can silently launder a false-GOVERNED into
ground truth or drop coverage a moat relied on. The gate's core is a
BEFORE/AFTER GOVERNED-SET comparison: apply the edit to a scratch model,
diff the governed set, and refuse any UNEXPLAINED verdict change. A change is
explained only if the change-set DECLARES it (declared_changes on the op).
Add-only change-sets skip the comparison — they can't remove or reword, so
they take the existing add gate, not this one.

The verdict oracle is injected so the gate's logic is provable deterministically;
the live wiring passes the engine's real what_governs as the oracle over a
probe suite. `evaluate_edit` NEVER mutates the live model — refusal leaves
the graph untouched (scratch-only application).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from mcp_server.changeset import ChangeSet, OpKind

_EDIT_OPS = frozenset({OpKind.REPLACE_CONTENT, OpKind.REMOVE_EDGE,
                       OpKind.REMOVE_CONCEPT, OpKind.SUPERSEDE_RULE,
                       OpKind.DEPRECATE_RULE})


def _declared_changes(cs: ChangeSet) -> set[str]:
    declared: set[str] = set()
    for op in cs.operations:
        for p in (op.payload or {}).get("declared_changes", []) or []:
            declared.add(p)
    return declared


def evaluate_edit(cs: ChangeSet, live_model: Any,
                  oracle: Callable[[Any], dict[str, str]],
                  apply_edit: Callable[[Any, ChangeSet], Any], *,
                  graph_db: Any | None = None,
                  seeds: list[dict] | None = None,
                  unevaluable: frozenset[str] = frozenset({"ABSENT"})) -> dict[str, Any]:
    """Gate an edit change-set. Returns a decision dict:
      allowed: bool
      reason: str
      changed: {predicate: (before, after)}  — verdicts the edit moved
      declared_changes: [predicate]           — what the change-set declared
      audited: bool                           — allowed changes are recorded

    An add-only change-set skips the comparison. Otherwise: any predicate
    whose verdict changed and was NOT declared → refusal. The cardinal case
    (undeclared UNGOVERNED→GOVERNED, a laundered false-GOVERNED) is named.
    Never mutates ``live_model``.

    When ``graph_db`` is supplied the SAME grain check the create/add paths run
    is folded in: merge/split/replace can deliberately reshape grain, so an
    UNDECLARED grain shift is refused exactly like an undeclared verdict flip
    (hard grain violations block regardless of declaration). Omit ``graph_db``
    for pure verdict gating — behaviour is then unchanged.

    ``unevaluable`` names oracle tokens that mean "no verdict could be
    established" rather than a verdict. Any probe carrying one on either side is
    refused as ``unevaluable_probe`` instead of being compared, because two
    placeholders compare equal and would otherwise read as "no change". The
    default covers the coverage-space ABSENT placeholder; pass an empty set for
    oracles whose every token is a real verdict."""
    if not any(op.kind in _EDIT_OPS for op in cs.operations):
        return _with_grain({"allowed": True, "reason": "add_only_no_verdict_check",
                            "changed": {}, "declared_changes": [], "audited": False},
                           cs, graph_db, seeds)

    before = oracle(live_model)
    # scratch application — deep-copy discipline is the apply_edit's job; we
    # also guard here so a careless apply cannot leak into the live model.
    scratch = json.loads(json.dumps(live_model)) if _is_jsonable(live_model) else live_model
    after_model = apply_edit(scratch, cs)
    after = oracle(after_model)

    # A probe the oracle could not evaluate is not evidence of "no change".
    # Two placeholders compare equal, so without this an edit gated against a
    # faulting engine would be allowed by default — the gate must decline to
    # decide instead.
    unevaluated = sorted(
        p for p in set(before) | set(after)
        if before.get(p) in unevaluable or after.get(p) in unevaluable
    )
    if unevaluated:
        return {"allowed": False,
                "reason": f"unevaluable_probe:{','.join(unevaluated)}",
                "changed": {}, "declared_changes": sorted(_declared_changes(cs)),
                "audited": False}

    changed = {p: (before.get(p), after.get(p)) for p in set(before) | set(after)
               if before.get(p) != after.get(p)}
    declared = _declared_changes(cs)
    undeclared = {p: v for p, v in changed.items() if p not in declared}

    if undeclared:
        # Name the cardinal case specifically, sharing ONE definition of the
        # laundering direction with the classifier that refuses to auto-accept
        # it. Written inline here as `b in (None, "UNGOVERNED") and a ==
        # "GOVERNED"`, it missed PARTIALLY_GOVERNED -> GOVERNED — an authority
        # increase reported as an ordinary verdict change.
        from mcp_server.correction_classify import authority_increase

        cardinal = [p for p, (b, a) in undeclared.items() if authority_increase(b, a)]
        if cardinal:
            reason = f"undeclared_governed_flip:{','.join(sorted(cardinal))}"
        elif any(b == "GOVERNED" and a in (None, "UNGOVERNED") for (b, a) in undeclared.values()):
            reason = f"undeclared_coverage_loss:{','.join(sorted(undeclared))}"
        else:
            reason = f"undeclared_verdict_change:{','.join(sorted(undeclared))}"
        return {"allowed": False, "reason": reason, "changed": changed,
                "declared_changes": sorted(declared), "audited": False}

    # every change was declared → allowed and audited
    return _with_grain(
        {"allowed": True, "reason": "declared_changes_reconciled" if changed else "no_verdict_change",
         "changed": changed, "declared_changes": sorted(declared), "audited": bool(changed)},
        cs, graph_db, seeds)


def _with_grain(decision: dict[str, Any], cs: ChangeSet, graph_db: Any | None,
                seeds: list[dict] | None) -> dict[str, Any]:
    """Fold the grain check into a verdict-allowed decision. No-op without a
    graph_db (pure verdict gating). A hard grain violation or an undeclared
    grain shift flips the decision to refused; a declared/clean grain result is
    attached for the audit trail."""
    if graph_db is None or not decision.get("allowed"):
        return decision
    from mcp_server.grain import grain_gate_for_edit

    g = grain_gate_for_edit(graph_db, cs, seeds=seeds)
    decision["grain"] = g
    if not g["allowed"]:
        decision["allowed"] = False
        decision["reason"] = g["reason"]
        decision["audited"] = False
    elif g.get("audited"):
        decision["audited"] = True
    return decision


def _is_jsonable(x: Any) -> bool:
    try:
        json.dumps(x)
        return True
    except (TypeError, ValueError):
        return False


def live_oracle(db_path, probes: list[str]):
    """Live verdict oracle: what_governs over a probe suite, as a function of
    a materialized graph path. The edit gate's before/after comparison calls
    this on the live graph and on a scratch copy with the edit applied. The
    'graph_model' the gate threads is the .lbug path here (apply_edit writes a
    scratch .lbug and returns its path).

    Returns the full COVERAGE_SPACE token, NOT a GOVERNED/UNGOVERNED binary.
    Collapsing the space hid two distinct edits from the gate: a
    GOVERNED→PARTIALLY_GOVERNED degradation read as "no change", and ABSENT —
    which `Surface.what_governs` documents as a closed-vocabulary placeholder
    and NOT a graph finding — read as a substantive UNGOVERNED verdict. ABSENT
    on both sides made the gate compare two placeholders and allow the edit, so
    an edit evaluated against a faulting engine passed by default.

    This oracle stays in coverage space by construction: `what_governs` is
    §2.3 coverage-only and strips `conformance_ruling`. A ruling-space flip
    (VIOLATES→CONFORMS at unchanged coverage) is therefore still invisible here
    and needs a separate RULING_SPACE oracle — see
    docs/FINDINGS_TEMPORAL_EDIT_PROFILE_V1.md §6."""
    def _oracle(graph_db):
        from mcp_server.surface import Surface

        s = Surface(graph_db)
        out = {}
        try:
            for pred in probes:
                g = s.what_governs(f"What governs {pred.replace('_', ' ')}?", explain=False)
                out[pred] = str(g.get("status") or "ABSENT")
        finally:
            s.close()
        return out
    return _oracle
