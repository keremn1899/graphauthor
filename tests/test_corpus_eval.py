"""Unit tests for `corpus_eval.evaluate_stage_a`.

Synthetic packet/state artifacts exercise each check independently so the
evaluator's correctness is decoupled from an actual engine run.
"""

from __future__ import annotations

import json
from pathlib import Path

from corpus_eval import evaluate_stage_a
from models import CorpusCase, CorpusGroundTruth, CorpusRubric


def _write_artifacts(
    case_dir: Path,
    *,
    packet: dict | None = None,
    state: dict | None = None,
    meta: dict | None = None,
    answer: str = "",
) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "packet.json").write_text(json.dumps(packet or {}), encoding="utf-8")
    (case_dir / "state.json").write_text(json.dumps(state or {}), encoding="utf-8")
    (case_dir / "meta.json").write_text(json.dumps(meta or {}), encoding="utf-8")
    (case_dir / "answer.md").write_text(answer, encoding="utf-8")


def _base_case(**overrides) -> CorpusCase:
    defaults = dict(
        id="t1",
        query="q",
        seed="lotr",
        query_class="enumeration",
    )
    defaults.update(overrides)
    return CorpusCase(**defaults)


def test_missing_artifacts_flagged_as_harness_run_missing(tmp_path: Path) -> None:
    case = _base_case()
    result = evaluate_stage_a(case, tmp_path / "cases" / "t1")
    assert not result.passed
    assert "harness_run_missing" in result.symptoms


def test_required_edge_types_missing(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(required_edge_types=["expresses"]),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={"edge_records": [{"source_id": "a", "target_id": "b", "edge_type": "leadsto"}]},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "required_edge_type_missing" in result.symptoms


def test_required_edge_types_present(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(required_edge_types=["expresses"]),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={"edge_records": [{"source_id": "a", "target_id": "b", "edge_type": "EXPRESSES"}]},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert result.passed, result.symptoms


def test_verdict_mismatch(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(expected_verdict=["CONFIRMED"]),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(case_dir, meta={"verdict": "EXHAUSTED"})
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "verdict_mismatch" in result.symptoms


def test_forbidden_gap_emitted(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_gap_types_forbidden=["missing_relationship"],
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        state={
            "company_handoff": {
                "internal_handoff": {
                    "gaps": [{"gap_type": "missing_relationship"}]
                }
            }
        },
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "forbidden_gap_emitted" in result.symptoms


def test_answer_must_not_contain(tmp_path: Path) -> None:
    case = _base_case(
        rubric=CorpusRubric(must_not_contain=["no expresses"]),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        answer="Sorry, no expresses edges were found in this graph.",
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "answer_forbidden_substring" in result.symptoms


def test_degradation_flags_allowed(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            degradation_flags_allowed=["semantic_warning:gap_specificity_unverified"],
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={"degradation_flags": ["semantic_violation:false_relation_denial"]},
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "degradation_unexpected" in result.symptoms


def test_min_edge_count(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(min_edge_count=3),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={"edge_records": [{"edge_type": "leadsto"}]},
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "packet_edge_underflow" in result.symptoms


def test_v8_retrieval_strategy_mismatch_hard_fails(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_retrieval_strategy="compass_derivation",
            strategy_is_hard_expectation=True,
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        state={"retrieval_strategy": "exploratory"},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "retrieval_strategy_mismatch" in result.symptoms
    assert result.retrieval_strategy == "exploratory"


def test_v8_retrieval_strategy_mismatch_soft_advisory(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_retrieval_strategy="compass_derivation",
            strategy_is_hard_expectation=False,
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        state={"retrieval_strategy": "exploratory"},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    # Soft: symptom recorded for reporting but does not fail the case.
    assert result.passed, result.symptoms
    assert "retrieval_strategy_mismatch" in result.symptoms


def test_v8_retrieval_strategy_legacy_route_translation(tmp_path: Path) -> None:
    """v7 `planner_route` names translate to v8 strategies."""
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_retrieval_strategy="compass_derivation",
            strategy_is_hard_expectation=True,
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        state={"planner_route": "map_reader"},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert result.passed, result.symptoms
    assert result.retrieval_strategy == "compass_derivation"


def test_v9_synthesis_mode_deprecated(tmp_path: Path) -> None:
    """v9: synthesis_mode is no longer enforced. Stage-A ignores mismatches."""
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_synthesis_mode="factual",
            strategy_is_hard_expectation=True,
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        state={"synthesis_mode": "synthesised"},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    # No synthesis_mode_mismatch symptom in v9.
    assert "synthesis_mode_mismatch" not in result.symptoms


def test_v8_compass_derivation_packet_underpopulated(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_retrieval_strategy="compass_derivation",
            strategy_is_hard_expectation=True,
            compass_landmark_count_expected=5,
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={"node_records": [{"id": "only_one"}]},
        state={"retrieval_strategy": "compass_derivation"},
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "compass_derivation_packet_underpopulated" in result.symptoms


def test_v8_ill_posed_vs_unknown_to_graph_mismatch(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(expected_verdict=["UNKNOWN_TO_GRAPH"]),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(case_dir, meta={"verdict": "ILL_POSED"})
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "unknown_to_graph_vs_ill_posed_mismatch" in result.symptoms


def test_v8_ill_posed_and_unknown_to_graph_both_acceptable(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            expected_verdict=["ILL_POSED", "UNKNOWN_TO_GRAPH"]
        ),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(case_dir, meta={"verdict": "UNKNOWN_TO_GRAPH"})
    result = evaluate_stage_a(case, case_dir)
    assert result.passed, result.symptoms


def test_v8_trail_orientation_violation(tmp_path: Path) -> None:
    """PathRecord walks A->B along LEADSTO but edge_records says B leadsto A."""
    case = _base_case()
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={
            "edge_records": [
                {"source_id": "b", "target_id": "a", "edge_type": "leadsto"},
            ],
            "path_records": [
                {"node_chain": ["a", "b"], "edge_chain": ["leadsto"]},
            ],
        },
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert not result.passed
    assert "trail_orientation_violation" in result.symptoms


def test_v8_trail_orientation_canonical_passes(tmp_path: Path) -> None:
    case = _base_case()
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={
            "edge_records": [
                {"source_id": "a", "target_id": "b", "edge_type": "leadsto"},
            ],
            "path_records": [
                {"node_chain": ["a", "b"], "edge_chain": ["leadsto"]},
            ],
        },
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert result.passed, result.symptoms


def test_v8_trail_orientation_nearto_undirected_no_violation(tmp_path: Path) -> None:
    """NEARTO is undirected; reversed node pair against the edge_record must
    not fire the orientation violation symptom."""
    case = _base_case()
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={
            "edge_records": [
                {"source_id": "b", "target_id": "a", "edge_type": "nearto"},
            ],
            "path_records": [
                {"node_chain": ["a", "b"], "edge_chain": ["nearto"]},
            ],
        },
        meta={"verdict": "CONFIRMED"},
    )
    result = evaluate_stage_a(case, case_dir)
    assert result.passed, result.symptoms


def test_all_passing_no_symptoms(tmp_path: Path) -> None:
    case = _base_case(
        ground_truth=CorpusGroundTruth(
            required_edge_types=["expresses"],
            required_node_ids_any=["char_frodo"],
            min_edge_count=1,
            expected_verdict=["CONFIRMED"],
            expected_gap_types_forbidden=["missing_relationship"],
        ),
        rubric=CorpusRubric(must_not_contain=["no expresses"]),
    )
    case_dir = tmp_path / "cases" / "t1"
    _write_artifacts(
        case_dir,
        packet={
            "edge_records": [
                {"source_id": "char_frodo", "target_id": "item_ring", "edge_type": "expresses"}
            ],
            "node_records": [{"id": "char_frodo"}, {"id": "item_ring"}],
        },
        state={"company_handoff": {"internal_handoff": {"gaps": []}}},
        meta={"verdict": "CONFIRMED"},
        answer="Frodo -> One Ring via expresses edge.",
    )
    result = evaluate_stage_a(case, case_dir)
    assert result.passed, result.symptoms
