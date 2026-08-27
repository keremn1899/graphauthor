from __future__ import annotations

import pytest

from source_pipeline.draft import GraphDraft, GraphDraftError, semantic_diff
from source_pipeline.encoding import predicate_vocabulary, validate_encoding


class Citation:
    atom_id = "atom:a"


def test_draft_merges_citations_without_choosing_domain_semantics():
    draft = GraphDraft("example", "organisation")
    draft.concept("person:bob", "person", "Bob", citations=Citation())
    draft.concept("person:bob", "person", "Bob", citations="atom:b", text_content="Bob, responder")
    draft.concept("team:ops", "team", "Operations", citations="atom:a")
    draft.edge("team:ops", "member", "person:bob", "contains", citations=["atom:a", "atom:b"])
    draft.require_concepts("person:bob", "team:ops")
    draft.require_edges(("team:ops", "member", "person:bob"))
    draft.require_relation("member", target_id="person:bob")

    encoding = draft.encoding(known_source_unit_ids={"atom:a", "atom:b"})

    assert encoding["concepts"][0]["source_unit_ids"] == ["atom:a", "atom:b"]
    assert predicate_vocabulary(encoding) == {"member": "CONTAINS"}


def test_draft_refuses_identity_and_geometry_conflicts():
    draft = GraphDraft("example")
    draft.concept("x:1", "person", "One", citations="a")
    with pytest.raises(GraphDraftError, match="changed identity"):
        draft.concept("x:1", "team", "One", citations="a")
    draft.edge("x:1", "knows", "x:1", "NEARTO", citations="a")
    with pytest.raises(GraphDraftError, match="changed SST geometry"):
        draft.edge("x:1", "knows", "x:1", "LEADSTO", citations="a")


def test_missing_requirements_fail_at_encoding_boundary():
    draft = GraphDraft("example")
    draft.require_concepts("missing:1")
    draft.require_relation("owns", target_id="thing:1")
    with pytest.raises(GraphDraftError, match="missing required concepts"):
        draft.encoding()


def test_predicate_must_have_one_portable_geometry():
    encoding = {
        "concepts": [
            {"id": "x:1", "kind": "x", "source_unit_ids": ["a"]},
            {"id": "x:2", "kind": "x", "source_unit_ids": ["a"]},
        ],
        "edges": [
            {"source_id": "x:1", "predicate": "related", "target_id": "x:2", "sst_type": "NEARTO", "source_unit_ids": ["a"]},
            {"source_id": "x:2", "predicate": "related", "target_id": "x:1", "sst_type": "LEADSTO", "source_unit_ids": ["a"]},
        ],
    }
    assert any("maps to multiple SST types" in problem for problem in validate_encoding(encoding))


def test_semantic_diff_ignores_citation_changes():
    before = {"concepts": [{"id": "x:1"}], "edges": []}
    after = {
        "concepts": [{"id": "x:1", "source_unit_ids": ["new"]}],
        "edges": [{"source_id": "x:1", "predicate": "self", "target_id": "x:1", "sst_type": "NEARTO"}],
    }
    diff = semantic_diff(before, after)
    assert diff.concept_id_churn == ()
    assert diff.added_edges == (("x:1", "self", "x:1", "NEARTO"),)
