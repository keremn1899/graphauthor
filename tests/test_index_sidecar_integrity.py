"""The structural sidecar is a cache, never part of graph truth.

These tests deliberately exercise provenance changes that used to alter what
the engine saw: an edge-only edit (node count unchanged) and a legacy/foreign
sidecar beside an otherwise valid graph.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tests.fixture_db import create_fixture_db


def _observe(path: Path, node_id: str) -> dict:
    """Process-shaped Compass + deterministic retrieval, minus runtime metadata."""
    from mcp_server.surface import Surface

    surface = Surface(path)
    try:
        compass = surface._session.compass.to_dict()
        result = surface.retrieve({
            "contract_version": "retrieval-v1",
            "steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": [node_id]},
                "assign_to": "seed",
            }, {
                "tool": "get_neighbourhood",
                "params": {
                    "node_ids": "$seed",
                    "depth": 2,
                    "edge_types": ["leadsto", "contains", "expresses", "nearto"],
                    "direction": "both",
                },
                "assign_to": "neighbourhood",
            }],
            "collect": "$seed + $neighbourhood",
        }, evidence="content")
    finally:
        surface.close()

    assert result["kind"] == "RETRIEVED"
    receipt = dict(result["execution_receipt"])
    receipt.pop("elapsed_ms", None)
    receipt.pop("graph_version", None)
    receipt.pop("compass_ref", None)
    for operation in receipt["operations"]:
        operation.pop("elapsed_ms", None)
    return {
        "compass": compass,
        "program": result["program"],
        "evidence": result["evidence"],
        "receipt": receipt,
    }


def test_edge_only_edit_invalidates_structural_sidecar(tmp_path: Path) -> None:
    """A matching node count must not make an old topology look current."""
    import engine

    db_path = tmp_path / "edge_edit.lbug"
    conn = create_fixture_db("lotr", db_path)
    original_path = engine._db_path
    try:
        engine._db_path = db_path
        engine._structural_index = None
        before = engine.get_structural_index(conn)

        node_ids = sorted(before)
        source, target = node_ids[0], node_ids[-1]
        before_degree = before[source].out_degree.get("leadsto", 0)
        conn.execute(
            "MATCH (a:Concept {id: $source}), (b:Concept {id: $target}) "
            "CREATE (a)-[:LEADSTO {label: 'sidecar moat'}]->(b)",
            {"source": source, "target": target},
        )

        # Simulate the next process/session. The on-disk sidecar still has the
        # same node_count, which was the old cache-validity check.
        engine._structural_index = None
        after = engine.get_structural_index(conn)

        assert after[source].out_degree.get("leadsto", 0) == before_degree + 1
    finally:
        engine._db_path = original_path
        engine._structural_index = None


def test_graph_read_rejects_an_unbound_sidecar(tmp_path: Path) -> None:
    """Old/copied cache files without graph identity are cache misses."""
    from graph_read import read_map

    db_path = tmp_path / "foreign_cache.lbug"
    conn = create_fixture_db("lotr", db_path)
    node_ids = sorted(row[0] for row in conn.execute("MATCH (c:Concept) RETURN c.id"))
    del conn

    poison = {
        "node_count": len(node_ids),
        "index_mode": "full",
        "index": {
            node_id: {
                "roles": ["poison"],
                "betweenness_centrality": 999.0,
                "in_degree": {},
                "out_degree": {},
            }
            for node_id in node_ids
        },
    }
    db_path.with_suffix(".lbug.idx").write_text(json.dumps(poison), encoding="utf-8")

    payload = read_map(db_path)

    assert payload["structural_mode"] == "full"
    # Betweenness is the observable the poison would reach, now that the map
    # read no longer emits structural roles. 999.0 is outside the range Brandes
    # can produce here, so seeing it anywhere means the foreign cache was used.
    assert all(node["betweenness"] != 999.0 for node in payload["nodes"])


def test_compass_and_retrieval_ignore_cache_provenance_and_graph_path(
    tmp_path: Path,
) -> None:
    """Cold, warm, copied-cache, and cacheless-copy observations are equal."""
    db_path = tmp_path / "original.lbug"
    conn = create_fixture_db("lotr", db_path)
    node_id = sorted(row[0] for row in conn.execute(
        "MATCH (c:Concept) RETURN c.id"
    ))[0]
    conn.execute("CHECKPOINT")
    conn.close()
    del conn

    cold = _observe(db_path, node_id)
    warm = _observe(db_path, node_id)

    copied = tmp_path / "copied.lbug"
    shutil.copy2(db_path, copied)
    shutil.copy2(db_path.with_suffix(".lbug.idx"), copied.with_suffix(".lbug.idx"))
    copied_cache = _observe(copied, node_id)

    copied.with_suffix(".lbug.idx").unlink()
    cacheless_copy = _observe(copied, node_id)

    assert warm == cold
    assert copied_cache == cold
    assert cacheless_copy == cold


def test_snapshot_restore_recovers_the_same_compass_and_evidence(
    tmp_path: Path,
) -> None:
    """Dropping the live index during restore changes cost, not graph truth."""
    import real_ladybug as lb

    from mcp_server.history import SnapshotStore

    db_path = tmp_path / "restored.lbug"
    conn = create_fixture_db("lotr", db_path)
    node_ids = sorted(row[0] for row in conn.execute(
        "MATCH (c:Concept) RETURN c.id"
    ))
    conn.execute("CHECKPOINT")
    conn.close()
    del conn

    snapshots = SnapshotStore(db_path)
    snapshots.capture("baseline")
    baseline = _observe(db_path, node_ids[0])

    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    conn.execute(
        "MATCH (a:Concept {id: $source}), (b:Concept {id: $target}) "
        "CREATE (a)-[:LEADSTO {label: 'temporary topology'}]->(b)",
        {"source": node_ids[0], "target": node_ids[-1]},
    )
    conn.execute("CHECKPOINT")
    conn.close()
    del conn, database

    changed = _observe(db_path, node_ids[0])
    assert changed != baseline, "moat mutation did not change an observable"

    snapshots.restore("baseline")
    assert not db_path.with_suffix(".lbug.idx").exists()
    restored = _observe(db_path, node_ids[0])

    assert restored == baseline
