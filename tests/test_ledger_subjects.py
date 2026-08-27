"""Activities must say WHICH NODES they are about.

`subject_node_ids` / `graph_version_before` / `graph_version_after` are already
columns on the event log and emission sites fill them, but the activity
projection never folded them up — so a ledger row could not point at the graph
without re-reading and re-joining its own events. That fold is the whole basis
of the Screen-2 list↔graph linkage.

Deterministic: no LLM, no network.
"""

from __future__ import annotations

import json

from interaction.event_types import GRAPH_COMMITTED, GRAPH_REVERTED
from mcp_server.ledger import project_activities


def _ev(eid, ts, type_, **kw):
    row = {"event_id": eid, "ts": ts, "type": type_, "gap_id": "", "handoff_id": "",
           "proposal_id": "", "case_id": "", "conversation_id": "", "batch_id": "",
           "authority_type": "", "subject_node_ids": "[]",
           "graph_version_before": "", "graph_version_after": "", "payload": "{}"}
    row.update(kw)
    return row


def test_activity_carries_the_union_of_its_events_subjects():
    events = [
        _ev("e2", 2.0, GRAPH_COMMITTED, gap_id="gap_x", proposal_id="p1",
            subject_node_ids=json.dumps(["c_a", "c_b"]),
            graph_version_before="v0", graph_version_after="v1"),
        _ev("e3", 3.0, GRAPH_REVERTED, proposal_id="p1",
            subject_node_ids=json.dumps(["c_b", "c_c"]),
            graph_version_before="v1", graph_version_after="v0"),
    ]
    (act,) = list(project_activities(events, now=3.0).values())

    # deduped, first mention wins → reading order matches what happened
    assert act["subject_node_ids"] == ["c_a", "c_b", "c_c"]
    assert act["graph_version_before"] == "v0"
    assert act["graph_version_after"] == "v0"


def test_version_pair_spans_the_arc_not_one_step():
    """`before` from the earliest event naming one, `after` from the latest —
    a two-commit arc must diff end to end, not just its last hop."""
    events = [
        _ev("e2", 2.0, GRAPH_COMMITTED, proposal_id="p1",
            graph_version_before="v1", graph_version_after="v2"),
        _ev("e3", 3.0, GRAPH_COMMITTED, proposal_id="p1",
            graph_version_before="v2", graph_version_after="v3"),
    ]
    (act,) = list(project_activities(events, now=3.0).values())
    assert act["graph_version_before"] == "v1"
    assert act["graph_version_after"] == "v3"


def test_activity_with_no_subjects_reports_empty_not_missing():
    """A write that names no nodes still carries the field, empty."""
    events = [_ev("e1", 1.0, GRAPH_REVERTED, proposal_id="p1")]
    (act,) = list(project_activities(events, now=1.0).values())
    assert act["subject_node_ids"] == []
    assert act["graph_version_before"] == "" and act["graph_version_after"] == ""


def test_malformed_subject_ids_do_not_break_the_feed():
    """The column is free text on the wire; one bad row must not take the whole
    ledger down."""
    events = [
        _ev("e1", 1.0, GRAPH_COMMITTED, proposal_id="p1", gap_id="g",
            subject_node_ids="not json at all",
            graph_version_before="v1", graph_version_after="v2"),
        _ev("e2", 2.0, GRAPH_REVERTED, proposal_id="p1",
            subject_node_ids=json.dumps(["c_ok"])),
    ]
    (act,) = list(project_activities(events, now=2.0).values())
    assert act["subject_node_ids"] == ["c_ok"]


def test_actor_and_authority_are_lifted_last_write_wins():
    """An arc that began as an auto-encode and ended in an operator revert is
    a human-authority arc now — the feed sorts and filters on that."""
    events = [
        _ev("e1", 1.0, GRAPH_COMMITTED, proposal_id="p1", gap_id="g",
            actor="gate:auto-encode", authority_type="gate",
            graph_version_before="v1", graph_version_after="v2"),
        _ev("e2", 2.0, GRAPH_REVERTED, proposal_id="p1",
            actor="kerem", authority_type="human",
            graph_version_before="v2", graph_version_after="v1"),
    ]
    (act,) = list(project_activities(events, now=2.0).values())
    assert act["actor"] == "kerem"
    assert act["authority_type"] == "human"


def test_actor_absent_is_empty_not_missing():
    events = [_ev("e1", 1.0, GRAPH_COMMITTED, proposal_id="p1")]
    (act,) = list(project_activities(events, now=1.0).values())
    assert act["actor"] == "" and act["authority_type"] == ""


def test_retired_types_are_recorded_but_never_projected():
    from mcp_server.ledger import project_activities, projects_to_activity

    for event_type in ("query.asked", "query.completed",
                       "query.completed:CONFIRMED", "governance.coverage_checked:GOVERNED",
                       "proposal.submitted", "receipt.issued"):
        assert not projects_to_activity(event_type), event_type

    events = [
        _ev("e1", 1.0, "query.completed:CONFIRMED", conversation_id="c1"),
        _ev("e2", 2.0, "governance.coverage_checked:GOVERNED", conversation_id="c1"),
    ]
    assert project_activities(events, now=3.0) == {}
