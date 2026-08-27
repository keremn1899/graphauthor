"""LadybugDB engine: SST schema, structural index, and Graph Compass.

Schema: 4 typed REL TABLEs with optional label, Concept nodes with
semantic_anchor and metanode fields.

Structural index: per-node roles and betweenness centrality, computed at
startup and held in memory.

Graph Compass: small orientation kernel (profile, landmarks, gaps), computed
once at startup. Not a census and not a proof. Ask and MCP `orient` read it;
there is no live Planner.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Protocol

import real_ladybug as lb
import requests

import normative
from models import SST_EDGE_TYPES, Compass, GraphSchema, StructuralFacts

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "sst.lbug"
# OpenRouter slug; must output vectors compatible with Concept.embedding FLOAT[3072].
DEFAULT_EMBEDDINGS_MODEL = "google/gemini-embedding-2-preview"
SCHEMA_EMBEDDING_DIM = 3072

_connection: lb.Connection | None = None
_database: lb.Database | None = None
_db_path: Path | None = None
class EmbeddingClient(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class OpenRouterEmbeddings:
    """Minimal embedding client using OpenRouter's /embeddings endpoint.

    We avoid provider-specific response parsing assumptions in third-party wrappers
    so seeding failures surface actionable API errors.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        request_timeout: int,
        max_retries: int = 3,
        batch_size: int = 32,
        dimensions: int | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.url = f"{base_url.rstrip('/')}/embeddings"
        self.request_timeout = max(1, request_timeout)
        self.max_retries = max(1, max_retries)
        self.batch_size = max(1, batch_size)
        self.dimensions = dimensions

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {"model": self.model, "input": texts}
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    self.url,
                    headers=headers,
                    json=payload,
                    timeout=self.request_timeout,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                body = resp.json()
                if body.get("error"):
                    raise RuntimeError(f"OpenRouter error: {body['error']}")
                data = body.get("data")
                if not isinstance(data, list) or not data:
                    raise RuntimeError(f"No embedding data received (keys={list(body.keys())})")
                vectors = [row.get("embedding") for row in data if isinstance(row, dict)]
                if len(vectors) != len(texts) or any(v is None for v in vectors):
                    raise RuntimeError(f"Malformed embedding payload (keys={list(body.keys())})")
                return vectors
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == self.max_retries:
                    break
                # Long runs (MetaQA materialise) hit transient provider/routing failures.
                delay = min(45.0, 1.6 ** attempt) + random.uniform(0.0, 0.75)
                time.sleep(delay)
        raise RuntimeError(
            f"Embedding batch failed after {self.max_retries} attempts: {last_error}"
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [(t or "").strip() or "concept" for t in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(cleaned), self.batch_size):
            vectors.extend(self._embed_batch(cleaned[i : i + self.batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([(text or "").strip()])[0]


_embeddings_model: EmbeddingClient | None = None
_structural_index: dict[str, StructuralFacts] | None = None
_compass: Compass | None = None
_graph_schema: GraphSchema | None = None
_source_unit_index: dict[str, list[str]] | None = None
_grain: dict | None = None
# Both caches are per-connection rather than per-process. `_compass` is a plain
# global because the engine opens one graph, but grain is read by packet-direct
# callers that open several in one process — a probe comparing two graphs was
# served the first graph's grain for the second until this key existed. The
# connection itself is held so its id cannot be recycled under the cache.
_grain_conn: object | None = None


# ---------------------------------------------------------------------------
# Typed engine-level failures (server-safe: never sys.exit from library code)
# ---------------------------------------------------------------------------


class SeedingError(RuntimeError):
    """Seeding the graph failed (embeddings/API/DB). The DB was not mutated."""


class EmptyGraphError(RuntimeError):
    """The DB at the given path has no Concept nodes and auto-seed is disabled.

    Honest-failure doctrine at the ops level: an empty or wrong path must be a
    typed refusal, not a silently fabricated default corpus. Opt in to demo
    seeding explicitly via ``get_connection(auto_seed=True)`` or
    ``SST_AUTO_SEED=1``.
    """


class GraphInUseError(RuntimeError):
    """Another process already owns this ``.lbug``.

    LadybugDB is single-owner. A second open rewrites the live file. MCP and
    Review must not share a path; close the holder or point this process at a
    different graph.
    """

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        holder: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.path = Path(path)
        self.holder = holder or {}


def owner_lock_path(db_path: Path | str) -> Path:
    """Sidecar flock file beside the graph. Released when the owner process exits."""
    path = Path(db_path).expanduser().resolve()
    return Path(str(path) + ".owner.lock")


_owner_lock_fd: int | None = None
_owner_lock_path: Path | None = None


def _holder_payload(path: Path) -> dict:
    argv = " ".join(sys.argv[:3]).strip() or Path(sys.argv[0]).name
    return {
        "pid": os.getpid(),
        "argv": argv[:240],
        "path": str(path),
        "since": int(time.time()),
    }


def _read_holder(lock_path: Path) -> dict:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_holder(fd: int, path: Path) -> None:
    encoded = json.dumps(_holder_payload(path), sort_keys=True).encode("utf-8")
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, encoded)
    os.fsync(fd)


def _acquire_owner_lock(path: Path) -> None:
    """Exclusive flock for this process's owned graph. Same path is a no-op."""
    import fcntl

    global _owner_lock_fd, _owner_lock_path
    path = Path(path).expanduser().resolve()
    lock_path = owner_lock_path(path)
    if _owner_lock_fd is not None and _owner_lock_path == lock_path:
        return
    if _owner_lock_fd is not None:
        _release_owner_lock()
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        holder = _read_holder(lock_path)
        os.close(fd)
        pid = holder.get("pid") or "unknown"
        argv = holder.get("argv") or "another process"
        raise GraphInUseError(
            f"{path} is already open in pid {pid} ({argv}). "
            "LadybugDB is single-owner: stop that process, or use a different "
            ".lbug. MCP and Review cannot share the same file.",
            path=path,
            holder=holder,
        ) from exc
    _write_holder(fd, path)
    _owner_lock_fd = fd
    _owner_lock_path = lock_path


def _release_owner_lock() -> None:
    import fcntl

    global _owner_lock_fd, _owner_lock_path
    if _owner_lock_fd is None:
        return
    try:
        fcntl.flock(_owner_lock_fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(_owner_lock_fd)
    except OSError:
        pass
    _owner_lock_fd = None
    _owner_lock_path = None


class _TemporaryOwnerLock:
    """Lock a graph this process does not already own, then release it.

    Uses its own file descriptor so a short-lived read of graph B cannot drop
    the session lock on graph A.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self._fd: int | None = None

    def __enter__(self) -> Path:
        import fcntl

        lock_path = owner_lock_path(self.path)
        if _owner_lock_fd is not None and _owner_lock_path == lock_path:
            return self.path
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            holder = _read_holder(lock_path)
            os.close(fd)
            pid = holder.get("pid") or "unknown"
            argv = holder.get("argv") or "another process"
            raise GraphInUseError(
                f"{self.path} is already open in pid {pid} ({argv}). "
                "LadybugDB is single-owner: stop that process, or use a different "
                ".lbug. MCP and Review cannot share the same file.",
                path=self.path,
                holder=holder,
            ) from exc
        self._fd = fd
        return self.path

    def __exit__(self, *_exc) -> None:
        import fcntl

        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None


def this_process_owns_graph(db_path: Path | str) -> bool:
    path = Path(db_path).expanduser().resolve()
    return _db_path is not None and Path(_db_path).resolve() == path


graph_owner_lock = _TemporaryOwnerLock


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def get_embeddings_model() -> EmbeddingClient:
    global _embeddings_model
    if _embeddings_model is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY must be set for embeddings.")
        # Keep DB seeding/materialization aligned with the project's 3072-dim LadybugDB vectors.
        embeddings_model = os.environ.get("EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL)
        dim_raw = (os.environ.get("EMBEDDINGS_DIMENSIONS") or "").strip().lower()
        if dim_raw in ("omit", "none"):
            embedding_dims: int | None = None
        elif dim_raw.isdigit():
            embedding_dims = int(dim_raw)
        else:
            embedding_dims = SCHEMA_EMBEDDING_DIM
        embeddings_base_url = os.environ.get("EMBEDDINGS_BASE_URL", "https://openrouter.ai/api/v1")
        request_timeout = int(os.environ.get("EMBEDDINGS_TIMEOUT_SEC", "90"))
        max_retries = int(os.environ.get("EMBEDDINGS_MAX_RETRIES", "8"))
        batch_size = int(os.environ.get("EMBEDDINGS_BATCH_SIZE", "32"))
        _embeddings_model = OpenRouterEmbeddings(
            model=embeddings_model,
            api_key=api_key,
            base_url=embeddings_base_url,
            request_timeout=request_timeout,
            max_retries=max_retries,
            batch_size=batch_size,
            dimensions=embedding_dims,
        )
    return _embeddings_model


# ---------------------------------------------------------------------------
# Schema + Seed
# ---------------------------------------------------------------------------

def _ensure_schema_and_seed(conn: lb.Connection) -> None:
    from seeds import get_seed_data

    profile = os.environ.get("ACTIVE_SEED", "default")
    nodes, edges = get_seed_data(profile)

    # ------------------------------------------------------------------
    # ATOMIC STEP 1: Remote — embed BEFORE touching the DB
    # ------------------------------------------------------------------
    try:
        embed_model = get_embeddings_model()
        for i, node in enumerate(nodes):
            node_id, content = node[0], node[2]
            if not content or not content.strip():
                raise ValueError(
                    f"Node '{node_id}' (index {i}) has empty content. "
                    "All nodes must have text content for embedding."
                )
        texts_to_embed = [n[2] for n in nodes]
        print("Generating vector embeddings (Atomic Phase 1: Remote API Call)...")
        embeddings = embed_model.embed_documents(texts_to_embed)
    except Exception as e:
        msg = str(e)
        if "402" in msg or "payment" in msg.lower():
            print("\n  Error: OpenRouter budget exceeded (402).")
        elif "401" in msg or "invalid_api_key" in msg.lower():
            print("\n  Error: Invalid API Key. Check your .env file.")
        elif "timeout" in msg.lower():
            print("\n  Error: API request timed out after 20 seconds.")
        else:
            print(f"\n  Error during embedding generation: {e}")
        # Never sys.exit from library code: a Zone-2 lookup or server request
        # touching an unseeded DB must degrade, not kill the process.
        raise SeedingError(f"Graph seeding aborted before any DB mutation: {e}") from e

    # ------------------------------------------------------------------
    # ATOMIC STEP 2: Local mutation
    # ------------------------------------------------------------------
    print("Seeding successful. Applying local database changes (Atomic Phase 2)...")

    # Drop all tables (rels before nodes)
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

    # Updated schema with semantic_anchor, metanode fields, optional edge labels
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
        # User-format node kind (paper / topic / claim / ...). Distinct from
        # claim_kind, which records normative authority.
        "  kind STRING DEFAULT '',"
        # What this node's text DOES — governing / contextual / interpretation
        # / navigation — and where that came from. `construction/workspace.py`
        # has classified nodes this way all along and then serialised the answer
        # into an "ADJUDICATES:" text prefix, because Concept had nowhere to put
        # it. The prefix was a workaround for these two columns being absent.
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
    conn.execute("CREATE REL TABLE LEADSTO   (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE CONTAINS  (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE EXPRESSES (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    conn.execute("CREATE REL TABLE NEARTO    (FROM Concept TO Concept, label STRING DEFAULT NULL)")

    # Insert nodes — supports 4-tuple (id, label, content, token_count),
    # 7-tuple (+ anchor, is_metanode, linked_graph_id), 9-tuple
    # (+ claim_kind, claim_kind_source), and 10-tuple (+ format kind).
    # The claim pair lets a builder declare
    # which nodes are rules as STRUCTURED DATA instead of encoding it in a text
    # prefix — which is what the prefix was always standing in for. The RFC
    # importer uses it to carry the specification's own RFC 2119 keywords.
    for i, node in enumerate(nodes):
        node_id, label, content, token_count = node[0], node[1], node[2], node[3]
        anchor = node[4] if len(node) > 4 else ""
        is_metanode = bool(node[5]) if len(node) > 5 else False
        linked_graph_id = node[6] if len(node) > 6 else ""
        claim_kind = node[7] if len(node) > 7 else ""
        claim_kind_source = node[8] if len(node) > 8 else ""
        format_kind = node[9] if len(node) > 9 else ""
        # The column is a plain STRING, so nothing stopped a builder writing a
        # value outside the vocabulary — and the readers disagree about what to
        # do with one. `normative.classify` ignores it and falls through to the
        # text prefix, reporting the result as declared; `certify._looks_like_rule`
        # takes it at face value and concludes "not a rule". One says rule, the
        # other says not, from the same row. Refuse it at the boundary instead.
        if claim_kind:
            from normative import CLAIM_KINDS

            if str(claim_kind).strip().lower() not in CLAIM_KINDS:
                raise ValueError(
                    f"node {node_id!r} declares claim_kind {claim_kind!r}, which is "
                    f"not one of {CLAIM_KINDS}. An unrecognised authority value is "
                    "read inconsistently by different consumers; write a known kind "
                    "or leave it empty for unknown."
                )
        if claim_kind and not claim_kind_source:
            claim_kind_source = "declared"
        emb = embeddings[i]
        conn.execute(
            "CREATE (c:Concept {id: $id, label: $label, text_content: $content,"
            " semantic_anchor: $anchor, embedding: $emb, token_count: $tc,"
            " centrality_score: 0.0, is_metanode: $meta, linked_graph_id: $linked,"
            " kind: $format_kind, claim_kind: $kind, "
            "claim_kind_source: $kind_source})",
            {"id": node_id, "label": label, "content": content,
             "anchor": anchor or "", "emb": emb, "tc": token_count,
             "meta": is_metanode, "linked": linked_graph_id or "",
             "format_kind": format_kind or "", "kind": claim_kind or "",
             "kind_source": claim_kind_source or ""},
        )

    # Insert typed edges
    _sst_rel_map = {
        "leadsto": "LEADSTO",
        "contains": "CONTAINS",
        "expresses": "EXPRESSES",
        "nearto": "NEARTO",
    }
    for edge in edges:
        src, dst, sst_type = edge[0], edge[1], edge[2]
        edge_label = edge[3] if len(edge) > 3 else ""
        rel_table = _sst_rel_map.get(sst_type)
        if rel_table is None:
            raise ValueError(
                f"Invalid SST edge type '{sst_type}' on edge ({src} -> {dst}). "
                "Must be one of: leadsto, contains, expresses, nearto."
            )
        conn.execute(
            f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $dst}})"
            f" CREATE (a)-[:{rel_table} {{label: $label}}]->(b)",
            {"src": src, "dst": dst, "label": edge_label or ""},
        )

    print("Local database seeding complete.")


# ---------------------------------------------------------------------------
# Structural Index Computation
# ---------------------------------------------------------------------------

def _build_adjacency(conn: lb.Connection) -> tuple[
    dict[str, dict[str, list[str]]],  # out_adj: node -> {sst_type -> [neighbour_ids]}
    dict[str, dict[str, list[str]]],  # in_adj:  node -> {sst_type -> [neighbour_ids]}
    set[str],                          # all node IDs
]:
    """Build adjacency lists from the database."""
    out_adj: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    in_adj: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    all_nodes: set[str] = set()

    # Collect all node IDs
    for row in conn.execute("MATCH (c:Concept) RETURN c.id"):
        all_nodes.add(row[0])

    rel_map = {"leadsto": "LEADSTO", "contains": "CONTAINS", "expresses": "EXPRESSES", "nearto": "NEARTO"}
    for sst_type, rel_name in rel_map.items():
        for row in conn.execute(
            f"MATCH (a:Concept)-[:{rel_name}]->(b:Concept) RETURN a.id, b.id"
        ):
            src, dst = row[0], row[1]
            out_adj[src][sst_type].append(dst)
            in_adj[dst][sst_type].append(src)

    return dict(out_adj), dict(in_adj), all_nodes


def _compute_betweenness(
    all_nodes: set[str],
    out_adj: dict[str, dict[str, list[str]]],
) -> dict[str, float]:
    """Brandes' algorithm for betweenness centrality (unweighted, directed).

    Pure Python — no external dependencies. Fine for graphs < 500 nodes.
    """
    betweenness: dict[str, float] = {n: 0.0 for n in all_nodes}
    node_list = list(all_nodes)

    def get_neighbours(node: str) -> list[str]:
        neighbours = []
        for sst_type in SST_EDGE_TYPES:
            neighbours.extend(out_adj.get(node, {}).get(sst_type, []))
            # NEARTO is undirected — also traverse backward
            # But for betweenness we treat all edges as directed from out_adj
            # NEARTO backward edges are in in_adj, handled separately
        return neighbours

    # For betweenness, treat NEARTO as undirected by including both directions
    full_adj: dict[str, list[str]] = defaultdict(list)
    for node in all_nodes:
        for sst_type in SST_EDGE_TYPES:
            full_adj[node].extend(out_adj.get(node, {}).get(sst_type, []))
        # Add NEARTO reverse direction (undirected)
        # We need in_adj for this — rebuild from out_adj for NEARTO
    for node, type_map in out_adj.items():
        for dst in type_map.get("nearto", []):
            if node not in full_adj.get(dst, []):
                full_adj[dst].append(node)

    for s in node_list:
        # BFS from s
        stack: list[str] = []
        pred: dict[str, list[str]] = {n: [] for n in all_nodes}
        sigma: dict[str, int] = {n: 0 for n in all_nodes}
        sigma[s] = 1
        dist: dict[str, int] = {n: -1 for n in all_nodes}
        dist[s] = 0
        queue: deque[str] = deque([s])

        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in full_adj.get(v, []):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        delta: dict[str, float] = {n: 0.0 for n in all_nodes}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                betweenness[w] += delta[w]

    # Normalise
    n = len(node_list)
    if n > 2:
        norm = 1.0 / ((n - 1) * (n - 2))
        betweenness = {k: v * norm for k, v in betweenness.items()}

    return betweenness


def _find_contains_subtrees(out_adj: dict[str, dict[str, list[str]]]) -> dict[str, int]:
    """Assign each node to a CONTAINS subtree root (for bridge detection).

    Delegates to `spine.contains_subtrees`. This derivation used to exist twice
    — here and in `graph_read` — so a node's role and its position could be
    computed against different structures in the same payload. One derivation
    now; the behaviour here is unchanged, deliberately, because role semantics
    are load-bearing across the verdict pipeline.
    """
    from spine import contains_subtrees

    return contains_subtrees(out_adj)


def _sidecar_path(db_path: Path) -> Path:
    """Return the sidecar JSON path for a given .lbug file."""
    return db_path.with_suffix(".lbug.idx")


INDEX_SIDECAR_FORMAT = 2


def _index_payload_digest(payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def structural_topology_fingerprint(conn: lb.Connection) -> str:
    """Canonical identity of exactly the structure cached in ``.lbug.idx``.

    Structural roles, degrees, and betweenness depend on node identity and the
    typed directed edge multiset.  Labels and node prose do not affect them.
    Sorting makes the identity independent of storage/insertion order; keeping
    duplicate edges makes it sensitive to the degree changes they cause.
    """
    node_ids = sorted(str(row[0]) for row in conn.execute(
        "MATCH (c:Concept) RETURN c.id"
    ))
    edges: list[tuple[str, str, str]] = []
    for sst_type, rel_name in (
        ("leadsto", "LEADSTO"),
        ("contains", "CONTAINS"),
        ("expresses", "EXPRESSES"),
        ("nearto", "NEARTO"),
    ):
        edges.extend(
            (sst_type, str(row[0]), str(row[1]))
            for row in conn.execute(
                f"MATCH (a:Concept)-[:{rel_name}]->(b:Concept) RETURN a.id, b.id"
            )
        )

    digest = hashlib.sha256()
    for node_id in node_ids:
        digest.update(b"n\x00")
        digest.update(node_id.encode("utf-8"))
        digest.update(b"\x00")
    for sst_type, source, target in sorted(edges):
        digest.update(b"e\x00")
        digest.update(sst_type.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(target.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _save_index_sidecar(
    db_path: Path,
    index: dict[str, StructuralFacts],
    node_count: int,
    *,
    topology_fingerprint: str,
    index_mode: str = "full",
) -> None:
    """Persist the structural index to a JSON sidecar alongside the DB file."""
    sidecar = _sidecar_path(db_path)
    payload = {
        nid: {
            "roles": facts.roles,
            "betweenness_centrality": facts.betweenness_centrality,
            "in_degree": facts.in_degree,
            "out_degree": facts.out_degree,
        }
        for nid, facts in index.items()
    }
    data = {
        "format_version": INDEX_SIDECAR_FORMAT,
        "node_count": node_count,
        "topology_fingerprint": topology_fingerprint,
        "index_mode": index_mode,
        "index_sha256": _index_payload_digest({
            "index_mode": index_mode,
            "index": payload,
        }),
        "index": payload,
    }
    try:
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        print(f"  Structural index cached to {sidecar.name}")
    except Exception as e:
        print(f"  Warning: could not write index sidecar ({e})")


def _load_index_sidecar_record(
    db_path: Path,
    current_node_count: int,
    *,
    topology_fingerprint: str,
    allow_fast: bool = False,
) -> tuple[dict[str, StructuralFacts], str] | None:
    """Load a structural cache only when it is bound to this exact topology.

    Sidecars from format v1 carried only a node count.  They are intentionally
    misses: an edge edit can leave that count unchanged while changing every
    cached structural fact.
    """
    sidecar = _sidecar_path(db_path)
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None

    if data.get("format_version") != INDEX_SIDECAR_FORMAT:
        print("  Structural index cache is unbound/legacy. Recomputing.")
        return None

    if data.get("node_count") != current_node_count:
        print(f"  Structural index cache stale (node count {data.get('node_count')} → {current_node_count}). Recomputing.")
        return None

    if data.get("topology_fingerprint") != topology_fingerprint:
        print("  Structural index cache stale (topology changed). Recomputing.")
        return None

    payload = data.get("index")
    cached_mode = str(data.get("index_mode") or "full")
    if (
        not isinstance(payload, dict)
        or len(payload) != current_node_count
        or cached_mode not in {"full", "fast"}
        or data.get("index_sha256") != _index_payload_digest({
            "index_mode": cached_mode,
            "index": payload,
        })
    ):
        print("  Structural index cache incomplete or corrupt. Recomputing.")
        return None

    want_fast = os.environ.get("SST_FAST_STRUCTURAL_INDEX", "").strip().lower() in ("1", "true", "yes")
    if not allow_fast and not want_fast and cached_mode == "fast":
        print("  Structural index cache is fast-only; recomputing full (Brandes).")
        return None

    index: dict[str, StructuralFacts] = {}
    for nid, d in payload.items():
        index[nid] = StructuralFacts(
            roles=d.get("roles", []),
            betweenness_centrality=float(d.get("betweenness_centrality", 0.0)),
            in_degree=d.get("in_degree", {}),
            out_degree=d.get("out_degree", {}),
        )
    print(f"  Structural index loaded from cache ({current_node_count} nodes, skipping Brandes).")
    return index, cached_mode


def _load_index_sidecar(
    db_path: Path,
    current_node_count: int,
    *,
    topology_fingerprint: str,
) -> dict[str, StructuralFacts] | None:
    """Compatibility-shaped loader for the engine's full-index path."""
    record = _load_index_sidecar_record(
        db_path,
        current_node_count,
        topology_fingerprint=topology_fingerprint,
    )
    return record[0] if record is not None else None


def _grain_profile(conn: lb.Connection, node_count: int) -> dict:
    """How finely this graph cuts its sources, as facts rather than a verdict.

    The Planner can read density and depth but has never been able to tell
    whether a node is a paragraph or a sentence, because `source_unit_ids` was
    dropped at materialization. That decides how many nodes must be
    co-retrieved to reconstitute one section of source — on the
    repo-architecture arm the median was 15 against a Squad budget of 8-12, so
    a single module interface consumed the whole budget and its largest unit
    could not be retrieved in one pass at all.

    Reported, never bounded. A corpus may honestly want one-sentence rule
    nodes; those are what let a caller name the specific constraints a
    proposed change would have to respect. What retrieval needs is not a graph
    that conforms to one shape but a graph that says which shape it is.

    Absent on graphs built before the column existed, and absent is honest —
    an unknown grain must not read as a fine one.
    """

    try:
        rows = list(
            conn.execute(
                "MATCH (c:Concept) RETURN c.source_unit_ids, c.text_content"
            )
        )
    except Exception:
        return {}

    per_unit: dict[str, int] = {}
    payloads: list[int] = []
    attributed = 0
    for row in rows:
        units = row[0] or []
        payloads.append(len(str(row[1] or "")))
        if units:
            attributed += 1
        for unit_id in units:
            per_unit[str(unit_id)] = per_unit.get(str(unit_id), 0) + 1

    if not per_unit:
        return {}

    counts = sorted(per_unit.values())
    payloads.sort()

    def at(values: list[int], fraction: float) -> int:
        if not values:
            return 0
        return values[min(len(values) - 1, int(len(values) * fraction))]

    median = at(counts, 0.5)
    if median <= 2:
        character = f"coarse — a source unit becomes about {median} node(s)"
    elif median <= 8:
        character = f"moderate — a source unit becomes about {median} nodes"
    else:
        character = (
            f"fine — a source unit becomes about {median} nodes, so answering "
            "from one section means co-retrieving many"
        )

    return {
        "grain_character": character,
        "source_units": len(per_unit),
        "nodes_per_source_unit_median": median,
        "nodes_per_source_unit_max": counts[-1],
        "payload_chars_p50": at(payloads, 0.5),
        "payload_chars_p90": at(payloads, 0.9),
        # Below 1.0 the grain figures describe only part of the graph.
        "grain_attributed_fraction": (
            round(attributed / node_count, 3) if node_count else 0.0
        ),
    }


def compute_structural_index(conn: lb.Connection) -> dict[str, StructuralFacts]:
    """Compute the full structural index for all nodes."""
    fast = os.environ.get("SST_FAST_STRUCTURAL_INDEX", "").strip().lower() in ("1", "true", "yes")
    index_mode = "fast" if fast else "full"
    if fast:
        print("Computing structural index (fast: Brandes betweenness skipped)...")
    else:
        print("Computing structural index...")

    out_adj, in_adj, all_nodes = _build_adjacency(conn)
    if fast:
        betweenness = dict.fromkeys(all_nodes, 0.0)
    else:
        betweenness = _compute_betweenness(all_nodes, out_adj)
    subtree_map = _find_contains_subtrees(out_adj)

    # Determine betweenness threshold for nexus/bridge roles
    bc_values = sorted(betweenness.values(), reverse=True)
    top_10_pct_threshold = bc_values[max(0, len(bc_values) // 10)] if bc_values else 0.0

    index: dict[str, StructuralFacts] = {}

    for node_id in all_nodes:
        out_deg = {}
        in_deg = {}
        for sst_type in SST_EDGE_TYPES:
            out_deg[sst_type] = len(out_adj.get(node_id, {}).get(sst_type, []))
            in_deg[sst_type] = len(in_adj.get(node_id, {}).get(sst_type, []))

        bc = betweenness.get(node_id, 0.0)
        total = sum(out_deg.values()) + sum(in_deg.values())

        roles: list[str] = []

        # Causal roles (based on LEADSTO)
        if in_deg["leadsto"] == 0 and out_deg["leadsto"] > 0:
            roles.append("causal_origin")
        if out_deg["leadsto"] == 0 and in_deg["leadsto"] > 0:
            roles.append("causal_terminal")
        if in_deg["leadsto"] > 0 and out_deg["leadsto"] > 0 and bc >= top_10_pct_threshold and top_10_pct_threshold > 0:
            roles.append("causal_nexus")

        # Associative hub (NEARTO degree >= 3, counting both directions)
        nearto_degree = out_deg["nearto"] + in_deg["nearto"]
        if nearto_degree >= 3:
            roles.append("associative_hub")

        # Inter-region bridge: high betweenness AND connects distinct CONTAINS subtrees
        if bc >= top_10_pct_threshold and top_10_pct_threshold > 0:
            my_subtree = subtree_map.get(node_id)
            neighbour_subtrees = set()
            for sst_type in SST_EDGE_TYPES:
                for nb in out_adj.get(node_id, {}).get(sst_type, []):
                    s = subtree_map.get(nb)
                    if s is not None:
                        neighbour_subtrees.add(s)
                for nb in in_adj.get(node_id, {}).get(sst_type, []):
                    s = subtree_map.get(nb)
                    if s is not None:
                        neighbour_subtrees.add(s)
            if my_subtree is not None:
                neighbour_subtrees.add(my_subtree)
            if len(neighbour_subtrees) >= 2:
                roles.append("inter_region_bridge")

        # Structural edge cases
        if total == 0:
            roles.append("orphan")
        elif total == 1:
            roles.append("weakly_connected")

        index[node_id] = StructuralFacts(
            roles=roles,
            betweenness_centrality=bc,
            in_degree=in_deg,
            out_degree=out_deg,
        )

    # Persist normalised degree centrality on Concept.centrality_score.
    # Supported field (retrieval tools + ambient LOD sizing) — NOT betweenness.
    # Written in both full and fast modes: degree needs no Brandes.
    max_degree = max((f.total_degree for f in index.values()), default=1) or 1
    for node_id, facts in index.items():
        score = round(facts.total_degree / max_degree, 4)
        conn.execute(
            "MATCH (c:Concept {id: $id}) SET c.centrality_score = $score",
            {"id": node_id, "score": score},
        )

    print(f"  Structural index built for {len(index)} nodes ({index_mode}).")
    role_counts = defaultdict(int)
    for f in index.values():
        for r in f.roles:
            role_counts[r] += 1
    for role, count in sorted(role_counts.items()):
        print(f"    {role}: {count}")

    return index


# ---------------------------------------------------------------------------
# Graph Compass
# ---------------------------------------------------------------------------

def compute_compass(
    conn: lb.Connection,
    structural_index: dict[str, StructuralFacts],
) -> Compass:
    """Compute the Graph Compass — a graph-to-language translation for the Planner."""
    print("Computing Graph Compass...")

    # --- Graph profile ---
    node_count = 0
    for row in conn.execute("MATCH (c:Concept) RETURN count(c)"):
        node_count = row[0]

    edge_counts: dict[str, int] = {}
    total_edges = 0
    rel_map = {"leadsto": "LEADSTO", "contains": "CONTAINS", "expresses": "EXPRESSES", "nearto": "NEARTO"}
    for sst_type, rel_name in rel_map.items():
        count = 0
        for row in conn.execute(f"MATCH ()-[:{rel_name}]->() RETURN count(*)"):
            count = row[0]
        edge_counts[sst_type] = count
        total_edges += count

    # Dominant SST type
    dominant = max(edge_counts, key=edge_counts.get) if edge_counts else "leadsto"

    # Structural character
    if total_edges == 0:
        structural_character = "empty graph"
    else:
        ratios = {k: v / total_edges for k, v in edge_counts.items()}
        if ratios.get("leadsto", 0) > 0.5:
            structural_character = "predominantly causal — reasons forward from causes to effects along distinct chains"
        elif ratios.get("contains", 0) > 0.5:
            structural_character = "predominantly hierarchical — organised into containment trees with membership relationships"
        elif ratios.get("nearto", 0) > 0.4:
            structural_character = "predominantly associative — dense similarity/proximity links with lateral connections"
        elif ratios.get("expresses", 0) > 0.4:
            structural_character = "predominantly attributive — concepts expressed through properties and states"
        else:
            top2 = sorted(ratios.items(), key=lambda x: x[1], reverse=True)[:2]
            structural_character = (
                f"mixed — primary {top2[0][0]} ({top2[0][1]:.0%}) with secondary "
                f"{top2[1][0]} ({top2[1][1]:.0%}) texture"
            )

    # Depth profile: BFS from causal origins (or all nodes if none)
    out_adj, _, all_nodes = _build_adjacency(conn)
    origins = [nid for nid, f in structural_index.items() if "causal_origin" in f.roles]
    if not origins:
        origins = list(all_nodes)[:3]  # fallback
    elif os.environ.get("SST_FAST_STRUCTURAL_INDEX", "").strip().lower() in ("1", "true", "yes"):
        # MetaQA-scale graphs can have huge origin sets; each BFS can sweep the component.
        origins = origins[:15]

    all_depths: list[int] = []
    max_depth = 0
    for origin in origins:
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(origin, 0)])
        while queue:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            all_depths.append(depth)
            max_depth = max(max_depth, depth)
            for sst_type in SST_EDGE_TYPES:
                for nb in out_adj.get(node, {}).get(sst_type, []):
                    if nb not in visited:
                        queue.append((nb, depth + 1))

    median_depth = statistics.median(all_depths) if all_depths else 0
    avg_degree = round(total_edges * 2 / max(node_count, 1), 1)

    if max_depth <= 3:
        depth_desc = f"shallow — median path length {median_depth:.0f}, max depth {max_depth}"
    elif max_depth <= 7:
        depth_desc = f"moderately deep — median path length {median_depth:.0f}, max depth {max_depth}"
    else:
        depth_desc = f"deep — median path length {median_depth:.0f}, max depth {max_depth}"

    if avg_degree < 2.0:
        density_desc = f"very sparse — average degree {avg_degree}"
    elif avg_degree < 4.0:
        density_desc = f"sparse — average degree {avg_degree}"
    else:
        density_desc = f"moderately dense — average degree {avg_degree}"

    # v7 Layer 1: role populations surface alongside graph shape so the
    # Planner's classifier sees role counts without needing to read Layer 3.
    role_populations: dict[str, int] = {}
    for facts in structural_index.values():
        for role in facts.roles:
            role_populations[role] = role_populations.get(role, 0) + 1

    # Edge schema direction: sample (source_label, target_label) pairs per SST
    # type and compute directional prevalence. Gives the Planner ground truth on
    # which node types connect to which, preventing direction-guess errors.
    edge_schema: dict[str, dict] = {}
    _SAMPLE_LIMIT = 200  # sample size for prevalence estimation
    for sst_type, rel_name in rel_map.items():
        if edge_counts.get(sst_type, 0) == 0:
            continue
        try:
            rows = list(conn.execute(
                f"MATCH (src:Concept)-[:{rel_name}]->(dst:Concept) "
                "RETURN src.label, dst.label "
                f"LIMIT {_SAMPLE_LIMIT}"
            ))
        except Exception:
            rows = []
        if not rows:
            continue
        # Count (src_label, dst_label) pair frequencies.
        pair_counts: dict[tuple, int] = {}
        for src_lbl, dst_lbl in rows:
            key = (str(src_lbl or "?"), str(dst_lbl or "?"))
            pair_counts[key] = pair_counts.get(key, 0) + 1
        total_sampled = len(rows)
        # Top-3 pairs with prevalence percentage.
        top_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        examples = [
            {
                "source": src,
                "target": dst,
                "prevalence_pct": round(cnt / total_sampled * 100),
            }
            for (src, dst), cnt in top_pairs
        ]
        # Dominant direction summary string.
        if examples:
            dominant_pair = examples[0]
            pct = dominant_pair["prevalence_pct"]
            if pct >= 60:
                summary = (
                    f"predominantly {dominant_pair['source']} → {dominant_pair['target']} "
                    f"(~{pct}% of sampled edges)"
                )
            else:
                top2 = examples[:2]
                summary = " | ".join(
                    f"{e['source']} → {e['target']} (~{e['prevalence_pct']}%)" for e in top2
                )
        else:
            summary = "direction varies"
        edge_schema[sst_type] = {"summary": summary, "examples": examples}

    # Edge label inventory: distinct r.label values per SST type with counts
    # and representative src→dst node-label examples. Gives the Planner the
    # vocabulary it needs to populate chain-contract edge_labels without
    # domain-specific coaching embedded in the system prompt.
    edge_label_inventory: dict[str, list[dict]] = {}
    _LABEL_SAMPLE = 2000
    for sst_type, rel_name in rel_map.items():
        if edge_counts.get(sst_type, 0) == 0:
            continue
        try:
            rows = list(conn.execute(
                f"MATCH (src:Concept)-[r:{rel_name}]->(dst:Concept) "
                "RETURN r.label, src.label, dst.label "
                f"LIMIT {_LABEL_SAMPLE}"
            ))
        except Exception:
            rows = []
        if not rows:
            continue
        label_data: dict[str, dict] = {}
        for edge_lbl, src_lbl, dst_lbl in rows:
            key = (str(edge_lbl or "")).strip()
            if key not in label_data:
                label_data[key] = {"count": 0, "examples": []}
            label_data[key]["count"] += 1
            if len(label_data[key]["examples"]) < 2:
                label_data[key]["examples"].append(
                    {"src": str(src_lbl or "?"), "dst": str(dst_lbl or "?")}
                )
        inventory = sorted(
            [
                {
                    "label": lbl or "(unlabeled)",
                    "count": data["count"],
                    "examples": data["examples"],
                }
                for lbl, data in label_data.items()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )
        edge_label_inventory[sst_type] = inventory

    # Connected components (weak — treat all edges as undirected).
    # Tells the Planner whether the graph is one connected mass or several
    # isolated regions, so it can avoid issuing find_paths between entities
    # that can never be reached from each other.
    parent: dict[str, str] = {n: n for n in all_nodes}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for node, type_map in out_adj.items():
        for sst_type, neighbours in type_map.items():
            for nb in neighbours:
                if nb in parent:
                    _union(node, nb)

    component_sizes: dict[str, int] = {}
    for n in all_nodes:
        root = _find(n)
        component_sizes[root] = component_sizes.get(root, 0) + 1

    sizes = sorted(component_sizes.values(), reverse=True)
    n_components = len(sizes)
    top5_sizes = sizes[:5]
    largest_pct = round(sizes[0] / node_count * 100) if node_count and sizes else 0

    connected_components = {
        "count": n_components,
        "top5_sizes": top5_sizes,
        "largest_pct": largest_pct,
    }

    graph_identity: dict[str, str] = {}
    try:
        metadata = list(
            conn.execute(
                "MATCH (g:GraphMetadata) RETURN g.id, g.domain LIMIT 1"
            )
        )
        if metadata:
            graph_identity = {
                "graph_id": str(metadata[0][0] or ""),
                "domain": str(metadata[0][1] or ""),
            }
    except Exception:
        # Existing and fixture graphs predate GraphMetadata.
        pass

    # Does this graph make normative claims at all? Descriptive, never a mode:
    # nothing branches on it. It exists so an ABSENCE can be reported
    # truthfully — "no rule covers your case" and "this graph states no rules"
    # are different answers, and today both come back as UNGOVERNED.
    #
    # Safe as an aggregate in a way per-node classification is not: measured
    # across the corpora on disk this separates deep-space 0.01, LOTR 0.05 and
    # AI-history 0.00 from Tesco 0.75 and English negligence 0.59, and stays
    # separated under every variant of the lexical rules tried.
    try:
        claim_rows = list(conn.execute(
            "MATCH (c:Concept) RETURN c.text_content, c.claim_kind, "
            "c.claim_kind_source"
        ))
        claim_nodes = [
            {"text_content": r[0], "claim_kind": r[1], "claim_kind_source": r[2]}
            for r in claim_rows
        ]
    except Exception:
        # Pre-migration graph: fall back to the text prefix and lexical prior.
        claim_nodes = [
            {"text_content": r[0]}
            for r in conn.execute("MATCH (c:Concept) RETURN c.text_content")
        ]
    normative_profile = normative.profile(claim_nodes)

    graph_profile = {
        "node_count": node_count,
        "structural_character": structural_character,
        **normative_profile.to_dict(),
        # The measurement above described the graph and drove nothing, so a
        # caller that did not name a verdict space got `coverage` over a corpus
        # with no rules in it. Publishing the derived default is what lets the
        # rest of the system stop guessing; it remains a default, and a caller
        # who declares a space still wins.
        "default_verdict_space": normative.default_verdict_space(
            normative_profile.character
        ),
        **_grain_profile(conn, node_count),
        "depth_profile": depth_desc,
        "density": density_desc,
        "dominant_sst_type": dominant.upper(),
        "edge_counts": edge_counts,
        "role_populations": role_populations,
        "total_edges": total_edges,
        "edge_schema": edge_schema,
        "edge_label_inventory": edge_label_inventory,
        "connected_components": connected_components,
        **graph_identity,
    }

    # --- Landmark nodes ---
    # Prefer betweenness when Brandes ran. Fast mode zeros betweenness — fall
    # back to total degree so large-graph / SST_FAST_STRUCTURAL_INDEX startups
    # still get a non-empty landmark set for Compass + ambient LOD.
    _any_bc = any(f.betweenness_centrality > 0 for f in structural_index.values())
    _landmark_kind = "betweenness" if _any_bc else "degree"
    ranked = sorted(
        structural_index.items(),
        key=(
            (lambda x: (x[1].betweenness_centrality, x[0]))
            if _any_bc
            else (lambda x: (x[1].total_degree, x[0]))
        ),
        reverse=True,
    )
    landmark_count = min(8, max(3, node_count // 5))
    landmarks = []
    _max_deg = max((f.total_degree for f in structural_index.values()), default=1) or 1
    for node_id, facts in ranked[:landmark_count]:
        if _any_bc and facts.betweenness_centrality <= 0:
            break
        if not _any_bc and facts.total_degree <= 0:
            break
        # Fetch label and anchor preview
        row = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.label, c.semantic_anchor, c.text_content, c.centrality_score",
            {"id": node_id},
        ))
        if not row:
            continue
        label, anchor, text, cent = row[0][0], row[0][1], row[0][2], row[0][3]
        preview = anchor if anchor else (text[:200] + "..." if len(text) > 200 else text)

        role_desc = ", ".join(facts.roles) if facts.roles else "no special role"
        if _landmark_kind == "betweenness":
            why = f"betweenness centrality {facts.betweenness_centrality:.3f} — {role_desc}"
        else:
            why = f"degree centrality {facts.total_degree} (fast index) — {role_desc}"

        landmarks.append({
            "id": node_id,
            "label": label,
            "anchor_preview": preview,
            "roles": facts.roles,
            "why_landmark": why,
            "importance_kind": _landmark_kind,
            "centrality_score": float(cent) if cent is not None else round(
                facts.total_degree / _max_deg, 4
            ),
            "total_degree": facts.total_degree,
            "betweenness_centrality": round(float(facts.betweenness_centrality), 4),
        })

    # --- Metanodes ---
    metanodes = []
    for row in conn.execute(
        "MATCH (c:Concept) WHERE c.is_metanode = true "
        "RETURN c.id, c.label, c.linked_graph_id, c.semantic_anchor, c.text_content"
    ):
        node_id, label, linked_id, anchor, text = row[0], row[1], row[2], row[3], row[4]
        preview = anchor if anchor else (text[:200] + "..." if len(text) > 200 else text)
        metanodes.append({
            "id": node_id,
            "label": label,
            "linked_graph_id": linked_id,
            "anchor_preview": preview,
        })

    # --- Structural gaps ---
    orphans = sum(1 for f in structural_index.values() if "orphan" in f.roles)
    weakly = sum(1 for f in structural_index.values() if "weakly_connected" in f.roles)

    # --- Node Census (top nodes by betweenness, capped for large graphs) ---
    # v7 Layer 3: every node with anchor_preview so the Planner's seed
    # selection is content-aware. Previews are capped at ~40 words; Layer 4
    # (on demand) has full previews. For graphs >500 nodes we cap to the top
    # 500 by betweenness (or degree when Brandes was skipped) — the Planner
    # cannot meaningfully use 43k entries.
    _MAX_CENSUS = 500
    _any_bc_census = any(f.betweenness_centrality > 0 for f in structural_index.values())
    # Ties break on node id, and that is load-bearing rather than tidy.
    #
    # Without it the sort is stable over `structural_index`'s INSERTION order,
    # which differs by how the index arrived: recomputing builds it by
    # iterating a set (hash-seed dependent, so it varies per process), while
    # loading the `.idx` sidecar freezes whatever order that file was written
    # in. Ties are the common case, not the corner — on the 31-node hexagonal
    # fixture 12 nodes sit at betweenness 0.0 and several more share 0.0042.
    #
    # The census feeds the Planner briefing and entity resolution, and
    # resolution takes the first substring hit, so the order decides which node
    # answers. Measured on that fixture, holding the file and every value
    # identical and permuting ONLY the key order: as-written GOVERNED 2/2,
    # alphabetical UNGOVERNED 2/2, reversed UNGOVERNED 2/2. That is a
    # governance verdict turning on dict ordering.
    #
    # This makes the order canonical. It does NOT make the answer right: that
    # the verdict is sensitive to census order at all is a separate defect, and
    # pinning the order stabilises it rather than removing it.
    _ranked_for_census = sorted(
        structural_index.items(),
        key=(
            (lambda x: (x[1].betweenness_centrality, x[0]))
            if _any_bc_census
            else (lambda x: (x[1].total_degree, x[0]))
        ),
        reverse=True,
    )[:_MAX_CENSUS]

    # Bulk-fetch all node labels in one query to avoid N individual round-trips.
    _label_map: dict[str, tuple] = {}
    for _row in conn.execute(
        "MATCH (c:Concept) RETURN c.id, c.label, c.is_metanode, c.semantic_anchor, c.text_content"
    ):
        _label_map[_row[0]] = (_row[1], bool(_row[2]), _row[3] or "", _row[4] or "")

    node_census: list[dict] = []
    for node_id, facts in _ranked_for_census:
        _node_data = _label_map.get(node_id)
        if not _node_data:
            continue
        label, is_meta, anchor, text = _node_data

        if anchor.strip():
            preview = anchor.strip()
        elif text:
            preview = text.split()
            preview = " ".join(preview[:40]) + ("..." if len(preview) > 40 else "")
        else:
            preview = ""

        # Dominant outgoing edge type for routing signal
        out_counts = {k: v for k, v in facts.out_degree.items() if v > 0}
        dominant_edge = max(out_counts, key=out_counts.get) if out_counts else "none"

        # Full adjacency (ID list) for the structural map
        adj_map = {
            sst_type: neighbors
            for sst_type, neighbors in out_adj.get(node_id, {}).items()
            if neighbors
        }

        census_entry: dict = {
            "id": node_id,
            "label": label,
            "roles": facts.roles,
            "dominant_out_edge": dominant_edge,
            "out_adjacency": adj_map,
            "anchor_preview": preview,
            "betweenness_centrality": round(float(facts.betweenness_centrality), 4),
            "total_degree": facts.total_degree,
        }
        if is_meta:
            census_entry["is_metanode"] = True
        node_census.append(census_entry)

    compass = Compass(
        graph_profile=graph_profile,
        landmark_nodes=landmarks,
        metanodes=metanodes,
        structural_gaps={"orphaned_nodes": orphans, "weakly_connected_nodes": weakly},
        node_census=node_census,
    )

    print(f"  Graph: {node_count} nodes, {total_edges} edges")
    print(f"  Character: {structural_character}")
    print(f"  Landmarks: {len(landmarks)}")
    print(f"  Metanodes: {len(metanodes)}")
    print(f"  Gaps: {orphans} orphaned, {weakly} weakly connected")

    return compass



# ---------------------------------------------------------------------------
# Connection Management
# ---------------------------------------------------------------------------

def _effective_db_path(db_path: Path | str | None) -> Path:
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    # When a connection is already open and no explicit path is requested,
    # return the active path so callers like planner.get_connection() don't
    # accidentally trigger reset_connection() by resolving to DEFAULT_DB_PATH.
    if _db_path is not None:
        return Path(_db_path).expanduser().resolve()
    env_path = os.environ.get("SST_DB_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_DB_PATH.expanduser().resolve()


def get_connection(
    db_path: Path | str | None = None,
    *,
    auto_seed: bool | None = None,
) -> lb.Connection:
    """Return a process-wide LadybugDB connection.

    ``auto_seed``: seed the demo corpus if the graph is empty. ``None`` (default)
    defers to the ``SST_AUTO_SEED`` env var; unset means **refuse** with
    :class:`EmptyGraphError`. Library/server callers should never enable this.
    """
    global _connection, _database, _db_path
    path = _effective_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if _connection is not None and _db_path is not None:
        if Path(_db_path).resolve() == path:
            return _connection
        reset_connection()

    if _connection is None:
        _acquire_owner_lock(path)
        _db_path = path
        try:
            _database = lb.Database(str(path))
            _connection = lb.Connection(_database)
        except BaseException:
            reset_connection()
            raise

        # Check if schema already exists and is populated. Never treat arbitrary
        # query/IO errors as "empty" — that can wipe a locked or valid DB (see benchmarks).
        try:
            res = _connection.execute("MATCH (c:Concept) RETURN count(c)")
            rows = list(res)
            count = int(rows[0][0]) if rows else 0
        except Exception as exc:
            err = str(exc).lower()
            if any(
                tok in err
                for tok in (
                    "binder exception",
                    "table",
                    "concept",
                    "does not exist",
                    "not exist",
                    "no node table",
                )
            ):
                count = 0
            else:
                raise RuntimeError(
                    f"Cannot query Concept count on {path} (refusing to auto-seed): {exc}"
                ) from exc
        if count == 0:
            allow_seed = (
                auto_seed
                if auto_seed is not None
                else os.environ.get("SST_AUTO_SEED", "").strip().lower() in ("1", "true", "yes")
            )
            if not allow_seed:
                # Ops-level honest failure: refuse rather than fabricate a default
                # corpus at a wrong/fresh path. Do not cache a connection to an
                # empty graph — the next call must re-evaluate.
                reset_connection()
                raise EmptyGraphError(
                    f"No Concept nodes at {path}. Refusing to auto-seed a default "
                    "corpus. Point SST_DB_PATH at a built graph, or opt in to demo "
                    "seeding via get_connection(auto_seed=True) / SST_AUTO_SEED=1."
                )
            print("Initializing schema and seeding graph...")
            try:
                _ensure_schema_and_seed(_connection)
            except BaseException:
                # Seed failed pre-mutation: drop the half-open connection so a
                # later call doesn't silently return an empty graph.
                reset_connection()
                raise
        else:
            migrate_claim_kind_columns(_connection)
            migrate_format_kind_column(_connection)

    return _connection


#: Added after every graph on disk was already built, so opening one must add
#: them rather than assume them. Kept narrow on purpose: this is an additive,
#: defaulted column pair, not a general migration framework.
_CLAIM_KIND_COLUMNS = (
    ("claim_kind", "STRING DEFAULT ''"),
    ("claim_kind_source", "STRING DEFAULT ''"),
)


def migrate_claim_kind_columns(conn: "lb.Connection") -> list[str]:
    """Add the claim-kind columns to a graph built before they existed.

    Returns the columns actually added. Idempotent: LadybugDB raises
    "already has property" on a re-add, which is the success case on the second
    call and is swallowed. Any other failure is left alone — a graph that
    cannot take the column still reads correctly, because `normative.classify`
    falls back to the text prefix.
    """
    added: list[str] = []
    for name, decl in _CLAIM_KIND_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE Concept ADD {name} {decl}")
            added.append(name)
        except Exception as exc:  # noqa: BLE001
            if "already has property" not in str(exc).lower():
                from sst_debug import log_event

                log_event("claim_kind_migration_skipped",
                          column=name, error=str(exc)[:120])
    return added


def migrate_format_kind_column(conn: "lb.Connection") -> list[str]:
    """Add the user-format node kind to graphs built before graph contracts."""
    try:
        conn.execute("ALTER TABLE Concept ADD kind STRING DEFAULT ''")
        return ["kind"]
    except Exception as exc:  # noqa: BLE001
        if "already has property" not in str(exc).lower():
            from sst_debug import log_event

            log_event("format_kind_migration_skipped", error=str(exc)[:120])
        return []


def get_structural_index(conn: "lb.Connection | None") -> dict[str, StructuralFacts]:
    """Return the structural index, loading from sidecar cache if valid, else computing."""
    global _structural_index
    if conn is None:
        return _structural_index or {}
    if _structural_index is None:
        topology_fingerprint = structural_topology_fingerprint(conn)
        # Try sidecar cache first
        if _db_path is not None:
            rows = list(conn.execute("MATCH (c:Concept) RETURN count(c)"))
            node_count = rows[0][0] if rows else 0
            cached = _load_index_sidecar(
                _db_path,
                node_count,
                topology_fingerprint=topology_fingerprint,
            )
            if cached is not None:
                _structural_index = cached
                return _structural_index

        # Compute from scratch and persist
        _structural_index = compute_structural_index(conn)
        if _db_path is not None:
            _fast = os.environ.get("SST_FAST_STRUCTURAL_INDEX", "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            _save_index_sidecar(
                _db_path,
                _structural_index,
                len(_structural_index),
                topology_fingerprint=topology_fingerprint,
                index_mode="fast" if _fast else "full",
            )

    return _structural_index


def get_compass(conn: lb.Connection, structural_index: dict[str, StructuralFacts]) -> Compass:
    """Return the Graph Compass, computing it if needed."""
    global _compass, _graph_schema
    if _compass is None:
        _compass = compute_compass(conn, structural_index)
        _graph_schema = compute_graph_schema(structural_index, _compass)
    return _compass


def _bind_grain_connection(conn: object) -> None:
    """Drop grain caches when the process moves to a different graph."""

    global _grain, _source_unit_index, _grain_conn
    if _grain_conn is not conn:
        _grain = None
        _source_unit_index = None
        _grain_conn = conn


_GRAIN_KEYS = (
    "grain_character",
    "source_units",
    "nodes_per_source_unit_median",
    "nodes_per_source_unit_max",
    "payload_chars_p50",
    "payload_chars_p90",
    "grain_attributed_fraction",
)


def get_grain_profile(conn: "lb.Connection | None") -> dict:
    """Grain facts for the open graph, without requiring a computed Compass.

    `compute_compass` already splices these into `graph_profile`, but retrieval
    tiers that need grain (the Squad budget) run with a connection and no
    guarantee the Compass was built — notably in tests and in packet-direct
    callers. Reading it from the Compass when one exists and computing it
    directly otherwise keeps a single definition and one scan per process.
    """

    global _grain
    if _grain is not None and (conn is None or conn is _grain_conn):
        return _grain
    if conn is None:
        return {}
    _bind_grain_connection(conn)
    if _compass is not None:
        profile = _compass.graph_profile or {}
        if any(k in profile for k in _GRAIN_KEYS):
            _grain = {k: profile[k] for k in _GRAIN_KEYS if k in profile}
            return _grain
    try:
        rows = list(conn.execute("MATCH (c:Concept) RETURN count(c)"))
        node_count = int(rows[0][0]) if rows else 0
    except Exception:
        return {}
    _grain = _grain_profile(conn, node_count)
    return _grain


def get_source_unit_index(conn: "lb.Connection | None") -> dict[str, list[str]]:
    """source_unit_id → every node id carrying it, computed once per graph.

    This is what makes "is this source unit fully represented in the packet?" a
    set operation rather than a judgement. It is a full scan, so it is cached
    alongside the structural index and invalidated with it.

    Empty on graphs built before the column existed — callers must read empty
    as "unknown", never as "every unit is complete".
    """

    global _source_unit_index
    if _source_unit_index is not None and (conn is None or conn is _grain_conn):
        return _source_unit_index
    if conn is None:
        return {}
    _bind_grain_connection(conn)
    index: dict[str, list[str]] = {}
    try:
        rows = list(conn.execute("MATCH (c:Concept) RETURN c.id, c.source_unit_ids"))
    except Exception:
        # Pre-column graph. Cache the emptiness so we do not rescan per packet.
        _source_unit_index = {}
        return _source_unit_index
    for row in rows:
        node_id = str(row[0] or "")
        if not node_id:
            continue
        for unit_id in (row[1] or []):
            index.setdefault(str(unit_id), []).append(node_id)
    _source_unit_index = index
    return _source_unit_index


def compute_graph_schema(
    structural_index: "dict[str, StructuralFacts]",
    compass: "Compass",
) -> "GraphSchema":
    """Derive a schema-level summary from the structural index and compass.

    Runs once at startup. The result is cheap to compute (one linear pass over
    the index) and gives the Planner's plan-validation step the structural facts
    it needs without requiring a live DB connection.
    """
    edge_types_present: set[str] = set()
    node_out_edge_types: dict[str, frozenset] = {}
    node_in_edge_types: dict[str, frozenset] = {}
    node_labels: dict[str, str] = {}
    role_outgoing: dict[str, set] = {}

    for node_id, facts in structural_index.items():
        out_present = frozenset(et for et, cnt in facts.out_degree.items() if cnt > 0)
        in_present = frozenset(et for et, cnt in facts.in_degree.items() if cnt > 0)
        node_out_edge_types[node_id] = out_present
        node_in_edge_types[node_id] = in_present
        edge_types_present.update(out_present)
        for role in facts.roles:
            role_outgoing.setdefault(role, set()).update(out_present)

    # Populate node_labels from compass node_census (already in memory)
    for entry in compass.node_census:
        nid = entry.get("id") or ""
        lbl = entry.get("label") or ""
        if nid and lbl:
            node_labels[nid] = lbl

    return GraphSchema(
        edge_types_present=edge_types_present,
        node_out_edge_types=node_out_edge_types,
        node_in_edge_types=node_in_edge_types,
        node_labels=node_labels,
        role_outgoing_edge_types={r: list(s) for r, s in role_outgoing.items()},
    )


def get_graph_schema() -> "GraphSchema":
    """Return the cached GraphSchema (computed once after get_compass)."""
    return _graph_schema or GraphSchema()


def reset_connection() -> None:
    """Tear down the global connection so the next get_connection() call re-initialises.

    The embeddings client goes with it. It is built once from
    `OPENROUTER_API_KEY` and then cached for the life of the process, so a
    teardown that left it standing handed the next caller a client bound to
    credentials that may since have been rotated or removed — and, in tests,
    made `get_connection(auto_seed=True)` succeed with no key in the
    environment, because the client had captured one earlier. That presented as
    an order-dependent failure in the server-readiness suite and was twice
    misdiagnosed here as disk pressure.
    """
    global _connection, _database, _db_path, _structural_index, _compass, _graph_schema
    global _embeddings_model, _source_unit_index, _grain, _grain_conn
    _embeddings_model = None
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        _connection = None
    if _database is not None:
        try:
            _database.close()
        except Exception:
            pass
        _database = None
    _db_path = None
    _structural_index = None
    _compass = None
    _graph_schema = None
    _source_unit_index = None
    _grain = None
    _grain_conn = None
    _release_owner_lock()


# ---------------------------------------------------------------------------
# GraphSession — explicit lifecycle for MCP / server (default session = globals)
# ---------------------------------------------------------------------------


class GraphSession:
    """Object handle for one LadybugDB graph.

    Module-level ``get_connection`` / ``reset_connection`` remain thin delegates
    over a process-default session (existing call sites unchanged). MCP and
    encode/snapshot swap should construct sessions explicitly via ``open``.

    Do **not** open multiple sessions against the same ``.lbug`` concurrently —
    LadybugDB is single-owner. ``get_connection`` takes an exclusive owner lock
    so a second process (MCP vs Review) is refused instead of rewriting the file.
    """

    def __init__(self) -> None:
        self._graph_version: str = ""

    # --- live views of process globals (default session) OR owned after open ---
    @property
    def path(self) -> Path | None:
        return _db_path

    @property
    def connection(self) -> lb.Connection | None:
        return _connection

    @property
    def structural_index(self) -> dict[str, StructuralFacts] | None:
        return _structural_index

    @property
    def compass(self) -> Compass | None:
        return _compass

    @property
    def graph_schema(self) -> GraphSchema | None:
        return _graph_schema

    @property
    def graph_version(self) -> str:
        return self._graph_version

    def open(self, path: Path | str, *, auto_seed: bool = False) -> "GraphSession":
        """Reset process graph state and open ``path`` (auto_seed default False)."""
        reset_connection()
        conn = get_connection(path, auto_seed=auto_seed)
        si = get_structural_index(conn)
        get_compass(conn, si)
        self.refresh_version()
        return self

    def close(self) -> None:
        reset_connection()
        self._graph_version = ""

    def refresh_version(self) -> str:
        self._graph_version = get_graph_version(_connection)
        return self._graph_version


_DEFAULT_GRAPH_SESSION = GraphSession()


def default_graph_session() -> GraphSession:
    """Process-default session mirroring module-level connection globals."""
    return _DEFAULT_GRAPH_SESSION


# ---------------------------------------------------------------------------
# v9: graph_version + describe_graph (Agent Contract v1 §4)
# ---------------------------------------------------------------------------

def fingerprint_connection(conn: lb.Connection) -> str:
    """Content identity of an open graph: sorted concepts + sorted edges.

    The single definition of "is this the same graph". `graph_version` is this
    truncated, and `mcp_server.history.graph_fingerprint` is this over a path
    the caller owns — one function, because the previous arrangement had two
    and they disagreed.

    Every field that a reader can act on is in here, `claim_kind` included: a
    node demoted from governing to contextual changes no count and no mtime,
    but it changes what the graph will certify, so it must change the version.
    """
    concepts: list[list[object]] = []
    has_format_kind = True
    has_claim_kind = True
    try:
        rows = conn.execute(
            "MATCH (c:Concept) RETURN c.id, c.label, c.text_content, "
            "c.semantic_anchor, c.kind, c.claim_kind, c.claim_kind_source, "
            "c.is_metanode, c.linked_graph_id"
        )
    except RuntimeError:
        has_format_kind = False
        try:
            rows = conn.execute(
                "MATCH (c:Concept) RETURN c.id, c.label, c.text_content, "
                "c.semantic_anchor, c.claim_kind, c.claim_kind_source, "
                "c.is_metanode, c.linked_graph_id"
            )
        except RuntimeError:
            has_claim_kind = False
            rows = conn.execute(
                "MATCH (c:Concept) RETURN c.id, c.label, c.text_content, "
                "c.semantic_anchor, c.is_metanode, c.linked_graph_id"
            )
    while rows.has_next():
        values = rows.get_next()
        if has_format_kind:
            concepts.append(
                [str(values[i] or "") for i in range(7)]
                + [bool(values[7]), str(values[8] or "")]
            )
        elif has_claim_kind:
            concepts.append(
                [str(values[i] or "") for i in range(4)]
                + [""]
                + [str(values[i] or "") for i in range(4, 6)]
                + [bool(values[6]), str(values[7] or "")]
            )
        else:
            concepts.append(
                [str(values[i] or "") for i in range(4)]
                + ["", "", ""]
                + [bool(values[4]), str(values[5] or "")]
            )
    concepts.sort(key=lambda row: row[0])

    edges: list[list[str]] = []
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        rows = conn.execute(
            f"MATCH (a:Concept)-[r:{rel}]->(b:Concept) RETURN a.id, b.id, r.label"
        )
        while rows.has_next():
            source_id, target_id, label = rows.get_next()
            edges.append([rel, str(source_id or ""), str(target_id or ""), str(label or "")])
    edges.sort()

    canonical = json.dumps(
        {"concepts": concepts, "edges": edges},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_graph_version(conn: lb.Connection | None = None) -> str:
    """Return an opaque version identifier for the current graph state.

    Derived from graph CONTENT. Not a semantic version; agents compare for
    equality to detect drift across queries.

    It was derived from the DB file mtime and node count, and LadybugDB touches
    the file on open, so every process start minted a new version for a graph
    nobody had changed. Caching per session hid it from every test, because a
    test is one process. What it cost, measured on the stores in this tree:
    287 recorded versions over 42 distinct graph contents — 245 phantom
    commits and 606 MB of duplicate snapshot copies, `SnapshotStore.capture`
    being idempotent per version and the version never repeating. Downstream,
    receipts could not survive a restart, `retrieve(graph_version=...)` was
    falsely STALE_GRAPH, and the B9 anti-rationalization check reported
    "unchanged code passed only after a graph change" when the graph had not
    moved.

    The path is deliberately not in the hash. Identical content at two paths is
    one version, which is the semantics a receipt needs: the adjudication is
    still sound because the governance text is the same. Path identity is a
    separate concern and `Surface._repin` handles it.
    """
    if conn is None:
        return "gv_" + hashlib.sha1(b"no-connection").hexdigest()[:12]
    try:
        digest = fingerprint_connection(conn)
    except Exception:
        # An unreadable graph has no content identity. Say so with a stable
        # sentinel rather than inventing a version that compares equal to
        # nothing — a caller comparing for drift must not read a fault as one.
        return "gv_unreadable"
    return f"gv_{digest[:12]}"


def describe_graph(
    conn: lb.Connection,
    structural_index: dict[str, StructuralFacts] | None = None,
    compass: Compass | None = None,
    graph_id: str = "",
) -> dict:
    """Produce the Agent Contract v1 §4 `describe_graph` response.

    Reads precomputed Compass and structural index. No LLM calls.
    """
    if structural_index is None:
        structural_index = get_structural_index(conn)
    if compass is None:
        compass = get_compass(conn, structural_index)

    node_count = 0
    try:
        rows = list(conn.execute("MATCH (c:Concept) RETURN count(c)"))
        node_count = rows[0][0] if rows else 0
    except Exception:
        pass

    edge_type_distribution: dict[str, int] = {}
    for rel in ["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]:
        try:
            rows = list(conn.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r)"))
            edge_type_distribution[rel] = rows[0][0] if rows else 0
        except Exception:
            edge_type_distribution[rel] = 0
    edge_count = sum(edge_type_distribution.values())

    profile = compass.graph_profile or {}
    structural_character = profile.get("structural_character") or profile.get(
        "character", ""
    )
    if not isinstance(structural_character, str):
        structural_character = str(structural_character)

    landmark_preview: list[dict] = []
    for lm in (compass.landmark_nodes or [])[:10]:
        landmark_preview.append(
            {
                "id": str(lm.get("id", "")),
                "label": str(lm.get("label", "")),
                "role": ",".join(lm.get("roles") or []) if isinstance(lm.get("roles"), list) else str(lm.get("role", "")),
                "anchor_preview": str(lm.get("anchor_preview", "") or lm.get("why_landmark", ""))[:240],
                "centrality_score": lm.get("centrality_score"),
                "total_degree": lm.get("total_degree"),
                "importance_kind": lm.get("importance_kind") or (
                    "betweenness" if float(lm.get("betweenness_centrality") or 0) > 0 else "degree"
                ),
            }
        )

    # Cheap ambient sizing scores for every Concept — normalised degree already
    # on the node; also emit from the in-memory index so Canvas need not wait
    # on a separate map_overview endpoint.
    max_deg = max((f.total_degree for f in structural_index.values()), default=1) or 1
    node_centrality: list[dict] = []
    for nid, facts in structural_index.items():
        node_centrality.append({
            "id": nid,
            "centrality_score": round(facts.total_degree / max_deg, 4),
            "total_degree": facts.total_degree,
        })

    return {
        "contract_version": "1",
        "graph_id": graph_id or os.environ.get("ACTIVE_SEED", "default"),
        "graph_version": get_graph_version(conn),
        "node_count": node_count,
        "edge_count": edge_count,
        "edge_type_distribution": edge_type_distribution,
        "structural_character": structural_character,
        "landmark_preview": landmark_preview,
        "node_centrality": node_centrality,
        "centrality_score_meaning": "normalised_degree",  # Concept.centrality_score; not betweenness
        "capabilities": ["query"],
    }
