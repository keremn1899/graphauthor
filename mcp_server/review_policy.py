"""Format-driven review exceptions for harness proposals.

This module only classifies whether a compatible proposal is ordinary or
exceptional under the active ``graph.md`` review mode. It never accepts or
rejects. A review-required row is not auto-encoded.
"""

from __future__ import annotations

from typing import Any

from mcp_server.graph_contract import GraphContractDocument, GraphFormatSpec


CONTRADICTION_PREDICATES = frozenset({"contradicts"})
SUPERSESSION_PREDICATES = frozenset({"supersedes"})
REQUIRED_TRAVERSAL_REFUSAL_CODES = frozenset(
    {
        "MISSING_REQUIRED_TRAVERSAL",
        "WRONG_TRAVERSAL",
        "WRONG_TRAVERSAL_TARGET",
    }
)


def classify_review(
    document: GraphContractDocument | None,
    *,
    concepts: list[Any],
    edges: list[Any],
    corrections: list[Any],
    source_refs: list[str],
    traversal_preflight: dict[str, Any],
    receipt: dict[str, Any],
    existing_kinds: dict[str, str],
) -> dict[str, Any]:
    """Return a deterministic review classification for one proposal."""
    if document is None:
        return {
            "review_mode": "",
            "review_required": False,
            "exceptions": [],
        }
    spec = document.specification
    exceptions: list[dict[str, str]] = []
    proposed_kinds = {
        str(getattr(concept, "kind", "") or "").strip()
        for concept in concepts
        if str(getattr(concept, "kind", "") or "").strip()
    }
    proposed_ids = {
        str(getattr(concept, "id", "") or "").strip()
        for concept in concepts
        if str(getattr(concept, "id", "") or "").strip()
    }
    endpoint_ids: set[str] = set()
    predicates: set[str] = set()
    for edge in edges:
        predicates.add(str(getattr(edge, "predicate", "") or "").strip())
        for endpoint in (
            getattr(edge, "source_id", ""),
            getattr(edge, "target_id", ""),
        ):
            node_id = str(endpoint or "").strip()
            if node_id:
                endpoint_ids.add(node_id)
    touched_ids = proposed_ids | endpoint_ids
    touched_kinds = set(proposed_kinds)
    for node_id in endpoint_ids:
        kind = existing_kinds.get(node_id, "")
        if kind:
            touched_kinds.add(kind)
        for concept in concepts:
            if str(getattr(concept, "id", "") or "") == node_id:
                kind = str(getattr(concept, "kind", "") or "").strip()
                if kind:
                    touched_kinds.add(kind)

    if corrections:
        exceptions.append(
            {
                "code": "CORRECTION",
                "detail": "corrections are always exceptional",
            }
        )
    if predicates & SUPERSESSION_PREDICATES:
        exceptions.append(
            {
                "code": "SUPERSESSION",
                "detail": "proposal uses supersedes",
            }
        )
    if predicates & CONTRADICTION_PREDICATES:
        exceptions.append(
            {
                "code": "CONTRADICTION",
                "detail": "proposal records disagreement",
            }
        )
    batch_size = len(concepts) + len(edges) + len(corrections)
    if batch_size > int(spec.oversized_batch):
        exceptions.append(
            {
                "code": "OVERSIZED_BATCH",
                "detail": (
                    f"batch of {batch_size} exceeds oversized_batch "
                    f"{spec.oversized_batch}"
                ),
            }
        )
    if not [ref for ref in source_refs if str(ref).strip()]:
        exceptions.append(
            {
                "code": "MISSING_SOURCE",
                "detail": "no source_refs attached",
            }
        )

    receipt_recipe = str(receipt.get("recipe_name") or "").strip()
    receipt_params = receipt.get("canonical_parameters") or {}
    if not isinstance(receipt_params, dict):
        receipt_params = {}
    preflight_status = str(traversal_preflight.get("status") or "NOT_SUPPLIED")
    exceptions.extend(
        required_traversal_exceptions(
            spec,
            touched_kinds=touched_kinds,
            touched_ids=touched_ids,
            preflight_status=preflight_status,
            receipt_recipe=receipt_recipe,
            receipt_params=receipt_params,
        )
    )

    review_required = spec.review_mode == "gated" or (
        spec.review_mode == "exceptions" and bool(exceptions)
    )
    return {
        "review_mode": spec.review_mode,
        "review_required": review_required,
        "exceptions": exceptions,
    }


def required_traversal_exceptions(
    spec: GraphFormatSpec,
    *,
    touched_kinds: set[str],
    touched_ids: set[str],
    preflight_status: str,
    receipt_recipe: str,
    receipt_params: dict[str, Any],
) -> list[dict[str, str]]:
    """Hard propose refusals when the format names a required recipe."""
    exceptions: list[dict[str, str]] = []
    for requirement in spec.required_traversals:
        required_kinds = set(requirement.when_kinds)
        if required_kinds and not (touched_kinds & required_kinds):
            continue
        if preflight_status != "VERIFIED" or not receipt_recipe:
            exceptions.append(
                {
                    "code": "MISSING_REQUIRED_TRAVERSAL",
                    "detail": (
                        f"required {requirement.recipe} was not attached"
                    ),
                }
            )
            continue
        if receipt_recipe != requirement.recipe:
            exceptions.append(
                {
                    "code": "WRONG_TRAVERSAL",
                    "detail": (
                        f"required {requirement.recipe}, attached "
                        f"{receipt_recipe}"
                    ),
                }
            )
            continue
        parameter = str(requirement.parameter or "").strip()
        if parameter:
            bound = str(receipt_params.get(parameter) or "").strip()
            if bound and bound not in touched_ids:
                exceptions.append(
                    {
                        "code": "WRONG_TRAVERSAL_TARGET",
                        "detail": (
                            f"{requirement.recipe} bound {parameter}={bound}, "
                            "which this proposal does not touch"
                        ),
                    }
                )
    return exceptions


def explain_membership(
    variables: dict[str, list],
    collected_ids: list[str],
    operations: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """Map collected node ids to the recipe variables that introduced them."""
    by_variable: dict[str, list[str]] = {}
    for name, values in variables.items():
        seen: set[str] = set()
        ordered: list[str] = []
        for item in values or []:
            node_id = ""
            if isinstance(item, str):
                node_id = item.strip()
            elif isinstance(item, dict):
                node_id = str(item.get("id") or "").strip()
            if node_id and node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        by_variable[str(name)] = ordered

    collected = [str(node_id) for node_id in collected_ids if str(node_id)]
    membership = {
        node_id: [
            name
            for name, ids in by_variable.items()
            if node_id in ids
        ]
        for node_id in collected
    }
    why: dict[str, dict[str, Any]] = {}
    for index, operation in enumerate(operations):
        assign = str(operation.get("assign_to") or "")
        for node_id in by_variable.get(assign, []):
            if node_id in membership and node_id not in why:
                why[node_id] = {
                    "variable": assign,
                    "tool": str(operation.get("tool") or ""),
                    "phase": str(operation.get("phase") or "primary"),
                    "step": index + 1,
                }
    return membership, why
