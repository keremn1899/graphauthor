"""Frozen deterministic layer of the host-retrieval query coverage moat."""

from __future__ import annotations

from benchmarks.host_retrieval.operator_matrix import (
    build_cases,
    load_graph_spec,
    run,
)


def test_operator_matrix_definition_matches_preregistration():
    spec = load_graph_spec()
    cases = build_cases(spec)

    assert len(cases) == 32
    assert {case["band"] for case in cases} == set("ABCDEFGHI")
    assert spec["deliberately_omitted_ids"] == [
        "decision_current_async_hook_contract"
    ]
    assert len(spec["nodes"]) == 23
    assert {edge["type"] for edge in spec["edges"]} == {
        "LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"
    }


def test_operator_matrix_closes_and_persists_inspectable_artifacts(tmp_path):
    report = run(tmp_path / "operator_matrix")

    assert report["summary"]["outcome"] == "OPERATOR_NUCLEUS_CLOSED"
    assert report["summary"]["rows"] == 32
    assert report["summary"]["passed"] == 32
    assert report["summary"]["outcome_counts"] == {
        "SUPPORTED_PASS": 30,
        "VALIDATION_REFUSAL": 2,
    }
    intersection = next(
        row for row in report["rows"]
        if row["case_id"] == "F26_intersection"
    )
    assert intersection["outcome"] == "SUPPORTED_PASS"
    assert intersection["collected_ids"] == ["diamond_join"]
    assert (tmp_path / "operator_matrix" / "report.json").exists()
    assert (tmp_path / "operator_matrix" / "graph_spec.json").exists()
    assert (tmp_path / "operator_matrix" / "sst_operator_motif_atlas.lbug").exists()
