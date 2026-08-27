"""Ask retrieval on a current constructed graph — not LOTR, not the hex fixture.

NIST SSDF critic-v3 is hierarchical (CONTAINS). Query natures covered here:

- identity (exact lookup, including trailing ``(PO.1)``)
- containment (lookup then expand)
- membership / relation (bounded path over CONTAINS)
- typed empty (known node, wrong edge type)
- exact miss (lookup never widens)
- candidate search (lexical; never a closed-world empty)

Planning is the Ask loop choosing those ops, plus ``plan_retrieval`` compiling
an executable retrieval-v1 program that ``retrieve`` can run. The loop model
and Battalion are stubbed; these tests do not spend on OpenRouter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server import ask as ask_mod
from mcp_server.retrieve import Retrieve
from mcp_server.surface import Surface


NIST = Path("data/construction_trials/nist-ssdf-blind-references-critic-v3/graph.lbug")

PRACTICE = "practice_po_1"
TASK = "task_po_1_1"
PRACTICE_LABEL = "Define Security Requirements for Software Development (PO.1)"


def _skip_if_missing():
    if not NIST.is_file():
        pytest.skip(f"constructed graph not present: {NIST}")


@pytest.fixture(scope="module")
def surface() -> Surface:
    _skip_if_missing()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        instance = Surface(NIST)
        yield instance
        instance.close()


@pytest.fixture
def ops(surface: Surface) -> Retrieve:
    return Retrieve(surface)


def _stub_claim(query, packet, _conn, verdict="CONFIRMED", compass=None):
    return {
        "query": query,
        "evidence_packet": packet,
        "confirmation_response": {"verdict": verdict},
        "final_answer": "stub-claim",
        "provenance": [],
        "gaps": [],
        "company_handoff": {"internal_handoff": {"gaps": []}},
        "retrieval_strategy": "contract_driven",
        "degradation_flags": list(packet.get("degradation_flags") or []),
    }


def _script_ask(monkeypatch, turns: list[str]):
    leftover = iter(turns)
    monkeypatch.setattr(ask_mod, "_call_loop_model", lambda _msgs: next(leftover))
    import claim as claim_mod

    monkeypatch.setattr(claim_mod, "write_claim", _stub_claim)


# ---------------------------------------------------------------------------
# Deterministic ops
# ---------------------------------------------------------------------------


def test_lookup_identity_by_id_and_trailing_code(ops: Retrieve):
    by_id = ops.lookup([PRACTICE])
    by_code = ops.lookup(["PO.1"])
    by_label = ops.lookup([PRACTICE_LABEL])

    assert by_id["outcome"] == "FOUND"
    assert by_id["evidence_scope"] == "closure-derived"
    assert by_id["evidence"]["node_records"][0]["id"] == PRACTICE
    assert by_code["outcome"] == "FOUND"
    assert by_code["evidence"]["node_records"][0]["id"] == PRACTICE
    assert by_label["outcome"] == "FOUND"
    assert by_label["evidence"]["node_records"][0]["id"] == PRACTICE


def test_expand_containment_lists_tasks(ops: Retrieve):
    result = ops.expand(
        [PRACTICE],
        edge_types=["contains"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "FOUND"
    kids = {row["id"] for row in result["evidence"]["node_records"]}
    assert TASK in kids
    assert all(
        edge["edge_type"] == "contains" for edge in result["evidence"]["edge_records"]
    )


def test_path_membership_over_contains(ops: Retrieve):
    result = ops.path(
        [PRACTICE],
        [TASK],
        edge_types=["contains"],
        max_hops=2,
    )
    assert result["outcome"] == "FOUND"
    assert result["evidence"]["path_records"]
    chain = result["evidence"]["path_records"][0]
    assert chain["source"] == PRACTICE
    assert chain["target"] == TASK


def test_typed_empty_is_not_an_unresolved_seed(ops: Retrieve):
    result = ops.expand(
        [PRACTICE],
        edge_types=["leadsto"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "EMPTY"
    assert result["evidence_scope"] == "closure-derived"
    assert result["seed_resolution"]["complete"] is True


def test_search_toolchain_is_candidates_not_a_verdict(ops: Retrieve):
    result = ops.search("toolchain", mode="lexical", limit=8)
    assert result["outcome"] == "CANDIDATES"
    assert result["candidate_only"] is True
    assert result["evidence_scope"] == "candidate-derived"
    ids = {row["id"] for row in result["evidence"]["node_records"]}
    assert any(item.startswith("practice_po_3") or item.startswith("task_po_3") for item in ids)


def test_search_miss_cannot_be_terminal_empty(ops: Retrieve):
    result = ops.search("definitely_missing_search_term_9f37", mode="lexical")
    assert result["outcome"] == "NO_CANDIDATES"
    assert result["outcome"] != "EMPTY"


# ---------------------------------------------------------------------------
# Ask loop planning (scripted model)
# ---------------------------------------------------------------------------


def test_ask_identity_uses_lookup_then_stops(surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": ["PO.1"]}),
        json.dumps({"final": {"reason": "named node"}}),
    ])
    state = ask_mod.run_ask(surface, "What is PO.1?")
    ids = {row["id"] for row in state["evidence_packet"]["node_records"]}
    assert PRACTICE in ids
    assert state["confirmation_response"]["verdict"] == "CONFIRMED"
    ops = [row["operation"] for row in state["evidence_packet"]["packet_provenance"]]
    assert ops == ["lookup"]


def test_ask_containment_lookup_then_expand(surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [PRACTICE]}),
        json.dumps({
            "tool": "expand",
            "node_ids": [PRACTICE],
            "edge_types": ["contains"],
            "direction": "outgoing",
            "depth": 1,
        }),
        json.dumps({"final": {"reason": "children in packet"}}),
    ])
    state = ask_mod.run_ask(surface, "What does PO.1 contain?")
    ids = {row["id"] for row in state["evidence_packet"]["node_records"]}
    assert PRACTICE in ids
    assert TASK in ids
    ops = [row["operation"] for row in state["evidence_packet"]["packet_provenance"]]
    assert ops == ["lookup", "expand"]


def test_ask_membership_uses_path(surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [PRACTICE, TASK]}),
        json.dumps({
            "tool": "path",
            "source_ids": [PRACTICE],
            "target_ids": [TASK],
            "edge_types": ["contains"],
            "max_hops": 2,
        }),
        json.dumps({"final": {"reason": "path in packet"}}),
    ])
    state = ask_mod.run_ask(
        surface, "Is PO.1.1 contained in PO.1?"
    )
    assert state["evidence_packet"]["path_records"]
    ops = [row["operation"] for row in state["evidence_packet"]["packet_provenance"]]
    assert ops == ["lookup", "path"]


def test_ask_exact_miss_does_not_widen(surface: Surface, monkeypatch):
    searched: list = []
    orig = ask_mod.Retrieve.search

    def _search(self, *args, **kwargs):
        searched.append((args, kwargs))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(ask_mod.Retrieve, "search", _search)
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": ["Sauron"]}),
        json.dumps({"tool": "search", "query": "Sauron", "mode": "lexical"}),
        json.dumps({"final": {"reason": "missed"}}),
    ])
    state = ask_mod.run_ask(surface, "Is Sauron in this graph?")
    assert searched == []
    assert state["confirmation_response"]["verdict"] == "UNKNOWN_TO_GRAPH"


# ---------------------------------------------------------------------------
# plan_retrieval → retrieve, no live Planner
# ---------------------------------------------------------------------------






