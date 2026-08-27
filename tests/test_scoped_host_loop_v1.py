from __future__ import annotations

from benchmarks.external.cattrs_software.scoped_host_loop_v1 import (
    POLICIES,
    _ids,
    _load_frozen,
    _summary,
)


def test_scoped_loop_binding_has_two_selection_policies_and_three_arms():
    frozen, selection = _load_frozen()

    assert tuple(frozen["selection"]["context_policies"]) == POLICIES
    assert len(selection["selection_cases"]) == 5
    assert frozen["adjudication"]["arms"] == [
        "host_owned", "host_guarded", "server_owned"
    ]


def test_scope_output_parser_deduplicates_but_reports_duplicate():
    values, errors = _ids(
        {"scope_node_ids": ["converter_registry", "converter_registry"]},
        "scope_node_ids",
    )

    assert values == ["converter_registry"]
    assert errors == ["scope_node_ids_duplicate"]


def test_selection_summary_counts_cost_and_passes():
    rows = [{
        "score": {"passed": True, "cardinal_failure": False},
        "telemetry": {
            "model_calls": 2, "tool_calls": 1, "total_tokens": 300,
            "cost_usd": 0.02, "wall_ms": 10,
        },
    }]

    summary = _summary(rows)

    assert summary["passed"] == 1
    assert summary["model_calls"] == 2
    assert summary["tokens"] == 300
