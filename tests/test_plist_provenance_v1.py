from benchmarks.external.cattrs_software.plist_provenance_v1 import (
    _load_frozen, _segments, _source_rows, _strengthened_case,
)


def test_plist_probe_reuses_exact_saved_packet_and_strengthens_tuple_authority():
    frozen, source = _load_frozen()
    selection, server = _source_rows(frozen, source)
    case = _strengthened_case(frozen)

    assert len(selection["compiled"]["compiled_packet_ids"]) == 8
    assert server["arm"] == "server_owned"
    assert set(case["required_applying_policy_ids"]) == {
        "decision_current_serializer_behavior_lives_in_preconf",
        "decision_current_sequence_structures_to_tuple",
    }


def test_segmentation_keeps_explicit_and_adjacent_candidates_distinct():
    frozen, source = _load_frozen()
    selection, _ = _source_rows(frozen, source)
    nodes = [{"id": node_id} for node_id in selection["compiled"]["compiled_packet_ids"]]

    segments = _segments(selection, nodes)

    explicit = {row["id"] for row in segments["explicit_query_relevant_candidates_neutral"]}
    adjacent = {row["id"] for row in segments["adjacent_scope_compiled_candidates_neutral"]}
    assert "decision_current_sequence_structures_to_tuple" in explicit
    assert "decision_current_edge_concerns_stay_out_of_models" in adjacent
    assert explicit.isdisjoint(adjacent)
