"""v7 Phase 6 — Pipeline A (Map Reader) tests.

Single-call answer; no Backend, no downstream tiers.
"""

from __future__ import annotations

from pipeline_a import compass_derivation_respond


def test_pipeline_a_lifts_planner_answer_to_final():
    state = {
        "query": "what is in the graph?",
        "planner_route": "compass_derivation",
        "map_reader_output": {
            "answer_text": "The graph contains 5 nodes about microservices.",
            "cited_node_ids": ["svc_gateway", "svc_auth"],
            "basis_layer": "L1+L2",
        },
        "degradation_flags": [],
    }
    out = compass_derivation_respond(state)
    assert out["final_answer"] == "The graph contains 5 nodes about microservices."
    assert out["provenance"][0]["tier"] == "compass_derivation"
    assert "svc_gateway" in out["provenance"][0]["cited_node_ids"]
    assert out["confirmation_response"]["verdict"] == "CONFIRMED"
    # No empty-answer flag (v8 may still add compass_derivation_*
    # structural notes when no compass is present in the state).
    flags = out.get("degradation_flags") or []
    assert "map_reader_empty_answer" not in flags


def test_pipeline_a_empty_answer_flagged_with_placeholder():
    state = {
        "query": "structural?",
        "planner_route": "compass_derivation",
        "map_reader_output": {"answer_text": "   "},  # whitespace-only
        "degradation_flags": [],
    }
    out = compass_derivation_respond(state)
    assert out["final_answer"] == ""
    assert "map_reader_empty_answer" in out["degradation_flags"]


def test_pipeline_a_passes_through_basis_layer():
    state = {
        "query": "?",
        "planner_route": "compass_derivation",
        "map_reader_output": {
            "answer_text": "answer",
            "cited_node_ids": [],
            "basis_layer": "L3",
        },
        "degradation_flags": [],
    }
    out = compass_derivation_respond(state)
    assert "compass_layers:L3" in out["provenance"][0]["basis"]
