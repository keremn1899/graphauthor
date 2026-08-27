"""Cases: the semantic half of conformance, checked deterministically.

Acceptance predicates are structural, and that is not a limitation to be
engineered away — every claim a program can decide about a graph without
knowing what the graph is *about* is a claim about shape. Measured: six
acceptance predicates passed a graph in which every node was typed
`character` and wired into a ring, and passed again on a held-out corpus where
a farm and a district were typed as people.

A case carries the other half. It is one concrete semantic claim about **this
corpus** — "Althing is a place, not a person" — supplied by whoever read the
text, and checked from then on by a lookup.

Three properties are load-bearing.

**The judgement happens once, at authoring; the check is deterministic.**
Nothing here calls a model. A case that cannot be stated decidably is not
written as prose to be interpreted later; it is either restated until it is
decidable, or it does not become a case.

**Cases are per-corpus, acceptance is per-format.** A claim about Althing
means nothing on a research paper. Formats declare acceptance; corpora carry
cases, beside the workbook that produced them.

**Cases key on labels, not ids.** A node id embeds its kind
(`character:althing`), so the id a mistyped node *has* is not the id you want
to talk about, and keying on it makes the most common case unwritable.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import yaml

#: Capped for the same reason acceptance caps them: nobody reads 4,000.
MAX_EXAMPLES = 5

CaseClaim = Literal[
    # Claims about a named thing. Written by whoever read the source.
    "node_kind",
    "node_present",
    "node_absent",
    "connected_within",
    # Claims about the graph as a whole. These are what a *format* can promise
    # ahead of any corpus, and the reason a claim file can attach at format
    # scope: "a research graph has at least two claims in it" is true of every
    # corpus in the format, and re-authoring it per corpus is waste.
    "label_shape",
    "nodes_per_kind",
    "degree_per_node",
    "no_duplicate_labels",
    "field_present",
    # Claims about edges. Everything above is a claim about nodes, which left
    # a format's most valuable predicate uncheckable: `contradicts` scored
    # precision 0 of 4 on a corpus with three real disputes and no case could
    # say so, because the defect was not in any node.
    "edges_per_predicate",
    "edge_backed_by",
]


class CaseError(ValueError):
    """A malformed case file. Raised at load, never at check time."""


@dataclass(frozen=True)
class Case:
    """One decidable semantic claim about one corpus."""

    claim: CaseClaim
    because: str = ""
    #: node_kind, node_present, node_absent, connected_within
    label: str = ""
    #: node_kind
    must_be: str = ""
    #: connected_within
    to: str = ""
    within: int = 0
    #: label_shape
    kind: str = ""
    must_not_match: str = ""
    must_match: str = ""
    #: Match a pattern rather than an exact label. Available to every claim
    #: that names a node, because labels extracted from a source are not
    #: stable: a paper node's label turned out to be its title plus the
    #: acceptance footnote plus an ellipsis, so an exact-title case reported
    #: "endpoint absent" for a node that was right there.
    label_matching: str = ""
    #: connected_within: the pattern form of `to`
    to_matching: str = ""
    #: nodes_per_kind, degree_per_node
    min: int | None = None
    max: int | None = None
    #: degree_per_node: predicates that do not count toward a node's degree.
    #: A format that declares a provenance predicate every node carries makes
    #: a minimum-degree claim unfailable without this -- measured at 92 of 92
    #: nodes passing while 44 touched nothing but their own citation.
    ignoring: list[str] = field(default_factory=list)
    #: edges_per_predicate, edge_backed_by: the edge label being claimed about
    predicate: str = ""
    #: edge_backed_by: the predicates the backing path may walk.
    #: Declared above `field` on purpose -- `field: str` shadows
    #: `dataclasses.field` for every line after it, so a later
    #: `field(default_factory=...)` raises "'str' object is not callable".
    using: list[str] = field(default_factory=list)
    #: field_present: the concept field that must be non-empty
    field: str = ""

    def describe(self) -> str:
        left = repr(self.label) if self.label else f"/{self.label_matching}/"
        right = repr(self.to) if self.to else f"/{self.to_matching}/"
        if self.claim == "node_kind":
            return f"{left} must be a {self.must_be}"
        if self.claim == "node_present":
            return f"{left} must exist"
        if self.claim == "node_absent":
            return f"nothing named {left} may be a node"
        if self.claim == "connected_within":
            return f"{left} and {right} within {self.within} hops"
        if self.claim == "label_shape":
            scope = f"{self.kind} labels" if self.kind else "labels"
            if self.must_not_match:
                return f"{scope} must not match /{self.must_not_match}/"
            return f"{scope} must match /{self.must_match}/"
        bound = (f"at least {self.min}" if self.max is None
                 else f"at most {self.max}" if self.min is None
                 else f"between {self.min} and {self.max}")
        if self.claim == "nodes_per_kind":
            return f"{bound} {self.kind} node(s)"
        if self.claim == "degree_per_node":
            scope = f"every {self.kind}" if self.kind else "every node"
            skip = f" (not counting {', '.join(self.ignoring)})" if self.ignoring else ""
            return f"{scope} needs {bound} edge(s){skip}"
        if self.claim == "no_duplicate_labels":
            scope = f"{self.kind} nodes" if self.kind else "nodes"
            return f"no two {scope} may share a label"
        if self.claim == "field_present":
            scope = f"every {self.kind}" if self.kind else "every node"
            return f"{scope} must carry a non-empty {self.field}"
        if self.claim == "edges_per_predicate":
            return f"{bound} {self.predicate} edge(s)"
        if self.claim == "edge_backed_by":
            return (f"every {self.predicate} edge backed by a path of "
                    f"{self.within} hop(s) over {', '.join(self.using)}")
        return self.claim


def _normalise(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "")).strip().lower()


def _nodes_by_label(nodes: list[dict]) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for node in nodes:
        found.setdefault(_normalise(node.get("label")), []).append(node)
    return found


def _resolve(nodes, by_label, label: str, pattern: str) -> list[dict]:
    """Nodes named by a case, by exact label or by pattern. Never both."""
    if pattern:
        compiled = re.compile(pattern, re.IGNORECASE)
        return [n for n in nodes if compiled.search(str(n.get("label") or ""))]
    return by_label.get(_normalise(label), [])


def _names(case, which: str) -> str:
    if which == "to":
        return case.to or f"/{case.to_matching}/"
    return case.label or f"/{case.label_matching}/"


def _check_node_kind(case, nodes, edges, by_label):
    matches = _resolve(nodes, by_label, case.label, case.label_matching)
    if not matches:
        # Absent is not the same as mistyped, and saying so is the difference
        # between "retype it" and "the constructor never found it".
        return [f"no node labelled {_names(case, 'label')}"]
    wrong = [n for n in matches if str(n.get("kind")) != case.must_be]
    return [f"{n['id']} is a {n.get('kind')!r}, not {case.must_be!r}" for n in wrong]


def _check_node_present(case, nodes, edges, by_label):
    if _resolve(nodes, by_label, case.label, case.label_matching):
        return []
    return [f"no node labelled {_names(case, 'label')}"]


def _check_node_absent(case, nodes, edges, by_label):
    found = _resolve(nodes, by_label, case.label, case.label_matching)
    return [f"{n['id']} ({str(n.get('label'))[:70]!r}) should not be a node"
            for n in found]


def _check_connected_within(case, nodes, edges, by_label):
    left = _resolve(nodes, by_label, case.label, case.label_matching)
    right = _resolve(nodes, by_label, case.to, case.to_matching)
    if not left or not right:
        missing = [
            _names(case, which) for which, hits in (("label", left), ("to", right))
            if not hits
        ]
        return [f"endpoint absent: {', '.join(missing)}"]

    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge.get("source_id"))
        target = str(edge.get("target_id"))
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)

    targets = {n["id"] for n in right}
    start = {n["id"] for n in left}
    seen = set(start)
    queue = deque((node_id, 0) for node_id in start)
    while queue:
        node_id, depth = queue.popleft()
        if node_id in targets and node_id not in start:
            return []
        if depth >= case.within:
            continue
        for neighbour in adjacency.get(node_id, ()):
            if neighbour in targets:
                return []
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, depth + 1))
    return [f"no path of {case.within} hops or fewer "
            f"between {_names(case, 'label')} and {_names(case, 'to')}"]


def _check_label_shape(case, nodes, edges, by_label):
    scoped = [n for n in nodes
              if not case.kind or str(n.get("kind")) == case.kind]
    bad = []
    if case.must_not_match:
        pattern = re.compile(case.must_not_match)
        for node in scoped:
            if pattern.search(str(node.get("label") or "")):
                bad.append(f"{node['id']}: {str(node.get('label'))[:70]!r}")
    if case.must_match:
        pattern = re.compile(case.must_match)
        for node in scoped:
            if not pattern.search(str(node.get("label") or "")):
                bad.append(f"{node['id']}: {str(node.get('label'))[:70]!r}")
    return bad


def _of_kind(nodes, kind: str):
    return [n for n in nodes if not kind or str(n.get("kind")) == kind]


def _bounds(case, count: int, what: str) -> list[str]:
    if case.min is not None and count < case.min:
        return [f"{what}: {count} < {case.min}"]
    if case.max is not None and count > case.max:
        return [f"{what}: {count} > {case.max}"]
    return []


def _check_nodes_per_kind(case, nodes, edges, by_label):
    return _bounds(case, len(_of_kind(nodes, case.kind)), f"{case.kind} nodes")


def _check_degree_per_node(case, nodes, edges, by_label):
    ignored = set(case.ignoring)
    degree: dict[str, int] = {}
    for edge in edges:
        if str(edge.get("predicate")) in ignored:
            continue
        for role in ("source_id", "target_id"):
            key = str(edge.get(role))
            degree[key] = degree.get(key, 0) + 1

    # A claim may not demand what the format makes impossible: once `about` is
    # excluded, a `topic` has no predicate that could ever attach it. The
    # acceptance checker solves that by reading the contract. A case file has
    # no contract, and the first version of this tried to infer it from the
    # graph -- skipping kinds where nothing was attached. That inverted the
    # claim: a graph where NOTHING is attached, which is the star this exists
    # to catch, has no attached kinds and was skipped entirely.
    #
    # So the exemption is stated instead of inferred. Scope the claim with
    # `kind` and it applies to that kind only. That is more typing in the case
    # file and it cannot silently mean the opposite of what it says.
    candidates = _of_kind(nodes, case.kind)

    bad = []
    for node in candidates:
        bad.extend(_bounds(case, degree.get(node["id"], 0), str(node["id"])))
    return bad[:MAX_EXAMPLES * 4]


def _check_no_duplicate_labels(case, nodes, edges, by_label):
    seen: dict[tuple[str, str], list[str]] = {}
    for node in _of_kind(nodes, case.kind):
        key = (str(node.get("kind")), _normalise(node.get("label")))
        seen.setdefault(key, []).append(str(node["id"]))
    return [f"{kind}/{label!r}: {', '.join(sorted(ids))}"
            for (kind, label), ids in sorted(seen.items()) if len(ids) > 1]


def _check_field_present(case, nodes, edges, by_label):
    return [f"{n['id']}: {case.field} is empty"
            for n in _of_kind(nodes, case.kind) if not n.get(case.field)]


def _edges_with(edges, predicate: str):
    return [e for e in edges
            if str(e.get("predicate") or e.get("label")) == predicate]


def _check_edges_per_predicate(case, nodes, edges, by_label):
    return _bounds(case, len(_edges_with(edges, case.predicate)),
                   f"{case.predicate} edge")


def _check_edge_backed_by(case, nodes, edges, by_label):
    """Every edge of one predicate must rest on a path of others.

    Written for the rule that took `contradicts` from precision 0/4 to 2/2 on
    a real corpus: a paper cannot disagree with one it has not read, so the
    two claims a `contradicts` joins must be reachable from each other through
    `asserts` and `cites`. Stated as a path rather than as a special case of
    citation, because the shape recurs -- a relation between two things is
    only credible when their containers are related too.

    The backing walk is undirected and restricted to `using`. Both matter: the
    path runs against the arrows on one side (claim <- asserts - paper) and an
    unrestricted walk would find a path through anything at all.
    """
    subject = _edges_with(edges, case.predicate)
    if not subject:
        return []
    labels = {n["id"]: str(n.get("label") or n["id"]) for n in nodes}
    allowed = set(case.using)
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        if str(edge.get("predicate") or edge.get("label")) not in allowed:
            continue
        source, target = str(edge.get("source_id")), str(edge.get("target_id"))
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)

    def reaches(start: str, goal: str) -> bool:
        seen = {start}
        queue = deque([(start, 0)])
        while queue:
            node_id, depth = queue.popleft()
            if node_id == goal and depth:
                return True
            if depth >= case.within:
                continue
            for neighbour in adjacency.get(node_id, ()):
                if neighbour == goal:
                    return True
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, depth + 1))
        return False

    bad = []
    for edge in subject:
        source, target = str(edge.get("source_id")), str(edge.get("target_id"))
        if not reaches(source, target):
            bad.append(
                f"{labels.get(source, source)[:45]!r} -{case.predicate}-> "
                f"{labels.get(target, target)[:45]!r}: no backing path"
            )
    return bad


_CLAIMS: dict[str, Callable] = {
    "node_kind": _check_node_kind,
    "node_present": _check_node_present,
    "node_absent": _check_node_absent,
    "connected_within": _check_connected_within,
    "label_shape": _check_label_shape,
    "nodes_per_kind": _check_nodes_per_kind,
    "degree_per_node": _check_degree_per_node,
    "no_duplicate_labels": _check_no_duplicate_labels,
    "field_present": _check_field_present,
    "edges_per_predicate": _check_edges_per_predicate,
    "edge_backed_by": _check_edge_backed_by,
}

#: Which fields each claim requires. A case missing one is refused at load
#: rather than silently passing: a claim that checks nothing reports a pass,
#: which is the exact failure mode acceptance already had.
_REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    "node_kind": (("label", "label_matching"), ("must_be",)),
    "node_present": (("label", "label_matching"),),
    "node_absent": (("label", "label_matching"),),
    "connected_within": (("label", "label_matching"),
                         ("to", "to_matching"), ("within",)),
    "label_shape": (("must_not_match", "must_match"),),
    "nodes_per_kind": (("kind",), ("min", "max")),
    "degree_per_node": (("min", "max"),),
    "no_duplicate_labels": (),
    "field_present": (("field",),),
    "edges_per_predicate": (("predicate",), ("min", "max")),
    "edge_backed_by": (("predicate",), ("using",), ("within",)),
}


def _assert_vocabulary_is_implemented() -> None:
    from typing import get_args

    declared = set(get_args(CaseClaim))
    implemented = set(_CLAIMS)
    if declared != implemented:
        raise RuntimeError(
            "case vocabulary and implementations disagree: "
            f"declared-only={sorted(declared - implemented)} "
            f"implemented-only={sorted(implemented - declared)}"
        )
    if set(_REQUIRED) != declared:
        raise RuntimeError("every claim needs its required fields declared")


_assert_vocabulary_is_implemented()


def load_cases(path) -> list[Case]:
    """Read a case file, refusing anything that would check nothing."""
    from pathlib import Path

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("cases") or []
    else:
        raise CaseError("a case file is a list of cases, or {cases: [...]}")

    known = set(Case.__dataclass_fields__)
    cases: list[Case] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CaseError(f"cases[{index}] is not a mapping")
        claim = str(row.get("claim") or "").strip()
        if claim not in _CLAIMS:
            raise CaseError(
                f"cases[{index}]: claim {claim!r} is not one of "
                f"{sorted(_CLAIMS)}"
            )
        unknown = set(row) - known
        if unknown:
            raise CaseError(f"cases[{index}]: unknown field(s) {sorted(unknown)}")
        for group in _REQUIRED[claim]:
            if not any(row.get(name) for name in group):
                raise CaseError(
                    f"cases[{index}] ({claim}): needs one of {list(group)}"
                )
        if not str(row.get("because") or "").strip():
            # The rationale is not decoration. A check whose point nobody
            # remembers gets deleted rather than fixed.
            raise CaseError(f"cases[{index}]: needs a `because`")
        cases.append(Case(**row))
    return cases


def format_cases_path(format_path) -> "Path | None":
    """`cases.yaml` beside a format's graph.md, if the format ships one.

    Format scope exists because the boundary between "true of this corpus" and
    "true of this format" is not one an author keeps straight while working.
    Four of the first nine cases written for a research-paper corpus -- claim
    labels must not be 200-character sentences, question labels must not begin
    "Future work" -- are true of every personal-research graph and were filed
    as corpus cases only because that is where the author happened to be.
    """
    from pathlib import Path

    candidate = Path(format_path).parent / "cases.yaml"
    return candidate if candidate.is_file() else None


def check_cases(cases: list[Case], encoding: dict[str, Any],
                scopes: dict[int, str] | None = None) -> dict[str, Any]:
    """Run every case. Deterministic, zero LLM."""
    nodes = list(encoding.get("concepts") or encoding.get("nodes") or [])
    edges = list(encoding.get("edges") or [])
    by_label = _nodes_by_label(nodes)

    reports = []
    for index, case in enumerate(cases):
        failures = _CLAIMS[case.claim](case, nodes, edges, by_label)
        reports.append({
            "claim": case.claim,
            "scope": (scopes or {}).get(index, "corpus"),
            "describes": case.describe(),
            "because": case.because,
            "ok": not failures,
            "failures": len(failures),
            "examples": failures[:MAX_EXAMPLES],
        })

    failed = [r for r in reports if not r["ok"]]
    # An empty case file is UNCHECKED, not a pass: a corpus nobody has made a
    # semantic claim about has not been judged, it has been left unjudged.
    outcome = ("UNCHECKED" if not cases
               else "CASES_FAILED" if failed
               else "CASES_PASS")
    return {
        "kind": "CASES",
        "outcome": outcome,
        "cases": len(reports),
        "failed": len(failed),
        "reports": reports,
    }
