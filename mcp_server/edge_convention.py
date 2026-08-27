"""The primitive a graph has already chosen for a relation, and whether a new
edge respects it.

Measured this session: the four SST primitives survive every ablation, but they
are used inconsistently, and the cost is real rather than cosmetic.

- A retrieval program keyed on LEADSTO for supersession returns **0.20 recall**
  on a graph that authored supersession as NEARTO, and **0.0** for dependency on
  two constructed graphs. Silent under-return, never an error.
- `antecedents_of` sees **1 of 4** supersession relations on `cattrs-built`,
  because three were authored on NEARTO and it walks LEADSTO.
- Collapsing directed relations onto NEARTO destroys direction outright: a
  depth-3 outgoing query returns 4.6x too much, because NEARTO is walked
  undirected.

None of that is fixed by changing the set. It is fixed at authoring time, and
the signal needed is already in the graph: **every edge label sits on exactly one
primitive, in all 37 graphs measured.** That is not a rule anyone wrote down — it
is a convention every author has so far kept by accident. So it can be read off
the graph and enforced against, without inventing a taxonomy.

Two dispositions, deliberately different in kind:

- `collision` — this label already exists on a DIFFERENT primitive in this graph.
  A mechanical contradiction: the same relation cannot be both directed and
  undirected, and a program keyed on either primitive now silently misses half
  its targets. Refusable.
- `novel` — this label is new here. Nothing to contradict, so nothing to refuse.
  Advisory guidance only, drawn from what similar labels do.

The split matters. Quality judgements about topology stay advisory because the
same signature has had opposite correct repairs on different graphs. A label
occupying two primitives at once is not a judgement call.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

SST_TYPES = ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO")
#: Walked undirected and, in `hop_expansion`, hop-capped. A relation whose
#: meaning is asymmetric loses that asymmetry here permanently.
UNDIRECTED = "NEARTO"

CONSISTENT = "consistent"
COLLISION = "collision"
NOVEL = "novel"


def read_convention(db_path: Path | str) -> dict[str, dict[str, Any]]:
    """`{label: {"primitive": T, "count": n}}` as the graph currently uses it.

    READ ONLY, and it must stay that way: `Surface` opens read-write and caches
    an index, so anything reaching for a graph to inspect it has to come in at
    this level or on a copy.
    """
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    seen: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    try:
        for rel in SST_TYPES:
            result = conn.execute(
                f"MATCH ()-[e:{rel}]->() RETURN e.label")
            while result.has_next():
                label = str(result.get_next()[0] or "").strip().lower()
                if label:
                    seen[label][rel] += 1
    finally:
        del conn, database

    convention: dict[str, dict[str, Any]] = {}
    for label, by_type in seen.items():
        primary = max(by_type.items(), key=lambda kv: (kv[1], kv[0]))
        convention[label] = {
            "primitive": primary[0],
            "count": primary[1],
            # Non-empty only on a graph that ALREADY violates the invariant.
            # Recorded rather than hidden: it means the graph was authored
            # inconsistently before this check existed.
            "also_on": sorted(t for t in by_type if t != primary[0]),
        }
    return convention


def check_edges(db_path: Path | str,
                edges: Iterable[tuple[str, str, str, str]]) -> dict[str, Any]:
    """Check proposed `(type, source, target, label)` edges against the graph.

    Returns findings plus `allowed`. Only collisions block; novel labels are
    reported with guidance and never refused.
    """
    convention = read_convention(db_path)
    findings: list[dict[str, Any]] = []
    for edge_type, source, target, label in edges:
        key = str(label or "").strip().lower()
        primitive = str(edge_type or "").strip().upper()
        if not key:
            continue
        established = convention.get(key)
        if established is None:
            findings.append({
                "disposition": NOVEL,
                "label": key,
                "primitive": primitive,
                "edge": f"{source}->{target}",
                "note": (
                    "new relation label for this graph; nothing to contradict"
                ),
            })
            continue
        if established["primitive"] == primitive:
            findings.append({"disposition": CONSISTENT, "label": key,
                             "primitive": primitive,
                             "edge": f"{source}->{target}"})
            continue
        findings.append({
            "disposition": COLLISION,
            "label": key,
            "primitive": primitive,
            "established": established["primitive"],
            "established_count": established["count"],
            "edge": f"{source}->{target}",
            # The consequence, not just the mismatch, because the mismatch on
            # its own reads as pedantry.
            "consequence": _consequence(established["primitive"], primitive),
            "repair": (
                f"author this edge as {established['primitive']}, which is what "
                f"{established['count']} existing edge(s) labelled {key!r} use — "
                f"or give this relation a different label if it genuinely means "
                f"something else"
            ),
        })

    collisions = [f for f in findings if f["disposition"] == COLLISION]
    return {
        "allowed": not collisions,
        "reason": ("edge_primitive_collision:"
                   + ",".join(sorted({f["label"] for f in collisions}))
                   if collisions else "edge_primitives_consistent"),
        "findings": findings,
        "collisions": collisions,
        "novel": [f for f in findings if f["disposition"] == NOVEL],
    }


def _consequence(established: str, proposed: str) -> str:
    """Why this particular collision costs something, in retrieval terms."""
    if proposed == UNDIRECTED and established != UNDIRECTED:
        return (
            "moves a directed relation onto NEARTO, which is walked undirected "
            "— the direction is lost, and a program keyed on the established "
            "primitive silently stops finding this edge"
        )
    if established == UNDIRECTED and proposed != UNDIRECTED:
        return (
            "gives direction to a relation the graph records as symmetric; the "
            "two cannot both be true of the same label"
        )
    return (
        "splits one label across two primitives, so no single "
        "expand(edge_types=...) can retrieve all of them"
    )


def overloaded_primitives(db_path: Path | str,
                          families: dict[str, str] | None = None) -> dict[str, Any]:
    """Which primitives carry more than one distinct label — ADVISORY ONLY.

    Overloading is what makes a dependency program keyed on LEADSTO score 0.167
    precision on its own source graph: supersession and dependency share the
    primitive, and only the label separates them. It is a real cost, but it is
    not a contradiction — a primitive is *supposed* to generalise — so this
    reports and never refuses.
    """
    convention = read_convention(db_path)
    by_primitive: dict[str, list[str]] = defaultdict(list)
    for label, entry in convention.items():
        by_primitive[entry["primitive"]].append(label)
    return {
        "labels_per_primitive": {k: sorted(v) for k, v in sorted(by_primitive.items())},
        "overloaded": sorted(k for k, v in by_primitive.items() if len(v) > 1),
        "note": (
            "advisory: a primitive carrying several relations cannot separate "
            "them for a type-keyed query, but generalising is what a primitive "
            "is for — this is a precision cost, not a defect"
        ),
    }
