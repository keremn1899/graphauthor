"""`graph_version` must answer "is this the same graph", not "is this the same process".

It answered the second. `get_graph_version` hashed the DB file mtime plus the
node count, and LadybugDB touches the file on open, so every process start
minted a new version for a graph nobody had touched. Caching the value per
session hid it completely, because a test is one process and a benchmark is one
process — the churn was only visible across restarts, which nothing exercised.

Measured on the snapshot stores in this tree at the time of the repair: 287
recorded versions over 42 distinct graph contents. 245 phantom commits, 606 MB
of duplicate `.lbug` copies, and one store — `data/construction_runs/operator`
— showing 40 versions of a graph that never changed once.

So these tests come in two halves, and the second is the important one. Pinning
stability alone would be satisfied by a constant.

One caveat on how to read a red run here against the old implementation. These
tests open raw `lb.Connection`s, and the old `get_graph_version` read
`engine._db_path`, a module global that only `get_connection` sets — so under
this harness the old hash collapsed to a constant and the node-field cases
failed for the wrong reason. The faithful before/after was measured through the
real server: five stdio restarts on one unchanged graph gave five versions
before and one after. The new function takes only a connection and reads no
global, which is part of the repair.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import real_ladybug as lb

from engine import get_graph_version
from mcp_server.fixture import ensure_fixture
from mcp_server.history import SnapshotStore, graph_fingerprint
from mcp_server.pr_gate import receipt_status


def _copy(src: Path, dst: Path) -> Path:
    (shutil.copytree if Path(src).is_dir() else shutil.copy2)(src, dst)
    return dst


@pytest.fixture
def graph(tmp_path: Path) -> Path:
    return _copy(Path(ensure_fixture("runtime/hexagonal_orders.lbug")), tmp_path / "g.lbug")


def _version(path: Path) -> str:
    """Read the version the way a fresh server start does: open, ask, close."""
    db = lb.Database(str(path))
    conn = lb.Connection(db)
    try:
        return get_graph_version(conn)
    finally:
        del conn, db


def _mutate(path: Path, cypher: str) -> None:
    db = lb.Database(str(path))
    conn = lb.Connection(db)
    conn.execute(cypher)
    del conn, db


def _first_id(path: Path) -> str:
    db = lb.Database(str(path))
    conn = lb.Connection(db)
    try:
        rows = conn.execute("MATCH (c:Concept) RETURN c.id ORDER BY c.id LIMIT 1")
        return str(rows.get_next()[0])
    finally:
        del conn, db


# --- half one: it must not move on its own ---------------------------------

def test_reopening_an_untouched_graph_does_not_mint_a_new_version(graph):
    assert len({_version(graph) for _ in range(4)}) == 1


def test_identical_content_at_another_path_is_the_same_version(graph, tmp_path):
    """The semantics a receipt needs: same governance text, same adjudication.

    The old hash mixed the path in, so moving a graph invalidated every receipt
    bound to it even though nothing a rule could read had changed.
    """
    assert _version(_copy(graph, tmp_path / "elsewhere.lbug")) == _version(graph)


# --- half two: it must move when the graph does ----------------------------

@pytest.mark.parametrize("field,cypher", [
    ("label", "SET c.label = 'renamed'"),
    ("text_content", "SET c.text_content = 'different prose'"),
    ("claim_kind", "SET c.claim_kind = 'contextual'"),
    ("semantic_anchor", "SET c.semantic_anchor = 'moved'"),
])
def test_a_node_field_a_reader_can_act_on_moves_the_version(graph, field, cypher):
    """`claim_kind` is why the list is not just label and text.

    Demoting a node from governing changes no count and no mtime, and it
    decides whether the graph can return a governed verdict at all. A version
    that missed it would let a receipt outlive the authority it was issued
    under.
    """
    before = _version(graph)
    _mutate(graph, f"MATCH (c:Concept) WHERE c.id = '{_first_id(graph)}' {cypher}")
    assert _version(graph) != before, f"{field} changed without moving the version"


def test_an_edge_relabel_moves_the_version(graph):
    before = _version(graph)
    _mutate(graph, "MATCH (:Concept)-[r:CONTAINS]->(:Concept) SET r.label = 'renamed'")
    assert _version(graph) != before


# --- the identity function is one function ---------------------------------

def test_version_and_fingerprint_are_the_same_definition(graph):
    """Two identity functions that disagree is how this defect survived.

    `graph_fingerprint` was already content-true and used for proposal
    staleness; `get_graph_version` was mtime-based and used for retrieval
    preconditions and gate receipts. The repair to the first never reached the
    second.
    """
    assert _version(graph) == "gv_" + graph_fingerprint(graph)[:12]


def test_an_unreadable_graph_gets_a_sentinel_not_an_invented_version():
    class _Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("graph is unreadable")

    assert get_graph_version(_Broken()) == "gv_unreadable"


# --- what it cost downstream ------------------------------------------------

def test_restarting_the_server_does_not_record_a_commit(graph):
    """`SnapshotStore.capture` is idempotent per version, and the version never
    repeated — so history recorded a commit, and copied the whole DB, every
    time the process started."""
    for _ in range(5):
        SnapshotStore(graph).capture(_version(graph))
    assert len(SnapshotStore(graph).versions()) == 1

    _mutate(graph, f"MATCH (c:Concept) WHERE c.id = '{_first_id(graph)}' SET c.label = 'x'")
    SnapshotStore(graph).capture(_version(graph))
    assert len(SnapshotStore(graph).versions()) == 2


def test_a_gate_receipt_survives_a_restart_but_not_a_graph_change(graph):
    """`graph_changed` is the anti-rationalization signal, and it was firing on
    restarts — telling the operator governance had moved under a checked diff
    when nothing had moved."""
    issued = {"diff_hash": "d1", "graph_version": _version(graph)}
    _version(graph)  # a restart
    assert receipt_status(
        issued, current_diff_hash="d1", current_graph_version=_version(graph)
    ) == {"valid": True, "stale_reason": ""}

    _mutate(graph, f"MATCH (c:Concept) WHERE c.id = '{_first_id(graph)}' SET c.claim_kind = 'contextual'")
    assert receipt_status(
        issued, current_diff_hash="d1", current_graph_version=_version(graph)
    ) == {"valid": False, "stale_reason": "graph_changed"}
