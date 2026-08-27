"""Structural grain enforcement — REPAIR what grain_check DETECTS (B5 lead).

The live construction experiment surfaced the lead: exemplar-binding pulls
generation toward the target grain but does not *guarantee* it — at a weak model
tier the generator still fuses rules and overruns the sanity ceiling, so the
graph is (correctly) refused at certification. Chasing a better model helps but
is not a guarantee; this module is the model-INDEPENDENT guarantee.

The principle: enforcement repairs ONLY the HARD gates grain_check blocks on —

  - **rule_fusion (D4, verdict-critical):** a node carrying >1 ADJUDICATES
    clause is split on its clause boundaries into one rule node per clause,
    held by a CONTAINS group. This is deterministic and safe (the clauses are
    textually delimited) and it is the ONE gate that threatens verdict
    integrity, so making it a guarantee is the highest-value repair.
  - **over_ceiling (D3, sanity):** a node past the absolute char ceiling is
    segmented at PARAGRAPH boundaries (never mid-sentence) into a CONTAINS
    parent + parts. If no safe boundary exists it is left intact and reported
    as residual — honest failure over a mid-thought butchering.

Enforcement deliberately does NOT touch SOFT drift (length/fan-out). Per D2/D3
those are advisory and legitimately region-varying; auto-"fixing" them would
override a judgement the charter leaves to the human. So an enforced graph can
still carry soft flags — it just no longer carries the hard, blocking ones.

Neutral representation: nodes are ``{id, label, text_content}`` dicts and edges
are ``(TYPE_UPPER, src, tgt, label)`` tuples — the exact shapes grain_check
consumes, so enforce → re-check is a closed loop.
"""

from __future__ import annotations

import re
from typing import Any

from mcp_server.grain import HARD_MAX_CHARS, _ADJUDICATES, grain_check

# Segment oversized prose only at these boundaries, strongest first. A node with
# none of them (one unbroken block past the ceiling) is left intact and reported
# residual rather than cut mid-thought.
_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# rule fission (D4)
# ---------------------------------------------------------------------------

def split_clauses(text: str) -> tuple[str, list[str]]:
    """(preamble, [clause_text, ...]) splitting on ADJUDICATES occurrences.
    Preamble is everything before the first clause; each clause runs from one
    ADJUDICATES marker to the next."""
    matches = list(_ADJUDICATES.finditer(text or ""))
    if len(matches) <= 1:
        return (text or "").strip(), []
    preamble = text[: matches[0].start()].strip()
    clauses = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        clauses.append(text[m.start(): end].strip())
    return preamble, clauses


def split_fused_rule(node: dict) -> tuple[dict, list[dict], list[tuple]] | None:
    """Fused rule node → (container, [child rule nodes], [CONTAINS edges]).

    The original id is RETAINED as the container so every pre-existing edge
    that referenced it stays valid (governance references attach at the group);
    each clause becomes an individually addressable rule child. Returns None if
    the node is not actually fused (≤1 clause)."""
    nid = node.get("id", "")
    label = node.get("label", "") or nid
    preamble, clauses = split_clauses(str(node.get("text_content") or ""))
    if len(clauses) <= 1:
        return None
    container = {
        "id": nid, "label": label,
        # a container carries the shared framing (preamble) or, absent one, a
        # thin group descriptor — never left empty.
        "text_content": preamble or f"{label}: groups {len(clauses)} adjudication rules.",
    }
    children: list[dict] = []
    edges: list[tuple] = []
    for k, clause in enumerate(clauses, start=1):
        cid = f"{nid}__r{k}"
        children.append({"id": cid, "label": f"{label} — rule {k}", "text_content": clause})
        edges.append(("CONTAINS", nid, cid, "rule"))
    return container, children, edges


# ---------------------------------------------------------------------------
# ceiling segmentation (D3)
# ---------------------------------------------------------------------------

def _pack(units: list[str], max_chars: int) -> list[str]:
    """Greedily pack text units into chunks each ≤ max_chars (a unit larger than
    max_chars becomes its own chunk — the caller decides if that is residual)."""
    chunks: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + len(u) + 2 > max_chars:
            chunks.append(cur)
            cur = u
        else:
            cur = f"{cur}\n\n{u}" if cur else u
    if cur:
        chunks.append(cur)
    return chunks


def _safe_units(text: str, max_chars: int) -> list[str]:
    """Paragraph units, but any paragraph still past the ceiling is itself split
    on sentence boundaries — so one oversized paragraph does not defeat the whole
    segmentation. A unit with no internal boundary is left oversized (the caller
    treats a residual over-ceiling chunk as unbreakable)."""
    units: list[str] = []
    for para in (p.strip() for p in _PARA.split(text) if p.strip()):
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(s.strip() for s in _SENT.split(para) if s.strip())
    return units


def segment_oversized(node: dict, max_chars: int = HARD_MAX_CHARS
                      ) -> tuple[dict, list[dict], list[tuple]] | None:
    """Over-ceiling node → (parent, [part nodes], [CONTAINS edges]) split at
    paragraph (else sentence) boundaries. Returns None when the node cannot be
    split safely (no boundary, or splitting still leaves a part over ceiling) —
    honest residual over a mid-thought cut."""
    nid = node.get("id", "")
    label = node.get("label", "") or nid
    text = str(node.get("text_content") or "")
    if len(text) <= max_chars:
        return None
    units = _safe_units(text, max_chars)
    if len(units) < 2:
        return None                                   # unbreakable → residual
    chunks = _pack(units, max_chars)
    if len(chunks) < 2 or any(len(c) > max_chars for c in chunks):
        return None                                   # could not get under ceiling
    parent = {"id": nid, "label": label,
              "text_content": f"{label}: {len(chunks)} parts (segmented at ceiling)."}
    parts: list[dict] = []
    edges: list[tuple] = []
    for k, chunk in enumerate(chunks, start=1):
        pid = f"{nid}__p{k}"
        parts.append({"id": pid, "label": f"{label} — part {k}", "text_content": chunk})
        edges.append(("CONTAINS", nid, pid, "part"))
    return parent, parts, edges


# ---------------------------------------------------------------------------
# the pass
# ---------------------------------------------------------------------------

def enforce_grain(nodes: list[dict], edges: list[tuple] | None = None, *,
                  seeds: list[dict] | None = None,
                  base_nodes: dict[str, dict] | None = None,
                  base_edges: list[tuple] | None = None,
                  anchoring: list[str] | None = None,
                  max_chars: int = HARD_MAX_CHARS) -> dict[str, Any]:
    """Repair the HARD grain violations in ``nodes`` and return the repaired
    graph plus a report. Soft drift is left untouched by design.

    Returns::

        {nodes, edges, applied:[{id,kind,into:[...]}],
         residual_hard:[...], before:{...}, after:{...}}
    """
    nodes = [dict(n) for n in (nodes or [])]
    edges = list(edges or [])
    before = grain_check(nodes, seeds=seeds, base_nodes=base_nodes,
                         base_edges=base_edges, added_edges=edges, anchoring=anchoring)

    by_id = {n["id"]: n for n in nodes}
    applied: list[dict] = []

    # rule fusion first (verdict-critical), then over-ceiling. A split child is
    # itself re-examined below, so a fused AND oversized node is handled in two
    # passes cleanly.
    for v in before["hard_violations"]:
        node = by_id.get(v["id"])
        if node is None:
            continue
        if v["kind"] == "rule_fusion":
            res = split_fused_rule(node)
            if res:
                container, children, new_edges = res
                by_id[container["id"]] = container
                for c in children:
                    by_id[c["id"]] = c
                edges.extend(new_edges)
                applied.append({"id": v["id"], "kind": "rule_fusion",
                                "into": [c["id"] for c in children]})
        elif v["kind"] == "over_ceiling":
            res = segment_oversized(node, max_chars)
            if res:
                parent, parts, new_edges = res
                by_id[parent["id"]] = parent
                for p in parts:
                    by_id[p["id"]] = p
                edges.extend(new_edges)
                applied.append({"id": v["id"], "kind": "over_ceiling",
                                "into": [p["id"] for p in parts]})

    out_nodes = list(by_id.values())
    # a child produced by segmentation can still exceed the ceiling if a single
    # paragraph is enormous; a second segmentation pass catches that layer.
    changed = True
    while changed:
        changed = False
        rep = grain_check(out_nodes, seeds=seeds, base_nodes=base_nodes,
                          base_edges=base_edges, added_edges=edges, anchoring=anchoring)
        idx = {n["id"]: n for n in out_nodes}
        for v in rep["hard_violations"]:
            node = idx.get(v["id"])
            if node is None:
                continue
            res = (split_fused_rule(node) if v["kind"] == "rule_fusion"
                   else segment_oversized(node, max_chars) if v["kind"] == "over_ceiling"
                   else None)
            if res:
                head, kids, new_edges = res
                idx[head["id"]] = head
                for c in kids:
                    idx[c["id"]] = c
                edges.extend(new_edges)
                applied.append({"id": v["id"], "kind": v["kind"],
                                "into": [c["id"] for c in kids]})
                changed = True
        out_nodes = list(idx.values())

    after = grain_check(out_nodes, seeds=seeds, base_nodes=base_nodes,
                        base_edges=base_edges, added_edges=edges, anchoring=anchoring)
    return {
        "nodes": out_nodes,
        "edges": edges,
        "applied": applied,
        "residual_hard": after["hard_violations"],
        "before": {"hard": len(before["hard_violations"]),
                   "kinds": sorted({h["kind"] for h in before["hard_violations"]})},
        "after": {"hard": len(after["hard_violations"]), "conforms": after["conforms"],
                  "kinds": sorted({h["kind"] for h in after["hard_violations"]})},
    }
