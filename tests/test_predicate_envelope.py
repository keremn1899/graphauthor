from __future__ import annotations

from pathlib import Path

import real_ladybug as lb

from engine import migrate_format_kind_column
from mcp_server.proposals import validate_proposal
from tests.workbook_graph_fixture import PERSONAL_RECIPE_CONTRACT


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "graph.recipes.md"
    path.write_text(PERSONAL_RECIPE_CONTRACT)
    return path


def _graph(path: Path, *, with_kind: bool = True) -> None:
    conn = lb.Connection(lb.Database(str(path)))
    kind_column = ", kind STRING DEFAULT ''" if with_kind else ""
    conn.execute(
        "CREATE NODE TABLE Concept ("
        "id STRING, label STRING, text_content STRING, semantic_anchor STRING"
        f"{kind_column}, PRIMARY KEY (id))"
    )
    if with_kind:
        conn.execute(
            "CREATE (:Concept {id: 'topic:agents', label: 'Agents', "
            "text_content: 'Agent systems', semantic_anchor: 'agents', kind: 'topic'})"
        )
    else:
        conn.execute(
            "CREATE (:Concept {id: 'topic:agents', label: 'Agents', "
            "text_content: 'Agent systems', semantic_anchor: 'agents'})"
        )
    del conn


def test_format_kind_migration_is_additive_and_idempotent(tmp_path):
    path = tmp_path / "legacy.lbug"
    _graph(path, with_kind=False)
    conn = lb.Connection(lb.Database(str(path)))

    assert migrate_format_kind_column(conn) == ["kind"]
    assert migrate_format_kind_column(conn) == []
    row = conn.execute(
        "MATCH (c:Concept {id: 'topic:agents'}) RETURN c.kind"
    ).get_next()
    assert row[0] == ""


def test_contract_proposal_derives_sst_from_predicate(tmp_path):
    path = tmp_path / "research.lbug"
    _graph(path)

    proposal, error = validate_proposal(
        {
            "concepts": [
                {
                    "id": "claim:bounded-context",
                    "kind": "claim",
                    "label": "Bounded context",
                    "text_content": "Named traversals return bounded context.",
                }
            ],
            "edges": [
                {
                    "predicate": "about",
                    "source_id": "claim:bounded-context",
                    "target_id": "topic:agents",
                }
            ],
        },
        path,
        graph_contract_path=_contract(tmp_path),
    )

    assert error == ""
    assert proposal is not None
    assert proposal.edges[0].type == "NEARTO"
    assert proposal.edges[0].predicate == "about"
    assert proposal.edges[0].label == "about"


def test_contract_proposal_rejects_unknown_kind_predicate_and_wrong_sst(tmp_path):
    path = tmp_path / "research.lbug"
    _graph(path)
    contract = _contract(tmp_path)

    common = {
        "concepts": [
            {
                "id": "claim:test",
                "kind": "claim",
                "label": "Test",
                "text_content": "A test claim.",
            }
        ],
        "edges": [],
    }
    proposal, error = validate_proposal(
        {**common, "concepts": [{**common["concepts"][0], "kind": "invented"}]},
        path,
        graph_contract_path=contract,
    )
    assert proposal is None and "not declared" in error

    proposal, error = validate_proposal(
        {
            **common,
            "edges": [
                {
                    "predicate": "invented",
                    "source_id": "claim:test",
                    "target_id": "topic:agents",
                }
            ],
        },
        path,
        graph_contract_path=contract,
    )
    assert proposal is None and "predicate" in error and "not declared" in error

    proposal, error = validate_proposal(
        {
            **common,
            "edges": [
                {
                    "predicate": "about",
                    "type": "LEADSTO",
                    "source_id": "claim:test",
                    "target_id": "topic:agents",
                }
            ],
        },
        path,
        graph_contract_path=contract,
    )
    assert proposal is None and "derives SST NEARTO" in error


def test_legacy_proposal_still_requires_explicit_sst(tmp_path):
    path = tmp_path / "legacy.lbug"
    _graph(path)

    proposal, error = validate_proposal(
        {
            "concepts": [
                {
                    "id": "legacy:new",
                    "label": "Legacy",
                    "text_content": "Legacy node.",
                }
            ],
            "edges": [
                {
                    "source_id": "legacy:new",
                    "target_id": "topic:agents",
                    "label": "related",
                }
            ],
        },
        path,
    )
    assert proposal is None and "legacy graphs require edge type" in error
