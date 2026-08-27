"""The node readers must work on every schema version they will meet.

`Concept` has grown twice: `kind`, then `source_unit_ids`. Graphs built before
each still exist and must still open.

This exists because the first attempt at adding `source_unit_ids` nested a try
per column and left the narrowest query *outside* its own `except`, so it ran
unconditionally and overwrote the good result. Every pre-`source_unit_ids`
graph then raised `IndexError` on a column the reader still believed was
there — and no test noticed, because every fixture in the suite is built from
the current schema.
"""

from __future__ import annotations

import pytest

import graph_read


def _graph_without(tmp_path, *, columns: tuple[str, ...]):
    """A Concept table carrying exactly `columns` and two rows."""
    import real_ladybug as lb

    db_path = tmp_path / "legacy.lbug"
    conn = lb.Connection(lb.Database(str(db_path)))
    decl = ", ".join(
        f"{c} {'STRING[]' if c == 'source_unit_ids' else 'STRING' if c in {'id','label','semantic_anchor','text_content','linked_graph_id','kind'} else 'DOUBLE' if c == 'centrality_score' else 'BOOLEAN' if c == 'is_metanode' else 'INT64'}"
        for c in columns
    )
    conn.execute(f"CREATE NODE TABLE Concept ({decl}, PRIMARY KEY (id))")
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        conn.execute(
            f"CREATE REL TABLE {rel} (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    for i in (1, 2):
        vals = []
        for c in columns:
            if c == "id":
                vals.append(f"'node{i}'")
            elif c in {"label", "semantic_anchor", "text_content", "linked_graph_id", "kind"}:
                vals.append(f"'{c}{i}'")
            elif c == "centrality_score":
                vals.append("0.5")
            elif c == "is_metanode":
                vals.append("false")
            elif c == "source_unit_ids":
                vals.append(f"['src#u:{i}@whole']")
            else:
                vals.append("10")
        conn.execute(f"CREATE (:Concept {{{', '.join(f'{c}: {v}' for c, v in zip(columns, vals))}}})")
    conn.close()
    return db_path


OLDEST = ("id", "label", "semantic_anchor", "text_content", "centrality_score",
          "is_metanode", "linked_graph_id", "token_count")
WITH_KIND = OLDEST + ("kind",)
CURRENT = WITH_KIND + ("source_unit_ids",)


@pytest.mark.parametrize("columns, expect_units, expect_kind", [
    (OLDEST, False, False),
    (WITH_KIND, False, True),
    (CURRENT, True, True),
])
def test_read_nodes_opens_every_schema_version(tmp_path, columns, expect_units, expect_kind):
    import real_ladybug as lb

    db = _graph_without(tmp_path, columns=columns)
    conn = lb.Connection(lb.Database(str(db)))
    try:
        nodes = graph_read.read_nodes(conn)
    finally:
        conn.close()

    assert len(nodes) == 2, "the reader silently dropped rows"
    node = nodes[0]
    # Absent columns degrade to a falsy default, never to a raise and never to
    # a wrong value read off a neighbouring column.
    assert bool(node["source_unit_ids"]) is expect_units
    assert bool(node["kind"]) is expect_kind
    assert node["id"] == "node1"
    assert node["token_count"] == 10, "column alignment drifted"


@pytest.mark.parametrize("columns, expect_units", [
    (OLDEST, False), (WITH_KIND, False), (CURRENT, True),
])
def test_read_node_opens_every_schema_version(tmp_path, columns, expect_units):
    db = _graph_without(tmp_path, columns=columns)
    node = graph_read.read_node(db, "node2")

    assert "error" not in node, node
    assert node["id"] == "node2"
    assert node["text_content"] == "text_content2", "the late payload went missing"
    assert bool(node["source_unit_ids"]) is expect_units
