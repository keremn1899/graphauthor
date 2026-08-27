"""Overlays — ids and roles, never geometry.

Focus is an **addition** to the ambient map, not a replacement for it: the
operator keeps the arrangement they have learned and something is lit on top.
That is enforced here rather than left to discipline — an overlay carries node
ids, edge references and a role for each, and has no way to express a position.
Nothing downstream of this module can move a node.

One shape, four consumers: the evidence behind an answer, the frontier where a
traversal ran out, a proposal or version diff, and a historical state. They
differ only in which roles appear.

Why this matters for the product: the moat is *exact traversal* — the graph can
say which relations decided a query, or honestly refuse. A picture of the route
to the verdict is something similarity search structurally cannot draw, because
it has no route. Everything here is a deterministic projection over facts the
engine already returned; nothing is inferred and nothing is invented.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

#: Node roles an overlay may assign.
#:
#: `lit` — used by the answer. `frontier` — used, and adjacent to material the
#: answer did not use. `added`/`removed`/`touched` — change review.
#: `ghost` — present in a past version, absent now.
NODE_ROLES = ("lit", "frontier", "added", "removed", "touched", "ghost")


def edge_ref(source: str, target: str, edge_type: str) -> str:
    """Stable reference for an edge. Positions never appear in an overlay."""
    return f"{source}→{target}:{edge_type}"


def _edge_endpoints(edges: Iterable[dict[str, Any]]):
    for e in edges:
        src = e.get("source")
        tgt = e.get("target")
        if src and tgt:
            yield str(src), str(tgt), str(e.get("type") or "")


def evidence_overlay(evidence: dict[str, Any] | None,
                     edges: list[dict[str, Any]],
                     gaps: list[dict[str, Any]] | None = None,
                     known_ids: set[str] | None = None,
                     claim_text: str = "") -> dict[str, Any]:
    """What the answer stood on, and where it ran out.

    **Frontier is defined precisely, and narrowly.** It is an evidence node with
    at least one neighbour the answer did not use. That is a fact about the
    boundary of the evidence subgraph — it is *not* a claim to know what the
    traversal considered and rejected, which this module cannot see. Naming it
    anything grander would be inventing knowledge, which is the one thing this
    product refuses to do.

    Gaps are anchored to a node only when they name one that exists. A gap that
    names nothing on the map is returned unanchored rather than being attached
    to a plausible-looking neighbour — an invented anchor would be a fabricated
    explanation of why an answer failed.

    ``claim_text`` (confirmed turns only) restricts lighting to nodes the
    sentence named, plus any retrieved path. Without it, the overlay is the
    retrieved set — where the engine looked.
    """
    evidence = evidence or {}
    retrieved = _evidence_ids(evidence)
    stood_on = _stood_on_ids(evidence, claim_text) if (claim_text or "").strip() else set()
    # A confirmed sentence that names some of the packet: light those, not
    # every expand neighbour that happened to arrive with them. If nothing
    # in the packet is named, keep the retrieved set — going dark would
    # hide where the answer looked.
    lit = stood_on or retrieved
    if known_ids is not None:
        lit &= known_ids

    adjacency: dict[str, set[str]] = {}
    for src, tgt, _t in _edge_endpoints(edges):
        adjacency.setdefault(src, set()).add(tgt)
        adjacency.setdefault(tgt, set()).add(src)

    frontier = {
        nid for nid in lit
        if any(nb not in lit for nb in adjacency.get(nid, ()))
    }

    # When *everything* is frontier the word has stopped meaning anything.
    # Observed live on a six-node graph: both evidence nodes came back frontier
    # and none came back lit, because on a small or sparse graph every used node
    # has an unused neighbour. Marking the whole answer "this is where we ran
    # out" tells the operator nothing and overstates the boundary, so the
    # distinction is withdrawn rather than reported emptily — the same
    # discipline as `tier: null` when no channel separates a graph.
    saturated = bool(lit) and frontier == lit
    if saturated:
        frontier = set()

    nodes = {nid: ("frontier" if nid in frontier else "lit") for nid in lit}

    # An edge is lit when the answer used both of its ends. Derived from the
    # graph rather than from `edge_records`, whose shape varies by tool.
    edge_roles = {
        edge_ref(src, tgt, t): "lit"
        for src, tgt, t in _edge_endpoints(edges)
        if src in lit and tgt in lit
    }

    anchored, unanchored = _anchor_gaps(gaps or [], lit, known_ids or set())

    return {
        "kind": "evidence",
        "nodes": nodes,
        "edges": edge_roles,
        "gaps": anchored,
        "unanchored_gaps": unanchored,
        "counts": {
            "lit": len(lit),
            "frontier": len(frontier),
            "edges": len(edge_roles),
        },
        # True when every evidence node bordered unused material, so the
        # frontier distinction was withdrawn rather than applied to everything.
        "frontier_saturated": saturated,
    }


def _evidence_ids(evidence: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for nid in evidence.get("node_ids") or ():
        if nid:
            ids.add(str(nid))
    for record in evidence.get("node_records") or ():
        if isinstance(record, dict) and record.get("id"):
            ids.add(str(record["id"]))
    for record in evidence.get("edge_records") or ():
        if not isinstance(record, dict):
            continue
        for key in ("source", "target", "source_id", "target_id"):
            if record.get(key):
                ids.add(str(record[key]))
    ids |= _path_ids(evidence)
    return ids


def _path_ids(evidence: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for path in evidence.get("path_records") or ():
        if not isinstance(path, dict):
            continue
        for nid in path.get("node_chain") or path.get("node_ids") or ():
            if nid:
                ids.add(str(nid))
        for key in ("source", "target"):
            if path.get(key):
                ids.add(str(path[key]))
    return ids


def _named_in_claim(name: str, claim: str) -> bool:
    token = (name or "").strip()
    if len(token) < 3:
        return False
    return re.search(
        r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])",
        claim,
        re.I,
    ) is not None


def _stood_on_ids(evidence: dict[str, Any], claim_text: str) -> set[str]:
    """Nodes the sentence used, not the whole retrieved neighbourhood.

    Expand of a region dumps every child onto the packet. Lighting those as
    evidence would say the answer stood on nodes it never named. Path
    chains are the proof even when an intermediate label is omitted.
    """
    claim = claim_text or ""
    named: set[str] = set()
    for record in evidence.get("node_records") or ():
        if not isinstance(record, dict) or not record.get("id"):
            continue
        nid = str(record["id"])
        labels = [
            str(record.get("label") or ""),
            str(record.get("semantic_anchor") or ""),
            nid,
        ]
        if any(_named_in_claim(label, claim) for label in labels if label):
            named.add(nid)
    for nid in evidence.get("node_ids") or ():
        if nid and _named_in_claim(str(nid), claim):
            named.add(str(nid))
    named |= _path_ids(evidence)
    return named


def _anchor_gaps(gaps: list[dict[str, Any]], lit: set[str],
                 known_ids: set[str]):
    """Attach a gap to a node only when it names one that exists."""
    anchored: list[dict[str, Any]] = []
    unanchored: list[dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        named = str(gap.get("specific_node_or_concept") or "").strip()
        entry = {
            "type": gap.get("type") or "",
            "names": named,
            "context": gap.get("context") or "",
            "suggestion": gap.get("actionable_suggestion") or "",
        }
        if named and named in known_ids:
            entry["anchor"] = named
            entry["anchor_is_evidence"] = named in lit
            anchored.append(entry)
        else:
            unanchored.append(entry)
    return anchored, unanchored


def diff_overlay(before_ids: Iterable[str], after_ids: Iterable[str],
                 touched_ids: Iterable[str] = ()) -> dict[str, Any]:
    """A change against the map the operator already knows.

    Removed nodes keep a role rather than vanishing, because the ordering ledger
    keeps their slot as a tombstone — so the canvas can show a ghost exactly
    where the thing used to be instead of closing ranks over it.
    """
    before, after = set(before_ids), set(after_ids)
    nodes: dict[str, str] = {}
    for nid in sorted(after - before):
        nodes[nid] = "added"
    for nid in sorted(before - after):
        nodes[nid] = "removed"
    for nid in sorted(set(touched_ids) & after):
        nodes.setdefault(nid, "touched")
    return {
        "kind": "diff",
        "nodes": nodes,
        "edges": {},
        "counts": {
            "added": sum(1 for r in nodes.values() if r == "added"),
            "removed": sum(1 for r in nodes.values() if r == "removed"),
            "touched": sum(1 for r in nodes.values() if r == "touched"),
        },
    }


def history_overlay(present_ids: Iterable[str],
                    current_ids: Iterable[str]) -> dict[str, Any]:
    """A past state, as a subset of the present geometry plus ghosts.

    Scrubbing must not re-lay-out: the map is a place, and a timeline that moved
    it would be unreadable. Anything in the current map but not in the state
    being viewed is simply absent from the overlay; anything in the past state
    but gone now is a ghost, standing in its tombstoned slot.
    """
    present, current = set(present_ids), set(current_ids)
    nodes = {nid: "lit" for nid in sorted(present & current)}
    nodes.update({nid: "ghost" for nid in sorted(present - current)})
    return {
        "kind": "history",
        "nodes": nodes,
        "edges": {},
        "counts": {
            "shown": len(present & current),
            "ghosts": len(present - current),
        },
    }
