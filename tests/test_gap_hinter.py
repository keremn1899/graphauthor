"""Gap hints must never contradict the canonical evidence packet."""

from __future__ import annotations

from gap_hinter import apply_gap_type_hints


NODES = [
    {"id": "practice_p", "label": "Practice P"},
    {"id": "task_t", "label": "Task T"},
]
QUERY = "What CONTAINS edge connects Practice P to Task T?"


def test_present_typed_edge_does_not_create_a_missing_relationship():
    gaps = apply_gap_type_hints(
        [],
        QUERY,
        node_records=NODES,
        edge_records=[
            {
                "source_id": "practice_p",
                "target_id": "task_t",
                "edge_type": "contains",
            }
        ],
    )

    assert gaps == []


def test_absent_typed_edge_creates_a_missing_relationship():
    gaps = apply_gap_type_hints(
        [],
        QUERY,
        node_records=NODES,
        edge_records=[],
    )

    assert [gap["gap_type"] for gap in gaps] == ["missing_relationship"]


def test_canonical_edge_type_key_prevents_false_schema_gap():
    gaps = apply_gap_type_hints(
        [],
        "What is the exact signing date as a timestamp?",
        node_records=NODES,
        edge_records=[
            {
                "source_id": "practice_p",
                "target_id": "task_t",
                "edge_type": "expresses",
            }
        ],
    )

    assert gaps == []


def test_graph_domain_qualifiers_are_not_missing_concepts():
    gaps = apply_gap_type_hints(
        [],
        "Which NIST SSDF task governs released software?",
        node_records=[{"id": "rv_1_2", "label": "RV.1.2"}],
        edge_records=[],
        known_context="NIST SSDF 1.1",
    )

    assert gaps == []


def test_a_token_the_graph_knows_is_not_reported_as_missing():
    """A gap is a claim about the GRAPH, made from packet evidence.

    Measured on the NIST SSDF held-out set: two of three queries came back
    advising "Add a node for 'NIST'" / "'SSDF'" while `nist_ssdf_1_1`
    ("NIST SSDF 1.1") was in the graph and simply had not been retrieved.
    Reporting a retrieval miss as a corpus gap sends an operator to author a
    node they already have — and it is the unretrieved-vs-absent conflation
    the engine exists to prevent, in its own output.
    """
    from gap_hinter import apply_gap_type_hints

    query = "Which NIST SSDF task governs identifying vulnerabilities?"
    packet = [{"id": "task_rv_1_1", "label": "Gather vulnerability information"}]

    # Without the check, the old behaviour: a confabulated gap.
    blind = apply_gap_type_hints([], query, node_records=packet)
    assert blind and blind[0]["specific_node_or_concept"] == "nist", (
        "guard the guard: this case must still confabulate when the hinter "
        "can only see the packet, or the test below proves nothing")

    # With it, silence — the graph knows the token.
    seeing = apply_gap_type_hints(
        [], query, node_records=packet,
        token_in_graph=lambda t: t.lower() in {"nist", "ssdf"})
    assert seeing == [], f"reported a gap for a token the graph holds: {seeing}"


def test_an_unreachable_graph_does_not_manufacture_a_gap():
    """The failure-open direction is chosen deliberately.

    If the existence check cannot answer, the hinter must not assert absence.
    A missing gap is a smaller harm than a fabricated one.
    """
    from gap_hinter import apply_gap_type_hints

    def _explodes(_token: str) -> bool:
        raise RuntimeError("graph unreachable")

    try:
        out = apply_gap_type_hints(
            [], "Which NIST task applies?",
            node_records=[{"id": "x", "label": "Something else"}],
            token_in_graph=_explodes)
    except RuntimeError:
        raise AssertionError("the hinter must not propagate a lookup failure")
    assert isinstance(out, list)
