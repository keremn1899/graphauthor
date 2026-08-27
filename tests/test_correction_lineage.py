"""Correction commits must be visible to live lineage readers.

D1 chose mutation over retraction because graph snapshots already preserve the
prior text. That only works for live readers if the corrected node is named on
GRAPH_COMMITTED and lineage surfaces the reason + prior version.
"""

from __future__ import annotations

import json
import shutil

import pytest

from interaction.event_log import EventStore
from interaction.write_path_store import WritePathStore
from mcp_server.fixture import ensure_fixture
from mcp_server.history import graph_fingerprint
from mcp_server.lineage import node_lineage
from mcp_server.proposals import GateSpec, confirm_proposal
from mcp_server.surface import Surface

EMB = lambda _t: [0.0] * 3072  # noqa: E731


@pytest.fixture()
def db(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def _gate():
    return GateSpec(
        target_gap_id="g",
        policy_id="order_service",
        policy_in_grounding=lambda r, pid, also=None: pid in str(r.get("grounding", "")),
        adjacent_only=lambda r, *a: False,
        runner=lambda: (
            [{"governance_verdict": "GOVERNED", "grounding": "order_service"}] * 5,
            {"a": [{"governance_verdict": "UNGOVERNED"}] * 5},
        ),
        baseline={"a": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}},
        intrinsic_ids=("a",),
        encoded_gap_ids=("g",),
        intentional_closure_ids=("g",),
    )


def _queue(db_path, encoding):
    from pathlib import Path

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


def test_a_correction_commit_names_the_rewritten_node(db):
    pid, store_path = _queue(db, {
        "corrections": [{
            "id": "order_service",
            "text_content": "historical note only",
            "reason": "never carried authority",
            "intent": "withdraw_force",
            "claim_kind": "contextual",
        }],
    })
    result = confirm_proposal(
        db, store_path, pid, primary_source="ADR-1", gate=_gate(), embedder=EMB,
        correction_probe_cap=40,
        correction_oracle_factory=lambda _db, probes: (
            lambda _m: {p: "UNGOVERNED" for p in probes}
        ),
    )
    assert result["status"] == "COMMITTED", result

    events = EventStore(store_path).list_events()
    committed = [e for e in events if e["type"] == "graph.committed"]
    assert committed
    subjects = json.loads(committed[-1]["subject_node_ids"])
    assert "order_service" in subjects
    payload = json.loads(committed[-1]["payload"] or "{}")
    assert "order_service" in payload.get("subject_correction_ids", [])
    assert payload["correction_reasons"][0]["reason"] == "never carried authority"


def test_lineage_surfaces_correction_reason_and_prior_version(db):
    pid, store_path = _queue(db, {
        "corrections": [{
            "id": "order_service",
            "text_content": "historical note only",
            "reason": "never carried authority",
            "intent": "withdraw_force",
            "claim_kind": "contextual",
        }],
    })
    result = confirm_proposal(
        db, store_path, pid, primary_source="ADR-1", gate=_gate(), embedder=EMB,
        correction_probe_cap=40,
        correction_oracle_factory=lambda _db, probes: (
            lambda _m: {p: "UNGOVERNED" for p in probes}
        ),
    )
    assert result["status"] == "COMMITTED", result

    lin = node_lineage("order_service", store_path=store_path, db_path=db)
    assert lin["origin"] == "correction"
    assert lin["recorded"]["correction"] is True
    assert lin["recorded"]["graph_version_before"] == result["graph_version_before"]
    assert "order_service" in lin["recorded"]["corrected_ids"]
    corr_step = next(s for s in lin["chain"] if s["step"] == "correction")
    assert corr_step["reason"] == "never carried authority"
    assert corr_step["graph_version_before"] == result["graph_version_before"]


def test_latest_commit_wins_when_a_node_is_corrected_after_an_add(db, tmp_path):
    """An earlier add commit must not hide a later correction."""
    from mcp_server.lineage import _committed_for_node

    events = [
        {
            "type": "graph.committed",
            "event_id": "e1",
            "proposal_id": "prop_add",
            "subject_node_ids": '["n1"]',
            "payload": "{}",
            "graph_version_before": "pre-add",
            "graph_version_after": "post-add",
        },
        {
            "type": "graph.committed",
            "event_id": "e2",
            "proposal_id": "prop_corr",
            "subject_node_ids": '["n1"]',
            "payload": json.dumps({
                "subject_correction_ids": ["n1"],
                "correction_reasons": [
                    {"id": "n1", "reason": "typo", "intent": "restate", "claim_kind": ""},
                ],
            }),
            "graph_version_before": "pre-corr",
            "graph_version_after": "post-corr",
        },
    ]
    assert _committed_for_node(events, "n1")["event_id"] == "e2"
