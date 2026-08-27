"""Measuring an arrangement, so layout choices get made from numbers.

Five figures, chosen because each maps to something an operator actually feels:

- **crossings** — the classic readability proxy; every crossing is a place the
  eye has to disambiguate two relationships.
- **overlap** — nodes sitting on top of each other; a hard failure, not a taste.
- **aspect** — width over height. Orientation is the primary job of this map and
  a mile-wide ribbon cannot be oriented in.
- **ink** — total edge length in graph units. Included because the deferred
  edge-rendering work (hulls, satellites, dropping NEARTO) claims to *reduce*
  ink; that claim should be checked against a render, not assumed.
- **delta** — mean position change against the previous layout. The stability
  number. A map that reshuffles is not a place anyone can learn, so this is the
  metric that decides whether the ordering ledger is doing its job.

Crossing counting is O(E²) and capped: past the cap it samples deterministically
and reports the sample size, because a slow honest number is still better than a
fast wrong one, but a hanging page load is worse than both.
"""

from __future__ import annotations

import math
from typing import Any

#: Above this edge count, crossings are estimated from a deterministic sample.
CROSSING_EDGE_CAP = 1200

# ------------------------------------------------------- the display transform
#
# Overlap is the one hard failure a layout can have, and it happens on a screen,
# not in graph units. The client does not draw graph units: it centres the map
# and scales it to a target extent that depends on the node count
# (`displayPositions`, frontend/src/product/graphModel.ts). Measuring a fixed
# graph-unit threshold therefore answered a question nobody asked — it reported
# `overlap: 0` for every graph in this repository while the scale factor shrank
# with every node added. Mirrored here so the number means "nodes that collide
# where the operator is looking".
#
# Kept as constants rather than imported because Python cannot read the module —
# they must be changed together, and `test_metrics_display_transform_matches_the_client`
# is what says so out loud.
DISPLAY_MIN_EXTENT = 720.0
DISPLAY_MAX_EXTENT = 2600.0
DISPLAY_EXTENT_PER_ROOT_NODE = 170.0
#: `GRAPH_DNA_GEOMETRY.nodeDiameter` in frontend/src/styles/graphDna.ts. Two
#: nodes closer than this are drawn on top of one another.
DISPLAY_NODE_DIAMETER = 90.0


def display_scale(positions: dict[str, tuple[float, float]]) -> float:
    """The graph-unit → display-unit factor the client will apply.

    Floored at the point where nodes would touch, because the client floors it
    there too. Fitting a map to an extent cannot preserve spacing —
    `DISPLAY_EXTENT_PER_ROOT_NODE` is 170 against a guaranteed clearance of 220,
    so even a perfectly packed map was compressed past its own pitch — and the
    client's answer is to stop shrinking and let the operator pan.

    This function's whole purpose is to predict what the browser does, so the
    floor has to live in both. A metric measured against a transform nobody
    applies is worse than no metric: it reports a clean bill of health.
    """
    if not positions:
        return 1.0
    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    width = max(1.0, max(xs) - min(xs))
    height = max(1.0, max(ys) - min(ys))
    target = max(DISPLAY_MIN_EXTENT,
                 min(DISPLAY_MAX_EXTENT,
                     math.sqrt(len(positions)) * DISPLAY_EXTENT_PER_ROOT_NODE))
    return max(min_display_scale(), target / max(width, height))


def min_display_scale() -> float:
    """Below this, two nodes at the guaranteed clearance are drawn too close.

    "Too close" is `MIN_NODE_PITCH_RATIO` node diameters apart, not zero: a
    floor set at tangency keeps `overlap` at 0 and still draws a mat of touching
    discs, which is the complaint this metric was supposed to answer.

    Imported lazily: `contract` reaches into this module, so taking it at import
    time would close the cycle.
    """
    from graph_layout.contract import MIN_DISPLAY_SCALE

    return MIN_DISPLAY_SCALE


def measure(positions: dict[str, tuple[float, float]],
            edges: list[dict[str, Any]],
            previous: dict[str, tuple[float, float]] | None = None,
            ) -> dict[str, Any]:
    segments = [
        (positions[e["source"]], positions[e["target"]])
        for e in edges
        if e["source"] in positions and e["target"] in positions
        and e["source"] != e["target"]
    ]

    crossings, sampled = _count_crossings(segments)
    scale = display_scale(positions)
    result = {
        "crossings": crossings,
        "crossings_sampled": sampled,
        "overlap": _count_overlaps(positions, DISPLAY_NODE_DIAMETER / scale),
        "aspect": _aspect(positions),
        "ink": round(sum(_length(a, b) for a, b in segments), 1),
        "nodes": len(positions),
        "edges": len(segments),
        # What the client will multiply these coordinates by. Falls as the graph
        # grows, which is the mechanism behind `overlap` — the map does not get
        # bigger past `DISPLAY_MAX_EXTENT`, it gets denser.
        "display_scale": round(scale, 5),
    }
    result["delta"] = _delta(positions, previous)
    return result


def _length(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _count_crossings(segments) -> tuple[int, bool]:
    """Pairwise proper-intersection count, sampled past the cap."""
    sampled = len(segments) > CROSSING_EDGE_CAP
    if sampled:
        # Deterministic stride sample — same graph, same estimate, always.
        stride = max(1, len(segments) // CROSSING_EDGE_CAP)
        working = segments[::stride][:CROSSING_EDGE_CAP]
        scale = (len(segments) / max(1, len(working))) ** 2
    else:
        working = segments
        scale = 1.0

    count = 0
    for i in range(len(working)):
        a1, a2 = working[i]
        for j in range(i + 1, len(working)):
            b1, b2 = working[j]
            if _crosses(a1, a2, b1, b2):
                count += 1
    return int(round(count * scale)), sampled


def _orient(p, q, r) -> int:
    val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if abs(val) < 1e-9:
        return 0
    return 1 if val > 0 else 2


def _crosses(p1, q1, p2, q2) -> bool:
    """Proper crossing only — shared endpoints are adjacency, not a crossing."""
    if p1 in (p2, q2) or q1 in (p2, q2):
        return False
    o1, o2 = _orient(p1, q1, p2), _orient(p1, q1, q2)
    o3, o4 = _orient(p2, q2, p1), _orient(p2, q2, q1)
    return o1 != o2 and o3 != o4


def _count_overlaps(positions, distance: float) -> int:
    """Nodes sharing space. Bucketed so this stays linear-ish on big graphs.

    `distance` is a *graph-unit* threshold, obtained by pulling the display node
    diameter back through `display_scale` — cheaper and exactly equivalent to
    scaling every coordinate first.
    """
    cell = max(distance, 1e-6)
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for x, y in positions.values():
        buckets.setdefault((int(x // cell), int(y // cell)), []).append((x, y))

    count = 0
    for (bx, by), members in buckets.items():
        neighbourhood = [
            p
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for p in buckets.get((bx + dx, by + dy), ())
        ]
        for i, a in enumerate(members):
            for b in neighbourhood:
                if b <= a:
                    continue  # each unordered pair once
                if math.hypot(a[0] - b[0], a[1] - b[1]) < distance:
                    count += 1
    return count


def _aspect(positions) -> float:
    if not positions:
        return 0.0
    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if height <= 0:
        return float("inf") if width > 0 else 1.0
    return round(width / height, 2)


def _delta(current, previous) -> float | None:
    """Mean movement of nodes present in both layouts.

    `None` when there is no previous layout — an unmeasured delta must not read
    as a stable one, the same discipline `betweenness: null` follows.
    """
    if not previous:
        return None
    shared = [nid for nid in current if nid in previous]
    if not shared:
        return None
    total = sum(_length(current[nid], previous[nid]) for nid in shared)
    return round(total / len(shared), 2)
