"""The first write of a greenfield project, from nothing.

A graph-driven project begins with an empty directory and a constitution
nobody has encoded yet, so the very first proposal is authored against a graph
that does not exist. That path used to surface as a raw Ladybug
`Binder exception: Table Concept does not exist` — accurate, and useless: it
does not say the schema is missing, does not say an empty graph would have
worked, and does not say which of the two schema definitions in this tree to
create it with.

The distinction these tests hold apart is the whole cold-start ladder:

    no schema        -> refuse, and say how to fix it
    schema, 0 nodes  -> ACCEPT; this is a legitimate greenfield graph
    schema, n nodes  -> ACCEPT, the ordinary case
"""
from __future__ import annotations

from pathlib import Path

import pytest
import real_ladybug as lb

from mcp_server.proposals import UninitialisedGraphError, _existing_ids, validate_proposal

CONSTITUTION_NODE = {
    "concepts": [{
        "id": "rule_no_pii_in_logs",
        "label": "No PII in logs",
        "text_content": "Services MUST NOT write personal data to application logs.",
        "semantic_anchor": "logging of personal data",
    }],
    "edges": [],
}


def _schema_only(path: Path) -> Path:
    """A graph with tables and no rows.

    Uses the existing fixture helper rather than spelling the schema out again.
    There are already three `CREATE NODE TABLE Concept` definitions in this tree
    and only `engine.py`'s carries `claim_kind`; a fourth copy here would be the
    same mistake with a test's name on it. What this fixture proves is narrow
    and schema-independent: a Concept table with zero rows is enough.
    """
    from mcp_server.fixture import _create_schema

    db = lb.Database(str(path))
    conn = lb.Connection(db)
    _create_schema(conn)
    del conn, db
    return path


def test_proposing_against_no_schema_is_a_refusal_not_a_binder_exception(tmp_path):
    prop, err = validate_proposal(CONSTITUTION_NODE, tmp_path / "absent.lbug")

    assert prop is None
    assert "no schema yet" in err
    # The message has to carry the fix, because the fix is not guessable: an
    # empty graph works, so "create the graph" is the whole answer.
    assert "engine" in err and "claim_kind" in err


def test_the_underlying_read_raises_a_named_error_not_a_database_message(tmp_path):
    with pytest.raises(UninitialisedGraphError):
        _existing_ids(tmp_path / "absent.lbug")


def test_an_empty_graph_with_a_schema_accepts_the_first_constitution_node(tmp_path):
    """The greenfield state proper — and it must not be refused.

    There is no bootstrap paradox here: nothing needs to be seeded before the
    first authored node. Were this to start refusing, a constitution could only
    be created by some privileged path outside propose/confirm, and every
    founding node would lose its PrimarySource.
    """
    prop, err = validate_proposal(
        CONSTITUTION_NODE, _schema_only(tmp_path / "greenfield.lbug")
    )

    assert prop is not None, err
    assert [c.id for c in prop.concepts] == ["rule_no_pii_in_logs"]
