from __future__ import annotations

import pytest

from mcp_server.host_retrieval import HostRetrievalSurface
from mcp_server.surface import Surface, open_fixture


FIXTURE = "runtime/hexagonal_orders.lbug"


@pytest.fixture(scope="module")
def surface() -> Surface:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        instance = open_fixture(FIXTURE)
        yield instance
        instance.close()




def test_host_expand_returns_typed_edges_and_optional_content(surface):
    host = HostRetrievalSurface(surface)
    result = host.expand(
        ["ports_module"],
        edge_types=["contains"],
        direction="outgoing",
        depth=1,
        include_content=True,
    )

    assert result["outcome"] == "FOUND"
    assert result["evidence_scope"] == "closure-derived"
    assert result["evidence"]["edge_records"]
    assert all(edge["edge_type"] == "contains" for edge in result["evidence"]["edge_records"])
    assert result["evidence"]["node_payloads"]


def test_host_path_preserves_path_records(surface):
    host = HostRetrievalSurface(surface)
    result = host.path(
        ["order_controller"],
        ["order_service"],
        edge_types=["leadsto"],
        max_hops=4,
    )

    assert result["outcome"] == "FOUND"
    assert result["evidence_scope"] == "closure-derived"
    assert result["evidence"]["path_records"]
    assert result["evidence"]["path_records"][0]["source"] == "order_controller"


def test_host_path_distinguishes_unresolved_endpoints_from_no_path(surface):
    historical = HostRetrievalSurface(
        surface, endpoint_resolution_feedback=False
    ).path(["definitely_missing"], ["order_service"], edge_types=["leadsto"])
    assert historical["outcome"] == "EMPTY"
    assert "endpoint_resolution" not in historical

    host = HostRetrievalSurface(surface)
    missing = host.path(
        ["definitely_missing"], ["also_missing"], edge_types=["leadsto"]
    )
    assert missing["outcome"] == "UNRESOLVED_ENDPOINT"
    assert missing["evidence_scope"] == "no-evidence"
    assert missing["retryable"] is False
    assert missing["endpoint_resolution"] == {
        "requested_source_ids": ["definitely_missing"],
        "resolved_source_ids": [],
        "unresolved_source_ids": ["definitely_missing"],
        "requested_target_ids": ["also_missing"],
        "resolved_target_ids": [],
        "unresolved_target_ids": ["also_missing"],
        "complete": False,
    }
    assert missing["execution_receipt"]["resolve_miss_count"] == 2

    known_no_path = host.path(
        ["order_controller"], ["order_service"], edge_types=["contains"], max_hops=1
    )
    assert known_no_path["outcome"] == "EMPTY"
    assert known_no_path["evidence_scope"] == "closure-derived"
    assert known_no_path["endpoint_resolution"]["complete"] is True


def test_host_search_is_explicitly_candidate_only(surface):
    host = HostRetrievalSurface(surface)
    result = host.search("dependency direction", mode="lexical", limit=5)

    assert result["candidate_only"] is True
    assert result["evidence_scope"] == "candidate-derived"
    assert result["outcome"] == "CANDIDATES"
    assert result["zero_llm"] is True
    assert result["operation"] == "search"


def test_host_search_miss_cannot_be_terminal_empty(surface):
    host = HostRetrievalSurface(surface)
    result = host.search("definitely_missing_search_term_9f37", mode="lexical")

    assert result["outcome"] == "NO_CANDIDATES"
    assert result["outcome"] != "EMPTY"
    assert result["candidate_only"] is True
    assert result["evidence_scope"] == "candidate-derived"


def test_host_surface_rejects_unbounded_or_unknown_parameters(surface):
    host = HostRetrievalSurface(surface)
    with pytest.raises(ValueError, match="depth"):
        host.expand(["ports_module"], depth=4)
    with pytest.raises(ValueError, match="unsupported edge"):
        host.expand(["ports_module"], edge_types=["invented"])
    with pytest.raises(ValueError, match="mode"):
        host.search("rules", mode="cypher")


def test_host_precondition_failure_is_not_misreported_as_empty(surface):
    host = HostRetrievalSurface(surface)

    stale_graph = host.lookup(
        ["dependency_direction_rule"], graph_version="stale"
    )
    stale_context = host.expand(["ports_module"], context_ref="stale")

    assert stale_graph["kind"] == "STALE_GRAPH"
    assert stale_graph["outcome"] == "STALE_GRAPH"
    assert stale_graph["evidence_scope"] == "no-evidence"
    assert stale_context["kind"] == "STALE_CONTEXT"
    assert stale_context["outcome"] == "STALE_CONTEXT"
    assert stale_context["evidence_scope"] == "no-evidence"


def test_linked_navigation_is_opt_in_exact_and_cached(surface):
    ordinary = HostRetrievalSurface(surface).lookup(["dependency_direction_rule"])
    assert "navigation" not in ordinary

    host = HostRetrievalSurface(surface, linked_navigation=True)
    first = host.lookup(["dependency_direction_rule"])
    second = host.expand(
        ["ports_module"],
        edge_types=["contains"],
        direction="outgoing",
        depth=1,
    )

    navigation = first["navigation"]
    assert navigation["kind"] == "regional"
    assert navigation["node_regions"]["dependency_direction_rule"].startswith(
        "region_"
    )
    assert navigation["continuations"] == [
        {
            "tool": "region",
            "region_id": navigation["node_regions"]["dependency_direction_rule"],
        }
    ]
    assert navigation["receipt"]["index_cache_hit"] is False
    assert navigation["receipt"]["serialized_chars"] > 0
    assert second["navigation"]["receipt"]["index_cache_hit"] is True


def test_structured_feedback_maps_exact_edge_label_without_widening(surface):
    host = HostRetrievalSurface(surface, structured_feedback=True)
    correction = host.expand(
        ["ports_module"],
        edge_types=["defines_outbound", "invented"],
        direction="outgoing",
    )

    assert correction["outcome"] == "INVALID_ARGUMENT"
    assert correction["retryable"] is True
    assert correction["error"] == {
        "code": "UNSUPPORTED_EDGE_TYPE",
        "provided": ["defines_outbound", "invented"],
        "allowed_edge_types": ["contains", "expresses", "leadsto", "nearto"],
        "matched_edge_labels": {"defines_outbound": ["contains"]},
        "edge_labels_argument": "edge_labels",
    }

    recovered = host.expand(
        ["ports_module"],
        edge_types=["contains"],
        edge_labels=["defines_outbound"],
        direction="outgoing",
    )
    assert recovered["outcome"] == "FOUND"
    assert all(
        edge["edge_label"] == "defines_outbound"
        for edge in recovered["evidence"]["edge_records"]
    )


def test_seed_resolution_feedback_distinguishes_unknown_from_known_empty(surface):
    ordinary = HostRetrievalSurface(
        surface, seed_resolution_feedback=False
    ).expand(["definitely_missing"])
    assert ordinary["outcome"] == "EMPTY"
    assert "seed_resolution" not in ordinary

    host = HostRetrievalSurface(surface, seed_resolution_feedback=True)
    missing = host.expand(["definitely_missing"])
    assert missing["outcome"] == "UNRESOLVED_SEED"
    assert missing["evidence_scope"] == "no-evidence"
    assert missing["retryable"] is False
    assert missing["seed_resolution"] == {
        "requested_node_ids": ["definitely_missing"],
        "resolved_node_ids": [],
        "unresolved_node_ids": ["definitely_missing"],
        "complete": False,
    }
    assert missing["execution_receipt"]["resolve_miss_count"] == 1

    known_empty = host.expand(
        ["ports_module"],
        edge_types=["leadsto"],
        direction="outgoing",
        edge_labels=["definitely_missing_label"],
    )
    assert known_empty["outcome"] == "EMPTY"
    assert known_empty["evidence_scope"] == "closure-derived"
    assert known_empty["seed_resolution"] == {
        "requested_node_ids": ["ports_module"],
        "resolved_node_ids": ["ports_module"],
        "unresolved_node_ids": [],
        "complete": True,
    }


def test_seed_resolution_feedback_preserves_stale_preconditions(surface):
    host = HostRetrievalSurface(surface, seed_resolution_feedback=True)
    stale = host.expand(["definitely_missing"], graph_version="stale")
    assert stale["outcome"] == "STALE_GRAPH"
    assert stale["operation"] == "expand"
