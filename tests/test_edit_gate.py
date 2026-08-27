"""Edit gate — before/after GOVERNED-set comparison (construction step 3)."""

from __future__ import annotations

import json

from mcp_server.changeset import ChangeOp, ChangeSet, OpKind
from mcp_server.edit_gate import evaluate_edit

PROBES = ["retry_ownership", "broker_choice"]


def oracle(m):
    return {p: ("GOVERNED" if any(f"ADJUDICATES:{p}" in n["text"] for n in m["nodes"].values())
                else "UNGOVERNED") for p in PROBES}


def apply_edit(m, cs):
    m = json.loads(json.dumps(m))
    for op in cs.operations:
        if op.kind == OpKind.REPLACE_CONTENT:
            m["nodes"][op.target_node_id] = {"text": op.payload.get("text", "")}
        elif op.kind == OpKind.REMOVE_CONCEPT:
            m["nodes"].pop(op.target_node_id, None)
    return m


def test_add_only_skips_the_verdict_comparison():
    cs = ChangeSet.from_proposal_encoding(
        {"concepts": [{"id": "x", "label": "X", "text_content": "t"}], "edges": []}, base="gv")
    r = evaluate_edit(cs, {"nodes": {}}, oracle, apply_edit=lambda m, c: m)
    assert r["allowed"] and r["reason"] == "add_only_no_verdict_check"


def test_undeclared_moat_flip_is_the_cardinal_refusal():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REPLACE_CONTENT, target_node_id="r",
        payload={"text": "ADJUDICATES:retry_ownership ADJUDICATES:broker_choice"})])
    r = evaluate_edit(cs, base, oracle, apply_edit=apply_edit)
    assert not r["allowed"] and r["reason"].startswith("undeclared_governed_flip")
    assert "broker_choice" in r["changed"]


def test_undeclared_coverage_loss_refused():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(kind=OpKind.REMOVE_CONCEPT, target_node_id="r")])
    r = evaluate_edit(cs, base, oracle, apply_edit=apply_edit)
    assert not r["allowed"] and r["reason"].startswith("undeclared_coverage_loss")


def test_declared_change_is_allowed_and_audited():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REPLACE_CONTENT, target_node_id="r",
        payload={"text": "ADJUDICATES:retry_ownership ADJUDICATES:broker_choice",
                 "declared_changes": ["broker_choice"]})])
    r = evaluate_edit(cs, base, oracle, apply_edit=apply_edit)
    assert r["allowed"] and r["audited"] and "broker_choice" in r["declared_changes"]


def test_evaluate_never_mutates_live():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    snap = json.dumps(base)
    cs = ChangeSet(base="gv", operations=[ChangeOp(kind=OpKind.REMOVE_CONCEPT, target_node_id="r")])
    evaluate_edit(cs, base, oracle, apply_edit=apply_edit)
    assert json.dumps(base) == snap


def test_absent_on_both_sides_is_refused_not_read_as_no_change():
    """A faulting engine must not gate an edit through by default.

    ABSENT is a closed-vocabulary placeholder, not a graph finding. Two
    placeholders compare equal, so before this the gate saw "no verdict change"
    and allowed the edit."""
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REMOVE_CONCEPT, target_node_id="r")])

    r = evaluate_edit(cs, base, lambda m: {p: "ABSENT" for p in PROBES},
                      apply_edit=apply_edit)

    assert not r["allowed"]
    assert r["reason"].startswith("unevaluable_probe")
    assert "retry_ownership" in r["reason"] and "broker_choice" in r["reason"]
    assert r["audited"] is False


def test_absent_on_one_side_only_is_also_refused():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REMOVE_CONCEPT, target_node_id="r")])
    calls = {"n": 0}

    def flaky(_m):
        calls["n"] += 1
        return {p: ("GOVERNED" if calls["n"] == 1 else "ABSENT") for p in PROBES}

    r = evaluate_edit(cs, base, flaky, apply_edit=apply_edit)

    assert not r["allowed"] and r["reason"].startswith("unevaluable_probe")


def test_partial_coverage_degradation_is_a_visible_change():
    """GOVERNED -> PARTIALLY_GOVERNED was collapsed to GOVERNED/UNGOVERNED and
    read as no change; it is a real, undeclared coverage move."""
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REPLACE_CONTENT, target_node_id="r", payload={"text": "weakened"})])
    calls = {"n": 0}

    def degrading(_m):
        calls["n"] += 1
        status = "GOVERNED" if calls["n"] == 1 else "PARTIALLY_GOVERNED"
        return {"retry_ownership": status, "broker_choice": "UNGOVERNED"}

    r = evaluate_edit(cs, base, degrading, apply_edit=apply_edit)

    assert not r["allowed"]
    assert r["reason"].startswith("undeclared_verdict_change")
    assert r["changed"]["retry_ownership"] == ("GOVERNED", "PARTIALLY_GOVERNED")


def test_declaring_the_degradation_allows_and_audits_it():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REPLACE_CONTENT, target_node_id="r",
        payload={"text": "weakened", "declared_changes": ["retry_ownership"]})])
    calls = {"n": 0}

    def degrading(_m):
        calls["n"] += 1
        status = "GOVERNED" if calls["n"] == 1 else "PARTIALLY_GOVERNED"
        return {"retry_ownership": status, "broker_choice": "UNGOVERNED"}

    r = evaluate_edit(cs, base, degrading, apply_edit=apply_edit)

    assert r["allowed"] and r["audited"]


def test_unevaluable_set_is_overridable_for_pure_verdict_oracles():
    base = {"nodes": {"r": {"text": "ADJUDICATES:retry_ownership"}}}
    cs = ChangeSet(base="gv", operations=[ChangeOp(
        kind=OpKind.REPLACE_CONTENT, target_node_id="r",
        payload={"text": "t", "declared_changes": ["retry_ownership"]})])

    r = evaluate_edit(cs, base, lambda m: {p: "ABSENT" for p in PROBES},
                      apply_edit=apply_edit, unevaluable=frozenset())

    assert r["allowed"] and r["reason"] == "no_verdict_change"
