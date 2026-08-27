"""Deterministic, queryable regional Compass over an exact graph snapshot.

The regional Compass is a navigation index.  It deliberately carries no node
prose, semantic summary, authority role, or conformance judgment.  Leiden sees
an undirected weighted projection; every card preserves the exact directed SST
edges that projection hid so a caller can drill through to graph truth.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from typing import Any


RELATIONS = (
    ("leadsto", "LEADSTO"),
    ("contains", "CONTAINS"),
    ("expresses", "EXPRESSES"),
    ("nearto", "NEARTO"),
)
ALGORITHM = "leiden-rb-configuration-v1"
DEFAULT_RESOLUTION = 1.0
DEFAULT_SEED = 0


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _extract(conn: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    nodes = sorted(
        (
            {"id": str(row[0]), "label": str(row[1] or "")}
            for row in conn.execute("MATCH (c:Concept) RETURN c.id, c.label")
        ),
        key=lambda row: row["id"],
    )
    edges: list[dict[str, str]] = []
    for edge_type, relation in RELATIONS:
        rows = conn.execute(
            f"MATCH (a:Concept)-[r:{relation}]->(b:Concept) "
            "RETURN a.id, b.id, r.label"
        )
        for source, target, label in rows:
            edges.append(
                {
                    "edge_type": edge_type,
                    "source": str(source),
                    "target": str(target),
                    "label": str(label or ""),
                }
            )
    edges.sort(
        key=lambda row: (
            row["edge_type"], row["source"], row["target"], row["label"]
        )
    )
    for ordinal, edge in enumerate(edges):
        edge["ordinal"] = ordinal
    return nodes, edges


def _partition(
    node_ids: list[str],
    edges: list[dict[str, Any]],
    *,
    resolution: float,
    seed: int,
) -> list[list[str]]:
    try:
        import igraph as ig
        import leidenalg as la
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise RuntimeError(
            "regional Compass requires the 'regional' extra: "
            "pip install -e '.[regional]'"
        ) from exc

    if not node_ids:
        return []
    position = {node_id: index for index, node_id in enumerate(node_ids)}
    pair_weights: Counter[tuple[str, str]] = Counter()
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        pair_weights[tuple(sorted((source, target)))] += 1
    ordered_pairs = sorted(pair_weights)
    graph = ig.Graph(
        n=len(node_ids),
        edges=[(position[source], position[target]) for source, target in ordered_pairs],
        directed=False,
    )
    graph.vs["name"] = node_ids
    weights = [float(pair_weights[pair]) for pair in ordered_pairs]
    partition = la.find_partition(
        graph,
        la.RBConfigurationVertexPartition,
        weights=weights or None,
        resolution_parameter=float(resolution),
        seed=int(seed),
    )
    communities = [sorted(node_ids[index] for index in community) for community in partition]
    return sorted(communities, key=lambda members: (members[0], len(members)))


def _connected(members: set[str], adjacency: dict[str, set[str]]) -> bool:
    if len(members) < 2:
        return True
    start = min(members)
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbour in adjacency.get(current, set()):
            if neighbour in members and neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen == members


def build_region_index(
    conn: Any,
    *,
    graph_version: str = "",
    resolution: float = DEFAULT_RESOLUTION,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Build the complete deterministic region index for one graph snapshot."""
    if float(resolution) <= 0:
        raise ValueError("resolution must be positive")
    nodes, edges = _extract(conn)
    node_ids = [node["id"] for node in nodes]
    labels = {node["id"]: node["label"] for node in nodes}
    topology_fingerprint = _digest(
        {
            "nodes": node_ids,
            "edges": [
                [edge["edge_type"], edge["source"], edge["target"], edge["label"]]
                for edge in edges
            ],
        }
    )
    communities = _partition(
        node_ids, edges, resolution=float(resolution), seed=int(seed)
    )

    node_region: dict[str, str] = {}
    region_members: dict[str, list[str]] = {}
    for members in communities:
        region_id = "region_" + _digest(members)[:12]
        region_members[region_id] = members
        for node_id in members:
            node_region[node_id] = region_id

    adjacency: dict[str, set[str]] = defaultdict(set)
    degree: Counter[str] = Counter()
    for edge in edges:
        source, target = edge["source"], edge["target"]
        adjacency[source].add(target)
        adjacency[target].add(source)
        degree[source] += 1
        degree[target] += 1

    internal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    crossing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    neighbours: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in edges:
        source_region = node_region[edge["source"]]
        target_region = node_region[edge["target"]]
        if source_region == target_region:
            internal[source_region].append(edge)
            continue
        crossing[source_region].append(edge)
        crossing[target_region].append(edge)
        neighbours[source_region][target_region] += 1
        neighbours[target_region][source_region] += 1

    total_volume = sum(degree.values())
    regions: list[dict[str, Any]] = []
    for region_id, members in sorted(region_members.items()):
        member_set = set(members)
        inside = internal.get(region_id, [])
        cut = crossing.get(region_id, [])
        within_degree: Counter[str] = Counter()
        boundary_degree: Counter[str] = Counter()
        unique_internal_pairs: set[tuple[str, str]] = set()
        for edge in inside:
            source, target = edge["source"], edge["target"]
            within_degree[source] += 1
            within_degree[target] += 1
            unique_internal_pairs.add(tuple(sorted((source, target))))
        for edge in cut:
            if edge["source"] in member_set:
                boundary_degree[edge["source"]] += 1
            if edge["target"] in member_set:
                boundary_degree[edge["target"]] += 1
        volume = sum(degree[node_id] for node_id in members)
        denominator = min(volume, total_volume - volume)
        possible_pairs = len(members) * (len(members) - 1) / 2
        landmarks = sorted(
            members,
            key=lambda node_id: (
                -within_degree[node_id], -boundary_degree[node_id], node_id
            ),
        )[:5]
        regions.append(
            {
                "region_id": region_id,
                "size": len(members),
                "member_ids": members,
                "connected": _connected(member_set, adjacency),
                "internal_edge_count": len(inside),
                "cut_edge_count": len(cut),
                "density": (
                    round(len(unique_internal_pairs) / possible_pairs, 6)
                    if possible_pairs else 0.0
                ),
                "conductance": (
                    round(len(cut) / denominator, 6) if denominator else 0.0
                ),
                "landmarks": [
                    {
                        "id": node_id,
                        "label": labels[node_id],
                        "within_degree": within_degree[node_id],
                        "boundary_degree": boundary_degree[node_id],
                    }
                    for node_id in landmarks
                ],
                "internal_edge_types": dict(
                    sorted(Counter(edge["edge_type"] for edge in inside).items())
                ),
                "internal_edge_labels": dict(
                    sorted(Counter(edge["label"] or "(unlabeled)" for edge in inside).items())
                ),
                "boundary_nodes": [
                    {
                        "id": node_id,
                        "label": labels[node_id],
                        "crossing_edge_count": count,
                    }
                    for node_id, count in sorted(
                        boundary_degree.items(), key=lambda item: (-item[1], item[0])
                    )
                ],
                "neighbour_regions": [
                    {"region_id": neighbour_id, "crossing_edge_count": count}
                    for neighbour_id, count in sorted(neighbours[region_id].items())
                ],
                "boundary_edges": sorted(
                    cut,
                    key=lambda edge: (
                        edge["edge_type"], edge["source"], edge["target"],
                        edge["label"], edge["ordinal"],
                    ),
                ),
            }
        )

    result = {
        "schema": "regional-compass-index-v1",
        "execution": "deterministic_zero_llm",
        "graph_version": str(graph_version or ""),
        "topology_fingerprint": topology_fingerprint,
        "algorithm": {
            "name": ALGORITHM,
            "resolution": float(resolution),
            "seed": int(seed),
            "partition_projection": "undirected_weighted_edge_multiplicity",
            "projection_loss": (
                "direction, SST type, and edge label do not affect the V1 partition; "
                "exact directed typed edges remain present in region cards"
            ),
        },
        "node_count": len(nodes),
        "edge_count": len(edges),
        "region_count": len(regions),
        "node_region": dict(sorted(node_region.items())),
        "regions": sorted(regions, key=lambda row: row["region_id"]),
    }
    result["index_sha256"] = _digest(result)
    return result


def compact_region_map(index: dict[str, Any]) -> dict[str, Any]:
    """Return a small graph-wide directory; exact members stay on region fetch."""
    return {
        "schema": "regional-compass-map-v1",
        "execution": index["execution"],
        "graph_version": index["graph_version"],
        "topology_fingerprint": index["topology_fingerprint"],
        "index_sha256": index["index_sha256"],
        "algorithm": index["algorithm"],
        "node_count": index["node_count"],
        "edge_count": index["edge_count"],
        "region_count": index["region_count"],
        "regions": [
            {
                key: region[key]
                for key in (
                    "region_id", "size", "internal_edge_count", "cut_edge_count",
                    "density", "conductance", "landmarks", "internal_edge_types",
                    "neighbour_regions",
                )
            }
            for region in index["regions"]
        ],
    }


def region_card(
    index: dict[str, Any],
    region_id: str,
    *,
    member_offset: int = 0,
    member_limit: int = 100,
    boundary_offset: int = 0,
    boundary_limit: int = 100,
) -> dict[str, Any]:
    """Page exact region membership and frontier edges with honest completion."""
    if member_offset < 0 or boundary_offset < 0:
        raise ValueError("offsets must be non-negative")
    if not 1 <= member_limit <= 500 or not 1 <= boundary_limit <= 500:
        raise ValueError("limits must be between 1 and 500")
    region = next(
        (row for row in index["regions"] if row["region_id"] == region_id), None
    )
    if region is None:
        return {
            "schema": "regional-compass-card-v1",
            "outcome": "UNKNOWN_REGION",
            "region_id": region_id,
            "graph_version": index["graph_version"],
            "index_sha256": index["index_sha256"],
        }
    members = region["member_ids"]
    boundaries = region["boundary_edges"]
    member_page = members[member_offset:member_offset + member_limit]
    boundary_page = boundaries[boundary_offset:boundary_offset + boundary_limit]
    return {
        "schema": "regional-compass-card-v1",
        "outcome": "FOUND",
        "graph_version": index["graph_version"],
        "topology_fingerprint": index["topology_fingerprint"],
        "index_sha256": index["index_sha256"],
        "algorithm": index["algorithm"],
        **{
            key: value for key, value in region.items()
            if key not in {"member_ids", "boundary_edges"}
        },
        "member_ids": member_page,
        "boundary_edges": boundary_page,
        "membership_page": {
            "offset": member_offset,
            "returned": len(member_page),
            "total": len(members),
            "complete": member_offset + len(member_page) >= len(members),
            "next_offset": (
                None if member_offset + len(member_page) >= len(members)
                else member_offset + len(member_page)
            ),
        },
        "boundary_page": {
            "offset": boundary_offset,
            "returned": len(boundary_page),
            "total": len(boundaries),
            "complete": boundary_offset + len(boundary_page) >= len(boundaries),
            "next_offset": (
                None if boundary_offset + len(boundary_page) >= len(boundaries)
                else boundary_offset + len(boundary_page)
            ),
        },
    }


def locate_regions(index: dict[str, Any], node_ids: list[str]) -> dict[str, Any]:
    """Map exact node identities to regions without similarity or widening."""
    cleaned = list(dict.fromkeys(str(node_id).strip() for node_id in node_ids if str(node_id).strip()))
    if not cleaned:
        raise ValueError("node_ids must not be empty")
    found = {
        node_id: index["node_region"][node_id]
        for node_id in cleaned if node_id in index["node_region"]
    }
    missing = [node_id for node_id in cleaned if node_id not in found]
    return {
        "schema": "regional-compass-locate-v1",
        "outcome": "EXACT_MISS" if not found else "PARTIAL" if missing else "FOUND",
        "graph_version": index["graph_version"],
        "index_sha256": index["index_sha256"],
        "node_regions": found,
        "missing_node_ids": missing,
    }
