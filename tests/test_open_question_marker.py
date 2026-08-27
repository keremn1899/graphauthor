"""A graph must be able to say "we know this is undecided", not only "we chose not to rule".

`classify_absence` exists because an agent facing silence cannot tell a real
gap from a deliberate local choice, and measured three of each, refused all six
— safe, and half wrong. A `local_choice` disposition fixed one half by
materializing `DOES NOT GOVERN:` into the graph. The other half stayed in the
event log, so a later agent — one that never saw the escalation — still read
plain silence and fell back to a structural guess.

These tests hold the two declarations apart. They are the same object
structurally and opposite in instruction:

    DOES NOT GOVERN: x   ->  proceed on your own judgement
    OPEN QUESTION:   x   ->  stop; a decision is owed
"""
from __future__ import annotations

from pathlib import Path

import pytest
import real_ladybug as lb

from mcp_server.materiality import (
    classify_absence,
    declared_exclusion_marker,
    dispose_absence,
    is_open_question,
    is_verdict_neutral_exclusion,
    materialize_open_question,
    open_question_marker,
)

PREDICATE = "which service owns session expiry"


def _nodes(*texts: str, subject: str = "") -> dict[str, dict]:
    """`_subject_match` reads label/anchor/id, not text — so a node that models
    the subject has to say so where the matcher looks."""
    return {f"n{i}": {"text_content": t, "label": subject, "semantic_anchor": subject}
            for i, t in enumerate(texts)}


def _graph(path: Path) -> Path:
    """A graph the write path can actually use.

    `_create_schema` in the fixture helper is one of three `CREATE NODE TABLE
    Concept` definitions in this tree and the only current one is engine's, so
    the fixture table has no `claim_kind`. The write path needs it —
    `graph_fingerprint` reads it to bind a proposal to a graph version — and
    without the migration this fails as `Binder exception: Cannot find property
    claim_kind`, which is the same wall a greenfield project hits if it
    bootstraps through anything but engine.
    """
    from engine import migrate_claim_kind_columns
    from mcp_server.fixture import _create_schema

    db = lb.Database(str(path))
    conn = lb.Connection(db)
    _create_schema(conn)
    migrate_claim_kind_columns(conn)
    del conn, db
    return path


# --- the declaration itself -------------------------------------------------

def test_an_open_question_is_detected_by_subject_not_by_exact_string():
    graph = _nodes(open_question_marker("service ownership of session expiry"))
    assert is_open_question(graph, PREDICATE)
    assert not is_open_question(graph, "which retry backoff constant to use")


def test_a_declared_open_question_outranks_the_structural_guess():
    """The point of declaring: the answer stops being advisory.

    `likely_material` is a guess from token overlap. `declared_open` is a
    recorded human act, and an agent may act on the difference — stop, rather
    than weigh a prior.
    """
    guessed = classify_absence(
        PREDICATE, _nodes("Sessions are held per user.", subject="session expiry ownership"))
    declared = classify_absence(PREDICATE, _nodes(open_question_marker(PREDICATE)))

    assert guessed["prior"] == "likely_material"
    assert declared["prior"] == "declared_open"
    assert declared["signals"]["open_question_found"] is True


def test_the_two_declarations_give_opposite_instructions():
    excluded = classify_absence(PREDICATE, _nodes(declared_exclusion_marker(PREDICATE)))
    opened = classify_absence(PREDICATE, _nodes(open_question_marker(PREDICATE)))

    assert excluded["prior"] == "already_excluded"
    assert opened["prior"] == "declared_open"
    assert excluded["prior"] != opened["prior"]


def test_contradictory_declarations_are_surfaced_not_resolved_by_precedence():
    """Silently preferring either would hand an agent a confident instruction
    the graph does not support, and hide an authoring defect that only a human
    can settle."""
    both = classify_absence(
        PREDICATE,
        _nodes(declared_exclusion_marker(PREDICATE), open_question_marker(PREDICATE)),
    )

    assert both["prior"] == "declared_conflict"
    assert both["signals"]["declared_exclusion_found"] is True
    assert both["signals"]["open_question_found"] is True


# --- it must never become authority ----------------------------------------

def test_the_materialized_node_cannot_flip_a_ruling(tmp_path):
    """Same construction as the exclusion, so the same proof applies: no
    ADJUDICATES and no governance-conferring edge means it cannot change any
    GOVERNED verdict. Without this an "open question" would be a way to write
    governance through a path with no rule review."""
    from mcp_server.proposals import validate_proposal

    out = materialize_open_question(
        _graph(tmp_path / "g.lbug"), tmp_path / "store.sqlite",
        predicate=PREDICATE, primary_source="ADR-12", emit_submission=False,
    )
    assert out.get("proposal_id"), out

    import json
    from interaction.write_path_store import WritePathStore

    store = WritePathStore(tmp_path / "store.sqlite")
    try:
        record = store.get_proposal(out["proposal_id"])
    finally:
        store.close()
    prop, err = validate_proposal(json.loads(record["encoding_json"]), tmp_path / "g.lbug")
    assert prop is not None, err

    neutral, why = is_verdict_neutral_exclusion(prop)
    assert neutral, why
    assert "ADJUDICATES" not in json.loads(record["encoding_json"])["concepts"][0]["text_content"]


# --- it is a sourced act ----------------------------------------------------

def test_writing_a_declaration_into_the_graph_requires_a_source(tmp_path):
    refused = dispose_absence(
        tmp_path / "store.sqlite", predicate=PREDICATE, category="arch_material",
        actor="kerem", primary_source="", db_path=_graph(tmp_path / "g.lbug"),
    )
    assert "PrimarySource" in refused.get("error", "")


def test_an_arch_material_disposition_materializes_the_open_question(tmp_path):
    out = dispose_absence(
        tmp_path / "store.sqlite", predicate=PREDICATE, category="arch_material",
        actor="kerem", primary_source="ADR-12", db_path=_graph(tmp_path / "g.lbug"),
    )
    assert out.get("error") is None, out
    assert out.get("open_question_proposal_id") or "open_question" in str(out)
