from __future__ import annotations

from benchmarks.host_retrieval.path_endpoint_feedback_v1 import audit


def test_path_endpoint_feedback_matrix_passes_through_mcp(tmp_path):
    report = audit(tmp_path)
    assert report["model_calls"] == 0
    assert report["summary"]["mechanism_gate_passed"] is True
    assert set(report["summary"]["historical_outcomes"].values()) == {
        "EMPTY",
        "FOUND",
    }

    rows = {
        (row["arm"], row["case_id"]): row
        for row in report["rows"]
    }
    assert rows[("historical", "missing_source")]["outcome"] == "EMPTY"
    assert rows[("historical", "known_no_path")]["outcome"] == "EMPTY"

    source = rows[("resolved_endpoints", "missing_source")]
    assert source["outcome"] == "UNRESOLVED_ENDPOINT"
    assert source["endpoint_resolution"]["unresolved_source_ids"] == [
        "definitely_missing"
    ]
    assert source["endpoint_resolution"]["unresolved_target_ids"] == []

    target = rows[("resolved_endpoints", "missing_target")]
    assert target["endpoint_resolution"]["unresolved_source_ids"] == []
    assert target["endpoint_resolution"]["unresolved_target_ids"] == [
        "definitely_missing"
    ]
    assert rows[("resolved_endpoints", "known_no_path")]["outcome"] == "EMPTY"
    assert rows[("resolved_endpoints", "known_path")]["outcome"] == "FOUND"
