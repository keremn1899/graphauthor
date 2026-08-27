from benchmarks.external.credential_governance.host_transfer_v1 import (
    ARMS,
    POLICIES,
    _ids,
    _load_task_binding,
    _statement,
    score_case,
)


def test_transfer_binding_covers_seven_cases_and_three_arms():
    frozen = _load_task_binding()

    assert len(frozen["cases"]) == 7
    assert tuple(frozen["selection"]["context_policies"]) == POLICIES
    assert tuple(frozen["adjudication"]["arms"]) == ARMS


def test_candidate_parser_preserves_any_stable_concept_id_and_reports_duplicates():
    values, errors = _ids({"candidate_node_ids": ["PurposeLimitationRule", "ScopedAccessClient", "PurposeLimitationRule"]})

    assert values == ["PurposeLimitationRule", "ScopedAccessClient"]
    assert errors == ["candidate_node_ids_duplicate"]


def test_statement_extracts_exact_rule_anchor():
    assert _statement({"text_content": "# Rule\n\nStatement: Exact MUST rule.\n\nScope: x"}) == "Exact MUST rule."


def test_scorer_rejects_component_as_applying_authority():
    case = {
        "predicate": "p",
        "required_applying_policy_ids": ["Rule"],
        "required_context_ids": ["Component"],
        "expected_policy_rulings": {"Rule": "VIOLATES"},
        "expected_kind": "VIOLATES",
        "expected_selected_ruling": "VIOLATES",
        "expected_coverage": "GOVERNED",
        "expected_disposition": "REVISE",
        "owner_decision_required": False,
        "expected_safe_to_act": False,
        "expected_gap_recordable": False,
        "requires_closure": False,
    }
    nodes = [
        {"id": "Rule", "text_content": "Statement: Exact MUST rule."},
        {"id": "Component", "text_content": "context"},
    ]
    result = {
        "decision_predicate": "p",
        "adjudications": [
            {"policy_id": "Rule", "conformance_ruling": "VIOLATES"},
            {"policy_id": "Component", "conformance_ruling": "VIOLATES"},
        ],
        "context_policy_ids": ["Component"],
        "kind": "VIOLATES",
        "selected_ruling": "VIOLATES",
        "selected_coverage": "GOVERNED",
        "disposition": "REVISE",
        "owner_decision_required": False,
        "safe_to_act": False,
        "gap_recordable": False,
        "closure_valid": False,
        "grounding": "Exact MUST rule.",
    }

    score = score_case(case, result, nodes, require_context=True)

    assert score["passed"] is False
    assert score["promoted_forbidden_authority_ids"] == ["Component"]
    assert score["cardinal_failure"] is True
