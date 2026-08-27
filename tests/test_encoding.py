"""Workbook encoding is mechanical, domain-free, and source-bound."""

from __future__ import annotations

import pytest

from source_pipeline.encoding import (
    EncodingError,
    canonical_encoding,
    to_graph,
    validate_encoding,
    write_graph,
)
from source_pipeline.workbook import Atom, write_workbook


GOOD = {
    "graph": {"id": "people", "domain": "organisation"},
    "concepts": [
        {
            "id": "person:bob",
            "kind": "person",
            "label": "Bob",
            "source_unit_ids": ["a2", "a1", "a2"],
        },
        {
            "id": "team:payments",
            "kind": "team",
            "label": "Payments",
            "source_unit_ids": ["a1"],
        },
    ],
    "edges": [
        {
            "source_id": "person:bob",
            "predicate": "member_of",
            "target_id": "team:payments",
            "sst_type": "EXPRESSES",
            "source_unit_ids": ["a1"],
        }
    ],
}


def test_canonical_output_is_repeatable():
    once = canonical_encoding(GOOD)
    shuffled = {
        "graph": GOOD["graph"],
        "concepts": list(reversed(GOOD["concepts"])),
        "edges": list(reversed(GOOD["edges"])),
    }
    twice = canonical_encoding(shuffled)

    assert once == twice
    assert once["concepts"][0]["source_unit_ids"] == ["a1", "a2"]


def test_valid_encoding_has_no_domain_contract():
    assert validate_encoding(GOOD) == []


def test_every_mechanical_problem_is_reported_together():
    broken = {
        "concepts": [
            {"id": "person:bob", "kind": "", "source_unit_ids": ["missing"]},
            {"id": "person:bob", "kind": "person", "synthetic_reason": "seed"},
            {"kind": "person"},
        ],
        "edges": [
            {
                "source_id": "person:bob",
                "predicate": "",
                "target_id": "team:missing",
                "sst_type": "MAGIC",
            }
        ],
    }
    problems = validate_encoding(broken, known_source_unit_ids={"a1"})
    joined = " | ".join(problems)

    assert "has no kind" in joined
    assert "unknown source unit 'missing'" in joined
    assert "duplicate concept id" in joined
    assert "has no id" in joined
    assert "target 'team:missing' is not a concept" in joined
    assert "has no predicate" in joined
    assert "sst_type" in joined
    assert "needs source_unit_ids" in joined


def test_source_backed_and_synthetic_are_explicitly_disjoint():
    row = {
        "concepts": [{
            "id": "topic:x",
            "kind": "topic",
            "source_unit_ids": ["a1"],
            "synthetic_reason": "navigation",
        }],
        "edges": [],
    }
    assert "cannot be both source-backed and synthetic" in " | ".join(
        validate_encoding(row)
    )


def test_dangling_edge_is_refused():
    broken = {
        "concepts": [{
            "id": "person:bob",
            "kind": "person",
            "synthetic_reason": "fixture",
        }],
        "edges": [{
            "source_id": "person:bob",
            "predicate": "member_of",
            "target_id": "team:missing",
            "sst_type": "EXPRESSES",
            "synthetic_reason": "fixture",
        }],
    }
    with pytest.raises(EncodingError, match="is not a concept"):
        to_graph(broken)


def test_program_chooses_predicate_and_portable_geometry():
    graph = to_graph(GOOD)
    edge = graph.edges[0]

    assert edge.label == "member_of"
    assert edge.sst_type == "EXPRESSES"


def test_materialization_writes_graph_and_source_sidecar(tmp_path):
    source = tmp_path / "directory.txt"
    source.write_text("Bob is a member of Payments.")
    atom = Atom(
        atom_id="a1",
        source_id="directory",
        unit_id="u1",
        text=source.read_text(),
        start=0,
        end=28,
        locator=str(source),
    )
    book = write_workbook(
        tmp_path / "workbook",
        sources=[source],
        atoms=[atom],
        producer="build.py:test",
    )
    encoding = {
        "concepts": [
            {
                "id": "person:bob",
                "kind": "person",
                "label": "Bob",
                "source_unit_ids": ["a1"],
            },
            {
                "id": "team:payments",
                "kind": "team",
                "label": "Payments",
                "source_unit_ids": ["u1"],
            },
        ],
        "edges": [{
            "source_id": "person:bob",
            "predicate": "member_of",
            "target_id": "team:payments",
            "sst_type": "EXPRESSES",
            "source_unit_ids": ["a1"],
        }],
    }

    out = write_graph(encoding, tmp_path / "built.lbug", workbook=book)

    assert out.exists()
    assert (tmp_path / "built.lbug.sources.json").exists()
    assert not (tmp_path / "graph.md").exists()
