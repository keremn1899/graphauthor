"""Arrangement — the ordering ledger, the lenses, and the shared spine.

Deterministic: no database, no LLM, no network. What is under test is the
property the map depends on — that it is a *place*, and does not move when
something unrelated changes.
"""

from __future__ import annotations

import pathlib
import random
import tempfile

import pytest

import spine as spine_mod
from graph_layout.contract import arrange
from graph_layout.ordering import Ordering, assign_slots, band_order, reconcile


def _edge(s, t, kind="CONTAINS"):
    return {"source": s, "target": t, "type": kind, "label": ""}


def _chain(n: int):
    ids = [f"n{i:02d}" for i in range(n)]
    return ids, [_edge(ids[i], ids[i + 1]) for i in range(n - 1)]


def _star(children: int):
    ids = ["root"] + [f"c{i:02d}" for i in range(children)]
    return ids, [_edge("root", c) for c in ids[1:]]


# ------------------------------------------------------------------- the spine


def test_contains_subtrees_matches_the_engines_original_semantics():
    """Role detection depends on this definition of a region, so unifying the
    implementation must not move it."""
    out_adj = {
        "a": {"contains": ["b", "c"]},
        "b": {"contains": ["d"]},
        "x": {"contains": ["y"]},
    }
    subtrees = spine_mod.contains_subtrees(out_adj)
    assert subtrees["a"] == subtrees["b"] == subtrees["c"] == subtrees["d"]
    assert subtrees["x"] == subtrees["y"]
    assert subtrees["a"] != subtrees["x"]
    # Nodes CONTAINS never touches are absent, not assigned to region 0.
    assert "unrelated" not in subtrees


def test_spine_prefers_contains_then_leadsto_and_never_nearto():
    ids = ["a", "b", "c"]
    edges = [_edge("a", "b", "LEADSTO"), _edge("c", "b", "CONTAINS"),
             _edge("a", "c", "NEARTO")]
    sp = spine_mod.derive(ids, edges)
    assert sp.parent["b"] == "c", "CONTAINS should outrank LEADSTO as a parent"
    assert "a" not in sp.parent, "NEARTO must never define a parent"


def test_spine_breaks_cycles_so_the_backbone_is_always_a_forest():
    ids = ["a", "b", "c"]
    edges = [_edge("a", "b"), _edge("b", "c"), _edge("c", "a")]
    sp = spine_mod.derive(ids, edges)
    assert len(sp.roots) >= 1
    assert len(sp.depth) == len(ids), "every node must be reachable from a root"


# ---------------------------------------------------------------- the ledger


def test_slots_keep_existing_leaves_exactly_put_when_one_is_inserted():
    slots = {"a": 0.0, "b": 1.0, "c": 2.0}
    assign_slots(["a", "b", "new", "c"], slots)
    assert slots["a"] == 0.0 and slots["b"] == 1.0 and slots["c"] == 2.0
    assert 1.0 < slots["new"] < 2.0


def test_slots_reject_stale_anchors_rather_than_stacking_nodes():
    """A reparented node can carry a slot from a position it no longer holds.
    Trusting it would interpolate between crossed anchors and overlap nodes."""
    slots = {"a": 5.0, "b": 1.0}
    assign_slots(["a", "b"], slots)
    assert slots["a"] < slots["b"]


def test_band_order_appends_newcomers_regardless_of_id_or_parent():
    """Both obvious orderings fail here: sorting by id lets an early-sorting id
    take the first cell, and walking the ledger lets a newcomer inherit its
    parent's rank."""
    slots = {"m": 0.0, "n": 1.0}
    order = band_order(["m", "n", "aaa_new"], slots)
    assert order == ["m", "n", "aaa_new"]


def test_departed_nodes_become_tombstones_and_keep_their_place():
    """History is on the ambient screen, so an older state must render as a
    subset of the current geometry plus ghosts — never a different layout."""
    ids, edges = _chain(4)
    _a, ordering, _l = arrange("canonical", ids, edges)

    survivors = [n for n in ids if n != "n02"]
    surviving_edges = [e for e in edges
                       if e["source"] != "n02" and e["target"] != "n02"]
    arrangement, ordering2, _l2 = arrange(
        "canonical", survivors, surviving_edges, ordering=ordering)

    assert "n02" in ordering2.tombstones
    assert "n02" in arrangement.positions, "a ghost needs somewhere to render"


# ----------------------------------------------------------------- stability


@pytest.mark.parametrize("lens", ["canonical", "causal"])
@pytest.mark.parametrize("build", [lambda: _chain(12), lambda: _star(15)])
def test_adding_a_node_leaves_the_rest_of_the_arrangement_alone(lens, build):
    ids, edges = build()
    first, ordering, _l = arrange(lens, ids, edges)

    grown_ids = ids + ["aaa_inserted"]  # an id that sorts before everything
    grown_edges = edges + [_edge(ids[-1], "aaa_inserted")]
    second, _o, _l2 = arrange(lens, grown_ids, grown_edges, ordering=ordering)

    moved = [nid for nid in first.positions
             if second.positions.get(nid) != first.positions[nid]]
    assert len(moved) <= 3, f"{lens}: {len(moved)} nodes moved: {moved[:8]}"


def test_many_small_subtrees_do_not_render_as_a_ribbon():
    """`agreements` is one component with 23 roots and a fan-out of two, and it
    measured at aspect 28.4 — a hairline across the canvas. Width came from
    subtrees standing in a row, so subtrees pack into a grid like components do."""
    from graph_layout.metrics import measure

    ids: list[str] = []
    edges = []
    for r in range(20):
        root = f"r{r:02d}"
        kid = f"k{r:02d}"
        ids += [root, kid]
        edges.append(_edge(root, kid))

    arrangement, _o, _l = arrange("canonical", ids, edges)
    aspect = measure(arrangement.positions, edges)["aspect"]
    assert 0.25 < aspect < 6, f"aspect {aspect} is a ribbon, not a map"


def test_universal_root_packs_first_tier_regions_instead_of_making_a_ribbon():
    """A constructed handbook often has one corpus root above many operational
    regions. The first-tier branches are regions, not 100 leaves for one row."""
    from graph_layout.metrics import measure

    ids = ["handbook"]
    edges = []
    for region in range(12):
        region_id = f"region_{region:02d}"
        ids.append(region_id)
        edges.append(_edge("handbook", region_id))
        previous = region_id
        for item in range(8):
            node_id = f"r{region:02d}_n{item:02d}"
            ids.append(node_id)
            edges.append(_edge(previous, node_id))
            previous = node_id

    arrangement, _ordering, _lens = arrange("canonical", ids, edges)
    aspect = measure(arrangement.positions, edges)["aspect"]
    assert 0.25 < aspect < 6, f"aspect {aspect} is a ribbon, not a map"


def test_the_grid_pitch_is_remembered_so_growth_does_not_re_pitch_it():
    """Sizing cells from the current widest subtree moved the whole grid every
    time any subtree grew — 1179 units for one added node."""
    ids: list[str] = []
    edges = []
    for r in range(9):
        ids += [f"r{r}", f"k{r}"]
        edges.append(_edge(f"r{r}", f"k{r}"))

    first, ordering, _l = arrange("canonical", ids, edges)
    grown = ids + ["k0b"]
    second, _o, _l2 = arrange(
        "canonical", grown, edges + [_edge("r0", "k0b")], ordering=ordering)

    moved = [n for n in first.positions
             if second.positions.get(n) != first.positions[n]]
    assert len(moved) <= 3, f"the grid re-pitched: {len(moved)} nodes moved"


def test_component_identity_survives_a_low_sorting_newcomer():
    """Naming a component after its sorted-first member let one node rename the
    whole region, which lost its packing rank and swapped it into another row."""
    ids_a, edges_a = _chain(3)
    ids_b = ["z0", "z1"]
    edges_b = [_edge("z0", "z1")]
    ids, edges = ids_a + ids_b, edges_a + edges_b

    _first, ordering, _l = arrange("canonical", ids, edges)
    key_before = ordering.component_of["n00"]

    grown = ids + ["aaa"]
    _second, ordering2, _l2 = arrange(
        "canonical", grown, edges + [_edge("n00", "aaa")], ordering=ordering)
    assert ordering2.component_of["n00"] == key_before
    assert ordering2.component_of["aaa"] == key_before


# -------------------------------------------------------------------- lenses


def test_canonical_puts_contained_nodes_below_what_contains_them():
    ids, edges = _chain(4)
    arrangement, _o, _l = arrange("canonical", ids, edges)
    ys = [arrangement.positions[n][1] for n in ids]
    assert ys == sorted(ys) and len(set(ys)) == len(ids)


def test_isolated_nodes_land_in_the_gutter_not_in_the_graph():
    ids, edges = _chain(3)
    arrangement, _o, _l = arrange("canonical", ids + ["lonely"], edges)
    assert arrangement.gutter == ["lonely"]


def test_causal_leaves_non_causal_material_out_of_the_flow():
    """Threading EXPRESSES material into causal layers would invent a causal
    reading the graph does not assert."""
    ids = ["a", "b", "prop"]
    edges = [_edge("a", "b", "LEADSTO"), _edge("a", "prop", "EXPRESSES")]
    arrangement, _o, _l = arrange("causal", ids, edges)
    assert arrangement.gutter == ["prop"]
    assert arrangement.positions["b"][1] > arrangement.positions["a"][1]


def test_causal_drops_back_edges_rather_than_reversing_them():
    """A reversed LEADSTO would draw an arrow the graph never asserted."""
    ids = ["a", "b", "c"]
    edges = [_edge("a", "b", "LEADSTO"), _edge("b", "c", "LEADSTO"),
             _edge("c", "a", "LEADSTO")]
    arrangement, _o, _l = arrange("causal", ids, edges)
    assert len({arrangement.positions[n][1] for n in ids}) > 1


def test_membership_is_offered_only_to_graphs_shaped_like_membership():
    """A lens with nothing to say is worse than a missing lens.

    The distinction it has to draw is between hubs that are *sinks* and hubs
    that are *sources*: belonging is asserted once per membership by the member,
    so a group collects incoming edges, while a tree's parent points outward at
    its children. Getting that backwards would hand the lens every hierarchy in
    the product.
    """
    from graph_layout.contract import applicable_lenses

    member_ids, member_edges = _membership(12, 4)
    assert "membership" in applicable_lenses(member_ids, member_edges)

    # A hierarchy: the same fan-out, pointing the other way.
    tree_ids, tree_edges = _star(15)
    assert "membership" not in applicable_lenses(tree_ids, tree_edges)

    chain_ids, chain_edges = _chain(12)
    assert "membership" not in applicable_lenses(chain_ids, chain_edges)


def test_select_lens_falls_back_when_the_lens_has_nothing_to_say():
    """A well-formed name is not enough. Bookmarking Cause on a containment
    tree must not draw the tray; that is how the operator learns the control
    is broken.
    """
    from graph_layout.contract import select_lens

    tree_ids, tree_edges = _star(15)
    assert select_lens("causal", tree_ids, tree_edges) == "canonical"
    assert select_lens("membership", tree_ids, tree_edges) == "canonical"
    assert select_lens("canonical", tree_ids, tree_edges) == "canonical"
    assert select_lens("no-such-lens", tree_ids, tree_edges) == "canonical"

    member_ids, member_edges = _membership(12, 4)
    assert select_lens("membership", member_ids, member_edges) == "membership"

    flow_ids = [f"n{i}" for i in range(8)]
    flow_edges = [_edge(flow_ids[i], flow_ids[i + 1], "LEADSTO")
                  for i in range(7)]
    assert select_lens("causal", flow_ids, flow_edges) == "causal"


def test_membership_beats_the_tree_on_the_shape_it_was_built_for():
    """The lens's entire justification, and the reason it is a lens rather than
    a tweak to canonical.

    Measured on `agreements` (23 countries, 8 organisations): canonical 97
    crossings, membership 32. Asserted here on a generated graph of the same
    shape, as a *comparison* rather than a fixed number — the point is that
    modelling the bipartition beats threading it onto a spine, not that any
    particular count is sacred.
    """
    from graph_layout.metrics import measure

    ids, edges = _membership(20, 5, per=3)
    tree, _o, _l = arrange("canonical", ids, edges)
    ring, _o2, _l2 = arrange("membership", ids, edges)

    assert (measure(ring.positions, edges)["crossings"]
            < measure(tree.positions, edges)["crossings"])


def test_a_group_keeps_being_a_group_when_it_gains_a_child():
    """Classification turns on in-degree beating out-degree, which is a knife
    edge — and the property tests found it on five nodes: one added child tipped
    a group onto the member side and redrew the whole diagram.

    The ledger holds the decision, so a group stays a group while it still has
    the members to justify it.
    """
    ids, edges = _membership(10, 3)
    _first, ordering, _l = arrange("membership", ids, edges)
    groups_before = set(ordering.membership_groups)
    assert groups_before, "no groups were recorded at all"

    # Give every group a child, flipping its in/out balance.
    grown = ids + [f"{g}_child" for g in groups_before]
    grown_edges = edges + [_edge(g, f"{g}_child") for g in groups_before]
    _second, after, _l2 = arrange("membership", grown, grown_edges,
                                  ordering=ordering)

    assert groups_before <= set(after.membership_groups), (
        "a group stopped being a group because it gained a child")


def test_membership_puts_a_shared_member_between_the_groups_it_joins():
    """What the geometry is *for*. Distance has to mean something, or the ring
    is decoration: a member of two groups belongs between them, not beside one
    of them with a long edge to the other."""
    ids, edges = _membership(9, 3, per=1, seed=3)
    shared = "m00"
    edges = [e for e in edges if e["source"] != shared]
    edges += [_edge(shared, "g0"), _edge(shared, "g1")]

    arrangement, _o, _l = arrange("membership", ids, edges)
    px, py = arrangement.positions[shared]
    g0, g1 = arrangement.positions["g0"], arrangement.positions["g1"]
    midpoint = ((g0[0] + g1[0]) / 2, (g0[1] + g1[1]) / 2)

    def far(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    assert far((px, py), midpoint) < far(g0, g1), (
        "a member of both groups was not drawn between them")


def test_arrangement_is_reproducible_from_scratch():
    """Same graph in, same coordinates out — on any machine, in any process."""
    ids, edges = _star(9)
    first, _o, _l = arrange("canonical", ids, edges)
    second, _o2, _l2 = arrange("canonical", list(reversed(ids)), list(edges))
    assert first.positions == second.positions


def test_empty_graph_arranges_to_nothing_without_erroring():
    arrangement, ordering, lens = arrange("canonical", [], [])
    assert arrangement.positions == {}
    assert lens == "canonical"
    assert isinstance(ordering, Ordering)


def test_reconcile_on_a_fresh_ledger_places_everything():
    ids, edges = _chain(3)
    sp = spine_mod.derive(ids, edges)
    ordering = reconcile(None, sp, set(ids))
    assert set(ids) <= {n for lst in ordering.siblings.values() for n in lst}
    assert ordering.tombstones == []


# ------------------------------------------------------- ordering by measurement


def _membership(members: int, groups: int, seed: int = 0, per: int = 2):
    """A bipartite membership graph — the shape a forest fits worst.

    `agreements` is exactly this: 23 countries against 8 organisations. The
    spine adopts each group as one member's child and every remaining edge
    becomes a cross edge, so 41 of its 49 edges influence no position at all.

    Membership is seeded-random rather than periodic. A periodic rule
    (`(i + j) % 3`) makes every group interchangeable, so there is no better
    arrangement to find and the fixture asserts nothing — which is exactly what
    the first version of this test did.
    """
    rng = random.Random(seed)
    ids = [f"m{i:02d}" for i in range(members)] + [f"g{j}" for j in range(groups)]
    edges = [_edge(f"m{i:02d}", f"g{j}")
             for i in range(members)
             for j in rng.sample(range(groups), per)]
    return ids, edges


def _drawn_quality(arrangement, edges):
    """The selector's own objective: overlapping pairs, then crossings."""
    from graph_layout.metrics import measure

    measured = measure(arrangement.positions, edges)
    return (measured["overlap"], measured["crossings"])


def test_cross_edges_get_a_say_in_where_a_subtree_sits():
    """The layout used to arrange the spine and ignore everything else.

    On a membership graph that means arranging a sixth of what is drawn, and it
    is where the crossings live: 164 of `agreements`'s 175 were off-spine edges
    crossing each other.

    Asserted against overlap-then-crossings rather than crossings alone,
    because that is what the selector optimises and the two genuinely diverge:
    on this fixture, consulting cross edges removes both overlapping pairs and
    widens spacing by 5% while *adding* 37 crossings. Demanding fewer crossings
    here would forbid that trade, which is the wrong way round — a crossing
    makes the eye work, an overlap makes a node not exist.
    """
    from graph_layout import contract

    ids, edges = _membership(18, 6)

    previous = contract.ORDERING_CANDIDATES
    contract.ORDERING_CANDIDATES = ()
    try:
        blind, _o, _l = arrange("canonical", ids, edges)
    finally:
        contract.ORDERING_CANDIDATES = previous
    seeing, _o2, _l2 = arrange("canonical", ids, edges)

    assert _drawn_quality(seeing, edges) < _drawn_quality(blind, edges)


def test_a_ledger_from_an_older_sidecar_is_refused_rather_than_misread():
    """`cells` has held three different meanings, all of them lists of floats.

    It was `[cell_w, cell_h, cols]`; it is now `[cols, *widths, *heights]`.
    Nothing about a stale record fails to parse — `[4.0, 3.9, 6.0]` reads
    happily as "four columns, widths [3.9, 6.0]" — so the failure is silent, and
    it lands on exactly the graphs that already exist and would never be
    reported as a bug, only as "the map looks a bit worse than the demo".

    The version is the only thing standing between those two readings, so this
    asserts the version actually moved when the meaning did.
    """
    import json

    from graph_read import LAYOUT_SIDECAR_VERSION, _read_sidecar

    stale = {
        "version": LAYOUT_SIDECAR_VERSION - 1,
        "topology_version": "whatever",
        "lenses": {"canonical": {"ordering": {
            "cells": {"c_argentina": [4.0, 3.9, 6.0]}}}},
    }
    with tempfile.TemporaryDirectory() as tmp:
        db = pathlib.Path(tmp) / "graph.lbug"
        (db.with_name(f"{db.stem}.layout.json")).write_text(
            json.dumps(stale), encoding="utf-8")
        assert _read_sidecar(db) is None, (
            "a sidecar from before the cells format changed was accepted; its "
            "grid pitches would be misread as column counts")


def test_arrange_is_never_worse_than_a_shape_drawn_on_its_own():
    """A candidate that cannot express itself is not a candidate.

    Lenses write back to the ledger as they draw, and `branch_roots` is
    deliberately **one-way** — a root that has earned packing keeps it, so a
    root on the fan threshold cannot oscillate. That makes ledger reuse silently
    fatal: an alternative handed the incumbent's ledger inherits its packing
    decisions, redraws the incumbent's own arrangement, ties, and loses. It is
    invisible from outside, because "the alternative never wins" is exactly what
    a genuinely worse alternative looks like. It shipped that way until the two
    were drawn standalone and compared.

    Eight branches of nine leaves is a shape where the two really diverge —
    packing measures (9 overlapping pairs, 26 crossings) against (0, 18) for
    rows — so `arrange` has to come back with the better one. Asserted against
    every candidate drawn independently, which is the actual contract: whatever
    else the selector does, it may never return a map worse than one it had.
    """
    from graph_layout import contract
    from graph_layout.ordering import reconcile

    ids = ["root"]
    edges = []
    for branch in range(8):
        bid = f"b{branch}"
        ids.append(bid)
        edges.append(_edge("root", bid))
        for leaf in range(9):
            lid = f"b{branch}_l{leaf}"
            ids.append(lid)
            edges.append(_edge(bid, lid))

    chosen, _o, _l = arrange("canonical", ids, edges)

    sp = spine_mod.derive(ids, edges)
    live = set(ids)
    alternatives = [None] + [s for _label, s in
                             contract.shape_candidates("canonical")]
    assert len(alternatives) > 1, "no alternative shape was offered"

    for shape in alternatives:
        standalone = contract.LENSES["canonical"](
            ids, edges, sp, reconcile(None, sp, live), {}, shape)
        assert _drawn_quality(chosen, edges) <= _drawn_quality(standalone, edges), (
            f"arrange returned a worse map than shape {shape} drawn alone")


def test_a_candidate_is_never_kept_when_it_draws_worse():
    """The selector's whole justification, and the reason it can be trusted at
    all: it is a floor, not a gamble.

    Every shape decision in this module helps one graph and hurts another.
    Ordering by connectivity halves the crossings on a bipartite membership
    graph and adds 16% to a tidy tree. Packing a broad branch rescues the
    416-node `rfc` (740 overlapping pairs to 475) and spoils the 84-node one (16
    to 59). Nothing available at layout time separates those cases — so each is
    drawn, measured, and kept only on the graphs where it wins.
    """
    from graph_layout import contract

    for build in (lambda: _chain(12), lambda: _star(15),
                  lambda: _membership(12, 4), lambda: _membership(20, 7)):
        ids, edges = build()
        previous = contract.ORDERING_CANDIDATES
        contract.ORDERING_CANDIDATES = ()
        try:
            incumbent, _o, _l = arrange("canonical", ids, edges)
        finally:
            contract.ORDERING_CANDIDATES = previous
        chosen, _o2, _l2 = arrange("canonical", ids, edges)

        assert _drawn_quality(chosen, edges) <= _drawn_quality(incumbent, edges)


def test_choosing_an_ordering_does_not_cost_the_stability_guarantee():
    """Candidates differ only in where *unplaced* nodes go. A node already in
    the ledger is pinned in every candidate, so the selector cannot reshuffle a
    map the operator has already learned."""
    ids, edges = _membership(14, 5)
    first, ordering, _l = arrange("canonical", ids, edges)

    grown = ids + ["aaa_inserted"]
    grown_edges = edges + [_edge("g0", "aaa_inserted")]
    second, _o, _l2 = arrange("canonical", grown, grown_edges, ordering=ordering)

    moved = [n for n in first.positions
             if second.positions.get(n) != first.positions[n]]
    assert len(moved) <= max(3, len(ids) // 2), f"{len(moved)} nodes moved"


# ------------------------------------------------------------ what gets offered


def test_a_lens_with_nothing_to_say_is_not_offered():
    """Real product graphs are CONTAINS/EXPRESSES — `rfc` (416 nodes) and
    `agreements` both have zero LEADSTO. Offering the causal lens there puts
    100% of the map in an out-of-flow band and teaches the operator that the
    control is broken."""
    from graph_layout.contract import applicable_lenses

    ids, edges = _chain(6)  # CONTAINS only
    assert applicable_lenses(ids, edges) == ["canonical"]

    causal_ids = ["a", "b", "c", "d"]
    causal_edges = [_edge("a", "b", "LEADSTO"), _edge("b", "c", "LEADSTO"),
                    _edge("c", "d", "LEADSTO")]
    assert "causal" in applicable_lenses(causal_ids, causal_edges)


def test_asking_for_an_unoffered_lens_still_answers():
    """Advertising is not gating. A lens that is a poor fit is still a legal
    request, and refusing it would cost the operator their map for a taste
    judgement."""
    from graph_layout.contract import resolve_lens

    assert resolve_lens("causal") == "causal"


# ------------------------------------------------------------------- the spokes


def test_a_branch_packed_root_reports_its_spokes():
    """No arrangement can draw a 59-way star into a 2-D grid without crossings —
    on `rfc` every one of the 170 comes from exactly that. The layout cannot fix
    it, so it names the edges instead and lets the renderer route or frame
    them."""
    ids = ["root"]
    edges = []
    for region in range(6):
        rid = f"region{region}"
        ids.append(rid)
        edges.append(_edge("root", rid))
        for item in range(3):
            nid = f"r{region}_n{item}"
            ids.append(nid)
            edges.append(_edge(rid, nid))

    arrangement, _o, _l = arrange("canonical", ids, edges)
    assert ["root", "region0"] in arrangement.spokes
    assert len(arrangement.spokes) == 6
    # and every node knows which packed region it is in
    assert arrangement.regions["r0_n0"]["branch_id"] == "region0"
    assert arrangement.regions["r5_n2"]["branch_id"] == "region5"


def test_a_graph_with_no_packed_region_reports_no_spokes():
    ids, edges = _chain(4)
    arrangement, _o, _l = arrange("canonical", ids, edges)
    assert arrangement.spokes == []


# ---------------------------------------------------------------- the metrics


def test_overlap_is_measured_where_the_operator_looks():
    """Overlap used to be a fixed threshold in graph units, but the client
    rescales by a factor that shrinks as the graph grows. So the metric reported
    0 for every graph in the repository while real maps collided — 740
    overlapping pairs on `rfc` once measured correctly."""
    from graph_layout.metrics import DISPLAY_MAX_EXTENT, measure

    # Two nodes a hair apart, in a map far too wide to be scaled up.
    positions = {"a": (0.0, 0.0), "b": (1.0, 0.0),
                 "far": (DISPLAY_MAX_EXTENT * 40, 0.0)}
    assert measure(positions, [])["overlap"] == 1


def test_the_spacing_floor_leaves_a_gap_not_a_touch():
    """The floor used to sit exactly at tangency.

    `MIN_DISPLAY_SCALE = NODE_DIAMETER / MIN_CLEARANCE` reads as "nodes stop
    overlapping here", and it is true by the strict definition — which is why
    `metrics.overlap` reported 0 across all 35 graphs while the maps still came
    out as mats of touching discs. Measured on the real sidecars, the closest
    pair on `agreements` and on `lotr` rendered at exactly 62.0px apart for a
    62px node: a gap of zero.

    The client fits every map to its viewport, so what the operator sees is this
    ratio and nothing else. Stated as a gap so it cannot silently return to a
    touch.
    """
    from graph_layout.contract import (
        MIN_CLEARANCE, MIN_DISPLAY_SCALE, NODE_DIAMETER)

    pitch = MIN_CLEARANCE * MIN_DISPLAY_SCALE
    assert pitch - NODE_DIAMETER >= NODE_DIAMETER * 0.5, (
        f"the tightest pair renders {pitch:.1f}px apart for a "
        f"{NODE_DIAMETER:.0f}px node — that is a touch, not spacing"
    )


def test_the_display_transform_matches_the_client():
    """These constants exist twice — here and in the browser — and a layout
    metric computed against a transform the client does not apply is worse than
    no metric, because it reads as a clean bill of health."""
    import re
    from pathlib import Path

    from graph_layout import metrics as lm

    root = Path(__file__).resolve().parent.parent
    model = root / "frontend/src/product/graphModel.ts"
    dna = root / "frontend/src/styles/graphDna.ts"
    if not model.exists() or not dna.exists():
        pytest.skip("frontend sources not present")

    source = model.read_text(encoding="utf-8")
    numbers = re.search(
        r"Math\.max\(\s*([\d.]+),\s*Math\.min\(\s*([\d.]+),"
        r"\s*Math\.sqrt\([^)]*\)\s*\*\s*([\d.]+)",
        source,
    )
    assert numbers, "could not read the display transform from graphModel.ts"
    assert float(numbers.group(1)) == lm.DISPLAY_MIN_EXTENT
    assert float(numbers.group(2)) == lm.DISPLAY_MAX_EXTENT
    assert float(numbers.group(3)) == lm.DISPLAY_EXTENT_PER_ROOT_NODE

    diameter = re.search(r"nodeDiameter:\s*([\d.]+)", dna.read_text(encoding="utf-8"))
    assert diameter, "could not read nodeDiameter from graphDna.ts"
    assert float(diameter.group(1)) == lm.DISPLAY_NODE_DIAMETER

    # The floor is the half of this transform that keeps nodes apart, so it has
    # to be mirrored too. The client reads it off the payload rather than
    # hard-coding it, which is the only reason there is no number to compare —
    # what must hold is that it applies one at all.
    assert re.search(r"Math\.max\(\s*floor,", source), (
        "the client no longer floors the display scale; the server's overlap "
        "metric predicts a transform the browser does not apply"
    )
    assert re.search(r"min_display_scale", source), (
        "the client floors the scale with something other than the server's "
        "min_display_scale"
    )
