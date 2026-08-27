"""Run a format's acceptance predicates against a produced graph. Zero LLM.

This is the executable half of grain. Until now `graph.md` said grain in prose
— "one independently citable claim" — which a person can agree with and no
program can decide, so nothing ever checked whether a construction obeyed it.

Two properties are load-bearing and both are guarded here rather than promised.

**Every declared check has an implementation.** The contract's `AcceptanceCheck`
literal and `_CHECKS` below are compared at import. A name that can be written
into a `graph.md` but does nothing when run would be worse than no check at
all: it reports a pass.

**An empty acceptance list is UNCHECKED, not a pass.** A format that makes no
checkable claim about construction has not been satisfied by a graph; it has
declined to say anything. Reporting that as conformance is how a vacuous test
becomes an endorsement.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

from mcp_server.graph_contract import GraphContractDocument

#: A finding is (count, examples). Examples are capped: a report that lists
#: 4,000 failures is not read by anyone, and five is enough to diagnose.
MAX_EXAMPLES = 5

Node = dict[str, Any]
Edge = dict[str, Any]


def _nodes_of_kind(nodes: list[Node], kind: str) -> list[Node]:
    if not kind:
        return nodes
    return [node for node in nodes if str(node.get("kind") or "") == kind]


def _check_every_node_has_a_source_unit(nodes, edges, spec, document, source_text):
    bad = [n["id"] for n in _nodes_of_kind(nodes, spec.kind) if not n.get("source_unit_ids")]
    return len(bad), bad[:MAX_EXAMPLES]


def _check_every_node_has_a_declared_kind(nodes, edges, spec, document, source_text):
    declared = set(document.specification.node_kinds)
    bad = [n["id"] for n in nodes if str(n.get("kind") or "") not in declared]
    return len(bad), bad[:MAX_EXAMPLES]


def _check_every_edge_has_a_declared_predicate(nodes, edges, spec, document, source_text):
    declared = set(document.specification.predicates)
    bad = [
        f"{e.get('source_id')} -{e.get('predicate')}-> {e.get('target_id')}"
        for e in edges
        if str(e.get("predicate") or "") not in declared
    ]
    return len(bad), bad[:MAX_EXAMPLES]


def _check_node_count_per_source_unit(nodes, edges, spec, document, source_text):
    """Grain, in the only form a program can decide.

    A unit that produced one summarising node and a unit that produced forty
    fragments are the two failure modes this catches, and they are the two
    that prose grain statements have never prevented.
    """
    per_unit: Counter = Counter()
    for node in _nodes_of_kind(nodes, spec.kind):
        for unit_id in node.get("source_unit_ids") or []:
            per_unit[unit_id] += 1
    bad = []
    for unit_id, count in sorted(per_unit.items()):
        if spec.min is not None and count < spec.min:
            bad.append(f"{unit_id}: {count} < {spec.min}")
        elif spec.max is not None and count > spec.max:
            bad.append(f"{unit_id}: {count} > {spec.max}")
    return len(bad), bad[:MAX_EXAMPLES]


def _check_nodes_per_kind(nodes, edges, spec, document, source_text):
    counts = Counter(str(n.get("kind") or "") for n in nodes)
    kinds = [spec.kind] if spec.kind else sorted(document.specification.node_kinds)
    bad = []
    for kind in kinds:
        count = counts.get(kind, 0)
        if spec.min is not None and count < spec.min:
            bad.append(f"{kind}: {count} < {spec.min}")
        elif spec.max is not None and count > spec.max:
            bad.append(f"{kind}: {count} > {spec.max}")
    return len(bad), bad[:MAX_EXAMPLES]


def _kinds_reachable_only_by(document, ignored: set[str]) -> set[str]:
    """Kinds no surviving predicate can attach, once `ignored` is removed."""
    reachable: set[str] = set()
    for name, spec in document.specification.predicates.items():
        if name in ignored:
            continue
        reachable.update(spec.source_kinds or ())
        reachable.update(spec.target_kinds or ())
        if not spec.source_kinds and not spec.target_kinds:
            # An unconstrained predicate can attach anything.
            return set()
    return set(document.specification.node_kinds) - reachable


def _check_edges_per_node(nodes, edges, spec, document, source_text):
    # `ignoring` exists because a format that declares a provenance predicate
    # every node carries makes this check unfailable: the edge satisfying it
    # is the one every conforming program emits. A degree of one is meant to
    # ask "is this node attached to the narrative", not "did you cite it".
    ignored = set(spec.ignoring)
    degree: Counter = Counter()
    for edge in edges:
        if str(edge.get("predicate")) in ignored:
            continue
        degree[str(edge.get("source_id"))] += 1
        degree[str(edge.get("target_id"))] += 1

    # A check may not demand what the format makes impossible. Excluding
    # `attested_by` leaves a `source` node with no predicate that could ever
    # reach it, so requiring it to have a degree fails every conforming graph
    # for a reason its author cannot act on. Which kinds those are is read off
    # the contract rather than named here, so a format that adds another
    # citation-only kind does not have to remember to update this.
    unreachable = _kinds_reachable_only_by(document, ignored) if ignored else set()

    bad = []
    for node in _nodes_of_kind(nodes, spec.kind):
        if str(node.get("kind")) in unreachable:
            continue
        count = degree.get(node["id"], 0)
        if spec.min is not None and count < spec.min:
            bad.append(f"{node['id']}: {count} < {spec.min}")
        elif spec.max is not None and count > spec.max:
            bad.append(f"{node['id']}: {count} > {spec.max}")
    return len(bad), bad[:MAX_EXAMPLES]


def _check_no_isolated_nodes(nodes, edges, spec, document, source_text):
    touched = set()
    for edge in edges:
        touched.add(str(edge.get("source_id")))
        touched.add(str(edge.get("target_id")))
    bad = [n["id"] for n in _nodes_of_kind(nodes, spec.kind) if n["id"] not in touched]
    return len(bad), bad[:MAX_EXAMPLES]


def _check_label_appears_in_source(nodes, edges, spec, document, source_text):
    """The cheapest guard against a fabricated node.

    Needs the source text; without it the check abstains loudly rather than
    passing, because a check that silently returns zero failures when it
    cannot run is indistinguishable from one that ran and found nothing.
    """
    if source_text is None:
        return None, ["source text not supplied; check could not run"]
    bad = []
    for node in _nodes_of_kind(nodes, spec.kind):
        label = str(node.get("label") or "").strip()
        if label and label not in source_text:
            bad.append(f"{node['id']}: {label!r}")
    return len(bad), bad[:MAX_EXAMPLES]


def _check_no_duplicate_labels_within_kind(nodes, edges, spec, document, source_text):
    by_kind: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for node in _nodes_of_kind(nodes, spec.kind):
        by_kind[str(node.get("kind") or "")][str(node.get("label") or "").strip().lower()].append(node["id"])
    bad = []
    for kind, labels in sorted(by_kind.items()):
        for label, ids in sorted(labels.items()):
            if label and len(ids) > 1:
                bad.append(f"{kind}/{label!r}: {', '.join(sorted(ids))}")
    return len(bad), bad[:MAX_EXAMPLES]


_CHECKS: dict[str, Callable] = {
    "every_node_has_a_source_unit": _check_every_node_has_a_source_unit,
    "every_node_has_a_declared_kind": _check_every_node_has_a_declared_kind,
    "every_edge_has_a_declared_predicate": _check_every_edge_has_a_declared_predicate,
    "node_count_per_source_unit": _check_node_count_per_source_unit,
    "nodes_per_kind": _check_nodes_per_kind,
    "edges_per_node": _check_edges_per_node,
    "no_isolated_nodes": _check_no_isolated_nodes,
    "label_appears_in_source": _check_label_appears_in_source,
    "no_duplicate_labels_within_kind": _check_no_duplicate_labels_within_kind,
}


def _assert_vocabulary_is_implemented() -> None:
    """A declarable check with no implementation would report a pass."""
    from typing import get_args

    from mcp_server.graph_contract import AcceptanceCheck

    declared = set(get_args(AcceptanceCheck))
    implemented = set(_CHECKS)
    missing = sorted(declared - implemented)
    extra = sorted(implemented - declared)
    if missing:
        raise RuntimeError(f"acceptance checks declared but not implemented: {missing}")
    if extra:
        raise RuntimeError(f"acceptance checks implemented but not declarable: {extra}")


_assert_vocabulary_is_implemented()


def check_acceptance(
    document: GraphContractDocument,
    encoding: dict[str, Any],
    *,
    source_text: str | None = None,
) -> dict[str, Any]:
    """Run every predicate the format declares. Deterministic, zero LLM."""
    nodes = list(encoding.get("concepts") or encoding.get("nodes") or [])
    edges = list(encoding.get("edges") or [])
    predicates = document.specification.acceptance

    reports: list[dict[str, Any]] = []
    for spec in predicates:
        failures, examples = _CHECKS[spec.check](
            nodes, edges, spec, document, source_text
        )
        reports.append({
            "check": spec.check,
            "kind": spec.kind,
            "predicate": spec.predicate,
            "min": spec.min,
            "max": spec.max,
            "because": spec.because,
            # None means the check could not run — distinct from zero failures.
            "ran": failures is not None,
            "failures": failures,
            "examples": examples,
            "ok": failures == 0,
        })

    could_not_run = [r for r in reports if not r["ran"]]
    failed = [r for r in reports if r["ran"] and not r["ok"]]
    if not predicates:
        outcome = "UNCHECKED"
    elif could_not_run:
        outcome = "INCOMPLETE"
    elif failed:
        outcome = "ACCEPTANCE_FAILED"
    else:
        outcome = "CONFORMS"

    return {
        "kind": "ACCEPTANCE",
        "outcome": outcome,
        "format_id": document.specification.format_id,
        "format_fingerprint": document.fingerprint,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "checks": len(reports),
        "failed": len(failed),
        "reports": reports,
    }
