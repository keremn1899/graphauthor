"""Two ops that compiled, executed, and answered wrongly.

Both were found by running one-shot programs against a real constructed graph
and checking each answer against the same set computed a second way. Neither
is reachable by reading the code: the step validates, the run reports FOUND,
and the number returned is plausible.

`union` had two spellings and only one of them arrived. `of: [$a, $b]` works --
the executor flattens the list -- but `of: $a` with `with: $b` compiled with no
second operand in its params at all and returned `$a`. On a saga graph the
union of two places' casts, eight characters and three, answered eight.

`walk_sequence` applied its `kinds` filter at every hop rather than to its
result. A `character -> event -> place` walk asking for places died on the
first hop, because an event is not a place, and returned nothing -- which this
format's `empty_means: bounded_no_result` states as "there are no such
places". The same walk as two `expand` steps returned three.
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


def _answer(surface, steps, answer, **spec) -> list[str]:
    program = {"name": "probe", "steps": steps, "collect": f"${answer}",
               "answers": [answer],
               "limits": {"max_steps": 12, "max_hops": 4, "max_nodes": 200}}
    program.update(spec)
    result = surface.run_ephemeral_traversal(program, {}, evidence="packet")
    if result["outcome"] == "INVALID_RECIPE":
        raise AssertionError(result["errors"])
    return sorted(result.get("answer_node_ids") or [])


def _cast_of(place: str, tag: str) -> list[dict]:
    """The characters at one place: two hops, against the arrows."""
    return [
        {"op": "lookup", "references": [place], "assign": tag},
        {"op": "expand", "from": f"${tag}", "predicates": ["occurs_at"],
         "direction": "incoming", "depth": 1, "max_nodes": 60,
         "kinds": ["event"], "assign": f"{tag}_events"},
        {"op": "expand", "from": f"${tag}_events",
         "predicates": ["participates_in"], "direction": "incoming",
         "depth": 1, "max_nodes": 60, "kinds": ["character"],
         "assign": f"{tag}_cast"},
    ]


LANDING, TERRACE = "place:the-landing", "place:the-terrace"


# --- union -------------------------------------------------------------

def test_both_spellings_of_union_return_the_same_set(surface):
    steps = _cast_of(LANDING, "l") + _cast_of(TERRACE, "r")

    left = _answer(surface, _cast_of(LANDING, "l"), "l_cast")
    right = _answer(surface, _cast_of(TERRACE, "r"), "r_cast")
    with_form = _answer(surface, steps + [
        {"op": "union", "of": "$l_cast", "with": "$r_cast", "assign": "both"},
    ], "both")
    list_form = _answer(surface, steps + [
        {"op": "union", "of": ["$l_cast", "$r_cast"], "assign": "both"},
    ], "both")

    assert with_form == list_form
    # The control the original bug slipped past: a union that returned only
    # its left operand equals `left`, and `left` is a perfectly good-looking
    # answer. Assert the union is strictly larger than either side.
    assert set(with_form) == set(left) | set(right)
    assert len(with_form) > len(left) and len(with_form) > len(right)


def test_a_union_of_one_set_is_refused(surface):
    program = {
        "name": "one_sided_union",
        "steps": _cast_of(LANDING, "l") + [
            {"op": "union", "of": "$l_cast", "assign": "both"}],
        "collect": "$both", "answers": ["both"],
        "limits": {"max_steps": 8, "max_hops": 3, "max_nodes": 60},
    }
    result = surface.run_ephemeral_traversal(program, {}, evidence="packet")
    assert result["outcome"] == "INVALID_RECIPE"
    assert "union" in " ".join(result["errors"])


# --- walk_sequence -----------------------------------------------------

def _walk(kinds=None) -> list[dict]:
    step = {"op": "walk_sequence", "from": "$seed",
            "predicates": ["participates_in", "occurs_at"],
            "direction": "outgoing", "max_nodes": 60, "assign": "walked"}
    if kinds is not None:
        step["kinds"] = kinds
    return [{"op": "lookup", "references": ["character:ilma"], "assign": "seed"},
            step]


def test_a_kind_filter_narrows_a_walk_rather_than_killing_it(surface):
    """The same question, two ways, and they have to agree."""
    chained = _answer(surface, [
        {"op": "lookup", "references": ["character:ilma"], "assign": "seed"},
        {"op": "expand", "from": "$seed", "predicates": ["participates_in"],
         "direction": "outgoing", "depth": 1, "max_nodes": 60,
         "kinds": ["event"], "assign": "events"},
        {"op": "expand", "from": "$events", "predicates": ["occurs_at"],
         "direction": "outgoing", "depth": 1, "max_nodes": 60,
         "kinds": ["place"], "assign": "places"},
    ], "places")
    walked = _answer(surface, _walk(kinds=["place"]), "walked")

    assert walked == chained
    assert walked, "an empty answer would pass this for the wrong reason"
    assert all(node_id.startswith("place:") for node_id in walked)


def test_an_unfiltered_walk_carries_what_it_passed_through(surface):
    """So the filter above is demonstrably doing something.

    Without this, `kinds` could be ignored entirely and the test above would
    still pass whenever the walk happened to end on the right kind.
    """
    walked = _answer(surface, _walk(), "walked")
    assert any(node_id.startswith("event:") for node_id in walked)
    assert any(node_id.startswith("place:") for node_id in walked)
