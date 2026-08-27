"""The sidecar that lets a graph show its own sources.

The gap it closes: `Concept.source_unit_ids` holds atom ids, the passage text
lives in the workbook's `atoms.jsonl`, and nothing beside a built `.lbug`
names the workbook. The join key is exact; only the pointer was missing.

The property that makes a *copy* of the excerpt acceptable rather than a
liability is that drift is detectable. Most of this file is about that, and
about the two ways a stale check can lie: claiming freshness it cannot prove,
and claiming staleness it cannot demonstrate.
"""

from __future__ import annotations

import json

from source_pipeline.sources_sidecar import (
    EXCERPT_CHARS,
    Sources,
    sidecar_path,
    write_sidecar,
)
from source_pipeline.workbook import Atom


def _atom(aid: str, text: str = "Hrafnkel rode to the assembly.", **kw) -> Atom:
    return Atom(
        atom_id=aid,
        source_id=kw.get("source_id", "saga"),
        unit_id=kw.get("unit_id", aid),
        text=text,
        start=kw.get("start", 0),
        end=kw.get("end", len(text)),
        locator=kw.get("locator", "§1"),
        heading_path=kw.get("heading_path", ("Chapter 1",)),
    )


def test_a_node_can_reach_the_passage_it_was_built_from(tmp_path):
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"not really a graph")
    write_sidecar(graph, [_atom("saga#u:1@whole")], source_fingerprint="abc123")

    sources = Sources.for_graph(graph)
    assert sources is not None
    unit = sources.resolve("saga#u:1@whole")
    assert unit is not None
    assert "Hrafnkel" in unit.excerpt
    assert unit.locator == "§1"
    assert unit.heading_path == ("Chapter 1",)


def test_a_graph_with_no_sidecar_degrades_to_none_not_an_error(tmp_path):
    """The common case for every graph built before this existed."""
    graph = tmp_path / "bare.lbug"
    graph.write_bytes(b"x")
    assert Sources.for_graph(graph) is None


def test_a_corrupt_sidecar_does_not_take_the_graph_down(tmp_path):
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    sidecar_path(graph).write_text("{ this is not json")
    assert Sources.for_graph(graph) is None


def test_drift_is_detectable(tmp_path):
    """The property the whole design rests on. Without it the excerpt is a
    copy that can silently disagree with the source, which is worse than not
    showing the source at all."""
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    write_sidecar(graph, [_atom("saga#u:1@whole")], source_fingerprint="build-time")

    sources = Sources.for_graph(graph)
    assert sources.is_stale_against("build-time") is False
    assert sources.is_stale_against("something-else") is True


def test_an_uncomputable_fingerprint_is_not_reported_as_stale(tmp_path):
    """Unknown is not stale.

    A graph copied away from its workbook cannot compute a live fingerprint.
    Reporting that as drift would put a warning on every portable graph, and a
    warning that is usually wrong is one people learn to dismiss -- including
    the time it is right.
    """
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    write_sidecar(graph, [_atom("saga#u:1@whole")], source_fingerprint="build-time")
    assert Sources.for_graph(graph).is_stale_against("") is False


def test_the_excerpt_is_bounded_and_says_when_it_was_cut(tmp_path):
    """A sidecar is not a second copy of the corpus."""
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    long_text = "word " * 2000
    write_sidecar(graph, [_atom("saga#u:1@whole", long_text)],
                  source_fingerprint="f")

    unit = Sources.for_graph(graph).resolve("saga#u:1@whole")
    assert len(unit.excerpt) == EXCERPT_CHARS
    assert unit.truncated is True, "a silently cut excerpt reads as the whole unit"


def test_uncovered_returns_units_that_produced_nothing(tmp_path):
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    atoms = [_atom(f"saga#u:{i}@whole") for i in range(5)]
    write_sidecar(graph, atoms, source_fingerprint="f")

    cited = {"saga#u:0@whole", "saga#u:3@whole"}
    uncovered = Sources.for_graph(graph).uncovered(cited)
    assert uncovered == ["saga#u:1@whole", "saga#u:2@whole", "saga#u:4@whole"]


def test_uncovered_preserves_document_order(tmp_path):
    """A run of uncovered units is a skipped section; scattered ones are not.

    Sorting or set-ordering the result destroys the only thing that
    distinguishes those two, which is the entire signal the coverage view
    exists to show.
    """
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    # ids deliberately not in lexical order
    order = ["saga#u:10@w", "saga#u:2@w", "saga#u:33@w", "saga#u:4@w"]
    write_sidecar(graph, [_atom(a) for a in order], source_fingerprint="f")

    uncovered = Sources.for_graph(graph).uncovered(cited=[])
    assert uncovered == order, "document order was not preserved"


def test_resolve_all_skips_ids_the_sidecar_does_not_have(tmp_path):
    """A node may cite a unit built by a different run. Drop it, do not raise."""
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    write_sidecar(graph, [_atom("saga#u:1@whole")], source_fingerprint="f")

    got = Sources.for_graph(graph).resolve_all(
        ["saga#u:1@whole", "saga#u:absent@whole"])
    assert [u.atom_id for u in got] == ["saga#u:1@whole"]


def test_the_sidecar_is_json_a_human_can_read(tmp_path):
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    path = write_sidecar(graph, [_atom("saga#u:1@whole")],
                         source_fingerprint="f", workbook_root=tmp_path / "wb")
    payload = json.loads(path.read_text())
    assert payload["schema"] == "sources-v1"
    assert payload["unit_count"] == 1
    assert payload["workbook_root"].endswith("wb")


# --- the two id vocabularies -------------------------------------------------
#
# `atom_id` is `{unit_id}@whole` (or `@bounded-<hash>-<i>`). Most construction
# paths record the atom id on a node, but `construction/python_env_reads.py`
# records `unit_id`, and `source_pipeline/workspace_bridge.py` assigns an atom
# id *into* the unit_id field. A sidecar keyed only on atom ids resolves
# nothing for those graphs, and the failure looks exactly like a graph that
# has no sources rather than a join that missed.


def test_a_node_citing_the_unit_id_still_resolves(tmp_path):
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    atom = _atom("saga#u:1@whole", unit_id="saga#u:1")
    write_sidecar(graph, [atom], source_fingerprint="f")

    sources = Sources.for_graph(graph)
    assert sources.resolve("saga#u:1@whole") is not None, "atom id must work"
    assert sources.resolve("saga#u:1") is not None, (
        "unit id must work too -- python_env_reads writes this form"
    )


def test_one_unit_cut_into_several_atoms_returns_all_of_them(tmp_path):
    """Collapsing a real one-to-many to one silently drops evidence."""
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    atoms = [
        _atom("saga#u:1@bounded-aa-0", "First half.", unit_id="saga#u:1"),
        _atom("saga#u:1@bounded-aa-1", "Second half.", unit_id="saga#u:1"),
    ]
    write_sidecar(graph, atoms, source_fingerprint="f")

    got = Sources.for_graph(graph).resolve_unit("saga#u:1")
    assert [u.atom_id for u in got] == [
        "saga#u:1@bounded-aa-0", "saga#u:1@bounded-aa-1"]


def test_resolution_is_exact_and_never_guesses(tmp_path):
    """Positive control for the lookup being exact.

    Without this, an implementation that prefix-matched would pass every test
    above while resolving `saga#u:1` to `saga#u:10`'s text -- showing a reader
    a passage their node was not built from, which is worse than showing none.
    """
    graph = tmp_path / "g.lbug"
    graph.write_bytes(b"x")
    write_sidecar(
        graph,
        [_atom("saga#u:10@whole", "Text of unit ten.", unit_id="saga#u:10")],
        source_fingerprint="f",
    )
    sources = Sources.for_graph(graph)
    assert sources.resolve("saga#u:1") is None
    assert sources.resolve("saga#u:10") is not None


def test_dict_shaped_atoms_write_the_same_sidecar_as_objects(tmp_path):
    """Construction hands units around as both dataclasses and plain dicts.

    An attribute-only reader writes a sidecar of empty rows for the dict case
    and raises nothing, so the failure arrives much later as "this graph has
    no sources" on a graph that does.
    """
    a = tmp_path / "a.lbug"; a.write_bytes(b"x")
    b = tmp_path / "b.lbug"; b.write_bytes(b"x")

    atom = _atom("saga#u:1@whole", "The passage.", unit_id="saga#u:1")
    write_sidecar(a, [atom], source_fingerprint="f")
    write_sidecar(b, [atom.to_json()], source_fingerprint="f")

    from_obj = Sources.for_graph(a).resolve("saga#u:1@whole")
    from_dict = Sources.for_graph(b).resolve("saga#u:1@whole")
    assert from_dict is not None, "dict-shaped atoms produced nothing"
    assert from_obj.to_json() == from_dict.to_json()
