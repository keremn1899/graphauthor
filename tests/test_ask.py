from __future__ import annotations

import json

import pytest

from mcp_server import ask as ask_mod
from mcp_server.surface import Surface, open_fixture
from claim import trails_from_packet


FIXTURE = "runtime/hexagonal_orders.lbug"


@pytest.fixture(scope="module")
def surface() -> Surface:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        instance = open_fixture(FIXTURE)
        yield instance
        instance.close()


def test_discover_without_a_key_is_still_a_typed_fault(surface):
    d = surface.discover("What does the domain layer contain?", evidence="summary")
    assert d["verdict"] in {
        "CONFIRMED", "ALTERNATIVE", "EXHAUSTED", "ILL_POSED", "UNKNOWN_TO_GRAPH",
    }
    assert d["engine_degraded"] is True
    assert any(str(f).startswith("engine_fault:") for f in d["degradation_flags"])


def test_ask_will_not_widen_an_exact_miss(surface, monkeypatch):
    turns = iter([
        json.dumps({"tool": "lookup", "references": ["async hook contract"]}),
        json.dumps({"tool": "search", "query": "async hook", "mode": "lexical"}),
        json.dumps({"final": {"reason": "missed"}}),
    ])
    monkeypatch.setattr(ask_mod, "_call_loop_model", lambda _msgs: next(turns))
    import claim as claim_mod
    monkeypatch.setattr(
        claim_mod,
        "write_claim",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("claim must not run on a miss")
        ),
    )
    searched = []
    orig = ask_mod.Retrieve.search

    def _search(self, *args, **kwargs):
        searched.append((args, kwargs))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(ask_mod.Retrieve, "search", _search)
    state = ask_mod.run_ask(surface, "Is there an async hook contract?")
    assert searched == []
    assert state["confirmation_response"]["verdict"] == "UNKNOWN_TO_GRAPH"
    assert "no node matching that name" in state["final_answer"]


def test_trails_from_packet_use_path_chains():
    packet = {
        "path_records": [{
            "node_chain": ["a", "b"],
            "edge_chain": ["leadsto"],
            "source": "a",
            "target": "b",
        }],
        "node_records": [{"id": "a"}, {"id": "b"}],
    }
    trails = trails_from_packet(packet)
    assert trails["primary_trails"][0]["node_ids"] == ["a", "b"]
    assert trails["primary_trails"][0]["trail_id"] == "path_0"


def test_write_claim_asks_in_confirmation_space(monkeypatch):
    captured: dict = {}

    def fake_synthesize(state, _conn):
        captured.update(state)
        return {"final_answer": "ok", "provenance": [], "gaps": []}

    monkeypatch.setattr("battalion.battalion_synthesize", fake_synthesize)
    from claim import write_claim

    write_claim("What is PO.1?", {}, None, verdict="CONFIRMED")
    assert captured["verdict_space"] == "confirmation"
    assert captured["confirmation_response"]["verdict"] == "CONFIRMED"


def test_ask_starts_from_the_graph_kernel(surface, monkeypatch):
    seen: list[list] = []

    def _call(msgs):
        seen.append(msgs)
        return json.dumps({"final": {"reason": "oriented"}})

    monkeypatch.setattr(ask_mod, "_call_loop_model", _call)
    import claim as claim_mod

    monkeypatch.setattr(claim_mod, "write_claim", lambda *_a, **_k: {
        "query": "q",
        "evidence_packet": {},
        "confirmation_response": {"verdict": "EXHAUSTED"},
        "final_answer": "",
        "provenance": [],
        "gaps": [],
        "company_handoff": {"internal_handoff": {"gaps": []}},
        "retrieval_strategy": "contract_driven",
        "degradation_flags": [],
    })
    ask_mod.run_ask(surface, "What does the domain layer contain?")
    assert seen
    user = next(m for m in seen[0] if m.get("role") == "user")
    assert user["content"].startswith("GRAPH KERNEL:")
    assert "TASK:\nWhat does the domain layer contain?" in user["content"]
    assert "LAYER 1" in user["content"]
