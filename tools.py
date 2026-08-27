"""Tool library for the SST traversal engine.

Each tool is a Python function taking a LadybugDB connection + parameters,
returning structured results. Called by the backend execution node.
"""

from __future__ import annotations

from collections import defaultdict, deque
import re
from typing import TYPE_CHECKING, Any

from engine import get_embeddings_model
from models import NEARTO_MAX_BACKWARD, NEARTO_MAX_FORWARD, SST_EDGE_TYPES, StructuralFacts

if TYPE_CHECKING:
    import real_ladybug as lb

_REL_MAP = {
    "leadsto": "LEADSTO",
    "contains": "CONTAINS",
    "expresses": "EXPRESSES",
    "nearto": "NEARTO",
}


# ---------------------------------------------------------------------------
# Seed Finding
# ---------------------------------------------------------------------------

def vector_search(
    conn: "lb.Connection",
    query: str,
    k: int = 5,
    field: str = "anchor",
) -> list[dict]:
    """Embed query text and find top-k nodes by cosine similarity.

    Uses semantic_anchor for search if available, falls back to text_content.
    """
    try:
        embedder = get_embeddings_model()
        query_emb = embedder.embed_query(query)

        rows = list(conn.execute(
            "MATCH (c:Concept) "
            "RETURN c.id, c.label, c.centrality_score, "
            "       array_cosine_similarity(c.embedding, $q_emb) AS cos_sim",
            {"q_emb": query_emb},
        ))

        candidates = [
            {"id": r[0], "label": r[1], "centrality": float(r[2]), "cos_sim": float(r[3])}
            for r in rows
        ]
        candidates.sort(key=lambda c: c["cos_sim"], reverse=True)
        return candidates[:k]
    except Exception:
        # Graceful fallback when embeddings provider is unavailable: lexical retrieval.
        terms = [t for t in query.split() if len(t) > 2][:8]
        if not terms:
            terms = [query]
        return lexical_search(conn, terms, k=k, field=field)


def lexical_search(
    conn: "lb.Connection",
    terms: list[str],
    k: int = 5,
    field: str = "anchor",
) -> list[dict]:
    """Substring match over ``label`` / ``semantic_anchor`` / ``text_content``.

    v7: this tool is the *natural-language* lexical path — it does not
    interpret glob or regex metacharacters. For ID-shaped patterns
    (``char_*``, ``org_*``, explicit IDs, regex), dispatch
    ``id_pattern_lookup`` instead. In v6 the single ``lexical_search``
    mixed both roles, which silently failed for ID-pattern inputs.
    """
    results: dict[str, dict] = {}

    for term in terms:
        if not isinstance(term, str) or not term.strip():
            continue
        rows = list(conn.execute(
            "MATCH (c:Concept) "
            "WHERE c.semantic_anchor CONTAINS $term OR c.text_content CONTAINS $term OR c.label CONTAINS $term "
            "RETURN c.id, c.label, c.centrality_score",
            {"term": term},
        ))
        for r in rows:
            nid = r[0]
            if nid not in results:
                results[nid] = {"id": nid, "label": r[1], "centrality": float(r[2]), "match_count": 0}
            results[nid]["match_count"] += 1

    ranked = sorted(results.values(), key=lambda x: x["match_count"], reverse=True)
    return ranked[:k]


_GOVERNING_SEED_STOPWORDS = frozenset({
    "about", "after", "before", "could", "does", "govern", "governed",
    "governing", "governs", "have", "into", "must", "plain", "rule",
    "rules", "should", "that", "their", "them", "these", "this", "what",
    "when", "where", "which", "with", "would",
})
_LEGACY_RULE_LABEL = re.compile(
    r"(?:rule|policy|standard|requirement|constitution|handbook)(?:\b|\s*\()",
    re.IGNORECASE,
)


def governing_seed_candidates(
    conn: "lb.Connection",
    query: str,
    *,
    k: int = 4,
    min_term_matches: int = 2,
) -> list[dict]:
    """Return bounded query-relevant candidate authority for coverage/ruling.

    This is a retrieval prior, never a governance verdict. Declared claim-kind
    authority is preferred. On a legacy corpus with no declarations at all,
    rule/policy-shaped labels are eligible so old hand-authored graphs remain
    usable. At least two substantive query terms must match and ties are broken
    by node id, making irrelevant graph insertions unable to reorder the set.
    """
    raw_terms = re.findall(r"[a-z0-9]+", str(query or "").lower())
    terms: list[str] = []
    for term in raw_terms:
        if len(term) < 4 or term in _GOVERNING_SEED_STOPWORDS:
            continue
        singular = (
            term[:-1]
            if term.endswith("s")
            and len(term) > 4
            and not term.endswith(("ss", "us", "is"))
            else ""
        )
        adjectival_root = term[:-1] if term.endswith("ure") else ""
        for variant in (
            term,
            singular,
            adjectival_root,
        ):
            if variant and variant not in terms:
                terms.append(variant)
    if not terms:
        return []

    try:
        rows = list(conn.execute(
            "MATCH (c:Concept) RETURN c.id, c.label, c.semantic_anchor, "
            "c.text_content, c.claim_kind, c.claim_kind_source"
        ))
    except Exception:
        rows = [
            (*row, "", "")
            for row in conn.execute(
                "MATCH (c:Concept) RETURN c.id, c.label, "
                "c.semantic_anchor, c.text_content"
            )
        ]

    import normative

    records: list[dict] = []
    for row in rows:
        record = {
            "id": str(row[0] or ""),
            "label": str(row[1] or ""),
            "semantic_anchor": str(row[2] or ""),
            "text_content": str(row[3] or ""),
            "claim_kind": str(row[4] or ""),
            "claim_kind_source": str(row[5] or ""),
        }
        record["_claim"] = normative.classify(record)
        records.append(record)

    declared = [
        record for record in records
        if record["_claim"].is_governing and record["_claim"].grants_authority
    ]
    if declared:
        eligible = declared
        basis = "declared_claim_kind"
    else:
        eligible = [
            record for record in records
            if _LEGACY_RULE_LABEL.search(f"{record['id']} {record['label']}")
        ]
        basis = "legacy_rule_label"

    ranked: list[dict] = []
    for record in eligible:
        label_text = f"{record['id']} {record['label']}".lower()
        anchor_text = str(record["semantic_anchor"]).lower()
        content_text = str(record["text_content"]).lower()
        matched = [
            term for term in terms
            if term in label_text or term in anchor_text or term in content_text
        ]
        if len(matched) < min_term_matches:
            continue
        label_matches = sum(term in label_text for term in matched)
        anchor_matches = sum(term in anchor_text for term in matched)
        ranked.append({
            "id": record["id"],
            "label": record["label"],
            "centrality": 0.0,
            "match_count": len(matched),
            "matched_terms": sorted(matched),
            "governing_seed_basis": basis,
            "_score": len(matched) + (2 * label_matches) + anchor_matches,
        })

    ranked.sort(key=lambda item: (-int(item["_score"]), str(item["id"])))
    for item in ranked:
        item.pop("_score", None)
    return ranked[:max(0, int(k))]


def id_pattern_lookup(
    conn: "lb.Connection",
    pattern: str,
    k: int = 25,
) -> list[dict]:
    """Match node IDs against a glob / prefix / regex pattern.

    Accepts three forms:

    - Glob patterns with ``*`` or ``?`` wildcards — e.g. ``char_*`` returns
      every node whose ID starts with ``char_``.
    - Plain prefixes with no wildcards — e.g. ``gandalf`` matches IDs
      containing ``gandalf`` (case-insensitive).
    - Regex patterns wrapped in ``re:`` — e.g. ``re:^org_[a-z]+$``.

    The v6 ``lexical_search`` treated ``*`` as a literal character and
    searched against label/anchor/text rather than ID; v7 splits this into
    a dedicated ID-matching tool so planners asking for
    ``char_*`` in the corpus actually get the character nodes.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        return []

    raw = pattern.strip()
    if raw.startswith("re:"):
        import re as _re
        try:
            rx = _re.compile(raw[3:])
        except _re.error:
            return []
        matcher = lambda nid: bool(rx.search(nid))
    elif "*" in raw or "?" in raw:
        import fnmatch as _fnmatch
        # Case-insensitive glob by applying to both raw + lowered.
        lowered = raw.lower()
        matcher = lambda nid: _fnmatch.fnmatchcase(nid, raw) or _fnmatch.fnmatchcase(nid.lower(), lowered)
    else:
        needle = raw.lower()
        matcher = lambda nid: needle in nid.lower()

    results: list[dict] = []
    for row in conn.execute(
        "MATCH (c:Concept) RETURN c.id, c.label, c.centrality_score"
    ):
        nid = row[0]
        if matcher(nid):
            results.append({
                "id": nid,
                "label": row[1],
                "centrality": float(row[2]) if row[2] is not None else 0.0,
            })
        if len(results) >= max(k, 0):
            break
    return results


def graph_mentions(conn: "lb.Connection", token: str) -> bool:
    """Does ANY node in the graph carry this token in its id, label or anchor?

    Deliberately a substring test rather than `exact_node_lookup`: the question
    is "is this word known to the graph at all", and the SSDF corpus answers to
    `NIST SSDF 1.1` while a query says `NIST`.

    Exists because `gap_hinter` was inspecting the retrieved packet and then
    making a claim about the graph — telling operators to "Add a node for
    'NIST'" when `nist_ssdf_1_1` was sitting in the graph, unretrieved. That is
    the unretrieved-vs-absent conflation this whole engine exists to avoid, in
    its own gap output.
    """
    needle = (token or "").strip().lower()
    if not needle:
        return False
    rows = list(conn.execute(
        "MATCH (c:Concept) WHERE lower(c.id) CONTAINS $t "
        "OR lower(c.label) CONTAINS $t "
        "OR lower(c.semantic_anchor) CONTAINS $t "
        "RETURN c.id LIMIT 1",
        {"t": needle},
    ))
    return bool(rows)


def exact_node_lookup(
    conn: "lb.Connection",
    label_or_id: str,
) -> dict | None:
    """Resolve a graph-native node reference without semantic guessing.

    Exact ID/label remain first.  The additional forms are deterministic
    spelling projections commonly produced by agents reading the Compass:
    case-insensitive identity, CamelCase→snake_case IDs, and a label without
    its parenthetical role suffix.  Embedding fallback belongs to the caller
    and runs only after these identity-preserving forms fail.
    """
    value = str(label_or_id or "").strip()
    if not value:
        return None

    def _record(row) -> dict:
        return {
            "id": row[0],
            "label": row[1],
            "centrality": float(row[2] or 0.0),
        }

    # Try ID first
    rows = list(conn.execute(
        "MATCH (c:Concept {id: $val}) RETURN c.id, c.label, c.centrality_score",
        {"val": value},
    ))
    if rows:
        return _record(rows[0])

    # Try label
    rows = list(conn.execute(
        "MATCH (c:Concept {label: $val}) RETURN c.id, c.label, c.centrality_score",
        {"val": value},
    ))
    if rows:
        return _record(rows[0])

    # Casing is presentation, not identity.
    rows = list(conn.execute(
        "MATCH (c:Concept) "
        "WHERE lower(c.id) = $val OR lower(c.label) = $val "
        "RETURN c.id, c.label, c.centrality_score LIMIT 2",
        {"val": value.lower()},
    ))
    if len(rows) == 1:
        return _record(rows[0])

    # Agents naturally copy a CamelCase concept name while software graphs use
    # snake_case opaque IDs.
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    snake = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", snake).lower()
    if snake != value.lower():
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $val}) "
            "RETURN c.id, c.label, c.centrality_score",
            {"val": snake},
        ))
        if rows:
            return _record(rows[0])

    # Compass labels often carry a role suffix: ``OrderService (use-case
    # core)``.  A unique base label is still the same identity, not a semantic
    # approximation.  Refuse ambiguity rather than choosing a convenient hit.
    rows = list(conn.execute(
        "MATCH (c:Concept) WHERE lower(c.label) STARTS WITH $prefix "
        "RETURN c.id, c.label, c.centrality_score LIMIT 2",
        {"prefix": value.lower() + " ("},
    ))
    if len(rows) == 1:
        return _record(rows[0])

    # The inverse suffix: ``Define Security Requirements (PO.1)``. Agents
    # copy the identifier in the parentheses; that is still the same node.
    rows = list(conn.execute(
        "MATCH (c:Concept) WHERE lower(c.label) ENDS WITH $suffix "
        "RETURN c.id, c.label, c.centrality_score LIMIT 2",
        {"suffix": " (" + value.lower() + ")"},
    ))
    if len(rows) == 1:
        return _record(rows[0])

    return None


def get_nodes_by_ids(
    conn: "lb.Connection",
    ids: list[str],
) -> list[dict]:
    """Fetch basic info for a list of node IDs."""
    results = []
    for nid in ids:
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.id, c.label, c.centrality_score",
            {"id": nid},
        ))
        if rows:
            results.append({"id": rows[0][0], "label": rows[0][1], "centrality": float(rows[0][2])})
    return results


def query_structural_index(
    structural_index: dict[str, StructuralFacts],
    role: str,
    min_betweenness: float = 0.0,
) -> list[dict]:
    """Filter the in-memory structural index by role and optional betweenness threshold."""
    results = []
    for node_id, facts in structural_index.items():
        if role in facts.roles and facts.betweenness_centrality >= min_betweenness:
            results.append({
                "id": node_id,
                "roles": facts.roles,
                "betweenness_centrality": facts.betweenness_centrality,
            })
    results.sort(key=lambda x: x["betweenness_centrality"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------

def hop_expansion(
    conn: "lb.Connection",
    seeds: list[str],
    hop_limits: dict[str, dict[str, int]],
) -> list[dict]:
    """Expand from seed nodes by SST type and direction up to specified hop limits.

    hop_limits format:
    {
        "leadsto": {"forward": 2, "backward": 1},
        "contains": {"up": 1, "down": 1},
        "nearto": {"forward": 1}
    }

    NEARTO hard-capped at NEARTO_MAX_FORWARD forward, NEARTO_MAX_BACKWARD backward.

    Returns list of discovered nodes with origin metadata.
    """
    discovered: dict[str, dict] = {}  # node_id -> {id, label, origin, depth, via_type, via_direction}

    for sst_type_raw, directions in hop_limits.items():
        sst_type = str(sst_type_raw).lower()
        rel_name = _REL_MAP.get(sst_type)
        if not rel_name:
            continue

        for direction, max_hops_raw in directions.items():
            try:
                max_hops = int(max_hops_raw)
            except (TypeError, ValueError):
                continue
            # Enforce NEARTO hard cap
            if sst_type == "nearto":
                if direction in ("forward", "down"):
                    max_hops = min(max_hops, NEARTO_MAX_FORWARD)
                else:
                    max_hops = min(max_hops, NEARTO_MAX_BACKWARD)
                if max_hops <= 0:
                    continue

            # Determine Cypher direction
            # "forward"/"down" = outgoing, "backward"/"up" = incoming
            # NEARTO is undirected
            if sst_type == "nearto":
                arrow_pattern = f"-[:{rel_name}]-"  # undirected
            elif direction in ("forward", "down"):
                arrow_pattern = f"-[:{rel_name}]->"
            else:
                arrow_pattern = f"<-[:{rel_name}]-"

            # BFS expansion
            frontier = set(seeds)
            for hop in range(1, max_hops + 1):
                next_frontier: set[str] = set()
                for src_id in frontier:
                    cypher = (
                        f"MATCH (src:Concept {{id: $src_id}}){arrow_pattern}(n:Concept) "
                        "RETURN n.id, n.label"
                    )
                    try:
                        rows = list(conn.execute(cypher, {"src_id": src_id}))
                    except Exception:
                        continue

                    for r in rows:
                        nid, label = r[0], r[1]
                        if nid not in discovered and nid not in set(seeds):
                            discovered[nid] = {
                                "id": nid,
                                "label": label,
                                "via_type": sst_type,
                                "via_direction": direction,
                                "depth": hop,
                                # Track direct parent for depth-1 results so callers can
                                # reconstruct a minimal path_chain (parent_id is None for
                                # deeper hops where the path is non-trivial).
                                "parent_id": src_id if hop == 1 else None,
                            }
                            next_frontier.add(nid)
                frontier = next_frontier

    return list(discovered.values())


def find_paths(
    conn: "lb.Connection",
    source_set: list[str],
    target_set: list[str],
    max_hops: int = 4,
    edge_types: list[str] | None = None,
    direction: str = "outgoing",
    exclude_labels: tuple[str, ...] = (),
) -> list[dict]:
    """Find paths between source and target node sets.

    Returns list of path records with node chains and edge types.

    ``direction`` is ``outgoing`` by default, which follows edges the way they
    point. That is right for a causal walk and wrong for "how are these two
    connected": the commonest connection in a narrative is two people who took
    part in the same event, and both of those edges point *into* the event, so
    a forward-only walk finds nothing. Measured on the format's own demo
    graph, where Ilma and Torv share an event and a faction and the fixture
    named `connected-pair` still reported no path -- it passed only because
    the outcome was decided on packet size, and looking the two of them up
    filled the packet.

    ``both`` walks either way. NEARTO was already bidirectional here because
    it is declared symmetric; this generalises that to the caller's choice
    rather than to one edge type.

    ``exclude_labels`` drops edges by predicate label. It exists because a
    provenance predicate every node carries -- `attested_by` to the one
    `source` node -- makes every pair of nodes two hops apart. Measured: with
    direction opened up, every "how are they connected" answer on a real saga
    graph ran through the document itself, which is true and useless. SST type
    filtering cannot express this, because `attested_by` and `causes` are both
    LEADSTO.
    """
    if not source_set or not target_set:
        return []

    paths: list[dict] = []
    types = edge_types or SST_EDGE_TYPES

    for src_id in source_set:
        for tgt_id in target_set:
            if src_id == tgt_id:
                continue
            # BFS from src to tgt across all allowed edge types
            visited: set[str] = set()
            # (current_node, path_nodes, path_edge_types, path_edge_labels)
            queue: deque[tuple[str, list[str], list[str], list[str]]] = deque(
                [(src_id, [src_id], [], [])]
            )
            found = False

            while queue and not found:
                current, path_nodes, path_edges, path_edge_labels = queue.popleft()
                if len(path_nodes) > max_hops + 1:
                    continue
                if current in visited:
                    continue
                visited.add(current)

                for sst_type in types:
                    rel_name = _REL_MAP.get(sst_type)
                    if not rel_name:
                        continue

                    # Forward edges — also fetch edge label
                    cypher = (
                        f"MATCH (src:Concept {{id: $src_id}})-[r:{rel_name}]->(n:Concept) "
                        "RETURN n.id, r.label"
                    )
                    try:
                        rows = list(conn.execute(cypher, {"src_id": current}))
                    except Exception:
                        continue

                    # Undirected for NEARTO because it is symmetric by
                    # declaration, and for everything when the caller asked.
                    if sst_type == "nearto" or direction == "both":
                        reverse_cypher = (
                            f"MATCH (src:Concept {{id: $src_id}})<-[r:{rel_name}]-(n:Concept) "
                            "RETURN n.id, r.label"
                        )
                        try:
                            rows.extend(list(conn.execute(reverse_cypher, {"src_id": current})))
                        except Exception:
                            pass

                    for r in rows:
                        nid, edge_lbl = r[0], (r[1] or "")
                        if edge_lbl and edge_lbl in exclude_labels:
                            continue
                        if nid in visited:
                            continue
                        new_nodes = path_nodes + [nid]
                        new_edges = path_edges + [sst_type]
                        new_edge_labels = path_edge_labels + [edge_lbl]

                        if nid == tgt_id:
                            paths.append({
                                "source": src_id,
                                "target": tgt_id,
                                "node_chain": new_nodes,
                                "edge_chain": new_edges,
                                "edge_label_chain": new_edge_labels,
                                "length": len(new_edges),
                            })
                            found = True
                            break
                        if len(new_nodes) <= max_hops:
                            queue.append((nid, new_nodes, new_edges, new_edge_labels))
                    if found:
                        break

    return paths


def traverse_chain(
    conn: "lb.Connection",
    starts: list[str],
    direction: str,
    edge_type: str,
    max_depth: int = 5,
) -> list[dict]:
    """Walk a directed chain from start nodes along a single edge type.

    Returns ordered node chains.
    """
    rel_name = _REL_MAP.get(edge_type)
    if not rel_name:
        return []

    if edge_type == "nearto":
        arrow = f"-[:{rel_name}]-"
    elif direction == "forward":
        arrow = f"-[:{rel_name}]->"
    else:
        arrow = f"<-[:{rel_name}]-"

    chains: list[dict] = []

    for start_id in starts:
        chain_nodes = [start_id]
        current = start_id
        visited = {start_id}

        for _ in range(max_depth):
            cypher = (
                f"MATCH (src:Concept {{id: $src_id}}){arrow}(n:Concept) "
                "RETURN n.id, n.label"
            )
            try:
                rows = list(conn.execute(cypher, {"src_id": current}))
            except Exception:
                break

            if not rows:
                break

            # Take first unvisited neighbour
            found_next = False
            for r in rows:
                nid = r[0]
                if nid not in visited:
                    chain_nodes.append(nid)
                    visited.add(nid)
                    current = nid
                    found_next = True
                    break

            if not found_next:
                break

        chains.append({
            "start": start_id,
            "edge_type": edge_type,
            "direction": direction,
            "node_chain": chain_nodes,
            "length": len(chain_nodes) - 1,
        })

    return chains


def _unique_ids(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    seen: set[str] = set()
    out: list[str] = []
    for item in values or []:
        if isinstance(item, dict):
            nid = str(item.get("id") or "").strip()
        else:
            nid = str(item or "").strip()
        if nid and nid not in seen:
            seen.add(nid)
            out.append(nid)
    return out


def _coerce_property(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return value


def _endpoint_matches(
    node_id: str,
    extras: dict[str, Any],
    kinds: list[str] | None,
    kind_prefixes: list[str] | None,
    properties: dict[str, Any] | None,
) -> bool:
    if kinds or kind_prefixes:
        kind_ok = False
        node_kind = str(extras.get("kind") or "").strip().lower()
        allowed = {str(kind).strip().lower() for kind in (kinds or []) if str(kind).strip()}
        if node_kind and node_kind in allowed:
            kind_ok = True
        for prefix in kind_prefixes or []:
            text = str(prefix or "")
            if text and node_id.startswith(text) and len(node_id) > len(text):
                kind_ok = True
                break
        if not kind_ok:
            return False
    for key, expected in dict(properties or {}).items():
        actual = extras.get(key)
        want = _coerce_property(expected)
        have = _coerce_property(actual)
        if isinstance(want, bool):
            if bool(have) != want:
                return False
        elif str(have).strip().lower() != str(want).strip().lower():
            return False
    return True


def _neighbour_hits(
    conn: "lb.Connection",
    src_id: str,
    types: list[str],
    *,
    do_outgoing: bool,
    do_incoming: bool,
    edge_label_set: set[str] | None,
    rich: list[bool],
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []

    def _query(rel_name: str, outgoing: bool) -> list:
        if outgoing:
            labelled = (
                f"MATCH (src:Concept {{id: $src_id}})-[r:{rel_name}]->(n:Concept) "
            )
            plain = (
                f"MATCH (src:Concept {{id: $src_id}})-[:{rel_name}]->(n:Concept) "
            )
        else:
            labelled = (
                f"MATCH (src:Concept {{id: $src_id}})<-[r:{rel_name}]-(n:Concept) "
            )
            plain = (
                f"MATCH (src:Concept {{id: $src_id}})<-[:{rel_name}]-(n:Concept) "
            )
        params = {"src_id": src_id}
        if rich[0]:
            try:
                return list(conn.execute(
                    labelled
                    + "RETURN n.id, n.label, r.label, n.kind, n.claim_kind, n.is_metanode",
                    params,
                ))
            except Exception:
                rich[0] = False
        try:
            rows = list(conn.execute(
                labelled + "RETURN n.id, n.label, r.label",
                params,
            ))
            return [tuple(row) + ("", "", False) for row in rows]
        except RuntimeError:
            rows = []
            for row in conn.execute(
                plain + "RETURN n.id, n.label",
                params,
            ):
                rows.append((row[0], row[1], "", "", "", False))
            return rows

    for sst_type in types:
        rel_name = _REL_MAP.get(sst_type)
        if not rel_name:
            continue
        treat_as_undirected = sst_type == "nearto"
        specs: list[bool] = []
        if do_outgoing or treat_as_undirected:
            specs.append(True)
        if do_incoming or treat_as_undirected:
            specs.append(False)
        for outgoing in specs:
            for row in _query(rel_name, outgoing):
                nid = row[0]
                nlabel = row[1] or ""
                elabel = (row[2] if len(row) > 2 else "") or ""
                if edge_label_set and elabel.lower().strip() not in edge_label_set:
                    continue
                extras = {
                    "kind": (row[3] if len(row) > 3 else "") or "",
                    "claim_kind": (row[4] if len(row) > 4 else "") or "",
                    "is_metanode": bool(row[5]) if len(row) > 5 else False,
                }
                hits.append(
                    {
                        "id": nid,
                        "label": nlabel,
                        "edge_label": elabel,
                        "sst_type": sst_type,
                        "outgoing": outgoing,
                        "extras": extras,
                    }
                )
    hits.sort(key=lambda hit: (hit["id"], hit["sst_type"], hit["edge_label"]))
    return hits


def get_neighbourhood(
    conn: "lb.Connection",
    node_ids: list[str],
    depth: int = 1,
    edge_types: list[str] | None = None,
    direction: str = "both",
    max_nodes: int = 3000,
    structural_index: "dict | None" = None,
    edge_labels: list[str] | None = None,
    strategy: str = "bfs",
    kinds: list[str] | None = None,
    kind_prefixes: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> list[dict]:
    """Fetch all nodes within `depth` hops of the given nodes, and return
    the edges traversed alongside the node records.

    v7 fix: the v6 implementation returned nodes only, which produced empty
    edge_records for every fanout/relation_proof query that used this tool.
    The first returned node carries the full edge list via `_edge_records`
    (the transport pattern established by `get_nodes_by_edge_type`) so
    `build_evidence_packet` picks them up automatically. `direction`
    accepts `"outgoing"`, `"incoming"`, or `"both"` (default); `"both"`
    preserves the v6 symmetric behaviour.

    `edge_labels`: when set, only edges whose r.label is in this list are
    traversed and recorded. Use to distinguish e.g. "directed_by" from
    "starred_actors" within CONTAINS edges.

    `strategy`: ``bfs`` (default) keeps the nearest frontier under a node
    budget; ``dfs`` is branch-first and caps as it walks. Neighbor order is
    by node id. Endpoint ``kinds`` / ``properties`` skip non-matching nodes
    rather than using them as waypoints.
    """
    _edge_label_set: set[str] | None = (
        {lbl.lower().strip() for lbl in edge_labels if lbl and lbl.strip()}
        if edge_labels else None
    )
    types = [str(item).strip().lower() for item in (edge_types or SST_EDGE_TYPES) if str(item).strip()]
    walk = str(strategy or "bfs").strip().lower()
    if walk not in {"bfs", "dfs"}:
        walk = "bfs"
    # A walk that stops because it ran out of budget is not a walk that
    # finished. The BFS branch logged a warning to `sst.engine` -- a line
    # nobody reads over MCP -- and the DFS branch dropped nodes in silence.
    # A probe agent got a correct seven-node answer alongside
    # `truncated: true`, could not tell which of the two it meant, and said
    # so. Carried on the first record, the way edge records already are.
    budget_reached = [False]
    all_discovered: dict[str, dict] = {}
    ordered_ids = _unique_ids(node_ids)
    seed_set = set(ordered_ids)

    # Preload seed labels so the transport edge_records contain both endpoints.
    seed_labels: dict[str, str] = {}
    for sid in ordered_ids:
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.label", {"id": sid},
        ))
        if rows:
            seed_labels[sid] = rows[0][0] or ""

    edge_list: list[dict] = []
    seen_edge_keys: set[tuple] = set()

    def _record_edge(src_id: str, src_label: str, tgt_id: str, tgt_label: str,
                     sst_type: str, edge_label: str) -> None:
        key = (src_id, tgt_id, sst_type, edge_label)
        if key in seen_edge_keys:
            return
        seen_edge_keys.add(key)
        edge_list.append({
            "source_id": src_id,
            "source_label": src_label,
            "target_id": tgt_id,
            "target_label": tgt_label,
            "edge_type": sst_type,
            "edge_label": edge_label,
        })

    do_outgoing = direction in ("outgoing", "both")
    do_incoming = direction in ("incoming", "both")
    label_cache: dict[str, str] = dict(seed_labels)
    rich = [True]
    endpoint_kinds = [str(kind).strip() for kind in (kinds or []) if str(kind).strip()]
    prefixes = [str(prefix) for prefix in (kind_prefixes or []) if str(prefix)]
    props = dict(properties or {})

    def _consider(src_id: str, src_label: str, hit: dict[str, Any], hop: int) -> bool:
        nid = hit["id"]
        nlabel = hit["label"]
        extras = hit["extras"]
        if not _endpoint_matches(nid, extras, endpoint_kinds, prefixes, props):
            return False
        label_cache.setdefault(nid, nlabel)
        if hit["outgoing"]:
            _record_edge(src_id, src_label, nid, nlabel, hit["sst_type"], hit["edge_label"])
        else:
            _record_edge(nid, nlabel, src_id, src_label, hit["sst_type"], hit["edge_label"])
        if nid in all_discovered or nid in seed_set:
            return True
        all_discovered[nid] = {
            "id": nid, "label": nlabel,
            "depth": hop, "via_type": hit["sst_type"],
        }
        return True

    if walk == "dfs":
        stack: list[tuple[str, int, str | None, dict | None]] = [
            (sid, 0, None, None) for sid in reversed(ordered_ids)
        ]
        expanded: set[str] = set()
        while stack:
            src_id, src_depth, parent_id, via = stack.pop()
            if src_id in expanded:
                continue
            if src_id not in seed_set:
                if len(all_discovered) >= max_nodes:
                    budget_reached[0] = True
                    continue
                label = (via or {}).get("label") or label_cache.get(src_id, "")
                all_discovered[src_id] = {
                    "id": src_id,
                    "label": label,
                    "depth": src_depth,
                    "via_type": (via or {}).get("sst_type") or "",
                }
                label_cache.setdefault(src_id, label)
            expanded.add(src_id)
            if parent_id is not None and via is not None:
                parent_label = label_cache.get(parent_id, "")
                nlabel = via["label"] or label_cache.get(src_id, "")
                if via["outgoing"]:
                    _record_edge(
                        parent_id, parent_label, src_id, nlabel,
                        via["sst_type"], via["edge_label"],
                    )
                else:
                    _record_edge(
                        src_id, nlabel, parent_id, parent_label,
                        via["sst_type"], via["edge_label"],
                    )
            if src_depth >= depth:
                continue
            hits = _neighbour_hits(
                conn, src_id, types,
                do_outgoing=do_outgoing, do_incoming=do_incoming,
                edge_label_set=_edge_label_set, rich=rich,
            )
            at_cap = len(all_discovered) >= max_nodes
            for hit in reversed(hits):
                nid = hit["id"]
                if nid in expanded:
                    continue
                if not _endpoint_matches(
                    nid, hit["extras"], endpoint_kinds, prefixes, props
                ):
                    continue
                if at_cap and nid not in all_discovered and nid not in seed_set:
                    continue
                stack.append((nid, src_depth + 1, src_id, hit))
    else:
        frontier = list(ordered_ids)
        for hop in range(1, depth + 1):
            next_frontier: list[str] = []
            seen_next: set[str] = set()
            for src_id in frontier:
                src_label = label_cache.get(src_id, "")
                for hit in _neighbour_hits(
                    conn, src_id, types,
                    do_outgoing=do_outgoing, do_incoming=do_incoming,
                    edge_label_set=_edge_label_set, rich=rich,
                ):
                    nid = hit["id"]
                    was_new = nid not in all_discovered and nid not in seed_set
                    if not _consider(src_id, src_label, hit, hop):
                        continue
                    if was_new and nid not in seen_next:
                        seen_next.add(nid)
                        next_frontier.append(nid)
            frontier = next_frontier

    node_records = list(all_discovered.values())

    # Soft cap: truncate by structural importance when result exceeds max_nodes.
    # Keeps the most central nodes so Battalion receives meaningful evidence
    # rather than a memory-exhausting dump of weakly-connected periphery.
    if walk != "dfs" and len(node_records) > max_nodes:
        budget_reached[0] = True
        import logging as _logging
        _logging.getLogger("sst.engine").warning(
            "get_neighbourhood: %d nodes discovered, capping at %d. "
            "Consider using sequential hop_expansion steps instead of depth ≥ 2.",
            len(node_records), max_nodes,
        )
        if structural_index:
            node_records.sort(
                key=lambda n: getattr(structural_index.get(n["id"]), "betweenness", 0.0),
                reverse=True,
            )
        else:
            # Degree proxy: nodes seen from more edges are more central.
            degree: dict[str, int] = {}
            for e in edge_list:
                degree[e["source_id"]] = degree.get(e["source_id"], 0) + 1
                degree[e["target_id"]] = degree.get(e["target_id"], 0) + 1
            node_records.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)
        # Prune edge_list to only edges where both endpoints survive the cap.
        surviving_ids = {n["id"] for n in node_records[:max_nodes]} | seed_set
        edge_list = [e for e in edge_list
                     if e["source_id"] in surviving_ids and e["target_id"] in surviving_ids]
        node_records = node_records[:max_nodes]

    # Stash edge_records on the first returned node so build_evidence_packet
    # recovers them during packet assembly. If the seed set had no neighbours
    # but we still found edges (unlikely), prepend a synthetic carrier using
    # the first seed.
    if budget_reached[0] and node_records:
        node_records[0] = dict(node_records[0])
        node_records[0]["_node_budget_reached"] = max_nodes
    if edge_list:
        if node_records:
            node_records[0] = dict(node_records[0])
            node_records[0]["_edge_records"] = edge_list
        else:
            anchor_id = next(iter(node_ids), None)
            if anchor_id is not None:
                node_records.append({
                    "id": anchor_id,
                    "label": seed_labels.get(anchor_id, ""),
                    "depth": 0,
                    "via_type": "",
                    "_edge_records": edge_list,
                })

    return node_records


def _node_filter_extras(
    conn: "lb.Connection", node_id: str, rich: list[bool]
) -> dict[str, Any]:
    extras = {"kind": "", "claim_kind": "", "is_metanode": False, "label": ""}
    if rich[0]:
        try:
            rows = list(conn.execute(
                "MATCH (c:Concept {id: $id}) "
                "RETURN c.kind, c.claim_kind, c.is_metanode, c.label",
                {"id": node_id},
            ))
            if rows:
                extras["kind"] = rows[0][0] or ""
                extras["claim_kind"] = rows[0][1] or ""
                extras["is_metanode"] = bool(rows[0][2])
                extras["label"] = rows[0][3] or ""
            return extras
        except Exception:
            rich[0] = False
    try:
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.label",
            {"id": node_id},
        ))
        if rows:
            extras["label"] = rows[0][0] or ""
    except Exception:
        pass
    return extras


def filter_nodes(
    conn: "lb.Connection",
    node_ids: list[str],
    *,
    kinds: list[str] | None = None,
    kind_prefixes: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> list[dict]:
    """Keep nodes matching kind and property filters, in input order."""
    rich = [True]
    kept: list[dict] = []
    for nid in _unique_ids(node_ids):
        extras = _node_filter_extras(conn, nid, rich)
        if not _endpoint_matches(nid, extras, kinds, kind_prefixes, properties):
            continue
        kept.append(
            {
                "id": nid,
                "label": extras.get("label") or "",
                "kind": extras.get("kind") or "",
            }
        )
    return kept


def sort_nodes(
    conn: "lb.Connection",
    node_ids: list[str],
    *,
    by: str = "id",
    order: str = "asc",
) -> list[dict]:
    """Deterministic sort of a node id list."""
    key_name = str(by or "id").strip().lower()
    descending = str(order or "asc").strip().lower() == "desc"
    rich = [True]
    records: list[dict] = []
    for nid in _unique_ids(node_ids):
        extras = _node_filter_extras(conn, nid, rich)
        records.append(
            {
                "id": nid,
                "label": extras.get("label") or "",
                "kind": extras.get("kind") or "",
            }
        )
    if key_name == "label":
        records.sort(key=lambda row: (str(row.get("label") or ""), row["id"]))
    else:
        records.sort(key=lambda row: row["id"])
    if descending:
        records.reverse()
    return records


def limit_nodes(node_ids: list[str], limit: int) -> list[dict]:
    """Keep the first ``limit`` ids, preserving order."""
    cap = max(0, int(limit))
    return [{"id": nid} for nid in _unique_ids(node_ids)[:cap]]


def set_algebra(
    *,
    op: str,
    left: list[str],
    right: list[str] | None = None,
) -> list[dict]:
    """Union, difference or intersection over already-resolved id lists."""
    left_ids = _unique_ids(left)
    right_ids = _unique_ids(right)
    right_set = set(right_ids)
    name = str(op or "").strip().lower()
    if name == "union":
        ids = _unique_ids(left_ids + right_ids)
    elif name == "difference":
        ids = [nid for nid in left_ids if nid not in right_set]
    elif name == "intersection":
        ids = [nid for nid in left_ids if nid in right_set]
    else:
        ids = left_ids
    return [{"id": nid} for nid in ids]


def select_landmarks(
    conn: "lb.Connection",
    structural_index: dict[str, StructuralFacts],
    *,
    pinned: list[str] | None = None,
    roles: list[str] | None = None,
    include_pinned: bool = True,
    limit: int = 8,
) -> list[dict]:
    """Format-pinned nodes plus optional structural-role landmarks."""
    ordered: list[dict] = []
    seen: set[str] = set()

    def _add(node_id: str, extra: dict | None = None) -> None:
        nid = str(node_id or "").strip()
        if not nid or nid in seen:
            return
        seen.add(nid)
        row = {"id": nid, "label": ""}
        if extra:
            row.update({k: v for k, v in extra.items() if k != "id"})
        ordered.append(row)

    if include_pinned:
        for pid in _unique_ids(pinned):
            record = exact_node_lookup(conn, pid)
            if record:
                _add(record["id"], record)

    wanted = [str(role).strip().lower() for role in (roles or []) if str(role).strip()]
    if wanted:
        for role in wanted:
            for row in query_structural_index(structural_index, role):
                _add(row["id"], row)
    elif structural_index:
        ranked = sorted(
            structural_index.items(),
            key=lambda item: (
                -float(item[1].betweenness_centrality),
                item[0],
            ),
        )
        for node_id, facts in ranked:
            _add(node_id, {"roles": list(facts.roles)})

    cap = max(1, int(limit or 8))
    chosen = ordered[:cap]
    rich = [True]
    for row in chosen:
        if row.get("label"):
            continue
        extras = _node_filter_extras(conn, row["id"], rich)
        row["label"] = extras.get("label") or ""
        if extras.get("kind"):
            row["kind"] = extras["kind"]
    return chosen


def walk_sequence(
    conn: "lb.Connection",
    starts: list[str],
    hops: list[dict[str, Any]],
    *,
    kinds: list[str] | None = None,
    kind_prefixes: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    max_nodes: int = 300,
) -> list[dict]:
    """Walk an ordered predicate/SST pattern. Simple paths only."""
    seeds = _unique_ids(starts)
    if not seeds or not hops:
        return []
    rich = [True]
    complete: list[list[dict[str, Any]]] = []

    for start in seeds:
        paths: list[list[dict[str, Any]]] = [[{"id": start, "label": "", "edge": None}]]
        for hop in hops:
            edge_types = [
                str(item).strip().lower()
                for item in (hop.get("edge_types") or [])
                if str(item).strip()
            ] or list(SST_EDGE_TYPES)
            labels = hop.get("edge_labels") or None
            edge_label_set = (
                {str(label).lower().strip() for label in labels if str(label).strip()}
                if labels
                else None
            )
            direction = str(hop.get("direction") or "outgoing").strip().lower()
            do_outgoing = direction in ("outgoing", "both")
            do_incoming = direction in ("incoming", "both")
            next_paths: list[list[dict[str, Any]]] = []
            for path in paths:
                src_id = path[-1]["id"]
                on_path = {step["id"] for step in path}
                for hit in _neighbour_hits(
                    conn, src_id, edge_types,
                    do_outgoing=do_outgoing, do_incoming=do_incoming,
                    edge_label_set=edge_label_set, rich=rich,
                ):
                    nid = hit["id"]
                    if nid in on_path:
                        continue
                    # The kind filter used to be applied here, at every hop.
                    # `character -> event -> place` with kinds=[place] then
                    # died on the first hop -- an event is not a place -- and
                    # the op returned nothing, which this format reads as "no
                    # such places". Measured against the same walk written as
                    # two `expand` steps, which returned three. The predicates
                    # already constrain each hop through the contract's
                    # source_kinds/target_kinds; `kinds` narrows the *result*,
                    # as it does on `expand`, and is applied below.
                    step = {
                        "id": nid,
                        "label": hit["label"],
                        # Carried so the result-level filter can read node
                        # properties; without it a `properties` filter would
                        # match nothing and look like an empty walk.
                        "extras": hit["extras"],
                        "edge": {
                            "sst_type": hit["sst_type"],
                            "edge_label": hit["edge_label"],
                            "outgoing": hit["outgoing"],
                        },
                    }
                    next_paths.append(path + [step])
            # Every other walk here keeps a visited set, so its cost is
            # bounded by the graph. This one keeps whole simple paths, so the
            # frontier grows multiplicatively with each hop -- which was
            # harmless only while no program could ask for more than six hops.
            # Bounding the live path set by the same node budget the caller
            # already set keeps that true at any hop count, and keeps it
            # deterministic: neighbour order is deterministic, so the paths
            # kept are the same ones on every run.
            if len(next_paths) > max_nodes:
                next_paths = next_paths[:max_nodes]
            paths = next_paths
            if not paths:
                break
        if paths:
            complete.extend(paths)

    records: list[dict] = []
    seen: set[str] = set()
    path_carrier: list[dict] = []
    for path in complete:
        node_chain = [step["id"] for step in path]
        edge_chain = []
        edge_label_chain = []
        for step in path[1:]:
            edge = step.get("edge") or {}
            edge_chain.append(edge.get("sst_type") or "")
            edge_label_chain.append(edge.get("edge_label") or "")
        for nid, step in zip(node_chain[1:], path[1:]):
            if nid in seen or len(seen) >= max_nodes:
                continue
            if not _endpoint_matches(
                nid, step.get("extras") or {}, kinds, kind_prefixes, properties
            ):
                continue
            seen.add(nid)
            records.append(
                {
                    "id": nid,
                    "label": next(
                        (step["label"] for step in path if step["id"] == nid),
                        "",
                    ),
                    "path_chain": node_chain,
                    "edge_chain": edge_chain,
                    "edge_label_chain": edge_label_chain,
                }
            )
        path_carrier.append(
            {
                "node_chain": node_chain,
                "edge_chain": edge_chain,
                "edge_label_chain": edge_label_chain,
            }
        )
    if records and path_carrier:
        records[0] = dict(records[0])
        records[0]["_path_records"] = path_carrier
    return records


def get_neighbours(
    conn: "lb.Connection",
    node_id: str,
    edge_type: str,
    direction: str = "forward",
) -> list[dict]:
    """Get immediate neighbours of a node along a specific edge type and direction."""
    rel_name = _REL_MAP.get(edge_type)
    if not rel_name:
        return []

    if edge_type == "nearto":
        cypher_lbl = (
            f"MATCH (src:Concept {{id: $src_id}})-[r:{rel_name}]-(n:Concept) "
            "RETURN n.id, n.label, r.label"
        )
        cypher_plain = (
            f"MATCH (src:Concept {{id: $src_id}})-[:{rel_name}]-(n:Concept) "
            "RETURN n.id, n.label"
        )
    elif direction == "forward":
        cypher_lbl = (
            f"MATCH (src:Concept {{id: $src_id}})-[r:{rel_name}]->(n:Concept) "
            "RETURN n.id, n.label, r.label"
        )
        cypher_plain = (
            f"MATCH (src:Concept {{id: $src_id}})-[:{rel_name}]->(n:Concept) "
            "RETURN n.id, n.label"
        )
    else:
        cypher_lbl = (
            f"MATCH (src:Concept {{id: $src_id}})<-[r:{rel_name}]-(n:Concept) "
            "RETURN n.id, n.label, r.label"
        )
        cypher_plain = (
            f"MATCH (src:Concept {{id: $src_id}})<-[:{rel_name}]-(n:Concept) "
            "RETURN n.id, n.label"
        )

    results: list[dict] = []
    try:
        for row in conn.execute(cypher_lbl, {"src_id": node_id}):
            el = (row[2] or "") if len(row) > 2 else ""
            results.append({"id": row[0], "label": row[1], "edge_label": el})
    except RuntimeError:
        # LadybugDB: some DBs throw "Cannot find property label for r" on rel.label
        for row in conn.execute(cypher_plain, {"src_id": node_id}):
            results.append({"id": row[0], "label": row[1], "edge_label": ""})
    return results


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

def get_node_anchors(
    conn: "lb.Connection",
    ids: list[str],
) -> dict[str, str]:
    """Fetch semantic anchors for nodes. Falls back to text_content[:200] if anchor is empty."""
    result: dict[str, str] = {}
    for nid in ids:
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.semantic_anchor, c.text_content",
            {"id": nid},
        ))
        if rows:
            anchor, text = rows[0][0], rows[0][1]
            if anchor and anchor.strip():
                result[nid] = anchor
            else:
                result[nid] = text[:200] + ("..." if len(text) > 200 else "")
    return result


def get_node_payloads(
    conn: "lb.Connection",
    ids: list[str],
) -> dict[str, dict]:
    """Fetch full text_content for nodes — Phase 3 synthesis only."""
    result: dict[str, dict] = {}
    # `claim_kind` post-dates every graph on disk, so a corpus that never took
    # the migration must still page in. One probe, not one per node.
    query = ("MATCH (c:Concept {id: $id}) RETURN c.label, c.text_content, "
             "c.token_count, c.claim_kind, c.claim_kind_source")
    has_claim_kind = True
    for nid in ids:
        if has_claim_kind:
            try:
                rows = list(conn.execute(query, {"id": nid}))
            except Exception:  # noqa: BLE001 — pre-migration graph
                has_claim_kind = False
                rows = []
        if not has_claim_kind:
            rows = list(conn.execute(
                "MATCH (c:Concept {id: $id}) RETURN c.label, c.text_content, "
                "c.token_count",
                {"id": nid},
            ))
        if rows:
            payload = {
                "id": nid,
                "label": rows[0][0],
                "text_content": rows[0][1],
                "token_count": rows[0][2],
            }
            if has_claim_kind:
                payload["claim_kind"] = rows[0][3] or ""
                payload["claim_kind_source"] = rows[0][4] or ""
            result[nid] = payload
    return result


def get_node_structural_facts(
    structural_index: dict[str, StructuralFacts],
    ids: list[str],
) -> dict[str, dict]:
    """Get structural facts for a list of node IDs."""
    result: dict[str, dict] = {}
    for nid in ids:
        facts = structural_index.get(nid)
        if facts:
            result[nid] = facts.to_dict()
    return result


# ---------------------------------------------------------------------------
# Structural enumeration (for set-difference and edge-type queries)
# ---------------------------------------------------------------------------

def get_all_node_ids(conn: "lb.Connection") -> list[dict]:
    """Return all node IDs in the graph.

    Designed for set-difference queries: retrieve everything, then the backend
    collect expression subtracts the unwanted subset. Returns node dicts with
    id and label so downstream steps can use result variable references.
    """
    results = []
    for row in conn.execute("MATCH (c:Concept) RETURN c.id, c.label"):
        results.append({"id": row[0], "label": row[1]})
    return results


def get_nodes_by_edge_type(
    conn: "lb.Connection",
    edge_type: str,
) -> dict:
    """Return canonical edge participation for a given SST edge type.

    v6: returns a structured object preserving source/target/edge_label rather
    than flattening to a bag of nodes. Shape:

        {
          "node_records": [{"id", "label", "via_edge_type"}],
          "edge_records": [{"source_id", "source_label",
                             "target_id", "target_label",
                             "edge_type", "edge_label"}]
        }

    The node_records list dedupes participants; edge_records preserves every
    distinct (source, target, label) triple so downstream tiers cannot lose
    the proof structure. For edge-type enumeration queries this is the primary
    evidence.
    """
    sst = str(edge_type).lower()
    rel_name = _REL_MAP.get(sst)
    if not rel_name:
        return {"node_records": [], "edge_records": []}

    # Try to fetch edge label; fall back to label-less query if property missing.
    edges: list[dict] = []
    try:
        rows = list(conn.execute(
            f"MATCH (a:Concept)-[e:{rel_name}]->(b:Concept) "
            f"RETURN a.id, a.label, b.id, b.label, e.label"
        ))
    except RuntimeError:
        rows = []
        for row in conn.execute(
            f"MATCH (a:Concept)-[:{rel_name}]->(b:Concept) "
            f"RETURN a.id, a.label, b.id, b.label"
        ):
            rows.append((row[0], row[1], row[2], row[3], ""))

    for row in rows:
        src_id, src_label, tgt_id, tgt_label = row[0], row[1], row[2], row[3]
        e_label = (row[4] if len(row) > 4 else "") or ""
        edges.append({
            "source_id": src_id,
            "source_label": src_label,
            "target_id": tgt_id,
            "target_label": tgt_label,
            "edge_type": sst,
            "edge_label": e_label,
        })

    seen: set[str] = set()
    node_records: list[dict] = []
    for e in edges:
        for nid, label in (
            (e["source_id"], e["source_label"]),
            (e["target_id"], e["target_label"]),
        ):
            if nid not in seen:
                seen.add(nid)
                node_records.append({
                    "id": nid,
                    "label": label,
                    "via_edge_type": sst,
                })

    return {"node_records": node_records, "edge_records": edges}


# ---------------------------------------------------------------------------
# v7 additions — structural profile + anchor previews
# ---------------------------------------------------------------------------

_STRUCTURAL_ROLE_ALIASES = {
    "centrality": "betweenness",
    "central": "betweenness",
}

_STRUCTURAL_ROLES = {
    "betweenness",
    "bridge",
    "origin",
    "terminal",
    "nexus",
    "associative_hub",
    "causal_origin",
    "causal_terminal",
    "causal_nexus",
    "inter_region_bridge",
    "orphan",
    "weakly_connected",
}


def get_structural_profile(
    structural_index: dict[str, StructuralFacts],
    role: str,
    top_n: int = 10,
    conn: "lb.Connection | None" = None,
) -> list[dict]:
    """Return precomputed structural features for a role, sorted by score.

    v7 §9: a first-class tool the Planner can dispatch when it declares
    ``structural_intent`` — e.g. "top nodes by connectivity". The v6
    Planner had no tool matching that intent; it fell back to
    ``get_all_node_ids`` or ``get_neighbourhood`` and produced empty or
    irrelevant packets.

    Roles:
      - ``betweenness`` / ``centrality`` — sort by betweenness_centrality
      - ``bridge`` / ``inter_region_bridge`` — nodes tagged as cross-region
        bridges, ranked by betweenness
      - ``origin`` / ``causal_origin`` — causal sources (no incoming
        LEADSTO), ranked by out-degree
      - ``terminal`` / ``causal_terminal`` — causal sinks, ranked by
        in-degree
      - ``nexus`` / ``causal_nexus`` — nodes with both in and out causal
        edges, ranked by total degree
      - ``associative_hub`` — NEARTO-heavy nodes, ranked by total degree
      - ``orphan`` / ``weakly_connected`` — isolates and fringe, ranked
        by betweenness
    """
    requested = str(role or "").strip().lower()
    canonical = _STRUCTURAL_ROLE_ALIASES.get(requested, requested)
    if canonical not in _STRUCTURAL_ROLES:
        return []

    entries: list[tuple[str, StructuralFacts]] = list(
        (nid, facts) for nid, facts in structural_index.items()
    )

    def _matches(facts: StructuralFacts) -> bool:
        if canonical == "betweenness":
            return True
        if canonical in ("bridge", "inter_region_bridge"):
            return "inter_region_bridge" in facts.roles or "bridge" in facts.roles
        if canonical in ("origin", "causal_origin"):
            return "causal_origin" in facts.roles
        if canonical in ("terminal", "causal_terminal"):
            return "causal_terminal" in facts.roles
        if canonical in ("nexus", "causal_nexus"):
            return "causal_nexus" in facts.roles
        if canonical == "associative_hub":
            return "associative_hub" in facts.roles
        if canonical in ("orphan", "weakly_connected"):
            return "orphan" in facts.roles or "weakly_connected" in facts.roles
        return False

    def _score(facts: StructuralFacts) -> float:
        if canonical in ("origin", "causal_origin"):
            return float(sum(facts.out_degree.values()))
        if canonical in ("terminal", "causal_terminal"):
            return float(sum(facts.in_degree.values()))
        if canonical in ("nexus", "causal_nexus", "associative_hub"):
            return float(facts.total_degree)
        return float(facts.betweenness_centrality)

    matched = [(nid, facts) for nid, facts in entries if _matches(facts)]
    matched.sort(key=lambda pair: _score(pair[1]), reverse=True)

    capped = matched[: max(int(top_n or 10), 0)]

    label_map: dict[str, str] = {}
    if conn is not None and capped:
        for nid, _ in capped:
            try:
                rows = list(conn.execute(
                    "MATCH (c:Concept {id: $id}) RETURN c.label",
                    {"id": nid},
                ))
                if rows:
                    label_map[nid] = rows[0][0] or ""
            except Exception:
                continue

    results: list[dict] = []
    for nid, facts in capped:
        results.append({
            "id": nid,
            "label": label_map.get(nid, ""),
            "role": canonical,
            "score": _score(facts),
            "betweenness_centrality": float(facts.betweenness_centrality),
            "roles": list(facts.roles),
            "total_degree": int(facts.total_degree),
        })
    return results


def get_anchor_previews(
    conn: "lb.Connection",
    ids: list[str],
    preview_tokens: int = 200,
) -> list[dict]:
    """Batch-fetch ``semantic_anchor`` plus a ``preview_tokens``-word slice
    of ``text_content`` for a list of node IDs.

    v7 §9: populates Compass Layer 4 (Semantic Previews) on demand for
    Company / Battalion without dragging full payloads through the whole
    pipeline. Returns a list of dicts preserving input order for IDs that
    were found; missing IDs are silently skipped (callers can diff).
    """
    if not isinstance(ids, list):
        return []
    results: list[dict] = []
    word_cap = max(int(preview_tokens or 200), 0)
    for nid in ids:
        if not isinstance(nid, str) or not nid:
            continue
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.id, c.label, c.semantic_anchor, c.text_content",
            {"id": nid},
        ))
        if not rows:
            continue
        row = rows[0]
        anchor = row[2] or ""
        text = row[3] or ""
        # Use whitespace tokenisation as a cheap stand-in for "tokens".
        # This keeps the tool dependency-free; downstream Battalion can
        # re-tokenise if it needs a model-accurate window.
        if word_cap > 0 and text:
            words = text.split()
            if len(words) > word_cap:
                preview = " ".join(words[:word_cap]) + "..."
            else:
                preview = text
        else:
            preview = ""
        results.append({
            "id": row[0],
            "label": row[1] or "",
            "semantic_anchor": anchor,
            "text_preview": preview,
        })
    return results
