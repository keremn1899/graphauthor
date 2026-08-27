"""Removal, deprecation, and gap explanation over decision series (V1.2).

The load-bearing structure here is two MATCHED PAIRS: series with identical
version intervals that differ only by the presence of a lifecycle event. If the
closing-event discriminator did nothing, each pair would come out the same.
"""

from __future__ import annotations

import json

from benchmarks.proposal_host.temporal_edit_profile_v1 import (
    in_force_at,
    validate_lifecycle,
)
from benchmarks.proposal_host.temporal_lifecycle_profile_v1_2 import run


def _graph(tmp_path):
    run(tmp_path / "lifecycle")
    return tmp_path / "lifecycle/graph/graph.lbug"


def test_lifecycle_profile_passes_zero_model(tmp_path):
    report = run(tmp_path / "lifecycle")

    assert report["overall"] == "PASS"
    assert report["passed"] == report["total"] == 10
    assert report["model_calls"] == 0
    assert all(report["checks"].values())
    assert json.loads(
        (tmp_path / "lifecycle/report.json").read_text())["overall"] == "PASS"


def test_gap_pair_differs_only_by_the_closing_event(tmp_path):
    """MATCHED PAIR — both series are 2020->2022 then 2025->open."""
    graph = _graph(tmp_path)

    repeal = validate_lifecycle(graph, "repeal_then_reintroduce")
    forgot = validate_lifecycle(graph, "forgotten_close")

    assert repeal["valid"] is True
    assert repeal["explained_gaps"] == [
        {"gap": "repeal_v1:repeal_v2", "closed_by": "removal_repeal_series"}]
    assert forgot["valid"] is False
    assert forgot["lifecycle_problems"] == ["unexplained_gap:forgot_v1:forgot_v2"]
    # the underlying interval structure really is identical
    assert repeal["intervals"]["valid"] == forgot["intervals"]["valid"] is True


def test_tail_pair_differs_only_by_the_closing_event(tmp_path):
    """MATCHED PAIR — both series are a single closed version."""
    graph = _graph(tmp_path)

    removed = validate_lifecycle(graph, "removed_series")
    tail = validate_lifecycle(graph, "unclosed_tail")

    assert removed["valid"] is True
    assert tail["valid"] is False
    assert tail["lifecycle_problems"] == ["unexplained_series_end:tail_v1"]


def test_removed_is_distinct_from_never_governed(tmp_path):
    """The distinction the product sells: an absent rule versus a decision to
    have none."""
    graph = _graph(tmp_path)

    removed = in_force_at(graph, "removed_series", "2024-01-01T00:00:00Z")
    absent = in_force_at(graph, "forgotten_close", "2023-01-01T00:00:00Z")

    assert removed["kind"] == "REMOVED"
    assert removed["removed_by_event"] == "removal_removed_series"
    assert removed["primary_source"] and removed["proposal_id"]
    assert absent["kind"] == "NO_IN_FORCE_DECISION"
    assert removed["safe_to_act"] is absent["safe_to_act"] is False


def test_removed_never_reads_as_a_governing_decision(tmp_path):
    graph = _graph(tmp_path)

    for at in ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
               "2099-01-01T00:00:00Z"):
        result = in_force_at(graph, "removed_series", at)
        assert result["kind"] == "REMOVED"
        assert "node_id" not in result
        assert result.get("authority_eligible_now") is None


def test_deprecation_marks_but_does_not_withdraw(tmp_path):
    """Treating a deprecated rule as withdrawn would be silent permission."""
    graph = _graph(tmp_path)

    before = in_force_at(graph, "deprecated_current", "2022-01-01T00:00:00Z")
    after = in_force_at(graph, "deprecated_current", "2024-01-01T00:00:00Z")

    assert before["kind"] == after["kind"] == "IN_FORCE_AT_TIME"
    assert before["deprecated"] is False
    assert after["deprecated"] is True
    assert after["deprecated_by_event"] == "deprecation_deprecated_current"
    # still applying authority after deprecation takes effect
    assert before["authority_eligible_now"] is after["authority_eligible_now"] is True


def test_a_defective_series_does_not_contaminate_a_clean_one(tmp_path):
    graph = _graph(tmp_path)

    assert validate_lifecycle(graph, "clean_control")["valid"] is True
    assert in_force_at(
        graph, "clean_control", "2024-06-01T00:00:00Z")["node_id"] == "lc_clean_v1"
