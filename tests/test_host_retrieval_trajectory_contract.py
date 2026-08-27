from __future__ import annotations

import pytest
from pydantic import ValidationError

from benchmarks.host_retrieval.trajectory_contract import (
    CacheCondition,
    LatencyBreakdown,
    ModelCallUsage,
    ToolCatalogueSnapshot,
    ToolOpportunity,
    ToolTurn,
    TrajectoryFinal,
    TrajectoryRecord,
    TrajectoryScore,
    aggregate_trajectories,
    json_schema,
)


def _record(*, passed: bool, cost: float, wall: float) -> TrajectoryRecord:
    return TrajectoryRecord(
        arm="compact_host",
        model="model-a",
        repetition=1,
        opportunity=ToolOpportunity(
            task_id=f"task-{passed}",
            graph_id="atlas",
            graph_sha256="abc",
            operator_band="B",
            intent="expand from the domain layer",
            opportunity_tools=["lookup", "expand"],
            allowed_tools=["lookup", "expand"],
        ),
        catalogue=ToolCatalogueSnapshot(
            advertised_tools=["lookup", "expand"],
            catalogue_sha256="catalogue",
            description_chars=100,
            serialized_schema_chars=200,
        ),
        model_calls=[ModelCallUsage(
            turn=1, model="model-a", input_tokens=10, output_tokens=2,
            cost_usd=cost, latency_ms=wall / 2,
        )],
        tool_turns=[ToolTurn(
            turn=1, tool="expand", arguments={"node_ids": ["domain"]},
            validation="accepted", observed_node_ids=["service"],
            server_latency_ms=3, graph_latency_ms=2, response_bytes=80,
        )],
        final=TrajectoryFinal(
            selected_node_ids=["service"] if passed else [], stopped=True,
        ),
        score=TrajectoryScore(
            task_passed=passed, terminal_honest=True,
            required_total=1, required_observed=1,
            required_selected=int(passed),
        ),
        latency=LatencyBreakdown(model_ms=wall / 2, wall_ms=wall),
        cache=CacheCondition(graph_cache="warm", model_cache="cold"),
    )


def test_contract_rejects_an_allowed_tool_without_an_opportunity():
    with pytest.raises(ValidationError, match="declared opportunities"):
        ToolOpportunity(
            task_id="t", graph_id="g", graph_sha256="h", operator_band="A",
            intent="lookup", opportunity_tools=["lookup"],
            allowed_tools=["lookup", "search"],
        )


def test_tool_turn_binds_argument_identity():
    turn = ToolTurn(
        turn=1, tool="lookup", arguments={"reference": "x"},
        validation="accepted",
    )
    assert len(turn.arguments_sha256) == 64
    with pytest.raises(ValidationError, match="does not match"):
        ToolTurn(
            turn=1, tool="lookup", arguments={"reference": "x"},
            arguments_sha256="wrong", validation="accepted",
        )


def test_aggregate_conditions_cost_on_safe_success_and_counts_opportunity():
    report = aggregate_trajectories([
        _record(passed=True, cost=0.01, wall=100),
        _record(passed=False, cost=0.02, wall=300),
    ])
    arm = report["arms"]["compact_host::model-a"]

    assert arm["rows"] == 2
    assert arm["safe_successes"] == 1
    assert arm["cost_usd"] == 0.03
    # Total spend divided by safe successes: failed attempts are not free.
    assert arm["cost_per_safe_success_usd"] == 0.03
    assert arm["wall_ms_p50"] == 100
    assert arm["wall_ms_p95"] == 300
    assert arm["tool_opportunities"] == {"expand": 2, "lookup": 2}
    assert arm["tool_used_when_available"] == {"expand": 2}
    assert arm["opportunity_adjusted_use"] == {"expand": 1.0, "lookup": 0.0}


def test_json_schema_freezes_load_bearing_telemetry_fields():
    schema = json_schema()
    required = set(schema["required"])
    assert {
        "arm", "model", "repetition", "opportunity", "catalogue",
        "model_calls", "tool_turns", "final", "score", "latency",
    } <= required


def test_catalogue_snapshot_binds_interface_instructions():
    class Tool:
        name = "lookup"
        description = "Exact graph identity."
        inputSchema = {"type": "object"}

    snapshot = ToolCatalogueSnapshot.from_tools(
        [Tool()], instructions="Do not widen an exact miss."
    )
    assert snapshot.instruction_chars == 27
    assert len(snapshot.instruction_sha256) == 64
