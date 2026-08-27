"""M4 proposal tests — unit-level guarantees behind scripts/run_m4_battery.py."""

from __future__ import annotations

import json
import shutil

import pytest

from mcp_server.fixture import ensure_fixture
from mcp_server.proposals import (
    GateSpec,
    confirm_proposal,
    new_proposal_id,
    reject_proposal,
    validate_proposal,
)
from mcp_server.surface import Surface

ENC = {
    "concepts": [{"id": "p_x", "label": "X", "text_content": "body", "semantic_anchor": "a"}],
    "edges": [{"type": "EXPRESSES", "source_id": "p_x", "target_id": "order_service", "label": "l"}],
}


@pytest.fixture()
def db(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def _pending(db, encoding=ENC, *, target_gap_id="test_gap", store_path=None,
             expected_graph_version="basis", expected_graph_fingerprint=None):
    from pathlib import Path

    from interaction.write_path_store import WritePathStore
    from mcp_server.history import graph_fingerprint

    prop, err = validate_proposal(encoding, db)
    assert prop is not None, err
    store_path = Path(store_path) if store_path else Path(db).with_suffix(".writestore.sqlite")
    pid = new_proposal_id()
    fp = expected_graph_fingerprint
    if fp is None and expected_graph_version:
        fp = graph_fingerprint(db)
    store = WritePathStore(store_path)
    try:
        store.save_proposal({
            "proposal_id": pid,
            "target_gap_id": target_gap_id,
            "encoding_json": json.dumps(prop.model_dump()),
            "generating_task": "t",
            "source_refs": [],
            "expected_graph_version": expected_graph_version,
            "expected_graph_fingerprint": fp or "",
            "status": "PENDING",
        })
    finally:
        store.close()
    return pid, store_path


def _gate(green=True):
    return GateSpec(
        target_gap_id="g",
        policy_id="p_x",
        policy_in_grounding=lambda r, pid, also=None: pid in str(r.get("grounding", "")),
        adjacent_only=lambda r, *a: False,
        runner=lambda: (
            [{"governance_verdict": "GOVERNED", "grounding": "p_x"}] * 5,
            {"a": [{"governance_verdict": "UNGOVERNED" if green else "GOVERNED"}] * 5},
        ),
        baseline={"a": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}},
        intrinsic_ids=("a",),
        encoded_gap_ids=("g",),
        intentional_closure_ids=("g",),
    )


def test_validation_rejects_duplicate_existing_id(db):
    prop, err = validate_proposal(
        {"concepts": [{"id": "order_service", "label": "dup", "text_content": "x"}], "edges": []}, db
    )
    assert prop is None and "already exist" in err


def test_validation_accepts_edge_between_existing_nodes(db):
    prop, err = validate_proposal(
        {"concepts": [], "edges": [{"type": "NEARTO", "source_id": "order_service", "target_id": "order_status"}]}, db
    )
    assert err == "" and prop is not None


def test_propose_requires_enablement(db):
    s = Surface(db)
    try:
        assert "not enabled" in s.propose(encoding=ENC)["error"]
        assert "propose" not in s.orient()["capabilities"]
    finally:
        s.close()


def test_propose_refuses_an_explicit_stale_authoring_version(db):
    from interaction.write_path_store import WritePathStore

    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        result = s.propose(
            encoding=ENC,
            target_gap_id="test_gap",
            expected_graph_version="gv_stale",
        )
        with WritePathStore(s._store_path) as store:
            records = store.list_proposals()
    finally:
        s.close()

    assert result["error_code"] == "STALE_GRAPH"
    assert result["retryable"] is True
    assert records == []


def test_ordinary_proposal_keeps_empty_construction_attachment(db):
    from interaction.write_path_store import WritePathStore

    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        queued = s.propose(
            encoding=ENC,
            target_gap_id="ordinary_proposal",
        )
        with WritePathStore(s._store_path) as store:
            record = store.get_proposal(queued["proposal_id"])
    finally:
        s.close()

    assert json.loads(record["construction_receipt_json"]) == {}
    assert json.loads(record["construction_evidence_json"]) == {}
    assert json.loads(record["construction_reasons_json"]) == {}
    assert json.loads(record["construction_edge_evidence_json"]) == []


def test_confirm_fails_closed_when_checked_basis_is_missing(db):
    from mcp_server.history import extract_manifest

    pid, store_path = _pending(
        db, expected_graph_version="", expected_graph_fingerprint="")
    before = extract_manifest(db)

    result = confirm_proposal(
        db,
        store_path,
        pid,
        primary_source="source",
        gate=_gate(True),
        embedder=lambda _: [0.0] * 3072,
    )

    assert result["error_code"] == "EXPECTED_GRAPH_BASIS_REQUIRED"
    assert result["status"] == "PENDING"
    assert extract_manifest(db) == before


def test_double_confirm_refused(db, tmp_path):
    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        r1 = s.propose(encoding=ENC, provenance={"generating_task": "t"}, target_gap_id="test_gap")
        pid = r1["proposal_id"]
        store = s._store_path
    finally:
        s.close()
    assert r1["status"] == "COMMITTED"
    r2 = confirm_proposal(db, store, pid, primary_source="src", gate=_gate(True),
                          embedder=lambda t: [0.0] * 3072)
    assert "not PENDING" in r2["error"]


def test_confirm_succeeds_while_the_read_plane_still_owns_the_graph(db):
    """Propose must be able to write while this process still holds the graph."""
    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        result = s.propose(
            encoding=ENC, provenance={"generating_task": "t"}, target_gap_id="test_gap"
        )
    finally:
        s.close()
    assert result.get("status") == "COMMITTED", result


def test_confirm_persists_declared_claim_kind(db):
    import real_ladybug as lb

    encoding = {
        **ENC,
        "concepts": [{**ENC["concepts"][0], "claim_kind": "governing"}],
    }
    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        result = s.propose(
            encoding=encoding, provenance={}, target_gap_id="test_gap"
        )
    finally:
        s.close()
    assert result["status"] == "COMMITTED"

    database = lb.Database(str(db))
    conn = lb.Connection(database)
    row = conn.execute(
        "MATCH (c:Concept {id: 'p_x'}) "
        "RETURN c.claim_kind, c.claim_kind_source"
    ).get_next()
    del conn, database
    assert list(row) == ["governing", "declared"]


def test_proposal_fingerprint_includes_claim_kind_source(db):
    import real_ladybug as lb
    from mcp_server.history import graph_fingerprint

    before = graph_fingerprint(db)
    database = lb.Database(str(db))
    conn = lb.Connection(database)
    conn.execute(
        "MATCH (c:Concept {id: 'order_service'}) "
        "SET c.claim_kind_source = 'declared'"
    )
    del conn, database

    assert graph_fingerprint(db) != before


def test_stale_proposal_refused_before_confirm_mutation(db):
    """An intervening commit leaves the older proposal PENDING for refresh."""
    pid1, store = _pending(db)
    pid2, _ = _pending(db, store_path=store)
    emb = lambda t: [0.0] * 3072
    assert confirm_proposal(db, store, pid1, primary_source="s", gate=_gate(True), embedder=emb)["status"] == "COMMITTED"
    r = confirm_proposal(db, store, pid2, primary_source="s", gate=_gate(True), embedder=emb)
    assert r.get("status") == "PENDING"
    assert r.get("error_code") == "STALE_GRAPH"
    assert r.get("agent_mutated_graph") is False


def test_gate_red_restores_and_records(db):
    s = Surface(db, enable_history=True, enable_proposals=True)
    v0 = s.orient()["graph_version"]
    s.close()
    pid, store = _pending(db)
    r = confirm_proposal(db, store, pid, primary_source="s", gate=_gate(False), embedder=lambda t: [0.0] * 3072)
    assert r["status"] == "GATE_FAILED"
    assert any(f["kind"] == "movement_toward_governed" for f in r["gate_report"]["findings"])
    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        d = s.changed_since(v0)
        assert not d.get("concepts_added") and not d.get("edges_added")
    finally:
        s.close()


def test_reject_and_cli_list(db, capsys):
    pid, store = _pending(db)
    assert reject_proposal(store, pid, reason="dup")["status"] == "REJECTED"
    from mcp_server.proposals_cli import main as cli

    assert cli(["list", str(store)]) == 0
    assert pid in capsys.readouterr().out


def test_requeue_state_machine(db, capsys):
    """GATE_FAILED → PENDING via operator requeue; COMMITTED refuses."""
    pid, store = _pending(db)
    r = confirm_proposal(db, store, pid, primary_source="s", gate=_gate(False), embedder=lambda t: [0.0] * 3072)
    assert r["status"] == "GATE_FAILED"

    from mcp_server.proposals_cli import main as cli

    assert cli(["requeue", str(store), pid]) == 0
    s = Surface(db, enable_history=True, enable_proposals=True)
    rec = s.proposal_status(pid)
    assert rec["status"] == "PENDING" and "requeued by operator" in rec["demotion_reason"]
    s.close()
    r2 = confirm_proposal(db, store, pid, primary_source="s", gate=_gate(True), embedder=lambda t: [0.0] * 3072)
    assert r2["status"] == "COMMITTED"
    assert cli(["requeue", str(store), pid]) == 1  # cannot requeue COMMITTED


def test_commit_event_failure_restores_graph_and_leaves_retryable_status(
        db, monkeypatch):
    import mcp_server.proposals as proposals
    from interaction.write_path_store import WritePathStore
    from mcp_server.history import extract_manifest

    pid, store = _pending(db)
    before = extract_manifest(db)
    original_emit = proposals._emit

    def fail_commit_event(store_path, **kw):
        if kw.get("type") == "graph.committed":
            raise OSError("sidecar unavailable")
        return original_emit(store_path, **kw)

    monkeypatch.setattr(proposals, "_emit", fail_commit_event)
    result = proposals.confirm_proposal(
        db, store, pid, primary_source="src", gate=_gate(True),
        embedder=lambda text: [0.0] * 3072)

    assert result["status"] == "ENCODE_FAILED"
    assert "event_append_error" in result["gate_report"]
    assert extract_manifest(db) == before
    records = WritePathStore(store)
    try:
        assert records.get_proposal(pid)["status"] == "ENCODE_FAILED"
    finally:
        records.close()


def test_empty_target_refused_at_propose_time(db):
    """F3 (L2-4): empty targets made the closure test degenerate. Typed
    refusal now; legacy stored records still reject-able (untested here —
    covered by existing reject path tests)."""
    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        r = s.propose(encoding=ENC, provenance={"generating_task": "t"}, target_gap_id="")
        assert "target_gap_id is required" in r["error"]
        r2 = s.propose(encoding=ENC, provenance={"generating_task": "t"})
        assert "target_gap_id is required" in r2["error"]
        # non-empty proceeds as before
        r3 = s.propose(encoding=ENC, provenance={"generating_task": "t"}, target_gap_id="real_gap")
        assert r3.get("status") == "COMMITTED"
    finally:
        s.close()


def test_proposal_origin_separates_recovery_from_new_human_decision(db):
    """A proposal may recover source truth or offer a new decision.

    Neither is authority while queued, but only the first may claim existing
    evidence and only a human may ratify the second.
    """

    from interaction.event_log import EventStore

    s = Surface(db, enable_history=True, enable_proposals=True)
    try:
        missing_source = s.propose(
            encoding=ENC,
            provenance={"decision_origin": "recover_existing"},
            target_gap_id="test_gap",
            dry_run=True,
        )
        assert missing_source["would_queue"] is False
        assert "requires at least one source_ref" in missing_source["error"]

        recovery = s.propose(
            encoding=ENC,
            provenance={
                "decision_origin": "recover_existing",
                "source_refs": ["ADR:17"],
            },
            target_gap_id="test_gap",
            dry_run=True,
        )
        assert recovery["would_queue"] is True
        assert recovery["decision_origin"] == "recover_existing"

        proposed = s.propose(
            encoding=ENC,
            provenance={"decision_origin": "propose_new"},
            target_gap_id="new_project_decision",
            claim_level="L1",
        )
        assert proposed["status"] == "COMMITTED"
        assert proposed["claim_level_effective"] == "L0"
        assert proposed["decision_origin"] == "propose_new"
        assert "human ratification" in proposed["demotion_reason"]

        status = s.proposal_status(proposed["proposal_id"])
        assert status["decision_origin"] == "propose_new"

        events = EventStore(s._store_path)
        try:
            committed = next(
                row for row in events.list_events()
                if row["proposal_id"] == proposed["proposal_id"]
                and row["type"] == "graph.committed"
            )
        finally:
            events.close()
        assert committed["actor"] == "gate:auto-encode"
    finally:
        s.close()
