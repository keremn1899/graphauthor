from __future__ import annotations

from benchmarks.host_retrieval.interface_ablation import (
    _catalogue,
    _integer_answer_matches,
    load_tasks,
    score_task,
)
from benchmarks.host_retrieval.trajectory_contract import ToolTurn, TrajectoryFinal


def test_frozen_interface_manifest_has_every_compact_operation_opportunity():
    tasks = load_tasks()
    assert len(tasks) == 18
    opportunities = {
        tool
        for task in tasks
        for tool in task.get("compact_opportunities") or []
    }
    assert {"lookup", "expand", "path", "search", "finish"} <= opportunities


def test_catalogues_are_small_vs_program_and_hash_instructions():
    compact = _catalogue("compact")
    program = _catalogue("program")
    assert compact.advertised_tools == ["lookup", "expand", "path", "search", "finish"]
    assert program.advertised_tools == ["retrieve", "finish"]
    assert compact.instruction_sha256 != program.instruction_sha256
    assert compact.instruction_chars > 0


def test_exact_answer_is_not_safe_when_it_was_never_observed():
    task = load_tasks()[0]
    score = score_task(
        task,
        arm="compact",
        final=TrajectoryFinal(
            selected_node_ids=["decision_current_retry"],
            status="ANSWERED",
            stopped=True,
        ),
        observed_ids=set(),
        tool_turns=[],
    )
    assert not score.task_passed
    assert score.false_authority
    assert not score.safe_success


def test_compact_unsupported_is_honest_but_not_task_success():
    task = next(task for task in load_tasks() if task["task_id"] == "E25_difference")
    score = score_task(
        task,
        arm="compact",
        final=TrajectoryFinal(status="UNSUPPORTED", stopped=True),
        observed_ids=set(),
        tool_turns=[],
    )
    assert score.terminal_honest
    assert not score.task_passed
    assert not score.safe_success


def test_search_after_exact_request_is_unsafe_widening():
    task = next(task for task in load_tasks() if task["task_id"] == "A04_exact_miss")
    score = score_task(
        task,
        arm="compact",
        final=TrajectoryFinal(status="EMPTY", stopped=True),
        observed_ids=set(),
        tool_turns=[ToolTurn(
            turn=1,
            tool="search",
            arguments={"query": "missing"},
            validation="accepted",
        )],
    )
    assert score.task_passed
    assert score.unsafe_widening
    assert not score.safe_success


def test_empty_answer_without_a_graph_call_is_false_authority():
    task = next(task for task in load_tasks() if task["task_id"] == "A04_exact_miss")
    score = score_task(
        task,
        arm="compact",
        final=TrajectoryFinal(status="EMPTY", stopped=True),
        observed_ids=set(),
        tool_turns=[],
    )
    assert not score.task_passed
    assert not score.evidence_grounded
    assert score.false_authority
    assert "no_graph_observation" in score.failures


def test_no_path_terminal_does_not_duplicate_boolean_in_optional_answer():
    task = next(
        task for task in load_tasks() if task["task_id"] == "C15_path_disconnected_empty"
    )
    score = score_task(
        task,
        arm="compact",
        final=TrajectoryFinal(status="NO_PATH", stopped=True),
        observed_ids={"diamond_start", "isolated_leaf"},
        tool_turns=[ToolTurn(
            turn=1,
            tool="path",
            arguments={
                "source_ids": ["diamond_start"],
                "target_ids": ["isolated_leaf"],
            },
            validation="accepted",
            result_outcome="EMPTY",
        )],
    )
    assert score.task_passed
    assert score.safe_success


def test_integer_answer_accepts_numeric_json_string_but_not_absence():
    assert _integer_answer_matches(2, 2)
    assert _integer_answer_matches("2", 2)
    assert not _integer_answer_matches(None, 2)
    assert not _integer_answer_matches(True, 1)


def test_candidate_search_cannot_prove_empty_global_enumeration():
    task = next(task for task in load_tasks() if task["task_id"] == "D20_enumerate_contains")
    score = score_task(
        task,
        arm="compact",
        final=TrajectoryFinal(status="EMPTY", stopped=True),
        observed_ids={"decision_current_retry"},
        tool_turns=[ToolTurn(
            turn=1,
            tool="search",
            arguments={"query": "contains"},
            validation="accepted",
            observed_node_ids=["decision_current_retry"],
        )],
    )
    assert not score.terminal_honest
    assert score.false_authority
    assert score.forbidden_tool_calls == 1
