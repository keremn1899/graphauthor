"""Adversarial interval reads over a multi-series decision graph (V1.1).

V1 declared AMBIGUOUS_TEMPORAL_OVERLAP and a `problems` vocabulary but built
only clean two-version series, so those paths were never entered. These tests
pin the safety properties strictly, and separately lock the two reporting
behaviours the protocol recorded without deciding — so that changing either is
a deliberate act rather than a silent drift.
"""

from __future__ import annotations

import json

from benchmarks.proposal_host.temporal_edit_profile_v1 import (
    in_force_at,
    validate_intervals,
)
from benchmarks.proposal_host.temporal_overlap_profile_v1_1 import run


def test_adversarial_interval_profile_passes_zero_model(tmp_path):
    report = run(tmp_path / "overlap")

    assert report["overall"] == "PASS"
    assert report["passed"] == report["total"] == 7
    assert report["model_calls"] == 0
    assert all(report["checks"].values())
    assert json.loads(
        (tmp_path / "overlap/report.json").read_text())["overall"] == "PASS"


def test_overlap_never_yields_a_confident_answer(tmp_path):
    run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    result = in_force_at(graph, "adjacent_overlap", "2024-09-01T00:00:00Z")

    assert result["kind"] == "AMBIGUOUS_TEMPORAL_OVERLAP"
    assert sorted(result["node_ids"]) == ["overlap_v1", "overlap_v2"]
    assert result["safe_to_act"] is False
    assert "node_id" not in result


def test_half_open_boundary_resolves_to_exactly_one_version(tmp_path):
    run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    before = in_force_at(graph, "boundary_instant", "2024-12-31T23:59:59Z")
    at = in_force_at(graph, "boundary_instant", "2025-01-01T00:00:00Z")

    assert before["node_id"] == "boundary_v1"
    assert at["node_id"] == "boundary_v2"
    assert at["kind"] == "IN_FORCE_AT_TIME"


def test_a_defective_series_does_not_contaminate_a_clean_one(tmp_path):
    """Every defective series lives in the same graph as clean_control."""
    report = run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    assert validate_intervals(graph, "clean_control")["valid"] is True
    assert in_force_at(
        graph, "clean_control", "2024-06-01T00:00:00Z")["node_id"] == "clean_v1"
    assert all(report["cross_series_control"]["matches_baseline"])


def test_two_open_ended_versions_are_an_overlap(tmp_path):
    run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    intervals = validate_intervals(graph, "two_open_ended")

    assert intervals["valid"] is False
    assert "overlap:openend_v1:openend_v2" in intervals["problems"]


def test_every_pair_implicated_in_a_failing_read_is_named(tmp_path):
    """DECIDED — was the §4.1 undecided lock; see backlog §16.88.

    The criterion is implication, not exhaustiveness-for-its-own-sake: any pair
    that an AMBIGUOUS_TEMPORAL_OVERLAP read can return together must appear in
    `problems`. Sorted-adjacent comparison used to report `long:mid` while the
    pair driving the read was `long:late`, so the diagnostic pointed away from
    the failure a repairer had just seen."""
    run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    intervals = validate_intervals(graph, "swallowing_interval")
    read = in_force_at(graph, "swallowing_interval", "2023-06-01T00:00:00Z")

    assert intervals["valid"] is False
    assert sorted(read["node_ids"]) == ["swallow_late", "swallow_long"]
    assert "overlap:swallow_long:swallow_late" in intervals["problems"]
    assert "overlap:swallow_long:swallow_mid" in intervals["problems"]
    # mid and late do not overlap each other and must not be named
    assert "overlap:swallow_mid:swallow_late" not in intervals["problems"]


def test_implication_holds_for_every_ambiguous_read_in_the_profile(tmp_path):
    """The general form of the criterion, over the whole fixture graph."""
    report = run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    checked = 0
    for entry in report["series"].values():
        for read in entry["reads"]:
            ids = read["result"].get("node_ids") or []
            if read["result"].get("kind") != "AMBIGUOUS_TEMPORAL_OVERLAP":
                continue
            problems = validate_intervals(graph, read["series_id"])["problems"]
            for first in ids:
                for second in ids:
                    if first == second:
                        continue
                    assert (f"overlap:{first}:{second}" in problems
                            or f"overlap:{second}:{first}" in problems)
                    checked += 1
    assert checked, "no ambiguous reads were exercised"


def test_recorded_gap_silence_is_locked_not_endorsed(tmp_path):
    """UNDECIDED BEHAVIOUR LOCK — see FINDINGS_TEMPORAL_OVERLAP_PROFILE_V1_1 §4.

    A four-year coverage gap is not a validity problem today. The read is
    correctly NO_IN_FORCE_DECISION, so nothing unsafe follows; whether a gap is
    a defect or a legitimate repeal-then-reintroduce history is undecided."""
    run(tmp_path / "overlap")
    graph = tmp_path / "overlap/graph/graph.lbug"

    intervals = validate_intervals(graph, "gap_reporting")
    read = in_force_at(graph, "gap_reporting", "2022-01-01T00:00:00Z")

    assert intervals["valid"] is True and intervals["problems"] == []
    assert read["kind"] == "NO_IN_FORCE_DECISION"
    assert read["safe_to_act"] is False
