"""The ordering ledger — the stable thing that positions are derived from.

The inversion this module exists for: **persist the ordering, derive the
coordinates.** Before it, leaf order came from `sorted()` on node ids, so a
single new node with an early-sorting id shifted an entire subtree sideways. A
map that reshuffles is not a place anyone can learn.

Three kinds of state, each of which turned out to be load-bearing when it was
measured on real fixtures:

- **slots** — fractional column indices for leaves. Sibling *order* alone is not
  enough: a tidy tree hands out columns from a running counter, so inserting one
  leaf shifts every leaf to its right by a full column. That measured as 184
  units of mean movement for one added node on the hexagonal-orders fixture.
  With slots it is ~3, and the residual is ancestors re-centring, which is
  honest — a parent that contains more really has changed.
- **component keys** — component identity by continuity of membership. Naming a
  component after its sorted-first member means any node with a low-sorting id
  renames the whole component, which loses its packing rank and swaps it into a
  different row. Observed on the mystery fixture: half the graph moved
  vertically because one probe id began with an underscore.
- **tombstones** — history lives on the ambient screen, so scrubbing back
  renders an older topology. Retired nodes keep their slot, so an older state is
  a subset of the current geometry plus ghosts where things used to be. Nothing
  moves; things fade.

The cost of slots is drift: repeated insertion into the same gap halves it each
time. `needs_renormalise` reports when the tightest gap is too small to render,
and the caller may reset to integers — a one-off reshuffle, rather than letting
nodes silently converge onto each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: Key used for the top-level sibling list (spine roots have no parent).
ROOT_KEY = ""

#: Prefix marking a slot that belongs to a node without being its id. One node
#: can hold several slots meaning different things — a column inside its subtree,
#: a cell inside a band — and they must not collide.
BAND_PREFIX = "band:"
SLOT_NAMESPACES = (BAND_PREFIX,)

#: Median-relaxation passes used to decide where an unplaced node belongs among
#: its siblings. Four is the usual point of diminishing returns, and matches the
#: sweep count the causal lens already uses.
BARYCENTRE_ROUNDS = 4


def band_key(node_id: str) -> str:
    """Slot key for a node's membership of a band.

    Namespaced away from the tree's leaf slots: a node can be a leaf in one
    arrangement and a band member in another, and one slot cannot mean a column
    in a subtree and a cell in a grid at the same time. `reconcile` knows the
    prefix, so a band slot survives exactly as long as its node does.
    """
    return f"{BAND_PREFIX}{node_id}"


@dataclass
class Ordering:
    """Sibling order, leaf slots, component identity, rank, and tombstones."""

    siblings: dict[str, list[str]] = field(default_factory=dict)
    slots: dict[str, float] = field(default_factory=dict)
    region_rank: list[str] = field(default_factory=list)
    tombstones: list[str] = field(default_factory=list)
    component_of: dict[str, str] = field(default_factory=dict)
    #: Roots laid out as packed regional branches rather than as one tidy tree.
    #: The choice is made on a child-count threshold, so it is a discontinuity:
    #: crossing it re-lays the whole component. Remembered and one-way, because
    #: a root sitting on the threshold would otherwise flip modes — and reshuffle
    #: everything under it — every time a child came or went.
    branch_roots: list[str] = field(default_factory=list)
    #: Nodes the membership lens has decided are *groups* rather than members.
    #: Classification turns on in-degree exceeding out-degree, which is a knife
    #: edge: one added child flipped a node out of the group side and re-drew
    #: the entire diagram. Found by the property tests on five nodes. Recorded
    #: here so the decision is sticky — a group stays a group while it still has
    #: the members to justify it, and only stops when it genuinely loses them.
    membership_groups: list[str] = field(default_factory=list)
    #: component key -> `[row_pitch, columns, *column_widths]` for the subtree
    #: grid. Sizing cells from the current widest subtree re-pitches the grid
    #: whenever any subtree grows — measured at 1179 units of movement for one
    #: added node — so the pitch is remembered and only ever grows, and only
    #: when a box genuinely no longer fits. Widths are per column because one
    #: unusually wide subtree used to set the cell for every other one, which
    #: cost up to 34x the canvas (see `canonical._grid_pack`).
    cells: dict[str, list[float]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "siblings": {k: list(v) for k, v in self.siblings.items()},
            "slots": {k: round(v, 6) for k, v in self.slots.items()},
            "region_rank": list(self.region_rank),
            "tombstones": list(self.tombstones),
            "component_of": dict(self.component_of),
            "branch_roots": list(self.branch_roots),
            "membership_groups": list(self.membership_groups),
            "cells": {k: list(v) for k, v in self.cells.items()},
        }

    @classmethod
    def from_json(cls, data: Any) -> "Ordering":
        if not isinstance(data, dict):
            return cls()
        slots: dict[str, float] = {}
        for k, v in (data.get("slots") or {}).items():
            try:
                slots[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return cls(
            siblings={str(k): [str(x) for x in v]
                      for k, v in (data.get("siblings") or {}).items()
                      if isinstance(v, list)},
            slots=slots,
            region_rank=[str(x) for x in (data.get("region_rank") or [])],
            tombstones=[str(x) for x in (data.get("tombstones") or [])],
            component_of={str(k): str(v)
                          for k, v in (data.get("component_of") or {}).items()},
            branch_roots=[str(x) for x in (data.get("branch_roots") or [])],
            membership_groups=[str(x) for x
                               in (data.get("membership_groups") or [])],
            # `[row_pitch, columns, *column_widths]` — variable length, since
            # the column count is part of the record. A stored entry from the
            # fixed `[w, h, cols]` era has the wrong meaning rather than the
            # wrong length, which is what the sidecar version guards.
            cells={str(k): [float(x) for x in v]
                   for k, v in (data.get("cells") or {}).items()
                   if isinstance(v, list) and v},
        )

    def ordered_children(self, parent: str) -> list[str]:
        return list(self.siblings.get(parent or ROOT_KEY, ()))

    def needs_renormalise(self, minimum_gap: float = 1e-3) -> bool:
        """Has fractional insertion crushed a family's columns together?

        What this is looking for is *drift*: interpolating repeatedly into the
        same gap halves it each time (1, 0.5, 0.25, …) until two columns are too
        close to draw. That is the only way the arrangement can breach its own
        clearance floor.

        Two slots being **exactly equal** is not that, and must not be reported.
        Slots are column indices within the subtree they were handed out in, and
        every subtree numbers its own columns from zero — the boxes are
        normalised and packed apart afterwards, so two sole-leaf roots both
        holding 0.0 is the healthy case. Comparing raw sorted values globally
        called `True` on a two-node graph joined by a single NEARTO edge, and on
        any real graph with more than one subtree; the caller this was written
        for would have reshuffled the map on every rebuild.

        So: grouped by family, and a gap only counts when it is small **and
        non-zero**.
        """
        for members in self.siblings.values():
            ordered = sorted(self.slots[n] for n in members if n in self.slots)
            if any(0.0 < b - a < minimum_gap for a, b in zip(ordered, ordered[1:])):
                return True
        return False


def lift_to_siblings(pairs: Iterable[tuple[str, str]],
                     parent_of: dict[str, str]) -> dict[str, list[str]]:
    """Project cross edges onto the sibling lists they are visible in.

    An edge between two nodes deep in different subtrees says nothing about
    where either node sits among *its own* siblings — but it says a great deal
    about where those two subtrees should sit relative to each other. So each
    edge is lifted to the nearest level where both ends have distinct ancestors
    in one sibling list, and recorded as a relation between those two siblings.
    Edges spanning separate trees lift to `ROOT_KEY`, which is the list that
    decides packing-grid cells — and on `agreements`, cell assignment is where
    the crossings were.

    Returned adjacency is within-list by construction, which is the property
    that makes a barycentre meaningful at all: a member's index is only
    comparable to the indices of nodes ranked against the same origin. Relaxing
    against neighbours in *other* lists was measured and is worse than doing
    nothing (`rfc` 170 → 197 crossings).

    Repeated pairs are kept, not de-duplicated: two subtrees joined by six edges
    should pull six times as hard as one joined by a single edge.
    """
    def chain(node: str) -> list[str]:
        out, seen, cur = [], set(), node
        while cur and cur != ROOT_KEY and cur not in seen:
            seen.add(cur)
            out.append(cur)
            cur = parent_of.get(cur, ROOT_KEY)
        return out

    lifted: dict[str, list[str]] = {}
    for u, v in pairs:
        if u == v:
            continue
        chain_u = chain(u)
        depth_u = {nid: i for i, nid in enumerate(chain_u)}
        sib_u = sib_v = None
        previous = None
        for nid in chain(v):
            if nid in depth_u:                      # lowest common ancestor
                index = depth_u[nid]
                sib_u = chain_u[index - 1] if index else None
                sib_v = previous
                break
            previous = nid
        else:
            # Separate trees: the roots themselves are the siblings, and their
            # list is the one that assigns packing cells.
            sib_u = chain_u[-1] if chain_u else None
            sib_v = previous
        if sib_u and sib_v and sib_u != sib_v:
            lifted.setdefault(sib_u, []).append(sib_v)
            lifted.setdefault(sib_v, []).append(sib_u)
    return lifted


def _relax(seed: dict[str, list[str]],
           neighbours: dict[str, list[str]],
           pinned: set[str],
           rounds: int = BARYCENTRE_ROUNDS) -> dict[str, float]:
    """Median relaxation over position-within-family.

    Free members drift toward the median of their neighbours' positions; median
    rather than mean, as in the causal lens's sweeps, so one distant neighbour
    cannot drag a node across its family.

    **Pinned nodes never move.** A node already in the ledger has a position the
    operator has learned, and the map's whole contract is that learning it stays
    valid. So this decides the order of a *cold* layout and the insertion point
    of *newcomers*, and it is never allowed to re-sort a list that already
    exists. That is what keeps it compatible with the no-swaps invariant.

    Deterministic: seeded from sorted membership, iterated in sorted order, fixed
    round count.
    """
    x: dict[str, float] = {}
    for members in seed.values():
        for i, nid in enumerate(members):
            x[nid] = float(i)

    free = sorted(n for n in x if n not in pinned)
    if not free or not neighbours:
        return {}

    for _ in range(rounds):
        nxt = dict(x)
        for nid in free:
            values = sorted(x[m] for m in neighbours.get(nid, ()) if m in x)
            if not values:
                continue
            mid = len(values) // 2
            nxt[nid] = (values[mid] if len(values) % 2
                        else (values[mid - 1] + values[mid]) / 2.0)
        x = nxt
    return x


def _insert_by_hint(kept: list[str], newcomers: list[str],
                    hint: dict[str, float]) -> list[str]:
    """Place newcomers among the survivors without disturbing them.

    Survivors keep both their order and their relative positions; a newcomer
    lands before the first member that wants to sit to its right. Appending
    would have been simpler and is what this replaces — but appending puts a node
    at the edge of its family regardless of what it is connected to, which is
    how related material ended up in opposite corners of the packing grid.
    """
    if not newcomers:
        return kept
    out = list(kept)
    for nid in sorted(newcomers, key=lambda m: (hint.get(m, float("inf")), m)):
        want = hint.get(nid, float("inf"))
        index = len(out)
        for i, other in enumerate(out):
            if hint.get(other, float("-inf")) > want:
                index = i
                break
        out.insert(index, nid)
    return out


def cross_pairs_of(spine) -> list[tuple[str, str]]:
    """The edges the backbone does not express, as unordered pairs."""
    cross = getattr(spine, "cross_neighbours", {}) or {}
    return [(u, v) for u, mates in sorted(cross.items())
            for v in mates if u < v]


def hint_from(baseline: "Ordering", previous: "Ordering | None", spine,
              kind: str = "lifted") -> dict[str, float]:
    """Build a candidate barycentre hint against an already-reconciled baseline.

    The baseline supplies both the seed positions and the family structure, so
    the hint describes *where a newcomer would rather sit than the end of the
    list* — which is the only question it is allowed to answer.

    Two kinds, because the obvious one and the principled one disagree and only
    measurement settles it (`contract.choose_ordering` runs both):

    - `lifted` — cross edges projected onto the sibling list they are visible
      in, so subtrees are ordered by what connects them.
    - `adjacent` — plain median over a node's whole neighbourhood.
    """
    pinned = {nid for lst in (previous.siblings if previous else {}).values()
              for nid in lst}
    if kind == "adjacent":
        return _relax(baseline.siblings, getattr(spine, "neighbours", {}) or {},
                      pinned)
    parent_of = {nid: key for key, members in baseline.siblings.items()
                 for nid in members}
    lifted = lift_to_siblings(cross_pairs_of(spine), parent_of)
    return _relax(baseline.siblings, lifted, pinned)


def reconcile(previous: Ordering | None, spine, live_ids: set[str],
              order_hint: dict[str, float] | None = None) -> Ordering:
    """Fold the current topology into the previous ordering.

    The three rules, in the order they matter:

    1. **Survivors keep their index.** Anything present last time stays where it
       was in its sibling list.
    2. **Newcomers are placed** — appended in id order, or, when `order_hint` is
       supplied, inserted at the position it suggests. Either way a local
       insertion, never a renumbering.
    3. **Leavers become tombstones** and keep their slot, so ghosts have
       somewhere to render and survivors do not close ranks.

    A node that changes parent is treated as leaving one list and joining
    another; it moves, but nothing else does.

    `order_hint` is a *candidate*, not a decision. `contract.arrange` builds one
    ordering with it and one without, measures both, and keeps whichever draws
    better — see `choose_ordering`.
    """
    previous = previous or Ordering()

    current_parent = {nid: spine.parent.get(nid, ROOT_KEY)
                      for nid in sorted(live_ids)}

    wanted: dict[str, list[str]] = {}
    for nid, par in current_parent.items():
        wanted.setdefault(par, []).append(nid)

    siblings: dict[str, list[str]] = {}
    placed: set[str] = set()

    # 1 + 3: walk the previous lists, keeping survivors and tombstones in place.
    for parent_key, prev_list in previous.siblings.items():
        kept: list[str] = []
        for nid in prev_list:
            if nid in live_ids:
                if current_parent.get(nid) == parent_key:
                    kept.append(nid)
                    placed.add(nid)
                # else: reparented — appended under its new parent below
            else:
                kept.append(nid)  # tombstone: the slot is the point
        if kept:
            siblings[parent_key] = kept

    # 2: newcomers (and the reparented) join their family.
    for parent_key, members in wanted.items():
        newcomers = [n for n in sorted(members) if n not in placed]
        if order_hint is None:
            if newcomers:
                siblings.setdefault(parent_key, []).extend(newcomers)
            else:
                siblings.setdefault(parent_key, [])
        else:
            siblings[parent_key] = _insert_by_hint(
                siblings.get(parent_key, []), newcomers, order_hint)

    tombstones = sorted(
        {nid for lst in siblings.values() for nid in lst if nid not in live_ids}
    )

    component_of, region_rank = _reconcile_regions(previous, spine)

    # Carry slots forward for everything still on the board (tombstones
    # included — a ghost must appear where the node used to be). Nodes that
    # vanished from the ledger entirely drop their slot.
    keep = {nid for lst in siblings.values() for nid in lst}

    def _survives(key: str) -> bool:
        # Namespaced keys belong to a node but are not node ids, so a plain
        # membership test against `keep` discarded every one of them on every
        # reconcile — and a band member silently re-derived its cell from zero
        # each time. Found by the property tests on a four-node graph with no
        # edges.
        #
        # Matched against the declared prefixes rather than by splitting on the
        # first colon: real node ids contain colons too (a Wikipedia build uses
        # `wiki:en:article:Machine_learning`), and splitting would have thrown
        # away the slot of every node in such a graph.
        for prefix in SLOT_NAMESPACES:
            if key.startswith(prefix):
                return key[len(prefix):] in keep
        return key in keep

    slots = {k: v for k, v in previous.slots.items() if _survives(k)}

    return Ordering(siblings=siblings, slots=slots, region_rank=region_rank,
                    tombstones=tombstones, component_of=component_of,
                    membership_groups=[g for g in previous.membership_groups
                                       if g in live_ids],
                    branch_roots=[r for r in previous.branch_roots
                                  if r in live_ids],
                    cells=dict(previous.cells))


def _reconcile_regions(previous: Ordering, spine
                       ) -> tuple[dict[str, str], list[str]]:
    """Give each component a stable key, then a stable packing rank.

    A component is identified by *continuity of membership*, not by any property
    of the nodes inside it: whichever previous key most of its members carried
    is the key it keeps. That survives growth, shrinkage and merges, and it is
    what stops an added node from silently re-identifying a region the operator
    has already learned.

    New components rank biggest-first so the eye still lands on the main mass,
    but they never displace a component that was already on the board.
    """
    prev_rank = {cid: i for i, cid in enumerate(previous.region_rank)}

    component_of: dict[str, str] = {}
    sizes: dict[str, int] = {}
    claimed: set[str] = set()

    for comp in spine.components:
        votes: dict[str, int] = {}
        for nid in comp:
            old = previous.component_of.get(nid)
            if old and old not in claimed:
                votes[old] = votes.get(old, 0) + 1
        if votes:
            # Most members win; ties break on the older rank, then on the key.
            key = min(votes, key=lambda k: (-votes[k],
                                            prev_rank.get(k, len(prev_rank)), k))
        else:
            key = comp[0]
        claimed.add(key)
        for nid in comp:
            component_of[nid] = key
        sizes[key] = len(comp)

    survivors = [k for k in previous.region_rank if k in sizes]
    seen = set(survivors)
    newcomers = sorted((k for k in sizes if k not in seen),
                       key=lambda k: (-sizes[k], k))
    return component_of, survivors + newcomers


def band_order(ids: list[str], slots: dict[str, float]) -> list[str]:
    """Grid-band order (gap gutter, out-of-flow material), newcomers last.

    The bands are grids rather than trees, but they need the same guarantee, and
    two obvious orderings both fail it. Sorting by id lets a node whose id sorts
    early take the first cell and shift the entire band along. Walking the
    ledger's sibling lists is worse in a subtler way: it enumerates parents in
    sorted order, so a newcomer inherits its *parent's* early rank — which is
    what was still moving 15 of 30 nodes on the hexagonal-orders fixture after
    the trees had been stabilised.

    Slots are absolute, so members keep their cell and newcomers land at the end
    where they belong.

    Read and written under `band_key`, never under the node id: a node can be a
    leaf in one arrangement and a band member in another, and one slot cannot
    mean a column in a subtree and a cell in a grid at the same time. The node's
    own slot is still consulted as a fallback so a ledger written before the
    namespace existed keeps the order it already had.
    """
    def rank(n: str) -> tuple[float, str]:
        key = band_key(n)
        if key in slots:
            return (slots[key], n)
        return (slots.get(n, float("inf")), n)

    ordered = sorted(ids, key=rank)
    assign_slots([band_key(n) for n in ordered], slots)
    return ordered


def assign_slots(ordered_leaves: list[str], slots: dict[str, float]) -> None:
    """Give every leaf a fractional column, keeping known ones exactly put.

    New leaves are interpolated between the nearest known neighbours, so an
    insertion is local: nothing that already had a slot moves. Leaves before the
    first known slot count backwards, leaves after the last count forwards.

    Mutates `slots` in place — it is the ledger's own state.
    """
    if not ordered_leaves:
        return

    # Only strictly increasing anchors are usable. A node can carry a slot from
    # a position it no longer holds (it was reparented, or the causal layering
    # moved it), and interpolating between crossed anchors would place nodes on
    # top of each other. A stale anchor is dropped, not trusted.
    anchors: list[tuple[int, float]] = []
    for i, leaf in enumerate(ordered_leaves):
        if leaf not in slots:
            continue
        value = slots[leaf]
        if anchors and value <= anchors[-1][1]:
            del slots[leaf]
            continue
        anchors.append((i, value))

    if not anchors:
        for i, leaf in enumerate(ordered_leaves):
            slots[leaf] = float(i)
        return

    first_i, first_v = anchors[0]
    for j in range(first_i):
        slots[ordered_leaves[j]] = first_v - (first_i - j)

    for (ai, av), (bi, bv) in zip(anchors, anchors[1:]):
        count = bi - ai - 1
        if count <= 0:
            continue
        step = (bv - av) / (count + 1)
        for k in range(count):
            slots[ordered_leaves[ai + 1 + k]] = av + step * (k + 1)

    last_i, last_v = anchors[-1]
    for j in range(last_i + 1, len(ordered_leaves)):
        slots[ordered_leaves[j]] = last_v + (j - last_i)


def band_cell(cell: float, columns: int, gap_rows: float,
              col_width: float, row_height: float) -> tuple[float, float]:
    """Where a band member sits: a fixed lane above the origin, growing upward.

    Bands used to sit *below* the graph, which made their top a function of the
    graph's height — so every orphan slid down a row whenever any tree above it
    grew one. The band kept its internal arrangement, but an operator watching
    the tray move each time an unrelated subtree deepened is being asked to
    re-find it. Found by the property tests, on four nodes and no edges.

    Above the origin, the band is anchored to nothing that grows: the graph
    extends downward, the band extends upward, and neither reaches the other.
    Row 0 sits nearest the graph so the reading order is still top-down.
    """
    col, row = cell % columns, cell // columns
    return (col * col_width, -(gap_rows + row) * row_height)
