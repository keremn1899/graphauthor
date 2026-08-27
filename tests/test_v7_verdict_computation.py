"""v7 Phase 7 — deterministic verdict computation tests (§7).

Covers the four reduction branches for Pipeline C:
- ILL_POSED (shapes unproducible from graph schema)
- CONFIRMED (packet satisfies contract + Company agrees)
- ALTERNATIVE (Company proposes graph-supported recovery, budget remains)
- EXHAUSTED (fallback: missing shapes, no viable recovery)
"""

from __future__ import annotations

from verdict_computation import (
    compute_verdict_exploratory,
    verdict_computation_node,
)


def _base_state(**overrides):
    state = {
        "query": "?",
        "planner_route": "exploratory",
        "compass": {
            "graph_profile": {
                "node_count": 10,
                "edge_counts": {"LEADSTO": 4, "CONTAINS": 3, "EXPRESSES": 2, "NEARTO": 1},
                "total_edges": 10,
            },
            "landmark_nodes": [{"id": "lm_a"}, {"id": "lm_b"}],
        },
        "structural_index": {"lm_a": {}, "lm_b": {}, "other": {}},
        "evidence_packet": {
            "node_records": [{"id": "lm_a"}],
            "edge_records": [],
            "path_records": [],
        },
        "answer_contract": {"evidence_shapes_expected": ["node_set"]},
        "company_verdict": {"hypothesis_assessment": "confirmed"},
        "dialogue_round": 0,
        "planner_program": {},
        "semantic_validation_result": {"violations": []},
    }
    state.update(overrides)
    return state


def test_ill_posed_when_graph_is_empty():
    state = _base_state(
        compass={"graph_profile": {"node_count": 0, "total_edges": 0, "edge_counts": {}}, "landmark_nodes": []},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "ILL_POSED"
    assert "zero nodes" in v["ill_posed_reason"]


def test_ill_posed_when_requires_edges_but_none_present():
    state = _base_state(
        compass={"graph_profile": {"node_count": 10, "total_edges": 0, "edge_counts": {}}, "landmark_nodes": []},
        answer_contract={"evidence_shapes_expected": ["subgraph"]},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "ILL_POSED"
    assert "zero edges" in v["ill_posed_reason"]


def test_ill_posed_when_declared_edge_types_absent():
    state = _base_state(
        compass={
            "graph_profile": {"node_count": 10, "total_edges": 5, "edge_counts": {"LEADSTO": 5}},
            "landmark_nodes": [],
        },
        planner_program={"steps": [{"params": {"edge_type": "EXPRESSES"}}]},
        answer_contract={"evidence_shapes_expected": ["edge_pairs"]},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "ILL_POSED"
    assert "expresses" in v["ill_posed_reason"].lower()


def test_confirmed_when_packet_satisfies_contract():
    state = _base_state()  # defaults: node_set satisfied, hypothesis=confirmed
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "CONFIRMED"
    assert v["terminal"] is True


def test_confirmed_partial_hypothesis_also_confirmed():
    state = _base_state(company_verdict={"hypothesis_assessment": "partial"})
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "CONFIRMED"
    assert "partial" in v["basis"].lower()


def test_alternative_when_company_supports_recovery():
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        answer_contract={"evidence_shapes_expected": ["node_set", "path"]},
        company_verdict={
            "hypothesis_assessment": "refuted",
            "recovery_intent": "local_extension",
            "recovery_intent_spec": {
                "target_ids": ["lm_a"],
                "reason": "extend from known landmark",
            },
        },
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "ALTERNATIVE"
    assert v["alternative_spec"]["type"] == "entry_point"
    assert v["alternative_spec"]["entry_point"]["landmark_id"] == "lm_a"


def test_alternative_denied_when_target_absent():
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        answer_contract={"evidence_shapes_expected": ["node_set", "path"]},
        company_verdict={
            "hypothesis_assessment": "refuted",
            "recovery_intent": "local_extension",
            "recovery_intent_spec": {"target_ids": ["nonexistent_node"]},
        },
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "EXHAUSTED"


def test_alternative_denied_when_edge_type_absent():
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        answer_contract={"evidence_shapes_expected": ["edge_pairs"]},
        company_verdict={
            "hypothesis_assessment": "refuted",
            "recovery_intent": "local_extension",
            "recovery_intent_spec": {"target_ids": ["lm_a"], "edge_type": "NONEXISTENT"},
        },
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "EXHAUSTED"


def test_exhausted_when_recovery_plan_already_attempted():
    """v6 closure: predictive fixpoint — a plan signature already in
    `recovery_plan_signatures` cannot be re-issued. Replaces the old count-
    based budget that capped ALTERNATIVE at one round."""
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        answer_contract={"evidence_shapes_expected": ["path"]},
        company_verdict={
            "hypothesis_assessment": "refuted",
            "recovery_intent": "local_extension",
            "recovery_intent_spec": {"target_ids": ["lm_a"]},
        },
    )
    # Mark this exact plan as already tried.
    state["recovery_plan_signatures"] = ["entry_point:lm_a"]
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "EXHAUSTED"
    assert "fixpoint" in v["exhaustion_explanation"]


def test_exhausted_when_prior_recovery_added_nothing():
    """v6 closure: post-hoc fixpoint — if the previous recovery round did
    not grow the packet, the reducer refuses another ALTERNATIVE round."""
    packet = {"node_records": [{"id": "n1"}], "edge_records": [], "path_records": []}
    state = _base_state(
        evidence_packet=packet,
        answer_contract={"evidence_shapes_expected": ["path"]},
        company_verdict={
            "hypothesis_assessment": "refuted",
            "recovery_intent": "local_extension",
            "recovery_intent_spec": {"target_ids": ["lm_a"]},
        },
    )
    # Pre-recovery snapshot matches the current packet — zero growth.
    state["pre_recovery_packet_signature"] = {
        "node_count": 1, "edge_count": 0, "path_count": 0,
    }
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "EXHAUSTED"
    assert "fixpoint" in v["exhaustion_explanation"]


def test_exhausted_when_missing_shapes_and_no_recovery_intent():
    state = _base_state(
        evidence_packet={"node_records": [{"id": "lm_a"}], "edge_records": [], "path_records": []},
        answer_contract={"evidence_shapes_expected": ["node_set", "path"]},
        company_verdict={"hypothesis_assessment": "refuted"},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "EXHAUSTED"
    assert "path" in v["missing_shapes"]


def test_confirmed_when_no_contract_but_packet_has_content():
    state = _base_state(
        answer_contract={},
        company_verdict={"hypothesis_assessment": ""},
        evidence_packet={"node_records": [{"id": "n1"}], "edge_records": [], "path_records": []},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "CONFIRMED"


def test_node_mirrors_verdict_to_confirmation_response():
    state = _base_state()
    out = verdict_computation_node(state)
    assert out["confirmation_response"]["verdict"] == "CONFIRMED"
    assert out["deterministic_verdict"]["kind"] == "CONFIRMED"
    assert out["dialogue_round"] == 0  # not ALTERNATIVE → no increment


def test_node_increments_dialogue_round_on_alternative():
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        answer_contract={"evidence_shapes_expected": ["node_set"]},
        company_verdict={
            "hypothesis_assessment": "refuted",
            "recovery_intent": "local_extension",
            "recovery_intent_spec": {"target_ids": ["lm_a"]},
        },
    )
    out = verdict_computation_node(state)
    assert out["confirmation_response"]["verdict"] == "ALTERNATIVE"
    assert out["dialogue_round"] == 1
    assert out["prev_alternative_spec"]["type"] == "entry_point"


def test_ill_posed_on_vocabulary_miss_after_reseed():
    """v8 §7: a full hypothesis miss after reseed when the schema could
    otherwise express the query produces UNKNOWN_TO_GRAPH (content gap),
    not ILL_POSED (structural unanswerability)."""
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        degradation_flags=["hypothesis_full_miss"],
        reseed_attempted=True,
        company_verdict={"hypothesis_assessment": "not_confirmed"},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "UNKNOWN_TO_GRAPH"
    assert "content gap" in v["basis"].lower()


def test_full_miss_without_reseed_does_not_trigger_ill_posed():
    """Without a reseed attempt yet, a full miss is not terminal — the
    router should still have a chance to reseed first."""
    state = _base_state(
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        degradation_flags=["hypothesis_full_miss"],
        # reseed_attempted defaults to absent
        company_verdict={"hypothesis_assessment": "not_confirmed"},
    )
    v = compute_verdict_exploratory(state)
    assert v["kind"] == "EXHAUSTED"


def test_node_exposes_ill_posed_reason_in_confirmation_response():
    state = _base_state(
        compass={"graph_profile": {"node_count": 0, "total_edges": 0, "edge_counts": {}}, "landmark_nodes": []},
    )
    out = verdict_computation_node(state)
    assert out["confirmation_response"]["verdict"] == "ILL_POSED"
    assert "zero nodes" in out["confirmation_response"]["ill_posed_reason"]
