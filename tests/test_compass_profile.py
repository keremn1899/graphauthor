"""Graph Compass facts the product still depends on.

Ported out of `test_v7_compass.py` when `legacy_fsm/` was deleted. That file
was four tests of the planner's briefing formatter and two of the Compass
itself; the formatter went with the FSM, the Compass did not.

`format_layer1` — the one piece of that briefing the product still calls, now
`mcp_server/compass_briefing.py` — is covered here too, since nothing else
exercised it once the planner's own tests were gone.
"""

from __future__ import annotations

from engine import compute_compass, compute_structural_index
from mcp_server.compass_briefing import format_layer1


def test_compass_reports_role_populations(deps_conn):
    index = compute_structural_index(deps_conn)
    profile = compute_compass(deps_conn, index).graph_profile
    assert "role_populations" in profile
    assert "total_edges" in profile
    assert sum(profile["role_populations"].values()) > 0


def test_every_census_entry_carries_an_anchor_preview_field(deps_conn):
    """Present-but-empty and missing are different facts; the census must not
    make a caller guess which it is looking at."""
    index = compute_structural_index(deps_conn)
    census = compute_compass(deps_conn, index).node_census
    assert census
    for entry in census:
        assert "anchor_preview" in entry
    assert any(entry.get("anchor_preview") for entry in census)




def test_layer1_omits_what_the_profile_does_not_carry():
    """Absent fields are skipped, never rendered as a guess. A graph that does
    not record its grain must not be described as having one."""
    lines = format_layer1({"node_count": 3, "total_edges": 2})
    body = "\n".join(lines)
    assert "Grain" not in body
    assert "Role populations" not in body
    assert "Nodes: 3" in body


def test_layer1_renders_the_profile_the_compass_produces(deps_conn):
    """The formatter and its only input, checked against each other.

    It used to live in the planner, and `mcp_server/ask.py` imported three
    thousand lines of dead code to format ten lines of text. Nothing tested it
    directly until the planner's own tests were deleted with it.
    """
    index = compute_structural_index(deps_conn)
    profile = compute_compass(deps_conn, index).graph_profile
    lines = format_layer1(profile)

    assert lines[0].startswith("## LAYER 1")
    body = "\n".join(lines)
    assert "Nodes:" in body and "Edges:" in body
    assert "Role populations:" in body
