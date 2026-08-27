"""Properties of the pure core, over generated graphs rather than fixtures.

The spine, the ordering ledger, the lenses and the overlay are all pure
functions, and every one of them is currently guarded by hand-written fixtures —
a chain, a star, twenty roots. Fixtures test the shapes someone thought of. Each
stability defect this codebase has had was a shape nobody thought of: a
low-sorting id that renamed a component, a subtree that grew and re-pitched a
grid, a reparented node carrying a stale slot into a crossed anchor.

These assert the invariants over a couple of hundred generated graphs including
orphans, cycles, multi-parent nodes and NEARTO-only nodes, and shrink any
failure to something readable.

Deterministic: seeded generation, pure functions, no database, no LLM.
"""

from __future__ import annotations

import math

import pytest

import spine as spine_mod
from graph_layout.contract import arrange
from tests.property_tools import Graph, assert_property, generate

LENSES = ("canonical", "causal", "membership")


def _no_line_swaps(before, after, nodes) -> bool:
    """No two nodes sharing a line trade places left-to-right.

    Restricted to nodes drawn on the same y in *both* arrangements, because that
    is the only place horizontal order carries meaning. A rescale — every grid
    cell widening because one subtree outgrew its box — keeps lines intact and
    passes; a reshuffle does not.
    """
    lines: dict[tuple[float, float], list[str]] = {}
    for n in nodes:
        lines.setdefault((before.positions[n][1], after.positions[n][1]),
                         []).append(n)
    for group in lines.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                was = before.positions[a][0] - before.positions[b][0]
                now = after.positions[a][0] - after.positions[b][0]
                if was * now < 0:              # strict sign flip: they swapped
                    return False
    return True


# ------------------------------------------------------------------- spine


def test_the_spine_is_always_a_forest():
    """Cycle-breaking is what makes depth computable. A cycle here means the
    tidy-tree walk never terminates."""
    def holds(g: Graph) -> bool:
        sp = spine_mod.derive(g.ids, g.edge_dicts())
        for nid in g.ids:
            seen, cur = {nid}, sp.parent.get(nid)
            while cur is not None:
                if cur in seen:
                    return False
                seen.add(cur)
                cur = sp.parent.get(cur)
        return True

    assert_property(holds, "the spine contains a cycle")


def test_every_node_gets_a_depth_and_a_region():
    """A node with no depth cannot be placed, and one with no region cannot be
    packed — both would silently vanish from the map."""
    def holds(g: Graph) -> bool:
        sp = spine_mod.derive(g.ids, g.edge_dicts())
        return all(n in sp.depth and n in sp.region_id for n in g.ids)

    assert_property(holds, "a node has no depth or no region")


def test_nearto_never_defines_a_parent():
    """Similarity is not hierarchy. If NEARTO could parent, the backbone would
    reshuffle whenever an unrelated similarity edge appeared."""
    def holds(g: Graph) -> bool:
        sp = spine_mod.derive(g.ids, g.edge_dicts())
        directed = {(s, t) for s, t, k in g.edges if k != "NEARTO"}
        return all((parent, child) in directed
                   for child, parent in sp.parent.items())

    assert_property(holds, "a NEARTO edge defined a parent")


def test_contains_outranks_leadsto_for_parenthood():
    def holds(g: Graph) -> bool:
        sp = spine_mod.derive(g.ids, g.edge_dicts())
        contains_parents = {t: s for s, t, k in g.edges if k == "CONTAINS"}
        for child, parent in sp.parent.items():
            if child in contains_parents:
                # some CONTAINS edge exists into this child, so its parent must
                # be a CONTAINS source
                sources = {s for s, t, k in g.edges
                           if k == "CONTAINS" and t == child}
                if parent not in sources:
                    return False
        return True

    assert_property(holds, "LEADSTO outranked CONTAINS as a parent")


def test_the_spine_is_deterministic():
    """Same graph in, same structure out — the property the persisted layout
    depends on across machines and processes."""
    def holds(g: Graph) -> bool:
        a = spine_mod.derive(g.ids, g.edge_dicts())
        b = spine_mod.derive(g.ids, g.edge_dicts())
        return (a.parent == b.parent and a.depth == b.depth
                and a.component_id == b.component_id)

    assert_property(holds, "the spine is not deterministic")


# ------------------------------------------------------------------ lenses


@pytest.mark.parametrize("lens", LENSES)
def test_every_node_is_placed_exactly_once(lens):
    """A node absent from the arrangement is a node the operator cannot see."""
    def holds(g: Graph) -> bool:
        arrangement, _o, _l = arrange(lens, list(g.ids), g.edge_dicts())
        return all(n in arrangement.positions for n in g.ids)

    assert_property(holds, f"{lens}: a node was not placed")


@pytest.mark.parametrize("lens", LENSES)
def test_no_two_nodes_land_on_the_same_point(lens):
    """Overlap is the one hard failure of a layout: two nodes on one point are
    indistinguishable, so one of them is invisible."""
    def holds(g: Graph) -> bool:
        arrangement, _o, _l = arrange(lens, list(g.ids), g.edge_dicts())
        placed = [arrangement.positions[n] for n in g.ids
                  if n in arrangement.positions]
        return len(set(placed)) == len(placed)

    assert_property(holds, f"{lens}: two nodes share a position")


@pytest.mark.parametrize("lens", LENSES)
def test_no_two_nodes_are_drawn_closer_than_a_node(lens):
    """Distinct positions are not enough — nodes have a size.

    `test_no_two_nodes_land_on_the_same_point` only rules out an exact tie, so
    two nodes a graph unit apart passed it while overlapping completely on
    screen. The arrangement's real guarantee is `MIN_CLEARANCE` (220 units, 3.5
    node diameters), and this is what holds it: the pitch is only a floor if
    nothing is ever allowed to sit inside it.

    Stated against `NODE_DIAMETER` rather than against the pitch, so the test
    keeps meaning what it says if the pitch is ever tuned.
    """
    from graph_layout.contract import NODE_DIAMETER

    def holds(g: Graph) -> bool:
        arrangement, _o, _l = arrange(lens, list(g.ids), g.edge_dicts())
        placed = sorted(arrangement.positions.items())
        for i, (_a, (ax, ay)) in enumerate(placed):
            for _b, (bx, by) in placed[i + 1:]:
                if math.hypot(ax - bx, ay - by) < NODE_DIAMETER:
                    return False
        return True

    assert_property(holds, f"{lens}: two nodes are drawn on top of each other")


def test_a_family_never_crushes_its_own_columns():
    """Fractional slots are the one way the clearance floor could be breached:
    repeated insertion into the same gap halves it each time. `needs_renormalise`
    is the detector, and it is only useful if it stays quiet when nothing is
    wrong — compared globally it fired on any graph with two subtrees, because
    every family numbers its columns from zero."""
    def holds(g: Graph) -> bool:
        _a, ordering, _l = arrange("canonical", list(g.ids), g.edge_dicts())
        return not ordering.needs_renormalise()

    assert_property(holds, "a fresh arrangement already wants renormalising")


@pytest.mark.parametrize("lens", LENSES)
def test_arrangement_is_deterministic(lens):
    def holds(g: Graph) -> bool:
        first, _o, _l = arrange(lens, list(g.ids), g.edge_dicts())
        second, _o2, _l2 = arrange(lens, list(g.ids), g.edge_dicts())
        return first.positions == second.positions

    assert_property(holds, f"{lens}: the arrangement is not deterministic")


@pytest.mark.parametrize("lens", LENSES)
def test_adding_a_node_leaves_most_of_the_map_alone(lens):
    """The property the map exists for. Fixtures cover a chain and a star; this
    covers whatever the generator produces, including the shapes that broke
    stability before.

    The bound is proportional, not absolute: ancestors re-centring over a
    widened child span is honest movement, and a small graph has proportionally
    more ancestors.

    **One exception, and it must prove itself.** When a root crosses
    `BRANCH_FAN_MIN` children it stops being laid out as a tidy tree and becomes
    packed regional branches — a different algorithm, so the component really
    does move. That is allowed here only on the step that records a new branch
    root in the ledger. Since the record is one-way, it can fire at most once per
    root: a genuine transition passes, an oscillation fails.
    """
    def holds(g: Graph) -> bool:
        ids = list(g.ids)
        edges = g.edge_dicts()
        first, ordering, _l = arrange(lens, ids, edges)
        before_modes = set(ordering.branch_roots)

        # attach to an existing node so the insertion is local, and give the
        # newcomer an id that sorts before everything
        anchor = sorted(ids)[0]
        grown = ids + ["aaa_new"]
        grown_edges = edges + [{"source": anchor, "target": "aaa_new",
                                "type": "CONTAINS", "label": ""}]
        second, after, _l2 = arrange(lens, grown, grown_edges, ordering=ordering)

        if set(after.branch_roots) - before_modes:
            return True                       # a recorded, one-time transition

        moved = sum(1 for n in ids
                    if second.positions.get(n) != first.positions.get(n))
        return moved <= max(3, len(ids) // 2)

    assert_property(holds, f"{lens}: adding one node moved too much of the map")


@pytest.mark.parametrize("lens", LENSES)
def test_adding_a_node_never_makes_two_nodes_swap(lens):
    """The stronger stability claim, and the one the operator actually relies on.

    Distance moved is a poor measure on its own: it cannot tell a *rescale* —
    every box translating because a grid cell grew, with nobody changing cell or
    neighbour — from a *reshuffle*, where two nodes trade places. The first
    leaves the map you learned intact and slightly wider. The second means what
    you learned is wrong.

    So assert the thing that matters: **two nodes drawn on the same line never
    swap left-to-right.** A shared line is where horizontal order is a reading
    order the operator learns. Anywhere else it is not a rank at all — a parent's
    x is a centroid over its children, and two roots in different rows of the
    packing grid have no left-to-right relationship to preserve. Both move for
    honest reasons that say nothing about where anyone's neighbours sit.

    A node crossing between the gutter and the graph is exempt — it changed
    category, which is a fact about that node rather than a reshuffle of the map
    — as is a recorded branch transition.
    """
    def holds(g: Graph) -> bool:
        ids = list(g.ids)
        edges = g.edge_dicts()
        first, ordering, _l = arrange(lens, ids, edges)
        before_modes = set(ordering.branch_roots)

        anchor = sorted(ids)[0]
        grown_edges = edges + [{"source": anchor, "target": "aaa_new",
                                "type": "CONTAINS", "label": ""}]
        second, after, _l2 = arrange(lens, ids + ["aaa_new"], grown_edges,
                                     ordering=ordering)

        if set(after.branch_roots) - before_modes:
            return True

        crossed = set(first.gutter) ^ set(second.gutter)
        stayed = [n for n in ids
                  if n not in crossed
                  and n in first.positions and n in second.positions]

        return _no_line_swaps(first, second, stayed)

    assert_property(holds, f"{lens}: two nodes swapped places when one was added")


@pytest.mark.parametrize("lens", LENSES)
def test_peer_order_survives_a_run_of_commits(lens):
    """The same claim over a *sequence*, on graphs big enough to re-pitch.

    One addition is not the test that matters — an operator adds nodes for
    weeks. The discontinuities in this layout are threshold-crossings, and a
    single-step probe on a small graph steps over most of them: measured on the
    31-node `agreements` fixture, the first three additions moved almost nothing
    and the fourth moved 1197 units, when a subtree finally outgrew its grid
    cell and every cell was re-pitched.

    That re-pitch is a rescale, not a reshuffle — which is exactly why peer
    order is the invariant asserted here and total distance is not.
    """
    def holds(g: Graph) -> bool:
        ids = list(g.ids)
        edges = g.edge_dicts()
        prev, ordering, _l = arrange(lens, ids, edges)
        anchor = sorted(ids)[0]

        for step in range(6):
            newcomer = f"aaa_new{step}"
            modes = set(ordering.branch_roots)
            ids = ids + [newcomer]
            edges = edges + [{"source": anchor, "target": newcomer,
                              "type": "CONTAINS", "label": ""}]
            cur, ordering, _l2 = arrange(lens, ids, edges, ordering=ordering)

            if not set(ordering.branch_roots) - modes:
                crossed = set(prev.gutter) ^ set(cur.gutter)
                survivors = [n for n in prev.positions
                             if n not in crossed and n in cur.positions]
                if not _no_line_swaps(prev, cur, survivors):
                    return False
            prev = cur
        return True

    assert_property(holds, f"{lens}: peers swapped during a run of commits",
                    seeds=range(60), max_nodes=40)


def test_branch_packing_never_reverses():
    """The exception above is only tolerable because it cannot repeat.

    Branch packing is chosen on a child-count threshold, and the two sides of
    that threshold are different layout algorithms. If the choice tracked the
    current count, a root sitting on the boundary would re-lay its whole
    component every time a child arrived or left — the same reshuffle, forever.
    One-way is what turns that into a single transition.
    """
    def holds(g: Graph) -> bool:
        ids = list(g.ids)
        edges = g.edge_dicts()
        _a, ordering, _l = arrange("canonical", ids, edges)

        anchor = sorted(ids)[0]
        grown_edges = edges + [{"source": anchor, "target": "aaa_new",
                                "type": "CONTAINS", "label": ""}]
        _b, after, _l2 = arrange("canonical", ids + ["aaa_new"], grown_edges,
                                 ordering=ordering)
        earned = set(after.branch_roots)

        # now take the newcomer away again: the mode must not fall back
        _c, back, _l3 = arrange("canonical", ids, edges, ordering=after)
        return earned & set(ids) <= set(back.branch_roots)

    assert_property(holds, "branch packing reverted when a child was removed")


# ----------------------------------------------------------------- overlay


def test_an_overlay_never_carries_geometry():
    """The contract that makes focus non-destructive. If an overlay could
    express a position it could fight the arrangement."""
    import graph_overlay

    def holds(g: Graph) -> bool:
        known = set(g.ids)
        lit = sorted(known)[:max(1, len(known) // 2)]
        overlay = graph_overlay.evidence_overlay(
            {"node_ids": lit}, g.edge_dicts(), [], known)
        blob = repr(overlay)
        return not any(k in blob for k in ("'x'", '"x"', "'y'", '"y"'))

    assert_property(holds, "an overlay carried geometry")


def test_an_overlay_only_names_nodes_that_exist():
    """A role on an id the map does not contain is a highlight with nowhere to
    land."""
    import graph_overlay

    def holds(g: Graph) -> bool:
        known = set(g.ids)
        claimed = sorted(known)[:2] + ["ghost_from_another_graph"]
        overlay = graph_overlay.evidence_overlay(
            {"node_ids": claimed}, g.edge_dicts(), [], known)
        return set(overlay["nodes"]) <= known

    assert_property(holds, "an overlay named a node outside the map")


def test_overlay_roles_stay_in_the_declared_vocabulary():
    import graph_overlay

    def holds(g: Graph) -> bool:
        known = set(g.ids)
        lit = sorted(known)[:max(1, len(known) // 2)]
        overlay = graph_overlay.evidence_overlay(
            {"node_ids": lit}, g.edge_dicts(), [], known)
        return set(overlay["nodes"].values()) <= set(graph_overlay.NODE_ROLES)

    assert_property(holds, "an overlay used a role outside NODE_ROLES")


# ------------------------------------------------------- the tools themselves


def test_the_generator_produces_the_shapes_that_broke_things():
    """Guard the guard. A generator that only makes tidy trees would pass every
    property above while testing nothing that ever failed."""
    graphs = [generate(s) for s in range(200)]

    assert any(not g.edges for g in graphs), "no edgeless graph generated"
    assert any(k == "NEARTO" for g in graphs for _s, _t, k in g.edges)
    assert any(k == "CONTAINS" for g in graphs for _s, _t, k in g.edges)

    def has_orphan(g: Graph) -> bool:
        touched = {n for e in g.edges for n in (e[0], e[1])}
        return bool(set(g.ids) - touched)

    assert any(has_orphan(g) for g in graphs), "no orphan generated"

    def has_multi_parent(g: Graph) -> bool:
        parents: dict[str, set[str]] = {}
        for s, t, k in g.edges:
            if k in ("CONTAINS", "LEADSTO"):
                parents.setdefault(t, set()).add(s)
        return any(len(v) > 1 for v in parents.values())

    assert any(has_multi_parent(g) for g in graphs), "no multi-parent node generated"


def test_the_shrinker_actually_shrinks():
    from tests.property_tools import shrink

    big = generate(7, max_nodes=14)
    # a property that fails whenever any edge exists at all
    small = shrink(big, lambda g: bool(g.edges))
    assert len(small.edges) <= 1, f"shrinker left {len(small.edges)} edges"
