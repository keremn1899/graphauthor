"""Backend tool execution helpers — shared between agent_graph.py and company.py.

Extracted to avoid circular imports: company.py needs to call these for inline
local recovery (v5 architecture), but agent_graph.py imports from company.py.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from models import NEARTO_MAX_BACKWARD, NEARTO_MAX_FORWARD, StructuralFacts
from tools import (
    exact_node_lookup,
    filter_nodes,
    find_paths,
    get_all_node_ids,
    get_anchor_previews,
    get_neighbourhood,
    get_nodes_by_edge_type,
    get_structural_profile,
    hop_expansion,
    id_pattern_lookup,
    lexical_search,
    limit_nodes,
    query_structural_index,
    select_landmarks,
    set_algebra,
    sort_nodes,
    traverse_chain,
    vector_search,
    walk_sequence,
)

if TYPE_CHECKING:
    import real_ladybug as lb

SUPPORTED_TOOL_NAMES = frozenset(
    {
        "vector_search",
        "lexical_search",
        "id_pattern_lookup",
        "exact_node_lookup",
        "query_structural_index",
        "get_structural_profile",
        "get_anchor_previews",
        "hop_expansion",
        "find_paths",
        "traverse_chain",
        "get_neighbourhood",
        "filter_nodes",
        "sort_nodes",
        "limit_nodes",
        "set_algebra",
        "select_landmarks",
        "walk_sequence",
        "get_all_node_ids",
        "get_nodes_by_edge_type",
    }
)

# v7 §9: the legacy ``get_neighbours`` alias is deprecated. The canonical
# tool name is ``get_neighbourhood``; the backend raises on the alias so
# stale Planner outputs surface loudly rather than silently coercing.
_DEPRECATED_TOOL_NAMES = frozenset({"get_neighbours"})


# ---------------------------------------------------------------------------
# ID extraction helpers
# ---------------------------------------------------------------------------

def _extract_ids_from_result_item(item) -> list[str]:
    """Extract node IDs from heterogeneous tool result records."""
    if isinstance(item, str):
        return [item] if item else []
    if not isinstance(item, dict):
        return []

    ids: list[str] = []
    node_id = item.get("id", "")
    if isinstance(node_id, str) and node_id:
        ids.append(node_id)

    for key in ("node_chain", "path_chain"):
        chain = item.get(key, [])
        if isinstance(chain, list):
            for nid in chain:
                if isinstance(nid, str) and nid:
                    ids.append(nid)

    start_id = item.get("start", "")
    if isinstance(start_id, str) and start_id:
        ids.append(start_id)

    seen: set[str] = set()
    ordered: list[str] = []
    for nid in ids:
        if nid not in seen:
            seen.add(nid)
            ordered.append(nid)
    return ordered


def _resolve_variable(value, variables: dict) -> list[str]:
    """Resolve a $variable reference to a list of node IDs."""
    if isinstance(value, str) and value.startswith("$"):
        var_name = value[1:]
        resolved = variables.get(var_name, [])
        if isinstance(resolved, list):
            ids = []
            for item in resolved:
                ids.extend(_extract_ids_from_result_item(item))
            return [i for i in ids if i]
        return []
    if isinstance(value, list):
        result = []
        for v in value:
            result.extend(_resolve_variable(v, variables))
        return result
    return []


def _assign_to_origin(var_name: str) -> str:
    """Map Planner assign_to variable name to candidate origin tag."""
    vn = var_name.lower()
    if "structural" in vn:
        return "structural"
    if "fallback" in vn:
        return "fallback"
    if "neighbourhood" in vn or "neighborhood" in vn or "neighbor_exp" in vn:
        return "neighbourhood"
    if vn.startswith("direct"):
        return "direct_path"
    if vn.startswith("hypothesis") or vn.startswith("seeds_b"):
        return "hypothesis_path"
    if "hypothesis_paths" in vn:
        return "hypothesis_path"
    if "paths" in vn and "direct" not in vn:
        return "hypothesis_path"
    return "direct_path"


def _resolve_collect(collect_expr: str, variables: dict) -> list[str]:
    """Resolve a collect expression like '$var1 + $var2 - $var3' to merged node IDs.

    Supports:
    - Addition (union):    '$a + $b'
    - Subtraction (diff):  '$a - $b'   → all IDs in $a that are not in $b
    - Intersection:        '$a & $b'   → IDs present in both, preserving $a order
    - Mixed:               '$all - $leads_to_x + $extra'

    Tokenises left-to-right. The first token is always unioned in.
    Each subsequent token is either added to or subtracted from the running set.
    """
    if not collect_expr:
        return []

    # Tokenise while preserving the operator.
    import re as _re
    token_pattern = _re.compile(r'([+\-&])\s*(\$\w+)')
    # First token has no leading operator — always added
    first_match = _re.match(r'\s*(\$\w+)', collect_expr)
    if not first_match:
        return []

    result_ids: list[str] = list(_resolve_variable(first_match.group(1).strip(), variables))
    result_set: set[str] = set(result_ids)

    for op_match in token_pattern.finditer(collect_expr, first_match.end()):
        op = op_match.group(1)
        var = op_match.group(2).strip()
        var_ids = set(_resolve_variable(var, variables))

        if op == "+":
            for nid in var_ids:
                if nid not in result_set:
                    result_set.add(nid)
                    result_ids.append(nid)
        elif op == "-":
            result_ids = [nid for nid in result_ids if nid not in var_ids]
            result_set -= var_ids
        elif op == "&":
            result_ids = [nid for nid in result_ids if nid in var_ids]
            result_set &= var_ids

    return result_ids


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def execute_tool(
    conn: "lb.Connection",
    tool_name: str,
    params: dict,
    structural_index: dict[str, StructuralFacts],
) -> list[dict]:
    """Dispatch a single tool call and return results."""
    tool_name = str(tool_name or "").strip().lower()
    if tool_name in _DEPRECATED_TOOL_NAMES:
        raise ValueError(
            f"Tool '{tool_name}' is deprecated in v7; use 'get_neighbourhood' instead"
        )
    try:
        if tool_name == "vector_search":
            query = params.get("query", "")
            k = int(params.get("k", 5))
            return vector_search(conn, query, k)

        elif tool_name == "lexical_search":
            terms = params.get("terms", [])
            k = int(params.get("k", 5))
            return lexical_search(conn, terms, k)

        elif tool_name == "id_pattern_lookup":
            pattern = str(params.get("pattern", ""))
            k = int(params.get("k", 25))
            return id_pattern_lookup(conn, pattern, k)

        elif tool_name == "exact_node_lookup":
            raw_values = params.get("label_or_id", "")
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            results: list[dict] = []
            seen_ids: set[str] = set()
            for value in values:
                label_or_id = str(value or "").strip()
                if not label_or_id:
                    continue
                result = exact_node_lookup(conn, label_or_id)
                if result and result.get("id") not in seen_ids:
                    results.append(result)
                    seen_ids.add(result["id"])
            return results

        elif tool_name == "query_structural_index":
            role = params.get("role", "")
            return query_structural_index(structural_index, role)

        elif tool_name == "get_structural_profile":
            role = str(params.get("role", ""))
            top_n = int(params.get("top_n", 10))
            return get_structural_profile(structural_index, role, top_n, conn)

        elif tool_name == "get_anchor_previews":
            ids = params.get("ids", params.get("node_ids", []))
            if isinstance(ids, list) and ids and isinstance(ids[0], dict):
                ids = [n.get("id", "") for n in ids if isinstance(n, dict)]
            preview_tokens = int(params.get("preview_tokens", 200))
            return get_anchor_previews(conn, ids, preview_tokens)

        elif tool_name == "hop_expansion":
            seeds = params.get("seeds", [])
            if isinstance(seeds, list) and seeds and isinstance(seeds[0], dict):
                seeds = [s.get("id", s) if isinstance(s, dict) else s for s in seeds]
            hop_limits = params.get("hop_limits", {})
            # Enforce NEARTO hard cap
            if "nearto" in hop_limits:
                nl = hop_limits["nearto"]
                for dir_key in list(nl.keys()):
                    if dir_key in ("forward", "down"):
                        nl[dir_key] = min(nl[dir_key], NEARTO_MAX_FORWARD)
                    else:
                        nl[dir_key] = min(nl[dir_key], NEARTO_MAX_BACKWARD)
            raw_results = hop_expansion(conn, seeds, hop_limits)
            path_results: list[dict] = []
            for item in raw_results:
                parent = item.get("parent_id")
                if parent:
                    via_type = item.get("via_type", "leadsto")
                    direction = item.get("via_direction", "forward")
                    if direction in ("backward", "up"):
                        chain = [item["id"], parent]
                    else:
                        chain = [parent, item["id"]]
                    item = dict(item, path_chain=chain, edge_chain=[via_type], edge_label_chain=[])
                path_results.append(item)
            return path_results

        elif tool_name == "find_paths":
            source_set = params.get("source_set", [])
            target_set = params.get("target_set", [])
            if isinstance(source_set, list) and source_set and isinstance(source_set[0], dict):
                source_set = [s["id"] for s in source_set if "id" in s]
            if isinstance(target_set, list) and target_set and isinstance(target_set[0], dict):
                target_set = [s["id"] for s in target_set if "id" in s]
            max_hops = int(params.get("max_hops", 6))
            edge_types = params.get("edge_types")
            if isinstance(edge_types, list):
                edge_types = [str(t).lower() for t in edge_types if str(t)] or None
            else:
                edge_types = None
            # The dispatcher drops params it does not name, so a `direction`
            # the recipe declared reached here and went nowhere. That is the
            # shape of bug worth stating: an option that is accepted, carried
            # through two layers, and silently ignored at the last one.
            direction = str(params.get("direction") or "outgoing").lower()
            exclude_labels = tuple(
                str(v) for v in (params.get("exclude_labels") or ()) if str(v)
            )
            results = find_paths(
                conn, source_set, target_set, max_hops,
                edge_types=edge_types, direction=direction,
                exclude_labels=exclude_labels,
            )
            path_nodes: list[dict] = []
            for path in results:
                for nid in path.get("node_chain", []):
                    path_nodes.append({
                        "id": nid,
                        "label": "",
                        "path_chain": path.get("node_chain", []),
                        "edge_chain": path.get("edge_chain", []),
                        "edge_label_chain": path.get("edge_label_chain", []),
                    })
            return path_nodes

        elif tool_name == "traverse_chain":
            starts = params.get("starts", params.get("seeds", []))
            if isinstance(starts, list) and starts and isinstance(starts[0], dict):
                starts = [s["id"] for s in starts if "id" in s]
            direction = params.get("direction", "forward")
            edge_type = str(params.get("edge_type", "leadsto")).lower()
            max_depth = int(params.get("max_depth", 5))
            chains = traverse_chain(conn, starts, direction, edge_type, max_depth)
            path_nodes: list[dict] = []
            for chain in chains:
                node_chain = chain.get("node_chain", [])
                if len(node_chain) <= 1:
                    for nid in node_chain:
                        path_nodes.append({"id": nid, "label": ""})
                    continue
                ordered = list(reversed(node_chain)) if direction == "backward" else node_chain
                chain_edge_types = [edge_type] * (len(ordered) - 1)
                for nid in ordered:
                    path_nodes.append({
                        "id": nid,
                        "label": "",
                        "path_chain": ordered,
                        "edge_chain": chain_edge_types,
                        "edge_label_chain": [],
                    })
            return path_nodes

        elif tool_name == "get_neighbourhood":
            node_ids = params.get("node_ids", [])
            if isinstance(node_ids, list) and node_ids and isinstance(node_ids[0], dict):
                node_ids = [n["id"] for n in node_ids if "id" in n]
            depth = int(params.get("depth", 1))
            edge_types = params.get("edge_types")
            if isinstance(edge_types, list):
                edge_types = [str(t).lower() for t in edge_types if isinstance(t, str)]
            else:
                edge_types = None
            # v7: direction defaults to "both" to preserve v6 symmetric semantics.
            # Pipeline B fanout sets this explicitly per RelationalContract.direction.
            direction = str(params.get("direction", "both")).lower()
            if direction not in ("outgoing", "incoming", "both"):
                direction = "both"
            max_nodes = max(1, int(params.get("max_nodes", 3000)))
            edge_labels = params.get("edge_labels")
            if isinstance(edge_labels, list):
                edge_labels = [str(label) for label in edge_labels if str(label)] or None
            else:
                edge_labels = None
            strategy = str(params.get("strategy") or "bfs").strip().lower()
            kinds = params.get("kinds")
            if isinstance(kinds, list):
                kinds = [str(kind) for kind in kinds if str(kind)] or None
            else:
                kinds = None
            kind_prefixes = params.get("kind_prefixes")
            if isinstance(kind_prefixes, list):
                kind_prefixes = [str(prefix) for prefix in kind_prefixes if str(prefix)] or None
            else:
                kind_prefixes = None
            properties = params.get("properties")
            if not isinstance(properties, dict):
                properties = None
            return get_neighbourhood(
                conn, node_ids, depth, edge_types, direction,
                structural_index=structural_index,
                max_nodes=max_nodes,
                edge_labels=edge_labels,
                strategy=strategy,
                kinds=kinds,
                kind_prefixes=kind_prefixes,
                properties=properties,
            )

        elif tool_name == "filter_nodes":
            return filter_nodes(
                conn,
                params.get("node_ids", []),
                kinds=params.get("kinds") or None,
                kind_prefixes=params.get("kind_prefixes") or None,
                properties=params.get("properties") if isinstance(params.get("properties"), dict) else None,
            )

        elif tool_name == "sort_nodes":
            return sort_nodes(
                conn,
                params.get("node_ids", []),
                by=str(params.get("by") or "id"),
                order=str(params.get("order") or "asc"),
            )

        elif tool_name == "limit_nodes":
            return limit_nodes(
                params.get("node_ids", []),
                int(params.get("limit") or 0),
            )

        elif tool_name == "set_algebra":
            left = params.get("of", params.get("left", []))
            if left is None:
                left = []
            right = params.get("minus")
            if right is None:
                right = params.get("with")
            if right is None:
                right = params.get("right")
            if right is None:
                right = []
            return set_algebra(
                op=str(params.get("op") or "union"),
                left=left if isinstance(left, list) else [left],
                right=right if isinstance(right, list) else [right],
            )

        elif tool_name == "select_landmarks":
            return select_landmarks(
                conn,
                structural_index,
                pinned=params.get("pinned") or [],
                roles=params.get("roles") or None,
                include_pinned=bool(params.get("include_pinned", True)),
                limit=int(params.get("limit") or 8),
            )

        elif tool_name == "walk_sequence":
            node_ids = params.get("node_ids", params.get("starts", []))
            hops = params.get("hops") or []
            if not isinstance(hops, list):
                hops = []
            return walk_sequence(
                conn,
                node_ids if isinstance(node_ids, list) else [node_ids],
                hops,
                kinds=params.get("kinds") or None,
                kind_prefixes=params.get("kind_prefixes") or None,
                properties=params.get("properties") if isinstance(params.get("properties"), dict) else None,
                max_nodes=max(1, int(params.get("max_nodes") or 300)),
            )

        elif tool_name == "get_all_node_ids":
            # Returns every node in the graph — for set-difference queries.
            return get_all_node_ids(conn)

        elif tool_name == "get_nodes_by_edge_type":
            edge_type = str(params.get("edge_type", "leadsto")).lower()
            result = get_nodes_by_edge_type(conn, edge_type)
            # v6 canonical shape: return node_records tagged with the edge
            # participation they proved, and stash edge_records on each node so
            # build_evidence_packet can recover them without re-querying.
            if isinstance(result, dict):
                edges = result.get("edge_records", [])
                nodes = result.get("node_records", [])
                if nodes:
                    # Attach the full edge list to the first node so downstream
                    # packet assembly can detect canonical edge evidence. This
                    # is a transport detail, not surfaced to LLMs.
                    nodes = [dict(n) for n in nodes]
                    nodes[0]["_edge_records"] = edges
                return nodes
            return result

        else:
            print(f"  Warning: Unknown tool '{tool_name}'")
            return []

    except Exception as e:
        print(f"  Warning: Tool '{tool_name}' failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Candidate set builder
# ---------------------------------------------------------------------------

def build_candidate_set(
    conn: "lb.Connection",
    collected_ids: list[str],
    variables: dict[str, list],
    program: dict,
) -> list[dict]:
    """Build the candidate set with origin tags and preserved path chains."""
    candidates: dict[str, dict] = {}

    _ORIGIN_PRIORITY = {
        "hypothesis_path": 5,
        "structural": 4,
        "direct_path": 3,
        "fallback": 2,
        "neighbourhood": 1,
    }
    origin_map: dict[str, str] = {}
    path_chain_map: dict[str, dict] = {}

    for var_name, var_val in variables.items():
        origin = _assign_to_origin(var_name)

        for item in var_val:
            for nid in _extract_ids_from_result_item(item):
                current = origin_map.get(nid)
                if current is None or _ORIGIN_PRIORITY.get(origin, 0) > _ORIGIN_PRIORITY.get(current, 0):
                    origin_map[nid] = origin

            if isinstance(item, dict) and item.get("path_chain"):
                for nid in _extract_ids_from_result_item(item):
                    if nid not in path_chain_map:
                        path_chain_map[nid] = {
                            "path_chain": item["path_chain"],
                            "edge_chain": item.get("edge_chain", []),
                            "edge_label_chain": item.get("edge_label_chain", []),
                        }

    for nid in collected_ids:
        if nid in candidates:
            continue

        label = ""
        rows = list(conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.label", {"id": nid}
        ))
        if rows:
            label = rows[0][0]

        candidate: dict = {
            "id": nid,
            "label": label,
            "origin": origin_map.get(nid, "neighbourhood"),
        }
        if nid in path_chain_map:
            candidate.update(path_chain_map[nid])

        candidates[nid] = candidate

    return list(candidates.values())


# ---------------------------------------------------------------------------
# v6: EvidencePacket assembly
# ---------------------------------------------------------------------------

def build_evidence_packet(
    conn: "lb.Connection",
    variables: dict[str, list],
    program: dict,
    collected_ids: list[str],
) -> dict:
    """Assemble the canonical EvidencePacket from backend tool outputs.

    The packet is the single source of truth for what the graph produced.
    Downstream tiers read it; recovery rounds append to it. This function
    preserves every edge_records and path_chain that the tools produced —
    the flattening that used to happen in build_candidate_set is no longer
    allowed.
    """
    node_records: list[dict] = []
    edge_records: list[dict] = []
    path_records: list[dict] = []
    packet_provenance: list[dict] = []
    degradation_flags: list[str] = []

    seen_node_ids: set[str] = set()
    seen_edge_keys: set[tuple] = set()
    seen_path_keys: set[tuple] = set()

    steps_by_var: dict[str, dict] = {}
    for step in program.get("steps", []) or []:
        va = step.get("assign_to")
        if isinstance(va, str) and va:
            steps_by_var[va] = step
    for step in (program.get("contingency", {}) or {}).get("fallback_steps", []) or []:
        va = step.get("assign_to")
        if isinstance(va, str) and va:
            steps_by_var[va] = step

    for var_name, var_val in variables.items():
        step = steps_by_var.get(var_name, {})
        tool = step.get("tool", "")
        origin = _assign_to_origin(var_name)

        added_nodes = 0
        added_edges = 0
        added_paths = 0

        items = var_val if isinstance(var_val, list) else []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                if isinstance(item, str) and item and item not in seen_node_ids:
                    seen_node_ids.add(item)
                    node_records.append({"id": item, "label": "", "origin": origin})
                    added_nodes += 1
                continue

            # Canonical edge records surfaced by get_nodes_by_edge_type
            canonical_edges = item.get("_edge_records") or []
            if isinstance(canonical_edges, list):
                for e in canonical_edges:
                    if not isinstance(e, dict):
                        continue
                    key = (
                        e.get("source_id", ""),
                        e.get("target_id", ""),
                        e.get("edge_type", ""),
                        e.get("edge_label", ""),
                    )
                    if key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(key)
                    edge_records.append({
                        "source_id": e.get("source_id", ""),
                        "source_label": e.get("source_label", ""),
                        "target_id": e.get("target_id", ""),
                        "target_label": e.get("target_label", ""),
                        "edge_type": e.get("edge_type", ""),
                        "edge_label": e.get("edge_label", ""),
                        "origin": origin,
                        "from_tool": tool,
                    })
                    added_edges += 1

            # Node record
            nid = item.get("id", "")
            if isinstance(nid, str) and nid and nid not in seen_node_ids:
                seen_node_ids.add(nid)
                node_record = {
                    "id": nid,
                    "label": item.get("label", ""),
                    "origin": origin,
                    "via_edge_type": item.get("via_edge_type", ""),
                }
                node_records.append(node_record)
                added_nodes += 1

            # Path record
            path_chain = item.get("path_chain")
            if isinstance(path_chain, list) and len(path_chain) >= 2:
                key = tuple(path_chain)
                if key not in seen_path_keys:
                    seen_path_keys.add(key)
                    edge_chain = item.get("edge_chain", [])
                    edge_label_chain = item.get("edge_label_chain", [])
                    # v8 §9: normalise trail orientation to edge-native direction.
                    _directed = {"leadsto", "contains", "expresses"}
                    chain_l = list(path_chain)
                    echain_l = list(edge_chain) if isinstance(edge_chain, list) else []
                    elabels_l = list(edge_label_chain) if isinstance(edge_label_chain, list) else []
                    fwd = rev = 0
                    for i in range(len(chain_l) - 1):
                        if i >= len(echain_l):
                            break
                        et_i = str(echain_l[i] or "").lower()
                        if et_i not in _directed:
                            continue
                        a, b = chain_l[i], chain_l[i + 1]
                        for e in edge_records:
                            if e.get("from_path"):
                                continue
                            if str(e.get("edge_type", "")).lower() != et_i:
                                continue
                            if e.get("source_id") == a and e.get("target_id") == b:
                                fwd += 1
                                break
                            if e.get("source_id") == b and e.get("target_id") == a:
                                rev += 1
                                break
                    oriented_flip = rev > 0 and fwd == 0
                    if oriented_flip:
                        chain_l = list(reversed(chain_l))
                        echain_l = list(reversed(echain_l))
                        elabels_l = list(reversed(elabels_l))
                    path_records.append({
                        "node_chain": list(chain_l),
                        "edge_chain": list(echain_l),
                        "edge_label_chain": list(elabels_l),
                        "source": chain_l[0],
                        "target": chain_l[-1],
                        "origin": origin,
                        "orientation_normalized": oriented_flip,
                    })
                    added_paths += 1
                    # Convert each consecutive pair into an edge_record
                    for i in range(len(chain_l) - 1):
                        src = chain_l[i]
                        tgt = chain_l[i + 1]
                        et = ""
                        if i < len(echain_l):
                            et = str(echain_l[i] or "").lower()
                        el = ""
                        if i < len(elabels_l):
                            el = elabels_l[i] or ""
                        ekey = (src, tgt, et, el)
                        if ekey in seen_edge_keys:
                            continue
                        seen_edge_keys.add(ekey)
                        edge_records.append({
                            "source_id": src,
                            "source_label": "",
                            "target_id": tgt,
                            "target_label": "",
                            "edge_type": et,
                            "edge_label": el,
                            "origin": origin,
                            "from_tool": tool,
                            "from_path": True,
                        })
                        added_edges += 1

        packet_provenance.append({
            "assign_to": var_name,
            "tool": tool,
            "added_nodes": added_nodes,
            "added_edges": added_edges,
            "added_paths": added_paths,
        })

    # Carry declared authority onto every record, in one pass.
    #
    # `claim_kind` was reachable only through the "ADJUDICATES:" prefix that
    # construction wrote into `text_content`, so any consumer that had not paged
    # in the payload — or that saw a reformatted one — could not tell a rule from
    # a paragraph. The column is the field; this is what makes retrieval read it.
    # An older graph has no column and returns '', which `normative.classify`
    # resolves from the legacy prefix exactly as before.
    _kind_ids = [n["id"] for n in node_records if n.get("id")]
    if _kind_ids:
        for nid in _kind_ids:
            try:
                rows = list(conn.execute(
                    "MATCH (c:Concept {id: $id}) "
                    "RETURN c.kind, c.claim_kind, c.claim_kind_source", {"id": nid}
                ))
            except Exception:
                try:
                    rows = [
                        ("", row[0], row[1])
                        for row in conn.execute(
                            "MATCH (c:Concept {id: $id}) "
                            "RETURN c.claim_kind, c.claim_kind_source",
                            {"id": nid},
                        )
                    ]
                except Exception:
                    continue
            if not rows:
                continue
            format_kind = rows[0][0] or ""
            kind, kind_source = rows[0][1] or "", rows[0][2] or ""
            for n in node_records:
                if n["id"] == nid:
                    n["kind"] = str(format_kind)
                    n["claim_kind"] = str(kind)
                    n["claim_kind_source"] = str(kind_source)

    # Back-fill missing node labels via one lookup pass.
    missing_label_ids = [n["id"] for n in node_records if not n.get("label")]
    if missing_label_ids:
        for nid in missing_label_ids:
            try:
                rows = list(conn.execute(
                    "MATCH (c:Concept {id: $id}) RETURN c.label", {"id": nid}
                ))
                if rows:
                    for n in node_records:
                        if n["id"] == nid:
                            n["label"] = rows[0][0] or ""
            except Exception:
                continue

    # Ensure every node referenced by an edge is in node_records.
    for e in edge_records:
        for key_id, key_label in (
            ("source_id", "source_label"),
            ("target_id", "target_label"),
        ):
            nid = e.get(key_id, "")
            if not nid or nid in seen_node_ids:
                continue
            seen_node_ids.add(nid)
            node_records.append({
                "id": nid,
                "label": e.get(key_label, ""),
                "origin": e.get("origin", "direct_path"),
            })

    packet = {
        "node_records": node_records,
        "edge_records": edge_records,
        "path_records": path_records,
        "structural_facts": {},
        "packet_provenance": packet_provenance,
        "append_log": [{
            "phase": "initial",
            "round": 0,
            "reason": "backend_execute",
            "added_nodes": len(node_records),
            "added_edges": len(edge_records),
            "added_paths": len(path_records),
        }],
        "degradation_flags": degradation_flags,
    }
    return annotate_source_unit_coverage(conn, packet)


def append_to_evidence_packet(
    packet: dict,
    new_nodes: list[dict],
    new_edges: list[dict] | None = None,
    new_paths: list[dict] | None = None,
    *,
    phase: str = "recovery",
    round_index: int = 0,
    reason: str = "",
) -> dict:
    """Append-only extension of an EvidencePacket. Never removes records."""
    packet = dict(packet or {})
    existing_nodes: list[dict] = list(packet.get("node_records") or [])
    existing_edges: list[dict] = list(packet.get("edge_records") or [])
    existing_paths: list[dict] = list(packet.get("path_records") or [])

    node_ids = {n.get("id") for n in existing_nodes}
    edge_keys = {
        (e.get("source_id"), e.get("target_id"), e.get("edge_type"), e.get("edge_label"))
        for e in existing_edges
    }
    path_keys = {tuple(p.get("node_chain") or []) for p in existing_paths}

    added_nodes = 0
    added_edges = 0
    added_paths = 0

    for n in (new_nodes or []):
        if not isinstance(n, dict):
            continue
        nid = n.get("id", "")
        if not nid or nid in node_ids:
            continue
        existing_nodes.append(n)
        node_ids.add(nid)
        added_nodes += 1

    for e in (new_edges or []):
        if not isinstance(e, dict):
            continue
        key = (e.get("source_id"), e.get("target_id"), e.get("edge_type"), e.get("edge_label"))
        if key in edge_keys:
            continue
        existing_edges.append(e)
        edge_keys.add(key)
        added_edges += 1

    for p in (new_paths or []):
        if not isinstance(p, dict):
            continue
        key = tuple(p.get("node_chain") or [])
        if not key or key in path_keys:
            continue
        existing_paths.append(p)
        path_keys.add(key)
        added_paths += 1

    packet["node_records"] = existing_nodes
    packet["edge_records"] = existing_edges
    packet["path_records"] = existing_paths
    append_log = list(packet.get("append_log") or [])
    append_log.append({
        "phase": phase,
        "round": round_index,
        "reason": reason,
        "added_nodes": added_nodes,
        "added_edges": added_edges,
        "added_paths": added_paths,
    })
    packet["append_log"] = append_log
    # Recompute rather than carry forward: an append can complete a unit that
    # was partial, and a stale finding is worse than none.
    return annotate_source_unit_coverage(None, packet)


def source_unit_coverage(
    unit_index: dict[str, list[str]], packet_node_ids: set[str]
) -> list[dict]:
    """Which source units the packet holds only part of.

    Fine grain is a legitimate authoring choice, but it makes partial retrieval
    invisible: a caller can receive three nodes of a fifteen-node module
    interface and nothing in the packet says the other twelve exist. Because
    every node carries the units it came from, this is a set operation with a
    decidable answer, so it belongs in the deterministic layer rather than in a
    tier's judgement about whether it has "enough".

    Reported, not repaired. Completing the unit would be a retrieval decision
    with its own cost, and inventing one here would silently overrule the
    Planner's program. Naming the absence is the honest half and the half that
    can be acted on.
    """

    partial: list[dict] = []
    for unit_id, node_ids in unit_index.items():
        present = [nid for nid in node_ids if nid in packet_node_ids]
        if not present or len(present) == len(node_ids):
            continue
        partial.append({
            "source_unit_id": unit_id,
            "nodes_in_packet": len(present),
            "nodes_in_graph": len(node_ids),
            "missing_node_ids": [nid for nid in node_ids if nid not in packet_node_ids],
        })
    # Worst-covered first: the unit the packet is furthest from holding whole.
    partial.sort(key=lambda p: (p["nodes_in_packet"] / p["nodes_in_graph"], -p["nodes_in_graph"]))
    return partial


def annotate_source_unit_coverage(conn: "lb.Connection | None", packet: dict) -> dict:
    """Attach source-unit completeness to a packet. Mutates and returns it.

    Called after initial assembly and after every append, because a recovery
    round that adds nodes can complete a unit that was partial.

    `conn` may be None on the append path, where only the index cached during
    assembly is available. An unavailable index leaves any existing annotation
    untouched rather than overwriting it with "no attribution" — recovery must
    not be able to erase a partial-unit finding.
    """

    try:
        from engine import get_source_unit_index

        unit_index = get_source_unit_index(conn)
    except Exception:
        return packet
    if not unit_index:
        packet.setdefault("source_unit_attribution", False)
        packet.setdefault("source_unit_coverage", [])
        return packet
    packet["source_unit_attribution"] = True
    node_ids = {
        str(n.get("id", ""))
        for n in (packet.get("node_records") or [])
        if isinstance(n, dict) and n.get("id")
    }
    packet["source_unit_coverage"] = source_unit_coverage(unit_index, node_ids)
    return packet


def verify_packet_integrity(packet: dict) -> dict:
    """Pure deterministic check: every edge_record references nodes in node_records."""
    node_ids = {n.get("id") for n in (packet.get("node_records") or []) if isinstance(n, dict)}
    violations: list[dict] = []
    for e in (packet.get("edge_records") or []):
        if not isinstance(e, dict):
            continue
        for k in ("source_id", "target_id"):
            nid = e.get(k, "")
            if nid and nid not in node_ids:
                violations.append({"edge": e, "missing": k, "missing_id": nid})
    # Path endpoints must also exist
    for p in (packet.get("path_records") or []):
        if not isinstance(p, dict):
            continue
        for nid in (p.get("node_chain") or []):
            if nid and nid not in node_ids:
                violations.append({"path": p, "missing": "node_chain", "missing_id": nid})
    return {
        "valid": not violations,
        "violations": violations,
        "node_count": len(node_ids),
        "edge_count": len(packet.get("edge_records") or []),
        "path_count": len(packet.get("path_records") or []),
    }


# ---------------------------------------------------------------------------
# Frontier clustering
# ---------------------------------------------------------------------------

def cluster_frontier(candidate_set: list[dict], conn: "lb.Connection") -> list[dict]:
    """Group frontier nodes into clusters by connectivity (BFS connected components)."""
    if not candidate_set:
        return []

    node_ids = [c["id"] for c in candidate_set]
    node_set = set(node_ids)

    adj: dict[str, set[str]] = defaultdict(set)
    rel_names = ["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]

    for nid in node_ids:
        for rel in rel_names:
            for r in conn.execute(
                f"MATCH (a:Concept {{id: $id}})-[:{rel}]->(b:Concept) RETURN b.id",
                {"id": nid},
            ):
                if r[0] in node_set:
                    adj[nid].add(r[0])
                    adj[r[0]].add(nid)

            for r in conn.execute(
                f"MATCH (a:Concept {{id: $id}})<-[:{rel}]-(b:Concept) RETURN b.id",
                {"id": nid},
            ):
                if r[0] in node_set:
                    adj[nid].add(r[0])
                    adj[r[0]].add(nid)

    visited: set[str] = set()
    clusters: list[dict] = []

    for nid in node_ids:
        if nid in visited:
            continue
        component: list[str] = []
        queue = deque([nid])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for nb in adj.get(current, set()):
                if nb not in visited:
                    queue.append(nb)

        clusters.append({
            "cluster_id": f"cluster_{len(clusters) + 1}",
            "node_ids": component,
            "size": len(component),
        })

    return clusters


# ---------------------------------------------------------------------------
# Company-spec local recovery dispatch (v5)
# ---------------------------------------------------------------------------

def execute_company_recovery(
    conn: "lb.Connection",
    structural_index: dict[str, StructuralFacts],
    recovery_spec: dict,
) -> list[dict]:
    """Execute a Company-issued local recovery spec synchronously.

    Supports targeted_extension and targeted_reseed types.
    Returns new candidate nodes (not yet merged with existing set).
    Origin is always 'alternative' so downstream code can distinguish.
    """
    spec_type = recovery_spec.get("type", "")

    if spec_type == "targeted_extension":
        # Support both single "extend_from" (legacy) and multi-source "extend_from_ids".
        extend_from_ids: list[str] = recovery_spec.get("extend_from_ids") or []
        if not extend_from_ids and recovery_spec.get("extend_from"):
            extend_from_ids = [recovery_spec["extend_from"]]
        edge_type = recovery_spec.get("edge_type", "LEADSTO").lower()
        direction = recovery_spec.get("direction", "forward")
        hops = int(recovery_spec.get("hops", 1))
        hops = max(1, min(3, hops))

        if not extend_from_ids:
            return []

        hop_limits = {edge_type: {}}
        if direction == "forward":
            hop_limits[edge_type]["forward"] = hops
        else:
            hop_limits[edge_type]["backward"] = hops

        raw = execute_tool(conn, "hop_expansion", {
            "seeds": extend_from_ids,
            "hop_limits": hop_limits,
        }, structural_index)
        for r in raw:
            r["origin"] = "alternative"
        return raw

    elif spec_type == "targeted_reseed":
        search_for = recovery_spec.get("search_for", "")
        connect_to = recovery_spec.get("connect_to", "")
        max_hops = int(recovery_spec.get("max_hops", 2))
        max_hops = max(2, min(4, max_hops))

        if not search_for:
            return []

        seeds = execute_tool(conn, "vector_search", {
            "query": search_for,
            "k": 3,
        }, structural_index)

        if not seeds or not connect_to:
            for r in seeds:
                r["origin"] = "alternative"
            return seeds

        path_results = execute_tool(conn, "find_paths", {
            "source_set": [s.get("id", "") for s in seeds if isinstance(s, dict) and s.get("id")],
            "target_set": [connect_to],
            "max_hops": max_hops,
        }, structural_index)

        for r in path_results:
            r["origin"] = "alternative"
        return path_results if path_results else [dict(s, origin="alternative") for s in seeds]

    elif spec_type == "bridging":
        source_set = recovery_spec.get("source_ids", [])
        target_set = recovery_spec.get("target_ids", [])
        max_hops = int(recovery_spec.get("max_hops", 4))
        
        if not source_set or not target_set:
            return []
            
        print(f"  [Backend] Executing Company bridging: {len(source_set)} sources -> {len(target_set)} targets")
        path_results = execute_tool(conn, "find_paths", {
            "source_set": source_set,
            "target_set": target_set,
            "max_hops": max_hops,
        }, structural_index)
        
        for r in path_results:
            r["origin"] = "alternative"
        return path_results

    return []
