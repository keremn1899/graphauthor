"""Four deterministic graph operations. No LLM. No authority.

Every host may call lookup, expand, path, and search. They compile to the
existing ``retrieval-v1`` executor.

lookup is exact and terminal on a miss — it never widens to search.
search results are candidates, never a closed-world empty and never a verdict.

This is the single implementation. Both doors — the product Ask loop
(`mcp_server/ask.py`) and the MCP stdio tools (`mcp_server/stdio.py`, via
`HostRetrievalSurface`) — run this class, because when they were two copies a
repair reached one of them: `search` had been moved to semantic on the host
copy while Ask kept ranking on the lexical token filter. An AST comparison of
the copies found nine of thirteen shared methods byte-identical and all four
public operations among them, so the duplication bought nothing and cost that.

Extending it is deliberate, not incidental: `_after_execute` is the one seam,
and an affordance built for an agent host reaches Ask only if someone puts it
in this class.
"""

from __future__ import annotations

import re
from typing import Any


_EDGE_TYPES = frozenset({"leadsto", "contains", "expresses", "nearto"})
_CANDIDATE_DERIVED = "candidate-derived"
_CLOSURE_DERIVED = "closure-derived"
_NO_EVIDENCE = "no-evidence"


class Retrieve:
    """Exact lookup, typed expansion/path, and bounded candidate search."""

    def __init__(
        self,
        surface: Any,
        *,
        structured_feedback: bool = False,
        seed_resolution_feedback: bool = True,
        endpoint_resolution_feedback: bool = True,
    ):
        self._surface = surface
        self._structured_feedback = bool(structured_feedback)
        self._seed_resolution_feedback = bool(seed_resolution_feedback)
        self._endpoint_resolution_feedback = bool(endpoint_resolution_feedback)

    @staticmethod
    def capability_card() -> dict[str, Any]:
        return {
            "execution": "deterministic_zero_llm",
            "operations": ["lookup", "expand", "path", "search"],
            "edge_types": sorted(_EDGE_TYPES),
            "identity_policy": (
                "lookup is exact and terminal on miss; it never widens to search"
            ),
            "authority_policy": (
                "search results and retrieved nodes are evidence candidates, not "
                "governance judgments"
            ),
            "evidence_scope_policy": (
                "lookup, bounded expansion, and bounded path results are closure-derived "
                "for their declared bounds; search is candidate-derived and can never "
                "return terminal EMPTY"
            ),
            "content_policy": (
                "lookup pages text only when include_content=true; traversal and "
                "search default to thin packet records"
            ),
        }

    def lookup(
        self,
        references: list[str],
        *,
        include_content: bool = False,
        context_ref: str = "",
        graph_version: str = "",
    ) -> dict[str, Any]:
        """Resolve graph-native IDs/labels exactly; an empty result is terminal."""
        values = self._strings(references, "references", maximum=20)
        return self._execute(
            "lookup",
            {
                "contract_version": "retrieval-v1",
                "steps": [{
                    "tool": "exact_node_lookup",
                    "params": {"label_or_id": values},
                    "assign_to": "exact",
                }],
                "collect": "$exact",
                "limits": {"max_recovery_rounds": 0},
            },
            evidence="content" if include_content else "packet",
            context_ref=context_ref,
            graph_version=graph_version,
            exact_terminal=True,
        )

    def expand(
        self,
        node_ids: list[str],
        *,
        edge_types: list[str] | None = None,
        direction: str = "both",
        depth: int = 1,
        edge_labels: list[str] | None = None,
        include_content: bool = False,
        context_ref: str = "",
        graph_version: str = "",
    ) -> dict[str, Any]:
        """Return a bounded typed neighbourhood without implicit fallback."""
        ids = self._strings(node_ids, "node_ids", maximum=50)
        types = self._types_or_feedback(edge_types, operation="expand")
        if isinstance(types, dict):
            return types
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be outgoing, incoming, or both")
        if not 1 <= int(depth) <= 3:
            raise ValueError("depth must be between 1 and 3")
        labels = self._strings(edge_labels or [], "edge_labels", maximum=20, required=False)
        params: dict[str, Any] = {
            "node_ids": ids,
            "depth": int(depth),
            "edge_types": types,
            "direction": direction,
            "max_nodes": 300,
        }
        if labels:
            params["edge_labels"] = labels
        if self._seed_resolution_feedback:
            return self._expand_with_seed_resolution(
                ids,
                params,
                include_content=include_content,
                context_ref=context_ref,
                graph_version=graph_version,
            )
        return self._execute(
            "expand",
            {
                "contract_version": "retrieval-v1",
                "steps": [{
                    "tool": "get_neighbourhood",
                    "params": params,
                    "assign_to": "neighbourhood",
                }],
                "collect": "$neighbourhood",
                "limits": {"max_recovery_rounds": 0, "max_hops_per_step": 3},
            },
            evidence="content" if include_content else "packet",
            context_ref=context_ref,
            graph_version=graph_version,
        )

    def _expand_with_seed_resolution(
        self,
        node_ids: list[str],
        params: dict[str, Any],
        *,
        include_content: bool,
        context_ref: str,
        graph_version: str,
    ) -> dict[str, Any]:
        """Resolve stable seed IDs and expand in one version-locked program."""
        bounded_params = dict(params)
        bounded_params["node_ids"] = "$resolved_seeds"
        result = self._execute(
            "expand",
            {
                "contract_version": "retrieval-v1",
                "steps": [
                    {
                        "tool": "exact_node_lookup",
                        "params": {"label_or_id": node_ids},
                        "assign_to": "resolved_seeds",
                    },
                    {
                        "tool": "get_neighbourhood",
                        "params": bounded_params,
                        "assign_to": "neighbourhood",
                    },
                ],
                "collect": "$neighbourhood",
                "limits": {"max_recovery_rounds": 0, "max_hops_per_step": 3},
            },
            evidence="content" if include_content else "packet",
            context_ref=context_ref,
            graph_version=graph_version,
        )
        if str(result.get("kind") or "") != "RETRIEVED":
            return result

        evidence = result.get("evidence") or {}
        returned_ids = {
            str(row.get("id") or "")
            for key in ("node_records", "node_payloads")
            for row in (evidence.get(key) or [])
            if isinstance(row, dict) and str(row.get("id") or "")
        }
        exact_resolved = [node_id for node_id in node_ids if node_id in returned_ids]
        unresolved = [node_id for node_id in node_ids if node_id not in returned_ids]
        resolution = {
            "requested_node_ids": node_ids,
            "resolved_node_ids": exact_resolved,
            "unresolved_node_ids": unresolved,
            "complete": not unresolved,
        }
        if unresolved:
            result["outcome"] = "UNRESOLVED_SEED"
            result["retryable"] = False
            result["evidence_scope"] = _NO_EVIDENCE
        result["seed_resolution"] = resolution
        return result

    def path(
        self,
        source_ids: list[str],
        target_ids: list[str],
        *,
        edge_types: list[str] | None = None,
        max_hops: int = 4,
        include_content: bool = False,
        context_ref: str = "",
        graph_version: str = "",
    ) -> dict[str, Any]:
        """Find bounded existing paths between exact endpoint IDs."""
        sources = self._strings(source_ids, "source_ids", maximum=20)
        targets = self._strings(target_ids, "target_ids", maximum=20)
        types = self._types_or_feedback(edge_types, operation="path")
        if isinstance(types, dict):
            return types
        if not 1 <= int(max_hops) <= 6:
            raise ValueError("max_hops must be between 1 and 6")
        if self._endpoint_resolution_feedback:
            return self._path_with_endpoint_resolution(
                sources,
                targets,
                types,
                max_hops=int(max_hops),
                include_content=include_content,
                context_ref=context_ref,
                graph_version=graph_version,
            )
        return self._execute(
            "path",
            {
                "contract_version": "retrieval-v1",
                "steps": [{
                    "tool": "find_paths",
                    "params": {
                        "source_set": sources,
                        "target_set": targets,
                        "edge_types": types,
                        "max_hops": int(max_hops),
                    },
                    "assign_to": "paths",
                }],
                "collect": "$paths",
                "limits": {"max_recovery_rounds": 0, "max_hops_per_step": int(max_hops)},
            },
            evidence="content" if include_content else "packet",
            context_ref=context_ref,
            graph_version=graph_version,
        )

    def _path_with_endpoint_resolution(
        self,
        source_ids: list[str],
        target_ids: list[str],
        edge_types: list[str],
        *,
        max_hops: int,
        include_content: bool,
        context_ref: str,
        graph_version: str,
    ) -> dict[str, Any]:
        """Resolve endpoints and find paths in one version-locked program."""
        result = self._execute(
            "path",
            {
                "contract_version": "retrieval-v1",
                "steps": [
                    {
                        "tool": "exact_node_lookup",
                        "params": {"label_or_id": source_ids},
                        "assign_to": "resolved_sources",
                    },
                    {
                        "tool": "exact_node_lookup",
                        "params": {"label_or_id": target_ids},
                        "assign_to": "resolved_targets",
                    },
                    {
                        "tool": "find_paths",
                        "params": {
                            "source_set": "$resolved_sources",
                            "target_set": "$resolved_targets",
                            "edge_types": edge_types,
                            "max_hops": max_hops,
                        },
                        "assign_to": "paths",
                    },
                ],
                "collect": "$paths",
                "limits": {"max_recovery_rounds": 0, "max_hops_per_step": max_hops},
            },
            evidence="content" if include_content else "packet",
            context_ref=context_ref,
            graph_version=graph_version,
        )
        if str(result.get("kind") or "") != "RETRIEVED":
            return result

        evidence = result.get("evidence") or {}
        returned_ids = {
            str(row.get("id") or "")
            for key in ("node_records", "node_payloads")
            for row in (evidence.get(key) or [])
            if isinstance(row, dict) and str(row.get("id") or "")
        }
        endpoint_resolution = {
            "requested_source_ids": source_ids,
            "resolved_source_ids": [value for value in source_ids if value in returned_ids],
            "unresolved_source_ids": [value for value in source_ids if value not in returned_ids],
            "requested_target_ids": target_ids,
            "resolved_target_ids": [value for value in target_ids if value in returned_ids],
            "unresolved_target_ids": [value for value in target_ids if value not in returned_ids],
        }
        endpoint_resolution["complete"] = not (
            endpoint_resolution["unresolved_source_ids"]
            or endpoint_resolution["unresolved_target_ids"]
        )
        if not endpoint_resolution["complete"]:
            result["outcome"] = "UNRESOLVED_ENDPOINT"
            result["retryable"] = False
            result["evidence_scope"] = _NO_EVIDENCE
        result["endpoint_resolution"] = endpoint_resolution
        return result

    def search(
        self,
        query: str,
        *,
        mode: str = "semantic",
        limit: int = 8,
        include_content: bool = False,
        context_ref: str = "",
        graph_version: str = "",
    ) -> dict[str, Any]:
        """Return bounded candidate nodes; never treat similarity as authority.

        ``semantic`` is the default, matching `HostRetrievalSurface.search`.
        ``lexical`` drops tokens under three characters and ``{the, and, for}``,
        which is the same construction as the planner fail-open repaired in
        `de7b3b9` and fails the same way: on *"may the author of a change
        approve their own pull request?"* the surviving tokens rank four context
        paragraphs above the rule that answers it, while semantic returns that
        rule at position one.

        The default was changed on the host surface and not here, because the
        two classes are separate copies of one contract. A recursive diff of
        both across lookup / expand / path / search found them identical but for
        a per-call trace id — and this. That is the cost of the duplication,
        measured: a fix reached one of two doors.

        ``lexical`` stays available and is the honest choice for an identifier
        rather than a question.
        """
        query = str(query or "").strip()
        if not query:
            raise ValueError("query is required")
        if mode not in {"lexical", "semantic"}:
            raise ValueError("mode must be lexical or semantic")
        if not 1 <= int(limit) <= 25:
            raise ValueError("limit must be between 1 and 25")
        if mode == "semantic":
            import json

            db_path = getattr(self._surface, "_db_path", None)
            metadata = (
                db_path.parent / f"{db_path.name}.metadata.json"
                if db_path is not None
                else None
            )
            if metadata is not None and metadata.exists():
                try:
                    embedding_status = str(
                        json.loads(metadata.read_text(encoding="utf-8")).get(
                            "embedding_status"
                        )
                        or ""
                    )
                except (OSError, ValueError, TypeError):
                    embedding_status = ""
                if embedding_status == "NOT_BUILT":
                    stamped = self._stamp_identity(
                        context_ref=context_ref, graph_version=graph_version
                    )
                    if stamped.get("kind") in {"STALE_GRAPH", "STALE_CONTEXT"}:
                        return stamped
                    return {
                        **stamped,
                        "kind": "RETRIEVED",
                        "operation": "search",
                        "zero_llm": True,
                        "outcome": "SEARCH_UNAVAILABLE",
                        "candidate_only": True,
                        "closed": False,
                        "evidence_scope": _NO_EVIDENCE,
                        "evidence": {"node_records": []},
                        "engine_degraded": True,
                        "degradation_flags": ["semantic_embeddings_not_built"],
                        "recovery": "use lexical search or build the optional embedding index",
                    }
        if mode == "lexical":
            terms = []
            for term in re.findall(r"[A-Za-z0-9_:-]+", query):
                if len(term) >= 3 and term.lower() not in {"the", "and", "for"}:
                    terms.append(term)
                if len(terms) == 8:
                    break
            params: dict[str, Any] = {"terms": terms or [query], "k": int(limit)}
            tool = "lexical_search"
        else:
            params = {"query": query, "k": int(limit)}
            tool = "vector_search"
        out = self._execute(
            "search",
            {
                "contract_version": "retrieval-v1",
                "steps": [{
                    "tool": tool,
                    "params": params,
                    "assign_to": "candidates",
                }],
                "collect": "$candidates",
                "limits": {
                    "max_recovery_rounds": 0,
                    "max_results_per_search": int(limit),
                },
            },
            evidence="content" if include_content else "packet",
            context_ref=context_ref,
            graph_version=graph_version,
            evidence_scope=_CANDIDATE_DERIVED,
        )
        # A bounded/ranked search miss is not a closed-world EMPTY.
        if out.get("outcome") == "FOUND":
            out["outcome"] = "CANDIDATES"
        elif out.get("outcome") == "EMPTY":
            out["outcome"] = "NO_CANDIDATES"
        out["candidate_only"] = True
        return out

    def _stamp_identity(
        self, *, context_ref: str, graph_version: str
    ) -> dict[str, Any]:
        """Bind the envelope read to the same version/context the other ops use."""
        out: dict[str, Any] = {"kind": "RETRIEVED"}
        surface = self._surface
        if hasattr(surface, "_base"):
            try:
                with surface._read_guard():
                    out.update(surface._base())
                    out["compass_ref"] = surface._compass_ref()
            except Exception:
                pass
        current_version = str(out.get("graph_version") or "")
        current_ref = str(out.get("compass_ref") or "")
        if graph_version and current_version and graph_version != current_version:
            return {
                **out,
                "kind": "STALE_GRAPH",
                "provided_graph_version": graph_version,
            }
        if context_ref and current_ref and context_ref != current_ref:
            return {
                **out,
                "kind": "STALE_CONTEXT",
                "provided_compass_ref": context_ref,
            }
        return out

    def _execute(
        self,
        operation: str,
        program: dict[str, Any],
        *,
        evidence: str,
        context_ref: str,
        graph_version: str,
        exact_terminal: bool = False,
        evidence_scope: str = _CLOSURE_DERIVED,
    ) -> dict[str, Any]:
        result = self._surface.retrieve(
            program,
            evidence=evidence,
            context_ref=context_ref,
            graph_version=graph_version,
        )
        kind = str(result.get("kind") or "")
        if kind != "RETRIEVED":
            result["operation"] = operation
            result["zero_llm"] = True
            result["outcome"] = kind or "FAILED"
            result["evidence_scope"] = _NO_EVIDENCE
            return result
        receipt = result.get("execution_receipt") or {}
        count = int(receipt.get("collected_node_count") or 0)
        result["operation"] = operation
        result["zero_llm"] = True
        result["evidence_scope"] = evidence_scope
        result["outcome"] = (
            "EXACT_MISS" if exact_terminal and count == 0
            else "EMPTY" if count == 0
            else "FOUND"
        )
        self._after_execute(result, collected_node_count=count)
        return result

    def _after_execute(self, result: dict[str, Any], *, collected_node_count: int) -> None:
        """The one extension seam. The core attaches nothing.

        A subclass may annotate a successful result here — see
        `HostRetrievalSurface`, which hangs its regional navigation projection
        off this hook. Nothing on this seam may change `outcome`,
        `evidence_scope`, or the evidence itself; those are the contract, and a
        host that gained a different one would no longer be running these ops.
        """

    def _types_or_feedback(
        self,
        values: list[str] | None,
        *,
        operation: str,
    ) -> list[str] | dict[str, Any]:
        try:
            return self._types(values)
        except ValueError:
            if not self._structured_feedback:
                raise
        if isinstance(values, list):
            provided = list(
                dict.fromkeys(
                    str(value).strip().lower()
                    for value in values
                    if str(value).strip()
                )
            )
        else:
            provided = [str(values).strip().lower()] if str(values or "").strip() else []
        invalid = sorted(set(provided) - _EDGE_TYPES)
        return {
            "operation": operation,
            "zero_llm": True,
            "outcome": "INVALID_ARGUMENT",
            "error": {
                "code": "UNSUPPORTED_EDGE_TYPE",
                "provided": invalid,
                "allowed_edge_types": sorted(_EDGE_TYPES),
                "matched_edge_labels": self._matching_edge_label_types(invalid),
                "edge_labels_argument": "edge_labels",
            },
            "retryable": True,
        }

    def _matching_edge_label_types(self, labels: list[str]) -> dict[str, list[str]]:
        if not labels:
            return {}
        wanted = set(labels)
        matched: dict[str, set[str]] = {label: set() for label in labels}
        relations = (
            ("leadsto", "LEADSTO"),
            ("contains", "CONTAINS"),
            ("expresses", "EXPRESSES"),
            ("nearto", "NEARTO"),
        )
        with self._surface._read_guard():
            conn = self._surface._session.connection
            for edge_type, relation in relations:
                for row in conn.execute(
                    f"MATCH (a:Concept)-[r:{relation}]->(b:Concept) RETURN r.label"
                ):
                    label = str(row[0] or "").strip().lower()
                    if label in wanted:
                        matched[label].add(edge_type)
        return {
            label: sorted(types)
            for label, types in matched.items()
            if types
        }

    @staticmethod
    def _strings(
        values: list[str],
        name: str,
        *,
        maximum: int,
        required: bool = True,
    ) -> list[str]:
        if not isinstance(values, list):
            raise ValueError(f"{name} must be a list")
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if required and not cleaned:
            raise ValueError(f"{name} must not be empty")
        if len(cleaned) > maximum:
            raise ValueError(f"{name} accepts at most {maximum} values")
        return list(dict.fromkeys(cleaned))

    @staticmethod
    def _types(values: list[str] | None) -> list[str]:
        if values is None:
            return sorted(_EDGE_TYPES)
        if not isinstance(values, list):
            raise ValueError("edge_types must be a list")
        cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
        invalid = sorted(set(cleaned) - _EDGE_TYPES)
        if invalid:
            raise ValueError("unsupported edge types: " + ", ".join(invalid))
        return list(dict.fromkeys(cleaned)) or sorted(_EDGE_TYPES)
