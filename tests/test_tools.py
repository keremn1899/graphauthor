"""Tool-level smoke tests on a local DB (no full LangGraph)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine import StructuralFacts
from tools import (
    exact_node_lookup,
    find_paths,
    get_anchor_previews,
    get_neighbourhood,
    get_structural_profile,
    hop_expansion,
    id_pattern_lookup,
    vector_search,
)


def test_hop_expansion_leadsto_forward_one(deps_conn):
    out = hop_expansion(
        deps_conn,
        ["svc_gateway"],
        {"leadsto": {"forward": 1}},
    )
    ids = {n["id"] for n in out}
    assert "svc_auth" in ids
    assert "svc_order" in ids


def test_find_paths_gateway_to_user_db(deps_conn):
    paths = find_paths(deps_conn, ["svc_gateway"], ["db_user"], max_hops=6)
    assert paths, "expected at least one path"
    best = min(paths, key=lambda p: p.get("length", 99))
    assert best["length"] <= 3
    assert "db_user" in best["node_chain"]


def test_get_neighbourhood_incoming_single_type(deps_conn):
    """v7: get_neighbourhood replaces get_neighbours. direction='incoming'
    + edge_types=['leadsto'] recovers the single-type-single-direction case
    the old alias covered, and also surfaces the traversed edges."""
    nodes = get_neighbourhood(
        deps_conn,
        ["db_user"],
        depth=1,
        edge_types=["leadsto"],
        direction="incoming",
    )
    ids = {n["id"] for n in nodes}
    assert "svc_auth" in ids
    assert "svc_payment" in ids


def test_get_neighbourhood_returns_edge_records(deps_conn):
    """v7 regression fix: get_neighbourhood now returns edge_records
    alongside nodes (stashed on the first node via `_edge_records`).
    This is the root cause of the v6 packet_edge_underflow cluster."""
    nodes = get_neighbourhood(deps_conn, ["svc_gateway"], depth=1)
    assert nodes, "expected at least one neighbour"
    edges = nodes[0].get("_edge_records") or []
    assert edges, "expected edge_records stashed on first node"
    types = {e["edge_type"] for e in edges}
    assert "leadsto" in types
    # Every edge has the endpoints populated.
    for e in edges:
        assert e["source_id"] and e["target_id"] and e["edge_type"]


def test_id_pattern_lookup_glob(deps_conn):
    """v7: id_pattern_lookup must treat `*` as a wildcard, not a literal."""
    hits = id_pattern_lookup(deps_conn, "svc_*", k=50)
    ids = {h["id"] for h in hits}
    # All IDs in the dependencies fixture that start with svc_.
    assert "svc_gateway" in ids
    assert "svc_auth" in ids
    # No db_* nodes leak through.
    assert not any(nid.startswith("db_") for nid in ids)


def test_id_pattern_lookup_prefix(deps_conn):
    """Plain prefix (no wildcard) is case-insensitive substring on ID."""
    hits = id_pattern_lookup(deps_conn, "db_", k=50)
    ids = {h["id"] for h in hits}
    assert any(nid.startswith("db_") for nid in ids)
    assert not any(nid.startswith("svc_") for nid in ids)


def test_id_pattern_lookup_regex(deps_conn):
    hits = id_pattern_lookup(deps_conn, r"re:^svc_(auth|order)$", k=10)
    ids = {h["id"] for h in hits}
    assert ids == {"svc_auth", "svc_order"}


def test_get_structural_profile_centrality_alias(deps_conn):
    """v7: `centrality` is an alias for `betweenness` and the tool returns a
    score-sorted NodeRecord list. The structural_index is synthetic — just
    enough to exercise the sort."""
    idx = {
        "svc_gateway": StructuralFacts(
            roles=["inter_region_bridge"], betweenness_centrality=0.75,
            out_degree={"leadsto": 3},
        ),
        "svc_auth": StructuralFacts(
            roles=["causal_nexus"], betweenness_centrality=0.50,
            in_degree={"leadsto": 1}, out_degree={"leadsto": 2},
        ),
        "db_user": StructuralFacts(
            roles=["causal_terminal"], betweenness_centrality=0.05,
            in_degree={"leadsto": 2},
        ),
    }
    hits = get_structural_profile(idx, "centrality", top_n=2, conn=deps_conn)
    assert [h["id"] for h in hits] == ["svc_gateway", "svc_auth"]
    assert hits[0]["role"] == "betweenness"
    assert hits[0]["score"] == pytest.approx(0.75)


def test_get_structural_profile_role_filter(deps_conn):
    idx = {
        "svc_gateway": StructuralFacts(
            roles=["inter_region_bridge"], betweenness_centrality=0.75,
        ),
        "svc_auth": StructuralFacts(
            roles=["causal_nexus"], betweenness_centrality=0.50,
        ),
    }
    hits = get_structural_profile(idx, "bridge", top_n=5, conn=deps_conn)
    assert [h["id"] for h in hits] == ["svc_gateway"]


def test_get_anchor_previews_returns_preview(deps_conn):
    """v7: get_anchor_previews batch-fetches anchor + text preview."""
    out = get_anchor_previews(deps_conn, ["svc_gateway", "db_user"], preview_tokens=50)
    assert len(out) == 2
    for entry in out:
        assert entry["id"] in {"svc_gateway", "db_user"}
        assert "semantic_anchor" in entry
        assert "text_preview" in entry


def test_get_anchor_previews_missing_ids_skipped(deps_conn):
    out = get_anchor_previews(deps_conn, ["svc_gateway", "nonexistent_id"])
    ids = [entry["id"] for entry in out]
    assert "svc_gateway" in ids
    assert "nonexistent_id" not in ids


@patch("tools.get_embeddings_model")
def test_vector_search_mocked(mock_get, deps_conn):
    """vector_search uses embeddings API — mock embedder for deterministic ranking."""
    emb_gateway = [0.0] * 3072
    emb_gateway[0] = 1.0
    mock = MagicMock()
    mock.embed_query.return_value = list(emb_gateway)
    mock_get.return_value = mock

    hits = vector_search(deps_conn, "checkout timeout gateway", k=3)
    assert hits
    assert hits[0]["id"] == "svc_gateway"


def test_exact_lookup_matches_trailing_parenthetical():
    """SSDF-style labels put the identifier in parentheses at the end."""

    def execute(_query, params=None):
        params = params or {}
        if params.get("suffix") == " (po.1)":
            return [("practice_po_1", "Define Security Requirements (PO.1)", 0.2)]
        return []

    conn = MagicMock()
    conn.execute.side_effect = execute
    hit = exact_node_lookup(conn, "PO.1")
    assert hit is not None
    assert hit["id"] == "practice_po_1"
