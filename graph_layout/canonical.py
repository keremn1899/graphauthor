"""The canonical lens — arranged for the question "what is in this graph?".

Three moves, in order of how much they change the picture:

1. **Tidy tree within a component**, children in ledger order rather than id
   order, so the arrangement is stable across commits.
2. **Shelf packing across components** to a target aspect ratio. The previous
   implementation walked a single accumulating `cursor`, so a graph with forty
   components rendered as a forty-region-wide ribbon — the worst possible shape
   for orientation, and a bigger legibility loss than any algorithm choice.
3. **A gap gutter.** Orphans are `structural_gaps` in compass terms and, in this
   product, they are output rather than noise — the honest gaps are the roadmap.
   They used to land in an accidental tail on the right, purely because
   single-node components sort last. Now they get a designed band, and their
   whitespace means something.

Packing walks components in *ledger rank order* rather than sorting by area
every time. True squarified packing would reshuffle the whole map whenever a
component changed size; keeping rank costs a little compactness and buys the
stability the map exists for.
"""

from __future__ import annotations

import math
from typing import Any

from graph_layout.contract import (
    COL_WIDTH,
    COMPONENT_GAP_X,
    COMPONENT_GAP_Y,
    ROW_HEIGHT,
    TARGET_ASPECT,
    Arrangement,
)
from graph_layout.ordering import (
    ROOT_KEY, Ordering, assign_slots, band_cell, band_key, band_order)

#: Columns per row in the gutter grid — wide and shallow, so isolated material
#: reads as a margin rather than as another region of the graph.
GUTTER_COLUMNS = 12
#: Clear air between the graph proper and the gutter lane above it.
GUTTER_GAP_ROWS = 2.0

#: First-tier children at which a root earns regional branch packing. Crossing
#: it re-lays the component, so the crossing is recorded and never reversed.
BRANCH_FAN_MIN = 4
#: Aspect at which a branch is judged a ribbon and packed in turn rather than
#: left as a row of leaves. `inf` disables the recursion entirely.
#:
#: Gated on the branch's *shape*, not on its depth. Recursing unconditionally
#: was measured and is not a win: it rescued `rfc`, whose worst branch is 52
#: columns wide (aspect 20), taking overlapping pairs from 740 to 124 — and it
#: made `english_negligence` worse on every single metric at once, because its
#: branches were already well proportioned and packing them only added
#: whitespace and crossings.
#:
#: Even gated it is not a free win. Over 35 real graphs it changes two, improving
#: the 416-node `rfc` (740 overlapping pairs to 475) and degrading the 84-node
#: one (16 to 59) — so it is offered to `contract.arrange` as a *candidate* and
#: kept only where it measures better, never applied on faith.
BRANCH_RIBBON_ASPECT = 4.0
#: The candidate that leaves broad branches as rows.
BRANCH_RIBBON_OFF = float("inf")
#: Clear air between packed subtrees inside one component.
SUBTREE_GAP_X = 1.0
SUBTREE_GAP_Y = 0.9
#: Never wrap a shelf narrower than this. Without a floor, a four-node graph
#: packs one box per row and renders as a single column — a ribbon on its side.
MIN_ROW_WIDTH = 3.0
#: Slack built into a grid cell when it is first sized. Without it the pitch has
#: to grow the first time any subtree gains a node, and re-pitching moves the
#: whole grid. One column of headroom absorbs ordinary growth for the cost of a
#: little whitespace — a trade the map wants every time.
CELL_HEADROOM = 1.0
#: How far a remembered shelf width may drift from `TARGET_ASPECT` before the
#: canvas is repacked, as a natural-log ratio — 0.7 is about a factor of two in
#: either direction. Repacking reflows every component, so it must be worth it.
PACK_ASPECT_TOLERANCE = 0.7
#: Ledger key for the component shelf's remembered width. Namespaced away from
#: component keys, which hold grid pitches and mean something different.
COMPONENT_SHELF_KEY = "::components"


def canonical_lens(node_ids: list[str],
                   edges: list[dict[str, Any]],
                   spine,
                   ordering: Ordering,
                   facts: dict[str, dict[str, Any]],
                   shape: dict[str, Any] | None = None) -> Arrangement:
    placeable = sorted(set(node_ids) | set(ordering.tombstones))
    known = set(placeable)

    by_component: dict[str, list[str]] = {}
    for nid in placeable:
        cid = ordering.component_of.get(nid) or spine.component_id.get(nid)
        if cid is None:
            continue  # tombstone with no current component: gutter handles it
        by_component.setdefault(cid, []).append(nid)

    # Isolated nodes are the gap gutter. Tombstones whose component is gone go
    # there too — a ghost of something removed is exactly gutter material.
    gutter = [nid for nid in placeable
              if spine.degree.get(nid, 0) == 0 or nid not in spine.component_id]
    gutter_set = set(gutter)

    # Filled in by `_tidy_root` as it packs regions: which first-tier branch
    # each node sits under, and the spokes that reach those branches.
    branch_of: dict[str, str] = {}
    spokes: list[list[str]] = []
    ribbon = float((shape or {}).get("ribbon_aspect", BRANCH_RIBBON_ASPECT))

    boxes: list[tuple[str, dict[str, tuple[float, float]], float, float]] = []
    for cid in ordering.region_rank:
        members = [n for n in by_component.get(cid, ()) if n not in gutter_set]
        if not members:
            continue
        local = _tidy_component(members, spine, ordering, known, cid,
                               branch_of, spokes, ribbon)
        if local:
            boxes.append(_box(local))

    positions = {
        nid: (x * COL_WIDTH, y * ROW_HEIGHT)
        for nid, (x, y) in _pack(boxes, COMPONENT_GAP_X, COMPONENT_GAP_Y,
                                 ordering, COMPONENT_SHELF_KEY).items()
    }

    # The gutter has a lane of its own, above the graph.
    if gutter:
        # Cells come from the absolute slot, never from the enumeration index.
        # Ordering alone is not enough: when a member LEAVES the band — an
        # orphan that gains a child is no longer isolated — every later member
        # re-indexed and shifted. Found by the property tests on a four-node,
        # zero-edge graph. With slots, a departure leaves a hole and an
        # insertion lands between, which is the same guarantee the trees get.
        band = band_order(gutter, ordering.slots)
        for nid in band:
            cell = ordering.slots.get(band_key(nid), 0.0)
            positions[nid] = band_cell(cell, GUTTER_COLUMNS, GUTTER_GAP_ROWS,
                                       COL_WIDTH, ROW_HEIGHT)

    regions = {
        nid: {
            "region_id": spine.region_id.get(nid, ""),
            "depth": spine.depth.get(nid, 0),
            "component_id": ordering.component_of.get(nid, ""),
            # Which packed first-tier region this node lives in, where there is
            # one. `region_id` cannot answer that: under a universal root it is
            # that root for every node in the graph, which is exactly the case
            # where the answer matters.
            "branch_id": branch_of.get(nid, ""),
        }
        for nid in placeable
    }

    return Arrangement(
        positions={k: (round(x, 2), round(y, 2)) for k, (x, y) in positions.items()},
        regions=regions,
        gutter=sorted(gutter),
        spokes=sorted(spokes),
        notes=f"{len(boxes)} components packed, {len(gutter)} in gutter",
    )


def _tidy_component(members: list[str], spine, ordering: Ordering,
                    known: set[str],
                    component_key: str = "",
                    branch_of: dict[str, str] | None = None,
                    spokes: list[list[str]] | None = None,
                    ribbon: float = BRANCH_RIBBON_ASPECT,
                    ) -> dict[str, tuple[float, float]]:
    """Tidy tree over one component, in grid units (columns x depth).

    Two levels of packing, because the ribbon turned out not to come from where
    it looked like it came from. `agreements` is one component with **23 roots
    and a maximum fan-out of two** — the width was 23 subtrees standing in a
    row, not one wide fan of siblings. So each root's subtree is laid out
    independently and the subtrees are then shelf-packed exactly as components
    are, one level up.

    Inside a subtree, leaves take fractional slots from the ledger, so an
    inserted node does not push its neighbours sideways. Parents are centred
    over their children and so do move when a child arrives — honest, since the
    thing they contain has changed.
    """
    member_set = set(members)

    roots = [n for n in _ordered(ordering, ROOT_KEY, member_set)
             if spine.parent.get(n) not in member_set]
    if not roots:
        # Fully cyclic (or entirely reparented) — pick a stable entry point.
        roots = sorted(member_set)[:1]

    placed: set[str] = set()
    boxes: list[tuple[dict[str, tuple[float, float]], float, float]] = []

    for root in roots:
        local = _tidy_root(root, member_set, ordering, placed, component_key,
                           branch_of, spokes, ribbon)
        if local:
            boxes.append(_box(local))

    # Defensive: anything unreachable from a root still gets a box of its own.
    for nid in sorted(member_set - placed):
        placed.add(nid)
        boxes.append(({nid: (0.0, 0.0)}, 1.0, 1.0))

    return _grid_pack(boxes, SUBTREE_GAP_X, SUBTREE_GAP_Y,
                      ordering, component_key)


def _tidy_root(root: str, member_set: set[str], ordering: Ordering,
               placed: set[str], component_key: str,
               branch_of: dict[str, str] | None = None,
               spokes: list[list[str]] | None = None,
               ribbon: float = BRANCH_RIBBON_ASPECT,
               ) -> dict[str, tuple[float, float]]:
    """Lay out a root, packing a broad first tier as regional branches.

    A universal corpus root is semantically useful and visually dangerous. If
    its twelve substantial children are passed to the ordinary tidy-tree move,
    all of their leaves occupy one line and a 100-node corpus becomes a 37:1
    ribbon. Those first-tier branches are the graph's meaningful visual
    regions, so pack them into the same stable grid used for independent
    subtrees, then place the universal root above their combined centre.

    Small fans stay ordinary trees. The threshold avoids turning every modest
    hierarchy into a tiled dashboard.

    **This applies at every level, not just the top.** Packing only the first
    tier left the ribbon intact one step down: on `rfc` the root's 59 branches
    were tiled correctly, but one of those branches held 53 nodes whose leaves
    all landed on a single line, so that branch alone was 52 columns wide and
    set the width of the column it sat in. It is the same failure the top-level
    packing exists to prevent, so it takes the same cure — a broad fan is packed
    wherever it occurs.

    **The choice is remembered and one-way.** A threshold on child count is a
    discontinuity — the component is laid out by a different algorithm on each
    side of it — so a root sitting on the boundary re-laid everything beneath it
    every time a child arrived or left. Once a root has earned branch packing it
    keeps it, which turns an oscillation into a single transition. The property
    tests assert exactly that: a large movement is allowed only on a step that
    records a new branch root.
    """
    children = [child for child in _ordered(ordering, root, member_set)
                if child not in placed]
    if len(children) >= BRANCH_FAN_MIN and root not in ordering.branch_roots:
        ordering.branch_roots.append(root)
    if root not in ordering.branch_roots:
        return _tidy_subtree(root, member_set, ordering, placed)

    branch_key = f"{component_key}::branches::{root}"
    placed.add(root)
    branch_boxes = []
    branch_roots: list[str] = []
    # Guards the re-lay below against retrying a branch this call already
    # packed, which would recurse without end on a pathological shape.
    placed_as_branch: set[str] = set()
    for child in children:
        # Recursive: a branch that is itself broad gets packed too. Neither
        # `branch_of` nor `spokes` is passed down.
        #
        # `branch_of` names the *first-tier* region a node belongs to, and an
        # inner level would overwrite that with a narrower answer to a question
        # nobody asked.
        #
        # `spokes` was passed down at first, on the reasoning that every packed
        # fan draws the same starburst. True, and not the point — measured on
        # `rfc`, the first tier's 59 spokes account for 154 of the map's 168
        # crossings and every nested spoke put together accounts for 14. Marking
        # all 276 made two thirds of the graph's edges "structural noise", which
        # is not a signal any more, it is just a dimmer switch.
        local = _tidy_subtree(child, member_set, ordering, placed)
        if local and _is_ribbon(local, ribbon) and child not in placed_as_branch:
            # Lay it again as a packed region. Cheap — a subtree is laid out in
            # microseconds — and it only happens for a branch that measured
            # badly, so ordinary material never pays for it.
            placed.difference_update(local)
            packed_local = _tidy_root(child, member_set, ordering, placed,
                                      branch_key, None, None, ribbon)
            if packed_local:
                local = packed_local
                placed_as_branch.add(child)
        if local:
            branch_boxes.append(_box(local))
            branch_roots.append(child)
            if branch_of is not None:
                for nid in local:
                    branch_of[nid] = child
            if spokes is not None:
                spokes.append([root, child])

    if not branch_boxes:
        return {root: (0.0, 0.0)}

    packed = _grid_pack(
        branch_boxes,
        SUBTREE_GAP_X,
        SUBTREE_GAP_Y,
        ordering,
        branch_key,
    )
    shifted = {nid: (x, y + 1.0) for nid, (x, y) in packed.items()}
    root_xs = [shifted[child][0] for child in branch_roots if child in shifted]
    if root_xs:
        root_x = (min(root_xs) + max(root_xs)) / 2.0
    else:
        root_x = (min(x for x, _ in shifted.values())
                  + max(x for x, _ in shifted.values())) / 2.0
    shifted[root] = (root_x, 0.0)
    return shifted


def _tidy_subtree(root: str, member_set: set[str], ordering: Ordering,
                  placed: set[str]) -> dict[str, tuple[float, float]]:
    """One root's subtree, in its own coordinate frame."""
    visit_order: list[str] = []
    depth_of: dict[str, int] = {}
    leaves: list[str] = []

    def walk(nid: str, depth: int) -> None:
        if nid in placed:
            return
        placed.add(nid)
        visit_order.append(nid)
        depth_of[nid] = depth
        kids = [k for k in _ordered(ordering, nid, member_set)
                if k not in placed]
        if not kids:
            leaves.append(nid)
            return
        for kid in kids:
            walk(kid, depth + 1)

    walk(root, 0)
    if not visit_order:
        return {}

    assign_slots(leaves, ordering.slots)

    local: dict[str, tuple[float, float]] = {}
    # Children are placed before their parents (reverse visit order), so a
    # parent can be centred over an already-positioned child span.
    for nid in reversed(visit_order):
        kids = [k for k in _ordered(ordering, nid, member_set) if k in local]
        if kids:
            xs = [local[k][0] for k in kids]
            x = (min(xs) + max(xs)) / 2.0
        else:
            x = ordering.slots.get(nid, 0.0)
        local[nid] = (x, float(depth_of.get(nid, 0)))
    return local


def _is_ribbon(local: dict[str, tuple[float, float]], ribbon: float) -> bool:
    """Is this subtree drawn far wider than it is tall, in real units?

    A tidy tree puts every leaf of a fan on one line, so a broad shallow subtree
    is a hairline — `rfc`'s worst branch is 52 columns by 3 rows, an aspect of
    20. Judged in real units because a column is 260 and a row is 220.
    """
    if not local or math.isinf(ribbon):
        return False
    _shifted, width, height = _box(local)
    return (width * COL_WIDTH) / max(height * ROW_HEIGHT, 1e-9) > ribbon


def _box(local: dict[str, tuple[float, float]]):
    """Normalise a layout to its own origin and report its extent.

    Slots are global, so a subtree's raw columns can start anywhere. A
    translation is invisible to the operator; what must not change is the
    arrangement *inside* the box.
    """
    ox = min(x for x, _ in local.values())
    oy = min(y for _, y in local.values())
    shifted = {nid: (x - ox, y - oy) for nid, (x, y) in local.items()}
    width = max(x for x, _ in shifted.values()) + 1.0
    height = max(y for _, y in shifted.values()) + 1.0
    return shifted, width, height


def _ordered(ordering: Ordering, parent: str, member_set: set[str]) -> list[str]:
    """Children of `parent` in ledger order, restricted to this component."""
    return [n for n in ordering.ordered_children(parent) if n in member_set]


def _track_sizes(needs: list[float], remembered: list[float]) -> list[float]:
    """Grow-only track sizes (column widths, or row heights).

    `CELL_HEADROOM` is added when a track is newly *established*, never to the
    running requirement. Adding it every pass looks equivalent and is not: the
    headroom then rises with the content it is supposed to absorb, so a box
    growing by one column always widens its own track and shifts everything
    after it. That is exactly the re-pitch the headroom exists to prevent, and
    it broke the stability property on a five-node graph.

    Shrinking back is never allowed: it would re-pitch the whole canvas to
    reclaim whitespace nobody was troubled by.
    """
    tracks = []
    for i, need in enumerate(needs):
        prior = remembered[i] if i < len(remembered) else 0.0
        tracks.append(prior if need <= prior else need + CELL_HEADROOM)
    return tracks


def _offsets(tracks: list[float]) -> list[float]:
    out = [0.0]
    for size in tracks[:-1]:
        out.append(out[-1] + size)
    return out


def _pack(boxes, gap_x: float, gap_y: float,
          ordering: Ordering | None = None,
          key: str = "") -> dict[str, tuple[float, float]]:
    """Arrange boxes as a table: fixed column count, tracks sized to content.

    Used at both levels — subtrees inside a component, and components on the
    canvas — because both need the same two things and the obvious algorithms
    each give up one of them.

    **Membership is by index, so growth never reflows.** A shelf wraps by
    accumulated width, so one box getting wider pushes a later box onto the next
    row and moves everything after it; measured on `mystery`, that was 13 units
    of movement per added node against 772. Here box *i* is always at
    `(i % cols, i // cols)` and a growing box widens its own column instead.

    **Tracks are sized per column and per row, so nothing is padded to the
    largest box.** A uniform cell is what made the canvas 122x larger than the
    material in it: `rfc` packs 59 branches averaging 6.1 columns wide, one of
    which is 52, so every one of them got a 54-wide cell — 17.3x waste, and
    34.7x on `tesco-200`, whose map filled **0.8%** of its own bounding box.
    That is not merely ugly. A client fits a map by scaling it down, so wasted
    canvas is spacing spent: a map five times too wide is drawn five times too
    small, and its nodes overlap.

    Rank order is preserved rather than sorting by area. True squarified packing
    would reshuffle everything whenever one box changed size; keeping rank costs
    a little compactness and buys the stability the map exists for.

    The column count is searched against the *real* aspect rather than estimated.
    It used to come from `sqrt(area * TARGET_ASPECT)`, which is wrong twice over:
    it ignores the gaps between boxes — `COMPONENT_GAP_X` is two columns, wider
    than the boxes themselves on a graph of narrow subtrees — and it treats a
    grid unit as square when a column is 260 and a row is 220. Asked for 1.6 on
    twenty root-and-child pairs it delivered 0.35, a vertical ribbon.
    """
    if not boxes:
        return {}

    n = len(boxes)

    def tracks_for(cols: int, prior_w: list[float], prior_h: list[float]):
        rows = math.ceil(n / cols)
        need_w = [0.0] * cols
        need_h = [0.0] * rows
        for i, (_local, w, h) in enumerate(boxes):
            need_w[i % cols] = max(need_w[i % cols], w + gap_x)
            need_h[i // cols] = max(need_h[i // cols], h + gap_y)
        return (_track_sizes(need_w, prior_w), _track_sizes(need_h, prior_h))

    def score_for(cols: int, prior_w: list[float], prior_h: list[float]) -> float:
        widths, heights = tracks_for(cols, prior_w, prior_h)
        aspect = ((sum(widths) * COL_WIDTH)
                  / max(sum(heights) * ROW_HEIGHT, 1e-9))
        return abs(math.log(max(aspect, 1e-9) / TARGET_ASPECT))

    remembered = (ordering.cells.get(key)
                  if ordering is not None and key else None)
    prior_w: list[float] = []
    prior_h: list[float] = []
    cols = 0
    if remembered:
        cols = int(remembered[0])
        prior_w = [float(v) for v in remembered[1:1 + cols]]
        prior_h = [float(v) for v in remembered[1 + cols:]]

    if not cols or cols > n:
        cols = min(range(1, n + 1), key=lambda c: (score_for(c, [], []), c))
        prior_w, prior_h = [], []
    else:
        want = min(range(1, n + 1),
                   key=lambda c: (score_for(c, prior_w, prior_h), c))
        # Adopt a new column count only when the shape is properly wrong. A
        # one-column drift is not worth relearning the map for — and a changed
        # count invalidates the remembered tracks, since a column then holds a
        # different set of boxes.
        if abs(want - cols) >= 2:
            cols, prior_w, prior_h = want, [], []

    widths, heights = tracks_for(cols, prior_w, prior_h)
    if ordering is not None and key:
        ordering.cells[key] = [float(cols), *widths, *heights]

    x_at, y_at = _offsets(widths), _offsets(heights)
    positions: dict[str, tuple[float, float]] = {}
    for i, (local, _w, _h) in enumerate(boxes):
        col, row = i % cols, i // cols
        for nid, (x, y) in local.items():
            positions[nid] = (x_at[col] + x, y_at[row] + y)
    return positions


#: Subtrees within a component and components on the canvas are packed the same
#: way; the name is kept because the call sites read better for it.
_grid_pack = _pack
