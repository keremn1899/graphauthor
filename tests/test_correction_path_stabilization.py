"""Stabilization regressions for the correction path.

These pin defects found on `experiment/host-agent-packet` after the report →
acknowledge workflow landed: an unevaluable comparison could be acknowledged
into a commit, mixed mutations compared only their correction half, heuristic
probe suites under-covered the oracle, fewer-move reruns failed as overreach,
expired policies stayed in `applying_policy_ids`, and correction events were
outside the declared vocabulary.
"""

from __future__ import annotations

import shutil

import pytest

from interaction.write_path_store import WritePathStore
from mcp_server.correction_ack import verify
from mcp_server.correction_classify import INTENT_WITHDRAW_FORCE, dispose_report
from mcp_server.fixture import ensure_fixture
from mcp_server.proposals import (
    GateSpec,
    _correction_gate,
    confirm_proposal,
    validate_proposal,
)
from mcp_server.surface import Surface

EMB = lambda _t: [0.0] * 3072  # noqa: E731


@pytest.fixture()
def db(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def _gate(green=True):
    return GateSpec(
        target_gap_id="g",
        policy_id="order_service",
        policy_in_grounding=lambda r, pid, also=None: pid in str(r.get("grounding", "")),
        adjacent_only=lambda r, *a: False,
        runner=lambda: (
            [{"governance_verdict": "GOVERNED", "grounding": "order_service"}] * 5,
            {"a": [{"governance_verdict": "UNGOVERNED" if green else "GOVERNED"}] * 5},
        ),
        baseline={"a": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}},
        intrinsic_ids=("a",),
        encoded_gap_ids=("g",),
        intentional_closure_ids=("g",),
    )


def _governing(db_path, node_id="order_service"):
    import real_ladybug as lb

    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    conn.execute(
        f"MATCH (c:Concept {{id: '{node_id}'}}) SET c.claim_kind = 'governing'")
    del conn, database


def _fake_oracle(verdicts):
    calls = {"n": 0}

    def factory(_db, probes):
        def oracle(_model):
            calls["n"] += 1
            state = verdicts[min(calls["n"], len(verdicts)) - 1]
            return {p: state.get(p, "UNGOVERNED") for p in probes}
        return oracle

    return factory


def _queue(db_path, encoding):
    import json
    from pathlib import Path

    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import new_proposal_id, validate_proposal

    prop, err = validate_proposal(encoding, db_path)
    assert prop is not None, err
    store_path = Path(db_path).with_suffix(".writestore.sqlite")
    pid = new_proposal_id()
    store = WritePathStore(store_path)
    try:
        store.save_proposal({
            "proposal_id": pid,
            "target_gap_id": "test_gap",
            "encoding_json": json.dumps(prop.model_dump()),
            "generating_task": "t",
            "source_refs": [],
            "expected_graph_version": "basis",
            "expected_graph_fingerprint": graph_fingerprint(db_path),
            "status": "PENDING",
        })
    finally:
        store.close()
    return pid, store_path


def test_an_unevaluable_report_cannot_be_acknowledged_into_a_commit():
    """The fail-closed property: placeholders are not a clean empty map."""
    disposition = dispose_report(
        {"ran": True, "reason": "unevaluable_probe:api_ingress", "changed": {}},
        ["order_service"], intent=INTENT_WITHDRAW_FORCE)
    assert disposition["disposition"] == "refused"
    assert disposition["compared"] is False

    outcome = verify(
        {"report_digest": "d", "moves": {}, "accepts": []},
        expected_digest="d",
        rerun_changed={},
        classification=disposition,
    )
    assert outcome["ok"] is False
    assert outcome["reason"] == "not_acknowledgeable"


def test_a_rerun_that_finds_fewer_moves_is_not_overreach():
    """Oracle noise may drop a previously seen move; that is not laundering."""
    classification = dispose_report(
        {"ran": True, "reason": "undeclared_verdict_change",
         "changed": {"api_ingress": ("GOVERNED", "UNGOVERNED")}},
        ["order_service"], intent=INTENT_WITHDRAW_FORCE)
    # First report also saw a second move the acknowledger accepted; the
    # re-run no longer shows it.
    outcome = verify(
        {
            "report_digest": "d",
            "moves": {
                "api_ingress": ("GOVERNED", "UNGOVERNED"),
                "payment_port": ("GOVERNED", "UNGOVERNED"),
            },
            "accepts": ["api_ingress", "payment_port"],
        },
        expected_digest="d",
        rerun_changed={"api_ingress": ("GOVERNED", "UNGOVERNED")},
        classification=classification,
    )
    assert outcome["ok"] is True, outcome


def test_corrections_cannot_be_mixed_with_adds(db):
    prop, err = validate_proposal(
        {
            "concepts": [{"id": "brand_new", "label": "N", "text_content": "t"}],
            "corrections": [{"id": "order_service", "text_content": "fixed",
                             "reason": "was wrong"}],
        },
        db,
    )
    assert prop is None
    assert "cannot be mixed" in err


def test_the_gate_probes_the_complete_graph_universe(db):
    _governing(db)
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""

    decision = _correction_gate(
        db, prop, None, EMB, oracle_factory=_fake_oracle([{}, {}]))

    assert decision["ran"] is True
    assert decision["probe_mode"] == "complete_universe"
    assert "order_service" in decision["probes"]
    assert "api_ingress" in decision["probes"]
    assert len(decision["probes"]) >= 30
    assert decision["universe"]["excluded"] == []


def test_a_universe_larger_than_the_cap_refuses(db):
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    decision = _correction_gate(
        db, prop, None, EMB, probe_cap=5,
        oracle_factory=_fake_oracle([{}, {}]))

    assert decision["allowed"] is False
    assert decision["ran"] is False
    assert decision["reason"] == "universe_exceeds_probe_cap"
    assert decision["universe"]["universe_size"] > 5


def test_unevaluable_confirm_path_refuses_rather_than_reporting(db):
    """confirm_proposal must not treat ran=True+unevaluable as acknowledgeable."""
    from mcp_server.edit_gate import evaluate_edit

    _governing(db)
    before_text = None
    import real_ladybug as lb
    database = lb.Database(str(db), read_only=True)
    conn = lb.Connection(database)
    before_text = conn.execute(
        "MATCH (c:Concept {id:'order_service'}) RETURN c.text_content"
    ).get_next()[0]
    del conn, database

    def factory(_db, probes):
        def oracle(_model):
            return {p: "ABSENT" for p in probes}
        return oracle

    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})
    result = confirm_proposal(
        db, store_path, pid, primary_source="human source",
        gate=_gate(True), embedder=EMB, correction_oracle_factory=factory,
        correction_acknowledgement={
            "report_digest": "anything",
            "moves": {},
            "accepts": [],
        })

    assert result["status"] == "CORRECTION_REFUSED"
    assert str(result["correction_gate"]["reason"]).startswith("unevaluable_probe")
    database = lb.Database(str(db), read_only=True)
    conn = lb.Connection(database)
    after = conn.execute(
        "MATCH (c:Concept {id:'order_service'}) RETURN c.text_content"
    ).get_next()[0]
    del conn, database
    assert after == before_text
    # evaluate_edit still exists for the gate; this assertion documents the
    # seam the confirm path must not trust alone.
    assert callable(evaluate_edit)


def test_correction_refused_is_not_an_event_type():
    import interaction.event_types as ev

    assert ev.all_event_types() == {ev.GRAPH_COMMITTED, ev.GRAPH_REVERTED}


def test_a_refused_correction_does_not_open_ledger_demand():
    from mcp_server.ledger import project_activities
    import interaction.event_types as ev

    events = [
        {
            "event_id": "e1", "ts": 1.0, "type": ev.GRAPH_COMMITTED,
            "proposal_id": "p1", "gap_id": "g", "actor": "gate:auto-encode",
            "authority_type": "gate", "payload_json": "{}",
        },
    ]
    acts = list(project_activities(events, now=2.0).values())
    assert len(acts) == 1
    assert acts[0]["state"] == "SETTLED"
    assert acts[0]["needs_me"] is False


