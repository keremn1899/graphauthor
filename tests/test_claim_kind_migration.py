"""The claim-kind columns, added to graphs that were built before them.

Every `.lbug` on disk predates these columns, so "open a graph that does not
have them" is the normal case and not the edge case. Both directions are
pinned: a pre-migration graph must read correctly, and a migrated one must
round-trip the value.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import real_ladybug as lb  # noqa: E402

import normative  # noqa: E402
from engine import migrate_claim_kind_columns  # noqa: E402
from tools import get_node_payloads  # noqa: E402


@pytest.fixture()
def legacy_graph():
    """A graph with the pre-claim_kind Concept schema."""
    tmp = Path(tempfile.mkdtemp(prefix="sst_claimkind_"))
    try:
        conn = lb.Connection(lb.Database(str(tmp / "g.lbug")))
        conn.execute(
            "CREATE NODE TABLE Concept ("
            "  id STRING, label STRING, text_content STRING,"
            "  semantic_anchor STRING, token_count INT64,"
            "  PRIMARY KEY (id))"
        )
        conn.execute(
            "CREATE (:Concept {id: 'rule', label: 'RC-1', "
            "text_content: '# RC-1\\n\\nADJUDICATES: sign every release.', "
            "semantic_anchor: 'release rule', token_count: 12})"
        )
        conn.execute(
            "CREATE (:Concept {id: 'ctx', label: 'Legacy note', "
            "text_content: 'CONTEXT: one approval used to be enough.', "
            "semantic_anchor: 'legacy', token_count: 9})"
        )
        yield conn
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_pre_migration_graph_still_pages_in(legacy_graph):
    """The read path must not require the column to exist."""
    payloads = get_node_payloads(legacy_graph, ["rule", "ctx"])
    assert set(payloads) == {"rule", "ctx"}
    assert "claim_kind" not in payloads["rule"], (
        "a column the graph does not have was reported as present")
    # …and the legacy text prefix still resolves.
    assert normative.classify(payloads["rule"]).kind == normative.GOVERNING
    assert normative.classify(payloads["ctx"]).kind == normative.CONTEXTUAL


def test_migration_adds_the_columns_and_is_idempotent(legacy_graph):
    added = migrate_claim_kind_columns(legacy_graph)
    assert added == ["claim_kind", "claim_kind_source"]
    # Second call is the normal case on every subsequent open.
    assert migrate_claim_kind_columns(legacy_graph) == []


def test_migration_defaults_to_empty_so_the_prefix_still_governs(legacy_graph):
    """Migrating must not silently reclassify anything.

    A freshly added column is empty, and empty must mean "no stored answer" so
    resolution falls through to the prefix — not "this node is not a rule".
    """
    migrate_claim_kind_columns(legacy_graph)
    payloads = get_node_payloads(legacy_graph, ["rule"])
    assert payloads["rule"]["claim_kind"] == ""
    assert normative.classify(payloads["rule"]).kind == normative.GOVERNING
    assert normative.classify(payloads["rule"]).source == normative.DECLARED_PREFIX
    assert normative.classify(payloads["rule"]).grants_authority


def test_a_written_claim_kind_round_trips_and_wins(legacy_graph):
    migrate_claim_kind_columns(legacy_graph)
    legacy_graph.execute(
        "MATCH (c:Concept {id: 'rule'}) SET c.claim_kind = 'contextual', "
        "c.claim_kind_source = 'classified'"
    )
    payloads = get_node_payloads(legacy_graph, ["rule"])
    result = normative.classify(payloads["rule"])
    assert result.kind == normative.CONTEXTUAL, (
        "the stored column lost to the stale text prefix")
    assert result.source == normative.CLASSIFIED


def test_migration_on_a_graph_without_concept_does_not_raise():
    """Opening something odd must degrade, not kill the process."""
    tmp = Path(tempfile.mkdtemp(prefix="sst_claimkind_"))
    try:
        conn = lb.Connection(lb.Database(str(tmp / "empty.lbug")))
        assert migrate_claim_kind_columns(conn) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
