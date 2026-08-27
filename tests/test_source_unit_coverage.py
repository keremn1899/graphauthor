"""Partial retrieval of a source unit must be visible in the packet.

On a finely cut graph a section of source becomes many nodes, and a packet
holding three of a section's fifteen nodes is indistinguishable from one holding
all fifteen — same shape, same types, no signal. Because every node carries the
units it came from, "is this unit whole?" is a set operation, so it belongs in
the deterministic layer rather than in a tier's judgement about sufficiency.

Reported, never repaired: completing the unit is a retrieval decision with a
cost, and making it here would silently overrule the Planner's program.
"""

from __future__ import annotations

import backend_tools
from backend_tools import (
    annotate_source_unit_coverage,
    append_to_evidence_packet,
    source_unit_coverage,
)

INDEX = {
    "repo:code:backend_tools": [f"bt{i}" for i in range(15)],
    "repo:code:models": ["m0", "m1"],
}


def test_a_partly_retrieved_unit_is_named_with_its_shortfall():
    partial = source_unit_coverage(INDEX, {"bt0", "bt1", "bt2", "m0", "m1"})

    assert len(partial) == 1
    found = partial[0]
    assert found["source_unit_id"] == "repo:code:backend_tools"
    assert found["nodes_in_packet"] == 3
    assert found["nodes_in_graph"] == 15
    assert len(found["missing_node_ids"]) == 12


def test_a_whole_unit_is_not_reported():
    """Only the shortfall is news. A complete unit needs no line."""

    assert source_unit_coverage(INDEX, {"m0", "m1"}) == []


def test_an_untouched_unit_is_not_reported():
    """Every unit the packet never reached is not a partial retrieval — it is
    simply outside the query, and listing them would bury the real finding."""

    partial = source_unit_coverage(INDEX, {f"bt{i}" for i in range(15)})

    assert partial == []


def test_the_worst_covered_unit_comes_first():
    index = {
        "nearly_whole": ["a1", "a2", "a3", "a4"],
        "barely_touched": ["b1", "b2", "b3", "b4"],
    }
    partial = source_unit_coverage(index, {"a1", "a2", "a3", "b1"})

    assert [p["source_unit_id"] for p in partial] == ["barely_touched", "nearly_whole"]


def test_a_graph_without_attribution_reports_unknown_not_complete(monkeypatch):
    """Empty coverage on an unattributed graph must not read as 'all whole'."""

    monkeypatch.setattr(
        "engine.get_source_unit_index", lambda conn: {}, raising=False
    )
    packet = annotate_source_unit_coverage(None, {"node_records": [{"id": "x"}]})

    assert packet["source_unit_coverage"] == []
    assert packet["source_unit_attribution"] is False


def test_annotation_survives_an_append_that_cannot_see_the_index(monkeypatch):
    """Recovery has no connection. It must not erase a finding it cannot recompute."""

    monkeypatch.setattr(
        "engine.get_source_unit_index", lambda conn: {}, raising=False
    )
    packet = {
        "node_records": [{"id": "bt0"}],
        "source_unit_attribution": True,
        "source_unit_coverage": [
            {
                "source_unit_id": "repo:code:backend_tools",
                "nodes_in_packet": 1,
                "nodes_in_graph": 15,
                "missing_node_ids": [],
            }
        ],
    }
    out = append_to_evidence_packet(packet, new_nodes=[{"id": "bt1"}])

    assert out["source_unit_attribution"] is True
    assert out["source_unit_coverage"][0]["source_unit_id"] == "repo:code:backend_tools"


def test_an_append_that_completes_a_unit_clears_its_finding(monkeypatch):
    """A stale shortfall is worse than none — it would make Battalion hedge
    about evidence it now holds whole."""

    monkeypatch.setattr(
        "engine.get_source_unit_index",
        lambda conn: {"u": ["n0", "n1"]},
        raising=False,
    )
    packet = {"node_records": [{"id": "n0"}]}
    annotate_source_unit_coverage(None, packet)
    assert packet["source_unit_coverage"][0]["nodes_in_packet"] == 1

    out = append_to_evidence_packet(packet, new_nodes=[{"id": "n1"}])

    assert out["source_unit_coverage"] == []
    assert out["source_unit_attribution"] is True


def test_the_annotation_never_removes_records():
    """It is an annotation on an append-only packet, so it must add only."""

    monkeypatched = {"node_records": [{"id": "n0"}], "edge_records": [{"source_id": "n0"}]}
    out = annotate_source_unit_coverage(None, monkeypatched)

    assert out["node_records"] == [{"id": "n0"}]
    assert out["edge_records"] == [{"source_id": "n0"}]


def test_module_exposes_the_pure_function_for_reuse():
    assert callable(backend_tools.source_unit_coverage)


def test_a_complete_packet_adds_nothing_to_the_synthesis_prompt():
    """No finding, no section. An empty header would seed hedging for free."""

    from battalion import _partial_source_units_block

    assert _partial_source_units_block({"source_unit_coverage": []}) == ""
    assert _partial_source_units_block({}) == ""
    assert _partial_source_units_block(None) == ""


def test_the_shortfall_reaches_the_synthesiser_as_a_count():
    from battalion import _partial_source_units_block

    block = _partial_source_units_block({
        "source_unit_coverage": [
            {
                "source_unit_id": "repo:code:agent_graph",
                "nodes_in_packet": 8,
                "nodes_in_graph": 27,
                "missing_node_ids": [],
            }
        ]
    })

    assert "repo:code:agent_graph: 8 of 27 nodes retrieved" in block
    # Disclosure, not abstention — a partial section is normal retrieval, and
    # telling the model to refuse on one would manufacture failures.
    assert "Answer from the evidence you have" in block
    assert "refuse" not in block.lower()


def test_many_partial_units_are_truncated_with_the_remainder_named():
    from battalion import _partial_source_units_block

    block = _partial_source_units_block({
        "source_unit_coverage": [
            {"source_unit_id": f"u{i}", "nodes_in_packet": 1, "nodes_in_graph": 9}
            for i in range(8)
        ]
    })

    assert "u4: 1 of 9" in block
    assert "u5" not in block
    assert "+3 further partially retrieved unit(s)" in block


def _write(path, rows):
    import real_ladybug as lb

    conn = lb.Connection(lb.Database(str(path)))
    conn.execute(
        "CREATE NODE TABLE Concept (id STRING, text_content STRING, "
        "source_unit_ids STRING[], PRIMARY KEY (id))"
    )
    for node_id, units in rows:
        conn.execute(
            "CREATE (c:Concept {id: $id, text_content: 'x', source_unit_ids: $u})",
            {"id": node_id, "u": units},
        )
    return conn


def test_the_index_is_built_from_the_graph(tmp_path):
    import engine

    engine.reset_connection()
    conn = _write(tmp_path / "a.lbug", [("n0", ["u"]), ("n1", ["u"]), ("n2", ["v"])])

    assert engine.get_source_unit_index(conn) == {"u": ["n0", "n1"], "v": ["n2"]}


def test_a_second_graph_in_one_process_is_not_served_the_first_ones_index(tmp_path):
    """The cache is per-connection. A probe comparing two graphs read the first
    graph's grain for the second until this held, and the comparison would have
    looked plausible rather than broken."""

    import engine

    engine.reset_connection()
    fine = _write(tmp_path / "fine.lbug", [(f"n{i}", ["u"]) for i in range(9)])
    assert engine.get_grain_profile(fine)["nodes_per_source_unit_median"] == 9

    coarse = _write(tmp_path / "coarse.lbug", [(f"m{i}", [f"u{i}"]) for i in range(4)])

    assert engine.get_grain_profile(coarse)["nodes_per_source_unit_median"] == 1
    assert len(engine.get_source_unit_index(coarse)) == 4
    engine.reset_connection()
