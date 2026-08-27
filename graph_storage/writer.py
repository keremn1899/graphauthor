"""Write graph records to the Ladybug traversal store."""

from __future__ import annotations

from pathlib import Path
import sys

import real_ladybug as lb

from engine import get_embeddings_model
from graph_storage.materialize import ensure_schema
from graph_storage.records import MaterializedGraph


def _estimate_tokens(text: str) -> int:
    # Cheap proxy: ~4 chars per token
    s = (text or "").strip()
    return max(1, len(s) // 4) if s else 1


def write_graph_records(
    db_path: Path,
    graph: MaterializedGraph,
    *,
    embed_batch: int = 32,
    embed: bool = True,
) -> None:
    """Persist a graph, optionally leaving the secondary vector index empty.

    Exact identities, relations and lexical retrieval do not require remote
    embeddings. ``embed=False`` writes zero vectors of the schema's fixed width;
    callers must mark the published artifact so semantic search can refuse
    honestly rather than rank those placeholders.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = lb.Database(str(db_path.resolve()))
    conn = lb.Connection(database)
    ensure_schema(conn)
    # Graph identity is retrieval context, not a Concept. Persist it separately
    # so queries may name the graph/domain without producing a false
    # missing-concept gap or polluting domain topology with a synthetic root.
    conn.execute(
        "CREATE (g:GraphMetadata {id: $id, domain: $domain})",
        {"id": graph.id, "domain": graph.domain},
    )

    node_list = list(graph.nodes.values())
    anchors: list[str] = []
    for n in node_list:
        a = (n.semantic_anchor or "").strip()
        if not a:
            a = (n.text_content or n.label)[:500].strip() or "concept"
        anchors.append(a)

    all_emb: list[list[float]] = []
    if embed:
        embedder = get_embeddings_model()
        print(
            f"Embedding {len(anchors)} anchors in batches of {embed_batch}...",
            file=sys.stderr,
        )
        for i in range(0, len(anchors), embed_batch):
            batch = anchors[i : i + embed_batch]
            all_emb.extend(embedder.embed_documents(batch))
    else:
        print(
            f"Writing {len(anchors)} nodes without semantic embeddings; "
            "exact, typed and lexical operations remain available.",
            file=sys.stderr,
        )
        all_emb = [[0.0] * 3072 for _ in anchors]

    _sst_rel_map = {
        "leadsto": "LEADSTO",
        "contains": "CONTAINS",
        "expresses": "EXPRESSES",
        "nearto": "NEARTO",
    }
    node_ids = {n.id for n in node_list}

    for j, n in enumerate(node_list):
        emb = all_emb[j]
        tc = n.token_count or _estimate_tokens(n.text_content)
        conn.execute(
            "CREATE (c:Concept {id: $id, label: $label, text_content: $content,"
            " semantic_anchor: $anchor, embedding: $emb, token_count: $tc,"
            " centrality_score: 0.0, is_metanode: $meta, linked_graph_id: $linked,"
            " kind: $format_kind, claim_kind: $kind, "
            "claim_kind_source: $kind_source,"
            " source_unit_ids: $units})",
            {
                "id": n.id,
                "label": n.label,
                "content": n.text_content or "",
                "anchor": anchors[j],
                "emb": emb,
                "tc": int(tc),
                "meta": bool(n.is_metanode),
                "linked": (n.linked_graph_id or "").strip(),
                "format_kind": (n.kind or "").strip().lower(),
                "kind": (n.claim_kind or "").strip().lower(),
                "kind_source": (n.claim_kind_source or "").strip().lower(),
                "units": [str(u) for u in (n.source_unit_ids or [])],
            },
        )

    inserted = 0
    for e in graph.edges:
        vt = e.validated_type()
        if not vt:
            continue
        rel_table = _sst_rel_map.get(vt)
        if not rel_table:
            continue
        if e.source not in node_ids or e.target not in node_ids:
            continue
        try:
            conn.execute(
                f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $dst}})"
                f" CREATE (a)-[:{rel_table} {{label: $label}}]->(b)",
                {"src": e.source, "dst": e.target, "label": (e.label or "").strip()},
            )
            inserted += 1
        except Exception:
            pass

    print(
        f"Materialized {len(node_list)} nodes, {inserted} edges into {db_path}",
        file=sys.stderr,
    )
