"""Build a no-API fixture graph for deterministic MCP server testing.

A small architecture graph with exact lookup, typed expansion, and a path.
Vector search is not semantically meaningful here; lexical search is.
"""

from __future__ import annotations

from pathlib import Path

import real_ladybug as lb

_REL_MAP = {
    "leadsto": "LEADSTO",
    "contains": "CONTAINS",
    "expresses": "EXPRESSES",
    "nearto": "NEARTO",
}

_DIM = 3072


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
        f"  embedding FLOAT[{_DIM}],"
        "  token_count INT64,"
        "  centrality_score DOUBLE,"
        "  is_metanode BOOLEAN DEFAULT false,"
        "  linked_graph_id STRING DEFAULT '',"
        "  PRIMARY KEY (id)"
        ")"
    )
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        conn.execute(f"CREATE REL TABLE {rel} (FROM Concept TO Concept, label STRING DEFAULT NULL)")


def _unit_vector(i: int) -> list[float]:
    v = [0.0] * _DIM
    v[i % _DIM] = 1.0
    return v


def fixture_graph_data():
    """Nodes and edges used by retrieve, history, and operator tests."""
    nodes = [
        (
            "ports_module",
            "Ports Module",
            "Ports module owns inbound adapters for the order path.",
            12,
            "ports module",
        ),
        (
            "intake_adapter",
            "Intake Adapter",
            "Inbound adapter that accepts new order commands.",
            10,
            "intake adapter",
        ),
        (
            "order_controller",
            "Order Controller",
            "HTTP controller that accepts order commands.",
            10,
            "order controller",
        ),
        (
            "order_service",
            "Order Service",
            "Domain service that fulfills orders.",
            8,
            "order service",
        ),
        (
            "dependency_direction_rule",
            "Dependency Direction Rule",
            "Dependency direction: adapters depend inward; domain does not depend out.",
            16,
            "dependency direction",
        ),
        (
            "retry_policy",
            "Retry Policy",
            "Retries require a project-approved policy.",
            8,
            "retry policy",
        ),
    ]
    edges = [
        ("ports_module", "order_controller", "contains", "owns"),
        ("ports_module", "intake_adapter", "contains", "owns"),
        ("intake_adapter", "order_controller", "leadsto", "forwards_to"),
        ("order_controller", "order_service", "leadsto", "delegates_to"),
        ("order_service", "dependency_direction_rule", "expresses", "obeys"),
        ("order_service", "retry_policy", "contains", "declares"),
    ]
    return nodes, edges


def build_fixture(db_path: Path | str) -> Path:
    """Create the fixture .lbug at ``db_path`` (idempotent: rebuilds if empty/missing)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    nodes, edges = fixture_graph_data()
    return _write_graph(nodes, edges, db_path)


def _write_graph(nodes, edges, db_path: Path) -> Path:
    db = lb.Database(str(db_path))
    conn = lb.Connection(db)
    _create_schema(conn)

    for i, node in enumerate(nodes):
        node_id, label, content, token_count = node[0], node[1], node[2], node[3]
        anchor = node[4] if len(node) > 4 else content[:180]
        conn.execute(
            "CREATE (:Concept {id: $id, label: $label, text_content: $tc, "
            "semantic_anchor: $anchor, embedding: $emb, token_count: $tok, "
            "centrality_score: 0.0, is_metanode: false, linked_graph_id: ''})",
            {
                "id": node_id,
                "label": label,
                "tc": content,
                "anchor": anchor,
                "emb": _unit_vector(i),
                "tok": int(token_count),
            },
        )

    for src, tgt, rel_type, rel_label in edges:
        tbl = _REL_MAP[rel_type.lower()]
        conn.execute(
            f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $tgt}}) "
            f"CREATE (a)-[:{tbl} {{label: $lbl}}]->(b)",
            {"src": src, "tgt": tgt, "lbl": rel_label},
        )

    del conn
    del db
    return db_path


def ensure_fixture(db_path: Path | str) -> Path:
    """Build the fixture only if missing or empty."""
    db_path = Path(db_path)
    if db_path.exists():
        try:
            db = lb.Database(str(db_path))
            conn = lb.Connection(db)
            res = conn.execute("MATCH (c:Concept) RETURN count(c)")
            count = res.get_next()[0] if res.has_next() else 0
            del conn, db
            if count > 0:
                return db_path
        except Exception:
            pass
    return build_fixture(db_path)
