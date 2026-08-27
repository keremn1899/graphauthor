from __future__ import annotations

import pytest

from mcp_server.graph_contract import (
    GraphContractError,
    lower_predicates,
    node_id_matches_kind,
    parse_graph_contract,
)
from mcp_server.surface import Surface
from tests.workbook_graph_fixture import PERSONAL_RECIPE_CONTRACT


def test_starter_contract_parses_and_binds_semantics():
    document = parse_graph_contract(PERSONAL_RECIPE_CONTRACT)

    assert document.specification.format_id == "workbook-research-fixture"
    assert document.specification.format_version == 1
    assert document.specification.review_mode == "exceptions"
    assert document.specification.predicates["supports"].sst == "LEADSTO"
    assert document.specification.predicates["contradicts"].symmetric is True
    assert document.specification.orientation.default_traversal == "prepare_topic_edit"
    assert document.specification.required_traversals[0].recipe == "prepare_topic_edit"
    assert document.specification.traversals["prepare_topic_edit"].version == 1
    assert document.fingerprint.startswith("gfmt_")
    assert len(document.content_sha256) == 64

    assert node_id_matches_kind(
        "topic:named-traversal", "topic", document.specification
    )
    assert not node_id_matches_kind(
        "claim:named-traversal", "topic", document.specification
    )
    assert lower_predicates(
        ["supports", "contradicts"], document.specification
    ) == (["leadsto", "nearto"], ["contradicts", "supports"])


def test_contract_fingerprint_is_deterministic_and_binds_markdown():
    text = PERSONAL_RECIPE_CONTRACT

    first = parse_graph_contract(text)
    second = parse_graph_contract(text.replace("\r\n", "\n"))
    changed = parse_graph_contract(
        text.replace("Graph-local recipe fixture", "Changed recipe fixture")
    )

    assert first.content_sha256 == second.content_sha256
    assert first.content_sha256 != changed.content_sha256


def test_unknown_recipe_predicate_is_rejected():
    text = PERSONAL_RECIPE_CONTRACT.replace(
        "predicates: [supports, contradicts, cites, asserts]",
        "predicates: [supports, contradicts, cites, invented]",
    )

    with pytest.raises(GraphContractError, match="unknown predicates"):
        parse_graph_contract(text)


def test_symmetric_predicate_must_use_nearto():
    text = PERSONAL_RECIPE_CONTRACT.replace(
        "{sst: NEARTO, symmetric: true, source_kinds: [claim], target_kinds: [claim]}",
        "{sst: LEADSTO, symmetric: true, source_kinds: [claim], target_kinds: [claim]}",
    )

    with pytest.raises(GraphContractError, match="symmetric predicates must map to NEARTO"):
        parse_graph_contract(text)


def test_contract_requires_frontmatter_and_explanatory_markdown():
    with pytest.raises(GraphContractError, match="must begin"):
        parse_graph_contract("# No frontmatter\n")

    with pytest.raises(GraphContractError, match="requires explanatory markdown"):
        parse_graph_contract(
            """---
format_id: x
format_version: 1
node_kinds: {thing: {id_pattern: "thing:<id>"}}
predicates:
  related: {sst: NEARTO, symmetric: true}
---
"""
        )


def test_surface_contract_projection_is_typed_without_opening_a_graph(tmp_path):
    recipe_path = tmp_path / "graph.recipes.md"
    recipe_path.write_text(PERSONAL_RECIPE_CONTRACT)
    surface = Surface.__new__(Surface)
    surface._graph_contract_path = recipe_path
    surface._graph_contract_explicit = True
    surface._workbook_traversals_path = tmp_path / "missing.traversals.json"
    surface._base = lambda: {
        "contract_version": "mcp-v0",
        "graph_version": "gv_test",
        "trace_id": "trace",
    }

    compact = surface.contract(include_markdown=False)

    assert compact["kind"] == "GRAPH_CONTRACT"
    assert compact["outcome"] == "FOUND"
    assert compact["format_id"] == "workbook-research-fixture"
    assert "markdown" not in compact

    surface._graph_contract_path = tmp_path / "missing-graph.md"
    absent = surface.contract()
    assert absent["outcome"] == "ABSENT"
    assert absent["available"] is False


def test_mcp_surface_lists_contract_tool():
    pytest.importorskip("mcp")
    from mcp_server.stdio import TOOLS

    assert "contract" in {tool.name for tool in TOOLS}
