"""The escape hatch, and the proof that it is only an escape hatch.

The typed verbs are deliberately narrow. Narrow is defensible only if what they
exclude is still reachable: an abstraction nobody can step outside of does not
constrain an agent, it removes capability from the graph and calls the loss a
design. `read_cypher` is that step outside.

The whole question is whether it can be a write. It is not answered by
inspecting the string — every string-matching read-only gate in the wild has
been walked around — but by the engine: the statement runs inside
`BEGIN TRANSACTION READ ONLY`, and LadybugDB refuses the write itself.
"""

from __future__ import annotations

import pytest

from mcp_server.surface import Surface
from tests.workbook_graph_fixture import personal_fixture


@pytest.fixture()
def surface(tmp_path):
    db_path, contract_path = personal_fixture(tmp_path / "personal_research.lbug")
    out = Surface(db_path, graph_contract_path=contract_path)
    try:
        yield out
    finally:
        out.close()


def test_a_read_returns_rows_and_a_graph_bound_receipt(surface):
    out = surface.read_cypher(
        "MATCH (c:Concept) WHERE c.kind = 'topic' RETURN c.id, c.label ORDER BY c.id"
    )

    assert out["outcome"] == "FOUND"
    assert out["columns"] == ["c.id", "c.label"]
    assert any(row[0] == "topic:named-traversal" for row in out["rows"])
    receipt = out["execution_receipt"]
    assert receipt["graph_version"] == out["graph_version"]
    assert receipt["read_only"] is True
    assert receipt["query_fingerprint"].startswith("cyp_")
    assert receipt["row_count"] == len(out["rows"])


def test_a_write_is_refused_by_the_engine_and_changes_nothing(surface):
    """The load-bearing test. Not "the string looked like a read"."""
    before = surface.read_cypher("MATCH (c:Concept) RETURN count(*)")["rows"][0][0]

    refused = surface.read_cypher(
        "CREATE (c:Concept {id: 'claim:written-by-cypher', label: 'x'})"
    )

    assert refused["kind"] == "CYPHER_FAILED"
    assert "read-only" in " ".join(refused["errors"]).lower()
    after = surface.read_cypher("MATCH (c:Concept) RETURN count(*)")["rows"][0][0]
    assert after == before
    # And the refusal did not leave the shared connection inside a transaction:
    # the next read still works, which is the failure this would otherwise hide.
    assert surface.read_cypher("MATCH (c:Concept) RETURN count(*)")["outcome"] == "FOUND"


def test_a_delete_is_refused_too(surface):
    """DELETE takes a different engine path than CREATE."""
    refused = surface.read_cypher("MATCH (c:Concept) DETACH DELETE c")

    assert refused["kind"] == "CYPHER_FAILED"
    assert surface.read_cypher("MATCH (c:Concept) RETURN count(*)")["rows"][0][0] > 0


def test_a_second_statement_cannot_ride_along(surface):
    """The wrapper is a transaction; a smuggled second statement would run
    outside the shape this verb reasoned about."""
    out = surface.read_cypher(
        "MATCH (c:Concept) RETURN c.id; CREATE (c:Concept {id: 'x'})"
    )

    assert out["kind"] == "INVALID_CYPHER"
    assert surface.read_cypher(
        "MATCH (c:Concept) WHERE c.id = 'x' RETURN c.id"
    )["outcome"] == "EMPTY"


def test_caller_transaction_control_is_refused(surface):
    for statement in ("BEGIN TRANSACTION", "COMMIT", "ROLLBACK"):
        out = surface.read_cypher(statement)
        assert out["kind"] == "INVALID_CYPHER", statement


def test_row_and_character_bounds_truncate_visibly(surface):
    capped = surface.read_cypher(
        "MATCH (c:Concept) RETURN c.id ORDER BY c.id", max_rows=2
    )

    assert len(capped["rows"]) == 2
    assert capped["execution_receipt"]["truncated"] is True
    # A truncated result is never dressed up as a complete one.
    assert capped["outcome"] == "FOUND"

    full = surface.read_cypher("MATCH (c:Concept) RETURN c.id ORDER BY c.id")
    assert full["execution_receipt"]["truncated"] is False
    assert len(full["rows"]) > 2


def test_embeddings_never_ride_out_in_a_returned_node(surface):
    """`RETURN c` is the obvious first query an agent writes. A 3072-float
    vector per row would exhaust any context window it was pasted into."""
    out = surface.read_cypher("MATCH (c:Concept) RETURN c LIMIT 1")

    node = out["rows"][0][0]
    assert isinstance(node, dict)
    assert "embedding" not in node
    assert "_id" not in node
    assert node["id"]


def test_an_empty_result_is_not_proof_of_absence(surface):
    out = surface.read_cypher(
        "MATCH (c:Concept) WHERE c.id = 'topic:not-in-this-graph' RETURN c.id"
    )

    assert out["outcome"] == "EMPTY"
    assert out["rows"] == []


def test_a_syntax_error_comes_back_as_a_message_not_a_crash(surface):
    out = surface.read_cypher("MATCH (c:Concept RETURN c.id")

    assert out["kind"] == "CYPHER_FAILED"
    assert out["errors"]
    assert surface.read_cypher("MATCH (c:Concept) RETURN count(*)")["outcome"] == "FOUND"


def test_a_stale_graph_version_precondition_is_refused(surface):
    out = surface.read_cypher(
        "MATCH (c:Concept) RETURN count(*)", graph_version="gv_not_this_graph"
    )

    assert out["kind"] == "STALE_GRAPH"


def test_the_verb_is_on_the_agent_surface():
    from mcp_server.stdio import TOOLS

    tool = next(t for t in TOOLS if t.name == "read_cypher")
    assert tool.inputSchema["required"] == ["query"]
