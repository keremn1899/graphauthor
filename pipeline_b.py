"""v7 Pipeline B — Targeted Retrieval.

Contract-driven backend: the Planner emits a ``RelationalContract`` and
the Backend translates it directly to a deterministic tool dispatch —
no second LLM planning call. The resulting EvidencePacket is handed
straight to Battalion along with a minimal synthetic ``company_handoff``
so Battalion's renderer can treat Pipeline-B evidence the same way it
treats Company-produced trails.

See ``design [new]/graph-traversal-v7.md`` §5 for the spec.

The module exposes two LangGraph-compatible node callables:

- ``pipeline_b_execute(state, conn)``: dispatch + packet build + handoff
- ``pipeline_b_verdict(state)``: deterministic verdict (§7 reduction)
"""

from __future__ import annotations

import re
import time
from typing import Any

import real_ladybug as lb

from backend_tools import build_evidence_packet
from empty_packet_recovery import try_broad_region_recovery
from judgment_view import build_judgment_view, packet_for_judgment
from models import EngineState
from sst_debug import log_event
from retrieval_program import execute_retrieval_program, program_for_targeted_state
from tools import (
    exact_node_lookup,
    lexical_search,
    find_paths,
    get_neighbourhood,
    get_nodes_by_edge_type,
    get_anchor_previews,
    get_node_payloads,
    governing_seed_candidates,
    SST_EDGE_TYPES,
)


_QUESTION_FORMS = frozenset({"proof", "enumeration", "fanout", "lookup", "chain", "count"})

# Content lookup is deliberately much tighter than the general neighbourhood
# tool's 3,000-node safety cap.  These limits apply only to the selected
# CONTAINS branch(es), never to a graph-wide expansion.
_CONTAINS_CONTENT_MAX_DEPTH = 2
_CONTAINS_CONTENT_MAX_NODES = 64


def _planner_exact_lookup_terms(state: EngineState) -> list[str]:
    """Return concrete node references from the Planner's executable steps.

    Targeted retrieval currently carries both ``planner_program`` and
    ``relational_contract``.  Until those become one canonical artifact, do
    not discard exact nodes named by the richer program when the contract has
    fallen back to a broad container such as a document root.
    """
    program = state.get("planner_program") or {}
    terms: list[str] = []
    for step in program.get("steps") or []:
        if not isinstance(step, dict) or step.get("tool") != "exact_node_lookup":
            continue
        params = step.get("params") or {}
        if not isinstance(params, dict):
            continue
        raw_values: list[Any] = []
        for key in ("label_or_id", "ids", "node_ids"):
            value = params.get(key)
            if isinstance(value, list):
                raw_values.extend(value)
            elif value is not None:
                raw_values.append(value)
        for value in raw_values:
            term = str(value or "").strip()
            if term and not term.startswith("$") and term not in terms:
                terms.append(term)
    return terms


def _content_seeking_contains_lookup(state: EngineState, contract: dict) -> bool:
    """Whether this contract needs payload below a hierarchical landmark.

    Enumeration/fanout/count/proof ask structural questions, so their declared
    hop count remains exact.  A lookup over outgoing CONTAINS is different: it
    identifies a scope in which answer-bearing content may live.  Only that
    case receives bounded descendant hydration.
    """
    if contract.get("question_form") != "lookup":
        return False
    if "contains" not in set(contract.get("edge_types") or []):
        return False
    return contract.get("direction") in {"outgoing", "both"}


def _contains_content_descendants(
    conn,
    seed_ids: list[str],
    *,
    max_depth: int = _CONTAINS_CONTENT_MAX_DEPTH,
    max_nodes: int = _CONTAINS_CONTENT_MAX_NODES,
) -> list[dict]:
    """Hydrate a bounded hierarchy below already-selected content scopes.

    This is not generic hop inflation.  It follows only outgoing CONTAINS from
    exact/bounded seeds, preserves the hierarchy edges, and leaves the other
    three SST relations untouched.
    """
    unique_seeds = list(dict.fromkeys(str(x) for x in seed_ids if str(x)))
    if not unique_seeds:
        return []
    return get_neighbourhood(
        conn,
        node_ids=unique_seeds,
        depth=max_depth,
        edge_types=["contains"],
        direction="outgoing",
        max_nodes=max_nodes,
    )


def _substantive_preview(text: str) -> bool:
    """Conservative payload check that does not depend on domain node kinds."""
    useful_lines: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("source:"):
            continue
        useful_lines.append(stripped)
    useful = " ".join(useful_lines)
    return len(useful) >= 48 or len(useful.split()) >= 9


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


def _asserts_actual_absence(reasoning: str) -> bool:
    """Return whether Planner prose makes a present-tense absence claim.

    Strategy-B reasoning commonly explains a diagnostic in counterfactual
    terms (``if X is missing...`` or ``absence would imply...``).  Those are
    search instructions, not observations about the graph.  Only
    non-conditional sentences with explicit absence language qualify.
    """
    sentences = re.split(r"(?<=[.!?])\s+|\n+", str(reasoning or "").lower())
    assertion_patterns = (
        r"\bis (?:absent|missing)\b",
        r"\bis not (?:present|found|represented|in (?:this |the )?graph)\b",
        r"\bnot (?:present|found|represented|in (?:this |the )?graph)\b",
        r"\bdoes not (?:exist|appear|occur|contain|cover)\b",
        r"\babsence (?:confirms|indicates|shows)\b",
    )
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        # Modal and if-conditional statements describe possible evidence, not
        # evidence that retrieval actually observed.
        if re.search(r"\bif\b", sentence):
            continue
        if re.search(r"\b(?:would|could|should|might|may)\b", sentence):
            continue
        if any(re.search(pattern, sentence) for pattern in assertion_patterns):
            return True
    return False


def _concept_exists(conn, concept: str, packet: dict) -> bool:
    """Check exact graph/packet identity before accepting a missing gap."""
    needle = str(concept or "").strip().lower()
    if not needle:
        return False
    for node in packet.get("node_records") or []:
        if needle in {
            str(node.get("id") or "").strip().lower(),
            str(node.get("label") or "").strip().lower(),
        }:
            return True
    for candidate in (concept, str(concept).title()):
        try:
            if exact_node_lookup(conn, candidate):
                return True
        except Exception:
            continue
    return False


def _normalise_contract(contract: dict | None) -> dict:
    """Coerce the RelationalContract dict with defaults matching models.py."""
    c = dict(contract or {})
    qf = str(c.get("question_form") or "lookup").strip().lower()
    if qf not in _QUESTION_FORMS:
        qf = "lookup"
    direction = str(c.get("direction") or "outgoing").strip().lower()
    if direction not in {"outgoing", "incoming", "both"}:
        direction = "outgoing"
    edge_types = [
        str(e).strip().lower() for e in (c.get("edge_types") or []) if str(e).strip()
    ]
    # Preserve chain steps if present; each step keeps edge_types, edge_labels, direction, max_hops.
    raw_steps = c.get("steps")
    steps: list[dict] = []
    if isinstance(raw_steps, list):
        for s in raw_steps:
            if not isinstance(s, dict):
                continue
            et = [str(e).strip().lower() for e in (s.get("edge_types") or []) if str(e).strip()]
            # Only preserve edge_labels for CONTAINS steps; EXPRESSES/LEADSTO/NEARTO
            # don't use meaningful sub-labels and wrong labels silently break traversal.
            el = (
                [str(lbl).strip() for lbl in (s.get("edge_labels") or []) if str(lbl).strip()]
                if "contains" in et
                else []
            )
            sd = str(s.get("direction") or "outgoing").strip().lower()
            if sd not in ("outgoing", "incoming", "both"):
                sd = "outgoing"
            try:
                mh = max(1, min(int(s.get("max_hops", 1)), 4))
            except (TypeError, ValueError):
                mh = 1
            steps.append({"edge_types": et, "edge_labels": el, "direction": sd, "max_hops": mh})

    return {
        "question_form": qf,
        "source_ids": [str(s) for s in (c.get("source_ids") or []) if str(s).strip()],
        "edge_types": edge_types,
        "direction": direction,
        "target_ids": [str(s) for s in (c.get("target_ids") or []) if str(s).strip()],
        "max_hops": int(c.get("max_hops") or 1),
        "expected_result_shape": str(c.get("expected_result_shape") or "edge_pairs"),
        "steps": steps,
        "answer_type_hint": str(c.get("answer_type_hint") or "").strip().lower(),
        "requires_content_arithmetic": bool(c.get("requires_content_arithmetic")),
        "exact_only": bool(c.get("exact_only")),
    }


def _trail_from_edge(edge: dict, trail_id: str, rationale: str) -> dict:
    """Render a single SST edge as a 2-node trail for Battalion."""
    return {
        "trail_id": trail_id,
        "origin": "pipeline_b",
        "rationale": rationale,
        "node_ids": [edge.get("source_id", ""), edge.get("target_id", "")],
        "edge_types": [edge.get("edge_type", "")],
        "edge_labels": [edge.get("edge_label", "")],
    }


def _trail_from_path(path: dict, trail_id: str, rationale: str) -> dict:
    """Render a find_paths result as a trail."""
    return {
        "trail_id": trail_id,
        "origin": "pipeline_b",
        "rationale": rationale,
        "node_ids": list(path.get("node_chain") or []),
        "edge_types": list(path.get("edge_chain") or []),
        "edge_labels": list(path.get("edge_label_chain") or []),
    }


def _dispatch_proof(conn, contract: dict) -> dict[str, list]:
    paths = find_paths(
        conn,
        source_set=_resolve_ids(conn, contract["source_ids"]),
        target_set=_resolve_ids(conn, contract["target_ids"]),
        max_hops=max(1, contract["max_hops"]),
        edge_types=contract["edge_types"] or None,
    )
    # build_evidence_packet keys path records off ``path_chain``; find_paths
    # emits the equivalent under ``node_chain``. Mirror the key so the packet
    # builder picks them up as paths (with auto-derived edges) rather than
    # dropping them as unstructured dicts.
    normalised: list[dict] = []
    for p in paths or []:
        if not isinstance(p, dict):
            continue
        q = dict(p)
        if "path_chain" not in q and isinstance(q.get("node_chain"), list):
            q["path_chain"] = list(q["node_chain"])
        normalised.append(q)
    return {"paths_primary": normalised}


def _dispatch_enumeration(conn, contract: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    edge_types = contract["edge_types"] or list(SST_EDGE_TYPES)
    for i, et in enumerate(edge_types):
        result = get_nodes_by_edge_type(conn, et)
        node_records = result.get("node_records") or []
        edge_records = result.get("edge_records") or []

        # Filter by source/target constraints if declared.
        src_filter = set(contract["source_ids"]) if contract["source_ids"] else None
        tgt_filter = set(contract["target_ids"]) if contract["target_ids"] else None

        if src_filter or tgt_filter:
            edge_records = [
                e for e in edge_records
                if (not src_filter or e.get("source_id") in src_filter)
                and (not tgt_filter or e.get("target_id") in tgt_filter)
            ]
            keep_ids: set[str] = set()
            for e in edge_records:
                keep_ids.add(e.get("source_id", ""))
                keep_ids.add(e.get("target_id", ""))
            node_records = [n for n in node_records if n.get("id") in keep_ids]

        # Transport shape — first node carries the edge records.
        if node_records:
            node_records[0] = {**node_records[0], "_edge_records": edge_records}
        elif edge_records:
            node_records = [{
                "id": edge_records[0].get("source_id", ""),
                "label": edge_records[0].get("source_label", ""),
                "_edge_records": edge_records,
            }]
        out[f"enumeration_{i}_{et}"] = node_records
    return out


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _resolve_ids(conn, raw_ids: list[str]) -> list[str]:
    """Resolve entity-name strings to real node IDs.

    The Planner emits human-readable labels (e.g. "Brendan Gleeson") into
    source_ids/target_ids. get_neighbourhood and find_paths expect opaque
    graph IDs (e.g. "mqa_<sha1>"). Resolution order:
      1. exact_node_lookup — exact ID or exact label match (raw)
      2. exact_node_lookup — title-cased variant (catches lowercase queries like MetaQA)
      2.5. case-insensitive exact label
      2.55. CamelCase → snake_case node id (software corpus)
      2.6. label prefix — "OrderService" → "OrderService (use-case core)"
      3. lexical_search — title-cased full string, take the top hit
      4. lexical_search — token-split (each word as a term), take the top hit
    Real IDs pass through unchanged at step 1.
    """
    resolved: list[str] = []
    for raw in raw_ids:
        # Step 1: exact match (original casing)
        hit = exact_node_lookup(conn, raw)
        if hit:
            resolved.append(hit["id"])
            continue

        # Step 2: title-case variant — handles "william atherton" → "William Atherton".
        # KuzuDB exact match is case-sensitive, so try title-cased form.
        titled = raw.title()
        if titled != raw:
            hit = exact_node_lookup(conn, titled)
            if hit:
                resolved.append(hit["id"])
                continue

        # Step 2.5: case-insensitive label match via lower() — handles multi-word
        # titles like "written on the wind" where .title() over-capitalises stop words
        # ("Written On The Wind" ≠ "Written on the Wind").
        try:
            rows = list(conn.execute(
                "MATCH (c:Concept) WHERE lower(c.label) = $val "
                "RETURN c.id, c.label, c.centrality_score LIMIT 1",
                {"val": raw.lower()},
            ))
            if rows:
                resolved.append(rows[0][0])
                continue
        except Exception:
            pass

        # Step 2.55: CamelCase planner token → snake_case graph id.
        if raw and raw[0].isupper() and " " not in raw:
            hit = exact_node_lookup(conn, _camel_to_snake(raw))
            if hit:
                resolved.append(hit["id"])
                continue

        # Step 2.6: label prefix — disambiguates "OrderService" from neighbours
        # that merely mention it in text_content (lexical_search tie-break failure).
        try:
            rows = list(conn.execute(
                "MATCH (c:Concept) "
                "WHERE lower(c.label) STARTS WITH $prefix "
                "RETURN c.id, c.label "
                "ORDER BY length(c.label) ASC LIMIT 1",
                {"prefix": raw.lower() + " ("},
            ))
            if rows:
                resolved.append(rows[0][0])
                continue
        except Exception:
            pass

        # Step 3: lexical search on the title-cased full name
        results = lexical_search(conn, terms=[titled if titled != raw else raw], k=1)
        if results:
            resolved.append(results[0]["id"])
            continue

        # Step 4: token-split — try each word as a separate term so partial names
        # like "Alex Gordon" can match "Aleksandr Gordon" via shared tokens.
        tokens = [t for t in raw.split() if len(t) > 2]
        if len(tokens) >= 2:
            titled_tokens = [t.title() for t in tokens]
            results = lexical_search(conn, terms=titled_tokens, k=3)
            if results:
                resolved.append(results[0]["id"])
                continue

        resolved.append(raw)  # unresolved — will silently return no edges
    return resolved


def _dispatch_fanout(conn, contract: dict) -> dict[str, list]:
    depth = max(1, contract["max_hops"])
    resolved_ids = _resolve_ids(conn, contract["source_ids"])
    result = get_neighbourhood(
        conn,
        node_ids=resolved_ids,
        depth=depth,
        edge_types=contract["edge_types"] or None,
        direction=contract["direction"],
    )
    # v9: Planner sometimes inverts direction (e.g. emits 'incoming' for
    # "What does X contain?"). If the declared direction yields no edges
    # and the contract doesn't hard-require it, retry with 'both' so the
    # packet is actually populated.
    def _edge_count(nodes: list[dict]) -> int:
        total = 0
        for n in nodes or []:
            total += len(n.get("_edge_records") or [])
        return total

    if _edge_count(result) == 0 and contract["direction"] != "both":
        retry = get_neighbourhood(
            conn,
            node_ids=resolved_ids,
            depth=depth,
            edge_types=contract["edge_types"] or None,
            direction="both",
        )
        if _edge_count(retry) > 0:
            result = retry
    return {"fanout_primary": result}


def _dispatch_chain(conn, contract: dict) -> dict[str, list]:
    """Execute a multi-hop chain: step N output node IDs feed step N+1 seeds.

    Each step specifies edge_types, direction, and max_hops. The final step's
    nodes are the primary answer set; intermediate nodes are preserved as
    supporting context. All edges from all steps are included in the packet.
    """
    steps = contract.get("steps") or []
    if not steps:
        # Degrade gracefully to single-hop fanout if steps omitted.
        return _dispatch_fanout(conn, contract)

    current_seeds = _resolve_ids(conn, contract["source_ids"])
    if not current_seeds:
        return {"chain_primary": [], "_chain_intermediate_found": False}

    all_results: list[list[dict]] = []
    for i, step in enumerate(steps):
        step_edge_types = [str(e).lower() for e in (step.get("edge_types") or [])] or None
        step_edge_labels = [str(l) for l in (step.get("edge_labels") or [])] or None
        step_direction = str(step.get("direction") or "outgoing")
        if step_direction not in ("outgoing", "incoming", "both"):
            step_direction = "outgoing"
        step_depth = max(1, min(int(step.get("max_hops") or 1), 4))

        result = get_neighbourhood(
            conn,
            node_ids=current_seeds,
            depth=step_depth,
            edge_types=step_edge_types,
            direction=step_direction,
            edge_labels=step_edge_labels,
        )
        # Direction fallback: if no edges returned, retry with 'both'.
        def _edge_count(nodes: list[dict]) -> int:
            return sum(len(n.get("_edge_records") or []) for n in (nodes or []))

        if _edge_count(result) == 0 and step_direction != "both":
            retry = get_neighbourhood(
                conn,
                node_ids=current_seeds,
                depth=step_depth,
                edge_types=step_edge_types,
                direction="both",
                edge_labels=step_edge_labels,
            )
            if _edge_count(retry) > 0:
                result = retry

        # Edge-label fallback: if still no edges and edge_labels were set,
        # retry without the label filter. Handles cases where the Planner
        # guessed a label that doesn't exist in this graph (e.g. "language"
        # when the DB uses "in_language", or "genre" vs "has_genre").
        if _edge_count(result) == 0 and step_edge_labels:
            retry = get_neighbourhood(
                conn,
                node_ids=current_seeds,
                depth=step_depth,
                edge_types=step_edge_types,
                direction="both",
                edge_labels=None,
            )
            if _edge_count(retry) > 0:
                result = retry

        all_results.append(result)
        # Feed this step's discovered node IDs as seeds for the next step.
        current_seeds = [n["id"] for n in result if n.get("id")]
        if not current_seeds:
            break

    if not all_results:
        return {
            "chain_primary": [],
            "_chain_terminal_empty": True,
            "_chain_intermediate_found": False,
        }

    # Track whether the final step in the chain returned any nodes.
    # If it did not, the chain resolved an intermediate entity but not the
    # terminal property — the answer is structurally absent regardless of
    # whether intermediate nodes were found.
    chain_terminal_empty = not bool(current_seeds)
    chain_intermediate_found = any(step for step in all_results if step)

    # Self-extension (Hypothesis A): if the contract declares answer_type_hint,
    # the Planner expects a typed property as the final answer (year, country,
    # genre, etc.). Check whether the terminal nodes already ground that hint.
    # If not, issue one more EXPRESSES outgoing hop from the terminal seeds to
    # surface property nodes that the Planner's step list may have omitted.
    answer_type_hint = str(contract.get("answer_type_hint") or "").strip().lower()
    if answer_type_hint and current_seeds and all_results:
        terminal_text = " ".join(
            (n.get("label", "") + " " + n.get("semantic_anchor", "")).lower()
            for n in all_results[-1] if isinstance(n, dict)
        )
        if answer_type_hint not in terminal_text:
            extension = get_neighbourhood(
                conn,
                node_ids=current_seeds,
                depth=1,
                edge_types=["expresses"],
                direction="outgoing",
            )
            if extension:
                all_results.append(extension)

    # Final step nodes are the primary answer; earlier steps are supporting.
    # Merge edge_records from all steps onto the first node of the merged list.
    merged_edges: list[dict] = []
    seen_edge_keys: set[tuple] = set()
    for step_nodes in all_results:
        for node in step_nodes:
            for edge in (node.pop("_edge_records", None) or []):
                key = (edge.get("source_id"), edge.get("target_id"),
                       edge.get("edge_type"), edge.get("edge_label"))
                if key not in seen_edge_keys:
                    seen_edge_keys.add(key)
                    merged_edges.append(edge)

    # Flatten all nodes, deduplicated.
    seen_ids: set[str] = set()
    flat_nodes: list[dict] = []
    for step_nodes in all_results:
        for node in step_nodes:
            if node.get("id") and node["id"] not in seen_ids:
                seen_ids.add(node["id"])
                flat_nodes.append(node)

    if flat_nodes and merged_edges:
        flat_nodes[0] = dict(flat_nodes[0])
        flat_nodes[0]["_edge_records"] = merged_edges

    result: dict = {
        "chain_primary": flat_nodes,
        "_chain_intermediate_found": chain_intermediate_found,
    }
    if chain_terminal_empty:
        result["_chain_terminal_empty"] = True
    return result


def _dispatch_lookup(conn, contract: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    nodes: list[dict] = []
    resolved_ids = _resolve_ids(conn, contract["source_ids"])
    for rid in resolved_ids:
        hit = exact_node_lookup(conn, rid)
        if hit and hit.get("id"):
            nodes.append({"id": hit["id"], "label": hit.get("label", "")})
    # Also fetch the surrounding neighbourhood to populate edges.
    neighbourhood = get_neighbourhood(
        conn,
        node_ids=[n["id"] for n in nodes],
        depth=1,
        edge_types=None,
        direction="both",
    )
    out["lookup_primary"] = nodes
    out["lookup_neighbourhood"] = neighbourhood
    return out


def _dispatch_contract(conn, contract: dict) -> dict[str, list]:
    """Dispatch the RelationalContract to its deterministic tool call(s)."""
    qf = contract["question_form"]
    if qf == "proof":
        return _dispatch_proof(conn, contract)
    if qf == "enumeration":
        # v9: enumeration with a named source is semantically a fanout
        # ("what does X contain?" = neighbourhood of X over [contains]).
        # Global enumeration (no source_ids) keeps the old path.
        if contract.get("source_ids"):
            return _dispatch_fanout(conn, contract)
        return _dispatch_enumeration(conn, contract)
    if qf == "fanout":
        return _dispatch_fanout(conn, contract)
    if qf == "chain":
        return _dispatch_chain(conn, contract)
    if qf == "count":
        # Count runs the same traversal as fanout then tags the result for
        # aggregation. _dispatch_fanout returns edges; we annotate the contract
        # with the count metadata so Battalion can render a graph statement.
        return _dispatch_fanout(conn, contract)
    return _dispatch_lookup(conn, contract)


def _governance_rule_closure(
    conn,
    variables: dict[str, list],
    *,
    source_ids: list[str] | None = None,
) -> list[dict]:
    """Lift rules that adjudicate subjects already reached by Pipeline B.

    Construction represents a rule as ``rule -[:EXPRESSES]-> subject``. A
    coverage lookup commonly reaches ``context -[:NEARTO]-> subject`` in its
    first hop and used to stop there, leaving Battalion with applicability
    context but no authoritative rule.

    Software architecture graphs also use a second, equally explicit shape:
    ``component -[:NEARTO]-> boundary -[:CONTAINS]-> decision``. Close that
    path only when the contained decision carries authoritative governing
    metadata. This admits a boundary constraint while excluding navigation,
    interpretations, and rejected/superseded context. Both closures are
    bounded typed traversals from evidence the targeted retrieval already
    named; query-wide governing priors are deliberately not expansion seeds.
    """

    seed_ids: list[str] = []
    seen: set[str] = set()
    for node_id in source_ids or []:
        node_id = str(node_id or "").strip()
        if node_id and node_id not in seen:
            seen.add(node_id)
            seed_ids.append(node_id)
    for value in variables.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id") or "").strip()
            if node_id and node_id not in seen:
                seen.add(node_id)
                seed_ids.append(node_id)
    if not seed_ids:
        return []
    expressed_rules = get_neighbourhood(
        conn,
        node_ids=seed_ids,
        depth=1,
        edge_types=["expresses"],
        direction="incoming",
    )

    # The architectural-boundary shape is intentionally exactly two typed
    # hops. A generic depth=2 expansion would also admit unrelated descendants
    # through LEADSTO/CONTAINS and recreate the noise this closure is fixing.
    nearby_scopes = get_neighbourhood(
        conn,
        node_ids=seed_ids,
        depth=1,
        edge_types=["nearto"],
        direction="both",
        max_nodes=32,
    )
    scope_nodes = {
        str(item.get("id")): item
        for item in nearby_scopes
        if isinstance(item, dict) and item.get("id")
    }
    # When both endpoints were already retrieval seeds, get_neighbourhood
    # carries the edge but correctly omits the endpoint from its "discovered"
    # list. Recover both endpoint identities from that canonical transport.
    for item in nearby_scopes:
        if not isinstance(item, dict):
            continue
        for edge in item.get("_edge_records") or []:
            if not isinstance(edge, dict):
                continue
            for id_key, label_key in (
                ("source_id", "source_label"),
                ("target_id", "target_label"),
            ):
                node_id = str(edge.get(id_key) or "")
                if node_id:
                    scope_nodes.setdefault(
                        node_id,
                        {"id": node_id, "label": edge.get(label_key, "")},
                    )
    if not scope_nodes:
        return expressed_rules

    contained = get_neighbourhood(
        conn,
        node_ids=list(scope_nodes),
        depth=1,
        edge_types=["contains"],
        direction="outgoing",
        max_nodes=128,
    )
    child_nodes = {
        str(item.get("id")): item
        for item in contained
        if isinstance(item, dict) and item.get("id")
    }
    if not child_nodes:
        return expressed_rules

    import normative

    payloads = get_node_payloads(conn, list(child_nodes))
    governing_ids = {
        node_id
        for node_id, payload in payloads.items()
        if (claim := normative.classify(payload)).is_governing
        and claim.grants_authority
    }
    if not governing_ids:
        return expressed_rules

    def transport_edges(records: list[dict]) -> list[dict]:
        edges: list[dict] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            for edge in record.get("_edge_records") or []:
                if not isinstance(edge, dict):
                    continue
                key = (
                    str(edge.get("source_id") or ""),
                    str(edge.get("target_id") or ""),
                    str(edge.get("edge_type") or ""),
                    str(edge.get("edge_label") or ""),
                )
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append(dict(edge))
        return edges

    contains_edges = [
        edge
        for edge in transport_edges(contained)
        if str(edge.get("source_id") or "") in scope_nodes
        and str(edge.get("target_id") or "") in governing_ids
        and str(edge.get("edge_type") or "").lower() == "contains"
    ]
    governing_scopes = {
        str(edge.get("source_id") or "") for edge in contains_edges
    }
    if not governing_scopes:
        return expressed_rules
    near_edges = [
        edge
        for edge in transport_edges(nearby_scopes)
        if str(edge.get("edge_type") or "").lower() == "nearto"
        and (
            str(edge.get("source_id") or "") in governing_scopes
            or str(edge.get("target_id") or "") in governing_scopes
        )
    ]

    boundary_nodes = [
        {"id": node_id, "label": scope_nodes[node_id].get("label", "")}
        for node_id in sorted(governing_scopes)
    ]
    boundary_nodes.extend(
        {"id": node_id, "label": child_nodes[node_id].get("label", "")}
        for node_id in sorted(governing_ids)
        if any(str(edge.get("target_id") or "") == node_id for edge in contains_edges)
    )
    if boundary_nodes:
        boundary_nodes[0]["_edge_records"] = near_edges + contains_edges
    return expressed_rules + boundary_nodes


def _declared_semantic_targets(
    conn,
    state: EngineState,
    contract: dict,
) -> list[dict]:
    """Preserve exact answer entities the Planner named beside its contract.

    Pipeline B executes only ``relational_contract`` and historically discarded
    the Planner program's direct ``get_anchor_previews`` target. On a wide
    hierarchy, a correct exact target could therefore be drowned in a root
    traversal packet even though the same Planner explicitly named it.

    Semantic lookups receive the Planner's declared entity terms.  Content
    lookups over CONTAINS also preserve concrete ``exact_node_lookup`` steps:
    those are frequently the precise section/scope IDs which a coarser
    relational contract has collapsed to a document root.  This preserves
    evidence, not a verdict.
    """

    program = state.get("planner_program") or {}
    answer_contract = (
        state.get("answer_contract")
        or program.get("answer_contract")
        or {}
    )
    query_class = str(answer_contract.get("query_class") or "")
    exact_terms = _planner_exact_lookup_terms(state)
    is_semantic_lookup = query_class == "semantic_lookup"
    is_contains_content = _content_seeking_contains_lookup(state, contract)
    if not is_semantic_lookup and not (is_contains_content and exact_terms):
        return []
    entity_intent = program.get("entity_intent") or {}
    raw = list(contract.get("target_ids") or [])
    if is_semantic_lookup:
        raw.extend(entity_intent.get("target_terms") or [])
    if is_contains_content:
        raw.extend(exact_terms)
    resolved = _resolve_ids(conn, list(dict.fromkeys(str(item) for item in raw if item)))
    nodes: list[dict] = []
    seen: set[str] = set()
    for node_id in resolved:
        hit = exact_node_lookup(conn, node_id)
        if not hit or not hit.get("id") or hit["id"] in seen:
            continue
        seen.add(hit["id"])
        nodes.append({"id": hit["id"], "label": hit.get("label", "")})
    return nodes


def _synth_program_from_contract(contract: dict, variables: dict[str, list]) -> dict:
    """Build a minimal ``program`` dict so ``build_evidence_packet`` can assign
    origin tags to each variable."""
    steps: list[dict] = []
    qf = contract["question_form"]

    if variables.get("declared_targets"):
        steps.append({"tool": "exact_node_lookup", "assign_to": "declared_targets"})
    if variables.get("contains_content"):
        steps.append({
            "tool": "get_neighbourhood",
            "assign_to": "contains_content",
            "params": {
                "edge_types": ["contains"],
                "direction": "outgoing",
                "depth": _CONTAINS_CONTENT_MAX_DEPTH,
            },
        })
    if qf == "proof":
        steps.append({"tool": "find_paths", "assign_to": "paths_primary"})
    elif qf == "enumeration":
        for key in variables:
            et = key.rsplit("_", 1)[-1] if "_" in key else ""
            steps.append({"tool": "get_nodes_by_edge_type", "assign_to": key, "params": {"edge_type": et}})
    elif qf in ("fanout", "count"):
        steps.append({"tool": "get_neighbourhood", "assign_to": "fanout_primary"})
    elif qf == "chain":
        steps.append({"tool": "get_neighbourhood", "assign_to": "chain_primary"})
    else:  # lookup
        steps.append({"tool": "exact_node_lookup", "assign_to": "lookup_primary"})
        steps.append({"tool": "get_neighbourhood", "assign_to": "lookup_neighbourhood"})

    return {
        "strategy_a": {"concepts": contract["source_ids"]},
        "strategy_b": {"concepts": contract["target_ids"]},
        "structural_intent": "null",
        "steps": steps,
        "collect": "",
        "contingency": {},
    }


def _chain_truncation_gap(
    contract: dict,
    chain_terminal_empty: bool,
    chain_intermediate_found: bool,
) -> dict | None:
    """The gap for a chain that started, walked, and stopped short.

    Pipeline B already detects this to decide the verdict — an intermediate
    entity was reached and the next hop returned nothing — and then discarded
    the finding. `chain_truncated` translates to `coverage_shallow` on the wire,
    which is the honest description: we reached less than the question needed.

    Until this existed, `chain_truncated` could only arise by *correcting* a
    `coverage_shallow` the Company LLM had already guessed at, so a chain
    question that produced no LLM gap produced no gap at all.
    """
    if contract.get("question_form") != "chain":
        return None
    if not (chain_terminal_empty and chain_intermediate_found):
        return None
    stopped_at = (
        (contract.get("target_ids") or [None])[0]
        or (contract.get("source_ids") or [None])[0]
        or "the requested chain"
    )
    return {
        "gap_type": "chain_truncated",
        "specific_node_or_concept": str(stopped_at),
        "actionable_suggestion": (
            "The chain was followed from the named source and the next hop "
            "returned nothing — intermediate steps exist but the graph does "
            "not carry the rest of the path. Author the missing links, or "
            "confirm the chain ends where it does."
        ),
    }


def _build_company_handoff(
    packet: dict,
    contract: dict,
    hypothesis_status: str,
    confidence: str,
    gaps: list,
) -> dict:
    """Construct a minimal company_handoff so Battalion can render Pipeline B
    evidence through its existing trail/payload pathway.

    Each edge becomes a 2-node trail; each path becomes an N-node trail.
    Orphan nodes (present in packet but not in any edge or path) are recorded
    as context trails so the Battalion prompt still sees their payloads.
    """
    primary: list[dict] = []
    supporting: list[dict] = []
    context: list[dict] = []

    qf = contract["question_form"]

    # Paths → primary trails.
    for idx, path in enumerate(packet.get("path_records") or []):
        primary.append(_trail_from_path(
            path,
            trail_id=f"pb_path_{idx}",
            rationale=f"Pipeline B — {qf}",
        ))

    # Edges → primary (or supporting, when paths also exist).
    edge_target = supporting if primary else primary
    for idx, edge in enumerate(packet.get("edge_records") or []):
        edge_target.append(_trail_from_edge(
            edge,
            trail_id=f"pb_edge_{idx}",
            rationale=f"Pipeline B — {qf} ({edge.get('edge_type', '')})",
        ))

    # Orphan nodes → context trails.
    claimed_ids: set[str] = set()
    for t in (*primary, *supporting):
        claimed_ids.update(t.get("node_ids", []))
    orphan_nodes = [
        n for n in (packet.get("node_records") or [])
        if n.get("id") and n.get("id") not in claimed_ids
    ]
    for idx, n in enumerate(orphan_nodes):
        context.append({
            "trail_id": f"pb_node_{idx}",
            "origin": "pipeline_b",
            "rationale": f"Pipeline B — {qf} (solo node)",
            "node_ids": [n.get("id", "")],
            "edge_types": [],
            "edge_labels": [],
        })

    # For count queries: compute the edge count and surface it explicitly so
    # Battalion can render a graph-statement answer with provenance.
    count_result: dict | None = None
    if qf == "count":
        edge_count = len(packet.get("edge_records") or [])
        source_label = (
            (packet.get("node_records") or [{}])[0].get("label", "")
            if packet.get("node_records") else ""
        )
        edge_types = contract.get("edge_types") or []
        edge_label = contract.get("edge_labels") or edge_types
        count_result = {
            "count": edge_count,
            "source_label": source_label,
            "edge_types": edge_types,
            "provenance_edge_ids": [
                e.get("id") or f"pb_edge_{i}"
                for i, e in enumerate(packet.get("edge_records") or [])
            ],
        }

    internal = {
        "hypothesis_status": hypothesis_status,
        "confidence": confidence,
        "primary_trails": primary,
        "supporting_trails": supporting,
        "context_trails": context,
        "gaps": gaps,
        **({"count_result": count_result} if count_result is not None else {}),
    }
    summary = (
        f"Pipeline B — count: graph contains {count_result['count']} edge(s) "
        f"of type {count_result['edge_types']} from {count_result['source_label']!r}"
        if count_result is not None
        else (
            f"Pipeline B — {qf}: "
            f"{len(primary)} primary trail(s), "
            f"{len(supporting)} supporting, "
            f"{len(context)} context"
        )
    )
    return {
        "internal_handoff": internal,
        "evidence_brief": {
            "primary_summary": summary,
            "recovery_memo": "",
        },
    }


def _compass_edge_type_populations(state: EngineState) -> dict[str, int]:
    compass = state.get("compass") or {}
    gp = compass.get("graph_profile") or {}
    edges = gp.get("edge_counts") or {}
    return {str(k).lower(): int(v) for k, v in edges.items() if isinstance(v, int)}


def compute_verdict_pipeline_b(
    state: EngineState,
    chain_terminal_empty: bool = False,
    chain_intermediate_found: bool = False,
) -> dict:
    """v7 §7 reduction for Pipeline B.

    Returns the deterministic verdict dict that can be stashed under
    ``deterministic_verdict`` and mirrored into ``confirmation_response``
    so Battalion's existing branches handle it without further change.
    """
    packet = state.get("evidence_packet") or {}
    contract = state.get("relational_contract") or {}
    edge_types = [str(e).lower() for e in (contract.get("edge_types") or [])]

    has_edges = bool(packet.get("edge_records"))
    has_paths = bool(packet.get("path_records"))
    has_nodes = bool(packet.get("node_records"))
    packet_empty = not (has_nodes or has_edges or has_paths)
    assessment = packet.get("retrieval_assessment") or {}
    content_status = str(assessment.get("content_status") or "not_required")
    retrieval_status = {
        "content_retrieved": "CONTENT_RETRIEVED",
        "partial": "PARTIAL",
        "unresolved": "NO_CONTENT",
        "not_required": "STRUCTURAL_ONLY",
    }.get(content_status, "UNKNOWN")

    # Identity hits for the two endpoints are context, not a relation proof.
    # The canonical program deliberately collects them for provenance, so a
    # missing path no longer produces a literally empty packet. Proof success
    # must therefore be keyed to the answer-bearing path shape itself.
    if contract.get("question_form") == "proof" and not has_paths:
        populations = _compass_edge_type_populations(state)
        if edge_types and all(populations.get(et, 0) == 0 for et in edge_types):
            return {
                "kind": "ILL_POSED",
                "retrieval_status": "INSUFFICIENT",
                "basis": (
                    f"relational contract declares edge types {edge_types} "
                    "which are absent from the graph"
                ),
                "terminal": True,
                "recovery_available": False,
            }
        return {
            "kind": "EXHAUSTED",
            "retrieval_status": "INSUFFICIENT",
            "basis": "no typed path connects the declared proof endpoints",
            "terminal": True,
            "recovery_available": False,
        }

    # Multi-hop chain where the final step returned no nodes: intermediate entity
    # was found but the terminal property is structurally absent. Returning CONFIRMED
    # here would let Battalion synthesise from hop-N-1 evidence and produce a wrong
    # answer (verdict_synthesis_drift). EXHAUSTED is the correct honest signal.
    if (
        chain_terminal_empty
        and chain_intermediate_found
        and contract.get("question_form") == "chain"
    ):
        return {
            "kind": "EXHAUSTED",
            "retrieval_status": "INSUFFICIENT",
            "basis": (
                "multi-hop chain: intermediate entity found but terminal property "
                "absent from graph structure — answer cannot be grounded"
            ),
            "terminal": True,
            "recovery_available": False,
        }

    if packet_empty:
        # ILL_POSED when the declared edge type does not exist in the graph
        # at all; EXHAUSTED otherwise (retrieval failed on a populated graph).
        populations = _compass_edge_type_populations(state)
        if edge_types and all(populations.get(et, 0) == 0 for et in edge_types):
            return {
                "kind": "ILL_POSED",
                "retrieval_status": "INSUFFICIENT",
                "basis": (
                    f"relational contract declares edge types "
                    f"{edge_types} which are absent from the graph"
                ),
                "terminal": True,
                "recovery_available": False,
            }
        return {
            "kind": "EXHAUSTED",
            "retrieval_status": "INSUFFICIENT",
            "basis": "contract-driven retrieval returned an empty packet",
            "terminal": True,
            "recovery_available": False,
        }

    # Check coverage per source_id when applicable.
    source_ids = [str(s) for s in (contract.get("source_ids") or [])]
    coverage_sources = contract.get("coverage_sources") or [
        {"id": source_id, "display": source_id} for source_id in source_ids
    ]
    missing_sources: list[str] = []
    relation_coverage_forms = {"fanout", "enumeration", "count", "chain"}
    if (
        coverage_sources
        and has_edges
        and contract.get("question_form") in relation_coverage_forms
    ):
        covered = {str(e.get("source_id", "")) for e in (packet.get("edge_records") or [])}
        covered |= {str(e.get("target_id", "")) for e in (packet.get("edge_records") or [])}
        missing_sources = [
            str(source.get("display") or source.get("id") or "")
            for source in coverage_sources
            if str(source.get("id") or "") not in covered
        ]

    return {
        "kind": "CONFIRMED",
        "retrieval_status": retrieval_status,
        "basis": (
            (
                "declared path found and content-bearing payload retrieved"
                if retrieval_status == "CONTENT_RETRIEVED"
                else "packet contains edge/path records matching the declared contract"
            )
            if not missing_sources
            else f"partial coverage — {len(missing_sources)} source(s) yielded no edges"
        ),
        "terminal": True,
        "recovery_available": False,
        "missing_sources": missing_sources,
    }


def pipeline_b_execute(state: EngineState, conn: lb.Connection) -> dict:
    """Phase 5 entry point for Pipeline B.

    Reads the RelationalContract from state, dispatches the matching tool
    calls, folds the results into a canonical EvidencePacket, and assembles
    a minimal company_handoff so Battalion can render the evidence directly.
    The confirmation_response is pre-populated with the deterministic verdict
    so the downstream Battalion branches observe the right verdict.
    """
    t0 = time.perf_counter()
    contract = _normalise_contract(state.get("relational_contract"))
    existing_flags = list(state.get("degradation_flags") or [])

    steps_summary = [
        f"{s.get('direction','?')}+labels={s.get('edge_labels',[])}"
        for s in (contract.get("steps") or [])
    ]
    print(
        f"\n[Pipeline B] question_form={contract['question_form']}, "
        f"edges={contract['edge_types']}, "
        f"sources={len(contract['source_ids'])}, "
        f"targets={len(contract['target_ids'])}"
        + (f", steps={steps_summary}" if steps_summary else "")
    )
    log_event(
        "pipeline_b_enter",
        question_form=contract["question_form"],
        edge_types=contract["edge_types"],
        source_count=len(contract["source_ids"]),
        target_count=len(contract["target_ids"]),
        direction=contract["direction"],
    )

    canonical = program_for_targeted_state({
        **state,
        "relational_contract": contract,
    })
    canonical_execution = execute_retrieval_program(
        conn,
        canonical,
        program_context=state.get("planner_program") or {},
    )
    variables = dict(canonical_execution["variables"])
    canonical_steps = list(canonical_execution["program"].get("steps") or [])
    if contract.get("question_form") == "chain" and canonical_steps:
        final_var = str(canonical_steps[-1].get("assign_to") or "")
        preceding = [
            str(step.get("assign_to") or "") for step in canonical_steps[:-1]
        ]
        chain_terminal_empty = not bool(variables.get(final_var))
        chain_intermediate_found = any(bool(variables.get(name)) for name in preceding)
    else:
        chain_terminal_empty = False
        chain_intermediate_found = False
    declared_targets = _declared_semantic_targets(conn, state, contract)
    content_refinement_required = _content_seeking_contains_lookup(state, contract)
    content_seed_ids = [
        str(node.get("id")) for node in declared_targets if node.get("id")
    ]
    if content_refinement_required and not content_seed_ids:
        content_seed_ids = _resolve_ids(conn, contract.get("source_ids") or [])
    contains_content = (
        _contains_content_descendants(conn, content_seed_ids)
        if content_refinement_required else []
    )

    # Priority order matters to late-paging callers: exact scopes and their
    # content arrive before a broad contract neighbourhood can consume the
    # caller's body budget.
    priority_variables: dict[str, list] = {}
    if declared_targets:
        priority_variables["declared_targets"] = declared_targets
    if contains_content:
        priority_variables["contains_content"] = contains_content
    variables = {**priority_variables, **variables}

    verdict_space = str(state.get("verdict_space") or "coverage").lower()
    if verdict_space in {"coverage", "ruling"}:
        # Freeze the graph-derived scope before adding lexical/query priors.
        # Priors may enter the packet, but they must not become topology
        # expansion seeds merely because their words resemble the query.
        governance_scope_variables = dict(variables)
        prior_candidates = state.get("planner_governing_candidates")
        if isinstance(prior_candidates, list):
            governing_candidates_for_query = prior_candidates
        else:
            # Direct Pipeline-B callers have no Planner state to reuse.
            governing_candidates_for_query = governing_seed_candidates(
                conn, str(state.get("query") or "")
            )
        if governing_candidates_for_query:
            # Candidate authority comes first so a broad neighbourhood cannot
            # consume the later payload budget before the likely rule nodes.
            variables = {
                "governing_query_candidates": governing_candidates_for_query,
                **variables,
            }
        # Run after content refinement so an explicitly requested ruling can
        # see rules attached to answer-bearing descendants as well as the
        # original structural neighbourhood.
        rule_closure = _governance_rule_closure(
            conn,
            governance_scope_variables,
            source_ids=_resolve_ids(conn, contract.get("source_ids") or []),
        )
        if rule_closure:
            variables["governance_rule_closure"] = rule_closure
    program = dict(canonical_execution["program"])
    program_steps = list(program.get("steps") or [])
    known_assignments = {
        str(step.get("assign_to") or "") for step in program_steps
    }
    synthetic = _synth_program_from_contract(contract, variables)
    for step in synthetic.get("steps") or []:
        assignment = str(step.get("assign_to") or "")
        if assignment and assignment not in known_assignments:
            program_steps.append(step)
            known_assignments.add(assignment)
    program["steps"] = program_steps

    collected_ids: list[str] = []
    for v in variables.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and item.get("id"):
                    collected_ids.append(str(item["id"]))
                elif isinstance(item, str):
                    collected_ids.append(item)

    packet = build_evidence_packet(conn, variables, program, collected_ids)
    packet["retrieval_program"] = canonical_execution["program"]

    packet, existing_flags, recovered = try_broad_region_recovery(
        conn,
        {**state, "evidence_packet": packet},
        packet,
        question_form=contract["question_form"],
        source_ids=contract["source_ids"],
        variables=variables,
        program=program,
        collected_ids=collected_ids,
        chain_terminal_empty=chain_terminal_empty,
        chain_intermediate_found=chain_intermediate_found,
        existing_flags=existing_flags,
    )

    postprocessing_operations: list[dict] = []
    if declared_targets:
        postprocessing_operations.append({
            "operation": "declared_target_preservation",
            "result_count": len(declared_targets),
        })
    if contains_content:
        postprocessing_operations.append({
            "operation": "contains_content_hydration",
            "result_count": len(contains_content),
        })
    if variables.get("governance_rule_closure"):
        postprocessing_operations.append({
            "operation": "governance_rule_closure",
            "result_count": len(variables["governance_rule_closure"]),
        })
    if variables.get("governing_query_candidates"):
        postprocessing_operations.append({
            "operation": "governing_query_candidates",
            "result_count": len(variables["governing_query_candidates"]),
        })
    if recovered:
        postprocessing_operations.append({
            "operation": "empty_packet_broad_region_recovery",
            "result_count": len(packet.get("node_records") or []),
        })

    # Populate semantic_anchor previews for packet nodes — Battalion context
    # expansion needs these for concise framing.
    node_ids = [n.get("id") for n in (packet.get("node_records") or []) if n.get("id")]
    try:
        preview_list = get_anchor_previews(conn, node_ids, preview_tokens=200)
    except Exception:
        preview_list = []
    preview_map: dict[str, dict] = {}
    if isinstance(preview_list, list):
        for pv in preview_list:
            if isinstance(pv, dict) and pv.get("id"):
                preview_map[str(pv["id"])] = pv
    if preview_map and packet.get("node_records"):
        for n in packet["node_records"]:
            pv = preview_map.get(str(n.get("id") or ""))
            if isinstance(pv, dict):
                if pv.get("semantic_anchor"):
                    n.setdefault("semantic_anchor", pv["semantic_anchor"])
                prev_text = pv.get("text_preview") or pv.get("preview") or ""
                if prev_text:
                    n.setdefault("anchor_preview", prev_text)

    contains_content_ids = {
        str(node.get("id") or "")
        for node in contains_content
        if isinstance(node, dict) and node.get("id")
    }
    assessed_ids = set(content_seed_ids) | contains_content_ids
    substantive_ids = [
        str(node.get("id"))
        for node in packet.get("node_records") or []
        if str(node.get("id") or "") in assessed_ids
        and _substantive_preview(str(node.get("anchor_preview") or ""))
    ]
    possibly_truncated = len(contains_content_ids) >= _CONTAINS_CONTENT_MAX_NODES
    if not content_refinement_required:
        content_status = "not_required"
    elif not substantive_ids:
        content_status = "unresolved"
    elif possibly_truncated:
        content_status = "partial"
    else:
        content_status = "content_retrieved"
    packet["retrieval_assessment"] = {
        "structural_status": "path_found" if packet.get("edge_records") else "node_found",
        "content_status": content_status,
        "semantic_completeness": "not_assessed",
        "content_refinement_required": content_refinement_required,
        "content_seed_ids": content_seed_ids,
        "content_descendant_ids": sorted(contains_content_ids),
        "substantive_node_ids": substantive_ids,
        "contains_depth_limit": _CONTAINS_CONTENT_MAX_DEPTH,
        "contains_node_limit": _CONTAINS_CONTENT_MAX_NODES,
        "possibly_truncated": possibly_truncated,
    }
    if content_status in {"partial", "unresolved"}:
        flag = (
            "contains_payload_budget_reached"
            if content_status == "partial"
            else "contains_payload_unresolved"
        )
        existing_flags.append(flag)
        packet["degradation_flags"] = sorted(set(
            list(packet.get("degradation_flags") or []) + [flag]
        ))

    # Content arithmetic flag: if the planner flagged this query as requiring
    # arithmetic over content values, inject the gap now so Battalion can
    # short-circuit with ILL_POSED and return the nodes to the caller.
    requires_arithmetic = bool(
        str(state.get("relational_contract", {}).get("requires_content_arithmetic") or "").lower()
        in ("true", "1", "yes")
        or contract.get("requires_content_arithmetic")
    )

    # Deterministic verdict for Pipeline B.
    resolved_coverage_ids = _resolve_ids(conn, contract["source_ids"])
    verdict_contract = {
        **contract,
        "coverage_sources": [
            {"id": resolved, "display": raw}
            for raw, resolved in zip(
                contract["source_ids"], resolved_coverage_ids
            )
        ],
    }
    verdict = compute_verdict_pipeline_b(
        {
            **state,
            "evidence_packet": packet,
            "relational_contract": verdict_contract,
        },
        chain_terminal_empty=chain_terminal_empty,
        chain_intermediate_found=chain_intermediate_found,
    )

    # Build synthetic handoff.
    hypothesis_status = "confirmed" if verdict["kind"] == "CONFIRMED" else "unconfirmed"
    confidence = "medium" if verdict["kind"] == "CONFIRMED" else "low"
    gaps: list = []
    if verdict.get("missing_sources"):
        gaps = [
            {
                "gap_type": "missing_source_coverage",
                "specific_node_or_concept": src,
                "actionable_suggestion": (
                    f"No matching edges of type {contract['edge_types']} "
                    f"covered {src}"
                ),
            }
            for src in verdict["missing_sources"]
        ]
    if verdict["kind"] == "ILL_POSED":
        gaps = [
            {
                "gap_type": "structural_absence",
                "specific_node_or_concept": ",".join(contract["edge_types"]),
                "actionable_suggestion": (
                    "This query requires edge types that do not exist in the graph"
                ),
            }
        ]

    truncation = _chain_truncation_gap(
        contract, chain_terminal_empty, chain_intermediate_found)
    if truncation is not None and not any(
        isinstance(g, dict) and g.get("gap_type") == "chain_truncated" for g in gaps
    ):
        gaps = list(gaps) + [truncation]

    # v9 meta_gap honesty: Pipeline B bypasses semantic_validation, so inspect
    # Strategy-B reasoning here. Counterfactual diagnostics are not findings:
    # only an actual absence assertion can create a gap, and the graph/packet
    # gets the final word on whether the named concept exists.
    strategy_b = (state.get("planner_program") or {}).get("strategy_b") or {}
    reasoning_map = strategy_b.get("reasoning_per_concept") or {}
    for concept, reasoning in reasoning_map.items():
        if not _asserts_actual_absence(str(reasoning or "")):
            continue
        concept_key = str(concept).strip()
        if not concept_key:
            continue
        if _concept_exists(conn, concept_key, packet):
            continue
        # Dedupe against already-collected gaps.
        if any(
            isinstance(g, dict)
            and g.get("gap_type") == "missing_concept"
            and str(g.get("specific_node_or_concept", "")).strip().lower()
            == concept_key.lower()
            for g in gaps
        ):
            continue
        gaps.append({
            "gap_type": "missing_concept",
            "specific_node_or_concept": concept_key,
            "actionable_suggestion": (
                f"The Planner's own reasoning indicates '{concept_key}' is "
                "absent from this graph. Author a node covering this concept "
                "so future queries can ground against explicit evidence."
            ),
            "provenance": {
                "source": "deterministic",
                "tier": "pipeline_b",
                "basis": "planner_strategy_b_absence_language",
            },
        })

    # v9.x: deterministic gap-type corrections (schema_gap / missing_relationship
    # / confabulation on unknown entity). Runs uniformly across all pipelines.
    from gap_hinter import apply_gap_type_hints

    apply_gap_type_hints(
        gaps,
        state.get("query", "") or "",
        node_records=packet.get("node_records") or [],
        edge_records=packet.get("edge_records") or [],
        token_in_graph=_token_in_graph_check(),
        known_context=str(
            ((state.get("compass") or {}).get("graph_profile") or {}).get(
                "domain", ""
            )
        ),
    )

    # Inject requires_content_arithmetic gap and override verdict to ILL_POSED
    # so Battalion short-circuits with the nodes attached rather than synthesising.
    if requires_arithmetic:
        node_labels = [
            n.get("label") or n.get("id", "")
            for n in (packet.get("node_records") or [])[:6]
        ]
        gaps.append({
            "gap_type": "requires_content_arithmetic",
            "specific_node_or_concept": ", ".join(node_labels) if node_labels else "retrieved nodes",
            "actionable_suggestion": (
                "This query requires arithmetic over content values (e.g. date subtraction, "
                "ratio computation). The relevant nodes have been retrieved with their values. "
                "Perform the arithmetic on the retrieved node content to compute the answer."
            ),
            "provenance": {
                "source": "deterministic",
                "tier": "pipeline_b",
                "basis": "planner_flagged_requires_content_arithmetic",
            },
        })
        hypothesis_status = "unconfirmed"
        confidence = "low"
        verdict = {
            "kind": "ILL_POSED",
            "basis": "requires_content_arithmetic — engine retrieved relevant nodes; arithmetic is caller's responsibility",
            "missing_sources": [],
        }

    packet["judgment_view"] = build_judgment_view(
        {
            **state,
            "relational_contract": contract,
            "retrieval_program": canonical_execution["program"],
        },
        packet,
        conn,
    )
    company_handoff = _build_company_handoff(
        packet_for_judgment(packet), contract, hypothesis_status, confidence, gaps
    )

    # Mirror the deterministic verdict into confirmation_response so
    # Battalion's existing verdict branches engage correctly.
    confirmation_response = {
        "verdict": verdict["kind"],
        "retrieval_status": verdict.get("retrieval_status", "UNKNOWN"),
        "ill_posed_reason": verdict.get("basis", "") if verdict["kind"] == "ILL_POSED" else "",
        "confidence_per_trail": {},
        "basis": verdict.get("basis", ""),
    }

    log_event(
        "pipeline_b_exit",
        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
        node_count=len(packet.get("node_records") or []),
        edge_count=len(packet.get("edge_records") or []),
        path_count=len(packet.get("path_records") or []),
        verdict=verdict["kind"],
        retrieval_status=verdict.get("retrieval_status", "UNKNOWN"),
        missing_sources=verdict.get("missing_sources", []),
    )

    execution_receipt = dict(canonical_execution["execution_receipt"])
    execution_receipt["postprocessing_operations"] = postprocessing_operations
    execution_receipt["empty_packet_recovery"] = recovered
    execution_receipt["final_packet_node_count"] = len(packet.get("node_records") or [])
    execution_receipt["final_packet_edge_count"] = len(packet.get("edge_records") or [])
    execution_receipt["final_packet_path_count"] = len(packet.get("path_records") or [])
    packet["retrieval_program"] = canonical_execution["program"]
    packet["execution_receipt"] = execution_receipt

    # v9: synthesis_mode collapsed into one uniform synthesis step. The
    # Planner no longer declares a mode; Battalion determines length from
    # packet richness. Field retained as a deprecated no-op for transitional
    # corpus compatibility.
    synthesis_mode = "uniform"

    return {
        "evidence_packet": packet,
        "retrieval_program": canonical_execution["program"],
        "execution_receipt": execution_receipt,
        "answer_contract": {},  # Pipeline B uses RelationalContract, not AnswerContract
        "company_handoff": company_handoff,
        "confirmation_response": confirmation_response,
        "deterministic_verdict": verdict,
        "relational_contract": contract,
        "retrieval_strategy": "contract_driven",
        "synthesis_mode": synthesis_mode,
        "degradation_flags": sorted(set(existing_flags)),
        "candidate_set": packet.get("node_records") or [],
        "frontier_clusters": [],
        "seed_diagnostic": {
            "strategies_fired": ["pipeline_b:" + contract["question_form"]],
            "per_strategy_counts": {k: len(v) if isinstance(v, list) else 0 for k, v in variables.items()},
            "seed_miss": not (packet.get("node_records") or packet.get("edge_records")),
            "total_candidates": len(packet.get("node_records") or []),
        },
    }
