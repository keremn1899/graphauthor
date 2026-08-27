"""Run graph.md recipe fixtures against an open surface.

Fixtures are format-owned expected packets. They do not prove the graph is
complete; they prove a named traversal still returns the bounded result the
format author wrote down.
"""

from __future__ import annotations

from typing import Any

from mcp_server.graph_contract import GraphContractDocument, load_graph_contract
from mcp_server.surface import Surface


def _node_ids(result: dict[str, Any]) -> set[str]:
    evidence = result.get("evidence") or {}
    return {
        str(row.get("id") or "")
        for row in evidence.get("node_records") or []
        if isinstance(row, dict) and row.get("id")
    }


def _collected_ids(result: dict[str, Any]) -> set[str]:
    """The nodes the recipe's `collect` expression actually selected.

    `membership` is keyed by exactly those nodes — the receipt's
    `collected_node_count` matches its length — which is what makes it the
    answer rather than the packet.
    """
    return {str(node_id) for node_id in (result.get("membership") or {})}


def evaluate_fixture_result(
    result: dict[str, Any],
    expect: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    outcome = str(result.get("outcome") or "")
    expected_outcome = str(expect.get("outcome") or "")
    if outcome != expected_outcome:
        failures.append(
            f"outcome {outcome or 'ABSENT'} != {expected_outcome}"
        )
    ids = _node_ids(result)
    for node_id in expect.get("contains") or []:
        if str(node_id) not in ids:
            failures.append(f"missing {node_id}")
    for node_id in expect.get("excludes") or []:
        if str(node_id) in ids:
            failures.append(f"unexpected {node_id}")
    expected_collected = expect.get("collects")
    if expected_collected is not None:
        actual = _collected_ids(result)
        wanted = {str(node_id) for node_id in expected_collected}
        for node_id in sorted(wanted - actual):
            failures.append(f"not collected: {node_id}")
        for node_id in sorted(actual - wanted):
            failures.append(f"collected but not expected: {node_id}")
    truncated = expect.get("truncated")
    if truncated is not None:
        actual = bool((result.get("execution_receipt") or {}).get("truncated"))
        if actual is not bool(truncated):
            failures.append(f"truncated {actual} != {truncated}")
    return failures


def run_contract_fixtures(
    surface: Surface,
    document: GraphContractDocument | None = None,
) -> dict[str, Any]:
    """Execute every fixture on the active contract. Zero LLM."""
    if document is None:
        document = load_graph_contract(surface._graph_contract_path)
    reports: list[dict[str, Any]] = []
    for recipe_name, recipe in sorted(document.specification.traversals.items()):
        for fixture in recipe.fixtures:
            result = surface.run_traversal(
                recipe_name,
                dict(fixture.parameters),
                version=recipe.version,
            )
            expect = fixture.expect.model_dump(mode="json")
            failures = evaluate_fixture_result(result, expect)
            reports.append(
                {
                    "recipe": recipe_name,
                    "fixture": fixture.name,
                    "ok": not failures,
                    "failures": failures,
                    "outcome": result.get("outcome"),
                    "cache_key": result.get("cache_key"),
                }
            )
    passed = sum(1 for row in reports if row["ok"])
    return {
        "kind": "RECIPE_FIXTURES",
        "format_id": document.specification.format_id,
        "format_fingerprint": document.fingerprint,
        "count": len(reports),
        "passed": passed,
        "failed": len(reports) - passed,
        "reports": reports,
    }
