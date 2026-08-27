"""Metanode crossing — verdict neutrality unit tests (keystone)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def split(tmp_path):
    from mcp_server.crossing import CrossingGraph, split_graph_at
    from mcp_server.fixture import ensure_fixture

    m = tmp_path / "m.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), m)
    man = split_graph_at(m, "adapters_module", tmp_path / "p.lbug", tmp_path / "c.lbug",
                         door_id="d", child_graph_id="cc")
    g = CrossingGraph(tmp_path / "p.lbug", {"cc": tmp_path / "c.lbug"})
    g.set_bridges(man["cross_edges"], "d", "cc")
    return m, g, man


def test_partition_is_lossless_and_door_is_additive(split):
    m, g, man = split
    assert (man["parent_count"] - 1) + man["moved_count"] == man["merged_count"]
    assert man["moved_count"] > 0


def test_reachability_is_verdict_neutral(split):
    from mcp_server.crossing import crossing_reachable, merged_reachable

    m, g, man = split
    for src, tgt in man["sample_pairs"]:
        assert merged_reachable(m, src, tgt) == crossing_reachable(g, src, tgt), (src, tgt)


def test_neighbourhood_is_verdict_neutral_across_the_cut(split):
    from mcp_server.crossing import crossing_neighbourhood, merged_neighbourhood

    m, g, man = split
    node = man["boundary_parent_node"]
    assert merged_neighbourhood(m, node, depth=2) == crossing_neighbourhood(g, node, depth=2)


def test_door_never_evidence_and_child_carries_via_boundary(split):
    from mcp_server.crossing import crossing_packet_records

    m, g, man = split
    recs = crossing_packet_records(g, man["boundary_parent_node"], depth=2)
    assert "d" not in {r["id"] for r in recs}
    crossed = [r for r in recs if r.get("via_boundary")]
    assert crossed and all(r["via_boundary"]["child_graph_id"] == "cc" for r in crossed)


def test_door_summary_derived_and_deterministic(split, tmp_path):
    from mcp_server.crossing import derive_door_summary

    a = derive_door_summary(tmp_path / "c.lbug")
    b = derive_door_summary(tmp_path / "c.lbug")
    assert a == b and a["landmarks"] and "authored" not in a
