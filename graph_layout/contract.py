"""The arrangement contract and the lens registry.

Every lens is the same pure function — `(nodes, edges, spine, ordering) ->
Arrangement` — so swapping or adding one touches nothing else, and any lens can
be measured against any other by `graph_layout.metrics`.

Hard cap of three lenses. Each lens is a separate place the operator has to
learn; past three, "the map is a place" stops being true. The third is
membership, offered only to graphs whose shape is that fact. See
`design [new]/graph-arrangement.md` §4.3 for what was considered and rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import spine as spine_mod
from graph_layout.ordering import Ordering

#: Graph-space spacing. Kept at the historical values so existing camera
#: behaviour and node sizing stay calibrated.
ROW_HEIGHT = 220.0
COL_WIDTH = 260.0

#: What a node actually measures when drawn — `GRAPH_DNA_GEOMETRY.nodeDiameter`
#: in frontend/src/styles/graphDna.ts.
#:
#: Spacing is meaningless without it. The pitch above is generous *relative to a
#: node* (the tightest the arrangement ever packs is `ROW_HEIGHT`, which is about
#: 2.4 node diameters centre-to-centre at 90px) and every overlap this map has
#: ever shown came from the client scaling that pitch down to fit a viewport, not
#: from the arrangement. Declared here so the relationship is visible and tunable
#: in one place instead of being a coincidence between two repositories.
NODE_DIAMETER = 90.0

#: The closest two nodes are ever placed, in graph units. Guaranteed by
#: construction: rows are `ROW_HEIGHT` apart and integer slots are `COL_WIDTH`
#: apart, so the floor is the smaller of the two. `test_no_two_nodes_are_drawn
#: _closer_than_a_node` holds it, and `Ordering.needs_renormalise` guards the
#: one way fractional slots could ever breach it.
MIN_CLEARANCE = min(ROW_HEIGHT, COL_WIDTH)

#: The closest two nodes may be drawn, as a multiple of their own diameter.
#:
#: 1.0 means tangent, which is what this was — the floor below was set exactly
#: at the point where circles touch, so every map big enough to hit the floor
#: came out as a mat of adjacent discs with no space between them. That is not
#: overlap by the strict measure `metrics.overlap` uses, and it is precisely why
#: that metric read 0 while the maps still looked collided.
#:
#: The client always fits the whole map to its viewport, so this ratio — not the
#: absolute scale — is what the operator actually sees. Below roughly 1.5 the
#: gap stops reading as a gap; at a 90px node, 1.6 leaves a ~54px clear run for
#: resting filaments and short edge chips between discs.
MIN_NODE_PITCH_RATIO = 1.6

#: Below this display scale, nodes at the guaranteed clearance are drawn closer
#: than `MIN_NODE_PITCH_RATIO` — 0.45 today. A client that scales a map to fit
#: its viewport must clamp at this and pan/zoom instead, or it is choosing
#: collisions over scrolling.
MIN_DISPLAY_SCALE = NODE_DIAMETER * MIN_NODE_PITCH_RATIO / MIN_CLEARANCE
#: Blank corridor between packed components, in columns/rows.
COMPONENT_GAP_X = 2.0
COMPONENT_GAP_Y = 1.2
#: Target width/height of the whole map. Orientation is the primary job, and a
#: mile-wide ribbon is the worst possible shape for a first-contact read.
#:
#: 1.2 rather than the 1.6 this started at, because aspect is not free: a client
#: fits a map by its **longest side**, so for a given amount of material a wider
#: map is a smaller map, and a smaller map overlaps. Swept 1.0/1.2/1.4/1.6/2.0
#: over five real graphs — total overlapping pairs 871 / 871 / 939 / 941 / 1053,
#: with 1.2 also giving the widest on-screen spacing of any setting on the
#: 200-node corpus. 1.0 ties on overlap and loses there, and squarer than the
#: viewport starts wasting the sides.
TARGET_ASPECT = 1.2


@dataclass
class Arrangement:
    """What a lens produces. Positions may include tombstones (for ghosts)."""

    positions: dict[str, tuple[float, float]]
    regions: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Nodes placed in the gap gutter — isolated material, shown as such.
    gutter: list[str] = field(default_factory=list)
    #: `[parent, child]` pairs from a branch-packed root to its regions.
    #:
    #: These are the edges no arrangement can draw well. A universal corpus root
    #: with 59 children packed into a grid emits 59 straight lines across the
    #: cells: measured on `rfc`, the spokes cross nothing among themselves and
    #: the rest of the graph crosses nothing among itself, yet together they make
    #: **every one** of that map's 170 crossings. Straight-line rendering of a
    #: star into a 2-D packing is the cause, so the fix is not a better ordering
    #: — it is to route them, or to draw the region as a frame and not draw the
    #: spoke at all. Reported so the renderer can decide; the geometry is
    #: unaffected either way.
    spokes: list[list[str]] = field(default_factory=list)
    notes: str = ""


LensFn = Callable[..., Arrangement]

#: Registered lenses, populated at import time below.
LENSES: dict[str, LensFn] = {}
DEFAULT_LENS = "canonical"

#: Sibling-ordering hypotheses tried alongside plain id order, in
#: `choose_ordering`. Each costs one extra arrangement per rebuild.
ORDERING_CANDIDATES = ("adjacent", "lifted")


#: Optional per-lens applicability test, `(node_ids, edges) -> bool`.
APPLIES: dict[str, Callable[[list[str], list[dict[str, Any]]], bool]] = {}

#: A lens is only offered when it can arrange this share of the graph. Below it
#: the lens is not a different view of the map, it is the same nodes in a tray.
LENS_COVERAGE_MIN = 0.25


def register(name: str, fn: LensFn, applies: Callable[..., bool] | None = None
             ) -> None:
    LENSES[name] = fn
    if applies is not None:
        APPLIES[name] = applies


def lens_names() -> list[str]:
    return sorted(LENSES)


def applicable_lenses(node_ids: list[str],
                      edges: list[dict[str, Any]]) -> list[str]:
    """The lenses worth offering *for this graph*.

    A lens with nothing to say about a graph is worse than a missing lens: the
    operator switches to it, sees the whole map dumped into an out-of-flow band,
    and learns that the control is broken. Measured on real product graphs, that
    is the normal case rather than an edge case — construction output is
    CONTAINS/EXPRESSES, so `rfc` (416 nodes) and `agreements` (31) both have
    **zero** LEADSTO edges and the causal lens puts 100% of their nodes in the
    band while reporting `0 causal layers`.

    Failures are non-fatal: a predicate that raises leaves its lens on offer,
    since hiding a working lens is the worse mistake.
    """
    offered = []
    for name in sorted(LENSES):
        test = APPLIES.get(name)
        if test is None:
            offered.append(name)
            continue
        try:
            if test(node_ids, edges):
                offered.append(name)
        except Exception:
            offered.append(name)
    return offered or [DEFAULT_LENS]


def _causal_applies(node_ids: list[str], edges: list[dict[str, Any]]) -> bool:
    """Causal is worth offering when the flow is actually most of the graph."""
    known = set(node_ids)
    in_flow = {e["source"] for e in edges
               if e.get("type") == "LEADSTO" and e["source"] in known}
    in_flow |= {e["target"] for e in edges
                if e.get("type") == "LEADSTO" and e["target"] in known}
    if len(in_flow) < 3:
        return False
    return len(in_flow) / max(1, len(known)) >= LENS_COVERAGE_MIN


def resolve_lens(name: str | None) -> str:
    """Unknown lens names fall back to canonical rather than erroring.

    A bad querystring should not cost the operator their map.
    """
    key = (name or "").strip().lower()
    return key if key in LENSES else DEFAULT_LENS


def select_lens(name: str | None,
                node_ids: list[str],
                edges: list[dict[str, Any]]) -> str:
    """Unknown *or* inapplicable names fall back to canonical.

    `resolve_lens` only catches a typo. A bookmark of `causal` on a graph with
    no LEADSTO is a well-formed name with nothing to say, and drawing it anyway
    is how the operator learns the control is broken.
    """
    wanted = resolve_lens(name)
    offered = applicable_lenses(node_ids, edges)
    return wanted if wanted in offered else DEFAULT_LENS


def arrange(lens: str | None,
            node_ids: list[str],
            edges: list[dict[str, Any]],
            *,
            ordering: Ordering | None = None,
            facts: dict[str, dict[str, Any]] | None = None) -> tuple[
                Arrangement, Ordering, str]:
    """Lay the graph out, folding the current topology into the prior ordering.

    Returns `(arrangement, reconciled_ordering, lens_name)`. The ordering comes
    back because it is what gets persisted — positions are derived from it, not
    the other way round.

    Where a newcomer joins its family is decided by *drawing it both ways*. See
    `choose_ordering`: the heuristic that reads best on a bipartite membership
    graph reads worst on a tidy tree, and neither this function nor its caller
    can tell which one it has.
    """
    from graph_layout.ordering import hint_from, reconcile

    name = resolve_lens(lens)
    live = set(node_ids)
    sp = spine_mod.derive(node_ids, edges)
    lens_fn = LENSES[name]

    # A lens writes back to the ledger as it draws — `branch_roots` above all,
    # which is deliberately one-way so a root on the fan threshold cannot
    # oscillate. So every candidate must start from a ledger reconciled fresh
    # from the *caller's* ordering, never from one another draw has touched. A
    # first version reused the incumbent's ledger and the alternative was never
    # once chosen anywhere: on the 84-node `rfc` it scored identically to the
    # incumbent, while drawing it in isolation gave 16 overlapping pairs to 59.
    baseline = reconcile(ordering, sp, live)

    def fresh(kind: str) -> Ordering:
        if kind == "id":
            return reconcile(ordering, sp, live)
        return reconcile(ordering, sp, live,
                         order_hint=hint_from(baseline, ordering, sp, kind))

    candidates = [("id", baseline,
                   lens_fn(node_ids, edges, sp, baseline, facts or {}))]
    for kind in ORDERING_CANDIDATES:
        hint = hint_from(baseline, ordering, sp, kind)
        if not hint:
            continue
        candidate = reconcile(ordering, sp, live, order_hint=hint)
        if candidate.siblings == baseline.siblings:
            continue
        candidates.append(
            (kind, candidate,
             lens_fn(node_ids, edges, sp, candidate, facts or {})))

    kind, chosen_ordering, result = choose_ordering(candidates, edges)

    # Then shape, against the ordering just chosen. Two measured decisions in
    # sequence rather than a search over their product: the interaction is weak,
    # and every extra combination is another whole arrangement.
    shaped = []
    for label, shape in shape_candidates(name):
        scratch = fresh(kind)
        drawn = lens_fn(node_ids, edges, sp, scratch, facts or {}, shape)
        shaped.append((f"{kind}+{label}", scratch, drawn))
    if shaped:
        kind, chosen_ordering, result = choose_ordering(
            [(kind, chosen_ordering, result), *shaped], edges)

    # Annotated once, here, rather than inside the selector — which runs twice
    # and would stamp a surviving arrangement with its own name each time.
    if kind != "id":
        result.notes = f"{result.notes}, {kind}"
    return result, chosen_ordering, name


def shape_candidates(lens: str) -> list[tuple[str, dict[str, Any]]]:
    """Alternative shapes worth drawing for this lens, beyond its default.

    Packing a broad branch instead of letting its leaves lie on one line is the
    only one so far, and it is here rather than hard-coded because it is a
    coin flip: over 35 real graphs it changes two of them, rescuing the 416-node
    `rfc` (740 overlapping pairs down to 475) and spoiling the 84-node one (16 up
    to 59). Nothing available at layout time separates those cases.
    """
    if lens != "canonical":
        return []
    from graph_layout.canonical import BRANCH_RIBBON_OFF

    return [("branches-as-rows", {"ribbon_aspect": BRANCH_RIBBON_OFF})]


def choose_ordering(candidates, edges: list[dict[str, Any]]):
    """Keep whichever candidate ordering actually draws better.

    Ordering siblings by connectivity rather than by id is a *hypothesis*, and
    measured across real graphs it is not reliably true. On `agreements` — a
    bipartite membership graph, 23 countries against 8 organisations, which the
    forest model fits badly — relaxing against a node's whole neighbourhood
    removed a third of the crossings. On `rfc`, a pure containment tree where
    every edge is already a spine edge, the same idea *added* crossings to a
    drawing that had none to spare. The principled variant (projecting cross
    edges onto the sibling list they are visible in) beat the naive one on the
    tree and lost badly on the bipartite graph.

    No property of the input available here settles that, so it draws each and
    counts. The incumbent (id order) is first and wins ties, so the map only
    ever changes when there is a measured reason to change it.

    Cost is one extra arrangement per candidate per rebuild — `canonical` lays
    out 416 nodes in 0.01s, and this runs only when topology moves.
    """
    from graph_layout import metrics as layout_metrics

    if len(candidates) == 1:
        return candidates[0]

    best = None
    for kind, order, arrangement in candidates:
        measured = layout_metrics.measure(arrangement.positions, edges)
        # Overlap first, crossings as the tiebreak. Two nodes drawn on top of
        # each other is the one *hard* failure a layout can have — one of them
        # is simply not there for the operator — while a crossing is a place the
        # eye has to work. Ranking them the other way would trade a node away to
        # tidy an edge.
        score = (measured["overlap"], measured["crossings"])
        if best is None or score < best[0]:
            best = (score, kind, order, arrangement)

    return best[1], best[2], best[3]


def _register_builtin_lenses() -> None:
    from graph_layout.canonical import canonical_lens
    from graph_layout.causal import causal_lens
    from graph_layout.membership import membership_applies, membership_lens

    register("canonical", canonical_lens)
    register("causal", causal_lens, applies=_causal_applies)
    register("membership", membership_lens, applies=membership_applies)


_register_builtin_lenses()
