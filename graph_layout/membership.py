"""The membership lens — arranged for the question "who belongs to what?".

Some graphs are not hierarchies wearing a disguise, they are **bipartite**: a
crowd of members that each point into a handful of groups. `agreements` is 23
countries against 8 organisations, and its shape defeats every arrangement built
on a spine, because a spine has to pick *one* parent per node and a country
belongs to four organisations at once. The other three memberships become
off-spine edges flying across the map — 84% of that graph's edges — and no
amount of sibling reordering fixes a model that is wrong. Canonical gets it to
97 crossings by sorting well; nothing it can do gets it near zero, because the
crossings are not a sorting problem.

So this lens throws the tree away and draws the bipartition directly.

**Groups sit on a ring; every member sits at the centre of gravity of the groups
it belongs to.** Distance therefore *means* something: a country in one
organisation sits beside it, a country in three sits in the middle of those
three, and countries with the same commitments end up neighbours without anyone
sorting them. Reading the map is reading the memberships.

That geometry was arrived at by measurement, after two others failed. The
textbook bipartite drawing — members on one rank, groups on another — lands at
**186 crossings** on `agreements` and cannot do better: swapping barycentre for
median, for lexicographic membership signatures, or for signature-then-degree
moved it between 186 and 188, so the ordering was never the problem. Wrapping
the member rank into a block to fix its 27:1 aspect made it worse still (322 to
387), because every edge from the top row then crosses every row beneath it. The
ring draws the same graph at **32 crossings** against canonical's 97, at an
aspect of 1.12 — and compactly enough that the client's fit no longer bottoms
out, so it is drawn at 105px between node centres where canonical gets 62px.

**Nodes land on a lattice of `MIN_CLEARANCE` cells, nearest free cell first.**
A centroid is a wish, not a position: members that belong to the same groups want
the identical point. Snapping to a shared lattice — groups included, claimed
first — is what turns the wish into a drawing that keeps the spacing guarantee
the rest of the layout makes.

**Existing members claim cells before newcomers.** Placement runs in ledger
order, so an arriving member takes a free cell near its own centroid instead of
displacing anyone.

Offered only to graphs that actually have this shape — see `membership_applies`.
A lens with nothing to say is worse than a missing lens.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from graph_layout.contract import (
    COL_WIDTH,
    MIN_CLEARANCE,
    ROW_HEIGHT,
    Arrangement,
)
from graph_layout.ordering import (
    BARYCENTRE_ROUNDS, Ordering, assign_slots, band_key, band_order)

#: Columns in the out-of-flow lane above the ring.
GUTTER_COLUMNS = 12

#: Edges of this type never imply membership. Similarity is not belonging.
IGNORED_TYPES = frozenset({"NEARTO"})
#: Incoming edges before a node is treated as a group rather than a member.
#: Two is too few — an ordinary tree node has two children and would qualify,
#: which would classify half of a hierarchy as groups and draw nonsense.
GROUP_MIN_INDEGREE = 3
#: Clear air between the member block and the group rank.
GROUP_GAP_ROWS = 2.0
#: Share of a graph's edges that must run member → group before the bipartite
#: reading is the honest one. Measured: `agreements` is 0.90, and the two graphs
#: that must *not* get this lens sit well below — `lotr` at 0.46 (one guild plus
#: a lot of ordinary story structure) and `hexagonal_governance` near zero,
#: since its hubs are sources, which is a hierarchy and canonical's business.
MEMBERSHIP_EDGE_SHARE = 0.6


def classify(node_ids: list[str], edges: list[dict[str, Any]],
             sticky: Iterable[str] = ()):
    """Split into `(groups, members, memberships)`.

    A group is a node that many edges *arrive* at and few leave. That asymmetry
    is the whole signal, and it is what separates this shape from an ordinary
    hierarchy: a tree's hubs are sources — a parent points at its children —
    while a membership graph's hubs are sinks, because belonging is asserted by
    the member, once per membership.

    `sticky` names groups the ledger already recorded, and they are held to a
    weaker test: enough members to still be a group, without having to keep
    winning the in-versus-out comparison. That comparison is a knife edge, and
    the property tests found the consequence on a five-node graph — giving a
    group one more child tipped it to the member side and redrew everything.
    Structure that flips back and forth is not structure.
    """
    known = set(node_ids)
    incoming: dict[str, set[str]] = {}
    outgoing: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("type") in IGNORED_TYPES:
            continue
        source, target = edge.get("source"), edge.get("target")
        if source not in known or target not in known or source == target:
            continue
        incoming.setdefault(target, set()).add(source)
        outgoing.setdefault(source, set()).add(target)

    remembered = set(sticky)
    groups = sorted(
        nid for nid in node_ids
        if len(incoming.get(nid, ())) >= GROUP_MIN_INDEGREE
        and (nid in remembered
             or len(incoming.get(nid, ())) > len(outgoing.get(nid, ())))
    )
    group_set = set(groups)

    memberships = {
        nid: sorted(group_set & outgoing.get(nid, set()))
        for nid in node_ids
        if nid not in group_set and (group_set & outgoing.get(nid, set()))
    }
    return groups, sorted(memberships), memberships


def membership_applies(node_ids: list[str], edges: list[dict[str, Any]]) -> bool:
    """Is the bipartite reading the honest one for this graph?"""
    groups, members, memberships = classify(node_ids, edges)
    if not groups or len(groups) >= len(members) or len(members) < 3:
        return False
    counted = [e for e in edges if e.get("type") not in IGNORED_TYPES]
    if not counted:
        return False
    spanning = sum(len(v) for v in memberships.values())
    return spanning / len(counted) >= MEMBERSHIP_EDGE_SHARE


def membership_lens(node_ids: list[str],
                    edges: list[dict[str, Any]],
                    spine,
                    ordering: Ordering,
                    facts: dict[str, dict[str, Any]],
                    shape: dict[str, Any] | None = None) -> Arrangement:
    placeable = sorted(set(node_ids) | set(ordering.tombstones))
    groups, members, memberships = classify(placeable, edges,
                                            ordering.membership_groups)
    # Record before drawing, so the decision survives into the next rebuild.
    for gid in groups:
        if gid not in ordering.membership_groups:
            ordering.membership_groups.append(gid)
    placed = set(groups) | set(members)
    outside = [nid for nid in placeable if nid not in placed]

    if not groups or not members:
        # Nothing bipartite to draw. Everything is out-of-flow, and the notes
        # say so rather than the map pretending it arranged something.
        return _all_outside(placeable, spine, ordering)

    members_of: dict[str, list[str]] = {g: [] for g in groups}
    for member, belongs in memberships.items():
        for group in belongs:
            members_of[group].append(member)

    # Seeded from the ledger, never from ids: the ring order is only as stable
    # as its starting order, and seeding from ids lets an unrelated commit
    # reshuffle the whole diagram.
    member_order = band_order(members, ordering.slots)
    group_order = band_order(groups, ordering.slots)

    # Groups that share members go next to each other on the ring, so a member
    # held in common sits between them instead of across the middle.
    for _round in range(BARYCENTRE_ROUNDS):
        index = {g: i for i, g in enumerate(group_order)}
        group_order.sort(key=lambda g: (_ring_affinity(g, group_order, index,
                                                       members_of), g))

    assign_slots([band_key(n) for n in member_order], ordering.slots)
    assign_slots([band_key(n) for n in group_order], ordering.slots)

    lattice = _Lattice()
    radius = _ring_radius(len(group_order), len(member_order))
    for i, gid in enumerate(group_order):
        angle = 2.0 * math.pi * i / len(group_order) - math.pi / 2.0
        lattice.claim(gid, radius * math.cos(angle), radius * math.sin(angle))

    for nid in member_order:
        belongs = memberships[nid]
        lattice.claim(nid,
                      _mean(lattice.at(g)[0] for g in belongs),
                      _mean(lattice.at(g)[1] for g in belongs))

    positions: dict[str, tuple[float, float]] = dict(lattice.positions)

    if outside:
        # The out-of-flow lane sits above the ring, anchored to nothing that
        # grows — see `ordering.band_cell`.
        from graph_layout.ordering import band_cell

        top = min((y for _x, y in positions.values()), default=0.0)
        lane = band_order(outside, ordering.slots)
        for nid in lane:
            cell = ordering.slots.get(band_key(nid), 0.0)
            x, y = band_cell(cell, GUTTER_COLUMNS, GROUP_GAP_ROWS,
                             COL_WIDTH, ROW_HEIGHT)
            positions[nid] = (x, top + y)

    primary = {m: (belongs[0] if belongs else "")
               for m, belongs in memberships.items()}
    regions = {
        nid: {
            # A member's region is the group it belongs to first, which gives
            # the client something real to tint by; a group is its own region.
            "region_id": nid if nid in members_of else primary.get(nid, ""),
            "depth": 1 if nid in members_of else 0,
            "component_id": spine.component_id.get(nid, ""),
            "branch_id": "" if nid in members_of else primary.get(nid, ""),
        }
        for nid in placeable
    }

    return Arrangement(
        positions={k: (round(x, 2), round(y, 2))
                   for k, (x, y) in positions.items()},
        regions=regions,
        gutter=sorted(outside),
        notes=(f"{len(members)} members across {len(groups)} groups, "
               f"{len(outside)} outside"),
    )


def _all_outside(placeable, spine, ordering: Ordering) -> Arrangement:
    from graph_layout.ordering import band_cell

    lane = band_order(list(placeable), ordering.slots)
    positions = {}
    for nid in lane:
        cell = ordering.slots.get(band_key(nid), 0.0)
        positions[nid] = band_cell(cell, 12, GROUP_GAP_ROWS,
                                   COL_WIDTH, ROW_HEIGHT)
    return Arrangement(
        positions={k: (round(x, 2), round(y, 2))
                   for k, (x, y) in positions.items()},
        regions={nid: {"region_id": "", "depth": 0,
                       "component_id": spine.component_id.get(nid, ""),
                       "branch_id": ""}
                 for nid in placeable},
        gutter=sorted(placeable),
        notes="no membership structure found",
    )


class _Lattice:
    """Positions on a `MIN_CLEARANCE` grid, nearest free cell to what was asked.

    Every node in this lens wants a point that something else may also want: a
    centroid is shared by every member with the same commitments, and two
    adjacent ring positions can round to one cell. Snapping to a grid whose
    pitch *is* the clearance guarantee turns "near here" into a position while
    keeping the promise the rest of the layout makes — orthogonal neighbours land
    exactly `MIN_CLEARANCE` apart and diagonals further, so nothing can be drawn
    inside another node.

    First claim wins, which is why callers claim in ledger order: an existing
    node keeps the cell it had and a newcomer settles beside it.
    """

    def __init__(self) -> None:
        self.positions: dict[str, tuple[float, float]] = {}
        self._taken: set[tuple[int, int]] = set()

    def at(self, node_id: str) -> tuple[float, float]:
        return self.positions[node_id]

    def claim(self, node_id: str, x: float, y: float) -> None:
        want = (x / MIN_CLEARANCE, y / MIN_CLEARANCE)
        best: tuple[float, tuple[int, int]] | None = None
        radius = 0
        while best is None:
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue          # only the shell, inner rings are done
                    cell = (round(want[0]) + dx, round(want[1]) + dy)
                    if cell in self._taken:
                        continue
                    distance = (cell[0] - want[0]) ** 2 + (cell[1] - want[1]) ** 2
                    # Ties broken on the cell itself so the result cannot depend
                    # on iteration order across machines.
                    if best is None or (distance, cell) < (best[0], best[1]):
                        best = (distance, cell)
            radius += 1
        self._taken.add(best[1])
        self.positions[node_id] = (best[1][0] * MIN_CLEARANCE,
                                   best[1][1] * MIN_CLEARANCE)


def _ring_radius(group_count: int, member_count: int) -> float:
    """Big enough for the groups to sit apart and the members to fit inside.

    Swept on `agreements`: 3x clearance gave 36 crossings, 4x gave 28, and 5x
    and beyond went back to 31 as the ring outgrew its own members and their
    centroids stopped landing between the groups they belong to.
    """
    for_groups = group_count * 0.5
    for_members = math.sqrt(max(member_count, 1)) * 0.8
    return max(2.5, for_groups, for_members) * MIN_CLEARANCE


def _ring_affinity(group: str, order: list[str], index: dict[str, int],
                   members_of: dict[str, list[str]]) -> float:
    """Mean ring position of the groups this one shares members with."""
    mine = set(members_of.get(group, ()))
    shared = [index[other] for other in order
              if other != group and mine & set(members_of.get(other, ()))]
    return _mean(shared) if shared else float(index.get(group, 0))


def _mean(values) -> float:
    seq = list(values)
    return sum(seq) / len(seq) if seq else 0.0
