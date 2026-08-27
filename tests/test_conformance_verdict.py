"""Unit tests for ConformanceVerdict mapping and mis-governance alignment."""

from __future__ import annotations

from conformance_verdict import (
    ConformanceKind,
    _bounded_grounding,
    conformance_matches_mis_governance_rec,
    expected_conformance_from_query,
    from_engine_state,
    infer_ruling,
)
from mis_governance_rubric import score_mis_governance


def _state(gov: str, answer: str, *, predicate: str = "", labels: list[str] | None = None, verdict: str = "CONFIRMED"):
    return {
        "confirmation_response": {
            "governance_verdict": gov,
            "ungoverned_predicate": predicate,
            "verdict": verdict,
            "governance_verdict_source": "battalion_synthesis",
        },
        "final_answer": answer,
        "evidence_packet": {"node_records": [{"label": l} for l in (labels or [])]},
        "planner_route": "targeted_retrieval",
    }


def test_ungoverned_distinct_from_insufficient():
    cv_u = from_engine_state(_state("UNGOVERNED", "No rule.", predicate="retry_policy"))
    assert cv_u.verdict == ConformanceKind.UNGOVERNED
    assert cv_u.predicate == "retry_policy"

    cv_i = from_engine_state(_state("ABSENT", "", verdict="UNKNOWN_TO_GRAPH"))
    assert cv_i.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE


def test_governed_allow_maps_conforms():
    answer = "**Answer:** The adapter may persist status via the repository."
    cv = from_engine_state(
        _state("GOVERNED", answer, labels=["OrderStatusOwnershipRule"]),
        allow_signals=[r"may persist"],
    )
    assert cv.verdict == ConformanceKind.CONFORMS
    assert cv.ruling_inferred == "ALLOW"


def test_governed_deny_maps_violates():
    answer = "**Answer:** The adapter must not set order.status — not permitted."
    cv = from_engine_state(
        _state("GOVERNED", answer, labels=["OrderStatusOwnershipRule"]),
        deny_signals=[r"must not set"],
    )
    assert cv.verdict == ConformanceKind.VIOLATES
    assert cv.ruling_inferred == "DENY"


def test_timeout_insufficient():
    cv = from_engine_state({"engine_verdict": "TIMEOUT"})
    assert cv.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE


def test_empty_packet_absent_governed_insufficient():
    cv = from_engine_state(_state("ABSENT", "", labels=[]))
    assert cv.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE


def test_expected_from_query_axes():
    assert expected_conformance_from_query({"expected_governance": "UNGOVERNED"}) == ConformanceKind.UNGOVERNED
    assert expected_conformance_from_query({"expected_governance": "GOVERNED", "expected_ruling": "ALLOW"}) == ConformanceKind.CONFORMS
    assert expected_conformance_from_query({"expected_governance": "GOVERNED", "expected_ruling": "DENY"}) == ConformanceKind.VIOLATES


def test_mis_governance_rec_alignment():
    query = {
        "expected_governance": "GOVERNED",
        "expected_ruling": "DENY",
        "ruling_deny_signals": [r"must not set"],
        "grounding_label_tokens": ["OrderStatusOwnershipRule"],
    }
    rec = {
        "governance_verdict": "GOVERNED",
        "final_answer": "The adapter must not set status.",
        "node_labels": ["OrderStatusOwnershipRule"],
        "verdict": "CONFIRMED",
    }
    rec.update(score_mis_governance(rec, query))
    assert conformance_matches_mis_governance_rec(rec, query) is True


def test_structured_conformance_ruling_from_confirmation():
    cv = from_engine_state(
        _state("GOVERNED", "Yes, authorized.", labels=["PacketImmutabilityRule"]),
        allow_signals=[],
        deny_signals=[r"forbidden"],
    )
    assert cv.verdict == ConformanceKind.CONFORMS  # Yes prefix fallback

    cv2 = from_engine_state(
        {
            "confirmation_response": {
                "governance_verdict": "GOVERNED",
                "conformance_ruling": "VIOLATES",
                "verdict": "CONFIRMED",
            },
            "final_answer": "Prose may disagree but structured field wins.",
            "evidence_packet": {"node_records": [{"label": "ContractDeterminismRule"}]},
        }
    )
    assert cv2.verdict == ConformanceKind.VIOLATES
    assert cv2.ruling_inferred == "VIOLATES"


def test_conformance_projects_folded_authority_axes():
    state = _state(
        "GOVERNED",
        "The proposal conforms.",
        labels=["StrictKeyPolicy"],
    )
    state["confirmation_response"].update({
        "decision_predicate": "per-class strict keys",
        "adjudications": [{
            "policy_id": "strict_key_policy",
            "conformance_ruling": "CONFORMS",
        }],
        "authority_binding": "marked",
        "unsupported_presuppositions": ["global strictness is required"],
        "conformance_ruling": "CONFORMS",
    })
    verdict = from_engine_state(state)
    assert verdict.decision_predicate == "per-class strict keys"
    assert verdict.applying_policy_ids == ["strict_key_policy"]
    assert verdict.authority_binding == "marked"
    assert verdict.unsupported_presuppositions == [
        "global strictness is required"
    ]


def test_bounded_grounding_reserves_space_for_exact_authority_appendix():
    marker = "**Governing constraints (verbatim graph anchors):**"
    clause = "Generated hooks inherit the converter's strict-key policy."
    answer = f"{'A' * 2500}\n\n{marker}\n- strict_key_policy: {clause}"

    grounding = _bounded_grounding(answer)

    assert len(grounding) == 2000
    assert grounding.startswith("A")
    assert grounding.endswith(f"- strict_key_policy: {clause}")


def test_bounded_grounding_without_authority_appendix_keeps_prefix_contract():
    assert _bounded_grounding("A" * 2500) == "A" * 2000


def test_bounded_grounding_does_not_truncate_an_oversized_authority_appendix():
    marker = "**Governing constraints (verbatim graph anchors):**"
    appendix = f"{marker}\n{'B' * 2500}"

    assert _bounded_grounding(f"prose\n\n{appendix}") == appendix
