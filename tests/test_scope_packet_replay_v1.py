from __future__ import annotations

from benchmarks.external.cattrs_software.reference import build_reference_graph
from benchmarks.external.cattrs_software.scope_packet_replay_v1 import (
    _load_frozen,
    compile_packet,
    score_compiled,
)


def test_scope_replay_inputs_are_frozen_and_complete():
    _, source, selection = _load_frozen()

    assert len(source["rows"]) == 20
    assert len(selection["selection_cases"]) == 5


def test_compiler_keeps_explicit_and_direct_scope_decisions_without_recursing():
    graph = build_reference_graph()
    row = {
        "final": {
            "primary_candidate_ids": ["decision_current_generated_hooks_inherit_policy"],
            "supplemental_context_ids": ["converter_registry"],
        },
        "observed_node_ids": [
            "decision_current_generated_hooks_inherit_policy",
            "converter_registry",
        ],
    }

    compiled = compile_packet(row, graph=graph)

    assert compiled["scope_ids"] == ["converter_registry"]
    assert "decision_current_converter_is_rule_registry" in compiled["compiled_packet_ids"]
    assert "decision_current_generated_hooks_inherit_policy" in compiled["compiled_packet_ids"]
    assert "decision_current_detailed_validation_default" not in compiled["compiled_packet_ids"]


def test_compiler_uses_one_labelled_adjacent_scope_then_direct_decisions():
    graph = build_reference_graph()
    row = {
        "final": {
            "primary_candidate_ids": ["decision_current_serializer_behavior_lives_in_preconf"],
            "supplemental_context_ids": ["serializer_adapter_layer"],
        },
        "observed_node_ids": [
            "decision_current_serializer_behavior_lives_in_preconf",
            "serializer_adapter_layer",
        ],
    }

    compiled = compile_packet(row, graph=graph)

    assert compiled["adjacent_scope_ids"] == ["edge_boundary"]
    assert "decision_current_edge_concerns_stay_out_of_models" in compiled["compiled_packet_ids"]
    assert "decision_rejected_model_coupled_serialization" in compiled["compiled_packet_ids"]


def test_compiler_rejects_unobserved_scope_and_score_preserves_failure():
    graph = build_reference_graph()
    row = {
        "final": {
            "primary_candidate_ids": ["decision_current_serializer_behavior_lives_in_preconf"],
            "supplemental_context_ids": ["serializer_adapter_layer"],
        },
        "observed_node_ids": ["decision_current_serializer_behavior_lives_in_preconf"],
    }

    compiled = compile_packet(row, graph=graph)
    score = score_compiled(
        {"required_packet_ids": ["decision_current_serializer_behavior_lives_in_preconf"]},
        compiled,
    )

    assert compiled["validation_errors"] == ["unobserved:serializer_adapter_layer"]
    assert score["passed"] is False
    assert score["failures"] == ["compiler_validation_error"]
