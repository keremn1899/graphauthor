"""v7 §7 — deterministic verdict computation.

Replaces the v6 ``planner_confirmation`` LLM tier for Pipeline C
(exploratory) traversals. The verdict is a function of:

- the canonical ``EvidencePacket`` (what was actually retrieved),
- the soft ``AnswerContract`` (what the Planner declared was needed),
- the ``CompanyVerdict`` (interpretive hypothesis assessment),
- Compass-derived graph facts (what the graph schema can produce).

Every branch condition is expressible from data the pipeline already
has, so no LLM call is needed. The escape hatch (re-introduce an LLM
tier) is documented in v7 §7 and remains a future option if the
deterministic logic is shown to misclassify edge cases.

Pipelines A and B compute their own verdicts in their pipeline modules
and are passed through unchanged here.
"""

from __future__ import annotations

import time
from typing import Any

from models import EngineState
from sst_debug import log_event


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map evidence-shape tokens to packet fields/edge requirements.
_SHAPE_REQUIRES_EDGES = frozenset({"edge_pairs", "subgraph", "path"})
_SHAPE_REQUIRES_PATHS = frozenset({"path"})
_SHAPE_REQUIRES_NODES = frozenset({"node_set", "subgraph", "complement", "comparison"})


# ---------------------------------------------------------------------------
# Compass-derived graph facts
# ---------------------------------------------------------------------------


def _compass_edge_counts(state: EngineState) -> dict[str, int]:
    compass = state.get("compass") or {}
    gp = compass.get("graph_profile") or {}
    edges = gp.get("edge_counts") or {}
    out: dict[str, int] = {}
    for k, v in edges.items():
        try:
            out[str(k).lower()] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _compass_node_count(state: EngineState) -> int:
    compass = state.get("compass") or {}
    gp = compass.get("graph_profile") or {}
    try:
        return int(gp.get("node_count") or 0)
    except (TypeError, ValueError):
        return 0


def _compass_total_edges(state: EngineState) -> int:
    counts = _compass_edge_counts(state)
    if counts:
        return sum(counts.values())
    compass = state.get("compass") or {}
    gp = compass.get("graph_profile") or {}
    try:
        return int(gp.get("total_edges") or 0)
    except (TypeError, ValueError):
        return 0


def _compass_landmark_ids(state: EngineState) -> set[str]:
    compass = state.get("compass") or {}
    landmarks = compass.get("landmark_nodes") or []
    return {str(l.get("id") or "") for l in landmarks if isinstance(l, dict)}


# ---------------------------------------------------------------------------
# Packet-derived facts
# ---------------------------------------------------------------------------


def _packet_shape_inventory(packet: dict) -> dict[str, bool]:
    return {
        "node_set": bool(packet.get("node_records")),
        "edge_pairs": bool(packet.get("edge_records")),
        "subgraph": bool(packet.get("node_records")) and bool(packet.get("edge_records")),
        "path": bool(packet.get("path_records")),
        "count": bool(packet.get("node_records")),
        "complement": bool(packet.get("node_records")),
        "comparison": bool(packet.get("node_records")),
    }


# ---------------------------------------------------------------------------
# Core deterministic checks
# ---------------------------------------------------------------------------


def _primitive_shapes_unproducible(
    contract: dict,
    state: EngineState,
) -> tuple[bool, str]:
    """v7 §7: a contract shape is unproducible if the graph schema cannot
    generate it. Returns (unproducible, reason)."""
    if not contract:
        return False, ""

    shapes = [str(s).lower() for s in (contract.get("evidence_shapes_expected") or [])]
    if not shapes:
        return False, ""

    node_count = _compass_node_count(state)
    total_edges = _compass_total_edges(state)
    edge_counts = _compass_edge_counts(state)

    if node_count == 0:
        return True, "graph contains zero nodes"

    requires_edges = any(s in _SHAPE_REQUIRES_EDGES for s in shapes)
    if requires_edges and total_edges == 0:
        return True, (
            f"contract requires edge-bearing shapes "
            f"({sorted(set(shapes) & _SHAPE_REQUIRES_EDGES)}) but the graph "
            f"contains zero edges"
        )

    requires_paths = any(s in _SHAPE_REQUIRES_PATHS for s in shapes)
    if requires_paths and total_edges == 0:
        return True, "contract requires paths but the graph has no edges"

    # Optional: examine planner_program steps for explicit edge_type targets
    # whose Compass count is zero. This only fires when the Planner asked
    # for a specific edge type (via get_nodes_by_edge_type or find_paths
    # with edge_types) that the Compass reports as absent.
    program = state.get("planner_program") or {}
    declared_types: set[str] = set()
    for step in program.get("steps") or []:
        params = step.get("params") or {}
        et = params.get("edge_type") or params.get("edge_types") or []
        if isinstance(et, str):
            declared_types.add(et.lower())
        elif isinstance(et, list):
            for e in et:
                if isinstance(e, str):
                    declared_types.add(e.lower())
    if declared_types and edge_counts:
        if all(edge_counts.get(t, 0) == 0 for t in declared_types):
            return True, (
                f"planner targeted edge types {sorted(declared_types)} which "
                f"are absent from the graph"
            )

    return False, ""


def _packet_satisfies_contract(packet: dict, contract: dict) -> tuple[bool, list[str]]:
    """Does the packet contain at least one of every shape the contract
    declared? Returns (satisfied, missing_shapes)."""
    if not contract:
        # No contract → packet is sufficient if it has anything at all.
        any_records = (
            bool(packet.get("node_records"))
            or bool(packet.get("edge_records"))
            or bool(packet.get("path_records"))
        )
        return any_records, []

    shapes = [str(s).lower() for s in (contract.get("evidence_shapes_expected") or [])]
    if not shapes:
        any_records = (
            bool(packet.get("node_records"))
            or bool(packet.get("edge_records"))
            or bool(packet.get("path_records"))
        )
        return any_records, []

    inventory = _packet_shape_inventory(packet)
    missing = [s for s in shapes if not inventory.get(s, False)]
    return (not missing), missing


def _extract_recovery(company_verdict: dict) -> tuple[str, dict]:
    """Normalise Company recovery output into (intent_str, spec_dict).

    Runtime shape: ``recovery_intent`` is a dict (the spec itself with a
    ``kind``/``type`` field), and no separate ``recovery_intent_spec``.
    Test shape: ``recovery_intent`` is a bare string and
    ``recovery_intent_spec`` is the dict.
    """
    ri = company_verdict.get("recovery_intent")
    ris = company_verdict.get("recovery_intent_spec") or {}
    if isinstance(ri, dict):
        spec = ri
        intent = str(
            ri.get("kind")
            or ri.get("type")
            or ri.get("intent")
            or ""
        ).lower()
        return intent, spec
    if isinstance(ri, str):
        return ri.lower(), (ris if isinstance(ris, dict) else {})
    return "", (ris if isinstance(ris, dict) else {})


def _company_supports_recovery(
    company_verdict: dict,
    state: EngineState,
) -> tuple[bool, str]:
    """Does Compass contain enough structure to support the recovery the
    Company proposed? Returns (supported, reason)."""
    intent, spec = _extract_recovery(company_verdict)
    if intent in {"", "none"}:
        return False, "no recovery intent declared"

    landmark_ids = _compass_landmark_ids(state)
    edge_counts = _compass_edge_counts(state)

    # Validate target landmarks exist in Compass.
    target_ids = spec.get("target_ids") or spec.get("extend_from") or []
    if isinstance(target_ids, str):
        target_ids = [target_ids]
    if isinstance(target_ids, list) and target_ids:
        if not any(str(t) in landmark_ids for t in target_ids):
            # Not landmarks, but they may still be present in the structural
            # index — accept conservatively.
            structural_index = state.get("structural_index") or {}
            if not any(str(t) in structural_index for t in target_ids):
                return False, (
                    f"recovery targets {target_ids} not present in Compass or index"
                )

    # Validate edge type if declared.
    edge_type = spec.get("edge_type") or spec.get("required_edge_type")
    if isinstance(edge_type, str) and edge_type:
        if edge_counts.get(edge_type.lower(), 0) == 0:
            return False, f"recovery edge_type '{edge_type}' absent from graph"

    return True, f"compass supports {intent} recovery"


def _packet_signature(packet: dict) -> dict:
    """Lightweight (node/edge/path count) signature of the packet.

    Used to detect zero-growth recovery rounds. The packet is append-only,
    so any growth shows up as a strictly larger count.
    """
    return {
        "node_count": len(packet.get("node_records") or []),
        "edge_count": len(packet.get("edge_records") or []),
        "path_count": len(packet.get("path_records") or []),
    }


def _alt_spec_signature(alt_spec: dict) -> str:
    """Canonical digest of an alternative_spec for fixpoint detection.

    Two alt_specs collide iff they would dispatch the same recovery action.
    The signature is deliberately coarse: only the type and the dispatch-
    relevant identifiers matter; reasons and other prose are excluded.
    """
    if not isinstance(alt_spec, dict):
        return ""
    t = str(alt_spec.get("type") or "")
    if t == "entry_point":
        ep = alt_spec.get("entry_point") or {}
        return f"entry_point:{str(ep.get('landmark_id') or '')}"
    if t == "vocabulary_correction":
        vc = alt_spec.get("vocabulary_correction") or {}
        return f"vocab:{str(vc.get('corrected_seed_query') or '')}"
    return t or ""


def _recovery_would_reach_new_territory(
    state: EngineState,
    alt_spec: dict,
) -> tuple[bool, str]:
    """v6 §7 closure: fixpoint termination predicate.

    Recovery may proceed iff (a) the proposed alt_spec is non-null, (b) the
    immediately-prior recovery round (if any) actually grew the packet, and
    (c) this alt_spec has not already been tried this query. The count-based
    "one round" budget that this replaces was an approximation of these
    conditions; the conditions themselves are the closed rule.

    Returns (proceed, reason).
    """
    if not alt_spec or alt_spec.get("type") in (None, "", "null"):
        return False, "no recovery plan"

    # (b) Post-hoc fixpoint: did the previous recovery round add anything?
    pre_sig = state.get("pre_recovery_packet_signature")
    if pre_sig:
        cur_sig = _packet_signature(state.get("evidence_packet") or {})
        if (
            cur_sig["node_count"] == pre_sig.get("node_count", 0)
            and cur_sig["edge_count"] == pre_sig.get("edge_count", 0)
            and cur_sig["path_count"] == pre_sig.get("path_count", 0)
        ):
            return False, "prior recovery round added no evidence (fixpoint reached)"

    # (c) Predictive fixpoint: have we already tried this exact plan?
    sig = _alt_spec_signature(alt_spec)
    if sig:
        prior = list(state.get("recovery_plan_signatures") or [])
        if sig in prior:
            return False, f"recovery plan {sig!r} already attempted"

    return True, "recovery would reach new territory"


def _build_alternative_spec(
    company_verdict: dict,
) -> dict:
    """Translate Company recovery_intent_spec into the AlternativeSpec
    shape that ``backend_execute_recovery`` already understands."""
    intent, spec = _extract_recovery(company_verdict)
    if intent in {"", "none"}:
        return {"type": "null"}

    if intent in {"local_extension", "bridging"}:
        landmark_id = (
            spec.get("landmark_id")
            or (spec.get("target_ids") or [None])[0]
            or (spec.get("extend_from") or [None])[0]
            or ""
        )
        return {
            "type": "entry_point",
            "entry_point": {
                "landmark_id": str(landmark_id) if landmark_id else "",
                "reason": str(spec.get("reason") or f"Company {intent} recovery"),
            },
        }

    if intent == "global_redirect":
        return {
            "type": "vocabulary_correction",
            "vocabulary_correction": {
                "original_concept": str(spec.get("original_concept") or ""),
                "graph_vocabulary": str(spec.get("graph_vocabulary") or ""),
                "evidence": str(spec.get("evidence") or ""),
                "corrected_seed_query": str(spec.get("corrected_seed_query") or ""),
            },
        }

    return {"type": "null"}


# ---------------------------------------------------------------------------
# Verdict reduction
# ---------------------------------------------------------------------------


def compute_verdict_exploratory(state: EngineState) -> dict:
    """v7 §7 reduction for Pipeline C.

    Returns a ``deterministic_verdict`` dict suitable for both stashing
    in state and mirroring into ``confirmation_response``.
    """
    packet = state.get("evidence_packet") or {}
    contract = state.get("answer_contract") or {}
    company_verdict = state.get("company_verdict") or {}
    if not isinstance(company_verdict, dict):
        company_verdict = {}

    # hypothesis_assessment is normally a dict {status, explanation, confidence}
    # but may degrade to a bare string at transition seams.
    ha_raw = company_verdict.get("hypothesis_assessment") or ""
    if isinstance(ha_raw, dict):
        hypothesis = str(ha_raw.get("status") or "").lower()
    else:
        hypothesis = str(ha_raw).lower()
    semantic_validation = state.get("semantic_validation_result") or {}
    semantic_violations = list(semantic_validation.get("violations") or [])

    # --- ILL_POSED check first --------------------------------------------
    unprod, reason = _primitive_shapes_unproducible(contract, state)
    if unprod:
        return {
            "kind": "ILL_POSED",
            "basis": f"contract shapes unproducible: {reason}",
            "terminal": True,
            "recovery_available": False,
            "alternative_spec": {"type": "null"},
            "ill_posed_reason": reason,
        }

    # --- ILL_POSED (vocabulary miss) --------------------------------------
    # Even when the schema *could* produce the shapes, a full hypothesis
    # miss after reseed means the Planner's concept tokens simply aren't
    # in the graph's vocabulary. This is a graph-coverage failure, not a
    # retrieval failure — report it as ILL_POSED so Battalion emits an
    # honest "the graph does not model this" answer instead of a blind
    # EXHAUSTED attempt.
    degradation_flags = [str(f) for f in (state.get("degradation_flags") or [])]
    reseed_attempted = state.get("reseed_attempted") is True or any(
        f == "hypothesis_full_miss_after_reseed" for f in degradation_flags
    )
    has_packet_content_for_ill = (
        bool(packet.get("node_records"))
        or bool(packet.get("edge_records"))
        or bool(packet.get("path_records"))
    )
    if (
        "hypothesis_full_miss" in degradation_flags
        and not has_packet_content_for_ill
        and reseed_attempted
    ):
        # v8 §7: distinguish schema gap (ILL_POSED) from content gap
        # (UNKNOWN_TO_GRAPH). Post-reseed content misses mean the graph's
        # schema *could* answer this class of question but no matching nodes
        # or edges about the topic exist — an authorship gap, not a
        # structural one. Callers consuming the verdict programmatically
        # need this distinction to know whether to change the graph's
        # schema or to add content.
        content_gap_reason = (
            "planner concept tokens absent from graph vocabulary after reseed; "
            "graph schema supports the query but no matching content exists"
        )
        return {
            "kind": "UNKNOWN_TO_GRAPH",
            "basis": f"content gap: {content_gap_reason}",
            "terminal": True,
            "recovery_available": False,
            "alternative_spec": {"type": "null"},
            "ill_posed_reason": content_gap_reason,
        }

    # --- CONFIRMED check --------------------------------------------------
    satisfied, missing_shapes = _packet_satisfies_contract(packet, contract)
    # 'partial' counts as confirmed for verdict purposes — Company already
    # reported it as supporting evidence; gaps surface separately.
    company_says_ok = hypothesis in {"confirmed", "partial"}
    has_packet_content = (
        bool(packet.get("node_records"))
        or bool(packet.get("edge_records"))
        or bool(packet.get("path_records"))
    )
    if satisfied and company_says_ok:
        return {
            "kind": "CONFIRMED",
            "basis": (
                "packet satisfies contract shapes and Company confirms"
                if hypothesis == "confirmed"
                else "packet satisfies contract shapes; Company reports partial confirmation"
            ),
            "terminal": True,
            "recovery_available": False,
            "alternative_spec": {"type": "null"},
        }

    # If the packet has content but Company gave no signal, treat as
    # CONFIRMED-with-low-confidence rather than EXHAUSTED — the v6 failure
    # mode where empty packets and empty Company outputs both produced
    # EXHAUSTED is exactly what the deterministic check is meant to fix.
    if has_packet_content and not contract:
        return {
            "kind": "CONFIRMED",
            "basis": "packet has content; no contract to satisfy",
            "terminal": True,
            "recovery_available": False,
            "alternative_spec": {"type": "null"},
        }

    # --- ALTERNATIVE check ------------------------------------------------
    # v6 closure: termination is fixpoint-based, not count-based. The plan
    # must (i) be supported by Compass and Company, (ii) target territory
    # outside the current packet, and (iii) not duplicate a plan already
    # tried this query. See `_recovery_would_reach_new_territory`.
    fixpoint_reason = ""
    recoverable, why_company = _company_supports_recovery(company_verdict, state)
    if recoverable:
        alt_spec = _build_alternative_spec(company_verdict)
        proceed, why_fix = _recovery_would_reach_new_territory(state, alt_spec)
        if proceed:
            return {
                "kind": "ALTERNATIVE",
                "basis": f"recovery available — {why_company}",
                "terminal": False,
                "recovery_available": True,
                "alternative_spec": alt_spec,
                "missing_shapes": missing_shapes,
            }
        # Fixpoint reached or plan already tried — fall through to EXHAUSTED
        # with the specific termination reason captured in the explanation.
        fixpoint_reason = why_fix

    # --- EXHAUSTED fallback ----------------------------------------------
    explanation_parts: list[str] = []
    if missing_shapes:
        explanation_parts.append(f"missing shapes={missing_shapes}")
    if hypothesis and hypothesis not in {"confirmed", "partial"}:
        explanation_parts.append(f"hypothesis={hypothesis}")
    if not has_packet_content:
        explanation_parts.append("empty packet")
    if semantic_violations:
        explanation_parts.append(f"semantic_violations={len(semantic_violations)}")
    # If we fell through here because recovery was supported but blocked by
    # the fixpoint predicate, surface that reason — it is the canonical v6
    # closure termination cause and downstream observability depends on it.
    if fixpoint_reason:
        explanation_parts.append(f"fixpoint: {fixpoint_reason}")
    explanation = "; ".join(explanation_parts) or "no further recovery path"

    return {
        "kind": "EXHAUSTED",
        "basis": f"no recovery available — {explanation}",
        "terminal": True,
        "recovery_available": False,
        "alternative_spec": {"type": "null"},
        "missing_shapes": missing_shapes,
        "exhaustion_explanation": explanation,
    }


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def verdict_computation_node(state: EngineState) -> dict:
    """Replaces ``planner_confirmation`` for Pipeline C.

    Computes the deterministic verdict and mirrors it into
    ``confirmation_response`` so the existing
    ``route_after_confirmation`` router needs no changes.
    """
    t0 = time.perf_counter()
    verdict = compute_verdict_exploratory(state)

    dialogue_round = int(state.get("dialogue_round") or 0)
    next_round = dialogue_round + 1 if verdict["kind"] == "ALTERNATIVE" else dialogue_round

    # Mirror to the legacy confirmation_response shape so the router and
    # Battalion can continue operating without schema changes.
    confirmation_response = {
        "verdict": verdict["kind"],
        "confirmed_trails": [],
        "confidence_per_trail": {},
        "alternative_spec": verdict.get("alternative_spec", {"type": "null"}),
        "exhaustion_explanation": verdict.get("exhaustion_explanation", verdict.get("basis", "")),
        "ill_posed_reason": verdict.get("ill_posed_reason", "") if verdict["kind"] == "ILL_POSED" else "",
        "planner_mode": state.get("planner_mode", "nominal") or "nominal",
        "compass_confidence": {
            "computed_under": "deterministic_v7",
            "note": verdict.get("basis", ""),
        },
    }

    log_event(
        "verdict_computation",
        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
        verdict=verdict["kind"],
        basis=verdict.get("basis", "")[:200],
        dialogue_round=dialogue_round,
        recovery_available=verdict.get("recovery_available", False),
    )

    print(
        f"\n[Verdict] {verdict['kind']} (deterministic) — "
        f"{verdict.get('basis', '')[:100]}"
    )

    out: dict = {
        "deterministic_verdict": verdict,
        "confirmation_response": confirmation_response,
        "dialogue_round": next_round,
    }
    if verdict["kind"] == "ALTERNATIVE":
        alt = verdict.get("alternative_spec", {"type": "null"})
        out["prev_alternative_spec"] = alt
        # v6 closure: record the plan signature so the predictive fixpoint
        # check in the next reducer pass can refuse to re-issue this plan.
        sig = _alt_spec_signature(alt)
        if sig:
            prior_sigs = list(state.get("recovery_plan_signatures") or [])
            if sig not in prior_sigs:
                prior_sigs.append(sig)
            out["recovery_plan_signatures"] = prior_sigs
    return out
