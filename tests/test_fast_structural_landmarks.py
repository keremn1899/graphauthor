"""Fast structural index must still produce landmarks + degree centrality_score."""

from __future__ import annotations

import os

from engine import compute_compass, compute_structural_index, describe_graph


def test_fast_mode_writes_centrality_and_degree_landmarks(deps_conn, monkeypatch):
    monkeypatch.setenv("SST_FAST_STRUCTURAL_INDEX", "1")
    index = compute_structural_index(deps_conn)
    assert index
    assert all(f.betweenness_centrality == 0.0 for f in index.values())

    # Degree score persisted on Concept even when Brandes is skipped.
    scored = 0
    for nid, facts in index.items():
        rows = list(deps_conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.centrality_score",
            {"id": nid},
        ))
        assert rows, nid
        score = float(rows[0][0] or 0)
        if facts.total_degree > 0:
            assert score > 0, nid
            scored += 1
    assert scored > 0, "expected at least one connected node with centrality_score"

    compass = compute_compass(deps_conn, index)
    assert compass.landmark_nodes, "fast mode must not collapse landmarks to empty"
    assert all(lm.get("importance_kind") == "degree" for lm in compass.landmark_nodes)

    desc = describe_graph(deps_conn, index, compass, graph_id="deps")
    assert desc["centrality_score_meaning"] == "normalised_degree"
    assert desc["landmark_preview"]
    assert desc["node_centrality"]
    assert len(desc["node_centrality"]) == len(index)


def test_full_mode_landmarks_prefer_betweenness(deps_conn, monkeypatch):
    monkeypatch.delenv("SST_FAST_STRUCTURAL_INDEX", raising=False)
    # Force a recompute path: unset alone is enough when compute reads env.
    os.environ.pop("SST_FAST_STRUCTURAL_INDEX", None)
    index = compute_structural_index(deps_conn)
    compass = compute_compass(deps_conn, index)
    if any(f.betweenness_centrality > 0 for f in index.values()):
        assert compass.landmark_nodes
        assert all(lm.get("importance_kind") == "betweenness" for lm in compass.landmark_nodes)
