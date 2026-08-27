"""Retyping a published edge — the last object with no repair route.

A wrong primitive is not cosmetic. `cattrs-built` authored four supersession
relations on NEARTO instead of LEADSTO; a LEADSTO-keyed supersession program
scored 0.20 recall on it and `antecedents_of` saw 1 of 4. Retyping those four
edges and changing nothing else took recall to 1.00 and antecedents to 5
(`convention_repair_validation_v1`).

So this is a governance repair, and it takes the same gate a node correction
does: the oracle reads structure, and moving a relation onto NEARTO makes it
undirected — a depth-3 outgoing walk then over-retrieves 4.6x.
"""

from __future__ import annotations

import shutil

import pytest

from mcp_server.fixture import ensure_fixture
from mcp_server.proposals import _correction_gate, validate_proposal

EMB = lambda _t: [0.0] * 3072  # noqa: E731


@pytest.fixture()
def db(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def _an_edge(db_path):
    """An existing (type, source, target, label) to retype."""
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    try:
        result = conn.execute(
            "MATCH (a:Concept)-[e:CONTAINS]->(b:Concept) "
            "WHERE e.label = 'includes_adapter' RETURN a.id, b.id LIMIT 1")
        source, target = result.get_next()
        return str(source), str(target)
    finally:
        del conn, database


def _retype(source, target, label="includes_adapter",
            frm="CONTAINS", to="LEADSTO", reason="wrong primitive"):
    return {"edge_retypes": [{
        "source_id": source, "target_id": target, "label": label,
        "from_type": frm, "to_type": to, "reason": reason}]}


def test_a_retype_names_an_edge_that_exists(db):
    source, target = _an_edge(db)
    prop, err = validate_proposal(_retype(source, target), db)

    assert err == "" and prop is not None
    assert prop.edge_retypes[0].to_type == "LEADSTO"


def test_a_retype_of_an_absent_edge_is_refused(db):
    prop, err = validate_proposal(
        _retype("nowhere", "nothing"), db)

    assert prop is None
    assert "retype names an existing edge" in err


def test_from_type_must_match_the_graph(db):
    """Required rather than inferred, so a retype cannot silently act on a
    different edge than the author was looking at."""
    source, target = _an_edge(db)
    prop, err = validate_proposal(
        _retype(source, target, frm="NEARTO"), db)

    assert prop is None and "no NEARTO edge" in err


def test_a_retype_that_changes_nothing_is_refused(db):
    source, target = _an_edge(db)
    prop, err = validate_proposal(
        _retype(source, target, to="CONTAINS"), db)

    assert prop is None and "changes nothing" in err


def test_a_retype_is_not_add_only_and_so_faces_the_gate(db):
    """The whole point: retyping changes what the oracle retrieves, so it
    cannot take the add path that skips verdict comparison."""
    source, target = _an_edge(db)
    prop, _ = validate_proposal(_retype(source, target), db)

    assert prop.is_add_only() is False


def test_a_retype_that_would_split_a_label_is_refused(db):
    """`includes_adapter` is CONTAINS on 9 edges. Moving one to LEADSTO splits
    the label across two primitives, which is the exact defect the convention
    check exists to prevent — a retype must not be a back door into it."""
    from mcp_server.edge_convention import check_edges

    source, target = _an_edge(db)
    report = check_edges(db, [("LEADSTO", source, target, "includes_adapter")])

    assert report["allowed"] is False
    assert report["collisions"][0]["established"] == "CONTAINS"


def test_a_retype_cannot_be_mixed_with_other_operations(db):
    """A mixed proposal would gate one half and commit both."""
    source, target = _an_edge(db)
    encoding = _retype(source, target)
    encoding["concepts"] = [{"id": "new_one", "label": "N", "text_content": "t"}]
    prop, err = validate_proposal(encoding, db)

    assert prop is None and "cannot be mixed" in err


def test_applying_a_retype_moves_the_edge_and_keeps_its_label(db):
    """Delete-and-create is the mechanism, because the primitive IS the REL
    table — but endpoints, direction and label must survive unchanged, or it
    would be authoring a new assertion rather than repairing one."""
    import real_ladybug as lb

    from mcp_server.proposals import _apply

    source, target = _an_edge(db)
    prop, err = validate_proposal(_retype(source, target), db)
    assert err == ""
    _apply(db, prop, EMB)

    database = lb.Database(str(db), read_only=True)
    conn = lb.Connection(database)
    try:
        moved = conn.execute(
            "MATCH (a:Concept)-[e:LEADSTO]->(b:Concept) "
            "WHERE a.id = $s AND b.id = $t RETURN e.label",
            {"s": source, "t": target})
        assert moved.has_next()
        assert str(moved.get_next()[0]) == "includes_adapter"
        gone = conn.execute(
            "MATCH (a:Concept)-[:CONTAINS]->(b:Concept) "
            "WHERE a.id = $s AND b.id = $t RETURN count(*)",
            {"s": source, "t": target})
        assert int(gone.get_next()[0]) == 0
    finally:
        del conn, database
