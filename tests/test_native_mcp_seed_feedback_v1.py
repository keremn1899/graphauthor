from __future__ import annotations

import json
import shutil


def test_graduated_feedback_is_default_on_and_control_remains_replayable(tmp_path):
    import asyncio
    import mcp.types as types

    from benchmarks.host_retrieval.regional_compass_host_ab_v1 import CATTRS_GRAPH
    from mcp_server.stdio import build_server
    from mcp_server.surface import Surface

    graph = tmp_path / "cattrs.lbug"
    shutil.copy2(CATTRS_GRAPH, graph)
    surface = Surface(graph, store_path=tmp_path / "events.sqlite")
    try:
        async def call(server):
            request = types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(
                    name="expand",
                    arguments={
                        "node_ids": ["definitely_missing"],
                        "edge_types": ["nearto"],
                        "direction": "incoming",
                        "depth": 1,
                    },
                ),
            )
            result = await server.request_handlers[types.CallToolRequest](request)
            return json.loads(result.root.content[0].text)

        feedback = asyncio.run(call(build_server(surface)))
        historical_control = asyncio.run(call(build_server(
            surface,
            host_retrieval_options={"seed_resolution_feedback": False},
        )))
    finally:
        surface.close()

    assert feedback["outcome"] == "UNRESOLVED_SEED"
    assert feedback["seed_resolution"]["unresolved_node_ids"] == [
        "definitely_missing"
    ]
    assert historical_control["outcome"] == "EMPTY"
    assert "seed_resolution" not in historical_control


def test_frozen_protocol_is_bound():
    from benchmarks.host_retrieval.native_mcp_seed_feedback_v1 import _protocol

    protocol = _protocol()
    assert protocol["cost_gate"]["campaign_cost_limit_usd"] == 0.1
    assert [case["case_id"] for case in protocol["cases"]] == [
        "unknown_seed",
        "known_empty_neighbourhood",
    ]
