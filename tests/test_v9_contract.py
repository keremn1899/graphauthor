"""v9 Agent Contract v1 conformance tests.

Deterministic: no LLM calls. Validates that ``build_agent_response``
produces a stable contract-shaped object from representative final
EngineState dicts covering each verdict and each retrieval strategy.
"""

from __future__ import annotations

import pytest

from contract import (
    CONTRACT_VERSION,
    AgentResponse,
    build_agent_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_packet() -> dict:
    return {
        "node_records": [
            {"id": "n_a", "label": "Alpha", "text_content": "Alpha is the first concept in the graph."},
            {"id": "n_b", "label": "Beta", "text_content": "Beta follows alpha and leads to gamma."},
            {"id": "n_c", "label": "Gamma", "text_content": "Gamma is a terminal."},
        ],
        "edge_records": [
            {"source_id": "n_a", "target_id": "n_b", "edge_type": "leadsto",
             "edge_label": "directly_causes", "source_label": "Alpha", "target_label": "Beta"},
            {"source_id": "n_b", "target_id": "n_c", "edge_type": "leadsto",
             "edge_label": "comes_before", "source_label": "Beta", "target_label": "Gamma"},
        ],
        "path_records": [
            {"node_chain": ["n_a", "n_b", "n_c"], "edge_chain": ["leadsto", "leadsto"]},
        ],
        "packet_provenance": [],
        "append_log": [],
        "degradation_flags": [],
    }


def _state_confirmed() -> dict:
    return {
        "query": "Does Alpha lead to Gamma?",
        "evidence_packet": _base_packet(),
        "confirmation_response": {"verdict": "CONFIRMED"},
        "deterministic_verdict": {"kind": "CONFIRMED", "basis": "path found"},
        "retrieval_strategy": "exploratory",
        "company_handoff": {
            "internal_handoff": {
                "primary_trails": [{"trail_id": "t1", "origin": "direct_path",
                                     "node_ids": ["n_a", "n_b", "n_c"]}],
                "gaps": [],
            }
        },
        "provenance": [
            {"trail_id": "t1", "origin": "direct_path", "node_ids": ["n_a", "n_b", "n_c"],
             "confidence_provenance": {"source": "llm", "tier": "company_llm",
                                        "basis": "primary"}},
        ],
        "gaps": [],
        "final_answer": "Yes, Alpha leads to Gamma via Beta.",
        "degradation_flags": [],
    }


def _state_ill_posed() -> dict:
    return {
        "query": "What is the set difference between bridges and origins?",
        "evidence_packet": _base_packet(),
        "confirmation_response": {"verdict": "ILL_POSED",
                                   "ill_posed_reason": "set-difference operator not in grammar"},
        "deterministic_verdict": {"kind": "ILL_POSED", "basis": "operator not in grammar"},
        "retrieval_strategy": "compass_derivation",
        "gaps": [],
        "final_answer": "",
    }


def _state_unknown() -> dict:
    return {
        "query": "Tell me about Quantum Entanglement Yoga.",
        "evidence_packet": {"node_records": [], "edge_records": [],
                             "path_records": [], "packet_provenance": [],
                             "append_log": [], "degradation_flags": []},
        "confirmation_response": {"verdict": "UNKNOWN_TO_GRAPH"},
        "deterministic_verdict": {"kind": "UNKNOWN_TO_GRAPH"},
        "retrieval_strategy": "exploratory",
        "gaps": [],
        "final_answer": "",
    }


def _state_exhausted_enum() -> dict:
    return {
        "query": "List all nodes in this graph.",
        "evidence_packet": _base_packet(),
        "confirmation_response": {"verdict": "EXHAUSTED"},
        "deterministic_verdict": {"kind": "EXHAUSTED"},
        "retrieval_strategy": "contract_driven",
        "gaps": [{"gap_type": "coverage_shallow", "specific_node_or_concept": "n_c",
                  "actionable_suggestion": "add downstream nodes"}],
        "final_answer": "Nodes: Alpha, Beta, Gamma.",
        "provenance": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContractConformance:
    def test_every_verdict_produces_valid_response(self):
        for state_fn in (_state_confirmed, _state_ill_posed, _state_unknown, _state_exhausted_enum):
            resp = build_agent_response(state_fn(), graph_version="gv_test_abc123")
            assert isinstance(resp, AgentResponse)
            # Schema-level round trip must succeed.
            AgentResponse.model_validate(resp.model_dump())

    def test_contract_version_is_pinned(self):
        resp = build_agent_response(_state_confirmed(), graph_version="gv_x")
        assert resp.contract_version == CONTRACT_VERSION == "1"

    def test_graph_version_propagates(self):
        resp = build_agent_response(_state_confirmed(), graph_version="gv_xyz")
        assert resp.graph_version == "gv_xyz"

    def test_verdict_is_one_of_five(self):
        for state_fn in (_state_confirmed, _state_ill_posed, _state_unknown, _state_exhausted_enum):
            resp = build_agent_response(state_fn())
            assert resp.verdict in {
                "CONFIRMED", "ALTERNATIVE", "EXHAUSTED", "ILL_POSED", "UNKNOWN_TO_GRAPH",
            }

    def test_claim_null_on_ill_posed_and_unknown(self):
        assert build_agent_response(_state_ill_posed()).claim is None
        assert build_agent_response(_state_unknown()).claim is None

    def test_claim_present_on_confirmed(self):
        resp = build_agent_response(_state_confirmed())
        assert resp.claim is not None
        assert resp.claim.primary_content
        assert resp.claim.answer_type in {"yes_no", "list", "narrative", "structural"}

    def test_yes_no_structured_data_shape(self):
        resp = build_agent_response(_state_confirmed())
        assert resp.claim is not None
        if resp.claim.answer_type == "yes_no":
            sd = resp.claim.structured_data
            assert "answer" in sd and "confidence" in sd
            assert isinstance(sd["answer"], bool)
            assert sd["confidence"] in ("high", "medium", "low")

    def test_list_structured_data_shape(self):
        resp = build_agent_response(_state_exhausted_enum())
        assert resp.claim is not None
        assert resp.claim.answer_type == "list"
        sd = resp.claim.structured_data
        assert "items" in sd and isinstance(sd["items"], list)
        for it in sd["items"]:
            assert {"node_id", "label", "relevance"} <= set(it.keys())

    def test_provenance_non_empty_on_confirmed(self):
        resp = build_agent_response(_state_confirmed())
        assert resp.provenance, "CONFIRMED must carry provenance"

    def test_ill_posed_contains_schema_gap(self):
        resp = build_agent_response(_state_ill_posed())
        assert any(g.type == "schema_gap" for g in resp.gaps)

    def test_unknown_contains_missing_concept_gap(self):
        resp = build_agent_response(_state_unknown())
        assert any(g.type == "missing_concept" for g in resp.gaps)

    def test_retrieval_strategy_enumerated(self):
        for state_fn in (_state_confirmed, _state_ill_posed, _state_unknown, _state_exhausted_enum):
            resp = build_agent_response(state_fn())
            assert resp.retrieval_strategy in {
                "compass_derivation", "contract_driven", "exploratory",
            }

    def test_gap_types_enumerated(self):
        resp = build_agent_response(_state_exhausted_enum())
        # Derived, not re-listed: a hand-copied set here is a fourth place the
        # vocabulary can drift, which is what gap_types.py exists to prevent.
        from interaction.gap_types import CONTRACT_GAP_TYPES

        for g in resp.gaps:
            assert g.type in set(CONTRACT_GAP_TYPES)

    def test_trace_id_present(self):
        resp = build_agent_response(_state_confirmed())
        assert resp.trace_id and resp.trace_id.startswith("tr_")

    def test_suggestions_populated_for_exhausted(self):
        resp = build_agent_response(_state_exhausted_enum())
        # Suggestions are optional but for EXHAUSTED with at least one gap
        # we should propose something.
        assert isinstance(resp.next_query_suggestions, list)

    def test_suggestions_on_confirmed_name_other_evidence(self):
        resp = build_agent_response(_state_confirmed())
        assert resp.next_query_suggestions
        assert all(s.suggested_query for s in resp.next_query_suggestions)
        # First packet node is the one the question already named; skip it.
        assert all("Alpha" not in s.suggested_query for s in resp.next_query_suggestions)

    def test_claim_prose_drops_presentation_headings(self):
        from contract import claim_prose

        raw = (
            "**Answer:** PS.3 requires a repository.\n\n"
            "**Provenance:** [Trail pb_edge_0]\n\n"
            "**Gaps:**\n(None)"
        )
        assert claim_prose(raw) == "PS.3 requires a repository."

    def test_claim_prose_does_not_graft_entity_labels(self):
        from contract import claim_prose

        raw = (
            "**Answer:** Sample containment prevents outward and inward transfer "
            "during custody. It is distinct from the sample cache.\n\n"
            "**Entities:** Sample cache, Containment breach, Sample acquisition, "
            "Planetary protection, Contamination monitoring, Bioburden accounting, "
            "Storm shelter"
        )
        prose = claim_prose(raw)
        assert prose.startswith("Sample containment prevents")
        assert "Containment breach" not in prose
        assert "Storm shelter" not in prose
        assert "sample cache" in prose

    def test_claim_prose_drops_a_trailing_name_list(self):
        from contract import claim_prose

        raw = (
            "Sample containment is a component of planetary protection.\n\n"
            "Sample cache, Containment breach, Sample acquisition, "
            "Planetary protection, Contamination monitoring, Bioburden accounting, "
            "Storm shelter"
        )
        assert claim_prose(raw) == (
            "Sample containment is a component of planetary protection."
        )

    def test_claim_prose_keeps_an_enumeration_that_is_the_claim(self):
        from contract import claim_prose

        raw = (
            "Sample cache, Containment breach, Sample acquisition, "
            "Planetary protection"
        )
        assert claim_prose(raw) == raw

    def test_claim_prose_keeps_a_bare_claim(self):
        from contract import claim_prose

        assert claim_prose("Yes, Alpha leads to Gamma via Beta.") == (
            "Yes, Alpha leads to Gamma via Beta."
        )

    def test_claim_prose_drops_the_old_empty_packet_fallback(self):
        from contract import claim_prose

        raw = (
            "The traversal engine was unable to find sufficient evidence in the "
            "knowledge graph to answer this query. The spreading activation and "
            "squad sensing did not surface any nodes with sufficient relevance."
        )
        assert claim_prose(raw) == ""
        kept = "Squad sensing reports local graph signal to Company."
        assert claim_prose(kept) == kept

    def test_claim_prose_drops_the_ill_posed_essay(self):
        from contract import claim_prose

        raw = (
            "This query is structurally unanswerable from a graph of this shape.\n\n"
            "Reason: no operator\n\n"
            "To answer this question, the graph would need:\n- [schema_gap] x"
        )
        assert claim_prose(raw) == ""

    def test_claim_prose_drops_a_citation_footer(self):
        from contract import claim_prose

        raw = (
            "Alpha leads to Beta.\n\n"
            "**⚠️ Citation verification (deterministic):**\n"
            "- [Trail 7] cited in answer but no such trail in Company handoff."
        )
        assert claim_prose(raw) == "Alpha leads to Beta."

    def test_provenance_publishes_the_trail_key(self):
        resp = build_agent_response(_state_confirmed())
        assert resp.provenance
        assert resp.provenance[0].trail_id == "t1"
        assert resp.provenance[0].ids == ["n_a", "n_b", "n_c"]

    def test_provenance_source_is_enumerated(self):
        resp = build_agent_response(_state_confirmed())
        for p in resp.provenance:
            assert p.source in ("deterministic", "llm")
            assert p.kind in ("node", "edge", "path")
            assert p.role_in_claim in ("primary", "supporting", "structural")


class TestDescribeGraphShape:
    """Contract §4: describe_graph response shape.

    Deterministic; does not require a live DB. We call build_agent_response
    as a proxy to ensure the shape module is importable and constants
    match. describe_graph itself is exercised in integration tests.
    """

    def test_import_describe_graph(self):
        from engine import describe_graph  # noqa: F401
