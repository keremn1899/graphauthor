"""Schema / TypedDict invariants (no DB, no network)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import (
    CompanyInternalHandoff,
    ConfirmationResponse,
    EngineState,
    SquadHandoff,
)


def test_engine_state_keys_match_runtime_initial_state():
    expected = {
        "query",
        "compass",
        "structural_index",
        "planner_program",
        "planner_reasoning",
        # Deterministic authority prior computed once during planning and
        # reused by Pipeline B to avoid a second graph scan.
        "planner_governing_candidates",
        "candidate_set",
        "judgment_candidate_set",
        "frontier_clusters",
        "squad_handoffs",
        "company_handoff",
        "company_recovery_spec",
        "confirmation_response",
        "dialogue_round",
        "semantic_feedback",
        "semantic_retry_attempted",
        "prev_alternative_spec",
        "seed_diagnostic",
        "reseed_attempted",
        "company_evidence_fingerprint",
        "pre_recovery_company_fingerprint",
        # v6 closure: fixpoint-based recovery termination state
        "pre_recovery_packet_signature",
        "recovery_plan_signatures",
        # v5 fields
        "candidate_set_quality",
        "cross_cluster_opportunities",
        "entity_resolution",
        "relation_proof_status",
        "evidence_status",
        "company_intent",
        "degradation_flags",
        "validation_result",
        "planner_mode",
        "final_answer",
        "provenance",
        "gaps",
        # v6 fields (info-infrastructure-v6): canonical evidence + contract
        "answer_contract",
        "evidence_packet",
        "company_dossier",
        "company_verdict",
        "semantic_validation_result",
        # v7 fields (graph-traversal-v7): three-pipeline dispatch + deterministic loops
        "planner_route",
        "classifier_rationale",
        "map_reader_output",
        "relational_contract",
        "hypothesis_grounding_result",
        "tool_dispatch_validation_result",
        "hypothesis_thread",
        "deterministic_verdict",
        # v9.x fields
        "grammar_guard_triggered",
        # v11 fields (plan validation)
        "plan_validation_ill_posed",
        "plan_validation_result",
        # rung-two: sticky governance/coverage-question signal (Option C)
        "governance_question",
        # Which verdict space the CALLER asked in. Typed replacement for the
        # query-text sniffing that sets `governance_question`.
        "verdict_space",
        # ...and whether the caller actually asked. Silence resolves to the
        # graph's published default, so the space alone no longer says who
        # chose it.
        "verdict_space_source",
        # Standing instruction for the reasoning tiers, kept out of the query.
        "governance_directive",
        # retrieval-v1: the structured operator→Planner intent envelope, the
        # canonical program executed this round, and the deterministic
        # operation/count/timing receipt for it. Read by pipeline_b,
        # agent_graph, planner and retrieval_program.
        "retrieval_request",
        "retrieval_program",
        "execution_receipt",
    }
    assert set(EngineState.__annotations__.keys()) == expected


def test_squad_handoff_termination_status_literals():
    for s in ("BUDGET_EXHAUSTED", "NATURAL_TERMINAL", "DEAD_END", "REDUNDANT", "COMPLETE"):
        SquadHandoff(termination_status=s, cluster_id="c1")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        SquadHandoff(termination_status="INVALID", cluster_id="c1")  # type: ignore[arg-type]


def test_confirmation_verdict_literals():
    for v in ("CONFIRMED", "EXHAUSTED", "ALTERNATIVE"):
        ConfirmationResponse(verdict=v)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        ConfirmationResponse(verdict="MAYBE")  # type: ignore[arg-type]


def test_confirmation_allows_null_alternative_spec_type():
    resp = ConfirmationResponse.model_validate(
        {
            "verdict": "EXHAUSTED",
            "alternative_spec": {"type": None},
        }
    )
    assert resp.alternative_spec is not None
    assert resp.alternative_spec.type == "null"


def test_company_confidence_literals():
    for c in ("high", "medium", "low"):
        CompanyInternalHandoff(confidence=c)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        CompanyInternalHandoff(confidence="maybe")  # type: ignore[arg-type]
