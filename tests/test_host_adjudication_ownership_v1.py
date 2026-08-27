from __future__ import annotations

from benchmarks.external.cattrs_software.host_adjudication_ownership_v1 import (
    _load_frozen,
    _server_cardinal,
    _summaries,
)


def test_ownership_binding_covers_exact_v1_1_cases_and_contexts():
    frozen, cases, contexts = _load_frozen()

    assert frozen["arms"] == ["host_owned", "host_guarded", "server_owned"]
    assert len(cases) == 6
    assert len(contexts) == 6
    assert [row["task_id"] for row in cases[:2]] == frozen["control_task_ids"]
    assert [row["task_id"] for row in cases[2:]] == frozen["remaining_task_ids"]
    assert all(contexts[row["task_id"]]["mixed_context"] for row in cases)


def test_server_cardinal_includes_contract_and_path_failures():
    assert _server_cardinal(
        {"failures": ["closure_contract_mismatch"]}, {}
    ) is True
    assert _server_cardinal(
        {"failures": ["unexpected_execution_path"]}, {}
    ) is True
    assert _server_cardinal(
        {"failures": ["kind_mismatch"]}, {}
    ) is False


def test_summary_counts_guard_as_zero_cost_derived_row():
    rows = [
        {
            "arm": "host_owned",
            "score": {"passed": True, "cardinal_failure": False},
            "telemetry": {
                "model_calls": 1, "tool_calls": 0, "total_tokens": 100,
                "cost_usd": 0.01, "wall_ms": 10,
            },
        },
        {
            "arm": "host_guarded",
            "score": {"passed": True, "cardinal_failure": False},
            "telemetry": {
                "model_calls": 0, "tool_calls": 0, "total_tokens": 0,
                "cost_usd": 0.0, "wall_ms": 0,
            },
        },
        {
            "arm": "server_owned",
            "score": {"passed": True, "cardinal_failure": False},
            "telemetry": {
                "model_calls": 1, "tool_calls": 0, "total_tokens": 200,
                "cost_usd": 0.02, "wall_ms": 20,
            },
        },
    ]

    summary = _summaries(rows)

    assert summary["host_guarded"]["model_calls"] == 0
    assert summary["paid_total"]["model_calls"] == 2
    assert summary["paid_total"]["tokens"] == 300
    assert summary["paid_total"]["cost_usd"] == 0.03
