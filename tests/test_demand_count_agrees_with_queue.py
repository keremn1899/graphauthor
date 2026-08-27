"""The number in the nav and the rows in the queue have to be the same claim.

Writes settle immediately. ``needs_me`` is false for committed and reverted
rows. The projector must keep that agreement: an activity with an open
action is counted, and a counted activity still carries an action. With
no human queue the interesting case is that settling never leaves a
phantom demand.
"""

from __future__ import annotations

import time

import interaction.event_types as event_types
from mcp_server.ledger import project_activities

IDLE_WINDOW = 30 * 60


def _event(**over):
    base = {
        "event_id": "ev_1",
        "ts": time.time(),
        "type": event_types.GRAPH_COMMITTED,
        "actor": "gate:auto-encode",
        "authority_type": "gate",
        "trace_id": "t1",
        "conversation_id": "",
        "case_id": "",
        "gap_id": "",
        "handoff_id": "",
        "proposal_id": "",
        "batch_id": "",
        "graph_version_before": "",
        "graph_version_after": "",
        "subject_node_ids": "[]",
        "reason": "",
        "payload": "{}",
        "causation_id": "",
    }
    base.update(over)
    return base


def _committed(ts, *, proposal_id="p1", event_id="ev_commit"):
    return _event(
        event_id=event_id,
        ts=ts,
        type=event_types.GRAPH_COMMITTED,
        proposal_id=proposal_id,
        gap_id="rollback_scope",
        actor="gate:auto-encode",
        authority_type="gate",
        graph_version_before="v1",
        graph_version_after="v2",
    )


def _reverted(ts, *, proposal_id="p1", event_id="ev_rev"):
    return _event(
        event_id=event_id,
        ts=ts,
        type=event_types.GRAPH_REVERTED,
        actor="kerem",
        authority_type="human",
        proposal_id=proposal_id,
        gap_id="rollback_scope",
        graph_version_before="v2",
        graph_version_after="v1",
    )


def _assert_agreement(acts, note):
    """`needs_me` and "carries an open action" must name the same activities."""
    for act in acts.values():
        carries_action = bool(act["open_actionable"])
        assert act["needs_me"] == carries_action, (
            f"{note}: activity {act['activity_id']} ({act['kind']}, "
            f"state={act['state']}) has open_actionable={act['open_actionable']} "
            f"but needs_me={act['needs_me']} — the nav count and the queue's "
            "admission test would disagree about this row"
        )


def test_committed_write_agrees():
    now = time.time()
    acts = project_activities([_committed(now)], now=now)

    (act,) = acts.values()
    assert act["state"] == "SETTLED"
    assert act["resolution"] == "committed"
    assert act["open_actionable"] == []
    assert act["needs_me"] is False
    _assert_agreement(acts, "committed write")


def test_reverted_write_agrees():
    now = time.time()
    acts = project_activities([_reverted(now)], now=now)

    (act,) = acts.values()
    assert act["state"] == "SETTLED"
    assert act["resolution"] == "reverted"
    assert act["needs_me"] is False
    _assert_agreement(acts, "reverted write")


def test_commit_then_revert_agrees():
    now = time.time()
    acts = project_activities(
        [_committed(now - 60), _reverted(now)], now=now
    )

    (act,) = acts.values()
    assert act["state"] == "SETTLED"
    assert act["resolution"] == "reverted"
    assert act["needs_me"] is False
    _assert_agreement(acts, "commit then revert")


def test_aged_writes_agree():
    """Write events settle immediately; they do not idle."""
    old = time.time() - (IDLE_WINDOW * 5)
    now = time.time()
    acts = project_activities(
        [_committed(old, proposal_id="p_old")], now=now
    )

    assert acts, "the fixture produced no activities; the test would be vacuous"
    (act,) = acts.values()
    assert act["state"] == "SETTLED"
    _assert_agreement(acts, "aged, past every idle window")


def test_mixed_feed_agrees():
    now = time.time()
    events = [
        _committed(now - 200, proposal_id="p_done", event_id="e1"),
        _committed(now - 100, proposal_id="p_later", event_id="e2"),
        _reverted(now - 50, proposal_id="p_later", event_id="e3"),
    ]
    acts = project_activities(events, now=now)

    assert len(acts) == 2, f"expected two arcs, got {sorted(acts)}"
    _assert_agreement(acts, "mixed feed")
    assert sum(1 for a in acts.values() if a["needs_me"]) == 0


def test_health_count_equals_the_activities_that_need_me(tmp_path):
    from mcp_server.operator import OperatorSurface

    op = OperatorSurface(tmp_path / "g.lbug", tmp_path / "store.sqlite")

    expected = sum(1 for a in op.activities() if a.get("needs_me"))
    assert op.health()["needs_me_count"] == expected
    assert op.inbox()["needs_me_count"] == expected, (
        "health and inbox are two readings of one count; the nav uses health"
    )


def test_health_exposes_the_field_the_nav_reads(tmp_path):
    from mcp_server.operator import OperatorSurface

    op = OperatorSurface(tmp_path / "g.lbug", tmp_path / "store.sqlite")
    health = op.health()

    assert "needs_me_count" in health
    assert isinstance(health["needs_me_count"], int)
