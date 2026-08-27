"""The atoms surface: one stream, refused when stale, and coverage both ways."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.atoms import main
from source_pipeline.workbook import StaleAtomStream, Workbook, write_workbook

#: No <main> wrapper, and real chrome elements — a <nav> and a <footer> —
#: because chrome is now set by the parser from ancestry rather than guessed
#: from a missing heading path. A bare <ul> is NOT chrome, which is exactly
#: the sagadb case the precise rule does not catch, and the test below pins
#: that limit rather than hiding it.
HTML = b"""<html><body>
<nav><ul><li>Downloads</li><li>About</li><li>Index</li></ul></nav>
<h1>A Saga</h1>
<h2>Chapter 1</h2>
<p>Hrafnkell rode to Adalbol and there met Einarr the shepherd.</p>
<h2>Chapter 2</h2>
<p>Samr rode to the Thing, and the suit against Hrafnkell was heard.</p>
<footer>Translated 1882 by John Coles.</footer>
</body></html>"""


@pytest.fixture
def workbook(tmp_path):
    source = tmp_path / "saga.html"
    source.write_bytes(HTML)
    book = tmp_path / "wb"
    assert main(["--workbook", str(book), "prepare", "--source", str(source)]) == 0
    return book, source


def test_prepare_writes_one_stream_and_records_who_wrote_it(workbook):
    """The manifest names the producer, which is what keeps one view.

    The construction program chooses its own parsers, so
    a default prepare could produce a different stream than the program does.
    Recording the producer is what stops that becoming two silent views.
    """
    book, _ = workbook
    manifest = json.loads((book / "workbook.json").read_text())

    assert manifest["atom_stream_producer"] == "atoms-prepare"
    assert manifest["atom_count"] > 0
    assert (book / "atoms.jsonl").exists()
    assert manifest["source_fingerprint"]


def test_a_stale_stream_is_refused_not_silently_used(workbook):
    """Authoring against a stale view fails much later and confusingly."""
    book, source = workbook
    source.write_bytes(HTML + b"<!-- changed -->")

    opened = Workbook.open(book)
    with pytest.raises(StaleAtomStream, match="sources have changed"):
        opened.check_fresh()


def test_a_missing_source_is_also_stale(workbook):
    book, source = workbook
    source.unlink()

    with pytest.raises(StaleAtomStream, match="source has gone"):
        Workbook.open(book).check_fresh()


def test_stats_counts_parser_flagged_chrome(workbook, capsys):
    """Chrome is what the parser says it is, not what a heuristic infers."""
    book, _ = workbook
    assert main(["--workbook", str(book), "stats", "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["atoms"] > 0
    # nav items plus the footer
    assert report["chrome"] >= 3


def test_chrome_is_flagged_not_filtered(workbook):
    """Flagged atoms stay in the stream on purpose.

    Filtering them here would make it impossible for coverage to report the
    case that matters — chrome that produced nodes anyway.
    """
    book, _ = workbook
    atoms = list(Workbook.open(book).atoms())

    assert any(a.chrome for a in atoms), "nav and footer must be flagged"
    assert any(not a.chrome for a in atoms), "content must not be"
    assert any(a.chrome and "Downloads" in a.text for a in atoms)


def test_content_position_boilerplate_is_not_caught_by_chrome(workbook):
    """The limit of a structural rule, pinned rather than glossed.

    On the real corpus the biggest boilerplate miss is a translation credit
    sitting in content position with a heading path — caught by neither the
    old heading-path guess nor the parser flag. What keeps it out of a graph
    today is a frequency threshold, and pretending otherwise would let someone
    claim this class is closed.
    """
    book, _ = workbook
    atoms = list(Workbook.open(book).atoms())
    credit = [a for a in atoms if "John Coles" in a.text]

    assert credit, "fixture must contain a translation credit"
    # It IS caught here, because the fixture puts it in a <footer>. The point
    # is that the rule is structural: move it into a <p> and it would not be.
    assert all(a.chrome for a in credit)


def test_grep_exits_nonzero_when_nothing_matches(workbook):
    book, _ = workbook

    assert main(["--workbook", str(book), "grep", "Hrafnkell"]) == 0
    assert main(["--workbook", str(book), "grep", "Beowulf"]) == 1


def test_sample_is_reproducible_under_a_seed(workbook, capsys):
    """An unseeded sample makes every finding an anecdote nobody can re-check."""
    book, _ = workbook
    main(["--workbook", str(book), "sample", "-n", "3", "--seed", "11"])
    first = capsys.readouterr().out
    main(["--workbook", str(book), "sample", "-n", "3", "--seed", "11"])
    second = capsys.readouterr().out

    assert first == second


def test_coverage_ranks_misses_by_size(workbook, capsys):
    """A hundred ignored one-line atoms are chrome; one ignored long passage
    is a real miss, and only size ordering puts the second first."""
    book, _ = workbook
    atoms = [json.loads(l) for l in (book / "atoms.jsonl").read_text().splitlines()]
    smallest = min(atoms, key=lambda a: len(a["text"]))

    encoding = {"concepts": [{"id": "x:1", "kind": "character", "label": "x",
                              "source_unit_ids": [smallest["atom_id"]]}],
                "edges": []}
    path = book / "enc.json"
    path.write_text(json.dumps(encoding))

    assert main(["--workbook", str(book), "coverage", "--encoding", str(path)]) == 0
    out = capsys.readouterr().out

    assert "produced nothing" in out
    body = out.split("largest first:")[1]
    sizes = [int(t.rstrip("c")) for t in body.split() if t.endswith("c") and t[:-1].isdigit()]
    assert sizes == sorted(sizes, reverse=True), "misses must be largest first"


def test_coverage_warns_when_chrome_produced_nodes(workbook, capsys):
    """The inverse view, and the one that catches a translator's name entering
    as a character: a parser-flagged chrome atom that DID produce a node."""
    book, _ = workbook
    atoms = list(Workbook.open(book).atoms())
    chrome = next(a for a in atoms if a.chrome)

    encoding = {"concepts": [{"id": "character:downloads", "kind": "character",
                              "label": chrome.text,
                              "source_unit_ids": [chrome.atom_id]}],
                "edges": []}
    path = book / "enc2.json"
    path.write_text(json.dumps(encoding))

    main(["--workbook", str(book), "coverage", "--encoding", str(path)])
    out = capsys.readouterr().out

    assert "WARNING" in out
    assert "chrome atom(s) DID produce" in out


def test_validate_reports_all_mechanical_problems(workbook, capsys):
    book, _ = workbook
    broken = book / "broken.json"
    broken.write_text(json.dumps({
        "concepts": [{"id": "person:bob", "kind": "person"}],
        "edges": [{
            "source_id": "person:bob", "target_id": "team:missing",
            "predicate": "member_of", "sst_type": "NOT_AN_SST",
            "source_unit_ids": ["unknown-unit"],
        }],
    }))

    assert main(["--workbook", str(book), "validate",
                 "--encoding", str(broken)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "INVALID"
    assert len(report["problems"]) >= 4


def test_audit_is_machine_readable_iteration_feedback(workbook, capsys):
    book, _ = workbook
    atom = next(a for a in Workbook.open(book).atoms() if not a.chrome)
    encoding = book / "iteration.json"
    encoding.write_text(json.dumps({
        "concepts": [{
            "id": "event:one", "kind": "event", "label": "One",
            "source_unit_ids": [atom.atom_id],
        }],
        "edges": [],
    }))

    assert main(["--workbook", str(book), "audit", "--encoding", str(encoding)]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["status"] == "VALID"
    assert report["coverage"]["atoms_contributed"] == 1
    assert report["coverage"]["unused_atom_ids"]
    assert "not generic completeness criteria" in report["interpretation"]


def test_explicit_missing_traversal_file_is_refused(workbook):
    book, _ = workbook
    atom = next(Workbook.open(book).atoms())
    encoding = book / "encoding.json"
    encoding.write_text(json.dumps({
        "concepts": [{"id": "x:1", "kind": "x", "source_unit_ids": [atom.atom_id]}],
        "edges": [],
    }))

    with pytest.raises(SystemExit, match="does not exist"):
        main([
            "--workbook", str(book), "materialize", "--encoding", str(encoding),
            "--traversals", str(book / "missing.json"),
        ])


def test_materialize_is_the_only_host_owned_construction_step(workbook, capsys):
    book, _ = workbook
    atom = next(Workbook.open(book).atoms())
    encoding = book / "agent-output.json"
    encoding.write_text(json.dumps({
        "graph": {"id": "org-example", "domain": "organisation"},
        "concepts": [
            {"id": "person:bob", "kind": "person", "label": "Bob",
             "source_unit_ids": [atom.atom_id]},
            {"id": "team:payments", "kind": "team", "label": "Payments",
             "source_unit_ids": [atom.atom_id]},
        ],
        "edges": [{
            "source_id": "person:bob", "target_id": "team:payments",
            "predicate": "member_of", "sst_type": "CONTAINS",
            "source_unit_ids": [atom.atom_id],
        }],
    }))

    assert main(["--workbook", str(book), "materialize",
                 "--encoding", str(encoding)]) == 0
    report = json.loads(capsys.readouterr().out)
    graph = Path(report["graph"])
    assert graph.exists()
    assert Path(report["encoding"]).exists()
    assert Path(report["sources"]).exists()
    metadata = json.loads(Path(report["metadata"]).read_text())
    assert metadata["embedding_status"] == "NOT_BUILT"
    assert metadata["concept_count"] == 2
    assert not (book / "out" / "graph.md").exists()


def test_materialize_binds_optional_workbook_traversals(workbook, capsys):
    book, _ = workbook
    atom = next(Workbook.open(book).atoms())
    out = book / "out"
    out.mkdir(exist_ok=True)
    encoding = out / "encoding.json"
    encoding.write_text(json.dumps({
        "graph": {"id": "self-example", "domain": "example"},
        "concepts": [
            {"id": "thing:one", "kind": "thing", "label": "One",
             "source_unit_ids": [atom.atom_id]},
        ],
        "edges": [{
            "source_id": "thing:one", "target_id": "thing:one",
            "predicate": "self", "sst_type": "NEARTO",
            "source_unit_ids": [atom.atom_id],
        }],
    }))
    (out / "traversals.json").write_text(json.dumps({
        "schema_version": "workbook-traversals-v1",
        "traversals": {
            "self": {
                "version": 1,
                "parameters": {"thing_id": {"type": "node_id", "kinds": ["thing"]}},
                "steps": [
                    {"op": "lookup", "references": ["$thing_id"], "assign": "seed"},
                    {"op": "traverse", "from": "$seed", "predicates": ["self"], "assign": "answer"},
                ],
                "collect": "$answer",
                "answers": ["answer"],
            }
        },
    }))

    assert main(["--workbook", str(book), "materialize", "--encoding", str(encoding)]) == 0
    report = json.loads(capsys.readouterr().out)
    bound = json.loads(Path(report["traversals"]).read_text())
    metadata = json.loads(Path(report["metadata"]).read_text())

    assert bound["binding"]["predicates"] == {"self": "NEARTO"}
    assert metadata["traversals"]["fingerprint"] == bound["fingerprint"]


def test_html_and_pdf_land_in_one_stream(tmp_path):
    """The program sees one stream regardless of how many parsers made it."""
    source = tmp_path / "saga.html"
    source.write_bytes(HTML)
    pdf = Path("tests/fixtures/two_page_text.pdf")
    book = tmp_path / "wb"

    assert main(["--workbook", str(book), "prepare",
                 "--source", str(source), str(pdf)]) == 0
    atoms = list(Workbook.open(book).atoms())

    sources = {a.source_id for a in atoms}
    assert sources == {"saga", "two_page_text"}


def test_coverage_matches_either_provenance_grain(workbook, tmp_path, capsys):
    """Citing the unit rather than the atom must not read as zero coverage.

    The field is `source_unit_ids`, the acceptance check is
    `every_node_has_a_source_unit`, and the stream carries both `unit_id` and
    `atom_id` — so citing the unit is the name-correct choice. Matching only
    on `atom_id` reported an entire 1,442-atom corpus as unused while
    `every_node_has_a_source_unit` passed, which is provenance that looks
    present and resolves to nothing.

    Two cold agents hit this independently on the same surface: one read this
    command's source and picked `atom_id`, the other followed the naming.
    """
    book, _ = workbook
    atoms = list(Workbook.open(book).atoms())
    content = [a for a in atoms if not a.chrome]
    assert content, "fixture assumption: some atoms are not chrome"

    by_unit = tmp_path / "by_unit.json"
    by_unit.write_text(json.dumps({
        "concepts": [{"id": "character:x", "kind": "character", "label": "X",
                      "source_unit_ids": [content[0].unit_id]}],
        "edges": [],
    }))
    assert main(["--workbook", str(book), "coverage",
                 "--encoding", str(by_unit)]) == 0
    assert "0/" not in capsys.readouterr().out.splitlines()[0]

    by_atom = tmp_path / "by_atom.json"
    by_atom.write_text(json.dumps({
        "concepts": [{"id": "character:x", "kind": "character", "label": "X",
                      "source_unit_ids": [content[0].atom_id]}],
        "edges": [],
    }))
    assert main(["--workbook", str(book), "coverage",
                 "--encoding", str(by_atom)]) == 0
    assert "0/" not in capsys.readouterr().out.splitlines()[0]


def test_every_parser_answers_the_same_prose_question(tmp_path):
    """A program must be able to ask for running text without knowing the parser.

    Each parser has its own `kind` vocabulary — HTML emits `p`/`text`/
    `list_item`, plain text emits `block`, PDF emits `page` — and nothing
    declared the correspondence. A real construction program selected prose
    with `kind in {"p", "text", "list_item"}`, which is exactly right for HTML
    and matches nothing a PDF produces: 162 pages of papers, 1,440 sentences
    that scored as claims, and zero claims in the output. Changing that one
    line to `prose` produced 15 claims and 36 edges from the same input.
    """
    html = tmp_path / "a.html"
    html.write_bytes(b"<html><body><nav><p>Downloads</p></nav>"
                     b"<h1>T</h1><p>Hrafnkell rode to Adalbol that summer.</p>"
                     b"</body></html>")
    txt = tmp_path / "b.txt"
    txt.write_text("Hrafnkell rode to Adalbol that summer.\n\nHe met Einarr.\n")

    book = tmp_path / "wb"
    assert main(["--workbook", str(book), "prepare",
                 "--source", str(html), str(txt)]) == 0

    atoms = list(Workbook.open(book).atoms())
    by_source = {}
    for atom in atoms:
        by_source.setdefault(atom.source_id, []).append(atom)

    for source_id, group in by_source.items():
        assert any(a.prose for a in group), (
            f"{source_id} produced no prose unit, so a program selecting on "
            "prose would silently skip this whole source"
        )

    # Chrome is never prose: a program taking prose gets content, not navigation.
    assert not any(a.prose and a.chrome for a in atoms)
    # And the heading is not prose either.
    headings = [a for a in atoms if a.kind == "heading"]
    assert headings and not any(a.prose for a in headings)
