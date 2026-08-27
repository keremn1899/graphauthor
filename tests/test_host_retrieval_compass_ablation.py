from __future__ import annotations

import json

from benchmarks.host_retrieval.compass_ablation import (
    DEFAULT_TASKS,
    _evidence_node_ids,
    _score,
)
from benchmarks.host_retrieval.tool_loop import _score as score_tool_loop
from benchmarks.host_retrieval.governance_ablation import _score as score_governance


def test_compass_ablation_task_set_is_frozen_and_covers_product_shapes():
    payload = json.loads(DEFAULT_TASKS.read_text(encoding="utf-8"))
    assert payload["status"] == "frozen_before_live_calls"
    tasks = payload["tasks"]
    assert len(tasks) == 8
    assert {task["shape"] for task in tasks} == {
        "exact_lookup",
        "containment",
        "known_chain",
        "architectural_boundary",
        "enumeration",
        "completeness",
        "genuine_gap",
        "distractor_resistance",
    }


def test_evidence_identity_reads_every_direct_projection_shape():
    assert _evidence_node_ids({
        "node_ids": ["summary"],
        "node_records": [{"id": "packet"}],
        "node_payloads": [{"id": "content"}],
    }) == ["content", "packet", "summary"]


def test_score_requires_identity_and_rejects_forbidden_or_false_gap():
    task = {
        "required_decision_ids": ["decision_required"],
        "forbidden_decision_ids": ["decision_forbidden"],
    }
    passed = _score(task, {"node_ids": ["component", "decision_required"]})
    assert passed["passed"] is True

    failed = _score(task, {
        "node_ids": ["decision_forbidden", "decision_unrelated"]
    })
    assert failed["passed"] is False
    assert failed["missing_required"] == ["decision_required"]
    assert failed["forbidden_present"] == ["decision_forbidden"]

    gap = _score(
        {
            "required_decision_ids": [],
            "forbidden_decision_ids": [],
            "expect_no_decisions": True,
        },
        {"node_ids": ["decision_adjacent"]},
    )
    assert gap["empty_ok"] is False
    assert gap["passed"] is False


def test_tool_loop_score_separates_observation_selection_and_grounding():
    task = {
        "required_decision_ids": ["decision_required"],
        "forbidden_decision_ids": ["decision_forbidden"],
    }
    selected = score_tool_loop(
        task,
        {"decision_ids": ["decision_required"]},
        {"decision_required", "decision_forbidden"},
    )
    assert selected["required_observed"] == 1
    assert selected["required_selected"] == 1
    assert selected["passed"] is True

    hallucinated = score_tool_loop(
        task,
        {"decision_ids": ["decision_required", "decision_unseen"]},
        {"decision_required"},
    )
    assert hallucinated["ungrounded_selected"] == ["decision_unseen"]
    assert hallucinated["passed"] is False


def test_governance_score_makes_false_governed_cardinal():
    case = {
        "expected_verdict": "UNGOVERNED",
        "required_policy_ids": [],
    }
    failed = score_governance(
        case,
        {
            "governance_verdict": "GOVERNED",
            "adjudications": [{
                "policy_id": "decision_adjacent",
                "conformance_ruling": "CONFORMS",
            }],
        },
        [],
    )
    assert failed["false_governed"] is True
    assert failed["passed"] is False
