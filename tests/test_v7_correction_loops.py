"""v7 Phase 4 — deterministic correction loops tests.

Covers Loop 1 (hypothesis grounding) and Loop 2 (tool dispatch validation).
No LLM calls. Operates on the deterministic fixtures.
"""

from __future__ import annotations

from correction_loops import (
    hypothesis_grounding_node,
    tool_dispatch_validation_node,
)


# ---------------------------------------------------------------------------
# Loop 1 — Hypothesis Grounding
# ---------------------------------------------------------------------------


def _base_state(**overrides):
    base = {
        "query": "test",
        "planner_route": "exploratory",
        "planner_program": {},
        "evidence_packet": {},
        "structural_index": {},
        "compass": {"graph_profile": {"node_count": 10}},
        "degradation_flags": [],
        "reseed_attempted": False,
    }
    base.update(overrides)
    return base


def test_loop1_skips_when_compass_derivation_route(deps_conn):
    state = _base_state(planner_route="compass_derivation")
    out = hypothesis_grounding_node(state, deps_conn)
    result = out["hypothesis_grounding_result"]
    assert result["proceed"] is True
    assert result["origin"] == "compass_derivation"
    assert result["verified_ids"] == []
    assert result["missing_ids"] == []
    assert "degradation_flags" not in out


def test_loop1_all_verified_proceeds_without_flag(deps_conn):
    # Pick a term we know exists — dependencies fixture seeds at least one node
    # whose label is resolvable via exact_node_lookup. Enumerate to find one.
    from tools import get_all_node_ids
    ids = get_all_node_ids(deps_conn)
    assert ids, "fixture must contain at least one node"
    known_id = ids[0]["id"] if isinstance(ids[0], dict) else ids[0]

    state = _base_state(
        planner_route="exploratory",
        planner_program={
            "strategy_a": {"concepts": [known_id]},
            "strategy_b": {"concepts": []},
        },
    )
    out = hypothesis_grounding_node(state, deps_conn)
    result = out["hypothesis_grounding_result"]
    assert result["proceed"] is True
    assert known_id in result["verified_terms"]
    assert result["missing_ids"] == []
    # No flag added on full verification.
    assert "degradation_flags" not in out


def test_loop1_full_miss_triggers_reseed(deps_conn):
    state = _base_state(
        planner_route="exploratory",
        planner_program={
            "strategy_a": {"concepts": ["definitely_not_a_real_node_xyz_123"]},
            "strategy_b": {"concepts": []},
        },
    )
    out = hypothesis_grounding_node(state, deps_conn)
    result = out["hypothesis_grounding_result"]
    assert result["proceed"] is False
    assert "hypothesis_full_miss" in out["degradation_flags"]


def test_loop1_partial_miss_flags_but_proceeds(deps_conn):
    from tools import get_all_node_ids
    ids = get_all_node_ids(deps_conn)
    known_id = ids[0]["id"] if isinstance(ids[0], dict) else ids[0]

    state = _base_state(
        planner_route="exploratory",
        planner_program={
            "strategy_a": {"concepts": [known_id, "definitely_not_a_real_node"]},
            "strategy_b": {"concepts": []},
        },
    )
    out = hypothesis_grounding_node(state, deps_conn)
    result = out["hypothesis_grounding_result"]
    assert result["proceed"] is True
    assert "hypothesis_partial_grounding" in out["degradation_flags"]
    assert known_id in result["verified_terms"]
    assert "definitely_not_a_real_node" in result["missing_ids"]


def test_loop1_respects_reseed_cap(deps_conn):
    """After one reseed, a still-missing term no longer triggers another."""
    state = _base_state(
        planner_route="exploratory",
        planner_program={
            "strategy_a": {"concepts": ["definitely_not_a_real_node_xyz_123"]},
            "strategy_b": {"concepts": []},
        },
        reseed_attempted=True,
    )
    out = hypothesis_grounding_node(state, deps_conn)
    result = out["hypothesis_grounding_result"]
    # Second pass must proceed even on full miss.
    assert result["proceed"] is True


def test_loop1_targeted_route_uses_source_ids(deps_conn):
    from tools import get_all_node_ids
    ids = get_all_node_ids(deps_conn)
    known_id = ids[0]["id"] if isinstance(ids[0], dict) else ids[0]

    state = _base_state(
        planner_route="targeted_retrieval",
        relational_contract={"source_ids": [known_id]},
    )
    out = hypothesis_grounding_node(state, deps_conn)
    result = out["hypothesis_grounding_result"]
    assert result["origin"] == "relational_contract"
    assert result["proceed"] is True
    assert known_id in result["verified_terms"]


# ---------------------------------------------------------------------------
# Loop 2 — Tool Dispatch Validation
# ---------------------------------------------------------------------------


def test_loop2_flags_structural_intent_without_structural_tool():
    state = _base_state(
        planner_program={
            "structural_intent": "centrality",
            "steps": [
                {"tool": "vector_search", "params": {"query_text": "x"}, "assign_to": "v1"},
            ],
        },
        evidence_packet={"node_records": [{"id": "n1"}]},
    )
    out = tool_dispatch_validation_node(state)
    validation = out["tool_dispatch_validation_result"]
    assert "structural_intent_without_structural_tool" in validation["mismatches"]
    assert any("tool_dispatch_mismatch" in f for f in out["degradation_flags"])
    assert validation["replan_required"] is True


def test_loop2_structural_tool_satisfies_intent():
    state = _base_state(
        planner_program={
            "structural_intent": "centrality",
            "steps": [
                {
                    "tool": "get_structural_profile",
                    "params": {"role": "centrality", "top_n": 5},
                    "assign_to": "s1",
                },
            ],
        },
        evidence_packet={"node_records": [{"id": "n1"}]},
    )
    out = tool_dispatch_validation_node(state)
    validation = out["tool_dispatch_validation_result"]
    assert "structural_intent_without_structural_tool" not in validation["mismatches"]


def test_loop2_flags_empty_packet_in_populated_graph():
    state = _base_state(
        planner_program={
            "structural_intent": "null",
            "steps": [
                {"tool": "vector_search", "params": {"query_text": "x"}, "assign_to": "v1"},
            ],
        },
        evidence_packet={"node_records": [], "edge_records": [], "path_records": []},
        compass={"graph_profile": {"node_count": 50}},
    )
    out = tool_dispatch_validation_node(state)
    validation = out["tool_dispatch_validation_result"]
    assert "empty_packet_in_populated_graph" in validation["mismatches"]


def test_loop2_no_flag_when_packet_populated_and_intent_matched():
    state = _base_state(
        planner_program={
            "structural_intent": "null",
            "steps": [
                {"tool": "vector_search", "params": {"query_text": "x"}, "assign_to": "v1"},
            ],
        },
        evidence_packet={"node_records": [{"id": "n1"}]},
    )
    out = tool_dispatch_validation_node(state)
    validation = out["tool_dispatch_validation_result"]
    assert validation["mismatches"] == []
    assert validation["replan_required"] is False
    assert "degradation_flags" not in out


def test_loop2_replan_capped_after_reseed_attempted():
    state = _base_state(
        planner_program={
            "structural_intent": "centrality",
            "steps": [
                {"tool": "vector_search", "params": {"query_text": "x"}, "assign_to": "v1"},
            ],
        },
        evidence_packet={"node_records": [{"id": "n1"}]},
        reseed_attempted=True,
    )
    out = tool_dispatch_validation_node(state)
    validation = out["tool_dispatch_validation_result"]
    # Mismatch still detected, but replan is not required (cap reached).
    assert "structural_intent_without_structural_tool" in validation["mismatches"]
    assert validation["replan_required"] is False
