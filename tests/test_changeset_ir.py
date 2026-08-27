"""ChangeSet IR — faithful-bridge unit tests (construction step 1)."""

from __future__ import annotations

import pytest

from mcp_server.changeset import ChangeOp, ChangeSet, Materialization, OpKind
from mcp_server.proposals import SSTProposal

ENC = {"concepts": [{"id": "c1", "label": "C1", "text_content": "b", "semantic_anchor": "a"}],
       "edges": [{"type": "CONTAINS", "source_id": "order_service", "target_id": "c1", "label": "x"}]}


def test_round_trip_and_sstproposal_equivalence():
    cs = ChangeSet.from_proposal_encoding(ENC, base="EMPTY")
    assert cs.to_encoding()["concepts"][0]["id"] == "c1"
    prop = cs.to_proposal()
    direct = SSTProposal.model_validate(ENC)
    assert [c.id for c in prop.concepts] == [c.id for c in direct.concepts]
    assert [e.type for e in prop.edges] == [e.type for e in direct.edges]


def test_base_selects_materialization():
    assert ChangeSet.from_proposal_encoding(ENC).materialization == Materialization.CREATE
    assert ChangeSet.from_proposal_encoding(ENC, base="gv").materialization == Materialization.EVOLVE


def test_non_add_ops_cannot_reach_the_add_only_commit_path():
    edit = ChangeSet(base="gv", operations=[
        ChangeOp(kind=OpKind.REPLACE_CONTENT, target_node_id="c1", payload={"text": "new"})])
    assert not edit.is_add_only()
    with pytest.raises(ValueError, match="edit gate"):
        edit.to_proposal()


def test_empty_and_add_only_predicates():
    assert ChangeSet().is_empty()
    assert ChangeSet.from_proposal_encoding(ENC).is_add_only()
