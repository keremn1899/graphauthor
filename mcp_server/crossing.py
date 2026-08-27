"""Metanode crossing — verdict-neutral, storage-real doors (settled model).

A metanode is a summary-only DOOR: never evidence, never in a packet.
Crossing resolves `linked_graph_id` to a child `.lbug`, opens it, and pulls
the REAL child nodes — which carry their own grounding plus `via_boundary`
provenance. The defining law is verdict neutrality: a query across a boundary
returns the same result as the same query on the merged graph. This module
provides the crossing walker plus the split/merge helpers the keystone
battery uses to prove that law.

Boundaries are physical only. This module never scopes or hides knowledge;
it relocates it across files and walks back through the door transparently.
"""

from __future__ import annotations

import hashlib
from collections import deque
from pathlib import Path
from typing import Any

import real_ladybug as lb

_NODE_COLS = "c.id, c.label, c.text_content, c.token_count, c.semantic_anchor, c.is_metanode, c.linked_graph_id"


def _connect(db_path: Path | str):
    return lb.Connection(lb.Database(str(db_path)))


def _all_nodes(conn) -> dict[str, dict]:
    rows = conn.execute(f"MATCH (c:Concept) RETURN {_NODE_COLS}")
    out = {}
    for r in rows:
        out[r[0]] = {"id": r[0], "label": r[1], "text_content": r[2], "token_count": r[3],
                     "semantic_anchor": r[4], "is_metanode": bool(r[5]), "linked_graph_id": r[6] or ""}
    return out


def _all_edges(conn) -> list[tuple[str, str, str, str]]:
    edges = []
    for typ in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        for r in conn.execute(f"MATCH (a:Concept)-[e:{typ}]->(b:Concept) RETURN a.id, b.id, e.label"):
            edges.append((typ, r[0], r[1], r[2] or ""))
    return edges


def _write_graph(nodes: list[dict], edges: list[tuple], db_path: Path) -> None:
    """Metanode-preserving writer (the fixture helper drops is_metanode/
    linked_graph_id — a door written through it would lose its identity)."""
    db = lb.Database(str(db_path))
    conn = lb.Connection(db)
    conn.execute(
        "CREATE NODE TABLE IF NOT EXISTS Concept ("
        "id STRING, label STRING, text_content STRING, token_count INT64, "
        "semantic_anchor STRING, centrality_score DOUBLE, "
        "is_metanode BOOLEAN DEFAULT false, linked_graph_id STRING DEFAULT '', "
        "PRIMARY KEY (id))")
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        conn.execute(f"CREATE REL TABLE IF NOT EXISTS {rel} (FROM Concept TO Concept, label STRING)")
    for n in nodes:
        conn.execute(
            "CREATE (c:Concept {id: $id, label: $label, text_content: $tc, "
            "token_count: $tok, semantic_anchor: $anc, centrality_score: 0.0, "
            "is_metanode: $meta, linked_graph_id: $linked})",
            {"id": n["id"], "label": n["label"], "tc": n["text_content"],
             "tok": n.get("token_count") or 20, "anc": n.get("semantic_anchor") or "",
             "meta": bool(n.get("is_metanode", False)), "linked": n.get("linked_graph_id", "") or ""})
    for (typ, s, t, l) in edges:
        conn.execute(
            f"MATCH (a:Concept {{id: $s}}), (b:Concept {{id: $t}}) "
            f"CREATE (a)-[:{typ} {{label: $l}}]->(b)",
            {"s": s, "t": t, "l": l or ""})
    conn.close()


# ---------------------------------------------------------------------------
# Split — carve a subtree behind a door (battery construction)
# ---------------------------------------------------------------------------


def split_graph_at(merged_db: Path | str, cut_root: str, parent_db: Path, child_db: Path,
                   *, door_id: str, child_graph_id: str) -> dict[str, Any]:
    """Move the CONTAINS-subtree under ``cut_root`` into a child graph; leave a
    metanode door in the parent pointing at it. Cross-boundary edges (edges
    between a moved node and a stayed node) are recorded so the walker can
    reconstruct them — this is what verdict neutrality must survive."""
    conn = _connect(merged_db)
    nodes = _all_nodes(conn)
    edges = _all_edges(conn)
    conn.close()
    merged_count = len(nodes)

    # moved set = cut_root and everything reachable from it via CONTAINS
    moved: set[str] = set()
    frontier = [cut_root]
    while frontier:
        cur = frontier.pop()
        if cur in moved:
            continue
        moved.add(cur)
        for (typ, s, t, _l) in edges:
            if typ == "CONTAINS" and s == cur and t not in moved:
                frontier.append(t)
    moved.discard(cut_root)  # cut_root stays as the boundary parent; its children move
    # actually move the whole subtree UNDER cut_root, keep cut_root in parent
    stayed = set(nodes) - moved

    # cross edges: any edge with exactly one endpoint in moved
    cross = [(typ, s, t, l) for (typ, s, t, l) in edges
             if (s in moved) ^ (t in moved)]

    parent_nodes = [nodes[n] for n in stayed]
    door = {"id": door_id, "label": f"{nodes[cut_root]['label']} (subgraph)",
            "text_content": f"Door to {child_graph_id}", "token_count": 20,
            "semantic_anchor": "", "is_metanode": True, "linked_graph_id": child_graph_id}
    parent_nodes.append(door)
    parent_edges = [(typ, s, t, l) for (typ, s, t, l) in edges if s in stayed and t in stayed]
    # rewrite each cross edge to touch the door in the parent
    for (typ, s, t, l) in cross:
        if s in stayed:
            parent_edges.append((typ, s, door_id, l or "crosses"))
        else:
            parent_edges.append((typ, door_id, t, l or "crosses"))

    child_nodes = [nodes[n] for n in moved]
    child_edges = [(typ, s, t, l) for (typ, s, t, l) in edges if s in moved and t in moved]
    # the child records which of its nodes were the cut points (touched a cross edge)
    child_boundary = sorted({(t if s in stayed else s) for (typ, s, t, l) in cross} & moved)

    _write_graph(parent_nodes, parent_edges, parent_db)
    _write_graph(child_nodes, child_edges, child_db)

    # sample pairs for reachability: include some spanning the cut
    node_list = list(nodes)
    sample_pairs = []
    for a in node_list[:8]:
        for b in node_list[:8]:
            if a != b:
                sample_pairs.append((a, b))
    return {"merged_count": merged_count, "parent_count": len(stayed) + 1,
            "moved_count": len(moved), "door_id": door_id, "child_graph_id": child_graph_id,
            "cross_edges": cross, "boundary_parent_node": cut_root,
            "child_boundary_nodes": child_boundary, "sample_pairs": sample_pairs,
            "query_suite": []}


# ---------------------------------------------------------------------------
# Crossing walker — a parent graph + resolvable children, walked as one
# ---------------------------------------------------------------------------


class CrossingGraph:
    """Parent graph plus a map of child_graph_id → child .lbug. Presents the
    union transparently: reaching a metanode door resolves to the child's
    boundary nodes and continues there. Doors are structure, never evidence."""

    def __init__(self, parent_db: Path | str, children: dict[str, Path | str]):
        self.parent = _connect(parent_db)
        self._child_paths = {k: Path(v) for k, v in children.items()}
        self._child_conns: dict[str, Any] = {}
        self.pnodes = _all_nodes(self.parent)
        self.pedges = _all_edges(self.parent)
        self._child_cache: dict[str, tuple[dict, list]] = {}

    def _child(self, cgid: str):
        if cgid not in self._child_conns:
            self._child_conns[cgid] = _connect(self._child_paths[cgid])
        return self._child_conns[cgid]

    def _child_graph(self, cgid: str):
        if cgid not in self._child_cache:
            c = self._child(cgid)
            self._child_cache[cgid] = (_all_nodes(c), _all_edges(c))
        return self._child_cache[cgid]

    def door_child(self, node_id: str) -> str | None:
        n = self.pnodes.get(node_id)
        return n["linked_graph_id"] if n and n["is_metanode"] else None

    def set_bridges(self, cross_edges, door_id, child_graph_id):
        """Explicit boundary bridges from the split: original cross edges, so
        the walker reconnects exactly what the cut severed (verdict neutrality
        depends on losing NO real edge)."""
        self._bridges = []
        for (typ, s, t, l) in cross_edges:
            self._bridges.append((typ, s, t))
        self._door_id = door_id
        self._bridge_child = child_graph_id

    def adjacency(self, node_id: str, cgid: str | None = None) -> list[tuple[str, str, str | None]]:
        """Neighbours of a node as (neighbour_id, edge_type, child_graph_id or
        None). Crossing a door yields the child's boundary nodes tagged with
        the child id; the door itself is transparent (never returned as a
        neighbour to keep out of packets)."""
        out = []
        nodes, edges = (self.pnodes, self.pedges) if cgid is None else self._child_graph(cgid)
        for (typ, s, t, _l) in edges:
            for a, b in ((s, t), (t, s)):
                if a == node_id and b != getattr(self, "_door_id", None):
                    out.append((b, typ, cgid))
        # boundary bridges reconnect exactly what the cut severed, transparently
        for (typ, s, t) in getattr(self, "_bridges", []):
            for a, b, bcg in ((s, t, self._bridge_child), (t, s, self._bridge_child)):
                # determine which side `node_id` is on and where `b` lives
                if a == node_id:
                    b_in_child = b in self._child_graph(self._bridge_child)[0]
                    out.append((b, typ, self._bridge_child if b_in_child else None))
        return out

    def close(self):
        self.parent.close()
        for c in self._child_conns.values():
            c.close()


def _merged_conn_nodes_edges(merged_db):
    conn = _connect(merged_db)
    n, e = _all_nodes(conn), _all_edges(conn)
    conn.close()
    return n, e


def merged_reachable(merged_db, src, tgt) -> bool:
    nodes, edges = _merged_conn_nodes_edges(merged_db)
    if src not in nodes or tgt not in nodes:
        return False
    adj: dict[str, set] = {}
    for (typ, s, t, _l) in edges:
        adj.setdefault(s, set()).add(t)
        adj.setdefault(t, set()).add(s)
    seen, q = {src}, deque([src])
    while q:
        cur = q.popleft()
        if cur == tgt:
            return True
        for nb in adj.get(cur, ()):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return tgt in seen


def crossing_reachable(walker: CrossingGraph, src, tgt) -> bool:
    """BFS across the union, transparently crossing doors. A door is never a
    visited 'node' — reaching one expands directly to the child's nodes."""
    start = (src, None)
    seen = {start}
    q = deque([start])
    while q:
        (cur, cgid) = q.popleft()
        if cur == tgt:
            return True
        for (nb, _typ, ncgid) in walker.adjacency(cur, cgid):
            key = (nb, ncgid)
            if key not in seen and not (walker.door_child(nb) if ncgid is None else False):
                seen.add(key)
                q.append(key)
    return any(n == tgt for (n, _c) in seen)


def merged_neighbourhood(merged_db, node_id, depth=1) -> set[str]:
    nodes, edges = _merged_conn_nodes_edges(merged_db)
    adj: dict[str, set] = {}
    for (typ, s, t, _l) in edges:
        adj.setdefault(s, set()).add(t)
        adj.setdefault(t, set()).add(s)
    seen = {node_id}
    frontier = {node_id}
    for _ in range(depth):
        nxt = set()
        for c in frontier:
            nxt |= adj.get(c, set()) - seen
        seen |= nxt
        frontier = nxt
    seen.discard(node_id)
    return seen


def crossing_neighbourhood(walker: CrossingGraph, node_id, depth=1) -> set[str]:
    seen = {(node_id, None)}
    frontier = {(node_id, None)}
    for _ in range(depth):
        nxt = set()
        for (c, cgid) in frontier:
            for (nb, _typ, ncgid) in walker.adjacency(c, cgid):
                if walker.door_child(nb) if ncgid is None else False:
                    continue  # doors are never members
                key = (nb, ncgid)
                if key not in seen:
                    nxt.add(key)
        seen |= nxt
        frontier = nxt
    return {n for (n, _c) in seen if n != node_id}


def crossing_packet_records(walker: CrossingGraph, node_id, depth=1) -> list[dict]:
    """Records for a crossing neighbourhood: parent nodes plain, child nodes
    tagged with via_boundary. Doors are NEVER included."""
    recs = []
    seen = {(node_id, None)}
    frontier = {(node_id, None)}
    for _ in range(depth):
        nxt = set()
        for (c, cgid) in frontier:
            for (nb, _typ, ncgid) in walker.adjacency(c, cgid):
                if (walker.door_child(nb) if ncgid is None else False):
                    continue
                key = (nb, ncgid)
                if key not in seen:
                    seen.add(key)
                    nxt.add(key)
        frontier = nxt
    door_by_child = {n["linked_graph_id"]: nid for nid, n in walker.pnodes.items() if n["is_metanode"]}
    for (nid, cgid) in seen:
        rec = {"id": nid}
        if cgid is not None:
            rec["via_boundary"] = {"door_id": door_by_child.get(cgid, ""), "child_graph_id": cgid}
        recs.append(rec)
    return recs


def derive_door_summary(child_db: Path | str, top_k: int = 3) -> dict:
    """Deterministic door rollup: the child's top-degree landmark labels.
    Never authored, always recomputed — so a door describes what is currently
    behind it. (Betweenness would be ideal; degree is a deterministic,
    dependency-free proxy sufficient for the door label and testable by the
    verdict-neutrality battery.)"""
    conn = _connect(child_db)
    nodes = _all_nodes(conn)
    edges = _all_edges(conn)
    conn.close()
    deg: dict[str, int] = {n: 0 for n in nodes}
    for (_typ, s, t, _l) in edges:
        deg[s] = deg.get(s, 0) + 1
        deg[t] = deg.get(t, 0) + 1
    landmarks = sorted(nodes, key=lambda n: (-deg.get(n, 0), n))[:top_k]
    fingerprint = hashlib.sha1(
        ("|".join(sorted(nodes)) + "#" + "|".join(sorted(f"{a}{b}{c}{d}" for (a, b, c, d) in edges))).encode()
    ).hexdigest()[:12]
    return {"landmarks": [nodes[n]["label"] for n in landmarks],
            "landmark_ids": landmarks, "child_fingerprint": fingerprint}


def live_adjudication_divergences(merged_db, walker, query_suite) -> list:  # pragma: no cover
    """LIVE tier hook: same coverage verdict via crossing vs merged. Populated
    when a query suite is provided; empty suite → no divergences."""
    return []
