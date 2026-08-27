"""`what_governs(adjudicate="host")` — evidence and a frame, never a verdict.

The measurement behind this mode is in `examples/host-loop-ablation/`: semantic
retrieval alone reached the governing rule at rank 1 on every governed question,
matching the three-call engine pipeline, and could not abstain on any distractor.
So the split these tests defend is retrieval (no reader needed) versus
adjudication (a reader needed).
"""
from __future__ import annotations

import pytest

from mcp_server.surface import COVERAGE_SPACE, Surface


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def has_next(self):
        return bool(self._rows)

    def get_next(self):
        return self._rows.pop(0)


class _FakeConn:
    def __init__(self, nodes):
        self._nodes = nodes

    def execute(self, query, params=None):
        node = self._nodes.get((params or {}).get("id"), {})
        return _FakeResult([[
            node.get("claim_kind", ""),
            node.get("claim_kind_source", ""),
            node.get("text_content", ""),
        ]]) if node else _FakeResult([])


@pytest.fixture
def surface(monkeypatch):
    nodes = {
        "rule_two_approvals": {
            "claim_kind": "governing", "claim_kind_source": "declared",
            "text_content": "Two collaborator approvals are required to land.",
        },
        "ctx_intro": {
            "claim_kind": "context", "claim_kind_source": "declared",
            "text_content": "Contributors propose modifications using pull requests.",
        },
    }
    s = Surface.__new__(Surface)
    s._session = type("S", (), {"connection": _FakeConn(nodes)})()
    s._base = lambda: {}
    s._read_guard = lambda: __import__("contextlib").nullcontext()
    s._record_fault = lambda *a, **k: None
    monkeypatch.setattr(
        "tools.vector_search",
        lambda conn, q, k=8: [
            {"id": "rule_two_approvals", "label": "Two approvals to land"},
            {"id": "ctx_intro", "label": "Contributors propose modifications"},
        ][:k],
    )
    return s


def test_host_mode_returns_a_frame_and_never_a_coverage_verdict(surface):
    out = surface.what_governs("How many approvals?", adjudicate="host")
    assert out["status"] == "REQUIRES_ADJUDICATION"
    # The whole point: this must not be mistakable for an answer.
    assert out["status"] not in COVERAGE_SPACE
    assert out["adjudicated_by"] == "host"
    assert out["llm_calls"] == 0
    assert set(out["adjudication_frame"]["verdict_space"]) == COVERAGE_SPACE


def test_only_declared_governing_candidates_can_carry_a_verdict(surface):
    out = surface.what_governs("How many approvals?", adjudicate="host")
    assert out["governing_candidate_ids"] == ["rule_two_approvals"]
    # The context node is still returned — the host must see what it rejected —
    # but it is not offered as authority.
    assert [c["id"] for c in out["candidates"]] == ["rule_two_approvals", "ctx_intro"]
    kinds = {c["id"]: c["claim_kind"] for c in out["candidates"]}
    assert kinds["ctx_intro"] == "context"


def test_a_graph_that_declares_no_claim_kind_says_so_rather_than_implying_absence(
    monkeypatch, surface
):
    """Two opposite repairs share one symptom, so they must not share a message."""
    surface._session.connection = _FakeConn({
        "n1": {"claim_kind": "", "text_content": "Some prose."},
    })
    monkeypatch.setattr("tools.vector_search",
                        lambda conn, q, k=8: [{"id": "n1", "label": "Some prose"}])
    out = surface.what_governs("anything", adjudicate="host")
    assert out["governing_candidate_ids"] == []
    assert "cannot support a governed verdict" in out["no_governing_candidates"]




def test_an_unknown_adjudicator_is_refused_rather_than_defaulted(surface):
    with pytest.raises(ValueError, match="adjudicate"):
        surface.what_governs("q", adjudicate="battalion")


def test_search_defaults_to_semantic_because_lexical_drops_the_question(monkeypatch):
    """Regression on the third appearance of the fail-open token filter."""
    import inspect

    from mcp_server.host_retrieval import HostRetrievalSurface

    assert inspect.signature(HostRetrievalSurface.search).parameters["mode"].default == "semantic"


def test_mcp_transport_search_defaults_to_semantic():
    """This used to also assert `what_governs` exposed `adjudicate` with default
    "host". The parameter is gone rather than defaulted, and
    `test_the_agent_surface_offers_one_adjudicator` makes the stronger claim in
    its place. The `search` half is an unrelated regression and stays."""
    from mcp_server.stdio import TOOLS

    search = next(t for t in TOOLS if t.name == "search")
    assert search.inputSchema["properties"]["mode"]["default"] == "semantic"


def test_what_governs_is_not_on_this_agent_surface():
    """It was withdrawn to host-only adjudication on the MCP transport, and
    then off this transport entirely: governance is the other product. The
    Python API below is what benchmarks and the ablation still use."""
    from mcp_server.stdio import TOOLS

    assert not any(t.name == "what_governs" for t in TOOLS)


