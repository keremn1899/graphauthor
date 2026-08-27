"""The bounded judgment view must never become lossy retrieval truth."""

from __future__ import annotations

from judgment_view import (
    build_judgment_view,
    packet_for_judgment,
    records_for_judgment,
)


def _packet(size: int = 24) -> dict:
    nodes = [
        {"id": f"noise_{i:02d}", "label": f"Unrelated account topic {i}"}
        for i in range(size)
    ]
    nodes[3] = {"id": "policy_exact", "label": "Exact governing return policy"}
    nodes[8] = {"id": "policy_prior", "label": "Receipt return rule"}
    nodes[12] = {"id": "query_match", "label": "Seasonal item returns"}
    return {
        "node_records": nodes,
        "edge_records": [
            {
                "source_id": "policy_exact",
                "target_id": "query_match",
                "edge_type": "contains",
            },
            {
                "source_id": "noise_00",
                "target_id": "noise_01",
                "edge_type": "nearto",
            },
        ],
        "path_records": [],
        "retrieval_program": {
            "steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": "policy_exact"},
                "assign_to": "seed",
            }]
        },
    }


def _state(**updates) -> dict:
    state = {
        "query": "Does the seasonal item return have a governing policy?",
        "verdict_space": "coverage",
        "planner_governing_candidates": [{"id": "policy_prior"}],
        "relational_contract": {"question_form": "lookup"},
    }
    state.update(updates)
    return state


def test_governance_lookup_builds_bounded_view_without_mutating_packet(monkeypatch):
    monkeypatch.setenv("SST_JUDGMENT_NODE_BUDGET", "6")
    packet = _packet()
    original_nodes = list(packet["node_records"])

    view = build_judgment_view(_state(), packet)
    packet["judgment_view"] = view
    projected = packet_for_judgment(packet)

    assert view["applied"] is True
    assert len(view["node_ids"]) <= 6
    assert {"policy_exact", "policy_prior", "query_match"}.issubset(view["node_ids"])
    assert packet["node_records"] == original_nodes
    assert len(packet["node_records"]) == 24
    assert len(projected["node_records"]) == len(view["node_ids"])
    selected = set(view["node_ids"])
    assert packet["edge_records"][0] in projected["edge_records"]
    assert all(
        edge["source_id"] in selected and edge["target_id"] in selected
        for edge in projected["edge_records"]
    )


def test_complete_question_forms_bypass_the_budget(monkeypatch):
    monkeypatch.setenv("SST_JUDGMENT_NODE_BUDGET", "4")
    packet = _packet()

    for question_form in ("enumeration", "fanout", "proof", "chain", "count"):
        view = build_judgment_view(
            _state(relational_contract={"question_form": question_form}), packet
        )
        assert view["applied"] is False
        assert view["node_ids"] == [n["id"] for n in packet["node_records"]]
        assert view["reason"] == f"complete_question_form:{question_form}"


def test_proof_path_is_never_split_even_when_it_exceeds_budget(monkeypatch):
    monkeypatch.setenv("SST_JUDGMENT_NODE_BUDGET", "3")
    packet = _packet()
    packet["path_records"] = [{
        "node_chain": ["noise_00", "noise_01", "noise_02", "policy_exact", "noise_04"],
        "edge_chain": ["leadsto"] * 4,
    }]

    view = build_judgment_view(_state(), packet)

    assert view["applied"] is True
    assert set(packet["path_records"][0]["node_chain"]).issubset(view["node_ids"])
    assert len(view["node_ids"]) >= 5


def test_non_governance_space_keeps_the_full_view(monkeypatch):
    monkeypatch.setenv("SST_JUDGMENT_NODE_BUDGET", "4")
    view = build_judgment_view(_state(verdict_space="confirmation"), _packet())
    assert view["applied"] is False
    assert view["reason"] == "verdict_space_not_governance"


def test_legacy_candidate_projection_tracks_selected_ids(monkeypatch):
    monkeypatch.setenv("SST_JUDGMENT_NODE_BUDGET", "5")
    packet = _packet()
    packet["judgment_view"] = build_judgment_view(_state(), packet)

    records = records_for_judgment(packet["node_records"], packet)

    assert [record["id"] for record in records] == packet["judgment_view"]["node_ids"]
