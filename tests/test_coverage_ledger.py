"""The gap ledger — "the honest gaps ARE the roadmap", proven.

The claims register flagged this as unproven: the *non-obvious* behaviour is
that recurrence keys on the **ungoverned predicate**, not the raw question, so
differently worded questions about one gap collapse into a single lead instead
of inflating into several. Nothing asserted that.

It matters beyond tidiness. `propose` requires `target_gap_id`, and this ledger
is where those predicates come from — so the keying is the join that makes the
authoring loop closed. If it fragmented, an agent would be proposing against
gap ids that each occurred once and never crossed the lead threshold.

Deterministic: a pure fold, no LLM, no database.
"""

from __future__ import annotations

from mcp_server.coverage import LEAD_THRESHOLD, project_coverage


def _gap(predicate: str, question: str, verdict: str = "UNGOVERNED",
         prefix: str = "governance.coverage_checked"):
    return {"type": f"{prefix}:{verdict}", "gap_id": predicate,
            "payload": {"question": question}}


def _keys(report):
    return {g["key"]: g for g in report["gaps"]}


def test_one_predicate_two_phrasings_is_one_lead():
    """The behaviour the module's own docstring calls the only non-obvious
    part: "what governs refunds?" and "is the refund window governed?" are one
    gap, not two."""
    report = project_coverage([
        _gap("refund_window", "what governs refunds?"),
        _gap("refund_window", "is the refund window governed?"),
    ])
    gaps = _keys(report)
    assert len(gaps) == 1, "one predicate fragmented into several gaps"
    only = next(iter(gaps.values()))
    assert only["count"] == 2
    assert only["is_lead"] is True
    assert len(only["examples"]) == 2, "both phrasings should be recoverable"


def test_recurrence_is_what_makes_a_lead():
    """One-offs are noise; repetition is signal. A gap seen once must not
    present as roadmap."""
    once = project_coverage([_gap("seen_once", "asked one time")])
    assert _keys(once)["seen_once"]["is_lead"] is False

    twice = project_coverage([
        _gap("seen_twice", "asked once"),
        _gap("seen_twice", "asked again"),
    ])
    assert _keys(twice)["seen_twice"]["is_lead"] is True
    assert LEAD_THRESHOLD == 2


def test_distinct_predicates_stay_distinct():
    """Collapsing must not over-reach: two real gaps are two leads."""
    report = project_coverage([
        _gap("refund_window", "what governs refunds?"),
        _gap("retry_limit", "how many retries are allowed?"),
    ])
    assert len(report["gaps"]) == 2
    assert report["summary"]["distinct_gaps"] == 2


def test_a_gap_with_no_predicate_falls_back_to_the_question():
    """An escalation without its predicate still has to land somewhere — but it
    keys on normalised text, so it cannot merge with anything else."""
    report = project_coverage([
        {"type": "conformance.completed:UNGOVERNED", "gap_id": "",
         "payload": {"question": "  A One-Off   Question "}},
    ])
    gaps = _keys(report)
    assert "a one-off question" in gaps, "fallback should normalise whitespace/case"
    assert gaps["a one-off question"]["is_lead"] is False


def test_every_honest_failure_verdict_reaches_the_ledger():
    """UNGOVERNED, ABSENT and INSUFFICIENT_EVIDENCE are all coverage signals.
    A verdict that never reaches the ledger is a gap the roadmap cannot see."""
    report = project_coverage([
        _gap("p_ungoverned", "q1", verdict="UNGOVERNED"),
        _gap("p_absent", "q2", verdict="ABSENT"),
        _gap("p_insufficient", "q3", verdict="INSUFFICIENT_EVIDENCE",
             prefix="conformance.completed"),
    ])
    assert report["summary"]["distinct_gaps"] == 3


def test_violations_are_tracked_apart_from_gaps():
    """A governed thing being broken is a different signal from a gap: it is a
    roadmap item for the code, not for the graph."""
    report = project_coverage([
        _gap("p1", "q1"),
        {"type": "conformance.completed:VIOLATES", "gap_id": "",
         "payload": {"question": "a broken rule"}},
    ])
    assert report["summary"]["distinct_gaps"] == 1
    assert report["summary"]["distinct_violations"] == 1


def test_an_empty_log_is_an_empty_roadmap_not_an_error():
    report = project_coverage([])
    assert report["gaps"] == []
    assert report["summary"]["distinct_gaps"] == 0
