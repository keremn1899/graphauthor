from __future__ import annotations

from benchmarks.external.cattrs_software.host_agent_context_adjudication_v2 import (
    _context_projection,
    _load_frozen,
    _selection_score,
    choose_context_policies,
    guard_host_result,
    score_host_case,
)
from mcp_server.surface import open_fixture


def _gate_rows(passing: set[str]) -> list[dict]:
    return [
        {
            "context_policy": policy,
            "score": {"passed": policy in passing},
        }
        for policy in ("tools_only", "kernel", "focused", "full")
        for _ in range(4)
    ]


def test_v2_frozen_inputs_and_context_gate_cardinality():
    frozen, topology = _load_frozen()

    assert len(frozen["context_gate"]["task_ids"]) == 4
    assert len(frozen["selection_cases"]) == 5
    assert sum(
        len(row["derived_adjudication_task_ids"])
        for row in frozen["selection_cases"]
    ) == 6
    assert set(frozen["context_gate"]["task_ids"]) <= set(topology)


def test_context_policy_selection_is_mechanical_and_keeps_full_control():
    assert choose_context_policies(_gate_rows({"tools_only", "kernel", "focused", "full"})) == [
        "tools_only", "full"
    ]
    assert choose_context_policies(_gate_rows({"focused", "full"})) == [
        "focused", "full"
    ]
    assert choose_context_policies(_gate_rows({"full"})) == ["full"]
    assert choose_context_policies(_gate_rows(set())) == []




def test_selection_score_rejects_forbidden_ungrounded_and_exact_widening():
    score = _selection_score(
        required=["decision_rule"],
        forbidden=["decision_old"],
        selected=["decision_old", "decision_invented"],
        observed={"decision_old"},
        exact_gap=True,
        invalid_calls=1,
    )

    assert score["passed"] is False
    assert set(score["failures"]) == {
        "missing_required_candidate",
        "forbidden_candidate_selected",
        "ungrounded_candidate_selected",
        "exact_gap_widened",
        "invalid_tool_call",
    }


def _case() -> dict:
    return {
        "predicate": "Does this conform?",
        "artifact": "change",
        "closure_mode": "none",
        "expected_kind": "INSUFFICIENT_EVIDENCE",
        "expected_selected_ruling": "CONFORMS",
        "expected_coverage": "GOVERNED",
        "required_applying_policy_ids": ["rule"],
        "required_context_ids": [],
        "forbidden_authority_ids": ["context"],
        "expected_safe_to_act": False,
        "expected_disposition": "CORPUS_CLOSURE_REQUIRED",
        "owner_decision_required": False,
    }


def _oracle() -> dict:
    return {"rule": {"statement": "The adapter must remain outside the domain."}}


def test_pure_host_score_exposes_permission_and_context_promotion():
    result = {
        "decision_predicate": "Does this conform?",
        "kind": "CONFORMS",
        "selected_ruling": "CONFORMS",
        "selected_coverage": "GOVERNED",
        "adjudications": [
            {"policy_id": "rule", "conformance_ruling": "CONFORMS"},
            {"policy_id": "context", "conformance_ruling": "CONFORMS"},
        ],
        "context_policy_ids": [],
        "disposition": "NONE",
        "owner_decision_required": False,
        "safe_to_act": True,
        "closure_valid": False,
        "grounding": "The adapter must remain outside the domain.",
    }

    score = score_host_case(
        _case(), result, _oracle(), packet_ids={"rule", "context"}
    )

    assert score["cardinal_failure"] is True
    assert "false_permission" in score["failures"]
    assert "forbidden_authority_promoted" in score["failures"]


def test_guard_rejects_predicate_substitution_without_semantic_fold():
    guarded = guard_host_result(
        raw={"decision_predicate": "Would another change conform?"},
        case=_case(),
        packet={"edge_records": []},
        nodes=[],
        closure_receipt=None,
        graph_version="v",
        graph_profile={"normative_character": "normative"},
    )

    assert guarded["kind"] == "INSUFFICIENT_EVIDENCE"
    assert guarded["safe_to_act"] is False
    assert guarded["disposition"] == "QUESTION_CONTRACT_MISMATCH"
    assert guarded["guard_rejections"] == ["predicate_substitution"]


def test_guard_projects_host_semantics_through_authority_and_closure_gate():
    node = {
        "id": "rule",
        "label": "Dependency rule",
        "text_content": "The adapter must remain outside the domain.",
        "claim_kind": "governing",
        "claim_kind_source": "declared",
    }
    raw = {
        "decision_predicate": "Does this conform?",
        "adjudications": [
            {"policy_id": "rule", "conformance_ruling": "CONFORMS"}
        ],
        "context_policy_ids": [],
        "governance_verdict": "GOVERNED",
        "conformance_ruling": "CONFORMS",
        "unresolved_predicates": [],
        "grounding": "It conforms.",
    }

    guarded = guard_host_result(
        raw=raw,
        case=_case(),
        packet={"edge_records": [], "node_records": [node]},
        nodes=[node],
        closure_receipt=None,
        graph_version="v",
        graph_profile={"normative_character": "normative"},
    )

    assert guarded["selected_ruling"] == "CONFORMS"
    assert guarded["kind"] == "INSUFFICIENT_EVIDENCE"
    assert guarded["disposition"] == "CORPUS_CLOSURE_REQUIRED"
    assert guarded["safe_to_act"] is False
    assert guarded["applying_policy_ids"] == ["rule"]
    assert "The adapter must remain outside the domain." in guarded["grounding"]


def test_guard_preserves_demoted_packet_node_as_context_only():
    rule = {
        "id": "rule",
        "label": "Signing rule",
        "text_content": "ADJUDICATES: Every delivery must be signed.",
    }
    specification = {
        "id": "signature_spec",
        "label": "Signature specification",
        "text_content": "Use X-Signature with hex HMAC-SHA256.",
    }
    raw = {
        "decision_predicate": "Does this conform?",
        "adjudications": [
            {"policy_id": "rule", "conformance_ruling": "CONFORMS"},
            {"policy_id": "signature_spec", "conformance_ruling": "CONFORMS"},
            {"policy_id": "invented", "conformance_ruling": "CONFORMS"},
        ],
        "context_policy_ids": ["component", "invented_context"],
        "governance_verdict": "GOVERNED",
        "conformance_ruling": "CONFORMS",
        "unresolved_predicates": [],
        "grounding": "It conforms.",
    }
    component = {
        "id": "component",
        "label": "Worker",
        "text_content": "Dispatch component.",
    }

    guarded = guard_host_result(
        raw=raw,
        case=_case(),
        packet={"edge_records": [], "node_records": [rule, specification, component]},
        nodes=[rule, specification, component],
        closure_receipt=None,
        graph_version="v",
        graph_profile={"normative_character": "normative"},
    )

    assert guarded["applying_policy_ids"] == ["rule"]
    assert guarded["context_policy_ids"] == ["component", "signature_spec"]
    assert "invented" not in guarded["context_policy_ids"]
    assert guarded["selected_ruling"] == "CONFORMS"
    assert guarded["kind"] == "INSUFFICIENT_EVIDENCE"
