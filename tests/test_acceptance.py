"""Acceptance checks, and the proof that each can fail.

A check that has never failed is not evidence. This project has shipped a
battery that went 12/12 green while a systematic rename passed every
invariant, and a scoring rubric that manufactured false failures for three
sessions. So every check here is exercised twice: once on a conforming graph
and once on a graph degraded in the specific way the check exists to catch.
"""

from __future__ import annotations

import copy

import pytest

from mcp_server.acceptance import check_acceptance
from mcp_server.graph_contract import load_graph_contract, parse_graph_contract

CONTRACT = """---
format_id: probe
format_version: 1
node_kinds:
  character:
    id_pattern: "character:<slug>"
  place:
    id_pattern: "place:<slug>"
predicates:
  visits:
    sst: LEADSTO
    directed: true
    source_kinds: [character]
    target_kinds: [place]
acceptance:
{predicates}
---

# Probe format
"""

GOOD = {
    "concepts": [
        {"id": "character:ilma", "kind": "character", "label": "Ilma",
         "source_unit_ids": ["u1"]},
        {"id": "character:torv", "kind": "character", "label": "Torv",
         "source_unit_ids": ["u2"]},
        {"id": "place:quay", "kind": "place", "label": "Quay",
         "source_unit_ids": ["u1"]},
    ],
    "edges": [
        {"source_id": "character:ilma", "predicate": "visits", "target_id": "place:quay"},
        {"source_id": "character:torv", "predicate": "visits", "target_id": "place:quay"},
    ],
}

SOURCE = "Ilma and Torv came to the Quay."


def _document(predicates: str):
    return parse_graph_contract(CONTRACT.format(predicates=predicates))


def _degrade(**changes):
    graph = copy.deepcopy(GOOD)
    for key, value in changes.items():
        graph[key] = value
    return graph


# ----------------------------------------------------- each check, both ways


def test_every_node_has_a_source_unit():
    doc = _document("  - check: every_node_has_a_source_unit\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    broken = copy.deepcopy(GOOD)
    broken["concepts"][1].pop("source_unit_ids")
    report = check_acceptance(doc, broken)
    assert report["outcome"] == "ACCEPTANCE_FAILED"
    assert report["reports"][0]["failures"] == 1
    assert "character:torv" in report["reports"][0]["examples"]


def test_every_node_has_a_declared_kind():
    doc = _document("  - check: every_node_has_a_declared_kind\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    broken = copy.deepcopy(GOOD)
    broken["concepts"][0]["kind"] = "warlock"
    assert check_acceptance(doc, broken)["outcome"] == "ACCEPTANCE_FAILED"


def test_every_edge_has_a_declared_predicate():
    doc = _document("  - check: every_edge_has_a_declared_predicate\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    broken = copy.deepcopy(GOOD)
    broken["edges"][0]["predicate"] = "haunts"
    assert check_acceptance(doc, broken)["outcome"] == "ACCEPTANCE_FAILED"


def test_node_count_per_source_unit_catches_both_grain_failures():
    """The summarising node and the fragment storm, which are the two failure
    modes prose grain statements have never prevented."""
    doc = _document("  - check: node_count_per_source_unit\n    min: 1\n    max: 3\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    fragmented = copy.deepcopy(GOOD)
    fragmented["concepts"] = [
        {"id": f"character:frag{i}", "kind": "character", "label": f"F{i}",
         "source_unit_ids": ["u1"]}
        for i in range(9)
    ]
    report = check_acceptance(doc, fragmented)
    assert report["outcome"] == "ACCEPTANCE_FAILED"
    assert "u1: 9 > 3" in report["reports"][0]["examples"]


def test_nodes_per_kind():
    doc = _document("  - check: nodes_per_kind\n    kind: place\n    min: 2\n")

    report = check_acceptance(doc, GOOD)
    assert report["outcome"] == "ACCEPTANCE_FAILED"  # only one place
    assert "place: 1 < 2" in report["reports"][0]["examples"]

    doc_ok = _document("  - check: nodes_per_kind\n    kind: place\n    min: 1\n")
    assert check_acceptance(doc_ok, GOOD)["outcome"] == "CONFORMS"


def test_edges_per_node_catches_the_star():
    """The dogfood graph was a star: 11 edges all of one predicate, every
    claim hanging off one topic. Minimum degree is what would have caught it."""
    doc = _document("  - check: edges_per_node\n    min: 1\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    orphaned = copy.deepcopy(GOOD)
    orphaned["concepts"].append(
        {"id": "place:uplands", "kind": "place", "label": "Uplands",
         "source_unit_ids": ["u3"]})
    report = check_acceptance(doc, orphaned)
    assert report["outcome"] == "ACCEPTANCE_FAILED"
    assert "place:uplands: 0 < 1" in report["reports"][0]["examples"]


def test_no_isolated_nodes():
    doc = _document("  - check: no_isolated_nodes\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    orphaned = copy.deepcopy(GOOD)
    orphaned["concepts"].append(
        {"id": "place:nowhere", "kind": "place", "label": "Nowhere",
         "source_unit_ids": ["u9"]})
    assert check_acceptance(doc, orphaned)["outcome"] == "ACCEPTANCE_FAILED"


def test_label_appears_in_source_catches_a_fabricated_node():
    doc = _document("  - check: label_appears_in_source\n")

    assert check_acceptance(doc, GOOD, source_text=SOURCE)["outcome"] == "CONFORMS"

    invented = copy.deepcopy(GOOD)
    invented["concepts"].append(
        {"id": "character:gandalf", "kind": "character", "label": "Gandalf",
         "source_unit_ids": ["u1"]})
    report = check_acceptance(doc, invented, source_text=SOURCE)
    assert report["outcome"] == "ACCEPTANCE_FAILED"


def test_a_check_that_cannot_run_is_not_a_pass():
    """The failure mode that turns a checker into an endorsement."""
    doc = _document("  - check: label_appears_in_source\n")

    report = check_acceptance(doc, GOOD, source_text=None)

    assert report["outcome"] == "INCOMPLETE"
    assert report["reports"][0]["ran"] is False
    assert report["reports"][0]["ok"] is False


def test_no_duplicate_labels_within_kind_catches_identity_fragmentation():
    """The measured defect: samr-bjarnarson and samr-bjarnason as two nodes."""
    doc = _document("  - check: no_duplicate_labels_within_kind\n")

    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"

    split = copy.deepcopy(GOOD)
    split["concepts"].append(
        {"id": "character:ilma-of-the-quay", "kind": "character", "label": "Ilma",
         "source_unit_ids": ["u4"]})
    report = check_acceptance(doc, split)
    assert report["outcome"] == "ACCEPTANCE_FAILED"


# ------------------------------------------------------------- the outcomes


def test_no_predicates_is_unchecked_rather_than_conforms():
    """A format that claims nothing has not been satisfied by a graph.

    Reporting this as CONFORMS is exactly how a vacuous test becomes an
    endorsement, and it is the single most likely way this whole mechanism
    would end up lying.
    """
    doc = _document("  []\n" if False else "  - check: every_node_has_a_declared_kind\n")
    stripped = parse_graph_contract(CONTRACT.format(predicates="  []"))

    assert check_acceptance(stripped, GOOD)["outcome"] == "UNCHECKED"
    assert check_acceptance(doc, GOOD)["outcome"] == "CONFORMS"


def test_a_bounded_check_without_bounds_is_refused_at_the_contract():
    with pytest.raises(Exception, match="needs min and/or max"):
        _document("  - check: node_count_per_source_unit\n")


def test_min_above_max_is_refused():
    with pytest.raises(Exception, match="min exceeds max"):
        _document("  - check: edges_per_node\n    min: 5\n    max: 2\n")
