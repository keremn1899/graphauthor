"""A one-shot traversal program, and what it deliberately cannot buy.

`run_traversal` answered "which of the procedures this format already names do
you want". Everything else had to drop to `retrieve`, which speaks retrieval-v1
directly: raw tools, no predicate vocabulary, no kind checks, no `project`.
So a walk that was not worth adding to graph.md was authored at the wrong
level, and promoting it later meant rewriting it.

An ephemeral program closes that: the same recipe ops, the same bounds, the
same receipt. What it does not carry is the one thing a name buys — a version
another session can re-run and `propose` can verify. That asymmetry is the
whole point, so it is asserted here rather than described.
"""

from __future__ import annotations

import pytest

from mcp_server.surface import Surface
from tests.workbook_graph_fixture import personal_fixture


# The declared prepare_topic_edit recipe, written out as a one-shot program.
TOPIC_CONTEXT = {
    "name": "topic_context",
    "steps": [
        {"op": "lookup", "references": ["$topic_id"], "assign": "seed"},
        {
            "op": "traverse",
            "from": "$seed",
            "strategy": "bfs",
            "sst_types": ["NEARTO"],
            "direction": "both",
            "max_depth": 2,
            "max_nodes": 30,
            "assign": "region",
        },
        {
            "op": "expand",
            "from": "$region",
            "predicates": ["supports", "contradicts", "cites", "asserts"],
            "direction": "both",
            "depth": 1,
            "max_nodes": 30,
            "assign": "evidence",
        },
    ],
    "collect": "$seed + $region + $evidence",
    "limits": {"max_steps": 8, "max_hops": 3, "max_nodes": 50},
}


@pytest.fixture()
def surface(tmp_path):
    db_path, contract_path = personal_fixture(tmp_path / "personal_research.lbug")
    out = Surface(
        db_path,
        graph_contract_path=contract_path,
        enable_history=True,
        enable_proposals=True,
    )
    try:
        yield out
    finally:
        out.close()


def test_the_same_program_named_or_not_returns_the_same_packet(surface):
    """Crystallizing a program must not change what it answers.

    If naming a recurring walk moved a single node in or out of the packet,
    nobody could promote one on the evidence of the ephemeral run.
    """
    named = surface.run_traversal(
        "prepare_topic_edit", {"topic_id": "topic:named-traversal"}
    )
    ephemeral = surface.run_ephemeral_traversal(
        TOPIC_CONTEXT, {"topic_id": "topic:named-traversal"}
    )

    assert named["outcome"] == ephemeral["outcome"] == "FOUND"
    assert ephemeral["kind"] == "EPHEMERAL_TRAVERSAL"
    assert (
        ephemeral["execution_receipt"]["result_fingerprint"]
        == named["execution_receipt"]["result_fingerprint"]
    )
    assert set(ephemeral["why_entered"]) == set(named["why_entered"])


def test_the_receipt_says_which_kind_of_program_produced_it(surface):
    """A reader deciding whether to trust a packet needs to see, without
    comparing it to graph.md, that nothing versioned stands behind it."""
    out = surface.run_ephemeral_traversal(
        TOPIC_CONTEXT, {"topic_id": "topic:named-traversal"}
    )

    receipt = out["execution_receipt"]
    assert receipt["ephemeral"] is True
    assert receipt["recipe_fingerprint"].startswith("tep_")
    assert receipt["recipe_version"] == 0
    assert out["recipe"]["ephemeral"] is True
    # Bounds, graph binding and the primitive contract are not relaxed.
    assert receipt["primitive_contract_version"] == "retrieval-v1"
    assert receipt["graph_version"] == out["graph_version"]


def test_an_ephemeral_program_cannot_wear_a_declared_recipes_name(surface):
    """Otherwise a receipt in Review reads as `prepare_topic_edit@1` while
    carrying neither that recipe's steps nor its version."""
    out = surface.run_ephemeral_traversal(
        {**TOPIC_CONTEXT, "name": "prepare_topic_edit"},
        {"topic_id": "topic:named-traversal"},
    )

    assert out["kind"] == "INVALID_TRAVERSAL"
    assert out["outcome"] == "INVALID_RECIPE"
    assert "prepare_topic_edit" in " ".join(out["errors"])


def test_an_ephemeral_receipt_never_satisfies_a_required_traversal(surface):
    """The authority line. `required_traversals` says a topic edit must be
    preceded by a re-runnable procedure; an unnamed program is not one, and
    propose must refuse it rather than accept a receipt it cannot reproduce.
    """
    ephemeral = surface.run_ephemeral_traversal(
        TOPIC_CONTEXT, {"topic_id": "topic:named-traversal"}
    )

    def _encoding(claim_id: str) -> dict:
        return {
            "concepts": [
                {
                    "id": claim_id,
                    "kind": "claim",
                    "label": "A program gathered this context",
                    "text_content": (
                        "Authored after a traversal over the same topic."
                    ),
                }
            ],
            "edges": [
                {
                    "predicate": "about",
                    "source_id": claim_id,
                    "target_id": "topic:named-traversal",
                }
            ],
        }

    refused = surface.propose(
        _encoding("claim:ephemeral-context"),
        provenance={"source_refs": ["paper:graph-retrieval-survey"]},
        target_gap_id="ephemeral_context",
        expected_graph_version=ephemeral["execution_receipt"]["graph_version"],
        traversal_receipt=ephemeral["execution_receipt"],
    )

    assert refused["error_code"] == "TRAVERSAL_MISMATCH"
    assert refused["traversal_preflight"]["status"] == "MISMATCH"

    # The control: the identical proposal behind the *named* run of the same
    # program is accepted, so the refusal above is about the receipt and not
    # about this edit.
    named = surface.run_traversal(
        "prepare_topic_edit", {"topic_id": "topic:named-traversal"}
    )
    committed = surface.propose(
        _encoding("claim:named-context"),
        provenance={"source_refs": ["paper:graph-retrieval-survey"]},
        target_gap_id="named_context",
        expected_graph_version=named["execution_receipt"]["graph_version"],
        traversal_receipt=named["execution_receipt"],
    )

    assert committed["status"] == "COMMITTED"
    assert committed["traversal_preflight"]["status"] == "VERIFIED"


def test_explain_returns_the_compiled_plan_without_executing(surface):
    out = surface.run_ephemeral_traversal(
        TOPIC_CONTEXT,
        {"topic_id": "topic:named-traversal"},
        explain=True,
    )

    assert out["kind"] == "TRAVERSAL_PLAN"
    assert out["outcome"] == "PLANNED"
    assert "evidence" not in out
    assert out["program"]["contract_version"] == "retrieval-v1"


def test_a_missing_seed_is_an_exact_miss_not_a_widened_search(surface):
    """The bounded-outcome invariant survives the new door."""
    out = surface.run_ephemeral_traversal(
        TOPIC_CONTEXT, {"topic_id": "topic:does-not-exist"}
    )

    assert out["outcome"] == "EXACT_MISS"
    assert not out["evidence"].get("node_records")


def test_a_predicate_the_format_does_not_declare_fails_closed(surface):
    """An ephemeral program is still bound by graph.md's vocabulary; that is
    what separates it from `retrieve`."""
    out = surface.run_ephemeral_traversal(
        {
            **TOPIC_CONTEXT,
            "steps": [
                {"op": "lookup", "references": ["$topic_id"], "assign": "seed"},
                {
                    "op": "expand",
                    "from": "$seed",
                    "predicates": ["invented_relation"],
                    "direction": "both",
                    "depth": 1,
                    "assign": "around",
                },
            ],
            "collect": "$around",
        },
        {"topic_id": "topic:named-traversal"},
    )

    assert out["kind"] == "INVALID_TRAVERSAL"
    assert out["outcome"] == "INVALID_RECIPE"


def test_the_verb_is_on_the_agent_surface_and_dispatches():
    from mcp_server.stdio import TOOLS

    tool = next(t for t in TOOLS if t.name == "run_ephemeral_traversal")
    assert tool.inputSchema["required"] == ["program"]
    assert "graph.md" in tool.description
