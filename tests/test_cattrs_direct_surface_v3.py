from benchmarks.external.cattrs_software.direct_surface_v3 import (
    DEFAULT_OUTPUT,
    TASK_BINDINGS_V31,
    _assert_frozen_inputs,
    _conformance_tool_arguments,
    _oracle_by_id,
    _load_task_bindings,
    score_conformance,
    score_discover,
    score_governance,
)


def test_whole_proposal_contract_uses_corpus_mode_not_scoped_receipt_mode():
    case = {
        "artifact": "Add a serializer adapter and define its wire semantics.",
        "predicate": "Which parts are governed, and which need an owner decision?",
        "attributed_rule_id": "expected_authority_not_a_tool_argument",
    }
    arguments = _conformance_tool_arguments(case)
    assert arguments == {
        "artifact": case["artifact"],
        "question": case["predicate"],
        "explain": True,
    }
    assert "rule_id" not in arguments


def test_v3_frozen_input_hashes_hold():
    _assert_frozen_inputs(DEFAULT_OUTPUT)


def test_v31_correction_is_a_separate_frozen_binding():
    corrected = _load_task_bindings(TASK_BINDINGS_V31)
    by_id = {case["task_id"]: case for case in corrected["conformance_cases"]}
    json_case = by_id["proposal:reject-core-json-special-case"]
    strict_case = by_id["proposal:per-class-strict-keys"]
    assert json_case["required_current_policy_ids"] == [
        "decision_current_serializer_behavior_lives_in_preconf"
    ]
    assert json_case["required_context_ids"] == [
        "decision_current_edge_concerns_stay_out_of_models"
    ]
    assert strict_case["required_current_policy_ids"] == [
        "decision_current_generated_hooks_inherit_policy"
    ]
    assert strict_case["required_context_ids"] == [
        "decision_current_converter_is_rule_registry"
    ]


def test_runner_exposes_repeatable_targeted_task_selection():
    from benchmarks.external.cattrs_software.direct_surface_v3 import main

    assert main([
        "--validate-only",
        "--surfaces", "check_conformance",
        "--task-id", "proposal:new-plistlib-backend",
    ]) == 0


def test_discover_exact_gap_rejects_candidate_widening():
    task = {
        "required_decision_ids": [],
        "forbidden_decision_ids": [],
        "expect_no_decisions": True,
    }
    result = {
        "verdict": "CONFIRMED",
        "evidence": {
            "node_records": [{"id": "decision_current_converter_is_rule_registry"}]
        },
        "prose": "A nearby hook decision exists.",
    }
    score = score_discover(task, result, _oracle_by_id())
    assert score["passed"] is False
    assert "exact_gap_not_preserved" in score["failures"]


def test_governance_packet_history_is_not_mistaken_for_authority():
    oracle = _oracle_by_id()
    current = "decision_current_sequence_structures_to_tuple"
    historical = "decision_superseded_sequence_structures_to_list"
    contract = {"predicate": "frozen contract"}
    case = {
        "expected_verdict": "GOVERNED",
        "required_policy_ids": [current],
    }
    result = {
        "status": "GOVERNED",
        "question": contract["predicate"],
        "evidence_node_ids": [current, historical],
        "grounding_summary": oracle[current]["statement"],
    }
    score = score_governance(case, contract, result, oracle)
    assert score["historical_authority_ids"] == []
    assert score["authority_basis_exposed"] is False
    assert "applying_authority_basis_not_exposed" in score["failures"]


def test_governance_rejects_historical_machine_authority():
    oracle = _oracle_by_id()
    current = "decision_current_sequence_structures_to_tuple"
    historical = "decision_superseded_sequence_structures_to_list"
    contract = {"predicate": "frozen contract"}
    case = {
        "expected_verdict": "GOVERNED",
        "required_policy_ids": [current],
    }
    result = {
        "status": "GOVERNED",
        "question": contract["predicate"],
        "evidence_node_ids": [current, historical],
        "authority_basis": [current, historical],
        "grounding_summary": oracle[current]["statement"],
    }
    score = score_governance(case, contract, result, oracle)
    assert score["passed"] is False
    assert score["historical_authority_ids"] == [historical]


def test_conformance_partial_state_is_not_coerced_to_a_binary_ruling():
    oracle = _oracle_by_id()
    current = "decision_current_serializer_behavior_lives_in_preconf"
    contract = {"predicate": "frozen ruling contract"}
    case = {
        "expected_coverage": "PARTIALLY_GOVERNED",
        "expected_ruling": "OWNER_DECISION_REQUIRED",
        "required_current_policy_ids": [current],
        "forbidden_authority_ids": [],
    }
    result = {
        "kind": "CONFORMS",
        "corpus_ruling": "CONFORMS",
        "governance_status": "GOVERNED",
        "attributed_rule": current,
        "grounding": oracle[current]["statement"],
    }
    score = score_conformance(
        case, contract, result, oracle,
        engine_queries=[contract["predicate"]],
    )
    assert score["expected_state_representable"] is True
    assert score["false_permission"] is True
    assert "ruling_mismatch" in score["failures"]
    assert "coverage_state_mismatch_or_unrepresentable" in score["failures"]


def test_conformance_partial_state_passes_on_separate_coverage_and_disposition_axes():
    oracle = _oracle_by_id()
    current = "decision_current_serializer_behavior_lives_in_preconf"
    contract = {"predicate": "frozen ruling contract"}
    case = {
        "expected_coverage": "PARTIALLY_GOVERNED",
        "expected_ruling": "OWNER_DECISION_REQUIRED",
        "required_current_policy_ids": [current],
        "forbidden_authority_ids": [],
    }
    result = {
        "kind": "INSUFFICIENT_EVIDENCE",
        "corpus_ruling": "INSUFFICIENT_EVIDENCE",
        "governance_status": "PARTIALLY_GOVERNED",
        "governed_ruling": "CONFORMS",
        "disposition": "OWNER_DECISION_REQUIRED",
        "owner_decision_required": True,
        "safe_to_act": False,
        "unresolved_predicates": ["exact plist wire semantics"],
        "applying_policy_ids": [current],
        "evidence_node_ids": [current],
        "grounding": oracle[current]["statement"],
    }
    score = score_conformance(
        case, contract, result, oracle,
        engine_queries=[contract["predicate"]],
    )
    assert score["passed"] is True
    assert score["false_permission"] is False


def test_conformance_context_is_evidence_not_applying_authority():
    oracle = _oracle_by_id()
    applying = "decision_current_generated_hooks_inherit_policy"
    context = "decision_current_converter_is_rule_registry"
    contract = {"predicate": "frozen ruling contract"}
    case = {
        "expected_coverage": "GOVERNED",
        "expected_ruling": "CONFORMS",
        "required_current_policy_ids": [applying],
        "required_context_ids": [context],
        "forbidden_authority_ids": [],
    }
    result = {
        "kind": "CONFORMS",
        "corpus_ruling": "CONFORMS",
        "governance_status": "GOVERNED",
        "applying_policy_ids": [applying],
        "evidence_node_ids": [applying, context],
        "grounding": oracle[applying]["statement"],
    }
    score = score_conformance(
        case, contract, result, oracle,
        engine_queries=[contract["predicate"]],
    )
    assert score["passed"] is True
    assert context not in score["declared_policy_ids"]


def test_conformance_exact_ruling_can_pass_complete_contract():
    oracle = _oracle_by_id()
    current = "decision_current_subclass_handling_is_opt_in"
    contract = {"predicate": "frozen ruling contract"}
    case = {
        "expected_coverage": "GOVERNED",
        "expected_ruling": "VIOLATES",
        "required_current_policy_ids": [current],
        "forbidden_authority_ids": [],
    }
    result = {
        "kind": "VIOLATES",
        "scoped_ruling": "VIOLATES",
        "corpus_ruling": "VIOLATES",
        "governance_status": "GOVERNED",
        "attributed_rule": current,
        "grounding": oracle[current]["statement"],
    }
    assert score_conformance(
        case, contract, result, oracle,
        engine_queries=[contract["predicate"]],
    )["passed"] is True
