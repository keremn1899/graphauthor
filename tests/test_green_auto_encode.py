"""Propose auto-commits. Sourceless, ungated, and correction writes commit
when they pass mechanical checks. MCP has no confirm verb.
"""

from __future__ import annotations

from interaction.event_log import EventStore
from interaction.event_types import GRAPH_COMMITTED
from mcp_server.fixture import ensure_fixture
from mcp_server.http import GateProvider
from mcp_server.proposals import GateSpec
from mcp_server.surface import Surface

ENC = {
    "concepts": [
        {
            "id": "p_auto",
            "label": "Auto",
            "text_content": "body",
            "semantic_anchor": "a",
        }
    ],
    "edges": [
        {
            "type": "EXPRESSES",
            "source_id": "p_auto",
            "target_id": "order_service",
            "label": "l",
        }
    ],
}

EMB = lambda _t: [0.0] * 3072  # noqa: E731


def _battery(green: bool = True):
    def closure():
        return [
            {"governance_verdict": "GOVERNED", "grounding": "p_auto adjudicates"}
        ] * 3

    def pins():
        return {
            "moat": [
                {"governance_verdict": "UNGOVERNED" if green else "GOVERNED"}
            ]
            * 3
        }

    def build_gate_for(db_path, proposal, store_path=None):
        return GateSpec(
            target_gap_id="auto_gap",
            policy_id="p_auto",
            policy_in_grounding=lambda r, pid, also=None: True,
            adjacent_only=lambda r, *a: False,
            runner=lambda: (closure(), pins()),
            baseline={
                "moat": {"n": 3, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}
            },
            intrinsic_ids=("moat",),
            encoded_gap_ids=("auto_gap",),
            intentional_closure_ids=("auto_gap",),
            closure_runner=closure,
            pins_runner=pins,
        )

    return build_gate_for


def _world(tmp_path, *, gated: bool):
    db = ensure_fixture(tmp_path / "g.lbug")
    store = tmp_path / "store.sqlite"
    provider = GateProvider(_battery(True), db, store) if gated else None
    surface = Surface(
        db,
        store_path=store,
        enable_proposals=True,
        enable_history=True,
        gate_provider=provider,
    )
    surface._preflight_embedder = EMB
    return surface


def _assert_committed(surface, out):
    assert out.get("status") == "COMMITTED", out
    events = EventStore(surface._store_path)
    try:
        committed = [
            row
            for row in events.list_events()
            if row["type"] == GRAPH_COMMITTED
            and row.get("proposal_id") == out["proposal_id"]
        ]
    finally:
        events.close()
    assert len(committed) == 1
    row = committed[0]
    assert row["graph_version_before"]
    assert row["graph_version_after"]
    assert row["actor"] == "gate:auto-encode"
    rec = surface._get_store().get_proposal(out["proposal_id"])
    assert rec["status"] == "COMMITTED"


def test_sourced_add_commits_when_the_gate_is_green(tmp_path):
    surface = _world(tmp_path, gated=True)
    try:
        out = surface.propose(
            encoding=ENC,
            provenance={"generating_task": "t", "source_refs": ["ADR:auto"]},
            target_gap_id="auto_gap",
        )
        _assert_committed(surface, out)
    finally:
        surface.close()


def test_sourceless_propose_commits(tmp_path):
    surface = _world(tmp_path, gated=True)
    try:
        out = surface.propose(
            encoding=ENC,
            provenance={"generating_task": "t"},
            target_gap_id="auto_gap",
        )
        _assert_committed(surface, out)
    finally:
        surface.close()


def test_sourced_propose_without_harness_or_gate_commits(tmp_path):
    surface = _world(tmp_path, gated=False)
    try:
        out = surface.propose(
            encoding=ENC,
            provenance={"generating_task": "t", "source_refs": ["ADR:auto"]},
            target_gap_id="auto_gap",
        )
        _assert_committed(surface, out)
    finally:
        surface.close()


def test_corrections_auto_commit(tmp_path):
    surface = _world(tmp_path, gated=True)
    try:
        out = surface.propose(
            encoding={
                "corrections": [
                    {
                        "id": "order_service",
                        "text_content": "rewritten",
                        "reason": "note",
                        "intent": "restate",
                    }
                ]
            },
            provenance={
                "generating_task": "t",
                "source_refs": ["ADR:auto"],
                "decision_origin": "recover_existing",
            },
            target_gap_id="auto_gap",
        )
        _assert_committed(surface, out)
    finally:
        surface.close()
