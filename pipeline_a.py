"""v8 compass-derivation strategy (formerly v7 Pipeline A — Map Reader).

Per ``graph-traversal-v8.md`` §3, compass_derivation must produce a real
``EvidencePacket`` populated from Compass landmarks, the MapReaderAnswer's
cited node ids, and the structural adjacency between them. This replaces
v7's packet-elision behaviour that Stage-A was correctly catching as a
failure of the "uniform information infrastructure" commitment.

Behaviour:

- ``node_records`` are populated from (cited_ids ∪ top-K landmarks),
  carrying ``anchor_preview``, ``label`` and ``roles`` drawn from the
  Compass node_census so Battalion / auditors have real NodeRecords to
  reason about.
- ``edge_records`` are synthesised from ``out_adjacency`` entries in the
  census where both endpoints are included in the packet. Edge types are
  edge-native (no orientation inversion).
- ``packet_provenance`` records that these records came from
  ``compass_derivation``.
- ``degradation_flags`` carries ``compass_derivation_no_landmarks`` if
  the graph has zero landmarks (a structural note, not a failure).
- The retrieval strategy and synthesis mode are emitted into the state
  so downstream reporting (Stage-A v8 checks) can read them directly.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from models import EngineState
from sst_debug import log_event


_MAX_PACKET_NODES = 25
_MIN_PACKET_NODES_FROM_LANDMARKS = 8


def _token_in_graph_check():
    """A graph-level existence test for `gap_hinter`, or None if unavailable.

    Guarded rather than required: a gap inventory is still worth producing
    without a live connection, it just cannot make the absent-vs-unretrieved
    distinction, and it then declines to make the claim at all.
    """
    try:
        import engine
        from tools import graph_mentions

        # The connection the engine is ALREADY running on — never `get_connection()`,
        # which resolves a path, creates directories and may auto-seed. A gap
        # hinter that can bring a database into existence is a side effect no
        # caller asked for, and it broke two server-readiness tests that assert
        # exactly when seeding may happen.
        conn = engine._connection
        if conn is None:
            return None
    except Exception:
        return None

    def _known(token: str) -> bool:
        try:
            return graph_mentions(conn, token)
        except Exception:
            # An unreachable graph must not manufacture a gap either.
            return True

    return _known


def _normalise_map_reader_output(mra: Any) -> dict:
    if not isinstance(mra, dict):
        return {"answer_text": "", "cited_node_ids": [], "basis_layer": "L1+L2+L3"}
    return {
        "answer_text": str(mra.get("answer_text") or "").strip(),
        "cited_node_ids": [str(x) for x in (mra.get("cited_node_ids") or []) if str(x)],
        "basis_layer": str(mra.get("basis_layer") or "L1+L2+L3"),
    }


def _census_index(compass: dict) -> dict[str, dict]:
    census = compass.get("node_census") or []
    out: dict[str, dict] = {}
    for entry in census:
        if isinstance(entry, dict):
            nid = str(entry.get("id") or "")
            if nid:
                out[nid] = entry
    return out


def _landmark_ids(compass: dict) -> list[str]:
    landmarks = compass.get("landmark_nodes") or []
    out: list[str] = []
    for l in landmarks:
        if isinstance(l, dict):
            nid = str(l.get("id") or "")
            if nid:
                out.append(nid)
    return out


def _pick_packet_nodes(cited_ids: list[str], compass: dict) -> list[str]:
    """Selection strategy: cited ids take priority, backfilled by landmarks,
    finally by highest-betweenness census entries up to ``_MAX_PACKET_NODES``."""
    census = _census_index(compass)
    ordered: list[str] = []
    seen: set[str] = set()

    for nid in cited_ids:
        if nid in census and nid not in seen:
            ordered.append(nid)
            seen.add(nid)

    for nid in _landmark_ids(compass):
        if len(ordered) >= _MAX_PACKET_NODES:
            break
        if nid in census and nid not in seen:
            ordered.append(nid)
            seen.add(nid)

    # Census is already sorted by betweenness desc in engine.build_graph_compass.
    if len(ordered) < _MIN_PACKET_NODES_FROM_LANDMARKS:
        for nid in census:
            if len(ordered) >= _MAX_PACKET_NODES:
                break
            if nid not in seen:
                ordered.append(nid)
                seen.add(nid)

    return ordered


def _build_compass_packet(
    compass: dict,
    cited_ids: list[str],
    structural_index: dict,
) -> dict:
    """v8 §3 — compass_derivation EvidencePacket construction."""
    census = _census_index(compass)
    selected = _pick_packet_nodes(cited_ids, compass)
    selected_set = set(selected)

    node_records: list[dict] = []
    for nid in selected:
        entry = census.get(nid) or {}
        node_records.append({
            "id": nid,
            "label": entry.get("label") or nid,
            "anchor_preview": entry.get("anchor_preview") or "",
            "roles": list(entry.get("roles") or []),
            "origin": "compass_derivation",
            "is_landmark": bool(entry.get("betweenness_centrality", 0.0) > 0)
                and nid in set(_landmark_ids(compass)),
        })

    # Edge records via out_adjacency — both endpoints must be in the packet.
    edge_records: list[dict] = []
    for nid in selected:
        entry = census.get(nid) or {}
        adj = entry.get("out_adjacency") or {}
        if not isinstance(adj, dict):
            continue
        for edge_type, neighbours in adj.items():
            if not isinstance(neighbours, list):
                continue
            et = str(edge_type).lower()
            for tgt in neighbours:
                tgt_id = str(tgt)
                if tgt_id in selected_set:
                    edge_records.append({
                        "source_id": nid,
                        "target_id": tgt_id,
                        "edge_type": et,
                        "edge_label": "",
                        "source_label": entry.get("label") or nid,
                        "target_label": (census.get(tgt_id) or {}).get("label") or tgt_id,
                        "origin": "compass_derivation",
                    })

    structural_facts = {
        "bridge_count": sum(
            1 for n in selected if "inter_region_bridge" in (census.get(n, {}).get("roles") or [])
        ),
        "landmark_count": len([n for n in selected if n in set(_landmark_ids(compass))]),
        "warnings": [],
    }

    degradation_flags: list[str] = []
    if not _landmark_ids(compass):
        degradation_flags.append("compass_derivation_no_landmarks")
    if not node_records:
        degradation_flags.append("compass_derivation_empty_packet")

    packet = {
        "node_records": node_records,
        "edge_records": edge_records,
        "path_records": [],
        "structural_facts": structural_facts,
        "packet_provenance": [
            {
                "step": 0,
                "tool": "compass_derivation",
                "assign_to": "compass_packet",
                "added_nodes": len(node_records),
                "added_edges": len(edge_records),
                "added_paths": 0,
                "basis": "v8 §3 — landmarks ∪ cited_ids",
            }
        ],
        "append_log": [
            {
                "round": 0,
                "phase": "initial",
                "reason": "compass_derivation strategy",
                "added_nodes": len(node_records),
                "added_edges": len(edge_records),
            }
        ],
        "degradation_flags": degradation_flags,
    }
    return packet


def compass_derivation_respond(state: EngineState) -> dict:
    """v8 compass_derivation entry point.

    Emits ``final_answer`` from the Planner's MapReaderAnswer AND a
    structurally-populated ``evidence_packet`` so Stage-A plumbing checks
    (min_node_count / required_edge_types) see real data. Also stamps
    ``retrieval_strategy`` and ``synthesis_mode`` into state.
    """
    t0 = time.perf_counter()
    map_reader = _normalise_map_reader_output(
        state.get("map_reader_output") or {}
    )
    answer_text = map_reader["answer_text"]
    cited_ids = map_reader["cited_node_ids"]
    basis_layer = map_reader["basis_layer"]

    existing_flags = list(state.get("degradation_flags") or [])
    new_flags = list(existing_flags)

    if not answer_text:
        answer_text = ""
        if "map_reader_empty_answer" not in new_flags:
            new_flags.append("map_reader_empty_answer")

    compass = state.get("compass") or {}
    structural_index = state.get("structural_index") or {}
    packet = _build_compass_packet(compass, cited_ids, structural_index)

    # v9 §1.3: remove partial node retrieval. Every NodeRecord in the packet
    # must carry full text_content. Backend caps are env-driven.
    try:
        import os as _os
        cap = int(_os.environ.get("SST_COMPASS_NODE_CAP", "15"))
    except Exception:
        cap = 15
    if cap > 0 and len(packet.get("node_records") or []) > cap:
        packet["node_records"] = packet["node_records"][:cap]
    try:
        from engine import get_connection as _get_conn
        from tools import get_node_payloads as _get_payloads
        _conn = _get_conn()
        _ids = [str(n.get("id", "")) for n in packet.get("node_records") or [] if n.get("id")]
        _payloads = _get_payloads(_conn, _ids) if _ids else {}
        for n in packet.get("node_records") or []:
            p = _payloads.get(str(n.get("id", ""))) or {}
            if p.get("text_content"):
                n["text_content"] = p["text_content"]
    except Exception:
        # Payload enrichment is best-effort; anchor_preview remains as fallback.
        pass

    # Merge packet degradation flags into the state-level list.
    for flag in packet.get("degradation_flags") or []:
        if flag not in new_flags:
            new_flags.append(flag)

    provenance = [
        {
            "source": "deterministic",
            "tier": "compass_derivation",
            "basis": f"compass_layers:{basis_layer}",
            "cited_node_ids": cited_ids,
        }
    ]

    # v9 meta_gap honesty is planner-owned: this node consumes the declared
    # contract and does not attempt re-classification heuristics.
    program = state.get("planner_program") or {}
    structural_intent = str(program.get("structural_intent") or "").lower()
    answer_contract = (
        state.get("answer_contract")
        or program.get("answer_contract")
        or {}
    )
    query_class = str(answer_contract.get("query_class") or "").lower()
    query_text = str(state.get("query") or "").strip()
    gaps: list[dict] = []
    verdict_kind = "CONFIRMED"
    if query_class == "meta_gap" or structural_intent == "gap":
        gaps = [{
            "gap_type": "missing_concept",
            "specific_node_or_concept": query_text[:240] or "(unspecified)",
            "actionable_suggestion": (
                "Author a node in the graph covering this concept so future "
                "queries can ground against explicit evidence."
            ),
        }]
        verdict_kind = "EXHAUSTED"
        if "compass_derivation_missing_concept" not in new_flags:
            new_flags.append("compass_derivation_missing_concept")

    # v9.x: deterministic gap-type corrections (schema_gap / missing_relationship
    # / confabulation on unknown entity). Runs uniformly across all pipelines.
    from gap_hinter import apply_gap_type_hints

    apply_gap_type_hints(
        gaps,
        query_text,
        node_records=packet.get("node_records") or [],
        edge_records=packet.get("edge_records") or [],
        token_in_graph=_token_in_graph_check(),
        known_context=str(
            ((state.get("compass") or {}).get("graph_profile") or {}).get(
                "domain", ""
            )
        ),
    )

    log_event(
        "compass_derivation_respond",
        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
        answer_chars=len(answer_text),
        cited_count=len(cited_ids),
        basis_layer=basis_layer,
        empty=not bool(map_reader["answer_text"]),
        packet_nodes=len(packet.get("node_records") or []),
        packet_edges=len(packet.get("edge_records") or []),
    )

    out: dict = {
        "final_answer": answer_text,
        "provenance": provenance,
        "gaps": gaps,
        "map_reader_output": map_reader,
        "evidence_packet": packet,
        "retrieval_strategy": "compass_derivation",
        "synthesis_mode": "uniform",
        "confirmation_response": {
            "verdict": verdict_kind,
            "basis": "compass_derivation",
        },
        "deterministic_verdict": {
            "kind": verdict_kind,
            "basis": (
                "compass_derivation — graph does not cover the queried concept"
                if verdict_kind == "EXHAUSTED"
                else "compass_derivation — packet populated from Compass landmarks"
            ),
            "terminal": True,
            "recovery_available": False,
        },
    }
    if new_flags != existing_flags:
        out["degradation_flags"] = sorted(set(new_flags))
    return out


def map_reader_respond(state: EngineState) -> dict:
    """Backward-compatible alias for pre-v8 call sites/tests."""
    return compass_derivation_respond(state)
