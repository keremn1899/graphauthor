from __future__ import annotations

from pathlib import Path

from graph_storage.writer import write_graph_records
from graph_storage.records import GraphEdge, MaterializedGraph, GraphNode
from mcp_server.graph_contract import parse_graph_contract
from mcp_server.surface import Surface
from mcp_server.traversal_compiler import compile_named_traversal
from tests.workbook_graph_fixture import PERSONAL_RECIPE_CONTRACT, personal_fixture


ROOT = Path(__file__).resolve().parents[1]

DFS_CONTRACT = """---
format_id: traversal-ops
format_version: 1
node_kinds:
  node:
    id_pattern: "n:<slug>"
predicates:
  next:
    sst: LEADSTO
    directed: true
    source_kinds: [node]
    target_kinds: [node]
traversals:
  dfs_cap:
    version: 1
    parameters:
      seed:
        type: node_id
        kinds: [node]
    steps:
      - op: lookup
        references: [$seed]
        assign: seed
      - op: traverse
        from: $seed
        strategy: dfs
        sst_types: [LEADSTO]
        direction: outgoing
        depth: 3
        max_nodes: 2
        assign: walk
    collect: "$walk"
    limits:
      max_steps: 4
      max_hops: 3
      max_nodes: 2
  bfs_full:
    version: 1
    parameters:
      seed:
        type: node_id
        kinds: [node]
    steps:
      - op: lookup
        references: [$seed]
        assign: seed
      - op: traverse
        from: $seed
        strategy: bfs
        sst_types: [LEADSTO]
        direction: outgoing
        depth: 3
        max_nodes: 30
        assign: walk
    collect: "$walk"
    limits:
      max_steps: 4
      max_hops: 3
      max_nodes: 30
---

# DFS fixture
"""


def test_dfs_caps_branch_first_not_nearest_frontier(tmp_path):
    db_path = tmp_path / "dfs.lbug"
    write_graph_records(
        db_path,
        MaterializedGraph(
            id="dfs-fixture",
            domain="DFS vs BFS",
            nodes={
                "n:a": GraphNode(id="n:a", kind="node", label="A"),
                "n:b": GraphNode(id="n:b", kind="node", label="B"),
                "n:c": GraphNode(id="n:c", kind="node", label="C"),
                "n:d": GraphNode(id="n:d", kind="node", label="D"),
                "n:e": GraphNode(id="n:e", kind="node", label="E"),
            },
            edges=[
                GraphEdge("n:a", "n:b", "leadsto", "next"),
                GraphEdge("n:a", "n:c", "leadsto", "next"),
                GraphEdge("n:b", "n:d", "leadsto", "next"),
                GraphEdge("n:d", "n:e", "leadsto", "next"),
            ],
        ),
        embed=False,
    )
    contract_path = tmp_path / "graph.md"
    contract_path.write_text(DFS_CONTRACT, encoding="utf-8")
    surface = Surface(db_path, graph_contract_path=contract_path)
    try:
        dfs = surface.run_traversal("dfs_cap", {"seed": "n:a"})
        bfs = surface.run_traversal("bfs_full", {"seed": "n:a"})
    finally:
        surface.close()

    dfs_ids = set(dfs["why_entered"])
    bfs_ids = set(bfs["why_entered"])
    assert dfs_ids == {"n:b", "n:d"}
    assert {"n:b", "n:c", "n:d", "n:e"} <= bfs_ids
    assert "n:c" not in dfs_ids


def test_kind_filters_walk_sequence_set_ops_and_output_schema(tmp_path):
    db_path, contract_path = personal_fixture(tmp_path / "personal_research.lbug")
    extra = """
  claim_neighbourhood:
    version: 1
    parameters:
      topic_id:
        type: node_id
        kinds: [topic]
    steps:
      - op: lookup
        references: [$topic_id]
        assign: seed
      - op: expand
        from: $seed
        predicates: [about]
        kinds: [claim]
        direction: both
        depth: 1
        assign: claims
    collect: "$claims"
    limits:
      max_steps: 4
      max_hops: 2
      max_nodes: 20
  paper_path:
    version: 1
    parameters:
      paper_id:
        type: node_id
        kinds: [paper]
    steps:
      - op: lookup
        references: [$paper_id]
        assign: seed
      - op: walk_sequence
        from: $seed
        predicates: [asserts, about]
        direction: outgoing
        assign: walk
    collect: "$walk"
    limits:
      max_steps: 4
      max_hops: 2
      max_nodes: 20
  set_and_schema:
    version: 1
    parameters:
      topic_id:
        type: node_id
        kinds: [topic]
    steps:
      - op: lookup
        references: [$topic_id]
        assign: seed
      - op: expand
        from: $seed
        predicates: [about]
        direction: both
        depth: 1
        assign: around
      - op: filter
        of: $around
        kinds: [claim]
        assign: claims
      - op: sort
        of: $claims
        by: id
        order: asc
        assign: ordered
      - op: limit
        of: $ordered
        limit: 1
        assign: top
      - op: union
        of: [$seed, $top]
        assign: combined
      - op: difference
        of: $combined
        minus: $seed
        assign: only_top
    collect: "$combined"
    project:
      nodes: ids
      edges: none
      paths: none
    limits:
      max_steps: 8
      max_hops: 2
      max_nodes: 20
  landmarks:
    version: 1
    steps:
      - op: select_landmarks
        include_pinned: true
        limit: 1
        assign: pins
    collect: "$pins"
    limits:
      max_steps: 2
      max_hops: 1
      max_nodes: 8
"""
    text = PERSONAL_RECIPE_CONTRACT.replace(
        "  pinned_nodes: []",
        '  pinned_nodes: ["topic:named-traversal"]',
        1,
    ).replace("\n---\n", extra + "\n---\n", 1)
    contract_path.write_text(text, encoding="utf-8")
    document = parse_graph_contract(text)
    compiled = compile_named_traversal(
        document, "claim_neighbourhood", {"topic_id": "topic:named-traversal"}
    )
    assert compiled.program.steps[1].params["kinds"] == ["claim"]

    surface = Surface(db_path, graph_contract_path=contract_path)
    try:
        claims = surface.run_traversal(
            "claim_neighbourhood", {"topic_id": "topic:named-traversal"}
        )
        walked = surface.run_traversal(
            "paper_path", {"paper_id": "paper:graph-retrieval-survey"}
        )
        projected = surface.run_traversal(
            "set_and_schema", {"topic_id": "topic:named-traversal"}
        )
        landmarks = surface.run_traversal("landmarks")
    finally:
        surface.close()

    claim_ids = set(claims["why_entered"])
    assert "claim:edges-select-context" in claim_ids
    assert "claim:receipts-bind-observation" in claim_ids
    assert "question:review-context" not in claim_ids
    assert all(node_id.startswith("claim:") for node_id in claim_ids)

    walk_ids = set(walked["why_entered"])
    assert "claim:edges-select-context" in walk_ids
    assert "topic:named-traversal" in walk_ids

    projected_ids = {row["id"] for row in projected["evidence"]["node_records"]}
    assert "topic:named-traversal" in projected_ids
    assert len(projected["evidence"]["edge_records"]) == 0
    for row in projected["evidence"]["node_records"]:
        assert set(row) <= {"id", "entered_via"}

    only_top = next(
        op
        for op in projected["execution_receipt"]["operations"]
        if op["assign_to"] == "only_top"
    )
    assert only_top["result_count"] == 1

    assert "topic:named-traversal" in landmarks["why_entered"]
