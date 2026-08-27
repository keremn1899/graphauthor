"""Lineage assembler (backlog B3 + B4) — "why does this node exist?"

Lineage is a PROJECTION over the event log, not a new write path. The chain is
already recorded as facts; assembling it is a fold indexed by node (the same
move as `mcp_server.ledger.project_activities`, oriented by node instead of
activity). Per the BFF decision, it is INFERRED and labelled "derived" — a
durable commit-time lineage record is deferred until export/packaging needs the
graph to carry its provenance without the event log.

Two roots:
- **evolution** — the node came through a proposal. Root = the graph.committed
  event → proposal → gap/escalation → PrimarySource → authority → graph_version.
- **unprovenanced** — no commit event: a workbook-materialized or seed node. Said
  plainly, never fabricated (honest failure applied to provenance).

B4: `authority_type` and `primary_source` are surfaced as RECORDED facts, kept
separate — authority is never parsed from the PrimarySource string.
"""

from __future__ import annotations

import interaction.event_types as event_types
import json
from pathlib import Path
from typing import Any


def _events(store_path: Path | str) -> list[dict]:
    from interaction.event_log import EventStore

    es = EventStore(store_path)
    try:
        return es.list_events()
    finally:
        es.close()


def _get_proposal(store_path: Path | str, proposal_id: str) -> dict | None:
    if not proposal_id:
        return None
    from interaction.write_path_store import WritePathStore

    store = WritePathStore(store_path)
    try:
        return store.get_proposal(proposal_id)
    finally:
        store.close()


def _committed_for_node(events: list[dict], node_id: str) -> dict | None:
    """Latest commit that names this node.

    A node may be added once and corrected later. Returning the first match
    would hide the rewrite that live readers actually see.
    """
    found = None
    for ev in events:
        if ev.get("type") != event_types.GRAPH_COMMITTED:
            continue
        try:
            sids = json.loads(ev.get("subject_node_ids") or "[]")
        except (ValueError, TypeError):
            sids = []
        if node_id in sids:
            found = ev
    return found


def node_lineage(node_id: str, *, store_path: Path | str,
                 db_path: Path | str | None = None) -> dict[str, Any]:
    """Assemble one node's proposal lineage without mutating the graph."""
    events = _events(store_path)
    commit = _committed_for_node(events, node_id)
    if commit is not None:
        return _evolution_lineage(node_id, commit, events, store_path)
    return {
        "node_id": node_id,
        "origin": "unprovenanced",
        "chain": [{"step": "node", "id": node_id}],
        "recorded": {},
        "derived": "no commit event records per-node provenance for this "
                   "workbook-materialized or seed node",
    }


def _correction_facts(rec: dict, commit: dict) -> dict[str, Any] | None:
    """Extract correction provenance from the proposal encoding and commit payload."""
    try:
        encoding = json.loads(rec.get("encoding_json") or "{}")
    except (ValueError, TypeError):
        encoding = {}
    corrections = list(encoding.get("corrections") or [])
    try:
        payload = json.loads(commit.get("payload") or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not corrections and not payload.get("subject_correction_ids"):
        return None
    reasons = payload.get("correction_reasons")
    if not isinstance(reasons, list) or not reasons:
        reasons = [
            {
                "id": str(c.get("id") or ""),
                "reason": str(c.get("reason") or ""),
                "intent": str(c.get("intent") or ""),
                "claim_kind": str(c.get("claim_kind") or ""),
            }
            for c in corrections
            if isinstance(c, dict)
        ]
    return {
        "corrected_ids": sorted({
            str(r.get("id") or "") for r in reasons if r.get("id")
        } | {str(i) for i in (payload.get("subject_correction_ids") or []) if i}),
        "reasons": reasons,
    }


def _evolution_lineage(node_id: str, commit: dict, events: list[dict],
                       store_path: Path | str) -> dict[str, Any]:
    pid = commit.get("proposal_id") or ""
    rec = _get_proposal(store_path, pid) or {}
    gap = commit.get("gap_id") or rec.get("target_gap_id") or ""
    # RECORDED — verbatim facts, authority kept separate from the source string.
    recorded = {
        "authority_type": commit.get("authority_type") or "",
        "primary_source": rec.get("primary_source") or "",
        "target_gap_id": gap,
        "graph_version_before": commit.get("graph_version_before") or "",
        "graph_version_after": commit.get("graph_version_after") or "",
        "commit_event_id": commit.get("event_id") or "",
        "proposal_id": pid,
        "decision_origin": rec.get("decision_origin") or "unspecified",
        "decided_at": rec.get("decided_at") or "",
    }
    correction = _correction_facts(rec, commit)
    if correction is not None:
        recorded["correction"] = True
        recorded["corrected_ids"] = correction["corrected_ids"]
        recorded["correction_reasons"] = correction["reasons"]

    # DERIVED — the ordered chain, assembled (not persisted).
    chain: list[dict] = [
        {"step": "node", "id": node_id},
    ]
    if correction is not None:
        # Makes D1 honest for live readers: the rewrite is visible without
        # restoring a snapshot. Prior graph version remains the byte-level record.
        chain.append({
            "step": "correction",
            "proposal_id": pid,
            "reason": next(
                (str(r.get("reason") or "") for r in correction["reasons"]
                 if r.get("id") == node_id),
                str((correction["reasons"][0] or {}).get("reason") or "")
                if correction["reasons"] else "",
            ),
            "graph_version_before": recorded["graph_version_before"],
            "corrected_ids": correction["corrected_ids"],
        })
    chain.extend([
        {"step": "commit", "event_id": commit.get("event_id") or "",
         "graph_version_after": recorded["graph_version_after"]},
        {"step": "proposal", "proposal_id": pid,
         "generating_task": rec.get("generating_task") or "",
         "decision_origin": recorded["decision_origin"]},
    ])
    if gap:
        chain.append({"step": "gap", "gap_id": gap})
    chain.append({"step": "primary_source", "primary_source": recorded["primary_source"],
                  "authority_type": recorded["authority_type"]})
    return {
        "node_id": node_id,
        "origin": "correction" if correction is not None else "evolution",
        "chain": chain,
        "recorded": recorded,
        "derived": "chain assembled from the event log + proposal store; "
                   "not a persisted lineage record",
    }


# ---------------------------------------------------------------------------
# edge lineage — first-class: an add_edge between pre-existing nodes has
# provenance distinct from either endpoint (the edge is often the governance
# assertion). Commit events carry subject_edge_refs in their payload.
# ---------------------------------------------------------------------------

def _committed_for_edge(events: list[dict], edge_ref: str) -> dict | None:
    for ev in events:
        if ev.get("type") != event_types.GRAPH_COMMITTED:
            continue
        try:
            payload = json.loads(ev.get("payload") or "{}")
        except (ValueError, TypeError):
            payload = {}
        if edge_ref in (payload.get("subject_edge_refs") or []):
            return ev
    return None


def edge_lineage(edge_ref: str, *, store_path: Path | str,
                 db_path: Path | str | None = None) -> dict[str, Any]:
    """Why does this edge exist? `edge_ref` is 'TYPE:source->target'. Same fold
    as node_lineage, indexed by edge. Unprovenanced when no commit carries it."""
    events = _events(store_path)
    commit = _committed_for_edge(events, edge_ref)
    if commit is None:
        return {"edge_ref": edge_ref, "origin": "unprovenanced",
                "chain": [{"step": "edge", "ref": edge_ref}], "recorded": {},
                "derived": "no commit event carries this edge — a fixture/seed "
                           "edge with no recorded provenance"}
    pid = commit.get("proposal_id") or ""
    rec = _get_proposal(store_path, pid) or {}
    gap = commit.get("gap_id") or rec.get("target_gap_id") or ""
    recorded = {
        "authority_type": commit.get("authority_type") or "",
        "primary_source": rec.get("primary_source") or "",
        "target_gap_id": gap,
        "graph_version_after": commit.get("graph_version_after") or "",
        "commit_event_id": commit.get("event_id") or "",
        "proposal_id": pid,
        "decision_origin": rec.get("decision_origin") or "unspecified",
    }
    chain = [
        {"step": "edge", "ref": edge_ref},
        {"step": "commit", "event_id": commit.get("event_id") or ""},
        {"step": "proposal", "proposal_id": pid,
         "decision_origin": recorded["decision_origin"]},
    ]
    chain.append(
        {
            "step": "primary_source",
            "primary_source": recorded["primary_source"],
            "authority_type": recorded["authority_type"],
        }
    )
    return {"edge_ref": edge_ref, "origin": "evolution", "chain": chain,
            "recorded": recorded,
            "derived": "chain assembled from the event log + proposal store; "
                       "the edge's provenance is its own proposal, not its endpoints'"}
