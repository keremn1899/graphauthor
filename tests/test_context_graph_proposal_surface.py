from __future__ import annotations

import pytest

from benchmarks.proposal_host.context_graph_surface import (
    ContextGraphProposalSurface,
)
from mcp_server.changeset import ChangeSet
from mcp_server.surface import Surface


@pytest.fixture()
def proposal_surface(tmp_path):
    from mcp_server.fixture import ensure_fixture
    import shutil

    db = tmp_path / "graph.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(
        db,
        store_path=tmp_path / "write.sqlite",
        enable_proposals=True,
    )
    try:
        yield ContextGraphProposalSurface(surface)
    finally:
        surface.close()


def _change_set(context: dict, *, anchoring: list[str]) -> dict:
    edge = context["context_graph"]["edges"][0]
    anchor = edge["source_id"]
    encoding = {
        "concepts": [
            {
                "id": "context_graph_rule",
                "label": "Context graph rule",
                "text_content": "The architecture must preserve this tested rule.",
            }
        ],
        "edges": [
            {
                "type": edge["type"],
                "source_id": anchor,
                "target_id": "context_graph_rule",
                "label": edge["label"],
            }
        ],
    }
    change_set = ChangeSet.from_proposal_encoding(
        encoding,
        base=context["graph_version"],
        target_gaps=["context_graph_gap"],
    )
    change_set.anchoring = anchoring
    return change_set.model_dump(mode="json")


def test_context_graph_exposes_closed_region_and_local_vocabulary(proposal_surface):
    context = proposal_surface.context_graph(["ports_module"])

    assert context["kind"] == "CONTEXT_GRAPH"
    assert context["context_graph"]["evidence_scope"] == "closure-derived"
    assert "ports_module" in {
        row["id"] for row in context["context_graph"]["nodes"]
    }
    assert context["context_graph"]["local_edge_labels"]
    assert context["authority"]["agent_can_commit"] is False


def test_context_graph_unions_multiple_declared_regions(proposal_surface):
    context = proposal_surface.context_graph(
        ["ports_module", "adapters_module", "ports_module"]
    )

    assert context["kind"] == "CONTEXT_GRAPH"
    assert context["context_graph"]["anchors"] == [
        "ports_module",
        "adapters_module",
    ]
    observed = {row["id"] for row in context["context_graph"]["nodes"]}
    assert {"ports_module", "adapters_module"} <= observed


def test_context_graph_requires_existing_endpoint_in_anchoring(proposal_surface):
    context = proposal_surface.context_graph(["ports_module"])
    raw = _change_set(context, anchoring=[])

    refused = proposal_surface.check(
        raw,
        provenance={
            "decision_origin": "recover_existing",
            "source_refs": ["source:test"],
        },
    )

    assert refused["error_code"] == "CONTEXT_ALIGNMENT_FAILED"
    assert refused["alignment"]["missing_anchors"]


def test_context_graph_accepts_aligned_local_vocabulary_change(proposal_surface):
    context = proposal_surface.context_graph(["ports_module"])
    anchor = context["context_graph"]["edges"][0]["source_id"]
    raw = _change_set(context, anchoring=[anchor])

    checked = proposal_surface.check(
        raw,
        provenance={
            "decision_origin": "recover_existing",
            "source_refs": ["source:test"],
        },
    )

    assert checked["kind"] == "VALID"
    assert checked["alignment"]["errors"] == []
    assert checked["alignment"]["new_edge_labels"] == []
    assert checked["alignment"]["reused_edge_labels"]


def test_context_graph_allows_but_discloses_a_new_edge_label(proposal_surface):
    context = proposal_surface.context_graph(["ports_module"])
    edge = context["context_graph"]["edges"][0]
    anchor = edge["source_id"]
    raw = _change_set(context, anchoring=[anchor])
    raw["operations"][1]["edge"]["label"] = "new_local_relation"

    checked = proposal_surface.check(
        raw,
        provenance={
            "decision_origin": "propose_new",
            "source_refs": ["owner-instruction:test"],
        },
    )

    assert checked["kind"] == "VALID"
    assert checked["alignment"]["errors"] == []
    assert checked["alignment"]["new_edge_labels"] == ["new_local_relation"]
    assert checked["alignment"]["reused_edge_labels"] == []


def test_context_graph_refuses_same_label_endpoint_cross_type_collision(
    proposal_surface,
):
    context = proposal_surface.context_graph(["ports_module"])
    edge = context["context_graph"]["edges"][0]
    other_type = "NEARTO" if edge["type"] != "NEARTO" else "LEADSTO"
    change_set = ChangeSet.from_proposal_encoding(
        {
            "concepts": [],
            "edges": [
                {
                    "type": other_type,
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "label": edge["label"],
                }
            ],
        },
        base=context["graph_version"],
        target_gaps=["collision_gap"],
    )
    change_set.anchoring = [edge["source_id"], edge["target_id"]]

    refused = proposal_surface.check(change_set.model_dump(mode="json"))

    assert refused["error_code"] == "CONTEXT_ALIGNMENT_FAILED"
    assert refused["alignment"]["cross_type_collisions"]
