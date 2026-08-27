from __future__ import annotations

import json

import pytest

from mcp_server.surface import Surface
from source_pipeline.encoding import write_graph
from source_pipeline.traversals import (
    WorkbookTraversalError,
    bind_workbook_traversals,
    load_bound_workbook_traversals,
)


def _encoding():
    return {
        "graph": {"id": "org", "domain": "organisation"},
        "concepts": [
            {"id": "team:ops", "kind": "team", "synthetic_reason": "fixture"},
            {"id": "person:bob", "kind": "person", "synthetic_reason": "fixture"},
        ],
        "edges": [
            {
                "source_id": "team:ops",
                "predicate": "member",
                "target_id": "person:bob",
                "sst_type": "CONTAINS",
                "synthetic_reason": "fixture",
            }
        ],
    }


def _programs(predicate="member"):
    return {
        "schema_version": "workbook-traversals-v1",
        "traversals": {
            "team_members": {
                "version": 1,
                "purpose": "Find direct members of a team.",
                "parameters": {
                    "team_id": {"type": "node_id", "kinds": ["team"]}
                },
                "steps": [
                    {"op": "lookup", "references": ["$team_id"], "assign": "team"},
                    {
                        "op": "traverse",
                        "from": "$team",
                        "predicates": [predicate],
                        "direction": "outgoing",
                        "depth": 1,
                        "assign": "members",
                    },
                ],
                "collect": "$members",
                "answers": ["members"],
            }
        },
    }


def test_binding_derives_vocabulary_instead_of_accepting_a_format():
    bound = bind_workbook_traversals(_programs(), _encoding())

    assert bound["binding"]["predicates"] == {"member": "CONTAINS"}
    assert bound["binding"]["node_kind_id_patterns"] == {
        "person": "person:<stable-id>",
        "team": "team:<stable-id>",
    }
    assert bound["fingerprint"].startswith("wtrv_")


def test_unknown_predicate_is_refused_against_observed_encoding():
    with pytest.raises(WorkbookTraversalError, match="unknown predicates"):
        bind_workbook_traversals(_programs("invented"), _encoding())


def test_bound_artifact_detects_tampering(tmp_path):
    path = tmp_path / "graph.lbug.traversals.json"
    bound = bind_workbook_traversals(_programs(), _encoding())
    bound["binding"]["predicates"]["member"] = "NEARTO"
    path.write_text(json.dumps(bound))

    with pytest.raises(WorkbookTraversalError, match="fingerprint"):
        load_bound_workbook_traversals(path)


def test_surface_runs_workbook_named_traversal_without_graph_md(tmp_path):
    graph = tmp_path / "org.lbug"
    write_graph(_encoding(), graph, traversals=_programs())

    surface = Surface(graph)
    try:
        card = surface.orient()["named_traversal"]
        result = surface.run_traversal("team_members", {"team_id": "team:ops"})
    finally:
        surface.close()

    assert card["source"] == "workbook"
    assert [recipe["name"] for recipe in card["recipes"]] == ["team_members"]
    assert result["outcome"] == "FOUND"
    assert "person:bob" in result["answer_node_ids"]
    assert result["execution_receipt"]["format_fingerprint"].startswith("wtrv_")
    assert result["execution_receipt"]["program_set_fingerprint"].startswith("wtrv_")


def test_rematerializing_without_programs_withdraws_bound_sidecar(tmp_path):
    graph = tmp_path / "org.lbug"
    write_graph(_encoding(), graph, traversals=_programs())
    sidecar = tmp_path / "org.lbug.traversals.json"
    assert sidecar.exists()

    write_graph(_encoding(), graph)

    assert not sidecar.exists()


def test_invalid_programs_are_refused_before_graph_replacement(tmp_path):
    graph = tmp_path / "org.lbug"
    write_graph(_encoding(), graph, traversals=_programs())
    before_graph = graph.read_bytes()
    before_sidecar = (tmp_path / "org.lbug.traversals.json").read_bytes()

    with pytest.raises(WorkbookTraversalError, match="unknown predicates"):
        write_graph(_encoding(), graph, traversals=_programs("invented"))

    assert graph.read_bytes() == before_graph
    assert (tmp_path / "org.lbug.traversals.json").read_bytes() == before_sidecar
