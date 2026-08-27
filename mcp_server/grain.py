"""Grain check (construction/evolution charter §5, grain profile).

Grain stops being a PROSE CONTRACT and becomes a REFERENCE SET of exemplar
nodes. One check runs on any ChangeSet — identically whether the base is EMPTY
(create) or a live graph_version (evolve), because construction is just editing
against the empty graph (`ChangeSet.materialization`). The check answers: do the
ADDED nodes fit `seed_exemplars ∪ sample(base)`?

Four founder decisions are encoded here:

- **D1 — seeds retain a permanent floor weight.** A graph that has slowly
  drifted off-grain must not become its own (wrong) reference. Seeds are the
  constitutional anchor; intentional grain change goes through the declared /
  audited merge/split path, never silent drift.
- **D2 — the reference is LOCAL.** New nodes are judged against the grain of
  their attachment neighbourhood (with a global fallback), because grain
  coherence matters locally — some regions of a graph legitimately run finer or
  coarser than others.
- **D3 — hard, grain-independent sanity bounds** (a constitutional length
  ceiling / floor) sit UNDER the soft reference band. They apply at N=0 and
  never derive from seeds: a 4000-char node is wrong at any grain.
- **D4 — rule fusion (ADJUDICATES-count > 1) is the one HARD structural gate.**
  It is the only structural signal that threatens verdict integrity (two rules
  fused into one node corrupt the governed set). Length / fan-out are SOFT.

Two-tier verdict: hard violations BLOCK (findings); soft flags WARN (advisory
score). The soft band's width scales with the reference's confidence (size), so
a thin seed sample yields a LOOSE band — never the live_v2 floor problem where a
tight bound from few samples rejects everything.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

# D3 — constitutional sanity CEILING (grain-independent, absolute). An essay is
# wrong at any grain. There is deliberately NO hard floor: short-ness is
# grain-DEPENDENT (fine grain legitimately has short nodes), so being too short
# is a SOFT length_drift signal against the reference, never a hard block.
HARD_MAX_CHARS = 4000

# D1 — seeds hold at least this share of the reference mass, however large base.
SEED_FLOOR = 0.25

# Soft-band shaping: full statistical confidence at this reference size; below
# it the band widens (permissive), above it the band tightens.
CONF_FULL_N = 30
SLACK_MAX = 3.0          # extra band multiplier at zero confidence
MIN_LOCAL = 3            # fewer local neighbours than this → fall back to global

_ADJUDICATES = re.compile(r"ADJUDICATES", re.I)


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def node_features(node: dict, out_degree: int = 0) -> dict[str, Any]:
    """The deterministic grain vector for one node.

    `adjudicates` counts ADJUDICATES markers in the payload, and the rule-fusion
    gate reads it. Those markers were the workaround for `Concept` having no
    column for governing role; a graph built since `claim_kind` exists carries
    none of them, so the count is 0 and **the one verdict-critical hard
    structural gate silently cannot fire.** Measured on the newest reference
    graph: 0 ADJUDICATES markers across 24 nodes, `claim_kind` set on all 24.

    So the vector also reports whether the signal was *available*. A node that
    declares `claim_kind` and carries no markers is UNEVALUABLE for fusion, not
    clean, and that difference must not stay invisible.

    The loss is at the materialization seam: the workspace knows the per-node
    governing-claim count exactly — it reports `governing_claim_count` — and the
    graph keeps a single `claim_kind` string. Counting fused rules downstream is
    impossible because the count was never written.
    """
    text = str(node.get("text_content") or "")
    adjudicates = len(_ADJUDICATES.findall(text))
    declared = str(node.get("claim_kind") or "").strip()
    return {
        "id": node.get("id", ""),
        "length": len(text),
        "adjudicates": adjudicates,
        "fusion_measurable": bool(adjudicates) or not declared,
        "fanout": out_degree,
    }


def _out_degrees(edges: list[tuple] | None) -> dict[str, int]:
    """CONTAINS+EXPRESSES out-degree per source id — the structural fan-out
    that distinguishes a coarse container from a fine leaf."""
    deg: dict[str, int] = {}
    for e in edges or []:
        typ, src = e[0], e[1]
        if typ in ("CONTAINS", "EXPRESSES"):
            deg[src] = deg.get(src, 0) + 1
    return deg


# ---------------------------------------------------------------------------
# reference construction (D1 floor + D2 local)
# ---------------------------------------------------------------------------

def _neighbourhood(base_nodes: dict[str, dict], base_edges: list[tuple],
                   anchoring: list[str]) -> list[dict]:
    """D2 — base nodes in the attachment neighbourhood: the anchors plus their
    direct neighbours. Empty/too-small → caller falls back to global."""
    if not anchoring:
        return []
    keep = set(a for a in anchoring if a in base_nodes)
    for (typ, s, t, _l) in base_edges or []:
        if s in keep and t in base_nodes:
            keep.add(t)
        if t in keep and s in base_nodes:
            keep.add(s)
    return [base_nodes[nid] for nid in keep]


def build_reference(seeds: list[dict], base_nodes: dict[str, dict] | None,
                    base_edges: list[tuple] | None, anchoring: list[str] | None
                    ) -> dict[str, Any]:
    """Assemble the reference: seeds (floor-weighted) ∪ local base sample."""
    base_nodes = base_nodes or {}
    seeds = seeds or []
    scope = "global"
    sample: list[dict] = []
    if base_nodes:
        local = _neighbourhood(base_nodes, base_edges or [], anchoring or [])
        if len(local) >= MIN_LOCAL:
            sample, scope = local, "local"
        else:
            sample, scope = list(base_nodes.values()), "global"

    deg = _out_degrees(base_edges)
    base_vecs = [node_features(n, deg.get(n.get("id", ""), 0)) for n in sample]
    seed_vecs = [node_features(n, 0) for n in seeds]

    # D1 — replicate seed vectors so they hold >= SEED_FLOOR of the pool mass,
    # no matter how large the base sample is. Distinct count drives confidence.
    n_base = len(base_vecs)
    if seed_vecs and n_base:
        need = math.ceil((SEED_FLOOR / (1 - SEED_FLOOR)) * n_base)
        reps = max(1, math.ceil(need / len(seed_vecs)))
    else:
        reps = 1
    pool = seed_vecs * reps + base_vecs
    return {
        "scope": scope,
        "n_seeds": len(seed_vecs),
        "n_base_sampled": n_base,
        "n_distinct": len(seed_vecs) + n_base,
        "pool": pool,
        "seed_vecs": seed_vecs,
        "base_vecs": base_vecs,
    }


# ---------------------------------------------------------------------------
# soft band
# ---------------------------------------------------------------------------

def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def _soft_band(pool_values: list[float], n_distinct: int) -> tuple[float, float, float]:
    """Returns (median, allowed_deviation, confidence). Band half-width scales
    up when the reference is thin (low confidence) — a loose band from few
    samples, never a tight one."""
    if not pool_values:
        return 0.0, float("inf"), 0.0
    m = _percentile(pool_values, 0.5)
    lo = _percentile(pool_values, 0.10)
    hi = _percentile(pool_values, 0.90)
    half = (hi - lo) / 2.0
    # a minimum sane band so near-identical seeds don't flag everything
    half = max(half, 0.25 * m, 40.0)
    conf = min(1.0, n_distinct / CONF_FULL_N)
    slack = 1.0 + SLACK_MAX * (1.0 - conf)
    return m, half * slack, conf


# ---------------------------------------------------------------------------
# the check
# ---------------------------------------------------------------------------

def grain_check(added: list[dict], *, seeds: list[dict] | None = None,
                base_nodes: dict[str, dict] | None = None,
                base_edges: list[tuple] | None = None,
                added_edges: list[tuple] | None = None,
                anchoring: list[str] | None = None) -> dict[str, Any]:
    """The single grain check. `added` are the ChangeSet's new nodes
    ({id, label, text_content}); the reference is `seeds ∪ sample(base)`.

    Returns:
      conforms: bool            — no HARD violations (soft flags do not block)
      hard_violations: [...]    — over_ceiling / under_floor / rule_fusion
      soft_flags: [...]         — length_drift / fanout_drift (advisory)
      score: float 0..1         — 1 - (soft-flagged fraction)
      reference: {...}          — scope, counts, confidence
    """
    added = added or []
    ref = build_reference(seeds or [], base_nodes, base_edges, anchoring)
    pool = ref["pool"]
    len_m, len_tol, conf = _soft_band([v["length"] for v in pool], ref["n_distinct"])

    # D1 — drift is allowed (regions vary) but never SILENT: report how far the
    # base's grain has moved from the constitutional seeds. Clearing it is a
    # declared act (update the seeds), not a quiet slide.
    seed_lens = [v["length"] for v in ref["seed_vecs"]]
    base_lens = [v["length"] for v in ref["base_vecs"]]
    drift_from_seeds = False
    seed_med = base_med = 0.0
    if seed_lens and base_lens:
        seed_med = _percentile(seed_lens, 0.5)
        base_med = _percentile(base_lens, 0.5)
        _, seed_tol, _ = _soft_band(seed_lens, len(seed_lens))
        drift_from_seeds = abs(base_med - seed_med) > seed_tol
    fan_pool = [v["fanout"] for v in pool if v["fanout"] > 0]
    fan_m, fan_tol, _ = _soft_band(fan_pool, ref["n_distinct"]) if fan_pool else (0.0, float("inf"), conf)

    add_deg = _out_degrees(added_edges)
    hard: list[dict] = []
    soft: list[dict] = []
    fusion_unevaluable = 0
    for node in added:
        f = node_features(node, add_deg.get(node.get("id", ""), 0))
        nid = f["id"]
        # D3 — hard sanity ceiling (grain-independent). No hard floor: short-ness
        # is grain-dependent and surfaces as a soft length_drift below.
        if f["length"] > HARD_MAX_CHARS:
            hard.append({"id": nid, "kind": "over_ceiling",
                         "detail": f"{f['length']} > {HARD_MAX_CHARS} chars"})
        # D4 — rule fusion (the one verdict-critical hard structural gate)
        if f["adjudicates"] > 1:
            hard.append({"id": nid, "kind": "rule_fusion",
                         "detail": f"{f['adjudicates']} ADJUDICATES clauses in one node"})
        elif not f["fusion_measurable"]:
            # Not a pass. The node declares its governing role in `claim_kind`
            # and carries no ADJUDICATES markers, so this gate had nothing to
            # count. Reported in aggregate below rather than per node, because
            # on a modern graph it is every node and would drown the flags that
            # do mean something.
            fusion_unevaluable += 1
        # soft — length drift vs the (confidence-scaled) reference band
        if pool and abs(f["length"] - len_m) > len_tol:
            soft.append({"id": nid, "kind": "length_drift",
                         "detail": f"len {f['length']} vs {len_m:.0f}±{len_tol:.0f}"})
        # soft — fan-out drift, only meaningful against a structured base
        if fan_pool and f["fanout"] > 0 and abs(f["fanout"] - fan_m) > fan_tol:
            soft.append({"id": nid, "kind": "fanout_drift",
                         "detail": f"fanout {f['fanout']} vs {fan_m:.1f}±{fan_tol:.1f}"})

    n = len(added) or 1
    flagged = {s["id"] for s in soft}
    # An EMPTY reference (no seeds and no base — construction with no exemplars
    # against the empty graph) yields an infinite tolerance by design: with
    # nothing to compare against, nothing may be flagged. Report that as an
    # explicitly UNBOUNDED band rather than rounding infinity to an int.
    band = ([None, None] if math.isinf(len_tol)
            else [round(len_m - len_tol), round(len_m + len_tol)])
    return {
        "conforms": not hard,
        "hard_violations": hard,
        "soft_flags": soft,
        "score": round(1.0 - len(flagged) / n, 3),
        # How much of the rule-fusion gate actually ran. `conforms` says nothing
        # about nodes this could not evaluate, and on a graph built since
        # `claim_kind` replaced the ADJUDICATES prefix that is all of them — so
        # a clean fusion result must be read together with this count, not
        # instead of it.
        "fusion_gate": {
            "unevaluable": fusion_unevaluable,
            "of": len(added),
            "reason": ("payload carries no ADJUDICATES markers and the node "
                       "declares claim_kind; the per-node governing-claim count "
                       "is not materialized, so fusion cannot be counted here")
            if fusion_unevaluable else "",
        },
        "reference": {"scope": ref["scope"], "n_seeds": ref["n_seeds"],
                      "n_base_sampled": ref["n_base_sampled"],
                      "n_distinct": ref["n_distinct"], "confidence": round(conf, 3),
                      "length_band": band,
                      "drift_from_seeds": drift_from_seeds,
                      "seed_median": round(seed_med), "base_median": round(base_med)},
    }


# ---------------------------------------------------------------------------
# ChangeSet adapter — the shared entry create-cert and the edit gate both call
# ---------------------------------------------------------------------------

def added_nodes_from_changeset(cs) -> tuple[list[dict], list[tuple]]:
    """Extract (added_nodes, added_edges) from a ChangeSet. ADD_CONCEPT →
    node; REPLACE_CONTENT → the replacement text as a node at target_node_id;
    ADD_EDGE → edge tuple. Works for CREATE (all adds) and EVOLVE alike."""
    from mcp_server.changeset import OpKind

    nodes: list[dict] = []
    edges: list[tuple] = []
    for op in cs.operations:
        if op.kind == OpKind.ADD_CONCEPT and op.concept is not None:
            nodes.append({"id": op.concept.id, "label": op.concept.label,
                          "text_content": op.concept.text_content})
        elif op.kind == OpKind.REPLACE_CONTENT and op.target_node_id:
            text = str((op.payload or {}).get("text_content") or "")
            nodes.append({"id": op.target_node_id, "label": op.target_node_id,
                          "text_content": text})
        elif op.kind == OpKind.ADD_EDGE and op.edge is not None:
            edges.append((op.edge.type, op.edge.source_id, op.edge.target_id, op.edge.label))
    return nodes, edges


def grain_check_changeset(cs, *, seeds: list[dict] | None = None,
                          base_nodes: dict[str, dict] | None = None,
                          base_edges: list[tuple] | None = None) -> dict[str, Any]:
    """Run the grain check on a ChangeSet against `seeds ∪ sample(base)`. The
    IDENTICAL call for create (base_nodes empty) and evolve (base_nodes live)."""
    added, added_edges = added_nodes_from_changeset(cs)
    return grain_check(added, seeds=seeds, base_nodes=base_nodes,
                       base_edges=base_edges, added_edges=added_edges,
                       anchoring=list(getattr(cs, "anchoring", []) or []))


# ---------------------------------------------------------------------------
# grain identity persistence — a graph carries its seeds so the EVOLVE path can
# check new writes against the SAME constitutional anchor create-cert used.
# ---------------------------------------------------------------------------

def grain_identity_path(db_path: Path | str) -> Path:
    return Path(db_path).with_suffix(".grain.json")


def save_grain_identity(db_path: Path | str, seeds: list[dict]) -> None:
    """Persist the graph's seed exemplars beside the .lbug (a runtime sidecar,
    like the .idx — not tracked)."""
    grain_identity_path(db_path).write_text(json.dumps({"seeds": seeds or []}, indent=2))


def load_grain_identity(db_path: Path | str) -> list[dict]:
    """Load persisted seeds; [] when a graph has no recorded grain identity
    (then the evolve gate runs emergent — only the hard gates can block)."""
    p = grain_identity_path(db_path)
    if p.exists():
        try:
            return list(json.loads(p.read_text()).get("seeds") or [])
        except (ValueError, OSError):
            return []
    return []


# ---------------------------------------------------------------------------
# evolve-side gates — the SAME grain_check, now against the live graph
# ---------------------------------------------------------------------------

def grain_gate(db_path: Path | str, added: list[dict],
               added_edges: list[tuple] | None = None, *,
               seeds: list[dict] | None = None,
               anchoring: list[str] | None = None) -> dict[str, Any]:
    """Evolve ADD gate: check added nodes against the LIVE graph + persisted
    seeds. Only HARD violations (sanity, rule fusion) block an add — soft drift
    is advisory (an incremental add slightly off-grain is not dangerous; it is
    flagged, not refused). The local reference is auto-derived: added edges that
    point at existing nodes are the attachment neighbourhood."""
    from mcp_server.crossing import _all_edges, _all_nodes, _connect

    seeds = seeds if seeds is not None else load_grain_identity(db_path)
    conn = _connect(db_path)
    try:
        base_nodes = _all_nodes(conn)
        base_edges = _all_edges(conn)
    finally:
        conn.close()
    added_ids = {n["id"] for n in added}
    base_nodes = {k: v for k, v in base_nodes.items()
                  if k not in added_ids and not v.get("is_metanode")}
    if anchoring is None:
        anchoring = []
        for e in (added_edges or []):
            for endpoint in (e[1], e[2]):
                if endpoint in base_nodes and endpoint not in anchoring:
                    anchoring.append(endpoint)
    rep = grain_check(added, seeds=seeds, base_nodes=base_nodes, base_edges=base_edges,
                      added_edges=added_edges, anchoring=anchoring)
    rep["allowed"] = rep["conforms"]        # hard blocks; soft advises
    rep["reason"] = "grain_clean" if rep["conforms"] else \
        "grain_hard:" + ",".join(f"{h['kind']}:{h['id']}" for h in rep["hard_violations"])
    return rep


def _declared_grain(cs) -> set[str]:
    """Grain changes a change-set explicitly declares: a blanket ``grain`` token
    or per-node ``grain:<id>`` in any op's payload declared_changes."""
    out: set[str] = set()
    for op in cs.operations:
        for tok in (op.payload or {}).get("declared_changes", []) or []:
            if tok == "grain" or str(tok).startswith("grain:"):
                out.add(tok)
    return out


def grain_gate_for_edit(db_path: Path | str, cs, *,
                        seeds: list[dict] | None = None) -> dict[str, Any]:
    """Evolve EDIT gate: merge/split/replace can deliberately reshape grain, so
    an UNDECLARED grain shift is refused exactly like an undeclared verdict flip
    — but a DECLARED one is allowed and audited. Hard violations (sanity, rule
    fusion) block regardless of declaration: you cannot declare your way into a
    fused rule."""
    added, added_edges = added_nodes_from_changeset(cs)
    rep = grain_gate(db_path, added, added_edges, seeds=seeds,
                     anchoring=list(getattr(cs, "anchoring", []) or []) or None)
    if rep["hard_violations"]:
        rep["allowed"] = False
        rep["reason"] = "grain_hard:" + ",".join(
            f"{h['kind']}:{h['id']}" for h in rep["hard_violations"])
        return rep
    declared = _declared_grain(cs)
    blanket = "grain" in declared
    undeclared = [s for s in rep["soft_flags"]
                  if not blanket and f"grain:{s['id']}" not in declared]
    if undeclared:
        rep["allowed"] = False
        rep["reason"] = "undeclared_grain_change:" + ",".join(
            f"{s['kind']}:{s['id']}" for s in undeclared)
    else:
        rep["allowed"] = True
        rep["reason"] = "grain_declared" if rep["soft_flags"] else "grain_clean"
        rep["audited"] = bool(rep["soft_flags"])
    return rep


def review_seeds(seeds: list[dict]) -> dict[str, Any]:
    """Seed review (the L0 constitutional step): the grain check applied
    REFLEXIVELY to the seed set. Seeds define the graph's grain identity, so
    they must be internally consistent and within sanity bounds before a human
    confirms them. Reflexive = each seed judged against the others."""
    seeds = seeds or []
    out = grain_check(seeds, seeds=seeds)
    # reflexive individuation: seeds must themselves be one-rule-per-node
    out["internally_consistent"] = out["conforms"] and not out["soft_flags"]
    return out


# Reference-trustworthiness tiers (distinct exemplar count). Below THIN the
# grain score is directional only; at/above STRONG it is statistically
# meaningful. These key off the same CONF_FULL_N the soft band uses.
REF_THIN_N = 6
REF_STRONG_N = 15


def grain_reference_health(seeds: list[dict]) -> dict[str, Any]:
    """A grain reference is only as trustworthy as its exemplar set, so make its
    quality visible. Reports confidence (is the score statistically meaningful?),
    reflexive consistency, and coverage (role diversity + length spread), with
    actionable recommendations. Deterministic, advisory — NEVER blocks: a thin
    reference does not make a graph wrong, only its score less trustworthy."""
    seeds = seeds or []
    n = len(seeds)
    review = review_seeds(seeds)
    conf = round(min(1.0, n / CONF_FULL_N), 3)
    level = ("empty" if n == 0 else "thin" if n < REF_THIN_N
             else "moderate" if n < REF_STRONG_N else "strong")

    rules = [s for s in seeds if _ADJUDICATES.search(str(s.get("text_content") or ""))]
    non_rules = [s for s in seeds if not _ADJUDICATES.search(str(s.get("text_content") or ""))]
    lengths = sorted(len(str(s.get("text_content") or "")) for s in seeds)

    recs: list[str] = []
    if level in ("empty", "thin"):
        recs.append(f"reference is {level} ({n} exemplars, confidence {conf}) — the grain "
                    f"score is DIRECTIONAL ONLY; add {max(0, REF_THIN_N - n)} to reach a "
                    f"moderate reference and {max(0, REF_STRONG_N - n)} for a trustworthy one")
    elif level == "moderate":
        recs.append(f"reference is moderate ({n} exemplars, confidence {conf}); add "
                    f"{REF_STRONG_N - n} more exemplars for a trustworthy score")
    if seeds and not rules:
        recs.append("no rule exemplar (no ADJUDICATES) — add one so rule grain is anchored")
    if seeds and not non_rules:
        recs.append("no non-rule/component exemplar — add one so component grain is anchored")
    if not review["internally_consistent"] and n:
        recs.append("exemplars are not internally consistent (reflexive grain check flags drift "
                    "among the seeds themselves) — tighten them before relying on the reference")

    return {
        "n_exemplars": n,
        "confidence": conf,
        "level": level,                                   # empty|thin|moderate|strong
        "trustworthy": level == "strong",
        "internally_consistent": review["internally_consistent"],
        "coverage": {"rule": len(rules), "non_rule": len(non_rules),
                     "length_min": lengths[0] if lengths else 0,
                     "length_max": lengths[-1] if lengths else 0},
        "recommendations": recs,
    }
