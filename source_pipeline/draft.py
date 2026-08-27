"""Small, constructor-neutral helpers for agent-authored workbook programs.

``GraphDraft`` owns bookkeeping, not interpretation.  The workbook program
still decides what a concept is, which relations matter, and which source
spans support them.  The helper only merges repeated citations, refuses
conflicting identities/geometries, and makes intended joins executable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from source_pipeline.encoding import canonical_encoding, validate_encoding


class GraphDraftError(ValueError):
    """A draft is internally contradictory or misses a declared requirement."""


def _citations(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    atom_id = getattr(value, "atom_id", None)
    if atom_id is not None:
        text = str(atom_id).strip()
        return [text] if text else []
    try:
        values = list(value)
    except TypeError as exc:
        raise GraphDraftError("citations must be ids, atoms, or an iterable of them") from exc
    out: list[str] = []
    for item in values:
        for ref in _citations(item):
            if ref not in out:
                out.append(ref)
    return out


@dataclass(frozen=True)
class SemanticDiff:
    """Source-insensitive change between two encodings."""

    added_concept_ids: tuple[str, ...]
    removed_concept_ids: tuple[str, ...]
    added_edges: tuple[tuple[str, str, str, str], ...]
    removed_edges: tuple[tuple[str, str, str, str], ...]

    @property
    def concept_id_churn(self) -> tuple[str, ...]:
        return tuple(sorted(self.added_concept_ids + self.removed_concept_ids))

    def wire(self) -> dict[str, Any]:
        return {
            "added_concept_ids": list(self.added_concept_ids),
            "removed_concept_ids": list(self.removed_concept_ids),
            "concept_id_churn": list(self.concept_id_churn),
            "added_edges": [list(row) for row in self.added_edges],
            "removed_edges": [list(row) for row in self.removed_edges],
        }


def semantic_diff(before: dict[str, Any], after: dict[str, Any]) -> SemanticDiff:
    """Compare graph meaning while ignoring citation-only changes."""

    def rows(encoding: dict[str, Any]):
        concepts = {str(row.get("id") or "") for row in encoding.get("concepts") or []}
        edges = {
            (
                str(row.get("source_id") or ""),
                str(row.get("predicate") or ""),
                str(row.get("target_id") or ""),
                str(row.get("sst_type") or "").upper(),
            )
            for row in encoding.get("edges") or []
        }
        return concepts, edges

    before_concepts, before_edges = rows(before)
    after_concepts, after_edges = rows(after)
    return SemanticDiff(
        added_concept_ids=tuple(sorted(after_concepts - before_concepts)),
        removed_concept_ids=tuple(sorted(before_concepts - after_concepts)),
        added_edges=tuple(sorted(after_edges - before_edges)),
        removed_edges=tuple(sorted(before_edges - after_edges)),
    )


class GraphDraft:
    """Accumulate one cited encoding without imposing a domain schema."""

    def __init__(self, graph_id: str, domain: str = "workbook") -> None:
        self.graph = {"id": str(graph_id), "domain": str(domain)}
        self._concepts: dict[str, dict[str, Any]] = {}
        self._edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._requirements: list[tuple[str, tuple[str, ...]]] = []

    @property
    def concept_ids(self) -> frozenset[str]:
        return frozenset(self._concepts)

    @property
    def edge_keys(self) -> frozenset[tuple[str, str, str]]:
        return frozenset(self._edges)

    def concept(
        self,
        concept_id: str,
        kind: str,
        label: str,
        *,
        citations: Any = None,
        synthetic_reason: str = "",
        text_content: str = "",
        semantic_anchor: str = "",
    ) -> str:
        concept_id = str(concept_id).strip()
        kind = str(kind).strip()
        label = str(label).strip()
        if not concept_id or not kind or not label:
            raise GraphDraftError("concept id, kind, and label must be non-empty")
        refs = _citations(citations)
        reason = str(synthetic_reason or "").strip()
        if refs and reason:
            raise GraphDraftError(f"concept {concept_id!r} cannot be sourced and synthetic")
        existing = self._concepts.get(concept_id)
        if existing is None:
            existing = {
                "id": concept_id,
                "kind": kind,
                "label": label,
                "text_content": str(text_content or label),
                "source_unit_ids": refs,
            }
            if semantic_anchor:
                existing["semantic_anchor"] = str(semantic_anchor)
            if reason:
                existing["synthetic_reason"] = reason
            self._concepts[concept_id] = existing
            return concept_id
        if (existing["kind"], existing["label"]) != (kind, label):
            raise GraphDraftError(
                f"concept {concept_id!r} changed identity from "
                f"{existing['kind']!r}/{existing['label']!r} to {kind!r}/{label!r}"
            )
        if bool(existing.get("synthetic_reason")) != bool(reason) and (refs or reason):
            raise GraphDraftError(f"concept {concept_id!r} mixes sourced and synthetic evidence")
        for ref in refs:
            if ref not in existing["source_unit_ids"]:
                existing["source_unit_ids"].append(ref)
        text = str(text_content or "")
        if text and len(text) > len(str(existing.get("text_content") or "")):
            existing["text_content"] = text
        return concept_id

    def edge(
        self,
        source_id: str,
        predicate: str,
        target_id: str,
        sst_type: str,
        *,
        citations: Any = None,
        synthetic_reason: str = "",
    ) -> tuple[str, str, str]:
        key = tuple(str(value).strip() for value in (source_id, predicate, target_id))
        if not all(key):
            raise GraphDraftError("edge source, predicate, and target must be non-empty")
        sst = str(sst_type).strip().upper()
        refs = _citations(citations)
        reason = str(synthetic_reason or "").strip()
        if refs and reason:
            raise GraphDraftError(f"edge {key!r} cannot be sourced and synthetic")
        existing = self._edges.get(key)
        if existing is None:
            existing = {
                "source_id": key[0],
                "predicate": key[1],
                "target_id": key[2],
                "sst_type": sst,
                "source_unit_ids": refs,
            }
            if reason:
                existing["synthetic_reason"] = reason
            self._edges[key] = existing
            return key
        if str(existing["sst_type"]).upper() != sst:
            raise GraphDraftError(
                f"edge {key!r} changed SST geometry from "
                f"{existing['sst_type']!r} to {sst!r}"
            )
        if bool(existing.get("synthetic_reason")) != bool(reason) and (refs or reason):
            raise GraphDraftError(f"edge {key!r} mixes sourced and synthetic evidence")
        for ref in refs:
            if ref not in existing["source_unit_ids"]:
                existing["source_unit_ids"].append(ref)
        return key

    def require_concepts(self, *concept_ids: str) -> None:
        self._requirements.append(("concepts", tuple(str(value) for value in concept_ids)))

    def require_edges(self, *edges: tuple[str, str, str]) -> None:
        for edge in edges:
            self._requirements.append(("edge", tuple(str(value) for value in edge)))

    def require_relation(
        self,
        predicate: str,
        *,
        source_id: str = "",
        target_id: str = "",
    ) -> None:
        """Require at least one matching relation shape."""
        self._requirements.append(
            ("relation", (str(source_id), str(predicate), str(target_id)))
        )

    def requirement_problems(self) -> list[str]:
        problems: list[str] = []
        for kind, values in self._requirements:
            if kind == "concepts":
                missing = sorted(set(values) - set(self._concepts))
                if missing:
                    problems.append(f"missing required concepts: {missing}")
            elif kind == "edge" and values not in self._edges:
                problems.append(f"missing required edge: {values}")
            elif kind == "relation":
                source, predicate, target = values
                if not any(
                    (not source or key[0] == source)
                    and key[1] == predicate
                    and (not target or key[2] == target)
                    for key in self._edges
                ):
                    problems.append(
                        "missing required relation: "
                        f"source={source or '*'}, predicate={predicate}, target={target or '*'}"
                    )
        return problems

    def encoding(self, *, known_source_unit_ids: Iterable[str] | None = None) -> dict[str, Any]:
        out = canonical_encoding(
            {
                "graph": self.graph,
                "concepts": list(self._concepts.values()),
                "edges": list(self._edges.values()),
            }
        )
        problems = self.requirement_problems() + validate_encoding(
            out, known_source_unit_ids=known_source_unit_ids
        )
        if problems:
            raise GraphDraftError(f"{len(problems)} problem(s): " + "; ".join(problems))
        return out
