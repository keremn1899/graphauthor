"""The two reads an agent needed and could not reach.

Both already existed on the operator plane, where only a human could call them.
That put the wrong party in front of each decision:

`classify_absence` — `what_governs` returns UNGOVERNED identically for "nobody
has decided which tier judges sufficiency" and "which log format to use", and
the agent's correct next move differs completely: propose the first, decide the
second locally. The agent is the party standing in front of that fork.

`lineage` — whether a node is source-derived or was legislated by a human last
week changes how much weight an agent should put on it, and the read plane had
no way to ask.

Neither grants any authority: both are deterministic, zero-LLM, and advisory.
The tests that matter here are the ones pinning that they STAY that way.
"""

from __future__ import annotations

import pytest

from mcp_server import stdio


def _tool(name: str):
    return next((t for t in stdio.TOOLS if t.name == name), None)


def test_neither_verb_is_on_this_agent_surface():
    """Both are governance reads and belong to the other product. They stay in
    `Surface` as Python API, and the two tests below still hold them to the
    properties that made them safe — but no agent here is offered them."""

    for name in ("classify_absence", "lineage"):
        assert _tool(name) is None, f"{name} must not be exposed on this surface"


def test_lineage_refuses_an_unknown_node_rather_than_inventing_one():
    """Fabricated provenance is worse than no provenance: it is authority the
    caller cannot audit. An unknown id must be a typed error."""

    from mcp_server.surface import Surface

    surface = Surface.__new__(Surface)
    surface._db_path = __import__("pathlib").Path("does/not/exist.lbug")
    surface._store_path = None
    surface._base = lambda: {}

    out = Surface.lineage(surface, "no_such_node")
    assert "error" in out
    assert "origin" not in out and "root" not in out


@pytest.mark.parametrize("verb", ["classify_absence", "lineage"])
def test_neither_verb_can_write(verb):
    """They read. If either grows a mutation path it stops being safe to hand
    an autonomous caller, so pin it at the source."""

    import inspect

    from mcp_server.surface import Surface

    src = inspect.getsource(getattr(Surface, verb))
    for forbidden in ("CREATE ", "DELETE ", "SET ", "confirm_proposal", "_apply("):
        assert forbidden not in src, f"{verb} must not mutate ({forbidden!r})"
