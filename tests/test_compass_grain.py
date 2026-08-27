"""The Compass must say how finely the graph cuts its sources.

The Planner could read density, depth and edge-type ratios and still had no
way to tell whether a node was a paragraph or a sentence — `source_unit_ids`
died at materialization. That number decides how many nodes must be
co-retrieved to reconstitute one section: on the repo-architecture arm the
median was 15 against a Squad budget of 8-12, so one module interface consumed
the entire budget and its largest unit could not be retrieved in one pass.

Reported, never bounded. Fine grain is a legitimate choice — those
one-sentence rule nodes are what let a caller name the specific constraints a
proposed change would have to respect.
"""

from __future__ import annotations

import real_ladybug as lb

from engine import _grain_profile


def _graph(tmp_path, rows, *, with_column=True):
    conn = lb.Connection(lb.Database(str(tmp_path / "g.lbug")))
    columns = "id STRING, text_content STRING"
    if with_column:
        columns += ", source_unit_ids STRING[]"
    conn.execute(f"CREATE NODE TABLE Concept ({columns}, PRIMARY KEY (id))")
    for node_id, text, units in rows:
        if with_column:
            conn.execute(
                "CREATE (c:Concept {id: $id, text_content: $t, source_unit_ids: $u})",
                {"id": node_id, "t": text, "u": units},
            )
        else:
            conn.execute(
                "CREATE (c:Concept {id: $id, text_content: $t})",
                {"id": node_id, "t": text},
            )
    return conn


def test_many_nodes_from_one_unit_reads_as_fine(tmp_path):
    rows = [(f"n{i}", "x" * 110, ["u1"]) for i in range(15)]
    profile = _grain_profile(_graph(tmp_path, rows), len(rows))

    assert profile["nodes_per_source_unit_median"] == 15
    assert profile["source_units"] == 1
    assert profile["grain_attributed_fraction"] == 1.0
    assert profile["grain_character"].startswith("fine")
    assert "co-retrieving" in profile["grain_character"]


def test_one_node_per_unit_reads_as_coarse(tmp_path):
    rows = [(f"n{i}", "x" * 900, [f"u{i}"]) for i in range(6)]
    profile = _grain_profile(_graph(tmp_path, rows), len(rows))

    assert profile["nodes_per_source_unit_median"] == 1
    assert profile["grain_character"].startswith("coarse")
    assert profile["payload_chars_p50"] == 900


def test_the_max_is_reported_because_the_median_hides_the_worst_unit(tmp_path):
    """One oversized unit is what breaks a budget, and a median will not show it."""

    rows = [(f"a{i}", "x", ["u1"]) for i in range(27)]
    rows += [(f"b{i}", "x", [f"u{i + 2}"]) for i in range(6)]
    profile = _grain_profile(_graph(tmp_path, rows), len(rows))

    assert profile["nodes_per_source_unit_median"] == 1
    assert profile["nodes_per_source_unit_max"] == 27


def test_partial_attribution_is_disclosed(tmp_path):
    rows = [("a", "x", ["u1"]), ("b", "x", []), ("c", "x", [])]
    profile = _grain_profile(_graph(tmp_path, rows), len(rows))

    assert profile["grain_attributed_fraction"] == round(1 / 3, 3)


def test_a_graph_without_the_column_reports_nothing(tmp_path):
    """Absent, not guessed. An unknown grain must not read as a fine one."""

    rows = [("a", "x", None), ("b", "x", None)]
    profile = _grain_profile(_graph(tmp_path, rows, with_column=False), len(rows))

    assert profile == {}


def test_a_graph_with_the_column_and_no_values_reports_nothing(tmp_path):
    rows = [("a", "x", []), ("b", "x", [])]
    assert _grain_profile(_graph(tmp_path, rows), len(rows)) == {}
