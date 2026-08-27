"""An operator may serve a graph without the tools underneath the vocabulary.

Written for an experiment and kept because the experiment is the use case: a
brief that *asks* an agent not to use `read_cypher` measures instruction
following, not what the graph.md vocabulary can do. Withholding the tool turns
a request into a fact.

Hidden rather than stubbed: a tool that is listed and then refuses reads as a
broken server. A call that arrives anyway is answered with an explicit
`TOOL_WITHHELD` and logged, because whether an agent goes looking for the
escape hatch is exactly the thing worth recording.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from mcp_server.surface import Surface
from tests.workbook_graph_fixture import narrative_fixture


@pytest.fixture()
def surface(tmp_path):
    db_path, contract_path = narrative_fixture(tmp_path / "narrative.lbug")
    surface = Surface(db_path, graph_contract_path=contract_path)
    try:
        yield surface
    finally:
        surface.close()


def _request(name: str, arguments: dict | None = None):
    import mcp.types as types

    return types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments or {}),
    )


def _served(server) -> set[str]:
    import mcp.types as types

    handler = server.request_handlers[types.ListToolsRequest]
    result = asyncio.run(handler(types.ListToolsRequest(method="tools/list")))
    return {tool.name for tool in result.root.tools}


def _call(server, name: str, arguments: dict | None = None) -> dict:
    handler = server.request_handlers[type(_request("orient"))]
    result = asyncio.run(handler(_request(name, arguments)))
    return json.loads(result.root.content[0].text)


def test_read_cypher_is_withheld_by_default(surface, monkeypatch):
    """Two probe runs on one graph decided this.

    Served, a strong model used `read_cypher` for twenty of twenty-nine calls,
    authored one traversal program and scored six of seven. Withheld, the same
    model authored twenty programs and scored seven of seven -- it asked for
    the raw tool once and never again. The preference is understandable and it
    is not a need.
    """
    monkeypatch.delenv("SST_MCP_HIDE_TOOLS", raising=False)
    monkeypatch.delenv("SST_MCP_RAW_QUERY", raising=False)
    from mcp_server.stdio import build_server

    served = _served(build_server(surface))
    assert "read_cypher" not in served
    # `retrieve` stays. It speaks retrieval-v1 rather than graph.md, so it is
    # the same kind of shortcut -- but it is bounded and receipted, and no
    # probe reached for it. Withholding it would be a guess.
    assert {"retrieve", "run_ephemeral_traversal"} <= served


def test_an_operator_can_ask_for_the_raw_query_tool(surface, monkeypatch):
    """Withheld by default is a posture, not a removal."""
    monkeypatch.delenv("SST_MCP_HIDE_TOOLS", raising=False)
    monkeypatch.setenv("SST_MCP_RAW_QUERY", "1")
    from mcp_server.stdio import build_server

    assert "read_cypher" in _served(build_server(surface))


def test_nothing_else_is_withheld_by_default(surface, monkeypatch):
    """The control. Without it, the tests below could pass on a broken list."""
    monkeypatch.delenv("SST_MCP_HIDE_TOOLS", raising=False)
    from mcp_server.stdio import build_server

    served = _served(build_server(surface))
    assert {"contract", "lookup", "expand", "path", "search", "orient",
            "run_traversal", "run_ephemeral_traversal", "retrieve"} <= served


def test_withheld_tools_are_absent_from_the_listing(surface, monkeypatch):
    monkeypatch.setenv("SST_MCP_HIDE_TOOLS", "read_cypher,retrieve")
    from mcp_server.stdio import build_server

    served = _served(build_server(surface))
    assert "read_cypher" not in served
    assert "retrieve" not in served
    # The vocabulary itself is untouched, or the arm would test nothing.
    assert {"run_traversal", "run_ephemeral_traversal", "contract"} <= served


def test_calling_a_withheld_tool_says_so_rather_than_failing_unknown(
    surface, monkeypatch
):
    monkeypatch.delenv("SST_MCP_RAW_QUERY", raising=False)
    monkeypatch.setenv("SST_MCP_HIDE_TOOLS", "read_cypher")
    from mcp_server.stdio import build_server

    payload = _call(build_server(surface), "read_cypher",
                    {"query": "MATCH (n:Concept) RETURN n.id"})
    assert payload["outcome"] == "TOOL_WITHHELD"
    assert "read_cypher" in payload["error"]


def test_withholding_one_tool_leaves_the_others_working(surface, monkeypatch):
    monkeypatch.setenv("SST_MCP_HIDE_TOOLS", "read_cypher,retrieve")
    from mcp_server.stdio import build_server

    server = build_server(surface)
    payload = _call(server, "run_traversal", {
        "name": "who_was_at_both_places",
        "parameters": {"left_id": "place:the-landing",
                       "right_id": "place:the-terrace"},
        "evidence": "packet"})
    assert payload["outcome"] == "FOUND"
    assert payload["answer_node_ids"] == ["character:ilma"]


def test_an_empty_setting_withholds_nothing_extra(surface, monkeypatch):
    """Blank and unset must mean the same thing, not "hide a tool called ''"."""
    monkeypatch.setenv("SST_MCP_HIDE_TOOLS", "  ")
    from mcp_server.stdio import build_server

    assert "retrieve" in _served(build_server(surface))


# --- the vocabulary the contract now serves ----------------------------

def test_the_contract_serves_the_ops_and_their_argument_keys(surface):
    """Arm B guessed `difference` took `with`; it takes `minus`.

    That cost one round out of six, and the contract could have said so. It is
    derived from the table the compiler enforces rather than written into each
    format's prose: a graph.md is per-format and this vocabulary is not, so a
    copy in every format is a copy that rots.
    """
    from mcp_server.graph_contract import _RECIPE_OP_KEYS

    payload = surface.contract(include_markdown=False)
    vocabulary = payload["traversal_vocabulary"]

    assert set(vocabulary["ops"]) == set(_RECIPE_OP_KEYS)
    assert "minus" in vocabulary["ops"]["difference"]
    assert "with" in vocabulary["ops"]["intersection"]
    assert vocabulary["ops"]["lookup"] == ["references"]


def test_the_contract_says_what_the_vocabulary_cannot_do(surface):
    """Five calls went into discovering the first of these by exhausting guesses."""
    payload = surface.contract(include_markdown=False)
    cannot = " ".join(payload["traversal_vocabulary"]["cannot"]).lower()

    assert "whole graph" in cannot
    assert "sort" in cannot
