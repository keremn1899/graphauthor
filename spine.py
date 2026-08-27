"""The backbone of an SST graph — derived once, shared by roles and layout.

This existed twice and differently: `engine._find_contains_subtrees` (CONTAINS
only, feeding `inter_region_bridge` detection) and `graph_read._spanning_forest`
(CONTAINS then LEADSTO, cycle-broken, feeding layout). A node's role and its
position could therefore be computed against two different structures inside the
same payload.

Both live here now, deliberately as **two functions rather than one**:

- `contains_subtrees` is an exact port of the engine's derivation. Role
  semantics are load-bearing across the whole verdict pipeline, so unifying the
  *implementation* must not change the *definition* of a region for roles.
- `derive` is the layout backbone: CONTAINS is the hierarchy of an SST graph
  where present, LEADSTO is the backbone where it is not, and EXPRESSES/NEARTO
  attach leaves but never define depth.

No database access here — callers pass plain records, so this is trivially
testable and usable from either side.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

# Which edge type gets to claim a node as its child. CONTAINS is the hierarchy
# of an SST graph; LEADSTO carries causal chains where no containment exists.
# NEARTO is undirected similarity and never defines a parent.
PARENT_PRIORITY = {"CONTAINS": 0, "LEADSTO": 1, "EXPRESSES": 2}


@dataclass(frozen=True)
class Spine:
    """The derived backbone. `region_id` is the root of a node's spine tree."""

    parent: dict[str, str]
    children: dict[str, list[str]]
    depth: dict[str, int]
    region_id: dict[str, str]
    roots: list[str]
    #: Weak components over *all* edge types — the unit that gets packed, so
    #: that connected material is never split across the canvas.
    component_id: dict[str, str]
    components: list[list[str]] = field(default_factory=list)
    #: Degree over all edge types, for gap detection.
    degree: dict[str, int] = field(default_factory=dict)
    #: Every neighbour over every edge type, undirected. Sorted lists, not sets:
    #: iteration order is part of the layout's determinism guarantee.
    neighbours: dict[str, list[str]] = field(default_factory=dict)
    #: Neighbours the backbone does **not** already express — everything except a
    #: node's own spine parent and spine children.
    #:
    #: This is the set the layout is blind to. The backbone keeps one parent per
    #: node, so on the `agreements` corpus 41 of 49 edges influence nothing, and
    #: 164 of that map's 175 crossings are those ignored edges crossing each
    #: other. It is kept separate from `neighbours` because ordering siblings by
    #: the *whole* adjacency measured worse, not better: on a pure tree every
    #: neighbour is already a spine relation, so the signal is entirely noise and
    #: it reshuffled a crossing-free `rfc` layout into 197 crossings. Geometry
    #: comes from the spine; ordering may only consult what the spine omits.
    cross_neighbours: dict[str, list[str]] = field(default_factory=dict)

    def isolated(self) -> list[str]:
        """Nodes no edge touches. `structural_gaps` in compass terms."""
        return sorted(n for n, d in self.degree.items() if d == 0)


def contains_subtrees(out_adj: dict[str, dict[str, list[str]]]) -> dict[str, int]:
    """Assign each node to a CONTAINS subtree root (for bridge detection).

    Exact port of the engine's original derivation, kept byte-for-byte in
    behaviour: a node only appears here if CONTAINS touches it, roots are the
    CONTAINS-parentless, and indices come from `enumerate(sorted(roots))`.
    Changing any of that would silently move `inter_region_bridge` roles.

    Note the adjacency here uses the engine's lowercase SST keys.
    """
    has_contains_parent: set[str] = set()
    all_contains_nodes: set[str] = set()

    for node, type_map in out_adj.items():
        children = type_map.get("contains", [])
        for child in children:
            has_contains_parent.add(child)
            all_contains_nodes.add(child)
        if children:
            all_contains_nodes.add(node)

    roots = all_contains_nodes - has_contains_parent

    subtree_map: dict[str, int] = {}
    for i, root in enumerate(sorted(roots)):
        queue = deque([root])
        while queue:
            node = queue.popleft()
            if node in subtree_map:
                continue
            subtree_map[node] = i
            for child in out_adj.get(node, {}).get("contains", []):
                queue.append(child)

    return subtree_map


def derive(node_ids: Iterable[str], edges: Iterable[dict[str, Any]]) -> Spine:
    """The layout backbone: a deterministic forest plus weak components.

    Deterministic in the strong sense — same graph in, same structure out, on
    any machine and in any process. Layout inherits that, which is the whole
    reason it is computed here rather than in a browser.
    """
    known = set(node_ids)
    ordered_ids = sorted(known)

    best_parent: dict[str, tuple[int, str]] = {}
    adjacency: dict[str, set[str]] = {nid: set() for nid in ordered_ids}
    degree: dict[str, int] = dict.fromkeys(ordered_ids, 0)

    for e in edges:
        s, t = e["source"], e["target"]
        if s not in known or t not in known or s == t:
            continue
        adjacency[s].add(t)
        adjacency[t].add(s)
        degree[s] += 1
        degree[t] += 1
        etype = e["type"]
        if etype not in PARENT_PRIORITY:
            continue  # NEARTO: similarity, not hierarchy
        rank = PARENT_PRIORITY[etype]
        cur = best_parent.get(t)
        if cur is None or (rank, s) < cur:
            best_parent[t] = (rank, s)

    parent = {child: p for child, (_rank, p) in best_parent.items()}

    # A node that reaches itself through parents loses its parent, so the
    # backbone is always a forest. Sorted iteration keeps the choice stable.
    for nid in sorted(parent):
        seen, cur = {nid}, parent.get(nid)
        while cur is not None:
            if cur in seen:
                parent.pop(nid, None)
                break
            seen.add(cur)
            cur = parent.get(cur)

    children: dict[str, list[str]] = {}
    for child, p in parent.items():
        children.setdefault(p, []).append(child)
    for kids in children.values():
        kids.sort()

    roots = [nid for nid in ordered_ids if nid not in parent]

    depth: dict[str, int] = {}
    region_id: dict[str, str] = {}
    for root in roots:
        stack = [(root, 0)]
        while stack:
            nid, d = stack.pop()
            if nid in depth:
                continue
            depth[nid] = d
            region_id[nid] = root
            for kid in children.get(nid, ()):
                stack.append((kid, d + 1))

    components = _weak_components(ordered_ids, adjacency)
    component_id: dict[str, str] = {}
    for comp in components:
        head = comp[0]
        for nid in comp:
            component_id[nid] = head

    return Spine(
        parent=parent,
        children=children,
        depth=depth,
        region_id=region_id,
        roots=roots,
        component_id=component_id,
        components=components,
        degree=degree,
        neighbours={nid: sorted(adjacency[nid]) for nid in ordered_ids},
        cross_neighbours={
            nid: sorted(adjacency[nid]
                        - {parent.get(nid)}
                        - set(children.get(nid, ())))
            for nid in ordered_ids
        },
    )


def _weak_components(node_ids: list[str],
                     adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Weak components, biggest first so the eye lands on the main mass."""
    seen: set[str] = set()
    comps: list[list[str]] = []
    for nid in node_ids:
        if nid in seen:
            continue
        stack, comp = [nid], []
        seen.add(nid)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in sorted(adjacency.get(cur, ())):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c[0]))
    return comps
