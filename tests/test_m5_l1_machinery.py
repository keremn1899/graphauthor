"""L1 machinery unit tests behind scripts/run_m5_battery.py + transcript logging."""

from __future__ import annotations

import json
import shutil

import pytest

from mcp_server.fixture import ensure_fixture
from mcp_server.proposals import WritePolicy, _gate_for_proposal, frontier_check
from mcp_server.surface import Surface


@pytest.fixture()
def db(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def test_frontier_requires_occurrences_and_typing(db, tmp_path):
    from interaction.write_path_store import WritePathStore
    from interaction.escalation import EscalationHandoff

    store = WritePathStore(tmp_path / "s.sqlite")
    pol = WritePolicy(l1_admitted=True, legislatable=lambda p: p == "known_pred")
    ok, why = frontier_check(store, "known_pred", pol)
    assert not ok and "0 escalation" in why
    for i in range(3):
        store.save_handoff(EscalationHandoff(
            handoff_id=f"h{i}", decision_id=f"d{i}", question="q",
            ungoverned_predicate="known_pred", status="OPEN", resolution="ESCALATE"))
    ok, _ = frontier_check(store, "known_pred", pol)
    assert ok
    ok, why = frontier_check(store, "", pol)
    assert not ok and "no target predicate" in why
    pol2 = WritePolicy(l1_admitted=True, legislatable=lambda p: False)
    ok, why = frontier_check(store, "known_pred", pol2)
    assert not ok and "LEGISLATABLE" in why
    store.close()


def test_gate_provider_supports_legacy_and_record_aware_forms():
    record = {"proposal_id": "prop_1", "target_gap_id": "replay_api_component"}
    assert _gate_for_proposal(lambda: "legacy", record) == "legacy"
    assert _gate_for_proposal(lambda proposal: proposal["target_gap_id"], record) == (
        "replay_api_component"
    )


def test_new_decisions_cannot_self_source_l1_authority():
    from mcp_server.proposals import ProposalProvenance, _l1_provenance_ok

    ok, why = _l1_provenance_ok(
        ProposalProvenance(
            generating_task="implement retry policy",
            source_refs=["diff:abc123"],
            decision_origin="propose_new",
        )
    )

    assert ok is False
    assert "human ratification" in why


def test_l1_green_commit_reopens_session_consistently(db):
    from mcp_server.proposals import GateSpec

    pol = WritePolicy(
        l1_admitted=True, admission_evidence="test",
        legislatable=lambda p: True,
        gate_provider=lambda: GateSpec(
            target_gap_id="pred", policy_id="c1",
            policy_in_grounding=lambda r, pid, also=None: pid in str(r.get("grounding", "")),
            adjacent_only=lambda r, *a: False,
            runner=lambda: ([{"governance_verdict": "GOVERNED", "grounding": "c1"}] * 5, {}),
            baseline={}, encoded_gap_ids=("pred",), intentional_closure_ids=("pred",)),
        embedder=lambda t: [0.0] * 3072)
    s = Surface(db, enable_history=True, enable_proposals=True, write_policy=pol)
    try:
        for i in range(3):
            s.escalate(question="q", ungoverned_predicate="pred")
        r = s.propose(
            encoding={"concepts": [{"id": "c1", "label": "C1", "text_content": "x", "semantic_anchor": "x"}], "edges": []},
            provenance={"generating_task": "t", "source_refs": ["run://1"]},
            target_gap_id="pred", claim_level="L1")
        assert r["status"] == "COMMITTED"
        # session observes post-commit content immediately
        assert s.orient()["node_count"] == 31
        assert r["graph_version"] == s.orient()["graph_version"]
        from interaction.event_log import EventStore

        events = EventStore(s._store_path)
        try:
            proposal_events = [
                row for row in events.list_events()
                if row.get("proposal_id") == r["proposal_id"]
            ]
        finally:
            events.close()
        assert [row["type"] for row in proposal_events] == ["graph.committed"]
        assert proposal_events[-1]["actor"] == "gate:auto-encode"
        assert proposal_events[-1]["authority_type"] == "gate"
    finally:
        s.close()


def test_transcript_logging_slims_and_appends(db, tmp_path):
    import asyncio

    import mcp.types as types

    from mcp_server.stdio import build_server

    log = tmp_path / "t.jsonl"
    s = Surface(db)
    try:
        server = build_server(s, transcript_path=str(log))
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="orient", arguments={}))
        handler = server.request_handlers[type(req)]
        asyncio.run(handler(req))
        asyncio.run(handler(req))
    finally:
        s.close()
    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(lines) == 2 and lines[0]["tool"] == "orient"
    assert "graph_version" in lines[0]["response"]
    assert "landmark_preview" not in lines[0]["response"]  # slim, not full payload


def test_transcript_full_mode_records_what_the_caller_saw(db, tmp_path, monkeypatch):
    """L2-4 session-1 operator finding: slim transcripts support linkage but
    not content-level claim audit. full mode records the complete wire
    response (already capped/stripped by the surface) — exactly what the
    builder saw, nothing more. slim stays the default, byte-compatible."""
    import asyncio

    import mcp.types as types

    from mcp_server.stdio import build_server

    def _call(server, log):
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="search",
                arguments={"query": "domain layer", "mode": "lexical"}))
        handler = server.request_handlers[type(req)]
        asyncio.run(handler(req))
        return [json.loads(l) for l in log.read_text().splitlines()]

    # full mode: complete response, including fields slim drops
    log_full = tmp_path / "full.jsonl"
    s = Surface(db)
    try:
        lines = _call(build_server(s, transcript_path=str(log_full), transcript_level="full"), log_full)
    finally:
        s.close()
    row = lines[0]
    assert row["level"] == "full"
    # `contract_version` and `mode` are absent from the slim key list, so their
    # presence is exactly what distinguishes a full record from a slim one.
    assert "contract_version" in row["response"]
    assert row["response"]["kind"]  # verdict-level fields still present

    # env-driven selection; slim default unchanged
    log_slim = tmp_path / "slim.jsonl"
    monkeypatch.delenv("SST_MCP_TRANSCRIPT_LEVEL", raising=False)
    s = Surface(db)
    try:
        lines = _call(build_server(s, transcript_path=str(log_slim)), log_slim)
    finally:
        s.close()
    row = lines[0]
    assert row["level"] == "slim"
    assert set(row["response"]).issubset({
        "verdict", "status", "kind", "error", "graph_version",
        "proposal_id", "handoff_id", "ungoverned_predicate",
        "engine_degraded", "trace_id"})
