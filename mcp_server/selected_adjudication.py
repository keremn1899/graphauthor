"""Experimental host-selected evidence adjudication.

The host chooses stable node IDs; the server re-reads them and Battalion judges
their applicability.  Selection never proves corpus completeness.  Only the
server-issued full-graph closure implemented here can promote a selected-scope
permission or absence to the corpus top line.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from conformance_verdict import ConformanceVerdict
from retrieval_program import canonicalise_program, execute_retrieval_program


SELECTED_ADJUDICATION_VERSION = "host-selected-adjudication-v1.1"
CLOSURE_CONTRACT_VERSION = "closure-v1"
FULL_GRAPH_NODE_LIMIT = 300
SELECTED_NODE_LIMIT = 50
_EDGE_TYPES = ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO")


class SelectedEvidenceError(ValueError):
    """Typed caller/precondition failure raised before any model call."""

    def __init__(self, code: str, detail: str, *, missing_ids: list[str] | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.missing_ids = list(missing_ids or [])


def canonical_selected_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise SelectedEvidenceError(
            "INVALID_EVIDENCE_IDS", "evidence_node_ids must be a list"
        )
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    cleaned = list(dict.fromkeys(cleaned))
    if not cleaned:
        raise SelectedEvidenceError(
            "INVALID_EVIDENCE_IDS", "at least one stable evidence node ID is required"
        )
    if len(cleaned) > SELECTED_NODE_LIMIT:
        raise SelectedEvidenceError(
            "INVALID_EVIDENCE_IDS",
            f"at most {SELECTED_NODE_LIMIT} host-selected IDs are accepted",
        )
    return cleaned


def _all_graph_nodes(conn) -> tuple[list[str], bool]:
    try:
        rows = list(conn.execute("MATCH (c:Concept) RETURN c.id, c.is_metanode"))
        ids = [str(row[0]) for row in rows if str(row[0] or "").strip()]
        has_metanode = any(bool(row[1]) for row in rows)
    except Exception:
        rows = list(conn.execute("MATCH (c:Concept) RETURN c.id"))
        ids = [str(row[0]) for row in rows if str(row[0] or "").strip()]
        has_metanode = False
    return sorted(set(ids)), has_metanode


def _induced_edges(conn, node_ids: set[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for edge_type in _EDGE_TYPES:
        rows = conn.execute(
            f"MATCH (a:Concept)-[e:{edge_type}]->(b:Concept) "
            "RETURN a.id, a.label, b.id, b.label, e.label"
        )
        for source_id, source_label, target_id, target_label, edge_label in rows:
            source = str(source_id or "")
            target = str(target_id or "")
            if source not in node_ids or target not in node_ids:
                continue
            edges.append({
                "source_id": source,
                "source_label": str(source_label or ""),
                "target_id": target,
                "target_label": str(target_label or ""),
                "edge_type": edge_type.lower(),
                "edge_label": str(edge_label or ""),
                "origin": "host_selected_induced",
                "from_tool": "exact_node_lookup",
            })
    return edges


def _node_set_hash(node_ids: list[str]) -> str:
    encoded = json.dumps(
        sorted(node_ids), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_selected_packet(
    conn,
    evidence_node_ids: list[str],
    *,
    graph_version: str,
    closure_mode: str = "none",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Re-read exact IDs and optionally expand them to a closed full snapshot."""
    selected = canonical_selected_ids(evidence_node_ids)
    closure_mode = str(closure_mode or "none").strip().lower()
    if closure_mode not in {"none", "full_graph"}:
        raise SelectedEvidenceError(
            "INVALID_CLOSURE_MODE", "closure_mode must be none or full_graph"
        )

    closure_receipt: dict[str, Any] | None = None
    effective_ids = list(selected)
    if closure_mode == "full_graph":
        all_ids, has_metanode = _all_graph_nodes(conn)
        if has_metanode:
            raise SelectedEvidenceError(
                "CLOSURE_UNSUPPORTED_METANODE",
                "full_graph V1 closure does not cross metanode boundaries",
            )
        if len(all_ids) > FULL_GRAPH_NODE_LIMIT:
            raise SelectedEvidenceError(
                "CLOSURE_GRAPH_TOO_LARGE",
                f"full_graph V1 closure is limited to {FULL_GRAPH_NODE_LIMIT} nodes",
            )
        effective_ids = all_ids
        closure_receipt = {
            "contract_version": CLOSURE_CONTRACT_VERSION,
            "kind": "full_graph",
            "graph_version": graph_version,
            "node_count": len(all_ids),
            "node_ids_sha256": _node_set_hash(all_ids),
            "complete": True,
        }

    program = canonicalise_program({
        "contract_version": "retrieval-v1",
        "author": "direct",
        "steps": [{
            "tool": "exact_node_lookup",
            "params": {"label_or_id": effective_ids},
            "assign_to": "selected",
        }],
        "collect": "$selected",
        "limits": {"max_recovery_rounds": 0},
    })
    execution = execute_retrieval_program(conn, program)
    packet = dict(execution["evidence_packet"])
    resolved = sorted(
        str(node.get("id") or "")
        for node in packet.get("node_records") or []
        if str(node.get("id") or "")
    )
    expected = sorted(effective_ids)
    missing = sorted(set(expected) - set(resolved))
    # A label may resolve successfully to a different stable ID.  That is a
    # valid lookup operation, but not a valid stable-ID evidence reference.
    substituted = sorted(set(resolved) - set(expected))
    if missing or substituted:
        raise SelectedEvidenceError(
            "UNRESOLVED_EVIDENCE_ID",
            "every evidence reference must resolve to the identical stable node ID",
            missing_ids=missing or substituted,
        )

    packet["edge_records"] = _induced_edges(conn, set(effective_ids))
    packet["evidence_selection_mode"] = "host_selected"
    packet["selection_graph_version"] = graph_version
    selection_receipt = {
        "contract_version": SELECTED_ADJUDICATION_VERSION,
        "graph_version": graph_version,
        "requested_node_ids": selected,
        "resolved_node_ids": resolved,
        "effective_node_count": len(effective_ids),
        "effective_node_ids_sha256": _node_set_hash(effective_ids),
        "closure_mode": closure_mode,
    }
    packet["selection_receipt"] = selection_receipt
    return packet, selection_receipt, closure_receipt


def selected_result_gate(
    verdict: ConformanceVerdict,
    *,
    closure_receipt: dict[str, Any] | None,
    graph_version: str = "",
) -> dict[str, Any]:
    """Project bounded adjudication onto the safe corpus-facing top line."""
    selected_ruling = verdict.verdict.value
    coverage = str(verdict.governance_status or "")
    closure_valid = bool(
        closure_receipt
        and closure_receipt.get("contract_version") == CLOSURE_CONTRACT_VERSION
        and closure_receipt.get("kind") == "full_graph"
        and closure_receipt.get("complete") is True
        and bool(str(graph_version or ""))
        and closure_receipt.get("graph_version") == graph_version
        and int(closure_receipt.get("node_count") or 0) > 0
        and len(str(closure_receipt.get("node_ids_sha256") or "")) == 64
    )
    kind = selected_ruling
    safe_to_act = False
    blocking = selected_ruling == "VIOLATES"
    gap_recordable = bool(closure_valid and selected_ruling == "UNGOVERNED")
    downgrade_reason = ""
    disposition = str(verdict.disposition or "")
    owner_decision_required = bool(verdict.owner_decision_required)

    if verdict.engine_degraded:
        kind = "INSUFFICIENT_EVIDENCE"
        blocking = False
        gap_recordable = False
        downgrade_reason = "bounded adjudication was degraded"
        disposition = ""
        owner_decision_required = False
    elif selected_ruling == "CONFORMS":
        safe_to_act = bool(
            closure_valid
            and coverage == "GOVERNED"
            and verdict.applying_policy_ids
        )
        if not safe_to_act:
            kind = "INSUFFICIENT_EVIDENCE"
            downgrade_reason = (
                "selected policies conform, but corpus permission requires closure"
            )
            disposition = "CORPUS_CLOSURE_REQUIRED"
            owner_decision_required = False
        else:
            disposition = "NONE"
            owner_decision_required = False
    elif selected_ruling == "UNGOVERNED" and not closure_valid:
        kind = "INSUFFICIENT_EVIDENCE"
        downgrade_reason = (
            "selected evidence contains no applying policy, but graph absence "
            "requires closure"
        )
        disposition = "CORPUS_CLOSURE_REQUIRED"
        owner_decision_required = False
    elif selected_ruling == "UNGOVERNED":
        disposition = "OWNER_DECISION_REQUIRED"
        owner_decision_required = True
    elif coverage == "PARTIALLY_GOVERNED":
        kind = "INSUFFICIENT_EVIDENCE"
        gap_recordable = False
        downgrade_reason = "selected evidence governs only part of the predicate"
        disposition = "OWNER_DECISION_REQUIRED"
        owner_decision_required = True
    elif selected_ruling == "VIOLATES":
        disposition = "REVISE"
        owner_decision_required = False

    return {
        "kind": kind,
        "selected_ruling": selected_ruling,
        "selected_coverage": coverage,
        "safe_to_act": safe_to_act,
        "blocking": blocking,
        "gap_recordable": gap_recordable,
        "closure_valid": closure_valid,
        "downgrade_reason": downgrade_reason,
        "disposition": disposition,
        "owner_decision_required": owner_decision_required,
    }
