"""Fill the claim field from a packet. No retrieval. Called by Ask."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import real_ladybug as lb


def trails_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Company-shaped trails so Ask can page payloads.

    Paths become primary trails. A packet with only nodes becomes one trail
    named ``packet``. Search-only candidates stay trails — the caller marks
    the verdict so the prose cannot treat them as closure.
    """
    trails: list[dict[str, Any]] = []
    for i, path in enumerate(packet.get("path_records") or []):
        if not isinstance(path, dict):
            continue
        node_ids = list(path.get("node_chain") or path.get("node_ids") or [])
        if not node_ids and path.get("source") and path.get("target"):
            node_ids = [str(path["source"]), str(path["target"])]
        trails.append({
            "trail_id": str(path.get("trail_id") or f"path_{i}"),
            "origin": str(path.get("origin") or "retrieve"),
            "rationale": "retrieved path",
            "node_ids": [str(n) for n in node_ids if n],
            "edge_types": [str(t) for t in (path.get("edge_chain") or path.get("edge_types") or [])],
            "edge_labels": [str(t or "") for t in (path.get("edge_label_chain") or path.get("edge_labels") or [])],
        })
    if not trails:
        ids = [
            str(n.get("id"))
            for n in (packet.get("node_records") or [])
            if isinstance(n, dict) and n.get("id")
        ]
        if ids:
            edges = [e for e in (packet.get("edge_records") or []) if isinstance(e, dict)]
            trails.append({
                "trail_id": "packet",
                "origin": "retrieve",
                "rationale": "retrieved nodes",
                "node_ids": ids,
                "edge_types": [str(e.get("edge_type") or "") for e in edges],
                "edge_labels": [str(e.get("edge_label") or e.get("label") or "") for e in edges],
            })
    return {
        "primary_trails": trails,
        "supporting_trails": [],
        "context_trails": [],
        "gaps": list(packet.get("gaps") or []),
    }


def write_claim(
    query: str,
    packet: dict[str, Any],
    conn: "lb.Connection | None",
    *,
    verdict: str = "CONFIRMED",
    compass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prose over ``packet``. Retrieval already happened; this does not fetch."""
    from battalion import battalion_synthesize

    state = {
        "query": query,
        "evidence_packet": packet or {},
        "confirmation_response": {"verdict": verdict},
        "company_handoff": {"internal_handoff": trails_from_packet(packet or {})},
        "compass": compass or {},
        "degradation_flags": list((packet or {}).get("degradation_flags") or []),
        "retrieval_strategy": "contract_driven",
        # Ask is confirmation space. Without this, Battalion's governance
        # fold overwrites a real answer with ILL_POSED ("no policy governs
        # this") — a true answer to a different question.
        "verdict_space": "confirmation",
        "verdict_space_source": "caller",
    }
    out = battalion_synthesize(state, conn)
    state.update(out)
    return state
