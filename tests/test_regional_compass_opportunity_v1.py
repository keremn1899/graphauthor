from __future__ import annotations

from benchmarks.host_retrieval.regional_compass_opportunity_v1 import analyze


def test_offline_opportunity_projection_finds_cross_region_cases(tmp_path):
    report = analyze(tmp_path)
    assert report["model_calls"] == 0
    assert report["summary"] == {
        "task_count": 15,
        "cross_region_task_count": 7,
        "cross_region_by_graph": {"cattrs": 1, "pulse": 6},
        "max_required_region_count": 3,
    }
    assert all(not row["missing_node_ids"] for row in report["rows"])

    dependency = next(
        row
        for row in report["rows"]
        if row["task_id"] == "pulse:dependency-direction-violate"
    )
    assert dependency["required_region_count"] == 3
    assert set(dependency["node_regions"]) == {
        "dependency_direction_rule",
        "domain_layer",
        "persistence_layer",
    }
