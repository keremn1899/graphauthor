"""Read-only projection of a committed `.lbug` for the ambient canvas.

This is a **database read**, not a governance surface. The canvas is a browser
for the knowledge graph — show the map, open nodes, explore — so it must not go
through `MCPSurface` (evidence packets, verdicts, capability gating are the
wrong shape entirely) and it must not touch `engine.get_connection`, which
**auto-seeds an empty database**. `tools/viz_sst.py` already avoids exactly that
trap by opening `real_ladybug` directly; this follows it.

Three things it owns:

- **Map projection** — every node and edge, skeletal. No `text_content`, never
  embeddings: "payloads paged in late" applies literally. Bodies are a separate
  read (`read_node`) when the operator opens a node.
- **Structural facts** — roles and betweenness come from the `.lbug.idx`
  sidecar the engine already writes. Recomputed only when it is missing or
  stale, and then with a connection this module owns.
- **Layout** — server-side, persisted, so every client sees the same map in the
  same place. The FE never lays out (decided 2026-07-27). Arrangement itself
  lives in `graph_layout/`; this module only projects it. Cached in a
  `.layout.json` sidecar keyed by **topology** version.

Decided constraints: the full map, uncapped, no runtime physics and no LOD
bands. Performance is bought with a skeletal payload, a static layout, and
client-side culling — not by hiding the graph from its owner.

See `design [new]/graph-arrangement.md` for the arrangement contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import real_ladybug as lb

REL_TYPES = ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO")

#: Bumped when the sidecar shape changes. An older sidecar is a cache miss.
#:
#: 7 — `MIN_DISPLAY_SCALE` moved off tangency, so every cached `display_scale`
#: (and the `overlap` measured through it) predicts a transform the client no
#: longer applies. The arrangements themselves are unchanged; the numbers stored
#: beside them are stale, and a stale metric is the one that reads clean.
#:
#: 6 — the ledger carries `membership_groups`, and a third lens exists. An older
#: sidecar simply lacks the field, so nothing is misread; the bump is so an
#: existing graph is re-examined and offered the new lens if it qualifies.
#:
#: 5 — `ordering.cells` changed meaning. It was `[cell_w, cell_h, cols]`, a
#: uniform cell for the whole grid; it is now `[cols, *column_widths,
#: *row_heights]`, a table sized to its content. The two are both lists of
#: floats, so a stale record does not fail to parse — it is *misread*, and a
#: cached `[4.0, 3.9, 6.0]` becomes "four columns, widths [3.9, 6.0]", which is
#: not wrong so much as meaningless. Nothing would have raised; the map would
#: just have been quietly worse on precisely the graphs that already existed.
#:
#: 4 — records carry `spokes`, and sibling ordering is chosen by measurement
#: rather than by id. The second reason is the load-bearing one: a cached
#: ordering is *preserved* on rebuild, so without a miss here an existing graph
#: would keep the arrangement it already had and never see the improvement. The
#: cost is one deliberate reshuffle per graph, which is what a version bump
#: means.
LAYOUT_SIDECAR_VERSION = 7

#: How many Ladybug ``Database`` objects this process has constructed. Native
#: memory from these never shows in ``tracemalloc``; the counter is how the
#: memory inspector knows a map read opened another graph.
open_count = 0


# ---------------------------------------------------------------- versioning


def graph_version(db_path: Path) -> str:
    """Cheap identity for a graph file: size + mtime, hashed.

    File identity — used by the catalogue, receipts, and payload cache-busting.
    Deliberately *not* the layout key any more: it changes on writes that do not
    change the graph's shape at all. `compute_structural_index` writes
    `centrality_score` back on every cold read, so keying layout on this meant
    reading the map could invalidate the map.
    """
    st = db_path.stat()
    return hashlib.sha256(f"{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:16]


def topology_version(nodes: list[dict[str, Any]],
                     edges: list[dict[str, Any]]) -> str:
    """Identity of the graph's *shape* — the layout cache key.

    Hashes exactly what an arrangement depends on: which nodes exist and which
    edges connect them. Renaming a label or recomputing centrality leaves this
    untouched, so the map holds still. Inputs arrive already sorted (see
    `read_nodes` / `read_edges`), which is what makes this reproducible across
    machines.
    """
    h = hashlib.sha256()
    for n in nodes:
        h.update(b"n\x00")
        h.update(str(n["id"]).encode())
    for e in edges:
        h.update(b"e\x00")
        h.update(f'{e["source"]}\x00{e["target"]}\x00{e["type"]}'.encode())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------- reading


def _open(db_path: Path) -> lb.Connection:
    """Read-only open. Never `engine.get_connection` — that seeds empty files."""
    global open_count
    open_count += 1
    return lb.Connection(lb.Database(str(db_path)))


#: Node columns in widest-first order. Older graphs lack the newer ones, and
#: the schema has grown twice (`kind`, then `source_unit_ids`), so the reader
#: tries each set and records which one answered rather than nesting a try per
#: column. The first version of this nested them and left the narrowest query
#: outside its own `except`, so it ran unconditionally and overwrote the good
#: result -- every old graph then raised IndexError on a column the reader
#: still believed was there.
_NODE_COLUMN_SETS: tuple[tuple[str, ...], ...] = (
    ("id", "label", "semantic_anchor", "centrality_score", "is_metanode",
     "linked_graph_id", "token_count", "kind", "source_unit_ids"),
    ("id", "label", "semantic_anchor", "centrality_score", "is_metanode",
     "linked_graph_id", "token_count", "kind"),
    ("id", "label", "semantic_anchor", "centrality_score", "is_metanode",
     "linked_graph_id", "token_count"),
)


def _select_widest(
    conn: lb.Connection,
    tail: str = "",
    params: dict | None = None,
    extra: tuple[str, ...] = (),
):
    """Run the widest column set this graph supports; return (rows, columns).

    `extra` adds columns present on every schema version (`text_content` for
    the node reader). Results are zipped back by name, so projection order
    does not matter.
    """
    last: Exception | None = None
    for base in _NODE_COLUMN_SETS:
        columns = base + extra
        projection = ", ".join(f"n.{c}" for c in columns)
        query = f"MATCH (n:Concept) {tail} RETURN {projection}".replace("  ", " ")
        try:
            return conn.execute(query, params or {}), columns
        except RuntimeError as exc:  # missing column on an older graph
            last = exc
    raise last if last else RuntimeError("no node column set succeeded")


def _node_record(values, columns) -> dict[str, Any]:
    row = dict(zip(columns, values))
    return {
        "id": row["id"],
        "label": row.get("label") or row["id"],
        "semantic_anchor": row.get("semantic_anchor") or "",
        "centrality_score": float(row.get("centrality_score") or 0.0),
        "is_metanode": bool(row.get("is_metanode")),
        "linked_graph_id": row.get("linked_graph_id") or "",
        "token_count": int(row.get("token_count") or 0),
        "kind": str(row.get("kind") or ""),
        # The join to the passage a node was built from, and the only signal
        # that carries grain -- how many nodes share a unit, how many units one
        # node draws on. A few short strings per node, unlike `text_content`.
        "source_unit_ids": list(row.get("source_unit_ids") or []),
    }


def read_nodes(conn: lb.Connection) -> list[dict[str, Any]]:
    """Skeletal node records. `text_content` is deliberately not selected."""
    rows, columns = _select_widest(conn)
    out: list[dict[str, Any]] = []
    while rows.has_next():
        out.append(_node_record(rows.get_next(), columns))
    out.sort(key=lambda n: n["id"])  # deterministic order in, deterministic map out
    return out

def read_edges(conn: lb.Connection) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in REL_TYPES:
        rows = conn.execute(
            f"MATCH (a:Concept)-[e:{rel}]->(b:Concept) RETURN a.id, b.id, e.label"
        )
        while rows.has_next():
            src, dst, label = rows.get_next()
            out.append({"source": src, "target": dst, "type": rel,
                        "label": label or ""})
    out.sort(key=lambda e: (e["type"], e["source"], e["target"]))
    return out


# Above this node count, a COLD read skips Brandes betweenness rather than
# making the operator wait for it. Measured on this machine: 10k nodes / 15k
# edges takes ~43s to index but only ~0.13s to serve once cached. Blocking a
# page load for three quarters of a minute is not a trade worth making for
# chrome; the engine still computes the full index on its own path, and the
# next read picks that up.
LARGE_GRAPH_NODES = 3000


def read_node(db_path: Path, node_id: str) -> dict[str, Any]:
    """Page in one node's body. Map payloads stay skeletal; this is the late load.

    Returns a node dict, or ``{"error": ...}`` when the id is missing/unknown.
    Never includes embeddings.
    """
    nid = (node_id or "").strip()
    if not nid:
        return {"error": "missing node id"}
    conn = _open(db_path)
    try:
        rows, columns = _select_widest(
            conn, "WHERE n.id = $id", {"id": nid}, extra=("text_content",)
        )
        if not rows.has_next():
            return {"error": "unknown node"}
        values = rows.get_next()
        record = _node_record(values, columns)
        record["text_content"] = dict(zip(columns, values)).get("text_content") or ""
        return record
    finally:
        try:
            conn.close()
        except Exception:
            pass

def structural_facts(db_path: Path, conn: lb.Connection,
                     node_count: int) -> tuple[dict[str, dict[str, Any]], str]:
    """Roles + betweenness per node, and how they were obtained.

    Returns `(facts, mode)` where mode is `full` (Brandes ran), `fast`
    (betweenness skipped — the values are ABSENT, not zero) or `none`.
    Callers must pass the mode on: reporting a skipped centrality as 0.0 with no
    marker would tell the UI "this node is not central" when the truth is "we
    did not measure it", and node sizing would quietly lie.

    The `.lbug.idx` sidecar is the engine's own cache and sits beside every
    graph it has opened; it is read when fresh and written when computed here,
    so the cost is paid once rather than on every page load.
    """
    import os

    fast = node_count > LARGE_GRAPH_NODES
    try:
        from engine import (
            _load_index_sidecar_record,
            _save_index_sidecar,
            compute_structural_index,
            structural_topology_fingerprint,
        )

        fingerprint = structural_topology_fingerprint(conn)
        cached = _load_index_sidecar_record(
            db_path,
            node_count,
            topology_fingerprint=fingerprint,
            allow_fast=fast,
        )
        if cached is not None:
            index, mode = cached
            return ({
                nid: {
                    "roles": list(facts.roles),
                    "betweenness": float(facts.betweenness_centrality),
                }
                for nid, facts in index.items()
            }, mode)

        prior = os.environ.get("SST_FAST_STRUCTURAL_INDEX")
        if fast:
            os.environ["SST_FAST_STRUCTURAL_INDEX"] = "1"
        try:
            index = compute_structural_index(conn)
        finally:
            if prior is None:
                os.environ.pop("SST_FAST_STRUCTURAL_INDEX", None)
            else:
                os.environ["SST_FAST_STRUCTURAL_INDEX"] = prior

        mode = "fast" if fast else "full"
        try:
            _save_index_sidecar(
                db_path,
                index,
                len(index),
                topology_fingerprint=fingerprint,
                index_mode=mode,
            )
        except Exception:
            pass  # a cold cache is slow, not wrong
        return ({nid: {"roles": list(f.roles),
                       "betweenness": float(f.betweenness_centrality)}
                 for nid, f in index.items()}, mode)
    except Exception:
        # A map without roles is still a map. Structure is chrome here; the
        # nodes and edges are the payload.
        return ({}, "none")


# -------------------------------------------------------------------- layout


def _sidecar_for(db_path: Path) -> Path:
    return db_path.with_name(f"{db_path.stem}.layout.json")


def _read_sidecar(db_path: Path) -> dict[str, Any] | None:
    """Previous layout, or None. An unreadable or older sidecar is a miss."""
    sidecar = _sidecar_for(db_path)
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("version") != LAYOUT_SIDECAR_VERSION:
        return None
    return data


def load_or_build_layout(db_path: Path, topo_version: str, nodes, edges,
                         lens: str | None = None) -> dict[str, Any]:
    """The arrangement for this graph, rebuilt only when its shape changed.

    Returns one lens record: positions, regions, the ordering ledger and the
    quality metrics. The ordering is the part that matters — positions are
    derived from it, so a rebuild after a commit reproduces the operator's map
    with the new material inserted locally rather than reshuffling it.

    Each lens keeps its **own** ledger in the sidecar. They cannot share one:
    slots mean different things in a containment tree and in a causal layering,
    so a shared ledger would mean switching lenses and switching back reshuffled
    the map the operator had learned.

    Best-effort persistence: a read-only or full disk costs a recomputation, not
    the map.
    """
    from graph_layout import metrics as layout_metrics
    from graph_layout.contract import arrange, select_lens
    from graph_layout.ordering import Ordering

    wanted_lens = select_lens(lens, [n["id"] for n in nodes], edges)
    prior = _read_sidecar(db_path) or {}
    prior_lenses = prior.get("lenses") if isinstance(prior.get("lenses"), dict) else {}
    prior_record = prior_lenses.get(wanted_lens) or {}
    topology_matches = prior.get("topology_version") == topo_version

    if topology_matches and prior_record.get("positions"):
        return prior_record

    previous_ordering = Ordering.from_json(prior_record.get("ordering"))
    previous_positions = {
        nid: (float(xy[0]), float(xy[1]))
        for nid, xy in (prior_record.get("positions") or {}).items()
        if isinstance(xy, (list, tuple)) and len(xy) == 2
    } or None

    node_ids = [n["id"] for n in nodes]
    arrangement, ordering, lens_name = arrange(
        wanted_lens, node_ids, edges, ordering=previous_ordering)

    measured = layout_metrics.measure(
        arrangement.positions, edges, previous_positions)

    record = {
        "lens": lens_name,
        "ordering": ordering.to_json(),
        "positions": {k: [v[0], v[1]] for k, v in arrangement.positions.items()},
        "regions": arrangement.regions,
        "gutter": arrangement.gutter,
        "spokes": arrangement.spokes,
        "metrics": measured,
        "notes": arrangement.notes,
    }

    # Other lenses' ledgers survive a rebuild of this one, but their positions
    # are stale the moment topology moves — drop those and keep the ledger, so
    # switching to them re-derives from what the operator already saw.
    lenses: dict[str, Any] = {}
    for name, rec in prior_lenses.items():
        if name == lens_name or not isinstance(rec, dict):
            continue
        lenses[name] = (rec if topology_matches
                        else {"lens": name, "ordering": rec.get("ordering") or {}})
    lenses[lens_name] = record

    try:
        _sidecar_for(db_path).write_text(json.dumps({
            "version": LAYOUT_SIDECAR_VERSION,
            "topology_version": topo_version,
            "lenses": lenses,
        }), encoding="utf-8")
    except OSError:
        pass
    return record


# ---------------------------------------------------------------- projection


def _tier_context(nodes: list[dict[str, Any]], measured: bool) -> dict[str, Any]:
    """Pick the channel that can actually separate *this* graph, once.

    Absolute betweenness cut-offs looked reasonable and were wrong: on
    `agreements` — 23 roots with a fan-out of two — every real betweenness is
    near zero because almost nothing routes through anything, so all 31 nodes
    came back `leaf` and the map had no hierarchy at all.

    So the channel is chosen per graph. Betweenness where it separates anything,
    degree where it does not, and nothing at all when neither does — which is
    the honest answer for a graph that genuinely has no centre.
    """
    betweenness = [float(n["betweenness"]) for n in nodes
                   if measured and n.get("betweenness") is not None]
    degrees = [float(n.get("centrality_score") or 0.0) for n in nodes]

    if betweenness and max(betweenness) > 0.0:
        return {"channel": "betweenness", "cuts": _cuts(betweenness)}
    if degrees and max(degrees) > 0.0:
        return {"channel": "degree", "cuts": _cuts(degrees)}
    return {"channel": None, "cuts": (0.0, 0.0)}


def _cuts(values: list[float]) -> tuple[float, float]:
    """Landmark and hub thresholds, by rank within this graph.

    Top tenth and top third, mirroring how `compute_structural_index` already
    picks out nexus and bridge roles — one definition of "prominent here",
    not two.
    """
    ordered = sorted(values, reverse=True)
    landmark = ordered[max(0, len(ordered) // 10)]
    hub = ordered[max(0, len(ordered) // 3)]
    return landmark, hub


def _tier(node: dict[str, Any], context: dict[str, Any]) -> str | None:
    """Size band, computed here so the client never reconciles two channels.

    The frontend had to choose between `centrality_score` (degree, always
    present) and `betweenness` (nullable under `structural_mode: "fast"`). That
    is a decision about honesty, not about pixels, so it belongs on this side.

    `None` means "we could not tell" and must render at a neutral size — never
    the smallest, which would say "peripheral" about a node nobody measured.
    Same discipline as `betweenness: null`.
    """
    if node.get("is_metanode"):
        return "landmark"  # a node that *is* another graph is never a leaf
    channel = context["channel"]
    if channel is None:
        return None
    value = (float(node["betweenness"])
             if channel == "betweenness" and node.get("betweenness") is not None
             else float(node.get("centrality_score") or 0.0))
    landmark, hub = context["cuts"]
    if value >= landmark and value > 0.0:
        return "landmark"
    if value >= hub and value > 0.0:
        return "hub"
    return "leaf"


def read_map(db_path: Path, lens: str | None = None) -> dict[str, Any]:
    """The whole committed graph, skeletal, with coordinates."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"error": f"no such graph: {db_path.name}"}

    conn = _open(db_path)
    try:
        nodes = read_nodes(conn)
        edges = read_edges(conn)
        facts, structural_mode = structural_facts(db_path, conn, len(nodes))
    finally:
        # Catalogue/map reads are short-lived. Leaving Ladybug connections
        # open here eventually exhausts handles (and can leave a graph looking
        # locked to a later request), which used to surface as an intermittent
        # `/graph/graphs` 500 after navigating between maps.
        conn.close()
    version = graph_version(db_path)
    topo = topology_version(nodes, edges)
    layout = load_or_build_layout(db_path, topo, nodes, edges, lens)
    positions = layout.get("positions") or {}
    regions = layout.get("regions") or {}

    # `fast` means betweenness was NOT measured. Emit null rather than 0.0 so a
    # client cannot mistake "unmeasured" for "not central" and size nodes by it.
    measured = structural_mode == "full"
    for n in nodes:
        f = facts.get(n["id"]) or {}
        # Structural roles are not emitted. They are engine vocabulary the Graph
        # Compass consumes to orient the Planner; no client could act on
        # "causal_nexus", and every one that received it merely printed it back.
        # `compute_structural_index` is unchanged — this is the read boundary.
        n["betweenness"] = f.get("betweenness", 0.0) if measured else None
    tier_context = _tier_context(nodes, measured)
    for n in nodes:
        x, y = positions.get(n["id"], [0.0, 0.0])
        n["x"], n["y"] = x, y
        region = regions.get(n["id"]) or {}
        n["region_id"] = region.get("region_id", "")
        n["depth"] = region.get("depth", 0)
        # The packed first-tier region, where the graph has one. Under a
        # universal root `region_id` is that root for every node, so it cannot
        # answer "which part of the map am I in" exactly when that is asked.
        n["branch_id"] = region.get("branch_id", "")
        n["tier"] = _tier(n, tier_context)

    return {
        "graph_version": version,
        # Layout cache key. Unlike graph_version this only moves when the
        # graph's *shape* moves, which is why the map holds still.
        "topology_version": topo,
        "lens": layout.get("lens"),
        # Only the lenses that can say something about *this* graph. A lens with
        # nothing to say is worse than a missing one — the operator switches to
        # it, sees the map in a tray, and concludes the control is broken.
        "available_lenses": _lens_names(nodes, edges),
        "node_count": len(nodes),
        "edge_count": len(edges),
        # full | fast (betweenness skipped for size) | none (unavailable)
        "structural_mode": structural_mode,
        # Mean node movement since the previous arrangement; null when there was
        # none to compare against. Lets the canvas animate rather than teleport.
        "layout_delta": (layout.get("metrics") or {}).get("delta"),
        "layout_metrics": layout.get("metrics") or {},
        # Spacing, stated rather than implied. The arrangement guarantees
        # `layout_clearance` graph units between any two nodes; a node is drawn
        # `node_diameter` wide. Scaling this map below `min_display_scale`
        # crowds them however good the arrangement is — measured, that is where
        # every overlap in this product has come from, and it starts biting at
        # 20 nodes, not at 400. A client that fits a map to its viewport must
        # clamp there and pan/zoom instead. The floor leaves a real gap rather
        # than stopping at the point where two nodes touch; tangent discs are
        # what "the nodes still overlap" looks like from the operator's chair.
        "layout_clearance": _spacing()[0],
        "node_diameter": _spacing()[1],
        "min_display_scale": round(_spacing()[2], 4),
        # Isolated material, placed in its own band. These are `structural_gaps`
        # in compass terms — output, not noise.
        "gutter": layout.get("gutter") or [],
        # `[parent, child]` edges into packed regions. Drawing these as straight
        # lines is what makes a universal root a starburst — on `rfc` all 170
        # crossings come from 59 of them. Renderers may route or suppress them
        # and draw the region as a frame; the geometry does not change either
        # way. Empty when the graph has no branch-packed root.
        "spokes": layout.get("spokes") or [],
        "nodes": nodes,
        "edges": edges,
    }


def _spacing() -> tuple[float, float, float]:
    """`(clearance, node diameter, minimum safe display scale)`."""
    try:
        from graph_layout.contract import (
            MIN_CLEARANCE, MIN_DISPLAY_SCALE, NODE_DIAMETER)

        return MIN_CLEARANCE, NODE_DIAMETER, MIN_DISPLAY_SCALE
    except Exception:
        return 220.0, 90.0, 90.0 * 1.6 / 220.0


def _lens_names(nodes: list[dict[str, Any]],
                edges: list[dict[str, Any]]) -> list[str]:
    try:
        from graph_layout.contract import applicable_lenses

        return applicable_lenses([n["id"] for n in nodes], edges)
    except Exception:
        return ["canonical"]
