"""Unified grounded-but-empty packet recovery (absent-seam fix).

When sources ground but declared-edge traversal yields an empty packet on a
populated graph, read the BROAD topic region (depth-2 neighbourhood, all edge
types) so Battalion can run predicate-identity on non-empty evidence.

Carve-out: proof, global enumeration, honest multi-hop chain terminal miss
(intermediate found, terminal empty), source miss.
See ``design [new]/absent-seam-unified-recovery-handoff.md`` and
``design [new]/chain-path-recovery-extension-handoff.md``.
"""

from __future__ import annotations

from typing import Any

from models import EngineState
from tools import exact_node_lookup, get_neighbourhood

RECOVERY_FLAG = "empty_packet_broad_region_fallback"
_EXCLUDED_FORMS = frozenset({"proof"})


def _packet_empty(packet: dict) -> bool:
    return not (
        packet.get("node_records")
        or packet.get("edge_records")
        or packet.get("path_records")
    )


def _graph_populated(state: EngineState) -> bool:
    compass = state.get("compass") or {}
    try:
        return int((compass.get("graph_profile") or {}).get("node_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def _node_exists(conn, node_id: str) -> bool:
    try:
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.id LIMIT 1",
            {"id": node_id},
        ))
        return bool(rows)
    except Exception:
        return False


def grounded_source_ids(conn, source_ids: list[str]) -> list[str]:
    """Return graph node ids for sources that actually resolve."""
    from pipeline_b import _resolve_ids

    if not source_ids:
        return []
    out: list[str] = []
    for rid in _resolve_ids(conn, source_ids):
        hit = exact_node_lookup(conn, rid)
        if hit and hit.get("id"):
            out.append(str(hit["id"]))
        elif _node_exists(conn, str(rid)):
            out.append(str(rid))
    return out


def _grounded_ids_from_variables(variables: dict[str, list]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for items in (variables or {}).values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                nid = str(item["id"])
                if nid not in seen:
                    seen.add(nid)
                    ids.append(nid)
            elif isinstance(item, str) and item and item not in seen:
                seen.add(item)
                ids.append(item)
    return ids


def _planner_concept_ids(conn, program: dict | None) -> list[str]:
    """Resolve Strategy A/B concept tokens to node ids for exploratory recovery."""
    if not program:
        return []
    from pipeline_b import _resolve_ids

    concepts: list[str] = []
    for key in ("strategy_a", "strategy_b"):
        block = program.get(key) or {}
        if isinstance(block, dict):
            concepts.extend(str(c) for c in (block.get("concepts") or []) if c)
    return _resolve_ids(conn, concepts)


def _chain_terminal_miss_is_honest(
    question_form: str,
    steps: list,
    *,
    chain_intermediate_found: bool,
) -> bool:
    """Skip recovery only when a multi-hop chain found intermediates but missed terminal."""
    if str(question_form or "").lower() != "chain":
        return False
    if not chain_intermediate_found:
        return False
    return len(steps) > 1


def _eligible_question_form(question_form: str, *, has_sources: bool) -> bool:
    qf = str(question_form or "").lower()
    if qf in _EXCLUDED_FORMS:
        return False
    if qf == "enumeration" and not has_sources:
        return False
    if not qf and has_sources:
        return True
    return True


def try_broad_region_recovery(
    conn,
    state: EngineState,
    packet: dict,
    *,
    question_form: str = "",
    source_ids: list[str] | None = None,
    variables: dict[str, list] | None = None,
    program: dict | None = None,
    collected_ids: list[str] | None = None,
    chain_terminal_empty: bool = False,
    chain_intermediate_found: bool = False,
    existing_flags: list[str] | None = None,
) -> tuple[dict, list[str], bool]:
    """Attempt broad-region recovery. Returns (packet, flags, recovered)."""
    from backend_tools import build_evidence_packet

    flags = list(existing_flags or [])
    if not _packet_empty(packet) or not _graph_populated(state):
        return packet, flags, False
    if chain_terminal_empty and _chain_terminal_miss_is_honest(
        question_form,
        (program or {}).get("steps") or [],
        chain_intermediate_found=chain_intermediate_found,
    ):
        return packet, flags, False
    if str(question_form or "").lower() == "proof":
        return packet, flags, False

    srcs = list(source_ids or [])
    grounded = grounded_source_ids(conn, srcs) if srcs else []
    if not grounded and variables:
        grounded = _grounded_ids_from_variables(variables)
        grounded = [g for g in grounded if _node_exists(conn, g)]
    if not grounded and program:
        grounded = [
            g for g in _planner_concept_ids(conn, program)
            if _node_exists(conn, g)
        ]

    if not grounded:
        return packet, flags, False

    if not _eligible_question_form(question_form, has_sources=bool(srcs or grounded)):
        return packet, flags, False

    neighbourhood = get_neighbourhood(
        conn,
        node_ids=grounded,
        depth=2,
        edge_types=None,
        direction="both",
    )
    if not neighbourhood:
        return packet, flags, False

    recovery_vars = {"broad_recovery_region": neighbourhood}
    base_program = program or {}
    recovery_program = {
        "strategy_a": base_program.get("strategy_a") or {},
        "strategy_b": base_program.get("strategy_b") or {},
        "structural_intent": base_program.get("structural_intent", "null"),
        "steps": [{"tool": "get_neighbourhood", "assign_to": "broad_recovery_region"}],
    }
    ids = list(collected_ids or []) + [
        str(n["id"]) for n in neighbourhood if isinstance(n, dict) and n.get("id")
    ]
    new_packet = build_evidence_packet(conn, recovery_vars, recovery_program, ids)
    if _packet_empty(new_packet):
        return packet, flags, False

    if RECOVERY_FLAG not in flags:
        flags.append(RECOVERY_FLAG)
    # Pipeline B tests expect the legacy flag name too.
    legacy = "pipeline_b_empty_broad_region_fallback"
    if legacy not in flags:
        flags.append(legacy)
    return new_packet, sorted(set(flags)), True
