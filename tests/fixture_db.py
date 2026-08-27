"""Create minimal LadybugDB fixtures for tests (no OpenRouter seeding path).

Fixtures use orthogonal unit vectors as embeddings so no API key is needed.
Supports both the 4-tuple (id, label, content, token_count) and extended
7-tuple (id, label, content, token_count, anchor, is_metanode, linked_graph_id)
node formats from seeds.py.
"""

from __future__ import annotations

from pathlib import Path

import real_ladybug as lb

from seeds import get_dependencies_data, get_seed_data


_SST_REL_MAP = {
    "leadsto": "LEADSTO",
    "contains": "CONTAINS",
    "expresses": "EXPRESSES",
    "nearto": "NEARTO",
}


def _create_schema(conn: lb.Connection) -> None:
    for tbl in [
        "LEADSTO",
        "CONTAINS",
        "EXPRESSES",
        "NEARTO",
        "GraphMetadata",
        "Concept",
    ]:
        try:
            conn.execute(f"DROP TABLE {tbl}")
        except Exception:
            pass

    conn.execute(
        "CREATE NODE TABLE Concept ("
        "  id STRING,"
        "  label STRING,"
        "  text_content STRING,"
        "  semantic_anchor STRING,"
        "  embedding FLOAT[3072],"
        "  token_count INT64,"
        "  centrality_score DOUBLE,"
        "  is_metanode BOOLEAN DEFAULT false,"
        "  linked_graph_id STRING DEFAULT '',"
        "  PRIMARY KEY (id)"
        ")"
    )
    conn.execute("CREATE REL TABLE LEADSTO   (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE CONTAINS  (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE EXPRESSES (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE NEARTO    (FROM Concept TO Concept, label STRING DEFAULT NULL)")


def _insert_nodes_and_edges(
    conn: lb.Connection,
    nodes: list,
    edges: list,
) -> None:
    for i, node in enumerate(nodes):
        node_id, label, content, token_count = node[0], node[1], node[2], node[3]
        anchor = node[4] if len(node) > 4 else ""
        is_metanode = bool(node[5]) if len(node) > 5 else False
        linked_graph_id = node[6] if len(node) > 6 else ""
        emb = [0.0] * 3072
        emb[i % 3072] = 1.0
        conn.execute(
            "CREATE (c:Concept {id: $id, label: $label, text_content: $content,"
            " semantic_anchor: $anchor, embedding: $emb, token_count: $tc,"
            " centrality_score: 0.0, is_metanode: $meta, linked_graph_id: $linked})",
            {
                "id": node_id, "label": label, "content": content,
                "anchor": anchor or "", "emb": emb, "tc": token_count,
                "meta": is_metanode, "linked": linked_graph_id or "",
            },
        )

    for edge in edges:
        src, dst, sst_type = edge[0], edge[1], edge[2]
        edge_label = edge[3] if len(edge) > 3 else ""
        rel_table = _SST_REL_MAP[sst_type]
        conn.execute(
            f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $dst}})"
            f" CREATE (a)-[:{rel_table} {{label: $label}}]->(b)",
            {"src": src, "dst": dst, "label": edge_label or ""},
        )


def create_fixture_db(seed_name: str, db_path: Path) -> lb.Connection:
    """Create a fixture DB from any named seed profile (no OpenRouter needed)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    _create_schema(conn)
    nodes, edges = get_seed_data(seed_name)
    _insert_nodes_and_edges(conn, nodes, edges)
    return conn


def create_dependencies_db(db_path: Path) -> lb.Connection:
    """Fresh DB with the `dependencies` seed graph and orthogonal unit embeddings."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    _create_schema(conn)
    nodes, edges = get_dependencies_data()
    _insert_nodes_and_edges(conn, nodes, edges)
    return conn
