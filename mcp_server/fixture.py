"""Build a no-API fixture graph for deterministic MCP server testing.

Uses the hexagonal-orders architecture corpus (30 Concepts) with orthogonal
unit-vector embeddings so no OpenRouter key is needed. Vector search is not
semantically meaningful on this fixture; exact/lexical lookup, typed traversal,
structural index, and compass all behave normally — which is what the
deterministic M2 tier exercises.
"""

from __future__ import annotations

import sys
from pathlib import Path

import real_ladybug as lb

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HEX_DIR = _REPO_ROOT / "examples" / "hexagonal-orders"

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


def build_fixture_from(corpus_dir: Path | str, getter: str, db_path: Path | str) -> Path:
    """Build a .lbug from any corpus module exposing ``getter() -> (nodes, edges)``
    (L2-4: the harness seed reuses the deterministic fixture machinery)."""
    corpus_dir = Path(corpus_dir)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    import importlib.util

    if str(corpus_dir) not in sys.path:
        sys.path.insert(0, str(corpus_dir))
    # corpus modules share the name graph_data across corpora — load by path
    spec = importlib.util.spec_from_file_location(f"corpus_{corpus_dir.name}", corpus_dir / "graph_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    nodes, edges = getattr(mod, getter)()
    return _write_graph(nodes, edges, db_path)


def build_fixture(db_path: Path | str) -> Path:
    """Create the fixture .lbug at ``db_path`` (idempotent: rebuilds if empty/missing)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if str(_HEX_DIR) not in sys.path:
        sys.path.insert(0, str(_HEX_DIR))
    from graph_data import get_hexagonal_orders_data  # type: ignore

    nodes, edges = get_hexagonal_orders_data()
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
