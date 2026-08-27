"""A seeded graph generator and a shrinker, for properties over the pure core.

`hypothesis` is not a dependency here and is not added by this: the generators
a graph engine needs are domain-specific — valid SST edge types, plausible
containment, deliberate cycles and orphans — so the built-in strategies would be
replaced almost immediately anyway. What is genuinely worth borrowing is
*shrinking*: a 40-node counterexample tells you nothing, and a 3-node one tells
you everything.

Seeded rather than random. A property test that fails once and passes on rerun
is worse than no test, and this session has already spent real effort separating
noise from signal in the model-facing suites. Here there is no excuse for it —
the core is pure.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Iterable

SST_TYPES = ("CONTAINS", "LEADSTO", "EXPRESSES", "NEARTO")


@dataclass(frozen=True)
class Graph:
    """A node-id list and edge dicts, the shape `spine` and the lenses take."""

    ids: tuple[str, ...]
    edges: tuple[tuple[str, str, str], ...]   # (source, target, type)

    def edge_dicts(self) -> list[dict[str, Any]]:
        return [{"source": s, "target": t, "type": k, "label": ""}
                for s, t, k in self.edges]

    def without_node(self, nid: str) -> "Graph":
        return Graph(
            ids=tuple(i for i in self.ids if i != nid),
            edges=tuple(e for e in self.edges if nid not in (e[0], e[1])),
        )

    def without_edge(self, index: int) -> "Graph":
        return Graph(ids=self.ids,
                     edges=tuple(e for i, e in enumerate(self.edges) if i != index))

    def __len__(self) -> int:
        return len(self.ids) + len(self.edges)

    def describe(self) -> str:
        return (f"Graph(ids={list(self.ids)},\n"
                f"      edges={[list(e) for e in self.edges]})")


def generate(seed: int, *, max_nodes: int = 14) -> Graph:
    """One graph. Deliberately includes the shapes that broke things before.

    Orphans, multi-parent nodes, cycles and NEARTO-only nodes are all generated
    on purpose: each corresponds to a real defect this codebase has had, and a
    generator that only makes tidy trees would have caught none of them.
    """
    rng = random.Random(seed)
    n = rng.randint(1, max_nodes)
    # Mixed-width ids: a low-sorting newcomer once renamed a whole component and
    # swapped its packing rank, so id shape is part of the input space.
    ids = tuple(
        (f"{rng.choice('abz_')}{i:02d}" if rng.random() < 0.5 else f"n{i}")
        for i in range(n)
    )
    ids = tuple(dict.fromkeys(ids))          # unique, order preserved

    edges: list[tuple[str, str, str]] = []
    for _ in range(rng.randint(0, len(ids) * 2)):
        s, t = rng.choice(ids), rng.choice(ids)
        if s == t:
            continue                          # self-loops are not SST edges
        edges.append((s, t, rng.choice(SST_TYPES)))

    return Graph(ids=ids, edges=tuple(dict.fromkeys(edges)))


def shrink(graph: Graph, still_fails: Callable[[Graph], bool]) -> Graph:
    """Smallest graph reachable by deletion that still fails.

    Greedy and bounded: drop one node or one edge at a time, keep the deletion
    when the property still fails, stop when nothing can be removed. Enough to
    turn a 14-node counterexample into something readable.
    """
    current = graph
    changed = True
    while changed:
        changed = False
        for nid in list(current.ids):
            candidate = current.without_node(nid)
            if candidate.ids and still_fails(candidate):
                current, changed = candidate, True
                break
        if changed:
            continue
        for index in range(len(current.edges)):
            candidate = current.without_edge(index)
            if still_fails(candidate):
                current, changed = candidate, True
                break
    return current


def find_counterexample(
    predicate: Callable[[Graph], bool],
    *,
    seeds: Iterable[int] = range(200),
    max_nodes: int = 14,
) -> Graph | None:
    """First generated graph where `predicate` is False, shrunk.

    `predicate` returns True when the property HOLDS, so a counterexample is
    where it does not.
    """
    def fails(g: Graph) -> bool:
        try:
            return not predicate(g)
        except Exception:
            return True                        # a crash is a failure too

    for seed in seeds:
        graph = generate(seed, max_nodes=max_nodes)
        if fails(graph):
            return shrink(graph, fails)
    return None


def assert_property(predicate: Callable[[Graph], bool], message: str,
                    *, seeds: Iterable[int] = range(200),
                    max_nodes: int = 14) -> None:
    counter = find_counterexample(predicate, seeds=seeds, max_nodes=max_nodes)
    assert counter is None, f"{message}\n\nminimal counterexample:\n{counter.describe()}"
