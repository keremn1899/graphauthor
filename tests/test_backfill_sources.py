"""Rebuilding a sidecar for a graph built before sidecars existed.

The claim the script rests on: unit ids are `sha256(locator)[:12]` and atom
ids are `{unit_id}@{span}`, both deterministic functions of the source and the
segmenter config rather than of the run. If that holds, a sidecar can be
rebuilt from the source alone. If it does not, the backfill writes a file full
of ids that match nothing.

So the first test checks determinism directly rather than assuming it, and the
rest check that a mismatch is refused rather than written.
"""

from __future__ import annotations

import json

import pytest
import real_ladybug as lb

from scripts.backfill_sources import _atoms_for, main
from source_pipeline.sources_sidecar import Sources, sidecar_path

SOURCE = """# Release policy

## Cutting a release

A release must be cut from `main`. The tag is the version, and it is
immutable once pushed.

## Rolling back

A rollback re-tags the previous commit. It never rewrites a published tag,
because someone downstream has already fetched it.
"""


def _source_file(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text(SOURCE, encoding="utf-8")
    return path


def test_preparing_the_same_source_twice_gives_the_same_ids(tmp_path):
    """The whole backfill rests on this. If ids moved between runs, a
    rebuilt sidecar would resolve nothing and the failure would look like a
    graph that simply has no sources."""
    path = _source_file(tmp_path)
    first = _atoms_for([path], 6000)
    second = _atoms_for([path], 6000)

    assert first, "the segmenter produced no atoms"
    assert [a.atom_id for a in first] == [a.atom_id for a in second]
    assert [a.text for a in first] == [a.text for a in second]


def _graph_citing(tmp_path, unit_ids):
    db = tmp_path / "g.lbug"
    conn = lb.Connection(lb.Database(str(db)))
    conn.execute(
        "CREATE NODE TABLE Concept (id STRING, label STRING, "
        "semantic_anchor STRING, text_content STRING, token_count INT64, "
        "centrality_score DOUBLE, is_metanode BOOLEAN, linked_graph_id STRING, "
        "kind STRING, source_unit_ids STRING[], PRIMARY KEY (id))"
    )
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        conn.execute(
            f"CREATE REL TABLE {rel} (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    for i, unit in enumerate(unit_ids):
        conn.execute(
            f"CREATE (:Concept {{id: 'claim:{i}', label: 'Claim {i}', "
            f"semantic_anchor: '', text_content: 'body', token_count: 2, "
            f"centrality_score: 0.1, is_metanode: false, linked_graph_id: '', "
            f"kind: 'claim', source_unit_ids: ['{unit}']}})"
        )
    conn.close()
    return db


def test_backfill_resolves_a_graph_built_from_the_same_source(tmp_path, capsys):
    path = _source_file(tmp_path)
    atoms = _atoms_for([path], 6000)
    db = _graph_citing(tmp_path, [a.atom_id for a in atoms[:2]])

    code = main(["--graph", str(db), "--source", str(path)])
    report = json.loads(capsys.readouterr().out)

    assert code == 0, report
    assert report["written"] is True
    assert report["resolved"] == report["cited_by_graph"] == 2

    sources = Sources.for_graph(db)
    assert sources is not None
    unit = sources.resolve(atoms[0].atom_id)
    assert unit is not None and unit.excerpt.strip()


def test_backfill_refuses_a_source_that_resolves_nothing(tmp_path, capsys):
    """A sidecar resolving nothing is worse than none: "not recorded" is
    honest, an empty passage panel is not."""
    path = _source_file(tmp_path)
    other = tmp_path / "unrelated.md"
    other.write_text("# Something else entirely\n\nNo shared locators.\n",
                     encoding="utf-8")
    db = _graph_citing(tmp_path, [a.atom_id for a in _atoms_for([path], 6000)[:2]])

    code = main(["--graph", str(db), "--source", str(other)])
    report = json.loads(capsys.readouterr().out)

    assert code == 1
    assert report["written"] is False
    assert "match" in report["refused"]
    assert not sidecar_path(db).exists(), "it wrote the sidecar it refused"


def test_force_writes_the_mismatched_sidecar_anyway(tmp_path, capsys):
    path = _source_file(tmp_path)
    other = tmp_path / "unrelated.md"
    other.write_text("# Something else\n\nText.\n", encoding="utf-8")
    db = _graph_citing(tmp_path, [a.atom_id for a in _atoms_for([path], 6000)[:2]])

    code = main(["--graph", str(db), "--source", str(other), "--force"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["written"] is True
    assert sidecar_path(db).exists()


def test_a_changed_source_is_detectable_after_backfill(tmp_path, capsys):
    """The fingerprint is computed the same way `write_workbook` computes it,
    so an edit after the backfill reads as drift rather than passing."""
    path = _source_file(tmp_path)
    db = _graph_citing(tmp_path, [a.atom_id for a in _atoms_for([path], 6000)[:1]])
    main(["--graph", str(db), "--source", str(path)])
    report = json.loads(capsys.readouterr().out)

    sources = Sources.for_graph(db)
    assert sources.is_stale_against(report["source_fingerprint"]) is False

    import hashlib
    path.write_text(SOURCE + "\n## A new section\n\nAdded later.\n", encoding="utf-8")
    live = hashlib.sha256(
        hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8")
    ).hexdigest()[:16]
    assert sources.is_stale_against(live) is True
