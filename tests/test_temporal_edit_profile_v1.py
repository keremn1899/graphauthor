from __future__ import annotations

import json

from benchmarks.proposal_host.temporal_edit_profile_v1 import (
    in_force_at,
    proposal_profile_gate,
    run,
)


def test_temporal_edit_profile_passes_zero_model(tmp_path):
    output = tmp_path / "temporal"

    report = run(output)

    assert report["overall"] == "PASS"
    assert report["passed"] == report["total"] == 8
    assert report["model_calls"] == 0
    assert all(report["checks"].values())
    assert (output / "edge_only/graph.lbug").exists()
    assert (output / "event_node/graph.lbug").exists()
    assert json.loads((output / "report.json").read_text())["overall"] == "PASS"


def test_point_in_time_read_fails_closed_outside_known_interval(tmp_path):
    output = tmp_path / "temporal"
    run(output)

    result = in_force_at(
        output / "event_node/graph.lbug",
        "abstract_sequence_default",
        "2023-01-01T00:00:00Z",
    )

    assert result["kind"] == "NO_IN_FORCE_DECISION"
    assert result["safe_to_act"] is False


def test_implementation_only_profile_rejects_graph_truth():
    refusal = proposal_profile_gate("implementation_only", 1)

    assert refusal["allowed"] is False
    assert refusal["error_code"] == "GRAPH_DELTA_NOT_JUSTIFIED"
