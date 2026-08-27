"""Workbook-owned named traversal programs bound to one encoding.

The workbook authors operations over the predicates it emitted.  At
materialization the host derives the observed predicate/SST vocabulary and
node kinds, validates every program against them, and writes a fingerprinted
sidecar beside the graph.  Nothing here declares a reusable domain format.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mcp_server.graph_contract import (
    GraphContractDocument,
    GraphFormatSpec,
    NodeKindSpec,
    PredicateSpec,
    TraversalRecipeSpec,
)
from source_pipeline.encoding import canonical_encoding, predicate_vocabulary


SCHEMA_VERSION = "workbook-traversals-v1"


class WorkbookTraversalError(ValueError):
    """The traversal program set is malformed or not bound to this graph."""


class WorkbookTraversalPrograms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["workbook-traversals-v1"] = SCHEMA_VERSION
    traversals: dict[str, TraversalRecipeSpec]


class TraversalBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str
    encoding_sha256: str
    predicates: dict[str, str]
    node_kind_id_patterns: dict[str, str]


class BoundWorkbookTraversalPrograms(WorkbookTraversalPrograms):
    binding: TraversalBinding
    fingerprint: str


def encoding_sha256(encoding: dict[str, Any]) -> str:
    payload = json.dumps(
        canonical_encoding(encoding),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _kind_patterns(encoding: dict[str, Any]) -> dict[str, str]:
    by_kind: dict[str, list[str]] = {}
    for row in encoding.get("concepts") or []:
        kind = str(row.get("kind") or "").strip()
        node_id = str(row.get("id") or "").strip()
        if kind and node_id:
            by_kind.setdefault(kind, []).append(node_id)
    patterns: dict[str, str] = {}
    for kind, node_ids in sorted(by_kind.items()):
        conventional = f"{kind}:"
        patterns[kind] = (
            conventional + "<stable-id>"
            if all(node_id.startswith(conventional) for node_id in node_ids)
            else "<node-id>"
        )
    return patterns


def _document(bound: BoundWorkbookTraversalPrograms, *, path: Path | str) -> GraphContractDocument:
    try:
        specification = GraphFormatSpec(
            format_id="workbook-traversals",
            format_version=1,
            node_kinds={
                name: NodeKindSpec(id_pattern=pattern)
                for name, pattern in bound.binding.node_kind_id_patterns.items()
            },
            predicates={
                name: PredicateSpec(sst=sst)
                for name, sst in bound.binding.predicates.items()
            },
            traversals=bound.traversals,
        )
    except ValidationError as exc:
        raise WorkbookTraversalError(f"invalid traversal program set: {exc}") from exc
    return GraphContractDocument(
        path=str(path),
        specification=specification,
        markdown="Workbook-owned traversal programs bound to the materialized encoding.\n",
        fingerprint=bound.fingerprint,
        content_sha256=bound.fingerprint.removeprefix("wtrv_"),
    )


def bind_workbook_traversals(
    value: dict[str, Any],
    encoding: dict[str, Any],
) -> dict[str, Any]:
    """Validate agent output and add the host-observed graph binding."""
    try:
        programs = WorkbookTraversalPrograms.model_validate(value)
    except ValidationError as exc:
        raise WorkbookTraversalError(f"invalid traversal program set: {exc}") from exc
    binding = TraversalBinding(
        graph_id=str((encoding.get("graph") or {}).get("id") or "workbook-build"),
        encoding_sha256=encoding_sha256(encoding),
        predicates=predicate_vocabulary(encoding),
        node_kind_id_patterns=_kind_patterns(encoding),
    )
    payload = {
        **programs.model_dump(mode="json"),
        "binding": binding.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    payload["fingerprint"] = f"wtrv_{digest}"
    try:
        bound = BoundWorkbookTraversalPrograms.model_validate(payload)
        _document(bound, path="traversals.json")
    except ValidationError as exc:
        raise WorkbookTraversalError(f"invalid traversal program set: {exc}") from exc
    return bound.model_dump(mode="json")


def write_bound_workbook_traversals(
    value: dict[str, Any], encoding: dict[str, Any], graph_path: Path | str
) -> Path:
    bound = bind_workbook_traversals(value, encoding)
    out = Path(str(Path(graph_path)) + ".traversals.json")
    out.write_text(json.dumps(bound, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load_bound_workbook_traversals(
    path: Path | str,
    *,
    expected_encoding_sha256: str = "",
) -> GraphContractDocument:
    artifact_path = Path(path)
    try:
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
        bound = BoundWorkbookTraversalPrograms.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise WorkbookTraversalError(f"invalid bound traversal artifact: {exc}") from exc
    payload = bound.model_dump(mode="json", exclude={"fingerprint"})
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if bound.fingerprint != f"wtrv_{digest}":
        raise WorkbookTraversalError("bound traversal artifact fingerprint does not match its content")
    if expected_encoding_sha256 and bound.binding.encoding_sha256 != expected_encoding_sha256:
        raise WorkbookTraversalError("traversal artifact is bound to a different encoding")
    return _document(bound, path=artifact_path)
