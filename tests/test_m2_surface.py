"""M2 surface tests — contract v0 enforcement at the unit level.

The executable source of truth for M2 semantics is scripts/run_m2_battery.py;
these tests keep the same guarantees inside the normal pytest loop and add
transport-layer checks the battery does not cover.
"""

from __future__ import annotations

import json
import threading

import pytest

from mcp_server.surface import (
    CONFIRMATION_SPACE,
    COVERAGE_SPACE,
    GOVERNANCE_FIELDS,
    Surface,
    open_fixture,
)


def _ensure():
    from mcp_server.fixture import ensure_fixture

    return ensure_fixture(FIXTURE)

FIXTURE = "runtime/hexagonal_orders.lbug"


@pytest.fixture(scope="module")
def surface() -> Surface:
    """No provider key for this module.

    Several assertions here are about HONEST DEGRADATION (`engine_degraded`,
    `engine_fault:` flags), which only holds when there is no key to call with.
    The module relied on the ambient environment happening not to have one, so
    under random test ordering — or with a key in `.env` — it flipped red for
    reasons unrelated to what it tests. Make the precondition explicit.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("OPENROUTER_API_KEY", raising=False)
        s = open_fixture(FIXTURE)
        yield s
        s.close()


def test_orient_shape_and_capabilities(surface):
    o = surface.orient()
    assert {"contract_version", "graph_version", "trace_id"} <= set(o)
    assert o["contract_version"] == "mcp-v0"
    assert "query" in o["capabilities"] and "propose" not in o["capabilities"]
    assert o["node_count"] == 30
    assert o["context_view"] == "graph_card"
    assert "landmark_preview" in o and "node_centrality" not in o
    assert o["retrieval"]["proof"]["success_evidence"] == "path_record"
    assert o["retrieval"]["judgment_view"]["packet_truth"] == "append_only"


def test_orient_context_is_progressively_disclosed(surface):
    capabilities = surface.orient(context="capabilities")
    full_map = surface.orient(context="full_map")
    assert "landmark_preview" not in capabilities
    assert "node_centrality" not in capabilities
    assert len(full_map["node_centrality"]) == full_map["node_count"]


def test_discover_is_confirmation_space_and_strips_governance(surface):
    d = surface.discover("What does the domain layer contain?", evidence="summary")
    assert d["verdict"] in CONFIRMATION_SPACE
    assert not (GOVERNANCE_FIELDS & set(d))
    # honest failure without a key: degraded, flagged, still typed
    assert d["engine_degraded"] is True
    assert any(f.startswith("engine_fault:") for f in d["degradation_flags"])


def test_discover_packet_mode_caps_and_no_text_content(surface):
    d = surface.discover("What does the domain layer contain?", evidence="packet")
    ev = d["evidence"]
    assert len(ev["node_records"]) <= 50 and len(ev["edge_records"]) <= 100
    assert all("text_content" not in n for n in ev["node_records"])
    assert isinstance(ev["path_records"], list)  # legally empty is fine




def test_direct_retrieve_resolves_compass_label_stems_before_embeddings(surface):
    result = surface.retrieve({
        "contract_version": "retrieval-v1",
        "steps": [{
            "tool": "exact_node_lookup",
            "params": {"label_or_id": [
                "StripePaymentAdapter",
                "WarehouseInventoryAdapter",
                "EmailNotificationAdapter",
            ]},
            "assign_to": "adapters",
        }],
        "collect": "$adapters",
    }, evidence="summary")
    assert result["kind"] == "RETRIEVED"
    assert set(result["evidence"]["node_ids"]) == {
        "stripe_payment_adapter",
        "warehouse_inventory_adapter",
        "email_notification_adapter",
    }


def test_direct_retrieve_rejects_an_invalid_program(surface):
    result = surface.retrieve({
        "contract_version": "retrieval-v1",
        "steps": [{"tool": "invent_answer", "params": {}, "assign_to": "x"}],
        "collect": "$x",
    })
    assert result["kind"] == "INVALID_PROGRAM"
    assert result["errors"]


def test_direct_retrieve_refuses_stale_plan_preconditions(surface, monkeypatch):
    import retrieval_program

    monkeypatch.setattr(
        retrieval_program,
        "execute_retrieval_program",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stale plan was executed")
        ),
    )
    program = {
        "contract_version": "retrieval-v1",
        "steps": [{
            "tool": "exact_node_lookup",
            "params": {"label_or_id": "dependency_direction_rule"},
            "assign_to": "rule",
        }],
        "collect": "$rule",
    }
    assert surface.retrieve(program, context_ref="stale")["kind"] == "STALE_CONTEXT"
    assert surface.retrieve(program, graph_version="stale")["kind"] == "STALE_GRAPH"














def test_what_governs_crash_is_not_actionable_as_graph_absence(surface, monkeypatch):
    """A crash wearing an answer's clothes.

    Retargeted from the engine adjudicator to host adjudication when the
    engine arm was deleted. The property is the same and it is the one that
    matters: an exception must not become a coverage finding, because a gap
    ledger that records transport failures as missing governance sends
    somebody to write a rule that already exists.
    """
    def _broken(*_args, **_kwargs):
        raise RuntimeError("provider transport broke")

    monkeypatch.setattr(surface, "_governance_candidates", _broken)
    result = surface.what_governs("what governs retries?")

    assert result["status"] == "ABSENT"  # closed coverage vocabulary remains stable
    assert result["engine_degraded"] is True
    assert "not a graph finding" in result["error"]

    # A crash is an operator incident, never a roadmap/gap-ledger observation.
    assert not any(
        gap["key"] == "what governs retries?"
        for gap in surface.coverage()["gaps"]
    )


def test_escalate_persists_across_reload(surface):
    e = surface.escalate(question="probe", ungoverned_predicate="p1")
    assert e["stored"] is True
    surface.reload()
    assert surface.escalation_exists(e["handoff_id"])


def test_empty_graph_probe_refuses_and_restores(surface):
    # The probe moved off Surface into the battery that is its only caller;
    # it is scaffolding, not a product verb.
    from scripts.run_m2_battery import probe_empty_graph_refusal

    assert probe_empty_graph_refusal(surface) is True
    # surface still functional afterwards
    assert surface.orient()["node_count"] == 30


def test_unknown_verdict_maps_honest(surface):
    from scripts.run_m2_battery import probe_unknown_verdict_mapping

    m = probe_unknown_verdict_mapping(surface)
    assert m["verdict"] in CONFIRMATION_SPACE
    assert m["engine_degraded"] is True
    assert any("unknown_verdict" in f for f in m["degradation_flags"])


def test_concurrent_discover_distinct_traces(surface):
    out: dict = {}

    def _q(k):
        out[k] = surface.discover("What does the domain layer contain?", evidence="none")

    ts = [threading.Thread(target=_q, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join(180) for t in ts]
    assert len(out) == 2 and out[0]["trace_id"] != out[1]["trace_id"]


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------


def test_stdio_tool_listing_matches_contract():
    from mcp_server.stdio import TOOLS

    names = {t.name for t in TOOLS}
    assert names == {"orient", "contract", "lookup", "expand", "path", "search",
                     "run_traversal", "run_ephemeral_traversal", "retrieve",
                     "read_cypher", "history", "propose", "proposal_status"}
    # The governance surface belongs to the other product and is not served
    # here.
    assert not ({"what_governs", "check_conformance", "escalate", "coverage",
                 "classify_absence", "lineage", "operation", "discover",
                 "plan_retrieval"} & names)
    assert not any(n.startswith("construction_") for n in names)
    assert not ({"confirm", "commit", "encode"} & names)  # commit authority never on the MCP surface
    assert "revert" not in names  # operators move backward; agents never do
    # propose absent by design until the reversal admission checklist is green


def test_stdio_call_tool_roundtrip(surface):
    """Drive the registered MCP call_tool handler directly."""
    import asyncio

    from mcp_server.stdio import build_server

    server = build_server(surface)
    handler = server.request_handlers[type(_call_tool_request("orient"))]

    async def _run():
        req = _call_tool_request("orient")
        result = await handler(req)
        return result

    res = asyncio.run(_run())
    payload = json.loads(res.root.content[0].text)
    assert payload["contract_version"] == "mcp-v0"
    assert payload["node_count"] == 30


def test_stdio_compact_retrieval_roundtrips(surface):
    """The promoted tools dispatch through MCP, not only the Python wrapper."""
    import asyncio

    from mcp_server.stdio import build_server

    server = build_server(surface)
    handler = server.request_handlers[type(_call_tool_request("orient"))]

    async def _call(name, arguments):
        result = await handler(_call_tool_request(name, arguments))
        return json.loads(result.root.content[0].text)

    async def _run():
        return {
            "lookup": await _call("lookup", {
                "references": ["dependency_direction_rule"],
                "include_content": True,
            }),
            "expand": await _call("expand", {
                "node_ids": ["ports_module"],
                "edge_types": ["contains"],
                "direction": "outgoing",
                "depth": 1,
            }),
            "path": await _call("path", {
                "source_ids": ["order_controller"],
                "target_ids": ["order_service"],
                "edge_types": ["leadsto"],
            }),
            "search": await _call("search", {
                "query": "dependency direction",
                "mode": "lexical",
                "limit": 5,
            }),
        }

    results = asyncio.run(_run())
    assert all(result["zero_llm"] is True for result in results.values())
    assert results["lookup"]["outcome"] == "FOUND"
    assert results["lookup"]["evidence"]["node_payloads"]
    assert results["expand"]["evidence"]["edge_records"]
    assert results["path"]["evidence"]["path_records"]
    assert results["search"]["candidate_only"] is True


def _call_tool_request(name: str, arguments: dict | None = None):
    import mcp.types as types

    return types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name=name, arguments=arguments or {}),
    )


# ---------------------------------------------------------------------------
# check_conformance plumbing (M2_FAIL:L3 regression — gate needs the component)
# ---------------------------------------------------------------------------


class _CapturedCall(Exception):
    def __init__(self, kwargs):
        self.kwargs = kwargs


def _capture_cc(**kwargs):
    raise _CapturedCall(kwargs)


def test_conformance_snippet_carries_target_file(monkeypatch, tmp_path):
    """Content + logical path → snippet mode with target_file (gate can fire)."""
    import conformance_check.surface as cs

    monkeypatch.setattr(cs, "check_conformance", _capture_cc)
    surface = Surface(_ensure(), handbook="testbook")
    try:
        out = surface.check_conformance(
            rule_id="SomeRule", artifact="x = 1", artifact_path="app/thing/loader.py"
        )
        # surface catches the raised capture as engine fault
        assert out["kind"] == "INSUFFICIENT_EVIDENCE" and out["engine_degraded"] is True
    finally:
        surface.close()


def test_conformance_plumbing_kwargs(monkeypatch, tmp_path):
    """Direct assertion on what the surface hands the conformance seam."""
    import conformance_check.surface as cs
    from mcp_server.surface import open_fixture

    s = Surface(_ensure(), handbook="testbook")
    try:
        captured: dict = {}

        def _spy(**kwargs):
            captured.update(kwargs)
            raise _CapturedCall(kwargs)

        monkeypatch.setattr(cs, "check_conformance", _spy)

        # 1) snippet + path not on disk → snippet mode, target_file carried
        s.check_conformance(rule_id="R", artifact="code", artifact_path="pkg/mod.py")
        assert captured["snippet"] == "code"
        assert captured["target_file"] == "pkg/mod.py"
        assert "file" not in captured or captured.get("file") is None

        # 2) path on disk, no content → gated file mode
        f = tmp_path / "loader.py"
        f.write_text("x = 1\n")
        captured.clear()
        s.check_conformance(rule_id="R", artifact_path=str(f))
        assert captured["file"] == f
        assert "snippet" not in captured or captured.get("snippet") is None

        # 3) content + path on disk → caller content wins, gate kept via target_file
        captured.clear()
        s.check_conformance(rule_id="R", artifact="unsaved edit", artifact_path=str(f))
        assert captured["snippet"] == "unsaved edit"
        assert captured["target_file"] == str(f)
    finally:
        s.close()


def test_engine_surface_accepts_target_file_param():
    import inspect

    from conformance_check.surface import check_conformance

    assert "target_file" in inspect.signature(check_conformance).parameters













