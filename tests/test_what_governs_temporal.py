"""Coverage answers the WHEN question the same way the ruling space does.

A rule outside its effective window does not govern. `check_conformance` has
resolved that since it was built; `what_governs` did not, so the two halves of
the product could disagree about the same graph at the same instant — coverage
answering GOVERNED while citing a policy the ruling space would refuse to
apply. That asymmetry failed toward the dangerous side: someone asking what
governs a decision is asking whether they are constrained, and a repealed rule
answers yes with nothing behind it.

**Rewritten when the engine adjudicator was deleted.** The property is
unchanged; the mechanism is not, and the new one is better. The old engine arm
produced a verdict and then *withdrew* it after the fact
(`_temporal_coverage`). Host adjudication resolves the window per candidate and
drops the ones out of force before ranking, and carries `in_force` /
`effective_from` / `effective_until` on the ones that survive. Filtering
upstream is the stronger version: there is no window in which a caller can
read a verdict that has not yet been withdrawn.

Two drafts of this file were wrong in opposite directions, and both were
caught by the same positive control. The first keyed on `order_service`, which
this fixture's ranking does not return for this question — so "not a
candidate" would have passed for a reason unrelated to time. The second read
the `in_force` flag on the payload and concluded expired rules were kept and
flagged; they are not, they are dropped, and the flag is there for the ones
that stay.
"""

from __future__ import annotations

import shutil

import pytest

from mcp_server.fixture import ensure_fixture
from mcp_server.surface import Surface

#: Deliberately not a hard-coded id. Which nodes reach the top k depends on
#: retrieval ranking, and ranking is not stable across suite conditions: a
#: first version keyed on `order_service` (never ranked) and a second on
#: `order` (ranked alone, not in the full suite). Both failed for reasons that
#: have nothing to do with time. Each test now asks the graph which rule it
#: offers, then puts a window on *that* one.
def _top_candidate_id(surface, question):
    out = surface.what_governs(question)
    ids = [str(c.get("id") or "") for c in (out.get("candidates") or [])]
    assert ids, "the fixture offered no candidates; the test measures nothing"
    return ids[0]


@pytest.fixture()
def graph(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def _window(surface, node_id, frm="", until=""):
    from mcp_server.temporal import set_rule_window

    set_rule_window(surface._session.connection, node_id, frm, until)


def _candidate(out, node_id):
    for c in out.get("candidates") or []:
        if str(c.get("id") or "") == node_id:
            return c
    return None


QUESTION = "does order_service govern dispatch?"


def test_a_rule_inside_its_window_is_in_force(graph):
    """The positive control. Without it every assertion below could pass on a
    surface that returns no candidates at all."""
    surface = Surface(graph)
    try:
        rule = _top_candidate_id(surface, QUESTION)
        _window(surface, rule, "2020-01-01", "2031-01-01")
        row = _candidate(surface.what_governs(QUESTION, as_of="2025-06-15"), rule)
        assert row is not None, "the rule stopped being a candidate inside its window"
        assert row["in_force"] is True
    finally:
        surface.close()


def test_a_repealed_rule_is_not_offered_as_a_candidate(graph):
    surface = Surface(graph)
    try:
        rule = _top_candidate_id(surface, QUESTION)
        _window(surface, rule, "2020-01-01", "2021-01-01")
        assert _candidate(surface.what_governs(QUESTION, as_of="2025-06-15"), rule) is None
    finally:
        surface.close()


def test_the_same_rule_is_in_force_inside_its_window(graph):
    """Same rule, same question, two instants. The window is doing the work
    rather than the rule being absent or unreachable."""
    surface = Surface(graph)
    try:
        rule = _top_candidate_id(surface, QUESTION)
        _window(surface, rule, "2020-01-01", "2021-01-01")
        inside = _candidate(surface.what_governs(QUESTION, as_of="2020-06-15"), rule)
        outside = _candidate(surface.what_governs(QUESTION, as_of="2025-06-15"), rule)
        assert inside is not None and inside["in_force"] is True
        assert outside is None
    finally:
        surface.close()


def test_a_graph_without_windows_is_in_force(graph):
    """Most graphs record no windows. They must not be silently narrowed."""
    surface = Surface(graph)
    try:
        rule = _top_candidate_id(surface, QUESTION)
        row = _candidate(surface.what_governs(QUESTION, as_of="2025-06-15"), rule)
        assert row is not None and row["in_force"] is True
        assert row["effective_from"] == ""
    finally:
        surface.close()


def test_the_answer_discloses_which_instant_it_was_asked_about(graph):
    """`as_of` defaults to today, so a reader cannot infer it from the call."""
    surface = Surface(graph)
    try:
        assert surface.what_governs(QUESTION, as_of="2025-06-15")["as_of"] == "2025-06-15"
        assert surface.what_governs(QUESTION)["as_of"] == "today"
    finally:
        surface.close()
