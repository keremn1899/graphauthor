from __future__ import annotations

from models import CompanyHandoff, CompanyInternalHandoff, EvidenceBrief, PlannerOutput, TrailRecord


def test_company_internal_handoff_coerces_nullable_text_fields():
    handoff = CompanyInternalHandoff(
        hypothesis_explanation=None,
        semantic_post_mortem=None,
    )
    assert handoff.hypothesis_explanation == ""
    assert handoff.semantic_post_mortem == ""


def test_company_handoff_coerces_nullable_and_string_list_fields():
    handoff = CompanyHandoff.model_validate(
        {
            "internal_handoff": {"semantic_post_mortem": None},
            "evidence_brief": {
                "strategy_b_surfaced": "cortisol",
                "primary_trail_labels": None,
                "recovery_memo": None,
            },
            "user_summary": None,
            "degradation_flags_received": "planner_schema_fallback",
            "recovery_spec": "",
        }
    )
    assert handoff.user_summary == ""
    assert handoff.evidence_brief.strategy_b_surfaced == ["cortisol"]
    assert handoff.evidence_brief.primary_trail_labels == []
    assert handoff.evidence_brief.recovery_memo == ""
    assert handoff.degradation_flags_received == ["planner_schema_fallback"]
    assert handoff.recovery_spec is None


def test_evidence_brief_coerces_warning_and_signal_shapes():
    brief = EvidenceBrief.model_validate(
        {
            "candidate_set_quality_warnings": ["legacy warning", {"type": "x", "severity": "high", "detail": "y"}],
            "squad_continuation_signals": {"termination_node": "n_001", "worth_continuing": True},
            "local_recovery_executed": None,
        }
    )
    assert brief.candidate_set_quality_warnings == [
        {"type": "unknown", "severity": "unknown", "detail": "legacy warning"},
        {"type": "x", "severity": "high", "detail": "y"},
    ]
    assert brief.squad_continuation_signals == [{"termination_node": "n_001", "worth_continuing": True}]
    assert brief.local_recovery_executed == {}


def test_trail_record_coerces_legacy_shape_fields():
    trail = TrailRecord.model_validate(
        {
            "trail_id": None,
            "origin": "neighbor",
            "rationale": None,
            "node_ids": "n_001",
            "edge_types": None,
            "edge_labels": None,
        }
    )
    assert trail.trail_id == ""
    assert trail.origin == "neighbourhood"
    assert trail.rationale == ""
    assert trail.node_ids == ["n_001"]
    assert trail.edge_types == []
    assert trail.edge_labels == []


def test_company_handoff_coerces_bridging_spec_false_to_none():
    handoff = CompanyHandoff.model_validate(
        {
            "internal_handoff": {"bridging_spec": False},
            "evidence_brief": {},
        }
    )
    assert handoff.internal_handoff.bridging_spec is None


def test_planner_output_still_accepts_basic_nested_shape():
    out = PlannerOutput.model_validate(
        {
            "reasoning_trace": "test",
            "strategy_a": {"concepts": []},
            "strategy_b": {"concepts": [], "reasoning_per_concept": None},
            "steps": [],
            "collect": "",
        }
    )
    assert out.strategy_a == {"concepts": []}
    assert out.strategy_b["concepts"] == []
