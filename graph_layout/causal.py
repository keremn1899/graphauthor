"""The causal lens — arranged for the question "where does this lead?".

Sugiyama layered drawing over the LEADSTO subgraph: break cycles, assign layers
by longest path, reduce crossings with median sweeps, then space the layers out.
Pure Python, ~200 lines, fully deterministic.

Two decisions worth knowing about:

**Nodes with no LEADSTO go to a band below, not into the flow.** A governance
graph has plenty of material that expresses or contains without leading
anywhere. Threading it into causal layers would invent a causal reading that the
graph does not assert. It sits out, visibly.

**Crossing reduction is seeded from the ordering ledger, not from node ids.** A
median sweep is only as stable as its starting order; seeding from the ledger is
what stops an unrelated commit from reshuffling the whole diagram.
"""

from __future__ import annotations

from typing import Any

from graph_layout.contract import (
    COL_WIDTH,
    ROW_HEIGHT,
    Arrangement,
)
from graph_layout.ordering import (
    Ordering, assign_slots, band_cell, band_key, band_order)

#: Median sweeps. Four is the usual point of diminishing returns and keeps a
#: cold layout of a large graph inside a second or two.
SWEEPS = 4
#: Clear air between the causal flow and the lane of non-causal material.
BAND_GAP_ROWS = 2.5
BAND_COLUMNS = 12


def causal_lens(node_ids: list[str],
                edges: list[dict[str, Any]],
                spine,
                ordering: Ordering,
                facts: dict[str, dict[str, Any]]) -> Arrangement:
    placeable = sorted(set(node_ids) | set(ordering.tombstones))
    known = set(placeable)

    flow_edges = [(e["source"], e["target"]) for e in edges
                  if e["type"] == "LEADSTO"
                  and e["source"] in known and e["target"] in known
                  and e["source"] != e["target"]]

    in_flow = {n for pair in flow_edges for n in pair}
    outside = [n for n in placeable if n not in in_flow]

    seed_rank = _seed_rank(ordering, placeable)
    acyclic = _break_cycles(flow_edges, seed_rank)
    layer_of = _assign_layers(sorted(in_flow), acyclic)
    layers = _order_within_layers(layer_of, acyclic, seed_rank)

    # Columns come from the ledger's fractional slots, same as canonical, so an
    # inserted node does not shove its whole layer sideways. Layering itself is
    # global — a new edge really can move a node between layers — so this lens
    # is inherently less stable than canonical, and honestly reports as much.
    positions: dict[str, tuple[float, float]] = {}
    for depth, row in enumerate(layers):
        assign_slots(row, ordering.slots)
        for nid in row:
            positions[nid] = (ordering.slots.get(nid, 0.0) * COL_WIDTH,
                              depth * ROW_HEIGHT)

    _centre_parents(positions, layers, acyclic)

    if outside:
        # Absolute slots in a fixed lane — see the notes in ordering.band_cell.
        band = band_order(outside, ordering.slots)
        for nid in band:
            cell = ordering.slots.get(band_key(nid), 0.0)
            positions[nid] = band_cell(cell, BAND_COLUMNS, BAND_GAP_ROWS,
                                       COL_WIDTH, ROW_HEIGHT)

    regions = {
        nid: {
            "region_id": spine.region_id.get(nid, ""),
            "depth": layer_of.get(nid, -1),
            "component_id": spine.component_id.get(nid, ""),
        }
        for nid in placeable
    }

    return Arrangement(
        positions={k: (round(x, 2), round(y, 2)) for k, (x, y) in positions.items()},
        regions=regions,
        gutter=sorted(outside),
        notes=f"{len(layers)} causal layers, {len(outside)} nodes outside the flow",
    )


def _seed_rank(ordering: Ordering, placeable: list[str]) -> dict[str, float]:
    """A stable global rank, taken from slots wherever they exist.

    Counting positions in the ledger's sibling lists looks equivalent and is
    not: inserting one node mid-list shifts the rank of everything after it,
    which perturbs the median sweeps and moves the whole diagram. Measured at
    217 units of mean movement for one added node before this changed.

    Slots are absolute, so they do not shift. Nodes without one sort after
    everything that has one, which is the right place for a newcomer.
    """
    rank: dict[str, float] = {nid: v for nid, v in ordering.slots.items()}
    if rank:
        ceiling = max(rank.values()) + 1.0
    else:
        ceiling = 0.0
    for i, nid in enumerate(placeable):
        rank.setdefault(nid, ceiling + i)
    return rank


def _break_cycles(edges: list[tuple[str, str]],
                  seed_rank: dict[str, float]) -> list[tuple[str, str]]:
    """Drop back edges found by DFS so layering terminates.

    Dropped rather than reversed: a reversed LEADSTO would draw an arrow the
    graph never asserted. The edge still renders — it just does not constrain
    the layering.
    """
    out: dict[str, list[str]] = {}
    for s, t in edges:
        out.setdefault(s, []).append(t)
    for lst in out.values():
        lst.sort(key=lambda n: (seed_rank.get(n, 0), n))

    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}
    back: set[tuple[str, str]] = set()

    for start in sorted(out, key=lambda n: (seed_rank.get(n, 0), n)):
        if colour.get(start, WHITE) != WHITE:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        colour[start] = GREY
        while stack:
            node, idx = stack[-1]
            kids = out.get(node, ())
            if idx >= len(kids):
                colour[node] = BLACK
                stack.pop()
                continue
            stack[-1] = (node, idx + 1)
            nxt = kids[idx]
            state = colour.get(nxt, WHITE)
            if state == GREY:
                back.add((node, nxt))
            elif state == WHITE:
                colour[nxt] = GREY
                stack.append((nxt, 0))

    return [e for e in edges if e not in back]


def _assign_layers(nodes: list[str],
                   edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering: a node sits one below its deepest predecessor."""
    preds: dict[str, list[str]] = {n: [] for n in nodes}
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    indeg: dict[str, int] = {n: 0 for n in nodes}
    for s, t in edges:
        succs.setdefault(s, []).append(t)
        preds.setdefault(t, []).append(s)
        indeg[t] = indeg.get(t, 0) + 1

    layer = {n: 0 for n in nodes}
    ready = sorted(n for n in nodes if indeg.get(n, 0) == 0)
    seen = 0
    while ready:
        node = ready.pop(0)
        seen += 1
        for nxt in sorted(succs.get(node, ())):
            layer[nxt] = max(layer.get(nxt, 0), layer[node] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
                ready.sort()
    return layer


def _order_within_layers(layer_of: dict[str, int],
                         edges: list[tuple[str, str]],
                         seed_rank: dict[str, float]) -> list[list[str]]:
    """Median-heuristic crossing reduction, seeded from the ordering ledger."""
    if not layer_of:
        return []
    depth = max(layer_of.values())
    layers: list[list[str]] = [[] for _ in range(depth + 1)]
    for nid, d in layer_of.items():
        layers[d].append(nid)
    for row in layers:
        row.sort(key=lambda n: (seed_rank.get(n, 0), n))

    preds: dict[str, list[str]] = {}
    succs: dict[str, list[str]] = {}
    for s, t in edges:
        succs.setdefault(s, []).append(t)
        preds.setdefault(t, []).append(s)

    for sweep in range(SWEEPS):
        downward = sweep % 2 == 0
        order = range(1, len(layers)) if downward else range(len(layers) - 2, -1, -1)
        for d in order:
            index = {n: i for i, n in enumerate(layers[d - 1 if downward else d + 1])}
            neighbours = preds if downward else succs
            layers[d].sort(key=lambda n: _median(n, neighbours, index, seed_rank))
    return layers


def _median(node: str, neighbours: dict[str, list[str]],
            index: dict[str, int], seed_rank: dict[str, float]) -> tuple[float, float]:
    """Median neighbour position; nodes with no neighbour hold their seed rank."""
    idxs = sorted(index[n] for n in neighbours.get(node, ()) if n in index)
    if not idxs:
        return (float("inf"), seed_rank.get(node, 0))
    mid = len(idxs) // 2
    if len(idxs) % 2:
        return (float(idxs[mid]), seed_rank.get(node, 0))
    return ((idxs[mid - 1] + idxs[mid]) / 2.0, seed_rank.get(node, 0))


def _centre_parents(positions: dict[str, tuple[float, float]],
                    layers: list[list[str]],
                    edges: list[tuple[str, str]]) -> None:
    """Nudge each node toward the mean x of its successors, without reordering.

    Cheap substitute for the full priority method: it straightens long chains
    while the sort order — and therefore the crossing count — stays fixed.
    """
    succs: dict[str, list[str]] = {}
    for s, t in edges:
        succs.setdefault(s, []).append(t)

    for row in reversed(layers[:-1] if layers else []):
        for i, nid in enumerate(row):
            kids = [k for k in succs.get(nid, ()) if k in positions]
            if not kids:
                continue
            target = sum(positions[k][0] for k in kids) / len(kids)
            low = positions[row[i - 1]][0] + COL_WIDTH if i else float("-inf")
            high = (positions[row[i + 1]][0] - COL_WIDTH
                    if i + 1 < len(row) else float("inf"))
            x = min(max(target, low), high)
            if x > float("-inf") and x < float("inf"):
                positions[nid] = (x, positions[nid][1])
