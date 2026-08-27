"""The node census must not depend on how the structural index was built.

The census is sorted by betweenness (or degree), and ties are the common case
rather than the corner — on the 31-node hexagonal fixture 12 nodes sit at
betweenness 0.0. With no tie-break the sort was stable over the index's
INSERTION order, which differs by provenance: recomputing builds the index by
iterating a set, so it varies per process with the hash seed, while loading the
`.idx` sidecar freezes whatever order that file happened to be written in.

That is not cosmetic. The census feeds the Planner briefing and entity
resolution, and resolution takes the first substring hit. Measured on the
hexagonal fixture with the sidecar file and every value held identical and ONLY
the key order permuted: as-written GOVERNED 2/2, alphabetical UNGOVERNED 2/2,
reversed UNGOVERNED 2/2 — a governance verdict turning on dict ordering, and
the reason a graph answered one way in place and another way as a copy.

These tests pin the ordering invariant, not the verdict. That the verdict is
sensitive to census order at all is a SEPARATE defect; a canonical order
stabilises it rather than removing it.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixture_db import create_fixture_db


def _census_ids(conn, index) -> list[str]:
    """Deliberately `compute_compass`, not `get_compass`.

    `get_compass` memoises into a module-level `_compass` and ignores the index
    it was handed on every call after the first — so a version of this test
    written against it passed with the tie-break removed, comparing one cached
    object with itself three times.
    """

    from engine import compute_compass

    return [entry["id"] for entry in compute_compass(conn, index).node_census]


def _landmark_ids(conn, index) -> list[str]:
    from engine import compute_compass

    return [entry["id"] for entry in compute_compass(conn, index).landmark_nodes]


def test_census_order_survives_a_permuted_index(tmp_path: Path) -> None:
    """Same facts, different insertion order, identical census."""

    from engine import compute_structural_index

    conn = create_fixture_db("lotr", tmp_path / "order.lbug")
    index = compute_structural_index(conn)
    assert len(index) > 2, "fixture too small to order-test"

    baseline = _census_ids(conn, index)
    reversed_index = dict(reversed(list(index.items())))
    sorted_index = {k: index[k] for k in sorted(index)}

    assert _census_ids(conn, reversed_index) == baseline
    assert _census_ids(conn, sorted_index) == baseline


def test_landmark_order_survives_a_permuted_index(tmp_path: Path) -> None:
    """Landmarks share the census sort keys and enter the Planner briefing."""
    from engine import compute_structural_index

    conn = create_fixture_db("lotr", tmp_path / "landmarks.lbug")
    index = compute_structural_index(conn)
    baseline = _landmark_ids(conn, index)

    assert _landmark_ids(conn, dict(reversed(list(index.items())))) == baseline
    assert _landmark_ids(conn, {key: index[key] for key in sorted(index)}) == baseline


def test_ties_are_broken_and_not_left_to_insertion_order(tmp_path: Path) -> None:
    """Guard the guard: if the fixture ever stops having ties, the test above
    passes for free and stops protecting anything."""

    from engine import compute_structural_index

    conn = create_fixture_db("lotr", tmp_path / "ties.lbug")
    index = compute_structural_index(conn)

    any_bc = any(f.betweenness_centrality > 0 for f in index.values())
    keys = [f.betweenness_centrality if any_bc else f.total_degree
            for f in index.values()]
    assert len(keys) != len(set(keys)), (
        "no tied sort keys in this fixture — the ordering test cannot fail, "
        "so it no longer guards the census against insertion order")


# --------------------------------------------------------------------- schema


def test_an_unusable_contingency_step_does_not_discard_the_primary_plan():
    """The Planner's whole output was being thrown away over a fallback step.

    `RetrievalStep.assign_to` and `.params` were required, so a contingency
    step emitted without them failed validation for the ENTIRE `PlannerOutput`
    — discarding a complete, correct primary program and dropping the engine to
    `schema_fallback`. Measured on the hexagonal fixture, ~40% of what_governs
    calls hit it, and the surface reports the degraded result as a coverage
    verdict, so it reads as "no policy found" rather than "the plan was
    discarded".
    """

    from models import ContingencySpec

    spec = ContingencySpec.model_validate(
        {"trigger": "x", "fallback_steps": [{"tool": "hop_expansion"}]}
    )
    assert spec.fallback_steps == [], "a step with nowhere to store its result must be dropped"

    kept = ContingencySpec.model_validate(
        {"fallback_steps": [{"tool": "hop_expansion", "assign_to": "y"}]}
    )
    assert [(s.tool, s.assign_to, s.params) for s in kept.fallback_steps] == [
        ("hop_expansion", "y", {})
    ], "a usable step must survive, with params defaulting rather than failing"


def test_primary_steps_stay_strict():
    """Dropping a load-bearing primary step would change the answer instead of
    preserving it, so only the contingency list is made tolerant."""

    import pytest
    from pydantic import ValidationError

    from models import RetrievalStep

    with pytest.raises(ValidationError):
        RetrievalStep.model_validate({"tool": "hop_expansion"})
