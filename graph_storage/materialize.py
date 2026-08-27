"""Create LadybugDB file from nodes + edges (same schema as engine seeding)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import real_ladybug as lb

from engine import get_embeddings_model

_CHECKPOINT_EVERY = 1000  # reconnect every N newly written nodes to flush WAL
_CACHE_COMMIT_EVERY = 200  # flush embedding cache every N new embeddings


def ensure_schema(conn: lb.Connection) -> None:
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
    _create_tables(conn)


def ensure_edge_tables(conn: lb.Connection) -> None:
    """Drop and recreate only the four edge tables — nodes are untouched."""
    for tbl in ["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]:
        try:
            conn.execute(f"DROP TABLE {tbl}")
        except Exception:
            pass
    _create_edge_tables(conn)


def _create_tables(conn: lb.Connection) -> None:
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
        "  kind STRING DEFAULT '',"
        # Kept in step with `engine.py`'s Concept table, which grew these two
        # first. Every builder that writes through this path — the Wikipedia
        # crawler, the LLM generator, and the construction workspace — wrote
        # into a table that had nowhere to put the classification it had
        # already computed, so it round-tripped through an "ADJUDICATES:" text
        # prefix and survived only until something reformatted the payload.
        # Two definitions of one table will diverge again; this one exists
        # because it already did.
        "  claim_kind STRING DEFAULT '',"
        "  claim_kind_source STRING DEFAULT '',"
        # Which source units this node was drawn from. Grain is a fact
        # about a graph that only construction knows and only retrieval
        # needs: how many nodes one source section became decides how
        # many must be co-retrieved to reconstitute it. Dropping it here
        # is why the Compass could describe density and depth but not
        # whether a node was a paragraph or a sentence.
        "  source_unit_ids STRING[],"
        "  PRIMARY KEY (id)"
        ")"
    )
    conn.execute(
        "CREATE NODE TABLE GraphMetadata ("
        "id STRING, domain STRING, PRIMARY KEY (id))"
    )
    _create_edge_tables(conn)


def _create_edge_tables(conn: lb.Connection) -> None:
    conn.execute("CREATE REL TABLE LEADSTO   (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE CONTAINS  (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE EXPRESSES (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE NEARTO    (FROM Concept TO Concept, label STRING DEFAULT NULL)")


def _open_conn(db_path: Path) -> tuple[lb.Database, lb.Connection]:
    database = lb.Database(str(db_path))
    return database, lb.Connection(database)


def _load_existing_ids(conn: lb.Connection) -> set[str]:
    try:
        rows = conn.execute("MATCH (c:Concept) RETURN c.id")
        return {row[0] for row in rows}
    except Exception:
        return set()


def _has_schema(conn: lb.Connection) -> bool:
    try:
        conn.execute("MATCH (c:Concept) RETURN c.id LIMIT 1")
        return True
    except Exception:
        return False


_SST_REL_MAP = {
    "leadsto": "LEADSTO",
    "contains": "CONTAINS",
    "expresses": "EXPRESSES",
    "nearto": "NEARTO",
}


_EDGE_CHECKPOINT_EVERY = 5000  # reconnect every N edges to flush WAL


def _insert_edges(
    conn: lb.Connection,
    edges: list[tuple],
    known_ids: set[str],
    db_path: Path | None = None,
) -> int:
    """Insert edges with periodic WAL checkpoints to prevent memory blow-up.

    db_path must be provided when the edge list is large (>_EDGE_CHECKPOINT_EVERY)
    so the connection can be closed+reopened to flush the WAL.
    """
    inserted = 0
    skipped_unknown_id = 0
    skipped_unknown_sst = 0
    failed = 0
    failure_samples: list[str] = []
    _conn = conn
    _db: lb.Database | None = None

    for i, edge in enumerate(edges):
        src, dst, sst_type = edge[0], edge[1], edge[2]
        edge_label = edge[3] if len(edge) > 3 else ""
        if src not in known_ids or dst not in known_ids:
            skipped_unknown_id += 1
            continue
        rel_table = _SST_REL_MAP.get(sst_type)
        if not rel_table:
            skipped_unknown_sst += 1
            continue
        try:
            _conn.execute(
                f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $dst}})"
                f" CREATE (a)-[:{rel_table} {{label: $label}}]->(b)",
                {"src": src, "dst": dst, "label": edge_label or ""},
            )
            inserted += 1
        except Exception as e:
            failed += 1
            if len(failure_samples) < 3:
                failure_samples.append(f"{src} -[{rel_table}]-> {dst}: {type(e).__name__}: {e}")

        # Periodic WAL checkpoint: close + reopen to flush WAL and prevent OOM.
        if db_path and inserted > 0 and inserted % _EDGE_CHECKPOINT_EVERY == 0:
            del _conn
            if _db is not None:
                del _db
            _db, _conn = _open_conn(db_path)
            print(f"  [edge checkpoint] {inserted}/{len(edges)} edges written", flush=True)

    print(
        f"  [edge insert summary] {inserted}/{len(edges)} inserted; "
        f"{skipped_unknown_id} skipped (unknown node id); "
        f"{skipped_unknown_sst} skipped (unmapped sst); "
        f"{failed} failed",
        flush=True,
    )
    for s in failure_samples:
        print(f"    sample failure: {s}", flush=True)
    return inserted


def write_node_texts(db_path: Path, nodes: list[tuple]) -> int:
    """Update text_content and token_count for existing nodes in-place.

    Skips embedding — use when only prose content changed but anchors (and
    therefore embedding keys) are unchanged. Returns the number of nodes updated.
    nodes: (id, label, text_content, semantic_anchor, token_count[, is_metanode])
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database, conn = _open_conn(db_path)
    known_ids = _load_existing_ids(conn)
    updated = 0
    for row in nodes:
        nid, _label, text, anchor, wc = row[0], row[1], row[2], row[3], row[4]
        if nid not in known_ids:
            continue
        try:
            conn.execute(
                "MATCH (c:Concept {id: $id}) SET c.text_content = $text, "
                "c.semantic_anchor = $anchor, c.token_count = $wc",
                {"id": nid, "text": text, "anchor": anchor, "wc": int(wc)},
            )
            updated += 1
        except Exception:
            pass
    print(f"Node text update complete: {updated}/{len(nodes)} nodes updated.", flush=True)
    return updated


def write_edges_only(db_path: Path, edges: list[tuple]) -> int:
    """Drop and rebuild all four edge tables without touching nodes.

    Returns the number of edges inserted. Use this when the predicate map
    changed but node content (and therefore embeddings) has not.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database, conn = _open_conn(db_path)
    ensure_edge_tables(conn)
    known_ids = _load_existing_ids(conn)
    print(f"Edge-only rebuild: {len(known_ids)} existing nodes, {len(edges)} candidate edges...", flush=True)
    inserted = _insert_edges(conn, edges, known_ids, db_path=db_path)
    print(f"Edge-only rebuild complete: {inserted} edges inserted.", flush=True)
    return inserted


def write_graph(
    db_path: Path,
    nodes: list[tuple],
    edges: list[tuple],
    *,
    embed_batch: int = 32,
    cache_path: Optional[Path] = None,
) -> None:
    """nodes: (id, label, text_content, semantic_anchor, token_count[, is_metanode])
    edges: (src, dst, sst_type) or (src, dst, sst_type, label)

    Embeddings are computed and written in streaming batches — never accumulates
    all vectors in memory at once (avoids OOM on large graphs like MetaQA).

    Reconnects every _CHECKPOINT_EVERY nodes to force a WAL checkpoint so that
    a mid-run crash leaves the DB in a valid (if partial) state. On restart,
    already-written nodes are skipped automatically (resume support).

    If cache_path is provided, embeddings are read from / written to the
    EmbeddingCache at that path so future rebuilds avoid API calls.
    """
    from graph_storage.embedding_cache import EmbeddingCache

    db_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(nodes)

    database, conn = _open_conn(db_path)

    if not _has_schema(conn):
        ensure_schema(conn)
        written_ids: set[str] = set()
        print(f"Schema created. Embedding and writing {total} nodes...", flush=True)
    else:
        written_ids = _load_existing_ids(conn)
        print(
            f"Resuming: {len(written_ids)}/{total} nodes already in DB. "
            f"{total - len(written_ids)} remaining.",
            flush=True,
        )

    embedder = get_embeddings_model()
    model_name: str = getattr(embedder, "model", "") or ""
    cache = EmbeddingCache(cache_path) if cache_path else None
    newly_written = 0
    cache_puts = 0

    try:
        for i in range(0, total, embed_batch):
            batch_nodes = nodes[i : i + embed_batch]

            pending = [n for n in batch_nodes if n[0] not in written_ids]
            if not pending:
                done = min(i + embed_batch, total)
                if done % (embed_batch * 20) == 0:
                    print(f"  [{done}/{total}] {done * 100 // total}% (skipping already-written)", flush=True)
                continue

            # Build anchor list and check cache for each
            anchors: list[str] = []
            for n in pending:
                a = (n[3] or "").strip() or n[2][:500].strip() or "concept"
                anchors.append(a)

            # Split into cache hits and API misses
            batch_emb: list[list[float] | None] = [None] * len(pending)
            api_indices: list[int] = []
            api_anchors: list[str] = []
            if cache:
                for k, anchor in enumerate(anchors):
                    hit = cache.get(model_name, anchor)
                    if hit is not None:
                        batch_emb[k] = hit
                    else:
                        api_indices.append(k)
                        api_anchors.append(anchor)
            else:
                api_indices = list(range(len(pending)))
                api_anchors = anchors

            # Embed only misses
            if api_anchors:
                api_results = embedder.embed_documents(api_anchors)
                for j, k in enumerate(api_indices):
                    batch_emb[k] = api_results[j]
                    if cache:
                        cache.put(model_name, api_anchors[j], api_results[j])
                        cache_puts += 1
                        if cache_puts % _CACHE_COMMIT_EVERY == 0:
                            cache.commit()

            for k, node_tuple in enumerate(pending):
                node_id, label, content, anchor = node_tuple[0], node_tuple[1], node_tuple[2], node_tuple[3]
                token_count = node_tuple[4]
                is_metanode = bool(node_tuple[5]) if len(node_tuple) > 5 else False
                emb = batch_emb[k]
                conn.execute(
                    "CREATE (c:Concept {id: $id, label: $label, text_content: $content,"
                    " semantic_anchor: $anchor, embedding: $emb, token_count: $tc,"
                    " centrality_score: 0.0, is_metanode: $meta, linked_graph_id: ''})",
                    {
                        "id": node_id,
                        "label": label,
                        "content": content,
                        "anchor": anchors[k],
                        "emb": emb,
                        "tc": token_count,
                        "meta": is_metanode,
                    },
                )
                written_ids.add(node_id)
                newly_written += 1

            done = min(i + embed_batch, total)
            cache_ratio = f" (cache {len(pending) - len(api_anchors)}/{len(pending)})" if cache else ""
            print(f"  [{done}/{total}] {done * 100 // total}% embedded+written{cache_ratio}", flush=True)

            # Periodic WAL checkpoint: close + reopen forces LadybugDB to flush WAL
            if newly_written > 0 and newly_written % _CHECKPOINT_EVERY < embed_batch:
                if cache:
                    cache.commit()
                del conn
                del database
                database, conn = _open_conn(db_path)
                print(f"  [checkpoint] WAL flushed — {len(written_ids)}/{total} nodes safe on disk", flush=True)

    finally:
        if cache:
            cache.close()

    print(f"Writing {len(edges)} edges...", flush=True)
    # Don't pass db_path — periodic checkpoint reopen here triggers a LadybugDB
    # schema-load bug ("Trying to create a vector with ANY type") on DBs with
    # FLOAT[3072] columns. Edge-only WAL bloat is only a problem after a DROP
    # TABLE (write_edges_only); the full-rebuild path has fresh tables and
    # 134K edges fit fine in a single connection.
    inserted = _insert_edges(conn, edges, written_ids)
    print(f"Inserted {len(nodes)} nodes, {inserted} edges into {db_path}", flush=True)
