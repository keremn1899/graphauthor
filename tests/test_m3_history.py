"""M3 history tests — snapshot store, content-based diff, operator revert.

Executable source of truth: scripts/run_m3_battery.py (M3_PASS pre-registered).
These keep the guarantees in the pytest loop at unit granularity.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mcp_server.fixture import ensure_fixture
from mcp_server.history import SnapshotStore, diff_manifests, extract_manifest
from mcp_server.surface import Surface


@pytest.fixture()
def db(tmp_path) -> Path:
    return ensure_fixture(tmp_path / "g.lbug")


def _add(db: Path, cid: str) -> None:
    import real_ladybug as lb

    d = lb.Database(str(db))
    c = lb.Connection(d)
    c.execute(
        "CREATE (:Concept {id: $id, label: $id, text_content: 'b', semantic_anchor: 'a', "
        "embedding: $e, token_count: 1, centrality_score: 0.0, is_metanode: false, linked_graph_id: ''})",
        {"id": cid, "e": [0.0] * 3072},
    )
    del c, d


def test_manifest_shape_and_diff(db):
    m0 = extract_manifest(db)
    assert len(m0["concepts"]) == 6 and len(m0["edges"]) == 6
    _add(db, "x1")
    m1 = extract_manifest(db)
    d = diff_manifests(m0, m1)
    assert [c["id"] for c in d["concepts_added"]] == ["x1"]
    assert not d["concepts_removed"] and not d["edges_added"] and not d["edges_removed"]


def test_diff_is_content_based_not_version_based(db):
    store = SnapshotStore(db)
    store.capture("vA")
    db.touch()  # mtime churn, no content change
    store.capture("vB")
    d = store.diff("vA", "vB")
    assert not any(d[k] for k in d)


def test_unknown_version_is_typed_error(db):
    store = SnapshotStore(db)
    store.capture("vA")
    assert "unknown version" in store.diff("vA", "nope")["error"]


def test_restore_swaps_content_and_drops_stale_index(db):
    store = SnapshotStore(db)
    store.capture("vA")
    _add(db, "x2")
    idx = db.parent / f"{db.name}.idx"
    idx.write_text("stale")
    store.restore("vA")
    assert not idx.exists()
    assert "x2" not in extract_manifest(db)["concepts"]


def test_operator_revert_records_a_focusable_write(db, tmp_path):
    from interaction.event_log import EventStore
    from mcp_server.history_cli import revert
    from mcp_server.ledger import project_activities

    snapshots = SnapshotStore(db)
    snapshots.capture("vA")
    _add(db, "x_reverted")
    store_path = tmp_path / "events.sqlite"

    revert(db, "vA", store_path=store_path, actor="Ada")

    events = EventStore(store_path)
    try:
        rows = events.list_events()
    finally:
        events.close()
    assert len(rows) == 1 and rows[0]["type"] == "graph.reverted"
    assert rows[0]["actor"] == "Ada"
    assert rows[0]["graph_version_after"] == "vA"
    assert rows[0]["subject_node_ids"] == '["x_reverted"]'
    (activity,) = project_activities(rows).values()
    assert activity["kind"] == "gap"
    assert activity["state"] == "SETTLED"
    assert activity["resolution"] == "reverted"
    assert activity["incident"] is False


def test_surface_version_stable_per_session_and_capability(db):
    s = Surface(db, enable_history=True)
    try:
        o1, o2 = s.orient(), s.orient()
        assert o1["graph_version"] == o2["graph_version"]
        assert "history" in o1["capabilities"]
        vs = s.history()["versions"]
        assert any(v["graph_version"] == o1["graph_version"] for v in vs)
    finally:
        s.close()


def test_history_disabled_is_typed(db):
    s = Surface(db)
    try:
        assert "not enabled" in s.history()["error"]
        assert "history" not in s.orient()["capabilities"]
    finally:
        s.close()


def test_history_tool_refuses_revert(db):
    s = Surface(db, enable_history=True)
    try:
        out = s.history_action({"action": "revert", "version": "vA"})
        assert out["error"].startswith("revert")
    finally:
        s.close()
