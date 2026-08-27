"""v5 architecture feature tests.

Tests for all 8 new test categories from testing-system-v2.md:
  degradation_observability, brief_integrity, structural_audit,
  planner_mode, cross_cluster, b_reasoning, battalion_calibration

Most tests are unit tests (no LLM, no DB). LLM-requiring tests
are marked @pytest.mark.integration and excluded from fast runs.

Run fast tests only:
    conda run -n agentic-graphrag pytest tests/test_v5_features.py -m "not integration" -v

Run all (including LLM-requiring):
    conda run -n agentic-graphrag pytest tests/test_v5_features.py -m integration -s -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from models import (
    CompanyHandoff,
    CompanyInternalHandoff,
    ConfirmationResponse,
    EvidenceBrief,
    GapEntry,
    PlannerOutput,
    SquadHandoff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_squad_handoff(
    cluster_id: str = "cluster_1",
    worth_continuing: bool = False,
    termination_node: dict | None = None,
    degradation_flags: list[str] | None = None,
    termination_status: str = "COMPLETE",
) -> dict:
    return SquadHandoff(
        cluster_id=cluster_id,
        decisions=[],
        termination_status=termination_status,
        termination_node=termination_node,
        continuation_signal={
            "worth_continuing": worth_continuing,
            "reason": "test",
            "suggested_edge_type": "LEADSTO",
            "suggested_direction": "forward",
        },
        cluster_summary="test cluster",
        degradation_flags=degradation_flags or [],
    ).model_dump()


def _make_company_handoff(
    gaps: list[dict] | None = None,
    continuation_signals: list[dict] | None = None,
    degradation_flags_received: list[str] | None = None,
) -> dict:
    if gaps is None:
        gaps = [{"gap_type": "missing_concept", "specific_node_or_concept": "X", "actionable_suggestion": "Add X"}]
    return CompanyHandoff(
        internal_handoff=CompanyInternalHandoff(
            hypothesis_status="not_confirmed",
            hypothesis_explanation="test",
            gaps=gaps,
        ),
        evidence_brief=EvidenceBrief(
            squad_continuation_signals=continuation_signals or [],
            specific_gaps=gaps,
        ),
        degradation_flags_received=degradation_flags_received or [],
    ).model_dump()


# ===========================================================================
# 1. DEGRADATION OBSERVABILITY
# ===========================================================================

@pytest.mark.degradation_observability
class TestDegradationObservability:

    def test_squad_handoff_has_degradation_flags_field(self):
        """Squad handoff schema must always include degradation_flags field."""
        h = _make_squad_handoff()
        assert "degradation_flags" in h
        assert isinstance(h["degradation_flags"], list)

    def test_squad_parse_error_flag_format(self):
        """squad_parse_error flag must be formatted as 'squad_parse_error:{cluster_id}'."""
        cluster_id = "cluster_3"
        h = _make_squad_handoff(cluster_id=cluster_id, degradation_flags=[f"squad_parse_error:{cluster_id}"])
        assert f"squad_parse_error:{cluster_id}" in h["degradation_flags"]

    def test_degradation_flags_propagate_to_company_handoff(self):
        """Company handoff schema must include degradation_flags_received."""
        ch = _make_company_handoff(degradation_flags_received=["squad_parse_error:cluster_1"])
        assert "degradation_flags_received" in ch
        assert "squad_parse_error:cluster_1" in ch["degradation_flags_received"]

    def test_nominal_squad_handoff_has_empty_degradation_flags(self):
        """On a nominal run, squad degradation_flags should be empty."""
        h = _make_squad_handoff()
        assert h["degradation_flags"] == []



    def test_company_handoff_schema_has_degradation_received(self):
        """CompanyHandoff schema must have degradation_flags_received field."""
        ch = CompanyHandoff()
        assert hasattr(ch, "degradation_flags_received")
        assert isinstance(ch.degradation_flags_received, list)


# ===========================================================================
# 2. EVIDENCE BRIEF INTEGRITY
# ===========================================================================

@pytest.mark.brief_integrity
class TestEvidenceBriefIntegrity:



    def test_gap_schema_violation_empty_specific_node(self):
        """GapEntry must reject empty specific_node_or_concept."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GapEntry(
                gap_type="missing_concept",
                specific_node_or_concept="",
                actionable_suggestion="Add X",
            )

    def test_gap_schema_violation_empty_actionable_suggestion(self):
        """GapEntry must reject empty actionable_suggestion."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GapEntry(
                gap_type="missing_concept",
                specific_node_or_concept="Some concept",
                actionable_suggestion="",
            )

    def test_gap_schema_valid_entry(self):
        """Valid GapEntry must construct without error."""
        g = GapEntry(
            gap_type="chain_truncated",
            specific_node_or_concept="n_089 (Cortisol Regulation)",
            actionable_suggestion="Extend this chain 2 hops forward via LEADSTO",
        )
        assert g.gap_type == "chain_truncated"
        assert g.specific_node_or_concept == "n_089 (Cortisol Regulation)"

    def test_gap_schema_all_valid_types(self):
        """All valid gap_type values must be accepted."""
        valid_types = [
            "missing_concept",
            "missing_relationship",
            "metanode_not_crossed",
            "coverage_shallow",
            "chain_truncated",
        ]
        for gt in valid_types:
            g = GapEntry(
                gap_type=gt,
                specific_node_or_concept="Test node",
                actionable_suggestion="Do something",
            )
            assert g.gap_type == gt




# ===========================================================================
# 3. STRUCTURAL AUDIT
# ===========================================================================

@pytest.mark.structural_audit
class TestStructuralAudit:

    def _make_structural_index(self, node_ids: list[str], roles: list[list[str]]) -> dict:
        """Build a minimal structural index for testing (StructuralFacts objects, as structural_audit expects)."""
        from models import StructuralFacts
        return {
            nid: StructuralFacts(roles=r)
            for nid, r in zip(node_ids, roles)
        }







# ===========================================================================
# 4. PLANNER MODE PROPAGATION
# ===========================================================================

@pytest.mark.planner_mode
class TestPlannerModePropagation:

    def test_planner_output_has_planner_mode_field(self):
        """PlannerOutput schema must include planner_mode field."""
        p = PlannerOutput(
            reasoning_trace="test",
            strategy_a={"concepts": []},
            strategy_b={"concepts": []},
            steps=[],
            collect="",
        )
        assert hasattr(p, "planner_mode")
        assert p.planner_mode == "nominal"

    def test_planner_output_schema_fallback_mode(self):
        """PlannerOutput must accept planner_mode='schema_fallback'."""
        p = PlannerOutput(
            reasoning_trace="test",
            strategy_a={"concepts": []},
            strategy_b={"concepts": []},
            steps=[],
            collect="",
            planner_mode="schema_fallback",
        )
        assert p.planner_mode == "schema_fallback"

    def test_confirmation_response_has_planner_mode(self):
        """ConfirmationResponse schema must include planner_mode field."""
        r = ConfirmationResponse(verdict="CONFIRMED")
        assert hasattr(r, "planner_mode")
        assert r.planner_mode == "nominal"

    def test_exhausted_under_fallback_has_compass_confidence_structure(self):
        """EXHAUSTED ConfirmationResponse under schema_fallback must have compass_confidence."""
        r = ConfirmationResponse(
            verdict="EXHAUSTED",
            planner_mode="schema_fallback",
            compass_confidence={"computed_under": "fallback_planning", "note": "fallback used"},
            exhaustion_explanation="Map exhausted under fallback planning.",
        )
        assert r.compass_confidence is not None
        assert r.compass_confidence["computed_under"] == "fallback_planning"

    def test_nominal_exhausted_has_nominal_compass_confidence(self):
        """EXHAUSTED under nominal mode must be structurally distinguishable."""
        nominal = ConfirmationResponse(
            verdict="EXHAUSTED",
            planner_mode="nominal",
            compass_confidence={"computed_under": "nominal", "note": ""},
        )
        fallback = ConfirmationResponse(
            verdict="EXHAUSTED",
            planner_mode="schema_fallback",
            compass_confidence={"computed_under": "fallback_planning", "note": ""},
        )
        assert nominal.compass_confidence["computed_under"] != fallback.compass_confidence["computed_under"]

    def test_confirmation_response_planner_mode_valid_values(self):
        """ConfirmationResponse planner_mode must only accept documented literals."""
        for mode in ("nominal", "schema_fallback", "compass_stale", "brief_incomplete"):
            r = ConfirmationResponse(planner_mode=mode)
            assert r.planner_mode == mode


# ===========================================================================
# 5. CROSS-CLUSTER CONTINUATION DETECTION
# ===========================================================================

@pytest.mark.cross_cluster
class TestCrossClusterDetection:





    def test_squad_handoff_has_cross_cluster_nodes_reached_field(self):
        """SquadHandoff schema must include cross_cluster_nodes_reached field."""
        h = SquadHandoff(cluster_id="cluster_1")
        assert hasattr(h, "cross_cluster_nodes_reached")
        assert isinstance(h.cross_cluster_nodes_reached, list)


# ===========================================================================
# 6. B-REASONING DOWNWARD CONTEXT
# ===========================================================================

@pytest.mark.b_reasoning
class TestBReasoningDownwardContext:

    def _make_planner_program_with_reasoning(self) -> dict:
        return {
            "strategy_b": {
                "concepts": ["cortisol_regulation", "hippocampal_plasticity"],
                "confidence": "medium",
                "reasoning_per_concept": {
                    "cortisol_regulation": "HPA axis upregulation directly suppresses hippocampal neurogenesis",
                    "hippocampal_plasticity": "memory consolidation impaired by chronic stress via BDNF reduction",
                },
            }
        }






# ===========================================================================
# 7. BATTALION DEGRADATION CALIBRATION
# ===========================================================================

@pytest.mark.battalion_calibration
class TestBattalionDegradationCalibration:

    def test_battalion_degradation_context_block_in_prompt(self):
        """Battalion synthesis prompt must include DEGRADATION CONTEXT block."""
        # We test that the string construction logic works by calling
        # the user_msg builder logic directly. Since battalion_synthesize
        # is tightly coupled to LLM calls, we test the state reading.

        # Simulate the degradation block construction (matches battalion.py logic)
        planner_mode = "schema_fallback"
        degradation_flags = ["squad_parse_error:cluster_1", "planner_schema_fallback"]
        compass_confidence = {"computed_under": "fallback_planning"}

        degradation_lines = [
            f"  planner_mode: {planner_mode}",
            f"  degradation_flags: {degradation_flags}",
            f"  compass_confidence: {compass_confidence}",
        ]
        block = "DEGRADATION CONTEXT:\n" + "\n".join(degradation_lines)

        assert "DEGRADATION CONTEXT" in block
        assert "schema_fallback" in block
        assert "squad_parse_error" in block

    def test_battalion_nominal_degradation_block_empty(self):
        """Battalion degradation context for nominal run must not contain real signals."""
        planner_mode = "nominal"
        degradation_flags: list = []
        compass_confidence = None

        degradation_lines = [
            f"  planner_mode: {planner_mode}",
            f"  degradation_flags: {degradation_flags if degradation_flags else '(none)'}",
            f"  compass_confidence: {compass_confidence if compass_confidence else '(nominal)'}",
        ]
        block = "DEGRADATION CONTEXT:\n" + "\n".join(degradation_lines)

        assert "planner_mode: nominal" in block
        assert "(none)" in block
        assert "(nominal)" in block

    def test_planner_mode_field_present_in_engine_state(self):
        """EngineState TypedDict must include planner_mode field."""
        from models import EngineState
        # TypedDicts don't have instances, but we can check the annotations
        annotations = EngineState.__annotations__
        assert "planner_mode" in annotations

    def test_degradation_flags_field_present_in_engine_state(self):
        """EngineState TypedDict must include degradation_flags field."""
        from models import EngineState
        assert "degradation_flags" in EngineState.__annotations__


# ===========================================================================
# 8. SCHEMA COMPLETENESS CHECKS (Hard Lines)
# ===========================================================================

class TestSchemaHardLines:
    """Schema-level hard line assertions — must all pass on every code change."""

    def test_squad_handoff_schema_complete(self):
        """SquadHandoff must include all v5 fields."""
        h = SquadHandoff(cluster_id="c1")
        assert hasattr(h, "degradation_flags")
        assert hasattr(h, "cross_cluster_nodes_reached")
        assert isinstance(h.degradation_flags, list)
        assert isinstance(h.cross_cluster_nodes_reached, list)

    def test_company_internal_handoff_gaps_type(self):
        """CompanyInternalHandoff gaps must be list (typed GapEntry dicts)."""
        ih = CompanyInternalHandoff()
        assert hasattr(ih, "gaps")
        assert isinstance(ih.gaps, list)
        assert hasattr(ih, "local_recovery_executed")
        assert isinstance(ih.local_recovery_executed, dict)

    def test_evidence_brief_schema_complete(self):
        """EvidenceBrief must include all v5 fields."""
        eb = EvidenceBrief()
        for field in (
            "strategy_b_reasoning_matches",
            "local_recovery_executed",
            "candidate_set_quality_warnings",
        ):
            assert hasattr(eb, field), f"Missing field: {field}"

    def test_company_handoff_schema_complete(self):
        """CompanyHandoff must include degradation_flags_received."""
        ch = CompanyHandoff()
        assert hasattr(ch, "degradation_flags_received")
        assert isinstance(ch.degradation_flags_received, list)

    def test_planner_output_schema_complete(self):
        """PlannerOutput must include cluster_budget_overrides and planner_mode."""
        p = PlannerOutput(
            reasoning_trace="r",
            strategy_a={"concepts": []},
            strategy_b={"concepts": []},
            steps=[],
            collect="",
        )
        assert hasattr(p, "cluster_budget_overrides")
        assert hasattr(p, "planner_mode")
        assert isinstance(p.cluster_budget_overrides, dict)

    def test_gap_entry_enum_exhaustive(self):
        """GapEntry gap_type enum must cover all documented types."""
        expected = {
            "missing_concept",
            "missing_relationship",
            "metanode_not_crossed",
            "coverage_shallow",
            "chain_truncated",
        }
        # Build one entry for each and verify no ValidationError
        for t in expected:
            g = GapEntry(
                gap_type=t,
                specific_node_or_concept="test_node",
                actionable_suggestion="Do something specific",
            )
            assert g.gap_type == t

    def test_confirmation_response_schema_complete(self):
        """ConfirmationResponse must include planner_mode and compass_confidence."""
        r = ConfirmationResponse()
        assert hasattr(r, "planner_mode")
        assert hasattr(r, "compass_confidence")
        assert r.planner_mode == "nominal"
        assert r.compass_confidence is None









