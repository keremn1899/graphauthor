"""Canonical retrieval-program contract and deterministic runtime."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from retrieval_program import (
    RETRIEVAL_PROGRAM_VERSION,
    canonicalise_program,
    execute_retrieval_program,
    lower_relational_contract,
    program_for_targeted_state,
    retrieval_capability_card,
)


def test_capability_card_announces_completeness_and_honest_terminals():
    card = retrieval_capability_card()

    assert card["empty_result"]["meaning"] == "valid_bounded_observation"
    assert "implicit widening" in card["empty_result"]["policy"]
    assert card["proof"]["success_evidence"] == "path_record"
    assert set(card["judgment_view"]["bypasses"]) >= {
        "proof", "enumeration", "fanout", "chain", "count", "confirmation"
    }
    assert card["judgment_view"]["packet_truth"] == "append_only"
    assert set(card["terminal_outcomes"]["discover"]) == {
        "ILL_POSED", "EXHAUSTED", "UNKNOWN_TO_GRAPH"
    }


def test_direct_program_executes_without_an_llm(deps_conn):
    program = {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "author": "direct",
        "steps": [
            {
                "tool": "exact_node_lookup",
                "params": {"label_or_id": ["svc_gateway"]},
                "assign_to": "seed",
            },
            {
                "tool": "get_neighbourhood",
                "params": {
                    "node_ids": "$seed",
                    "edge_types": ["leadsto"],
                    "direction": "outgoing",
                    "depth": 1,
                },
                "assign_to": "next",
            },
        ],
        "collect": "$seed + $next",
        "limits": {"max_nodes_per_step": 20},
    }

    result = execute_retrieval_program(deps_conn, program)
    packet = result["evidence_packet"]
    ids = {node["id"] for node in packet["node_records"]}

    assert "svc_gateway" in ids
    assert packet["edge_records"]
    assert all(edge["edge_type"] == "leadsto" for edge in packet["edge_records"])
    assert result["execution_receipt"]["author"] == "direct"
    assert result["execution_receipt"]["program_hash"]


def test_program_rejects_forward_references():
    with pytest.raises(ValidationError, match="before it is assigned"):
        canonicalise_program({
            "contract_version": RETRIEVAL_PROGRAM_VERSION,
            "steps": [{
                "tool": "get_neighbourhood",
                "params": {"node_ids": "$later"},
                "assign_to": "first",
            }],
            "collect": "$first",
        })


def test_program_rejects_unknown_tools_and_collect_variables():
    with pytest.raises(ValidationError, match="unsupported tool"):
        canonicalise_program({
            "contract_version": RETRIEVAL_PROGRAM_VERSION,
            "steps": [{"tool": "invent_answer", "params": {}, "assign_to": "x"}],
            "collect": "$x",
        })
    with pytest.raises(ValidationError, match="collect references unknown"):
        canonicalise_program({
            "contract_version": RETRIEVAL_PROGRAM_VERSION,
            "steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": "svc_gateway"},
                "assign_to": "x",
            }],
            "collect": "$missing",
        })


def test_program_rejects_unsupported_collect_operators_instead_of_ignoring_them():
    """Unknown set operators must not execute as only their left operand."""
    with pytest.raises(ValidationError, match="unsupported collect expression"):
        canonicalise_program({
            "contract_version": RETRIEVAL_PROGRAM_VERSION,
            "steps": [
                {
                    "tool": "exact_node_lookup",
                    "params": {"label_or_id": "a"},
                    "assign_to": "a",
                },
                {
                    "tool": "exact_node_lookup",
                    "params": {"label_or_id": "b"},
                    "assign_to": "b",
                },
            ],
            "collect": "$a | $b",
        })


def test_program_accepts_the_complete_declared_collect_algebra():
    program = canonicalise_program({
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "steps": [
            {"tool": "exact_node_lookup", "params": {}, "assign_to": "a"},
            {"tool": "exact_node_lookup", "params": {}, "assign_to": "b"},
            {"tool": "exact_node_lookup", "params": {}, "assign_to": "c"},
        ],
        "collect": "$a + $b - $c & $a",
    })
    assert program.collect == "$a + $b - $c & $a"


@pytest.mark.parametrize("edge_type", ["leadsto", "contains", "expresses", "nearto"])
def test_legacy_fanout_contract_lowers_to_the_same_program_grammar(edge_type):
    program = lower_relational_contract({
        "question_form": "fanout",
        "source_ids": ["svc_gateway"],
        "edge_types": [edge_type],
        "direction": "outgoing",
        "max_hops": 1,
    })

    assert program.contract_version == RETRIEVAL_PROGRAM_VERSION
    assert program.author == "contract_lowering"
    assert [step.tool for step in program.steps] == [
        "exact_node_lookup", "get_neighbourhood"
    ]
    assert program.steps[1].params["edge_types"] == [edge_type]


def test_targeted_state_compiles_its_relational_contract_not_exploratory_steps():
    state = {
        "planner_program": {
            "steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": ["svc_auth"]},
                "assign_to": "precise",
            }],
            "collect": "$precise",
        },
        "relational_contract": {
            "question_form": "lookup",
            "source_ids": ["svc_gateway"],
            "edge_types": ["leadsto"],
        },
    }

    program = program_for_targeted_state(state)

    assert program.author == "contract_lowering"
    assert program.steps[0].params["label_or_id"] == ["svc_gateway"]


def test_contract_is_lowered_only_when_planner_has_no_steps():
    program = program_for_targeted_state({
        "planner_program": {"steps": []},
        "relational_contract": {
            "question_form": "lookup",
            "source_ids": ["svc_gateway"],
            "edge_types": ["leadsto"],
        },
    })
    assert program.author == "contract_lowering"


def test_limits_are_applied_to_neighbourhood_receipt(deps_conn):
    result = execute_retrieval_program(deps_conn, {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "steps": [
            {
                "tool": "exact_node_lookup",
                "params": {"label_or_id": "svc_gateway"},
                "assign_to": "seed",
            },
            {
                "tool": "get_neighbourhood",
                "params": {"node_ids": "$seed", "depth": 99},
                "assign_to": "region",
            },
        ],
        "collect": "$seed + $region",
        "limits": {"max_hops_per_step": 1, "max_nodes_per_step": 2},
    })

    assert result["execution_receipt"]["limits"]["max_hops_per_step"] == 1
    assert len(result["variables"]["region"]) <= 2


def test_planner_null_contingency_syntax_triggers_without_eval(deps_conn):
    result = execute_retrieval_program(deps_conn, {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "steps": [{
            "tool": "exact_node_lookup",
            "params": {"label_or_id": "not_a_real_node"},
            "assign_to": "missing",
        }],
        "collect": "$missing",
        "contingency": {
            "trigger": "$missing == null",
            "fallback_steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": "svc_gateway"},
                "assign_to": "fallback",
            }],
            "fallback_collect": "$fallback",
        },
    })

    assert result["execution_receipt"]["contingency_triggered"] is True
    assert "svc_gateway" in result["collected_ids"]


def test_invalid_contingency_syntax_is_a_safe_non_trigger(deps_conn):
    result = execute_retrieval_program(deps_conn, {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "steps": [{
            "tool": "exact_node_lookup",
            "params": {"label_or_id": "svc_gateway"},
            "assign_to": "seed",
        }],
        "collect": "$seed",
        "contingency": {"trigger": "this is not valid ("},
    })
    assert result["execution_receipt"]["contingency_triggered"] is False


def test_exact_lookup_never_hides_a_semantic_fallback(deps_conn, monkeypatch):
    import backend_tools

    monkeypatch.setattr(
        backend_tools,
        "vector_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("exact lookup called vector search")
        ),
    )
    result = execute_retrieval_program(deps_conn, {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "steps": [{
            "tool": "exact_node_lookup",
            "params": {"label_or_id": "a_plausible_but_absent_node"},
            "assign_to": "missing",
        }],
        "collect": "$missing",
    })
    assert result["collected_ids"] == []
