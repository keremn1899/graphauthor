from __future__ import annotations

import json

from benchmarks.host_retrieval.edge_semantics_audit_v1 import (
    audit_ill_posed,
    audit_retry_trajectories,
)


def test_ill_posed_audit_separates_false_refusal_from_real_gap(tmp_path):
    corpus = tmp_path / "tests/corpus"
    corpus.mkdir(parents=True)
    (corpus / "cases.yaml").write_text(
        """- id: answerable_case
  ground_truth:
    answerable: true
    expected_verdict: [CONFIRMED]
- id: gap_case
  ground_truth:
    answerable: false
    expected_verdict: [EXHAUSTED]
""",
        encoding="utf-8",
    )
    for case_id in ("answerable_case", "gap_case"):
        case_dir = tmp_path / "data/test_reports/corpus/run/cases" / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "state.json").write_text(
            json.dumps(
                {
                    "confirmation_response": {
                        "verdict": "ILL_POSED",
                        "ill_posed_reason": f"reason for {case_id}",
                    }
                }
            ),
            encoding="utf-8",
        )

    report = audit_ill_posed(tmp_path)

    assert report["ill_posed_occurrences"] == 2
    assert report["false_refusal_occurrences"] == 1
    assert report["false_refusal_unique_cases"] == 1
    cases = {row["case_id"]: row for row in report["cases"]}
    assert cases["answerable_case"]["false_refusal"] is True
    assert cases["gap_case"]["false_refusal"] is False


def test_retry_audit_does_not_invent_evidence_when_trajectories_lack_outcome(
    tmp_path,
):
    (tmp_path / "old.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "opportunity": {"task_id": "old_empty"},
                        "tool_turns": [{"result_outcome": "EMPTY"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit_retry_trajectories(tmp_path)

    assert report["unresolved_outcomes_observed_by_model"] == 0
    assert report["build_r5_from_current_evidence"] is False


def test_retry_audit_records_later_probe_when_evidence_exists(tmp_path):
    (tmp_path / "trajectory.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "opportunity": {"task_id": "recover"},
                        "tool_turns": [
                            {"tool": "expand", "result_outcome": "UNRESOLVED_SEED"},
                            {"tool": "search", "result_outcome": "CANDIDATES"},
                        ],
                        "final": {"status": "ANSWERED"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit_retry_trajectories(tmp_path)

    assert report["unresolved_outcomes_observed_by_model"] == 1
    assert report["build_r5_from_current_evidence"] is True
    assert report["hits"][0]["later_tools"] == ["search"]
