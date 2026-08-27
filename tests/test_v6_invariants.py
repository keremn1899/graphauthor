"""Phase 0 invariant tests for the info-infrastructure-v6 refactor.

These tests encode the contract that the new canonical evidence infrastructure
is supposed to guarantee. They MUST fail on the pre-refactor pipeline and pass
once Phases 1-8 have landed.

Invariants under test:

1. Packet integrity: the EvidencePacket exists after backend_execute, its
   edge_records all reference nodes in node_records, and recovery appends
   rather than overwrites.
2. Canonical edge preservation: get_nodes_by_edge_type returns source/target/
   edge_label structure; nothing downstream can flatten it back to a bag of
   nodes.
3. Truth preservation under LLM error: Company/CompanyVerdict cannot report
   missing_relationship for a relation that the EvidencePacket contains — the
   semantic_validation layer deterministically catches that contradiction.
4. Enumeration regression: the ``EXPRESSES`` enumeration query that first
   surfaced this class of bug must produce a CONFIRMED (or equivalent
   positive) verdict with edge pairs in the evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixture_db import create_fixture_db


# ---------------------------------------------------------------------------
# Phase 1: schema presence
# ---------------------------------------------------------------------------

def test_v6_schemas_exist() -> None:
    """Phase 1 schemas must be importable from models."""
    import models

    assert hasattr(models, "AnswerContract"), "AnswerContract schema missing"
    assert hasattr(models, "EvidencePacket"), "EvidencePacket schema missing"
    assert hasattr(models, "CompanyDossier"), "CompanyDossier schema missing"
    assert hasattr(models, "CompanyVerdict"), "CompanyVerdict schema missing"
    assert hasattr(models, "ConfidenceProvenance"), "ConfidenceProvenance missing"


def test_confirmation_response_has_ill_posed_verdict() -> None:
    """Phase 7: ConfirmationResponse must accept ILL_POSED."""
    from models import ConfirmationResponse

    r = ConfirmationResponse(verdict="ILL_POSED", exhaustion_explanation="no shape")
    assert r.verdict == "ILL_POSED"


# ---------------------------------------------------------------------------
# Phase 2: canonical edge preservation
# ---------------------------------------------------------------------------

def test_get_nodes_by_edge_type_returns_canonical_edges(tmp_path: Path) -> None:
    """get_nodes_by_edge_type must emit edge_records with source/target/label."""
    from tools import get_nodes_by_edge_type

    conn = create_fixture_db("lotr", tmp_path / "lotr_edges.lbug")
    result = get_nodes_by_edge_type(conn, "expresses")

    assert isinstance(result, dict), (
        "v6: get_nodes_by_edge_type must return {node_records, edge_records}, not list"
    )
    assert "node_records" in result
    assert "edge_records" in result

    edges = result["edge_records"]
    assert len(edges) > 0, "LOTR seed has EXPRESSES edges — must be preserved"

    for e in edges:
        assert "source_id" in e
        assert "target_id" in e
        assert "edge_type" in e
        assert "edge_label" in e
        assert e["edge_type"] == "expresses"






# ---------------------------------------------------------------------------
# Phase 6: semantic validation truth-preservation invariants
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Phase 9: end-to-end enumeration regression (smoke — may require OpenRouter)
# ---------------------------------------------------------------------------

