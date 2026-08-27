"""Events + projector — pytest wrappers over the remaining write record."""

from __future__ import annotations

from interaction.event_types import GRAPH_COMMITTED, GRAPH_REVERTED


def test_projector_is_pure_and_deterministic():
    from mcp_server.ledger import project_activities

    ev = [
        {"event_id": "e3", "ts": 3.0, "type": GRAPH_COMMITTED, "gap_id": "g",
         "handoff_id": "", "proposal_id": "p1", "case_id": "", "conversation_id": "",
         "batch_id": "", "trace_id": "t", "actor": "gate:auto-encode",
         "authority_type": "gate",
         "graph_version_before": "a", "graph_version_after": "b",
         "subject_node_ids": '["c1"]', "payload": "{}"},
    ]
    a1 = project_activities(ev, now=100.0)
    a2 = project_activities(list(ev), now=100.0)
    assert a1.keys() == a2.keys() and len(a1) == 1
    arc = next(iter(a1.values()))
    assert arc["kind"] == "gap" and arc["state"] == "SETTLED" and arc["resolution"] == "committed"
    assert arc["weight"] == "notable" and not arc["needs_me"]


def test_projector_replays_by_event_time_not_input_order():
    from mcp_server.ledger import project_activities

    events = [
        {"event_id": "e2", "ts": 2.0, "type": GRAPH_COMMITTED, "gap_id": "g",
         "handoff_id": "", "proposal_id": "p1", "case_id": "", "conversation_id": "",
         "batch_id": "", "trace_id": "t", "actor": "gate:auto-encode",
         "authority_type": "gate",
         "graph_version_before": "v0", "graph_version_after": "v1",
         "subject_node_ids": '["c1"]', "payload": "{}"},
        {"event_id": "e3", "ts": 3.0, "type": GRAPH_REVERTED, "gap_id": "g",
         "handoff_id": "", "proposal_id": "p1", "case_id": "", "conversation_id": "",
         "batch_id": "", "trace_id": "t", "actor": "Ada", "authority_type": "human",
         "graph_version_before": "v1", "graph_version_after": "v0",
         "subject_node_ids": '["c1"]', "payload": "{}"},
    ]

    chronological = project_activities(events, now=10.0)
    reversed_replay = project_activities(list(reversed(events)), now=10.0)
    assert reversed_replay == chronological
    assert len(reversed_replay) == 1
    arc = next(iter(reversed_replay.values()))
    assert arc["resolution"] == "reverted"


def test_write_path_settles_immediately():
    """Committed and reverted never sit OPEN and never idle."""
    from mcp_server.ledger import project_activities

    ev = [{"event_id": "p1", "ts": 10.0,
           "type": GRAPH_COMMITTED, "proposal_id": "p1",
           "gap_id": "", "handoff_id": "", "case_id": "", "conversation_id": "",
           "batch_id": "", "trace_id": "t", "actor": "gate:auto-encode",
           "authority_type": "gate",
           "graph_version_before": "a", "graph_version_after": "b",
           "subject_node_ids": "[]", "payload": "{}"}]
    assert next(iter(project_activities(ev, now=20.0, idle_window=100).values()))["state"] == "SETTLED"
    assert next(iter(project_activities(ev, now=500.0, idle_window=100).values()))["state"] == "SETTLED"


def test_event_store_append_only_roundtrip(tmp_path):
    from interaction.event_log import EventStore

    es = EventStore(tmp_path / "s.sqlite")
    es.emit(type=GRAPH_COMMITTED, gap_id="g", proposal_id="p1", actor="gate:auto-encode",
            authority_type="gate", subject_node_ids=["n1"], payload={"q": "?"})
    es.emit(type=GRAPH_REVERTED, proposal_id="p1", actor="op", authority_type="human")
    rows = es.list_events()
    es.close()
    assert [r["type"] for r in rows] == [GRAPH_COMMITTED, GRAPH_REVERTED]
    assert rows[0]["gap_id"] == "g" and rows[1]["actor"] == "op"


def test_existing_event_store_migrates_causation_additively(tmp_path):
    import sqlite3

    from interaction.event_log import EventStore, _SCHEMA

    path = tmp_path / "old.sqlite"
    old_schema = _SCHEMA.replace(
        "    causation_event_id TEXT NOT NULL DEFAULT '',\n", "")
    connection = sqlite3.connect(path)
    connection.executescript(old_schema)
    connection.close()

    events = EventStore(path)
    events.emit(
        type=GRAPH_COMMITTED, causation_event_id="ev_parent",
        actor="gate:auto-encode", authority_type="gate")
    rows = events.list_events()
    events.close()
    assert rows[0]["causation_event_id"] == "ev_parent"


def test_retired_and_unknown_extensions_never_create_phantom_demand():
    from mcp_server.ledger import event_contract, project_activities

    events = [
        {"event_id": "origin", "ts": 1.0, "type": "receipt.issued",
         "actor": "gate", "authority_type": "gate",
         "graph_version_after": "origin:1", "payload": '{"diff_hash":"abc"}'},
        {"event_id": "future", "ts": 2.0, "type": "extension.not_yet_understood",
         "actor": "system", "authority_type": "system", "payload": "{}"},
    ]
    activities = list(project_activities(events, now=2.0).values())
    assert event_contract("receipt.issued") == {
        "activity_kind": "misc", "role": "unknown"}
    assert event_contract("extension.not_yet_understood") == {
        "activity_kind": "misc", "role": "unknown"}
    assert {a["kind"] for a in activities} == {"misc"}
    assert all(a["state"] == "SETTLED" for a in activities)
    assert all(not a["needs_me"] and not a["incident"] for a in activities)


def test_retired_types_do_not_project():
    from mcp_server.ledger import project_activities, projects_to_activity

    retired = (
        "escalation.recorded",
        "query.completed:CONFIRMED",
        "governance.coverage_checked:GOVERNED",
        "conformance.completed:VIOLATES",
        "absence.dispositioned:local_choice",
        "rationalization.flagged",
        "incident.acknowledged",
        "system.fault",
        "construction.review_required",
        "graph.created",
        "proposal.submitted",
        "gate.completed:green",
        "receipt.issued",
    )
    for event_type in retired:
        assert not projects_to_activity(event_type), event_type
    events = [
        {"event_id": str(i), "ts": float(i), "type": event_type,
         "actor": "system", "authority_type": "system", "payload": "{}"}
        for i, event_type in enumerate(retired, start=1)
    ]
    assert project_activities(events, now=100.0) == {}
