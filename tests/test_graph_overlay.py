"""Overlays — the focus plane. Ids and roles, never geometry.

Deterministic: no database, no LLM. What is under test is the contract that
makes focus non-destructive, and the honesty of what it claims.
"""

from __future__ import annotations

import graph_overlay


def _edge(s, t, kind="LEADSTO"):
    return {"source": s, "target": t, "type": kind, "label": ""}


def test_an_overlay_carries_no_geometry():
    """The whole point: focus is an addition to the map, not a replacement. If
    an overlay could express a position it could fight the arrangement."""
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a"]}, [_edge("a", "b")], [], {"a", "b"}
    )
    blob = repr(overlay)
    for forbidden in ("'x'", '"x"', "'y'", '"y"'):
        assert forbidden not in blob
    assert set(overlay["nodes"]) <= {"a", "b"}


def test_evidence_is_lit_and_the_boundary_is_frontier():
    edges = [_edge("a", "b"), _edge("b", "c")]
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a", "b"]}, edges, [], {"a", "b", "c"}
    )
    # `b` touches `c`, which the answer did not use.
    assert overlay["nodes"]["b"] == "frontier"
    # `a` only touches `b`, which the answer did use.
    assert overlay["nodes"]["a"] == "lit"
    assert "c" not in overlay["nodes"]


def test_an_edge_lights_only_when_both_ends_were_used():
    edges = [_edge("a", "b"), _edge("b", "c")]
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a", "b"]}, edges, [], {"a", "b", "c"}
    )
    assert graph_overlay.edge_ref("a", "b", "LEADSTO") in overlay["edges"]
    assert graph_overlay.edge_ref("b", "c", "LEADSTO") not in overlay["edges"]


def test_a_gap_naming_nothing_real_is_left_unanchored():
    """Attaching a gap to a plausible-looking neighbour would fabricate an
    explanation of why an answer failed. Honest failure applies here too."""
    gaps = [
        {"type": "missing_relation", "specific_node_or_concept": "b",
         "actionable_suggestion": "add it"},
        {"type": "missing_node", "specific_node_or_concept": "not_a_node"},
        {"type": "vague"},
    ]
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a"]}, [_edge("a", "b")], gaps, {"a", "b"}
    )
    assert [g["anchor"] for g in overlay["gaps"]] == ["b"]
    assert len(overlay["unanchored_gaps"]) == 2


def test_evidence_ids_outside_the_map_are_dropped():
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a", "ghost_from_another_graph"]},
        [_edge("a", "b")],
        [],
        {"a", "b"},
    )
    assert set(overlay["nodes"]) == {"a"}


def test_evidence_is_read_from_records_as_well_as_ids():
    overlay = graph_overlay.evidence_overlay(
        {"node_records": [{"id": "a"}], "edge_records": [{"source": "a", "target": "b"}]},
        [_edge("a", "b")],
        [],
        {"a", "b"},
    )
    assert set(overlay["nodes"]) == {"a", "b"}


def test_diff_keeps_removed_nodes_so_a_ghost_has_a_role():
    overlay = graph_overlay.diff_overlay(
        before_ids=["a", "b"], after_ids=["a", "c"], touched_ids=["a"]
    )
    assert overlay["nodes"] == {"c": "added", "b": "removed", "a": "touched"}
    assert overlay["counts"] == {"added": 1, "removed": 1, "touched": 1}


def test_history_shows_a_past_state_as_a_subset_plus_ghosts():
    """Scrubbing must not re-lay-out — a timeline that moved the map would be
    unreadable, which is why the ledger keeps tombstones."""
    overlay = graph_overlay.history_overlay(
        present_ids=["a", "b", "gone"], current_ids=["a", "b", "new"]
    )
    assert overlay["nodes"] == {"a": "lit", "b": "lit", "gone": "ghost"}
    assert "new" not in overlay["nodes"]


def test_an_empty_evidence_payload_produces_an_empty_overlay():
    overlay = graph_overlay.evidence_overlay(None, [], [], set())
    assert overlay["nodes"] == {} and overlay["edges"] == {}
    assert overlay["counts"]["lit"] == 0


def test_frontier_is_withdrawn_when_everything_is_frontier():
    """Observed live on a six-node graph: both evidence nodes came back
    `frontier` and none came back `lit`. On a small or sparse graph every used
    node borders an unused one, so the word stops discriminating. Saying "this
    is where we ran out" about the whole answer overstates the boundary."""
    edges = [_edge("a", "x"), _edge("b", "y"), _edge("a", "b")]
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a", "b"]}, edges, [], {"a", "b", "x", "y"}
    )
    assert set(overlay["nodes"].values()) == {"lit"}
    assert overlay["frontier_saturated"] is True
    assert overlay["counts"]["frontier"] == 0


def test_a_real_boundary_is_still_reported():
    edges = [_edge("a", "b"), _edge("b", "c")]
    overlay = graph_overlay.evidence_overlay(
        {"node_ids": ["a", "b"]}, edges, [], {"a", "b", "c"}
    )
    assert overlay["frontier_saturated"] is False
    assert overlay["nodes"] == {"a": "lit", "b": "frontier"}


def test_a_confirmed_claim_does_not_light_unnamed_expand_neighbours():
    """Expand of a region dumps every child. Evidence is what the sentence
    stood on, not the whole retrieved neighbourhood."""
    evidence = {
        "node_records": [
            {"id": "bio", "label": "Bioburden accounting"},
            {"id": "log", "label": "Logistics and resources"},
            {"id": "prop", "label": "Propellant inventory"},
        ],
        "edge_records": [
            {"source": "bio", "target": "log"},
            {"source": "log", "target": "prop"},
        ],
    }
    edges = [
        _edge("bio", "log", "NEARTO"),
        _edge("log", "prop", "CONTAINS"),
    ]
    known = {"bio", "log", "prop"}
    whole = graph_overlay.evidence_overlay(evidence, edges, [], known)
    assert set(whole["nodes"]) == known
    overlay = graph_overlay.evidence_overlay(
        evidence,
        edges,
        [],
        known,
        claim_text=(
            "Bioburden accounting shares a broader operational context "
            "with Logistics and resources."
        ),
    )
    assert set(overlay["nodes"]) == {"bio", "log"}
    assert "prop" not in overlay["nodes"]


def test_a_path_stays_lit_even_when_an_intermediate_label_is_omitted():
    evidence = {
        "node_records": [
            {"id": "a", "label": "Alpha"},
            {"id": "b", "label": "Beta"},
            {"id": "c", "label": "Gamma"},
        ],
        "path_records": [{"node_chain": ["a", "b", "c"]}],
    }
    overlay = graph_overlay.evidence_overlay(
        evidence,
        [_edge("a", "b"), _edge("b", "c")],
        [],
        {"a", "b", "c"},
        claim_text="Alpha leads to Gamma.",
    )
    assert set(overlay["nodes"]) == {"a", "b", "c"}
