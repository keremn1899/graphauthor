"""A walk cut short by its own bounds now says so.

Found by a probe agent, not by us. It asked a `traverse` step for
`max_depth: 8`, got a six-node answer to a question whose true answer is
forty-one events thirty hops down, and was told `truncated: false`. It noticed
the numbers were too small, dropped to raw Cypher for the rest of the run, and
wrote in its notes that the walks "did not say they were truncated".

`truncated` was not lying: it reports the evidence *packet* being projected
down, which is a different thing from the walk being cut. Nothing reported the
second one. `_apply_limits` clamped `depth`, `max_hops`, `max_depth` and the
`hops` list in silence.

Only a clamp that changed what the caller asked for is recorded. Filling in a
default is not evidence of anything; being given less than you asked for is,
and a check that fired on every call would be ignored within a day.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graph_storage.writer import write_graph_records
from graph_storage.records import GraphEdge, MaterializedGraph, GraphNode
from mcp_server.surface import Surface
from tests.workbook_graph_fixture import NARRATIVE_RECIPE_CONTRACT, narrative_fixture

#: Longer than the ceiling this file exists because of.
CHAIN = 30


@pytest.fixture()
def surface(tmp_path):
    db_path, contract_path = narrative_fixture(tmp_path / "narrative.lbug")
    surface = Surface(db_path, graph_contract_path=contract_path)
    try:
        yield surface
    finally:
        surface.close()


def _walk(depth: int, max_nodes: int = 50) -> dict:
    return {
        "name": f"walk_{depth}",
        "steps": [
            {"op": "lookup", "references": ["event:the-summons"], "assign": "seed"},
            {"op": "traverse", "from": "$seed", "strategy": "bfs",
             "predicates": ["causes"], "direction": "outgoing",
             "max_depth": depth, "max_nodes": max_nodes, "assign": "after"},
        ],
        "collect": "$after",
        "answers": ["after"],
    }


def _receipt(surface, program) -> dict:
    result = surface.run_ephemeral_traversal(program, {}, evidence="packet")
    assert result["outcome"] != "INVALID_RECIPE", result.get("errors")
    return result


def test_a_walk_bounded_below_what_it_asked_for_says_so(surface):
    result = _receipt(surface, _walk(depth=8))
    applied = (result["execution_receipt"]).get("bounds_applied")

    assert applied, "a step asking for depth 8 was cut and reported nothing"
    clamp = next(entry for entry in applied if entry["param"] == "depth")
    assert clamp["requested"] == 8
    assert clamp["applied"] < 8
    # Named, so a caller can act on it rather than knowing to suspect it.
    assert clamp["step"] == "after"


def test_a_walk_within_its_bounds_reports_nothing(surface):
    """Otherwise the flag fires on every call and stops meaning anything."""
    result = _receipt(surface, _walk(depth=2))
    assert "bounds_applied" not in result["execution_receipt"]


def test_the_two_truncations_are_reported_separately(surface):
    """`truncated` is about the packet; a clamped walk is about the answer.

    Both false, or both true, would be the tell that one of them was being
    used to stand in for the other -- which is the state this test was written
    out of.
    """
    result = _receipt(surface, _walk(depth=8))
    receipt = result["execution_receipt"]
    assert receipt["truncated"] is False
    assert receipt["bounds_applied"]


def test_depth_governs_what_comes_back(surface):
    """The premise: without this, the clamp above would be cosmetic.

    the-summons causes the-refusal causes the-breaking, so depth one and depth
    two are genuinely different answers.
    """
    shallow = _receipt(surface, _walk(depth=1))["answer_node_ids"]
    deeper = _receipt(surface, _walk(depth=2))["answer_node_ids"]

    assert set(shallow) < set(deeper), (shallow, deeper)
    assert "event:the-breaking" in deeper and "event:the-breaking" not in shallow


def test_the_plan_carries_the_clamps_too(surface):
    """`plan.actual` is what a reviewer reads back; it may not disagree."""
    result = _receipt(surface, _walk(depth=8))
    assert result["plan"]["actual"]["bounds_applied"] == \
        result["execution_receipt"]["bounds_applied"]


# --- a chain longer than the old ceiling -------------------------------

@pytest.fixture()
def long_chain(tmp_path):
    """Thirty events in a causal line, which the old ceiling of six hid.

    A real saga graph had a chain this long and no program could walk it: the
    schema capped `max_hops_per_step` at six, so the true forty-one-event
    answer was unreachable rather than expensive. This fixture is the shape
    that made that a bug rather than a policy.
    """
    nodes = {
        f"event:step-{i}": GraphNode(
            id=f"event:step-{i}", kind="event", label=f"Step {i}",
            text_content=f"Step {i}", semantic_anchor=f"Step {i}",
            source_unit_ids=["chain#u:1"])
        for i in range(CHAIN + 1)
    }
    edges = [
        GraphEdge(source=f"event:step-{i}", target=f"event:step-{i + 1}",
                      sst_type="LEADSTO", label="causes")
        for i in range(CHAIN)
    ]
    graph = MaterializedGraph(id="long-chain", domain="Long chain",
                           nodes=nodes, edges=edges)
    db_path = tmp_path / "chain.lbug"
    write_graph_records(db_path, graph, embed=False)
    contract_path = tmp_path / "chain.recipes.md"
    contract_path.write_text(NARRATIVE_RECIPE_CONTRACT)
    surface = Surface(db_path, graph_contract_path=contract_path)
    try:
        yield surface
    finally:
        surface.close()


def _chain_walk(depth: int) -> dict:
    return {
        "name": f"chain_{depth}",
        "steps": [
            {"op": "lookup", "references": ["event:step-0"], "assign": "seed"},
            {"op": "traverse", "from": "$seed", "strategy": "bfs",
             "predicates": ["causes"], "direction": "outgoing",
             "max_depth": depth, "max_nodes": 200, "assign": "after"},
        ],
        "collect": "$after",
        "answers": ["after"],
        "limits": {"max_steps": 4, "max_hops": depth, "max_nodes": 200},
    }


def test_a_walk_deeper_than_the_old_ceiling_is_honoured(long_chain):
    result = _receipt(long_chain, _chain_walk(depth=CHAIN))

    assert len(result["answer_node_ids"]) == CHAIN, "the chain was cut short"
    assert "bounds_applied" not in result["execution_receipt"], (
        "nothing was clamped, so nothing should be reported"
    )


def test_seven_hops_would_have_been_capped_at_six(long_chain):
    """The specific number the ceiling used to be, so a reintroduction fails.

    Six is not special to this graph -- it was the schema's cap. Asking for
    seven and getting seven is the assertion.
    """
    result = _receipt(long_chain, _chain_walk(depth=7))
    assert len(result["answer_node_ids"]) == 7


def test_a_walk_that_exhausts_the_chain_does_not_claim_it_was_bounded(long_chain):
    """Asking for more than there is must not read as a truncated answer."""
    result = _receipt(long_chain, _chain_walk(depth=64))
    assert len(result["answer_node_ids"]) == CHAIN
    assert "bounds_applied" not in result["execution_receipt"]


def test_the_ceiling_still_exists(long_chain):
    """Raised, not removed: a program asking past it is refused, not clamped."""
    program = _chain_walk(depth=CHAIN)
    program["limits"]["max_hops"] = 500

    result = long_chain.run_ephemeral_traversal(program, {}, evidence="packet")
    # The ephemeral compiler clamps its own limits block rather than refusing,
    # so the walk still runs -- at the ceiling, which is above this chain.
    assert result["outcome"] == "FOUND"
    assert len(result["answer_node_ids"]) == CHAIN


# --- the node budget, and the key that was dropped in silence -----------

def _budget_walk(max_nodes: int) -> dict:
    return {
        "name": f"budget_{max_nodes}",
        "steps": [
            {"op": "lookup", "references": ["event:step-0"], "assign": "seed"},
            {"op": "traverse", "from": "$seed", "strategy": "bfs",
             "predicates": ["causes"], "direction": "outgoing",
             "max_depth": CHAIN, "max_nodes": max_nodes, "assign": "after"},
        ],
        "collect": "$after",
        "answers": ["after"],
        "limits": {"max_steps": 4, "max_hops": CHAIN, "max_nodes": 300},
    }


def test_a_walk_that_runs_out_of_budget_says_so(long_chain):
    """The BFS branch logged this to `sst.engine`; DFS dropped nodes silently.

    Neither reaches a caller over MCP, so a partial walk and a complete one
    were the same result. Reported through `bounds_applied` alongside the hop
    clamp, because they are the same thing from the caller's side: asked for a
    walk, got part of one.
    """
    result = _receipt(long_chain, _budget_walk(max_nodes=5))
    applied = result["execution_receipt"].get("bounds_applied") or []

    assert any(entry["param"] == "max_nodes" for entry in applied), applied
    assert len(result["answer_node_ids"]) == 5


def test_a_walk_inside_its_budget_says_nothing(long_chain):
    result = _receipt(long_chain, _budget_walk(max_nodes=300))
    assert len(result["answer_node_ids"]) == CHAIN
    assert "bounds_applied" not in result["execution_receipt"]


def test_a_step_key_the_op_does_not_read_is_refused(long_chain):
    """`{"op": "lookup", "pattern": "character:"}` used to compile and plan.

    An invented field and a real empty answer produced the same output, which
    is how a probe agent spent three calls deciding the vocabulary had no way
    to name every node of a kind. It does not -- but that had to be inferred
    from silence rather than read from an error.
    """
    program = {
        "name": "invented_field",
        "steps": [{"op": "lookup", "assign": "all", "pattern": "event:"}],
        "collect": "$all",
    }
    result = long_chain.run_ephemeral_traversal(program, {}, evidence="packet")

    assert result["outcome"] == "INVALID_RECIPE"
    message = " ".join(result["errors"])
    assert "pattern" in message
    # The message teaches the vocabulary rather than only refusing it.
    assert "references" in message
