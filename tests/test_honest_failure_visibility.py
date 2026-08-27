"""Every honest failure reaches the operator. Silence is the failure mode.

`positioning.md` sells honest refusal — `UNGOVERNED`, `INSUFFICIENT_EVIDENCE`,
`ILL_POSED` are outputs, not errors — and `coverage.py` says the honest gaps ARE
the roadmap. Both are only true if the refusals are *recorded*. A refusal nobody
hears is indistinguishable from a question nobody asked.

Two producers were missing when this was checked:

- **`system.fault`** — the ledger and the event log both treat it as an incident
  opener; nothing emitted one, so a degraded engine told the calling agent and
  never the operator.
- **`query.completed:*`** — the ledger has matched the `query.` prefix since it
  was written, and `discover` recorded nothing. Coverage and ruling space
  recorded their failures; confirmation space did not, so the roadmap saw
  governance gaps and was blind to knowledge gaps.

Deterministic: the fold is pure, and the surface plumbing is checked by
inspection rather than by running an engine.
"""

from __future__ import annotations

import inspect

import pytest

from mcp_server.coverage import GAP_VERDICTS, project_coverage


def _event(evtype: str, gap_id: str = "", question: str = "q"):
    return {"type": evtype, "gap_id": gap_id, "payload": {"question": question}}


# ------------------------------------------------------- the producers exist


def test_discover_does_not_record_a_query_event():
    from mcp_server.surface import Surface

    src = inspect.getsource(Surface.discover)
    assert "query.completed:" not in src


def test_verdict_spaces_do_not_emit_product_events():
    from mcp_server.surface import Surface

    src = inspect.getsource(Surface)
    for evtype in ("query.completed:", "governance.coverage_checked:",
                   "conformance.completed:"):
        assert evtype not in src, f"retired producer still present for {evtype}"


def test_an_engine_fault_does_not_emit_a_product_event():
    from mcp_server.surface import Surface

    assert "system.fault" not in inspect.getsource(Surface._record_fault)


# --------------------------------------------------- the ledger folds them


@pytest.mark.parametrize("verdict", ["ILL_POSED", "UNKNOWN_TO_GRAPH"])
def test_confirmation_space_absences_become_roadmap(verdict):
    """The question cannot be asked of this graph, or the content is not there.
    Both are as much roadmap as an ungoverned predicate."""
    report = project_coverage([
        _event(f"query.completed:{verdict}", "napoleon", "how did Napoleon…?"),
        _event(f"query.completed:{verdict}", "napoleon", "what did Napoleon…?"),
    ])
    gaps = {g["key"]: g for g in report["gaps"]}
    assert "napoleon" in gaps, f"{verdict} did not reach the ledger"
    assert gaps["napoleon"]["count"] == 2
    assert gaps["napoleon"]["is_lead"] is True


def test_a_successful_answer_is_not_a_gap():
    report = project_coverage([_event("query.completed:CONFIRMED", "x")])
    assert report["summary"]["distinct_gaps"] == 0


def test_exhausted_is_not_counted_as_a_gap():
    """"We searched and the answer is no" is often correct, not missing.
    Counting it would drown the ledger in legitimate negatives."""
    assert "EXHAUSTED" not in GAP_VERDICTS
    report = project_coverage([_event("query.completed:EXHAUSTED", "x")])
    assert report["summary"]["distinct_gaps"] == 0


def test_knowledge_and_governance_gaps_share_one_ledger():
    """An operator should see one roadmap, not two — and a predicate hit from
    both directions should collapse rather than double-count."""
    report = project_coverage([
        _event("query.completed:ILL_POSED", "retry_limit", "how many retries?"),
        _event("governance.coverage_checked:UNGOVERNED", "retry_limit",
               "are retries governed?"),
    ])
    gaps = {g["key"]: g for g in report["gaps"]}
    assert list(gaps) == ["retry_limit"], "one predicate should be one lead"
    assert gaps["retry_limit"]["count"] == 2
    assert gaps["retry_limit"]["is_lead"] is True
