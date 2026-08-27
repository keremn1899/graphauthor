from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from mcp_server.retrieve import Retrieve
from mcp_server.surface import Surface, open_fixture


FIXTURE = "runtime/hexagonal_orders.lbug"


@pytest.fixture(scope="module")
def surface() -> Surface:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        instance = open_fixture(FIXTURE)
        yield instance
        instance.close()


def test_capability_card_is_the_four_bounded_retrieval_ops():
    card = Retrieve.capability_card()
    assert card["operations"] == ["lookup", "expand", "path", "search"]
    assert "region" not in card["operations"]
    assert "lookup is exact and terminal on miss" in card["identity_policy"]




def test_expand_returns_typed_edges_and_optional_content(surface):
    ops = Retrieve(surface)
    result = ops.expand(
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


def test_path_preserves_path_records(surface):
    ops = Retrieve(surface)
    result = ops.path(
        ["order_controller"],
        ["order_service"],
        edge_types=["leadsto"],
        max_hops=4,
    )

    assert result["outcome"] == "FOUND"
    assert result["evidence_scope"] == "closure-derived"
    assert result["evidence"]["path_records"]
    assert result["evidence"]["path_records"][0]["source"] == "order_controller"


def test_path_distinguishes_unresolved_endpoints_from_no_path(surface):
    historical = Retrieve(
        surface, endpoint_resolution_feedback=False
    ).path(["definitely_missing"], ["order_service"], edge_types=["leadsto"])
    assert historical["outcome"] == "EMPTY"
    assert "endpoint_resolution" not in historical

    ops = Retrieve(surface)
    missing = ops.path(
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

    known_no_path = ops.path(
        ["order_controller"], ["order_service"], edge_types=["contains"], max_hops=1
    )
    assert known_no_path["outcome"] == "EMPTY"
    assert known_no_path["evidence_scope"] == "closure-derived"
    assert known_no_path["endpoint_resolution"]["complete"] is True


def test_search_is_explicitly_candidate_only(surface):
    ops = Retrieve(surface)
    result = ops.search("dependency direction", mode="lexical", limit=5)

    assert result["candidate_only"] is True
    assert result["evidence_scope"] == "candidate-derived"
    assert result["outcome"] == "CANDIDATES"
    assert result["zero_llm"] is True
    assert result["operation"] == "search"


def test_search_miss_cannot_be_terminal_empty(surface):
    ops = Retrieve(surface)
    result = ops.search("definitely_missing_search_term_9f37", mode="lexical")

    assert result["outcome"] == "NO_CANDIDATES"
    assert result["outcome"] != "EMPTY"
    assert result["candidate_only"] is True
    assert result["evidence_scope"] == "candidate-derived"


def test_semantic_search_refuses_an_artifact_without_optional_embeddings(tmp_path):
    db_path = tmp_path / "offline.lbug"
    Path(str(db_path) + ".metadata.json").write_text(
        json.dumps({"embedding_status": "NOT_BUILT"}), encoding="utf-8"
    )

    class OfflineSurface:
        _db_path = db_path

        @staticmethod
        def _read_guard():
            return nullcontext()

        @staticmethod
        def _base():
            return {"graph_version": "gv-offline"}

        @staticmethod
        def _compass_ref():
            return "compass-offline"

    result = Retrieve(OfflineSurface()).search("architecture decision")

    assert result["outcome"] == "SEARCH_UNAVAILABLE"
    assert result["candidate_only"] is True
    assert result["closed"] is False
    assert result["degradation_flags"] == ["semantic_embeddings_not_built"]


def test_rejects_unbounded_or_unknown_parameters(surface):
    ops = Retrieve(surface)
    with pytest.raises(ValueError, match="depth"):
        ops.expand(["ports_module"], depth=4)
    with pytest.raises(ValueError, match="unsupported edge"):
        ops.expand(["ports_module"], edge_types=["invented"])
    with pytest.raises(ValueError, match="mode"):
        ops.search("rules", mode="cypher")


def test_precondition_failure_is_not_misreported_as_empty(surface):
    ops = Retrieve(surface)

    stale_graph = ops.lookup(
        ["dependency_direction_rule"], graph_version="stale"
    )
    stale_context = ops.expand(["ports_module"], context_ref="stale")

    assert stale_graph["kind"] == "STALE_GRAPH"
    assert stale_graph["outcome"] == "STALE_GRAPH"
    assert stale_graph["evidence_scope"] == "no-evidence"
    assert stale_context["kind"] == "STALE_CONTEXT"
    assert stale_context["outcome"] == "STALE_CONTEXT"
    assert stale_context["evidence_scope"] == "no-evidence"


def test_seed_resolution_distinguishes_unknown_from_known_empty(surface):
    ordinary = Retrieve(
        surface, seed_resolution_feedback=False
    ).expand(["definitely_missing"])
    assert ordinary["outcome"] == "EMPTY"
    assert "seed_resolution" not in ordinary

    ops = Retrieve(surface)
    missing = ops.expand(["definitely_missing"])
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

    known_empty = ops.expand(
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


def test_both_retrieval_doors_run_one_implementation_of_the_four_ops():
    """The defect this replaces: a repair that reached one of two copies.

    `HostRetrievalSurface.search` was moved to semantic after lexical was
    measured ranking four context paragraphs above the rule that answered the
    question. `Retrieve.search` kept the old default for months, because it was
    a separate copy — so product Ask went on ranking lexically. An AST
    comparison then found nine of the thirteen shared methods byte-identical,
    all four public ops among them.

    A parity assertion on the defaults would not have been enough: it fixes the
    one field that already broke and leaves the next one open. This asserts the
    property instead — there is one implementation, and the host door reaches it
    by inheritance rather than by copy. A third copy fails here.
    """
    from mcp_server.host_retrieval import HostRetrievalSurface
    from mcp_server.retrieve import Retrieve

    assert issubclass(HostRetrievalSurface, Retrieve)
    for op in ("lookup", "expand", "path", "search"):
        assert getattr(HostRetrievalSurface, op) is getattr(Retrieve, op), (
            f"{op} was overridden on the host door; the two doors have forked again"
        )
    # The validation and program-building helpers are the ops' actual behaviour;
    # forking one of these forks the contract just as effectively.
    for helper in ("_strings", "_types", "_types_or_feedback", "_execute",
                   "_expand_with_seed_resolution", "_path_with_endpoint_resolution"):
        assert getattr(HostRetrievalSurface, helper) is getattr(Retrieve, helper), (
            f"{helper} was overridden on the host door"
        )


def test_the_host_extension_seam_can_annotate_but_not_change_the_answer(surface):
    """`_after_execute` is the one seam, and it is deliberately weak.

    Regional navigation is the only thing on it today, and it is navigation,
    not authority. If an extension could move `outcome` or `evidence`, the two
    doors would be running different contracts again while still passing the
    subclass check above.
    """
    from mcp_server.host_retrieval import HostRetrievalSurface

    plain = HostRetrievalSurface(surface).lookup(["dependency_direction_rule"])
    linked = HostRetrievalSurface(surface, linked_navigation=True).lookup(
        ["dependency_direction_rule"]
    )

    assert "navigation" not in plain
    assert linked["navigation"]["kind"] == "regional"
    for field in ("outcome", "evidence_scope", "evidence", "operation", "zero_llm"):
        assert linked[field] == plain[field], f"the seam moved {field}"
