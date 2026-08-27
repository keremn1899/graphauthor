"""What a traversal returns as its *answer*, as opposed to as evidence.

Three defects found by running one-shot programs against a real constructed
graph rather than a fixture, all of the same family: the machinery knew which
nodes were the answer and no caller could tell.

1. The evidence packet is every node the walk touched. A `difference` over two
   characters' places answered four places inside a fifty-node packet and
   nothing in `node_records` marked which four.
2. `answers` -- the field that decides EMPTY against FOUND -- was read only by
   the named verb. An identical five-step program reported EMPTY as a recipe
   and FOUND as an ephemeral one, over the same six-node packet with no
   bridges in it. The ephemeral verb's whole promise is that a program keeps
   its semantics when it is promoted to a name.
3. `who_bridges` declared `place` endpoints it could not serve: a character is
   one hop from a faction and from an event, but two hops from a place. Every
   place pair returned EMPTY, and this format says EMPTY means "no bridges".
   On a real saga graph Aðalból and Þingvöll have two bridging characters and
   the recipe answered "nobody". Both of its fixtures used factions.
"""

from __future__ import annotations

import pytest

from mcp_server.surface import Surface
from tests.workbook_graph_fixture import narrative_fixture


@pytest.fixture()
def surface(tmp_path):
    db_path, contract_path = narrative_fixture(tmp_path / "narrative.lbug")
    surface = Surface(db_path, graph_contract_path=contract_path)
    try:
        yield surface
    finally:
        surface.close()


def _bridge_program(left: str, right: str) -> dict:
    """`who_bridges`, written out as a one-shot program, step for step."""
    return {
        "name": "bridges_inline",
        "steps": [
            {"op": "lookup", "references": [left], "assign": "left_seed"},
            {"op": "lookup", "references": [right], "assign": "right_seed"},
            {"op": "expand", "from": "$left_seed", "direction": "both",
             "depth": 1, "max_nodes": 60, "kinds": ["character"],
             "assign": "left_side"},
            {"op": "expand", "from": "$right_seed", "direction": "both",
             "depth": 1, "max_nodes": 60, "kinds": ["character"],
             "assign": "right_side"},
            {"op": "intersection", "of": "$left_side", "with": "$right_side",
             "assign": "bridges"},
        ],
        "collect": "$bridges",
        "answers": ["bridges"],
        "limits": {"max_steps": 8, "max_hops": 3, "max_nodes": 60},
    }


def _packet_ids(result) -> list[str]:
    return [row.get("id") for row
            in (result.get("evidence") or {}).get("node_records") or []]


# --- the answer is named, and marked in the packet ----------------------

def test_the_answer_is_named_and_marked_inside_a_wider_packet(surface):
    result = surface.run_traversal(
        "who_bridges",
        {"left_id": "faction:the-quay", "right_id": "faction:the-uplands"},
        evidence="packet")

    assert result["outcome"] == "FOUND"
    assert result["answer_node_ids"] == ["character:ilma"]

    rows = (result.get("evidence") or {}).get("node_records") or []
    marked = [row["id"] for row in rows if row.get("is_answer")]
    assert marked == ["character:ilma"]
    # The point of the marking: the packet is wider than the answer, on
    # purpose, and Torv is legitimately in it.
    assert "character:torv" in _packet_ids(result)


def test_a_path_answer_names_node_ids_rather_than_records(surface):
    """`find_paths` assigns dicts, not ids.

    The first version of this stringified them, so `answer_node_ids` held four
    `repr` blobs, matched no packet row and marked nothing -- a field that
    reads as an answer while naming none of the graph.
    """
    result = surface.run_traversal(
        "how_are_they_connected",
        {"from_id": "character:ilma", "to_id": "character:torv"},
        evidence="packet")

    assert result["outcome"] == "FOUND"
    assert result["answer_node_ids"], "a FOUND path traversal named no answer"
    assert all(":" in node_id and "{" not in node_id
               for node_id in result["answer_node_ids"])
    assert set(result["answer_node_ids"]) <= set(_packet_ids(result))


def test_a_recipe_that_names_no_answer_gets_no_answer_field(surface):
    """Absent, not empty: `[]` would read as "this traversal found nothing"."""
    result = surface.run_traversal(
        "what_led_to", {"event_id": "event:the-breaking"}, evidence="packet")
    assert result["outcome"] == "FOUND"
    assert "answer_node_ids" not in result


# --- the named and ephemeral verbs must agree ---------------------------

@pytest.mark.parametrize("left, right", [
    ("faction:the-quay", "faction:the-uplands"),   # one bridge
    ("event:the-refusal", "event:the-summons"),    # one bridge
])
def test_an_inline_program_agrees_with_the_recipe_it_copies(surface, left, right):
    named = surface.run_traversal(
        "who_bridges", {"left_id": left, "right_id": right}, evidence="packet")
    inline = surface.run_ephemeral_traversal(
        _bridge_program(left, right), {}, evidence="packet")

    assert inline["outcome"] == named["outcome"]
    assert inline["answer_node_ids"] == named["answer_node_ids"]


def test_an_inline_program_reports_empty_where_the_recipe_does(surface):
    """The measured divergence, in the only shape that could hide.

    With a non-empty packet and an empty answer the two verbs disagreed:
    EMPTY from the recipe, FOUND from the identical inline program. A
    non-empty answer would have agreed for the wrong reason.
    """
    left, right = "event:the-refusal", "event:the-tally-count"
    named = surface.run_traversal(
        "who_bridges", {"left_id": left, "right_id": right}, evidence="packet")
    inline = surface.run_ephemeral_traversal(
        _bridge_program(left, right), {}, evidence="packet")

    assert named["outcome"] == "EMPTY"
    assert inline["outcome"] == "EMPTY"
    assert _packet_ids(inline), "an empty packet would make this pass for free"


def test_an_inline_answer_variable_no_step_assigns_is_refused(surface):
    program = _bridge_program("faction:the-quay", "faction:the-uplands")
    program["answers"] = ["bridge"]      # the variable is `bridges`

    result = surface.run_ephemeral_traversal(program, {}, evidence="packet")
    assert result["outcome"] == "INVALID_RECIPE"
    assert "bridge" in " ".join(result["errors"])


def test_an_inline_program_without_answers_still_runs(surface):
    """Declaring an answer stays optional; the packet is then the answer."""
    program = _bridge_program("faction:the-quay", "faction:the-uplands")
    program.pop("answers")

    result = surface.run_ephemeral_traversal(program, {}, evidence="packet")
    assert result["outcome"] == "FOUND"
    assert "answer_node_ids" not in result


# --- a recipe may not accept an endpoint kind it cannot serve -----------

def test_who_bridges_refuses_a_place_rather_than_answering_nobody(surface):
    result = surface.run_traversal(
        "who_bridges",
        {"left_id": "place:the-landing", "right_id": "place:the-terrace"},
        evidence="packet")
    assert result["outcome"] == "INVALID_RECIPE"


def test_the_two_hop_recipe_answers_the_place_question(surface):
    result = surface.run_traversal(
        "who_was_at_both_places",
        {"left_id": "place:the-landing", "right_id": "place:the-terrace"},
        evidence="packet")
    assert result["outcome"] == "FOUND"
    # Ilma is at both; Torv is only at the terrace. Asserting the exact set
    # rather than membership, because a two-hop walk that forgot to intersect
    # would contain Ilma too.
    assert result["answer_node_ids"] == ["character:ilma"]
