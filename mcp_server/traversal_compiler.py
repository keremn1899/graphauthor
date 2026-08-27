"""Deterministic graph.md named-traversal compiler.

Named recipes are user-owned semantic procedures. The harness lowers their
bounded graph operations to the existing retrieval-v1 execution IR; no prompt
or model participates in compilation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from mcp_server.graph_contract import (
    GraphContractDocument,
    GraphContractError,
    _RECIPE_OPS,
    kind_id_prefix,
    lower_predicates,
    node_id_matches_kind,
    unknown_step_keys,
)
from mcp_server.graph_contract import _RECIPE_OP_KEYS
from retrieval_program import CanonicalRetrievalProgram


class TraversalCompileError(ValueError):
    """A named recipe or invocation cannot be lowered safely."""


@dataclass(frozen=True)
class CompiledTraversal:
    name: str
    version: int
    fingerprint: str
    format_fingerprint: str
    parameters: dict[str, Any]
    program: CanonicalRetrievalProgram
    project: dict[str, Any] = field(default_factory=dict)
    #: Variables that carry the answer; empty means "the packet is the answer".
    answers: tuple[str, ...] = ()

    @property
    def program_set_fingerprint(self) -> str:
        """Neutral name for the legacy ``format_fingerprint`` receipt field."""
        return self.format_fingerprint


def _canonical_hash(value: Any, *, prefix: str) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"{prefix}{hashlib.sha256(encoded).hexdigest()[:16]}"


def _bind(value: Any, parameters: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name in parameters:
            return parameters[name]
        return value
    if isinstance(value, list):
        return [_bind(item, parameters) for item in value]
    if isinstance(value, dict):
        return {key: _bind(item, parameters) for key, item in value.items()}
    return value


def _validate_parameters(
    document: GraphContractDocument,
    recipe_name: str,
    supplied: dict[str, Any],
) -> dict[str, Any]:
    recipe = document.specification.traversals[recipe_name]
    unknown = sorted(set(supplied) - set(recipe.parameters))
    if unknown:
        raise TraversalCompileError(f"unknown traversal parameter(s): {unknown}")
    canonical: dict[str, Any] = {}
    for name, parameter in sorted(recipe.parameters.items()):
        if name not in supplied:
            if parameter.required:
                raise TraversalCompileError(
                    f"missing required traversal parameter {name!r}"
                )
            continue
        value = supplied[name]
        if parameter.type == "node_id":
            if not isinstance(value, str) or not value.strip():
                raise TraversalCompileError(
                    f"parameter {name!r} must be a non-empty node id"
                )
            value = value.strip()
            if parameter.kinds and not any(
                node_id_matches_kind(value, kind, document.specification)
                for kind in parameter.kinds
            ):
                raise TraversalCompileError(
                    f"parameter {name!r} does not match any allowed kind "
                    f"{parameter.kinds}"
                )
        canonical[name] = value
    return canonical


def _direction(value: Any) -> str:
    direction = str(value or "both").strip().lower()
    if direction not in {"outgoing", "incoming", "both"}:
        raise TraversalCompileError(
            "traversal direction must be outgoing, incoming, or both"
        )
    return direction


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _normalize_project(raw: dict[str, Any] | None) -> dict[str, Any]:
    spec = dict(raw or {})
    if not spec:
        return {}
    allowed = {
        "nodes": {"ids", "summary", "full"},
        "edges": {"none", "full"},
        "paths": {"none", "full"},
        "content": {"none", "terminal_only", "full"},
        "structural_facts": {"none", "full"},
    }
    canonical: dict[str, Any] = {}
    for key, choices in allowed.items():
        if key not in spec:
            continue
        value = str(spec.get(key) or "").strip().lower()
        if value not in choices:
            raise TraversalCompileError(
                f"project.{key} must be one of {sorted(choices)}"
            )
        canonical[key] = value
    unknown = sorted(set(spec) - set(allowed))
    if unknown:
        raise TraversalCompileError(f"unknown project field(s): {unknown}")
    return canonical


def _kind_filter_params(
    bound: dict[str, Any], document: GraphContractDocument
) -> dict[str, Any]:
    kinds = _string_list(bound.get("kinds"))
    properties = bound.get("properties") if isinstance(bound.get("properties"), dict) else {}
    unknown = sorted(
        str(key)
        for key in properties
        if str(key) not in {"kind", "claim_kind", "is_metanode"}
    )
    if unknown:
        raise TraversalCompileError(f"unsupported property filter(s): {unknown}")
    params: dict[str, Any] = {}
    if kinds:
        params["kinds"] = kinds
        params["kind_prefixes"] = [
            prefix
            for prefix in (
                kind_id_prefix(kind, document.specification) for kind in kinds
            )
            if prefix
        ]
    if properties:
        params["properties"] = properties
    return params


def _predicate_filters(
    bound: dict[str, Any], document: GraphContractDocument
) -> tuple[list[str], list[str]]:
    edge_types = [
        str(value).strip().lower()
        for value in (bound.get("sst_types") or [])
        if str(value).strip()
    ]
    edge_labels: list[str] = []
    predicates = _string_list(bound.get("predicates"))
    if predicates:
        try:
            derived_types, edge_labels = lower_predicates(
                predicates, document.specification
            )
        except GraphContractError as exc:
            raise TraversalCompileError(str(exc)) from exc
        edge_types = sorted(set(edge_types) | set(derived_types))
    return edge_types, edge_labels


#: Keys an op used to read and deliberately no longer does. Separate from
#: unknown keys so a withdrawal does not report itself as a typo.
_WITHDRAWN_STEP_KEYS: dict[str, dict[str, str]] = {
    "select_landmarks": {
        "roles": (
            "the structural-role taxonomy is computed but not served in this "
            "version. select_landmarks returns the format's pinned nodes "
            "ranked by betweenness."
        ),
    },
}


def _compile_step(
    step: dict[str, Any],
    document: GraphContractDocument,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    bound = _bind(step, parameters)
    op = str(bound.get("op") or "").strip()
    assign = str(bound.get("assign") or "").strip()
    if not assign:
        raise TraversalCompileError(f"{op!r} step requires assign")
    # A key the op does not read used to be dropped in silence, so a guess at
    # the vocabulary and a real empty answer produced the same output.
    withdrawn = _WITHDRAWN_STEP_KEYS.get(op, {})
    for key, reason in withdrawn.items():
        if bound.get(key) is not None:
            raise TraversalCompileError(f"{op} no longer takes {key}: {reason}")

    stray = unknown_step_keys(bound)
    if stray:
        raise TraversalCompileError(
            f"{op} step has unknown key(s) {stray}; it reads "
            f"{sorted(_RECIPE_OP_KEYS.get(op, set()))}"
        )

    if op == "lookup":
        references = bound.get("references") or []
        if not isinstance(references, list):
            references = [references]
        return {
            "tool": "exact_node_lookup",
            "params": {"label_or_id": references},
            "assign_to": assign,
        }

    if op == "search":
        query = str(bound.get("query") or "").strip()
        if not query:
            raise TraversalCompileError("search step requires query")
        terms = [
            term
            for term in re.findall(r"[A-Za-z0-9_:-]+", query)
            if len(term) >= 3 and term.lower() not in {"the", "and", "for"}
        ][:8]
        return {
            "tool": "lexical_search",
            "params": {
                "terms": terms or [query],
                "k": int(bound.get("limit") or bound.get("k") or 8),
            },
            "assign_to": assign,
        }

    if op in {"traverse", "expand"}:
        strategy = str(bound.get("strategy") or "bfs").strip().lower()
        if strategy not in {"bfs", "dfs"}:
            raise TraversalCompileError(
                f"{op} strategy {strategy!r} is unsupported; use bfs or dfs"
            )
        edge_types, edge_labels = _predicate_filters(bound, document)
        depth = int(bound.get("depth") or bound.get("max_depth") or 1)
        params: dict[str, Any] = {
            "node_ids": bound.get("from"),
            "edge_types": edge_types,
            "direction": _direction(bound.get("direction")),
            "depth": depth,
            "max_nodes": int(bound.get("max_nodes") or 300),
            "strategy": strategy,
        }
        if edge_labels:
            params["edge_labels"] = edge_labels
        params.update(_kind_filter_params(bound, document))
        return {
            "tool": "get_neighbourhood",
            "params": params,
            "assign_to": assign,
        }

    if op in {"shortest_path", "find_paths"}:
        edge_types, _ = _predicate_filters(bound, document)
        return {
            "tool": "find_paths",
            "params": {
                "source_set": bound.get("from") or bound.get("source"),
                "target_set": bound.get("to") or bound.get("target"),
                "edge_types": edge_types,
                "max_hops": int(bound.get("max_hops") or 4),
                "direction": _direction(bound.get("direction") or "outgoing"),
                "exclude_labels": [
                    str(v) for v in (bound.get("excluding") or []) if str(v)
                ],
            },
            "assign_to": assign,
        }

    if op == "select_landmarks":
        # The structural-role taxonomy (causal_origin, causal_nexus,
        # associative_hub, inter_region_bridge, orphan, weakly_connected,
        # causal_terminal) is NOT served in v1.
        #
        # It works -- roles=[inter_region_bridge] returns the bridge -- but
        # "works" is not the same as "is finished". The taxonomy is a
        # betweenness-threshold heuristic that has never been validated
        # against what a reader would call a bridge, no shipped format's
        # recipes use it, and a role name in an agent-facing vocabulary is a
        # promise about meaning. Serving an unvalidated one invites programs
        # to be written against a classification we may change.
        #
        # The computation stays (engine.compute_structural_index), `orient`
        # still reports role populations, and tools.select_landmarks still
        # accepts `roles` for internal callers. Only the served door is shut,
        # and refusing loudly beats silently ignoring the argument.
        include_pinned = bound.get("include_pinned")
        if include_pinned is None:
            include_pinned = True
        return {
            "tool": "select_landmarks",
            "params": {
                "pinned": list(document.specification.orientation.pinned_nodes),
                "include_pinned": bool(include_pinned),
                "limit": int(bound.get("limit") or 8),
            },
            "assign_to": assign,
        }

    if op == "walk_sequence":
        if bound.get("from") is None:
            raise TraversalCompileError("walk_sequence step requires from")
        cycle = str(bound.get("cycle") or "simple").strip().lower()
        if cycle not in {"simple", "reject"}:
            raise TraversalCompileError(
                "walk_sequence cycle policy must be simple or reject"
            )
        predicates = _string_list(bound.get("predicates"))
        sst_types = [
            str(value).strip().lower()
            for value in (bound.get("sst_types") or [])
            if str(value).strip()
        ]
        hops: list[dict[str, Any]] = []
        direction = _direction(bound.get("direction") or "outgoing")
        if predicates:
            for predicate in predicates:
                try:
                    derived_types, labels = lower_predicates(
                        [predicate], document.specification
                    )
                except GraphContractError as exc:
                    raise TraversalCompileError(str(exc)) from exc
                hops.append(
                    {
                        "edge_types": derived_types,
                        "edge_labels": labels,
                        "direction": direction,
                    }
                )
        elif sst_types:
            for sst_type in sst_types:
                hops.append(
                    {
                        "edge_types": [sst_type],
                        "direction": direction,
                    }
                )
        else:
            raise TraversalCompileError(
                "walk_sequence requires predicates or sst_types"
            )
        max_hops = int(bound.get("max_hops") or len(hops) or 4)
        if len(hops) > max_hops:
            raise TraversalCompileError(
                "walk_sequence exceeds max_hops"
            )
        params = {
            "node_ids": bound.get("from"),
            "hops": hops,
            "max_nodes": int(bound.get("max_nodes") or 300),
        }
        params.update(_kind_filter_params(bound, document))
        return {
            "tool": "walk_sequence",
            "params": params,
            "assign_to": assign,
        }

    if op == "filter":
        source = bound.get("of") if bound.get("of") is not None else bound.get("from")
        if source is None:
            raise TraversalCompileError("filter step requires of")
        params = {"node_ids": source}
        params.update(_kind_filter_params(bound, document))
        return {
            "tool": "filter_nodes",
            "params": params,
            "assign_to": assign,
        }

    if op == "sort":
        by = str(bound.get("by") or "id").strip().lower()
        if by not in {"id", "label"}:
            raise TraversalCompileError("sort by must be id or label")
        order = str(bound.get("order") or "asc").strip().lower()
        if order not in {"asc", "desc"}:
            raise TraversalCompileError("sort order must be asc or desc")
        source = bound.get("of") if bound.get("of") is not None else bound.get("from")
        return {
            "tool": "sort_nodes",
            "params": {
                "node_ids": source,
                "by": by,
                "order": order,
            },
            "assign_to": assign,
        }

    if op == "limit":
        source = bound.get("of") if bound.get("of") is not None else bound.get("from")
        return {
            "tool": "limit_nodes",
            "params": {
                "node_ids": source,
                "limit": int(bound.get("limit") or bound.get("k") or bound.get("n") or 8),
            },
            "assign_to": assign,
        }

    if op in {"union", "difference", "intersection"}:
        left = bound.get("of")
        if left is None:
            left = bound.get("left") or bound.get("from")
        if left is None:
            raise TraversalCompileError(f"{op} step requires of")
        params: dict[str, Any] = {"op": op, "of": left}
        if op == "difference":
            minus = bound.get("minus")
            if minus is None:
                minus = bound.get("right")
            if minus is None:
                raise TraversalCompileError("difference step requires minus")
            params["minus"] = minus
        elif op == "intersection":
            right = bound.get("with")
            if right is None:
                right = bound.get("right")
            if right is None:
                raise TraversalCompileError("intersection step requires with")
            params["with"] = right
        elif op == "union":
            # Two spellings, and only one of them used to arrive. A union
            # written `of: [$a, $b]` works -- the executor flattens the list.
            # A union written `of: $a` with `with: $b` compiled, executed, and
            # returned $a: the second operand was never put in the params at
            # all. Measured on a real graph as the union of two places' casts,
            # eight characters and three, answering eight -- a plausible
            # number, and wrong, with nothing marking it wrong.
            right = bound.get("with")
            if right is None:
                right = bound.get("right")
            if right is not None:
                params["with"] = right
            elif not isinstance(left, list):
                # A union of one set is a no-op, so it is an authoring slip
                # rather than a request. Refusing it is what makes the silent
                # case above impossible to write again.
                raise TraversalCompileError(
                    "union step requires with, or a list of operands in of"
                )
        return {
            "tool": "set_algebra",
            "params": params,
            "assign_to": assign,
        }

    if op == "project":
        source = bound.get("of") if bound.get("of") is not None else bound.get("from")
        return {
            "tool": "filter_nodes",
            "params": {"node_ids": source},
            "assign_to": assign,
        }

    raise TraversalCompileError(
        f"recipe op {op!r} is declared but not executable in traversal-v1"
    )


def compile_named_traversal(
    document: GraphContractDocument,
    name: str,
    parameters: dict[str, Any] | None = None,
    *,
    version: int | None = None,
) -> CompiledTraversal:
    recipe_name = str(name or "").strip()
    recipe = document.specification.traversals.get(recipe_name)
    if recipe is None:
        raise TraversalCompileError(f"unknown named traversal {recipe_name!r}")
    if version is not None and int(version) != recipe.version:
        raise TraversalCompileError(
            f"traversal {recipe_name!r} is version {recipe.version}, "
            f"not requested version {version}"
        )
    canonical_parameters = _validate_parameters(
        document, recipe_name, dict(parameters or {})
    )
    steps = [
        _compile_step(step, document, canonical_parameters)
        for step in recipe.steps
    ]
    fallback_steps = [
        _compile_step(step, document, canonical_parameters)
        for step in recipe.then
    ]
    limits = {
        "max_steps": int(
            recipe.limits.get("max_steps") or (len(steps) + len(fallback_steps))
        ),
        "max_hops_per_step": int(recipe.limits.get("max_hops") or 4),
        "max_nodes_per_step": int(recipe.limits.get("max_nodes") or 300),
        "max_recovery_rounds": 0,
    }
    program = CanonicalRetrievalProgram.model_validate(
        {
            "contract_version": "retrieval-v1",
            "author": "contract_lowering",
            "steps": steps,
            "collect": recipe.collect,
            "contingency": {
                "trigger": recipe.when,
                "fallback_steps": fallback_steps,
                "fallback_collect": recipe.then_collect or recipe.collect,
            }
            if fallback_steps
            else {},
            "limits": limits,
        }
    )
    recipe_payload = {
        "format_fingerprint": document.fingerprint,
        "name": recipe_name,
        "recipe": recipe.model_dump(mode="json"),
    }
    project = _normalize_project(recipe.project)
    for step in recipe.steps + recipe.then:
        if str(step.get("op") or "").strip() != "project":
            continue
        merged = dict(project)
        for key in ("nodes", "edges", "paths", "content", "structural_facts"):
            if key in step and key not in recipe.project:
                merged[key] = step[key]
        project = _normalize_project(merged)
    return CompiledTraversal(
        name=recipe_name,
        version=recipe.version,
        fingerprint=_canonical_hash(recipe_payload, prefix="trv_"),
        format_fingerprint=document.fingerprint,
        parameters=canonical_parameters,
        program=program,
        project=project,
        answers=tuple(name.lstrip("$") for name in recipe.answers),
    )


def compile_ephemeral_traversal(
    document: GraphContractDocument,
    program: dict[str, Any],
    parameters: dict[str, Any] | None = None,
) -> CompiledTraversal:
    """Lower a one-shot recipe-op program with the same IR as a named traversal.

    The program is not written to graph.md. Recurring programs should be
    copied into the format as a named recipe.
    """

    spec = dict(program or {})
    steps_raw = spec.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise TraversalCompileError("ephemeral traversal requires a non-empty steps list")
    collect = str(spec.get("collect") or "").strip()
    if not collect:
        raise TraversalCompileError("ephemeral traversal requires collect")
    canonical_parameters = dict(parameters or {})
    compiled_steps = []
    for step in steps_raw:
        if not isinstance(step, dict):
            raise TraversalCompileError("ephemeral steps must be objects")
        op = str(step.get("op") or "").strip()
        if op not in _RECIPE_OPS:
            raise TraversalCompileError(
                f"ephemeral op {op!r} is not a named-traversal primitive"
            )
        compiled_steps.append(_compile_step(step, document, canonical_parameters))
    then_raw = spec.get("then") or []
    if then_raw and not isinstance(then_raw, list):
        raise TraversalCompileError("ephemeral then must be a list of steps")
    fallback_steps = []
    for step in then_raw:
        if not isinstance(step, dict):
            raise TraversalCompileError("ephemeral then steps must be objects")
        op = str(step.get("op") or "").strip()
        if op not in _RECIPE_OPS:
            raise TraversalCompileError(
                f"ephemeral op {op!r} is not a named-traversal primitive"
            )
        fallback_steps.append(_compile_step(step, document, canonical_parameters))
    raw_limits = spec.get("limits") or {}
    if raw_limits and not isinstance(raw_limits, dict):
        raise TraversalCompileError("ephemeral limits must be an object")
    limits = {
        "max_steps": min(
            max(int(raw_limits.get("max_steps") or len(compiled_steps) + len(fallback_steps)), 1),
            12,
        ),
        "max_hops_per_step": min(max(int(raw_limits.get("max_hops") or 4), 1), 64),
        "max_nodes_per_step": min(max(int(raw_limits.get("max_nodes") or 300), 1), 3000),
        "max_recovery_rounds": 0,
    }
    retrieval_program = CanonicalRetrievalProgram.model_validate(
        {
            "contract_version": "retrieval-v1",
            "author": "direct",
            "steps": compiled_steps,
            "collect": collect,
            "contingency": {
                "trigger": str(spec.get("when") or ""),
                "fallback_steps": fallback_steps,
                "fallback_collect": str(spec.get("then_collect") or collect),
            }
            if fallback_steps
            else {},
            "limits": limits,
        }
    )
    project = _normalize_project(spec.get("project") if isinstance(spec.get("project"), dict) else {})
    name = str(spec.get("name") or "ephemeral").strip() or "ephemeral"
    # A receipt names the program that produced it. An ephemeral run borrowing a
    # declared recipe's name would read as that recipe in Review while carrying
    # a different fingerprint and no version, so refuse the collision here
    # rather than leave a reader to notice the tep_ prefix.
    if name in document.specification.traversals:
        raise TraversalCompileError(
            f"ephemeral traversal cannot reuse the declared recipe name {name!r}; "
            "run it with run_traversal, or give the one-shot program its own name"
        )
    # `answers` is what decides EMPTY against FOUND, so an ephemeral program
    # that could not declare it did not execute under the semantics its named
    # twin executes under. Measured on one graph: the same five steps reported
    # EMPTY as a recipe and FOUND as a one-shot program, over an identical
    # six-node packet with no bridges in it.
    answers_raw = spec.get("answers") or []
    if answers_raw and not isinstance(answers_raw, list):
        raise TraversalCompileError("ephemeral answers must be a list of variables")
    assigned = {
        str(step.get("assign_to") or "").lstrip("$")
        for step in compiled_steps + fallback_steps
    }
    answers: list[str] = []
    for entry in answers_raw:
        variable = str(entry or "").lstrip("$").strip()
        if not variable:
            raise TraversalCompileError("ephemeral answers must name variables")
        if variable not in assigned:
            raise TraversalCompileError(
                f"ephemeral traversal declares answer {variable!r} that no step assigns"
            )
        if variable not in answers:
            answers.append(variable)
    payload = {
        "format_fingerprint": document.fingerprint,
        "kind": "ephemeral",
        "program": spec,
        "parameters": canonical_parameters,
    }
    return CompiledTraversal(
        name=name,
        version=0,
        fingerprint=_canonical_hash(payload, prefix="tep_"),
        format_fingerprint=document.fingerprint,
        parameters=canonical_parameters,
        program=retrieval_program,
        project=project,
        answers=tuple(answers),
    )


def traversal_cache_key(
    *,
    graph_version: str,
    compiled: CompiledTraversal,
    evidence: str,
) -> str:
    """Identity of one named-traversal result. Packet contents must not change
    for the same key; elapsed time may."""
    return _canonical_hash(
        {
            "graph_version": graph_version,
            "recipe_fingerprint": compiled.fingerprint,
            "format_fingerprint": compiled.format_fingerprint,
            "parameters": compiled.parameters,
            "evidence": evidence,
            "primitive_contract_version": "retrieval-v1",
        },
        prefix="tck_",
    )


def _step_estimate(step: Any) -> dict[str, Any]:
    params = dict(step.params or {})
    max_nodes = int(params.get("max_nodes") or 0)
    depth = int(params.get("depth") or params.get("max_hops") or 0)
    return {
        "assign": step.assign_to,
        "tool": step.tool,
        "params": params,
        "estimated_max_nodes": max_nodes or None,
        "estimated_depth": depth or None,
        "predicates": list(params.get("edge_labels") or []),
        "sst_types": list(params.get("edge_types") or []),
    }


def explain_compiled_traversal(compiled: CompiledTraversal) -> dict[str, Any]:
    """Compiled execution and estimated costs. Does not touch the graph."""
    program = compiled.program
    steps = [_step_estimate(step) for step in program.steps]
    fallback = [_step_estimate(step) for step in program.contingency.fallback_steps]
    return {
        "recipe_name": compiled.name,
        "recipe_version": compiled.version,
        "recipe_fingerprint": compiled.fingerprint,
        "format_fingerprint": compiled.format_fingerprint,
        "canonical_parameters": compiled.parameters,
        "project": compiled.project,
        "primitive_contract_version": "retrieval-v1",
        "program": program.model_dump(mode="json"),
        "steps": steps,
        "fallback_steps": fallback,
        "estimated": {
            "step_count": len(program.steps),
            "fallback_step_count": len(program.contingency.fallback_steps),
            "max_steps": program.limits.max_steps,
            "max_hops_per_step": program.limits.max_hops_per_step,
            "max_nodes_per_step": program.limits.max_nodes_per_step,
            "sum_step_node_caps": sum(
                int(step.get("estimated_max_nodes") or 0) for step in steps
            ),
        },
    }
