"""How much of a graph the correction gate can actually check.

Production gating probes the COMPLETE Concept universe within a hard cap.
This measurement reports whether that universe fits under the cap — not
structural neighbourhood density, which no longer controls the gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def gate_coverage(db_path: Path | str, *, hops: int | None = None,
                  cap: int | None = None) -> dict[str, Any]:
    """Per-graph report on whether the complete probe universe fits the cap.

    READ ONLY. ``hops`` is ignored and retained only for call-site compatibility
    with older diagnostics.

    This localises; it does not diagnose. A graph over the cap cannot be gated
    without raising the cap. A graph under the cap is checkable — it does not
    say whether individual nodes were wrongly promoted or left unwired.
    """
    import real_ladybug as lb

    from mcp_server.proposals import COMPLETE_PROBE_CAP

    del hops  # neighbourhood depth no longer controls the gate
    cap = COMPLETE_PROBE_CAP if cap is None else cap
    path = Path(db_path)

    database = lb.Database(str(path), read_only=True)
    conn = lb.Connection(database)
    try:
        nodes = int(conn.execute("MATCH (c:Concept) RETURN count(*)").get_next()[0])
        edges = 0
        for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
            edges += int(conn.execute(
                f"MATCH ()-[:{rel}]->() RETURN count(*)").get_next()[0])
        governing: list[str] = []
        result = conn.execute(
            "MATCH (c:Concept) WHERE c.claim_kind = 'governing' RETURN c.id")
        while result.has_next():
            governing.append(str(result.get_next()[0] or ""))
    finally:
        del conn, database

    exceeds = nodes > cap
    return {
        "graph": str(path),
        "nodes": nodes,
        "edges": edges,
        "edges_per_node": round(edges / nodes, 3) if nodes else 0.0,
        "governing": len(governing),
        "cap": cap,
        "probe_mode": "complete_universe",
        # True when every Concept.id can be probed without truncation.
        "checkable": not exceeds,
        "universe_exceeds_cap": exceeds,
        # Edgeless governing nodes: no longer a gate concern, still a
        # CONSTRUCTION one. Under complete-universe probing they are checked
        # like anything else, so this is not a coverage gap. It is reported
        # because it is free and because it localises a region worth reading:
        # on a Kubernetes KEP graph the five edgeless governing nodes were
        # motivation and history sections that should never have governed.
        # (An earlier comment here said that graph answered UNGOVERNED for all
        # fourteen; that was a 3-probe generalisation, retracted — the full
        # sweep is 5 GOVERNED / 17 UNGOVERNED / 1 ABSENT.)
        # On a cattrs construction output the four were real rules left unwired.
        # Same signature, opposite repairs — which is why this never refuses.
        "edgeless_governing": _edgeless_governing(path, governing),
        # Primitive usage, advisory. A primitive carrying several relations
        # cannot separate them for a type-keyed query — measured, that is what
        # makes a dependency program keyed on LEADSTO score 0.167 precision on
        # its OWN source graph, because supersession and dependency share it.
        # Reported here rather than left as an unwired function: a measurement
        # with no consumer is an untested claim.
        "primitive_usage": _primitive_usage(path),
        "over_cap": sorted(governing) if exceeds else [],
        "note": (
            "gate protection is the complete Concept universe within the hard "
            "cap; this localises whether the graph fits that cap — it does not "
            "diagnose whether a node was wrongly promoted or left unwired. "
            "Both have been observed."
        ),
    }


def _primitive_usage(path: Path) -> dict[str, Any]:
    """Which primitives carry more than one relation label. Advisory."""
    from mcp_server.edge_convention import overloaded_primitives

    report = overloaded_primitives(path)
    return {"overloaded": report["overloaded"],
            "labels_per_primitive": {k: len(v) for k, v in
                                     report["labels_per_primitive"].items()}}


def _edgeless_governing(path: Path, governing: list[str]) -> list[str]:
    """Governing nodes with no edge in any SST type, in either direction.

    READ ONLY. Free to compute, so it can run on every graph rather than only
    the ones somebody paid to characterise.
    """
    import real_ladybug as lb

    if not governing:
        return []
    database = lb.Database(str(path), read_only=True)
    conn = lb.Connection(database)
    touched: set[str] = set()
    try:
        for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
            result = conn.execute(
                f"MATCH (a:Concept)-[:{rel}]->(b:Concept) RETURN a.id, b.id")
            while result.has_next():
                source, target = result.get_next()
                touched.add(str(source))
                touched.add(str(target))
    finally:
        del conn, database
    return sorted(n for n in governing if n not in touched)
