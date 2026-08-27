"""v7 deterministic correction loops.

Two loops implemented here; §8 of ``design [new]/graph-traversal-v7.md``:

- **Loop 1 — Hypothesis Grounding.** Between ``planner_initial`` and
  ``backend_execute``. Verifies that the Planner's declared identifiers
  (Strategy A / Strategy B concepts for exploratory, ``source_ids`` for
  targeted retrieval) actually exist in the graph before the Backend
  fires tool calls against them. If *all* declared IDs miss, the query
  is reseeded once; if *some* miss, we proceed with the verified subset
  and flag ``hypothesis_partial_grounding`` so Battalion can frame the
  answer honestly.

- **Loop 2 — Tool Dispatch Validation.** Between ``packet_integrity_check``
  and the downstream router. Checks that the executed retrieval program
  matches its declared intent. If ``structural_intent != null`` but no
  structural tool was dispatched, or if every step produced zero despite
  the Compass suggesting results should exist, the program is flagged
  ``tool_dispatch_mismatch:<tool>`` and Planner replan is triggered
  (once, capped per query).

Both loops are pure state transforms. They write diagnostic dicts into
``EngineState`` (``hypothesis_grounding_result``,
``tool_dispatch_validation_result``) and extend
``degradation_flags`` with well-named entries that the rest of the
pipeline already consumes.

Routing decisions are kept in ``agent_graph`` to preserve the single
topology definition.
"""

from __future__ import annotations

from typing import Any, Iterable

import real_ladybug as lb

from models import EngineState
from sst_debug import log_event
from tools import exact_node_lookup


_STRUCTURAL_DISPATCH_TOOLS = frozenset({
    "get_structural_profile",
    "query_structural_index",
})

# v9: proof / enumeration / fanout queries mechanically need edge traversal.
# The Planner sometimes emits only entity lookups (exact_node_lookup,
# vector_search) and leaves the packet edge-empty. This mirrors the
# structural_intent_without_structural_tool invariant.
_TRAVERSAL_DISPATCH_TOOLS = frozenset({
    "find_paths",
    "hop_expansion",
    "get_neighbourhood",
    "get_nodes_by_edge_type",
})


def _as_concept_list(block: Any) -> list[str]:
    """Pull ``concepts: [...]`` from a planner strategy dict safely."""
    if not isinstance(block, dict):
        return []
    concepts = block.get("concepts")
    if not isinstance(concepts, list):
        return []
    out: list[str] = []
    for item in concepts:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
    return out


def _collect_declared_terms(state: EngineState) -> tuple[list[str], str]:
    """Collect the terms that Loop 1 should verify, plus the origin tag.

    Returns (terms, origin) where origin is one of:
    - "compass_derivation" — Pipeline A; no grounding needed (empty terms)
    - "relational_contract" — Pipeline B; source_ids from the contract
    - "strategy_ab" — Pipeline C; strategy_a + strategy_b concepts
    """
    route = (state.get("planner_route") or "exploratory").strip().lower()

    if route in {"map_reader", "compass_derivation"}:
        return [], "compass_derivation"

    if route == "targeted_retrieval":
        contract = state.get("relational_contract") or {}
        if isinstance(contract, dict):
            src = contract.get("source_ids")
            if isinstance(src, list):
                return [s.strip() for s in src if isinstance(s, str) and s.strip()], "relational_contract"
        return [], "relational_contract"

    # Exploratory (default).
    program = state.get("planner_program") or {}
    sa = _as_concept_list(program.get("strategy_a"))
    sb = _as_concept_list(program.get("strategy_b"))
    # Deduplicate but preserve order.
    seen: set[str] = set()
    terms: list[str] = []
    for t in (*sa, *sb):
        if t in seen:
            continue
        seen.add(t)
        terms.append(t)
    return terms, "strategy_ab"


def _prefix_alternatives(
    structural_index: dict,
    missing: Iterable[str],
    limit: int = 5,
) -> dict[str, list[str]]:
    """Suggest prefix-matched alternatives for missing terms from the index.

    Deterministic best-effort: for each missing term, look for index
    keys that begin with its lowercased first three characters. This is
    the v7 spec's suggestion for reseed feedback.
    """
    if not isinstance(structural_index, dict) or not structural_index:
        return {m: [] for m in missing}

    lowered_keys = sorted(structural_index.keys())
    out: dict[str, list[str]] = {}
    for term in missing:
        prefix = term.strip().lower()[:3]
        if not prefix:
            out[term] = []
            continue
        matches: list[str] = []
        for key in lowered_keys:
            if key.lower().startswith(prefix):
                matches.append(key)
                if len(matches) >= limit:
                    break
        out[term] = matches
    return out


def hypothesis_grounding_node(state: EngineState, conn: lb.Connection) -> dict:
    """Loop 1: verify Planner-declared IDs/concepts exist in the graph.

    Emits:
      - ``hypothesis_grounding_result``: {verified_ids, missing_ids, proceed,
        origin, alternatives}
      - ``degradation_flags``: extended with
        ``hypothesis_partial_grounding`` or ``hypothesis_full_miss`` as
        appropriate.
    """
    terms, origin = _collect_declared_terms(state)
    existing_flags = list(state.get("degradation_flags") or [])

    if not terms:
        # Nothing to ground (Pipeline A, or empty program). Pass through.
        result = {
            "verified_ids": [],
            "missing_ids": [],
            "alternatives": {},
            "proceed": True,
            "origin": origin,
            "reason": "no_declared_terms",
        }
        log_event("hypothesis_grounding_skip", origin=origin)
        return {"hypothesis_grounding_result": result}

    verified: list[str] = []
    missing: list[str] = []
    verified_map: dict[str, str] = {}
    for term in terms:
        try:
            hit = exact_node_lookup(conn, term)
        except Exception:
            hit = None
        if hit and hit.get("id"):
            node_id = str(hit["id"])
            verified.append(term)
            verified_map[term] = node_id
        else:
            missing.append(term)

    structural_index = state.get("structural_index") or {}
    alternatives = _prefix_alternatives(structural_index, missing) if missing else {}

    reseed_attempted = bool(state.get("reseed_attempted"))
    all_missing = len(verified) == 0 and len(missing) > 0
    partial = len(verified) > 0 and len(missing) > 0

    new_flags = list(existing_flags)
    if all_missing and not reseed_attempted:
        # Planner-level fault. Signal reseed to the router; backend stays
        # uncalled this round.
        if "hypothesis_full_miss" not in new_flags:
            new_flags.append("hypothesis_full_miss")
        proceed = False
    elif partial:
        if "hypothesis_partial_grounding" not in new_flags:
            new_flags.append("hypothesis_partial_grounding")
        proceed = True
    else:
        # Fully verified OR fully missing on a second pass — let the
        # pipeline run so downstream tiers can report honestly.
        proceed = True

    result = {
        "verified_ids": [verified_map[t] for t in verified if t in verified_map],
        "verified_terms": verified,
        "missing_ids": missing,
        "alternatives": alternatives,
        "proceed": proceed,
        "origin": origin,
    }

    log_event(
        "hypothesis_grounding",
        origin=origin,
        verified_count=len(verified),
        missing_count=len(missing),
        proceed=proceed,
        reseed_attempted=reseed_attempted,
    )

    out: dict = {"hypothesis_grounding_result": result}
    if new_flags != existing_flags:
        out["degradation_flags"] = sorted(set(new_flags))
    return out


def _steps_tools(program: dict) -> list[str]:
    """Flatten tool names across main + fallback steps."""
    names: list[str] = []
    for step in program.get("steps") or []:
        tool = str(step.get("tool") or "").strip().lower()
        if tool:
            names.append(tool)
    cont = program.get("contingency") or {}
    for step in cont.get("fallback_steps") or []:
        tool = str(step.get("tool") or "").strip().lower()
        if tool:
            names.append(tool)
    return names


def tool_dispatch_validation_node(state: EngineState) -> dict:
    """Loop 2: validate retrieval program matches declared intent.

    Checks two properties:

    1. **Intent→tool binding.** If ``structural_intent`` is non-null, the
       program must include at least one structural tool
       (``get_structural_profile`` or ``query_structural_index``).
    2. **Evidence production.** If the packet contains zero records and
       Compass shows the graph is non-empty, flag a generic
       ``tool_dispatch_mismatch:no_records`` so the Planner can replan.

    Emits ``tool_dispatch_validation_result`` and extends
    ``degradation_flags``. Replan routing is a separate concern; this
    node only diagnoses.
    """
    program = state.get("planner_program") or {}
    packet = state.get("evidence_packet") or {}
    existing_flags = list(state.get("degradation_flags") or [])

    intent = str(program.get("structural_intent") or "").strip().lower()
    dispatched = _steps_tools(program)

    mismatches: list[str] = []

    if intent and intent not in {"", "null", "none"}:
        if not any(t in _STRUCTURAL_DISPATCH_TOOLS for t in dispatched):
            mismatches.append("structural_intent_without_structural_tool")

    # v9: relation_proof / fanout / enumeration must dispatch at least one
    # traversal tool — otherwise the packet will have no edges and the
    # answer cannot be grounded structurally.
    contract = program.get("answer_contract") or {}
    qclass = str(contract.get("query_class") or "").lower()
    if qclass in {"relation_proof", "fanout", "enumeration"}:
        if not any(t in _TRAVERSAL_DISPATCH_TOOLS for t in dispatched):
            mismatches.append(f"{qclass}_without_traversal_tool")

    has_nodes = bool(packet.get("node_records"))
    has_edges = bool(packet.get("edge_records"))
    has_paths = bool(packet.get("path_records"))
    packet_empty = not (has_nodes or has_edges or has_paths)
    compass = state.get("compass") or {}
    graph_node_count = 0
    if isinstance(compass, dict):
        gp = compass.get("graph_profile") or {}
        if isinstance(gp, dict):
            graph_node_count = int(gp.get("node_count") or 0)
    if packet_empty and graph_node_count > 0:
        mismatches.append("empty_packet_in_populated_graph")

    replan_attempted = bool(state.get("reseed_attempted"))
    replan_required = bool(mismatches) and not replan_attempted

    new_flags = list(existing_flags)
    for m in mismatches:
        flag = f"tool_dispatch_mismatch:{m}"
        if flag not in new_flags:
            new_flags.append(flag)

    result = {
        "mismatches": mismatches,
        "dispatched_tools": sorted(set(dispatched)),
        "structural_intent": intent or "null",
        "replan_required": replan_required,
    }

    log_event(
        "tool_dispatch_validation",
        mismatches=mismatches,
        dispatched_tools=sorted(set(dispatched)),
        structural_intent=intent or "null",
        replan_required=replan_required,
    )

    out: dict = {"tool_dispatch_validation_result": result}
    if new_flags != existing_flags:
        out["degradation_flags"] = sorted(set(new_flags))
    return out
