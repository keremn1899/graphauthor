"""A Surface answers from its own graph, even after another one is opened.

`engine` holds the connection, structural index, compass, grain and source-unit
index in module globals, and every `GraphSession` property is a live view of
them. Constructing a second `Surface` therefore redirected every existing one to
the newest graph, and the redirected surface kept answering — well-formed, fully
populated, and from the wrong graph. It was found by an ablation whose
node-graph questions came back citing rules that only exist in a different
corpus. No degradation flag, no error, nothing in the payload.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import engine
from mcp_server.surface import Surface


def _tiny_graph(path: Path, marker: str):
    """Two distinct one-node graphs, no API key — see mcp_server.fixture."""
    from mcp_server.fixture import _write_graph

    nodes = [(f"n_{marker}", f"node {marker}", f"body {marker}", 3, f"anchor {marker}")]
    _write_graph(nodes, [], path)
    return path


@pytest.fixture
def two_graphs(tmp_path):
    a, b = tmp_path / "a.lbug", tmp_path / "b.lbug"
    _tiny_graph(a, "alpha")
    _tiny_graph(b, "beta")
    engine.reset_connection()
    yield a, b
    engine.reset_connection()


def _node_ids(surface):
    with surface._read_guard():
        result = surface._session.connection.execute("MATCH (c:Concept) RETURN c.id")
        out = []
        while result.has_next():
            out.append(result.get_next()[0])
    return sorted(out)


def test_a_surface_keeps_its_own_graph_after_another_is_opened(two_graphs):
    a, b = two_graphs
    first = Surface(a)
    assert _node_ids(first) == ["n_alpha"]

    second = Surface(b)
    assert _node_ids(second) == ["n_beta"]

    # The bug: this returned n_beta.
    assert _node_ids(first) == ["n_alpha"], (
        "the first surface answered from the second surface's graph"
    )


def test_interleaving_two_surfaces_stays_correct_in_both_directions(two_graphs):
    a, b = two_graphs
    first, second = Surface(a), Surface(b)

    for _ in range(3):
        assert _node_ids(first) == ["n_alpha"]
        assert _node_ids(second) == ["n_beta"]


def test_repin_is_a_no_op_when_the_graph_is_already_current(two_graphs):
    """It must not reopen on every read — only on an actual switch."""
    a, _ = two_graphs
    surface = Surface(a)
    _node_ids(surface)

    opened = []
    original = surface._session.open
    surface._session.open = lambda *args, **kw: (opened.append(args), original(*args, **kw))[1]
    _node_ids(surface)
    _node_ids(surface)
    assert opened == [], "re-pinned a graph that was already current"
