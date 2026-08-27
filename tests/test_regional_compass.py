from __future__ import annotations

import json

import pytest

pytest.importorskip("igraph")
pytest.importorskip("leidenalg")

from mcp_server.host_retrieval import HostRetrievalSurface
from mcp_server.regional_compass import (
    build_region_index,
    compact_region_map,
    locate_regions,
    region_card,
)
from mcp_server.surface import open_fixture


FIXTURE = "runtime/hexagonal_orders.lbug"


@pytest.fixture(scope="module")
def world():
    surface = open_fixture(FIXTURE)
    try:
        yield surface
    finally:
        surface.close()


def test_region_index_is_deterministic_and_conserves_graph(world):
    first = build_region_index(world._session.connection, graph_version="test")
    second = build_region_index(world._session.connection, graph_version="test")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["execution"] == "deterministic_zero_llm"
    assert first["algorithm"]["seed"] == 0
    assert "do not affect" in first["algorithm"]["projection_loss"]

    members = [
        node_id for region in first["regions"] for node_id in region["member_ids"]
    ]
    assert len(members) == first["node_count"]
    assert len(set(members)) == first["node_count"]
    assert all(region["connected"] for region in first["regions"])

    internal = sum(region["internal_edge_count"] for region in first["regions"])
    crossing_twice = sum(region["cut_edge_count"] for region in first["regions"])
    assert crossing_twice % 2 == 0
    assert internal + crossing_twice // 2 == first["edge_count"]


def test_region_boundaries_are_symmetric_and_drillable(world):
    index = build_region_index(world._session.connection, graph_version="test")
    region_by_id = {region["region_id"]: region for region in index["regions"]}
    for region in index["regions"]:
        for neighbour in region["neighbour_regions"]:
            reverse = next(
                row for row in region_by_id[neighbour["region_id"]]["neighbour_regions"]
                if row["region_id"] == region["region_id"]
            )
            assert reverse["crossing_edge_count"] == neighbour["crossing_edge_count"]
        card = region_card(index, region["region_id"], member_limit=500, boundary_limit=500)
        assert card["outcome"] == "FOUND"
        assert card["membership_page"]["complete"] is True
        assert card["boundary_page"]["complete"] is True
        for edge in card["boundary_edges"]:
            assert edge["source"] in index["node_region"]
            assert edge["target"] in index["node_region"]


def test_compact_map_omits_members_and_exact_locator_never_widens(world):
    index = build_region_index(world._session.connection, graph_version="test")
    compact = compact_region_map(index)
    assert all("member_ids" not in region for region in compact["regions"])
    located = locate_regions(index, ["ports_module", "definitely_missing"])
    assert located["outcome"] == "PARTIAL"
    assert located["node_regions"]["ports_module"].startswith("region_")
    assert located["missing_node_ids"] == ["definitely_missing"]


def test_host_surface_exposes_regional_navigation(world):
    host = HostRetrievalSurface(world)
    region_map = host.region_map()
    located = host.locate_regions(["dependency_direction_rule"])
    region_id = located["node_regions"]["dependency_direction_rule"]
    card = host.region(region_id, member_limit=2, boundary_limit=2)

    assert region_map["region_count"] >= 1
    assert located["outcome"] == "FOUND"
    assert card["outcome"] == "FOUND"
    assert card["region_id"] == region_id
    assert card["membership_page"]["returned"] <= 2
