from __future__ import annotations

import pytest

from mcp_server.graph_contract import parse_graph_contract
from mcp_server.traversal_compiler import (
    TraversalCompileError,
    compile_named_traversal,
)
from tests.workbook_graph_fixture import PERSONAL_RECIPE_CONTRACT


def test_prepare_topic_edit_lowers_to_retrieval_v1():
    document = parse_graph_contract(PERSONAL_RECIPE_CONTRACT)

    compiled = compile_named_traversal(
        document,
        "prepare_topic_edit",
        {"topic_id": "topic:named-traversal"},
        version=1,
    )

    assert compiled.name == "prepare_topic_edit"
    assert compiled.version == 1
    assert compiled.fingerprint.startswith("trv_")
    assert compiled.format_fingerprint == document.fingerprint
    assert compiled.program.author == "contract_lowering"
    assert [step.tool for step in compiled.program.steps] == [
        "exact_node_lookup",
        "get_neighbourhood",
        "get_neighbourhood",
    ]
    assert compiled.program.steps[0].params == {
        "label_or_id": ["topic:named-traversal"]
    }
    assert compiled.program.steps[1].params["strategy"] == "bfs"
    assert compiled.program.steps[1].params["node_ids"] == "$seed"
    assert compiled.program.steps[1].params["edge_types"] == ["nearto"]
    assert compiled.program.steps[1].params["depth"] == 2
    assert compiled.program.steps[2].params["node_ids"] == "$region"
    assert compiled.program.steps[2].params["edge_types"] == [
        "expresses",
        "leadsto",
        "nearto",
    ]
    assert compiled.program.steps[2].params["edge_labels"] == [
        "asserts",
        "cites",
        "contradicts",
        "supports",
    ]
    assert compiled.program.collect == "$seed + $region + $evidence"
    assert compiled.program.limits.max_steps == 8
    assert compiled.program.limits.max_hops_per_step == 3
    assert compiled.program.limits.max_nodes_per_step == 50
    assert compiled.program.limits.max_recovery_rounds == 0

    from mcp_server.traversal_compiler import explain_compiled_traversal

    plan = explain_compiled_traversal(compiled)
    assert plan["estimated"]["step_count"] == 3
    assert plan["steps"][0]["tool"] == "exact_node_lookup"
    assert plan["steps"][1]["sst_types"] == ["nearto"]
    assert "asserts" in plan["steps"][2]["predicates"]


def test_explicit_condition_lowers_to_receipt_visible_contingency():
    text = PERSONAL_RECIPE_CONTRACT.replace(
        '    collect: "$seed + $region + $evidence"',
        '''    when: "$seed.count == 0"
    then:
      - op: search
        query: $topic_id
        limit: 5
        assign: seed
    then_collect: "$seed"
    collect: "$seed + $region + $evidence"''',
    )
    document = parse_graph_contract(text)

    compiled = compile_named_traversal(
        document, "prepare_topic_edit", {"topic_id": "topic:missing"}
    )

    contingency = compiled.program.contingency
    assert contingency.trigger == "$seed.count == 0"
    assert contingency.fallback_steps[0].tool == "lexical_search"
    assert contingency.fallback_steps[0].assign_to == "seed"
    assert contingency.fallback_collect == "$seed"


@pytest.mark.parametrize(
    ("name", "parameters", "version", "message"),
    [
        ("missing", {}, None, "unknown named traversal"),
        ("prepare_topic_edit", {}, None, "missing required"),
        (
            "prepare_topic_edit",
            {"topic_id": "paper:not-allowed"},
            None,
            "allowed kind",
        ),
        (
            "prepare_topic_edit",
            {"topic_id": "topic:x", "extra": "x"},
            None,
            "unknown traversal parameter",
        ),
        ("prepare_topic_edit", {"topic_id": "topic:x"}, 2, "not requested version"),
    ],
)
def test_invalid_traversal_invocations_are_refused(
    name, parameters, version, message
):
    document = parse_graph_contract(PERSONAL_RECIPE_CONTRACT)
    with pytest.raises(TraversalCompileError, match=message):
        compile_named_traversal(
            document, name, parameters, version=version
        )


def test_mcp_surface_lists_run_traversal_tool():
    pytest.importorskip("mcp")
    from mcp_server.stdio import TOOLS

    assert "run_traversal" in {tool.name for tool in TOOLS}


def _starter_with(extra_traversals: str, *, pinned: str | None = None):
    text = PERSONAL_RECIPE_CONTRACT
    if pinned is not None:
        text = text.replace("  pinned_nodes: []", f"  pinned_nodes: {pinned}", 1)
    text = text.replace("\n---\n", extra_traversals + "\n---\n", 1)
    return parse_graph_contract(text)


def test_new_recipe_ops_lower_to_retrieval_tools():
    document = _starter_with(
        """
  gather_claims:
    version: 1
    parameters:
      topic_id:
        type: node_id
        kinds: [topic]
    steps:
      - op: lookup
        references: [$topic_id]
        assign: seed
      - op: select_landmarks
        limit: 4
        assign: landmarks
      - op: expand
        from: $seed
        strategy: dfs
        predicates: [about]
        kinds: [claim]
        direction: both
        depth: 1
        assign: claims
      - op: walk_sequence
        from: $seed
        predicates: [about]
        direction: incoming
        assign: walk
      - op: filter
        of: $claims
        kinds: [claim]
        assign: filtered
      - op: sort
        of: $filtered
        by: id
        order: asc
        assign: ordered
      - op: limit
        of: $ordered
        limit: 2
        assign: top
      - op: union
        of: [$seed, $top]
        assign: combined
      - op: difference
        of: $combined
        minus: $seed
        assign: only_top
      - op: intersection
        of: $filtered
        with: $top
        assign: overlap
      - op: project
        from: $overlap
        assign: shown
    collect: "$shown"
    project:
      nodes: ids
      edges: none
      paths: none
      content: none
    limits:
      max_steps: 12
      max_hops: 4
      max_nodes: 50
"""
    )
    compiled = compile_named_traversal(
        document, "gather_claims", {"topic_id": "topic:named-traversal"}
    )
    tools = [step.tool for step in compiled.program.steps]
    assert tools == [
        "exact_node_lookup",
        "select_landmarks",
        "get_neighbourhood",
        "walk_sequence",
        "filter_nodes",
        "sort_nodes",
        "limit_nodes",
        "set_algebra",
        "set_algebra",
        "set_algebra",
        "filter_nodes",
    ]
    neighbourhood = compiled.program.steps[2].params
    assert neighbourhood["strategy"] == "dfs"
    assert neighbourhood["kinds"] == ["claim"]
    assert "claim:" in neighbourhood["kind_prefixes"]
    assert compiled.program.steps[3].params["hops"][0]["edge_labels"] == ["about"]
    assert compiled.program.steps[7].params["op"] == "union"
    assert compiled.program.steps[8].params["op"] == "difference"
    assert compiled.program.steps[9].params["op"] == "intersection"
    assert compiled.project == {
        "nodes": "ids",
        "edges": "none",
        "paths": "none",
        "content": "none",
    }


def test_unknown_dfs_strategy_is_still_refused():
    document = _starter_with(
        """
  bad_walk:
    version: 1
    parameters:
      topic_id:
        type: node_id
        kinds: [topic]
    steps:
      - op: lookup
        references: [$topic_id]
        assign: seed
      - op: traverse
        from: $seed
        strategy: random
        assign: walk
    collect: "$walk"
"""
    )
    with pytest.raises(TraversalCompileError, match="unsupported"):
        compile_named_traversal(
            document, "bad_walk", {"topic_id": "topic:x"}
        )
