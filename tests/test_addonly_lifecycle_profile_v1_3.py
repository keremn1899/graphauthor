"""Add-only lifecycle — the construction case that bears on the edit gate.

V1.2 pre-populated `valid_to` on removed versions, which assumed the version is
EDITED on removal. `ChangeSet.from_proposal_encoding` emits only ADD_CONCEPT and
ADD_EDGE, so a live host cannot emit that edit. These tests build every series
with inserts alone and check that lifecycle still reads correctly.
"""

from __future__ import annotations

import json

from benchmarks.proposal_host.temporal_edit_profile_v1 import (
    in_force_at,
    validate_intervals,
    validate_lifecycle,
)
from benchmarks.proposal_host.addonly_lifecycle_profile_v1_3 import run


def _graph(tmp_path):
    run(tmp_path / "addonly")
    return tmp_path / "addonly/graph/graph.lbug"


def test_addonly_lifecycle_profile_passes_zero_model(tmp_path):
    report = run(tmp_path / "addonly")

    assert report["overall"] == "PASS"
    assert report["passed"] == report["total"] == 10
    assert report["model_calls"] == 0
    assert report["graph"]["mutations"] == 0
    assert json.loads(
        (tmp_path / "addonly/report.json").read_text())["overall"] == "PASS"


def test_a_repeal_that_mutates_nothing_still_withdraws_the_rule(tmp_path):
    """The silent-permission regression: before deriving ends from events, this
    read returned IN_FORCE_AT_TIME with authority a year after withdrawal."""
    graph = _graph(tmp_path)

    during = in_force_at(graph, "addonly_bare_repeal", "2021-01-01T00:00:00Z")
    after = in_force_at(graph, "addonly_bare_repeal", "2024-01-01T00:00:00Z")

    assert during["kind"] == "IN_FORCE_AT_TIME"
    assert during["authority_eligible_now"] is False
    assert after["kind"] == "REMOVED"
    assert after["removed_by_event"] == "ao_removal_event"
    assert "node_id" not in after


def test_addonly_and_mutated_representations_agree(tmp_path):
    """MATCHED TWINS — the same supersession, one built add-only and one with
    the stored end pre-written as an edit would leave it."""
    graph = _graph(tmp_path)

    for at, expect_v1 in (("2021-01-01T00:00:00Z", True),
                          ("2024-01-01T00:00:00Z", False)):
        addonly = in_force_at(graph, "addonly_supersession", at)
        mutated = in_force_at(graph, "mutated_supersession_control", at)
        assert addonly["kind"] == mutated["kind"] == "IN_FORCE_AT_TIME"
        assert (addonly["node_id"] == "ao_super_v1") is expect_v1
        assert (mutated["node_id"] == "mut_super_v1") is expect_v1
        assert (addonly["authority_eligible_now"]
                == mutated["authority_eligible_now"])


def test_stored_field_view_is_misleading_on_the_addonly_path(tmp_path):
    """Why the lifecycle verdict cannot inherit the interval verdict.

    Add-only leaves every version stored open-ended, so `validate_intervals`
    reports an overlap for any superseded series by construction, even though
    the closing event resolves it cleanly."""
    graph = _graph(tmp_path)

    intervals = validate_intervals(graph, "addonly_supersession")
    lifecycle = validate_lifecycle(graph, "addonly_supersession")

    assert intervals["valid"] is False
    assert "overlap:ao_super_v1:ao_super_v2" in intervals["problems"]
    assert lifecycle["valid"] is True
    assert lifecycle["lifecycle_problems"] == []


def test_disagreeing_end_is_reported_and_the_earlier_one_wins(tmp_path):
    graph = _graph(tmp_path)

    lifecycle = validate_lifecycle(graph, "stored_end_disagrees_with_event")
    read = in_force_at(graph, "stored_end_disagrees_with_event",
                       "2024-01-01T00:00:00Z")

    assert lifecycle["valid"] is False
    assert ("interval_event_disagreement:dis_v1:dis_removal_event"
            in lifecycle["lifecycle_problems"])
    # event says 2023, stored field says 2026 — closing sooner is the safe side
    assert read["kind"] == "REMOVED"


def test_a_rule_never_repealed_is_unaffected(tmp_path):
    graph = _graph(tmp_path)

    result = in_force_at(graph, "addonly_never_repealed", "2024-01-01T00:00:00Z")

    assert result["kind"] == "IN_FORCE_AT_TIME"
    assert result["authority_eligible_now"] is True
    assert validate_lifecycle(graph, "addonly_never_repealed")["valid"] is True
