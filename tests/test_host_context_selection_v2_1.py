from __future__ import annotations

from benchmarks.external.cattrs_software.host_context_selection_v2_1 import (
    _load_frozen,
    choose_advancing,
    score_selection,
)


def _case() -> dict:
    return {
        "required_packet_ids": ["decision_rule", "decision_context"],
        "expected_primary_ids": ["decision_rule"],
        "expected_supplemental_ids": ["decision_context"],
        "permitted_optional_ids": ["decision_history"],
    }


def test_v2_1_frozen_binding_has_four_policies_and_five_cases():
    frozen = _load_frozen()

    assert frozen["context_policies"] == ["tools_only", "kernel", "focused", "full"]
    assert len(frozen["selection_cases"]) == 5


def test_packet_role_disagreement_is_diagnostic_not_gate_failure():
    score = score_selection(
        _case(),
        primary=["decision_context"],
        supplemental=["decision_rule", "decision_history"],
        invalid_values=[],
        observed={"decision_rule", "decision_context", "decision_history"},
        invalid_calls=0,
        completed=True,
    )

    assert score["passed"] is True
    assert score["role_diagnostics"]["expected_primary_not_primary"] == [
        "decision_rule"
    ]
    assert score["role_diagnostics"]["optional_selected_ids"] == [
        "decision_history"
    ]


def test_packet_gate_rejects_missing_extraneous_ungrounded_and_overlap():
    score = score_selection(
        _case(),
        primary=["decision_rule", "decision_extra", "decision_overlap"],
        supplemental=["decision_overlap"],
        invalid_values=["component"],
        observed={"decision_rule", "decision_overlap"},
        invalid_calls=1,
        completed=True,
    )

    assert set(score["failures"]) == {
        "missing_required_packet_id",
        "extraneous_packet_id",
        "ungrounded_packet_id",
        "packet_role_overlap",
        "duplicate_packet_id",
        "invalid_packet_value",
        "invalid_tool_call",
    }


def _rows(passing: set[str]) -> list[dict]:
    return [
        {"context_policy": policy, "score": {"passed": policy in passing}}
        for policy in ("tools_only", "kernel", "focused", "full")
        for _ in range(5)
    ]


def test_advancing_policy_is_smallest_pass_plus_full_control():
    assert choose_advancing(_rows({"tools_only", "kernel", "full"})) == [
        "tools_only", "full"
    ]
    assert choose_advancing(_rows({"focused", "full"})) == ["focused", "full"]
    assert choose_advancing(_rows({"full"})) == ["full"]
    assert choose_advancing(_rows(set())) == []
