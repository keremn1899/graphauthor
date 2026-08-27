"""Mechanical boundary between an agent-authored workbook program and a graph.

The host does not prescribe a domain format. A workbook program chooses node
kinds, predicates, and the projection of each relationship onto the four
portable SST geometries. The host checks only what it can know mechanically:

- ids are stable and unique within the encoding;
- edges have real endpoints and a valid SST projection;
- source-derived rows cite admitted workbook units;
- source-free rows say explicitly why they are synthetic;
- canonical output is deterministic.

The encoding remains the record. LadybugDB is a traversal projection and does
not currently store edge evidence or every provenance field.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

SST_TYPES = ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO")


class EncodingError(ValueError):
    """The program output cannot be materialized."""


def _refs(row: dict[str, Any]) -> list[str]:
    value = row.get("source_unit_ids")
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validate_provenance(
    row: dict[str, Any],
    *,
    path: str,
    known_source_unit_ids: set[str] | None,
) -> list[str]:
    problems: list[str] = []
    raw_refs = row.get("source_unit_ids")
    if raw_refs is not None and not isinstance(raw_refs, list):
        problems.append(f"{path}.source_unit_ids must be a list")
        refs: list[str] = []
    else:
        refs = _refs(row)

    reason = str(row.get("synthetic_reason") or "").strip()
    if not refs and not reason:
        problems.append(
            f"{path} needs source_unit_ids or a non-empty synthetic_reason"
        )
    if refs and reason:
        problems.append(
            f"{path} cannot be both source-backed and synthetic"
        )
    if known_source_unit_ids is not None:
        for ref in refs:
            if ref not in known_source_unit_ids:
                problems.append(f"{path} cites unknown source unit {ref!r}")
    return problems


def validate_encoding(
    encoding: dict[str, Any],
    *,
    known_source_unit_ids: Iterable[str] | None = None,
) -> list[str]:
    """Return every mechanical problem so an agent can repair in one pass."""
    problems: list[str] = []
    concepts = encoding.get("concepts")
    edges = encoding.get("edges")
    if not isinstance(concepts, list):
        return ["encoding.concepts must be a list"]
    if edges is None:
        edges = []
    if not isinstance(edges, list):
        problems.append("encoding.edges must be a list")
        edges = []

    known = (
        {str(value) for value in known_source_unit_ids}
        if known_source_unit_ids is not None
        else None
    )
    seen: dict[str, int] = {}
    for index, concept in enumerate(concepts):
        path = f"concepts[{index}]"
        if not isinstance(concept, dict):
            problems.append(f"{path} is not an object")
            continue
        node_id = str(concept.get("id") or "").strip()
        if not node_id:
            problems.append(f"{path} has no id")
        elif node_id in seen:
            problems.append(
                f"duplicate concept id {node_id!r} at {seen[node_id]} and {index}"
            )
        else:
            seen[node_id] = index
        if not str(concept.get("kind") or "").strip():
            problems.append(f"{path} has no kind")
        problems.extend(
            _validate_provenance(
                concept, path=path, known_source_unit_ids=known
            )
        )

    predicate_sst: dict[str, set[str]] = {}
    for index, edge in enumerate(edges):
        path = f"edges[{index}]"
        if not isinstance(edge, dict):
            problems.append(f"{path} is not an object")
            continue
        source = str(edge.get("source_id") or "").strip()
        target = str(edge.get("target_id") or "").strip()
        predicate = str(edge.get("predicate") or "").strip()
        sst_type = str(edge.get("sst_type") or "").strip().upper()
        if source not in seen:
            problems.append(f"{path}: source {source!r} is not a concept")
        if target not in seen:
            problems.append(f"{path}: target {target!r} is not a concept")
        if not predicate:
            problems.append(f"{path} has no predicate")
        else:
            predicate_sst.setdefault(predicate, set()).add(sst_type)
        if sst_type not in SST_TYPES:
            problems.append(
                f"{path}.sst_type must be one of {list(SST_TYPES)}, got "
                f"{sst_type!r}"
            )
        problems.extend(
            _validate_provenance(edge, path=path, known_source_unit_ids=known)
        )
    for predicate, geometries in sorted(predicate_sst.items()):
        if len(geometries) > 1:
            problems.append(
                f"predicate {predicate!r} maps to multiple SST types: "
                f"{sorted(geometries)}"
            )
    return problems


def predicate_vocabulary(encoding: dict[str, Any]) -> dict[str, str]:
    """Derive the encoding's semantic predicate → SST mapping.

    This is observed output, not a domain schema.  A predicate must have one
    portable geometry so later traversal programs cannot lower ambiguously.
    """
    problems = validate_encoding(encoding)
    if problems:
        raise EncodingError(
            "cannot derive predicate vocabulary from an invalid encoding: "
            + "; ".join(problems[:10])
        )
    return dict(
        sorted(
            {
                str(edge.get("predicate") or "").strip():
                str(edge.get("sst_type") or "").strip().upper()
                for edge in encoding.get("edges") or []
                if str(edge.get("predicate") or "").strip()
            }.items()
        )
    )


def canonical_encoding(encoding: dict[str, Any]) -> dict[str, Any]:
    """Canonical bytes for receipts, diffs, and repeatable materialization."""
    concepts = sorted(
        (dict(row) for row in encoding.get("concepts") or []),
        key=lambda row: str(row.get("id") or ""),
    )
    edges = sorted(
        (dict(row) for row in encoding.get("edges") or []),
        key=lambda row: (
            str(row.get("source_id") or ""),
            str(row.get("predicate") or ""),
            str(row.get("target_id") or ""),
        ),
    )
    for row in concepts + edges:
        if isinstance(row.get("source_unit_ids"), list):
            row["source_unit_ids"] = sorted(
                {str(value) for value in row["source_unit_ids"] if str(value)}
            )
    for edge in edges:
        if "sst_type" in edge:
            edge["sst_type"] = str(edge["sst_type"]).upper()
    out: dict[str, Any] = {
        "concepts": concepts,
        "edges": edges,
    }
    if isinstance(encoding.get("graph"), dict):
        out["graph"] = dict(encoding["graph"])
    return out


def to_graph(
    encoding: dict[str, Any],
    *,
    known_source_unit_ids: Iterable[str] | None = None,
):
    """Translate valid program output into the traversal graph projection."""
    from graph_storage.records import GraphEdge, GraphNode, MaterializedGraph

    problems = validate_encoding(
        encoding, known_source_unit_ids=known_source_unit_ids
    )
    if problems:
        raise EncodingError(
            f"{len(problems)} problem(s): " + "; ".join(problems[:10])
        )

    canonical = canonical_encoding(encoding)
    nodes = {}
    for concept in canonical["concepts"]:
        node_id = str(concept["id"])
        label = str(concept.get("label") or node_id)
        nodes[node_id] = GraphNode(
            id=node_id,
            kind=str(concept["kind"]),
            label=label,
            text_content=str(concept.get("text_content") or label),
            semantic_anchor=str(concept.get("semantic_anchor") or label),
            source_unit_ids=list(concept.get("source_unit_ids") or []),
        )
    edges = [
        GraphEdge(
            source=str(edge["source_id"]),
            target=str(edge["target_id"]),
            sst_type=str(edge["sst_type"]).upper(),
            label=str(edge["predicate"]),
        )
        for edge in canonical["edges"]
    ]
    graph_meta = canonical.get("graph") or {}
    return MaterializedGraph(
        id=str(graph_meta.get("id") or "workbook-build"),
        domain=str(graph_meta.get("domain") or "workbook"),
        nodes=nodes,
        edges=edges,
    )


def write_graph(
    encoding: dict[str, Any],
    out_path: Path | str,
    *,
    workbook=None,
    traversals: dict[str, Any] | None = None,
) -> Path:
    """Materialize a workbook encoding and write its portable source sidecar."""
    from graph_storage.writer import write_graph_records

    atoms = list(workbook.atoms()) if workbook is not None else []
    known: set[str] | None = None
    if workbook is not None:
        known = {
            ref
            for atom in atoms
            for ref in (str(atom.atom_id), str(atom.unit_id))
            if ref
        }
        workbook.check_fresh()

    out = Path(out_path)
    graph = to_graph(encoding, known_source_unit_ids=known)
    bound_traversals: dict[str, Any] | None = None
    if traversals is not None:
        # Validate and bind before replacing the graph. A malformed optional
        # program set must not turn a failed command into a partial update.
        from source_pipeline.traversals import bind_workbook_traversals

        bound_traversals = bind_workbook_traversals(traversals, encoding)
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    write_graph_records(out, graph, embed=False)
    canonical = canonical_encoding(encoding)
    canonical_bytes = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    metadata = {
        "schema_version": 1,
        "graph_id": graph.id,
        "domain": graph.domain,
        "concept_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "encoding_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "embedding_status": "NOT_BUILT",
    }
    traversal_sidecar = Path(str(out) + ".traversals.json")
    if bound_traversals is not None:
        traversal_path = traversal_sidecar
        traversal_path.write_text(
            json.dumps(bound_traversals, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        metadata["traversals"] = {
            "path": str(traversal_path),
            "fingerprint": bound_traversals["fingerprint"],
            "count": len(bound_traversals["traversals"]),
        }
    elif traversal_sidecar.exists():
        # The graph projection and its bound programs are one materialization.
        # Keeping a sidecar after the agent withdraws its source artifact would
        # silently keep an obsolete program active.
        traversal_sidecar.unlink()
    Path(str(out) + ".metadata.json").write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    if workbook is not None:
        from source_pipeline.sources_sidecar import write_sidecar

        write_sidecar(
            out,
            atoms,
            source_fingerprint=workbook.source_fingerprint(),
            workbook_root=workbook.root,
        )
    return out
