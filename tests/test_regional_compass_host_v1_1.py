from __future__ import annotations

import json

from benchmarks.host_retrieval.regional_compass_host_v1_1 import (
    CostBudget,
    _load_cases,
    _mechanism_gate,
    _protocol,
    run_case,
)


def test_v1_1_protocol_and_controls_are_hash_bound():
    protocol = _protocol()
    cases = _load_cases()
    assert protocol["status"] == "frozen_before_runner_implementation_or_live_calls"
    assert len(cases) == 6
    assert sum(case["cross_region"] for case in cases) == 3
    assert {case["task_id"] for case in cases if case["cross_region"]} == {
        "enumeration:migration-status",
        "pulse:retry-and-outcome-violate",
        "pulse:dependency-direction-violate",
    }


def test_cost_budget_stops_admitting_before_declared_limit():
    budget = CostBudget(limit=0.75, stop_before=0.70)
    budget.record(0.69)
    assert budget.admit() is True
    budget.record(0.01)
    assert budget.admit() is False
    assert budget.exceeded is False
    budget.record(0.051)
    assert budget.exceeded is True


def test_mechanism_gate_requires_useful_cross_region_adoption():
    def row(arm: str, *, regional_calls: int = 0, useful: int = 0):
        return {
            "arm": arm,
            "completed": True,
            "cross_region": regional_calls > 0,
            "score": {
                "passed": True,
                "required_observed": 1,
                "required_selected": 1,
                "required_total": 1,
                "forbidden_selected_ids": [],
                "ungrounded_selected_ids": [],
                "exact_gap_ok": True,
            },
            "telemetry": {
                "regional_tool_calls": regional_calls,
                "useful_regional_ids": ["required"] if useful else [],
                "total_tokens": 100,
                "model_calls": 1,
                "tool_calls": 1,
                "invalid_calls": 0,
                "typed_refusals": 0,
                "typed_refusals_recovered": 0,
                "navigation_offered": 1 if arm == "linked_regional" else 0,
                "navigation_chars": 100 if arm == "linked_regional" else 0,
                "navigation_cold": 0,
                "navigation_warm": 0,
                "navigation_elapsed_ms": 0,
                "input_tokens": 80,
                "output_tokens": 20,
                "cost_usd": 0.001,
                "model_wall_seconds": 1,
            },
        }

    rows = [row("bare") for _ in range(6)] + [row("global") for _ in range(6)]
    rows += [row("linked_regional") for _ in range(6)]
    passed, reasons = _mechanism_gate(rows)
    assert passed is False
    assert set(reasons) == {
        "no_cross_region_continuation_followed",
        "no_required_id_first_observed_via_region",
    }

    rows[-1] = row("linked_regional", regional_calls=1, useful=1)
    assert _mechanism_gate(rows) == (True, [])


def test_linked_runner_preserves_navigation_and_region_observation(monkeypatch):
    replies = iter(
        [
            {"tool": "lookup", "references": ["Seed"], "include_content": True},
            {"tool": "region", "region_id": "region_a"},
            {"final": {"evidence_node_ids": ["required"], "reason": "found"}},
        ]
    )

    def fake_call(_model, _messages):
        parsed = next(replies)
        return {
            "raw": json.dumps(parsed),
            "parsed": parsed,
            "elapsed_seconds": 0.01,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "response_metadata": {"token_usage": {"cost": 0.001}},
        }

    class FakeHost:
        def lookup(self, _references, **_kwargs):
            return {
                "outcome": "FOUND",
                "evidence": {
                    "node_records": [{"id": "seed", "label": "Seed"}],
                    "node_payloads": [],
                    "edge_records": [],
                    "path_records": [],
                },
                "execution_receipt": {"collected_node_count": 1},
                "navigation": {
                    "kind": "regional",
                    "index_ref": "index",
                    "node_regions": {"seed": "region_a"},
                    "continuations": [{"tool": "region", "region_id": "region_a"}],
                    "receipt": {
                        "index_cache_hit": False,
                        "elapsed_ms": 2.0,
                        "serialized_chars": 200,
                    },
                },
            }

        def region(self, _region_id, **_kwargs):
            return {
                "outcome": "FOUND",
                "member_ids": ["seed", "required"],
                "boundary_edges": [],
                "membership_page": {"complete": True},
                "boundary_page": {"complete": True},
            }

    monkeypatch.setattr(
        "benchmarks.host_retrieval.regional_compass_host_v1_1._call", fake_call
    )
    budget = CostBudget(limit=0.75, stop_before=0.70)
    result = run_case(
        {
            "graph": "cattrs",
            "task_id": "test:linked",
            "shape": "test",
            "prompt": "Find required from Seed.",
            "required_ids": ["required"],
            "forbidden_ids": [],
            "exact_gap": False,
            "cross_region": True,
        },
        "linked_regional",
        FakeHost(),
        "",
        budget,
    )
    assert result["score"]["passed"] is True
    assert result["telemetry"]["navigation_offered"] == 1
    assert result["telemetry"]["navigation_cold"] == 1
    assert result["telemetry"]["regional_tool_calls"] == 1
    assert result["telemetry"]["useful_regional_ids"] == ["required"]
    assert result["telemetry"]["complete_region_reads"] == 1
    assert budget.cost_usd == 0.003
