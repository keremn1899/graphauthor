from __future__ import annotations

import pytest

from source_pipeline import (
    BoundedTextSegmenter,
    HtmlSourceParser,
    MarkdownSourceParser,
    ParserDescriptor,
    SegmentationContext,
    SegmentationDecision,
    SegmenterDescriptor,
    SourceArtifact,
    SourceAtom,
    parse_artifact,
    segment_parsed_source,
)


HTML = b"""<!doctype html>
<html lang="en">
  <head>
    <title>Traversal Notes</title>
    <base href="https://example.test/docs/">
    <link rel="canonical" href="topic.html">
    <script>window.secret = 'not evidence';</script>
  </head>
  <body>
    <nav>Site navigation</nav>
    <main>
      <h1>Named traversal</h1>
      <p>A traversal follows <a href="edges.html">accepted edges</a>.</p>
      <h2>Properties</h2>
      <ul><li>Bounded</li><li>Deterministic</li></ul>
      <table><tr><th>Mode</th><th>Meaning</th></tr><tr><td>EMPTY</td><td>Bounded no result</td></tr></table>
      <pre>run(topic_id)</pre>
    </main>
    <footer>Copyright chrome</footer>
  </body>
</html>"""


def _html_artifact() -> SourceArtifact:
    return SourceArtifact(
        source_id="page:named-traversal",
        media_type="text/html; charset=utf-8",
        content=HTML,
        locator="named-traversal.html",
        source_uri="https://example.test/fetched/page.html",
    )


def test_html_parser_extracts_addressable_main_content_and_reports_the_cut():
    artifact = _html_artifact()
    parsed = parse_artifact(artifact, [MarkdownSourceParser(), HtmlSourceParser()])

    assert parsed.parser.parser_id == "html-visible-blocks"
    assert parsed.status == "PARTIAL"
    assert parsed.fidelity == "EXTRACTED"
    assert parsed.artifact_content_sha256 == artifact.content_sha256
    assert parsed.metadata["title"] == "Traversal Notes"
    assert parsed.metadata["canonical_uri"] == "https://example.test/docs/topic.html"
    assert parsed.metadata["content_root"] == "main"
    assert "Site navigation" not in parsed.representation
    assert "Copyright chrome" not in parsed.representation
    assert "window.secret" not in parsed.representation

    kinds = [unit.kind for unit in parsed.units]
    assert kinds == [
        "heading",
        "p",
        "heading",
        "list_item",
        "list_item",
        "table_row",
        "table_row",
        "code_block",
    ]
    paragraph = next(unit for unit in parsed.units if unit.kind == "p")
    assert paragraph.text == "A traversal follows accepted edges."
    assert paragraph.links == ("https://example.test/docs/edges.html",)
    assert paragraph.heading_path == ("Named traversal",)
    assert parsed.outline[1]["path"] == ["Named traversal", "Properties"]
    assert all(
        parsed.representation[unit.start : unit.end] == unit.text
        for unit in parsed.units
    )
    assert {row.code for row in parsed.diagnostics} == {
        "html_content_root_selected",
        "html_elements_removed",
    }


def test_html_drop_selectors_are_fingerprinted_and_reported():
    artifact = SourceArtifact(
        source_id="page",
        media_type="text/html",
        content=b"<html><body><p>Keep</p><div class='advert'>Discard me</div></body></html>",
    )
    default = HtmlSourceParser(prefer_main=False)
    configured = HtmlSourceParser(prefer_main=False, drop_selectors=(".advert",))

    parsed = configured.parse(artifact)

    assert default.descriptor.config_fingerprint != configured.descriptor.config_fingerprint
    assert parsed.status == "PARTIAL"
    assert parsed.representation == "Keep"
    removed = next(row for row in parsed.diagnostics if row.code == "html_elements_removed")
    assert removed.details["elements"][0]["selector"] == ".advert"
    assert removed.details["elements"][0]["visible_characters"] == len("Discard me")


def test_html_mixed_inline_and_block_content_is_ordered_without_duplication():
    artifact = SourceArtifact(
        source_id="mixed",
        media_type="text/html",
        content=(
            b"<html><body><div>Hello <span>dear <a href='/reader'>reader</a>"
            b"</span><p>world</p> after <strong>the block</strong>.</div></body></html>"
        ),
        source_uri="https://example.test/page",
    )

    parsed = HtmlSourceParser(prefer_main=False).parse(artifact)

    assert [unit.text for unit in parsed.units] == [
        "Hello dear reader",
        "world",
        "after the block.",
    ]
    assert [unit.kind for unit in parsed.units] == ["text", "p", "text"]
    assert sum(unit.text == "world" for unit in parsed.units) == 1
    assert parsed.units[0].links == ("https://example.test/reader",)
    assert parsed.units[1].links == ()
    assert parsed.units[0].locator.endswith("/text-run[1]")
    assert parsed.units[2].locator.endswith("/text-run[2]")


def test_html_inline_wrapper_is_not_emitted_again_during_recursion():
    artifact = SourceArtifact(
        source_id="inline",
        media_type="text/html",
        content=b"<html><body><div><span>Only once</span></div></body></html>",
    )

    parsed = HtmlSourceParser(prefer_main=False).parse(artifact)

    assert [unit.text for unit in parsed.units] == ["Only once"]


def test_markdown_is_an_independent_parser_with_stable_units():
    artifact = SourceArtifact(
        source_id="notes",
        media_type="text/markdown",
        content=b"# Decision\n\nUse a bounded program.\n\n## Reason\n\nIt is reproducible.",
        locator="decision.md",
    )
    parser = MarkdownSourceParser()

    first = parse_artifact(artifact, [HtmlSourceParser(), parser])
    second = parser.parse(artifact)

    assert first.parser.parser_id == "markdown-blocks"
    assert first.fidelity == "NORMALIZED"
    assert first.fingerprint() == second.fingerprint()
    assert [unit.unit_id for unit in first.units] == [
        unit.unit_id for unit in second.units
    ]
    assert "Use a bounded program." in first.representation


def test_bounded_segmenter_is_lossless_and_keeps_receipts():
    artifact = SourceArtifact(
        source_id="long-note",
        media_type="text/markdown",
        content=(b"# Long\n\n" + (b"Sentence with useful material. " * 40)),
        locator="long.md",
    )
    parsed = MarkdownSourceParser().parse(artifact)
    segmented = segment_parsed_source(
        parsed,
        [BoundedTextSegmenter()],
        context=SegmentationContext(max_atom_chars=120),
    )

    atoms_by_unit = {}
    for atom in segmented.atoms:
        atoms_by_unit.setdefault(atom.unit_id, []).append(atom)
        assert len(atom.text) <= 120 or atom.metadata.get("passthrough")
    for unit in parsed.units:
        assert "".join(atom.text for atom in atoms_by_unit[unit.unit_id]) == unit.text

    assert any(record.status == "APPLIED" for record in segmented.records)
    assert segmented.parsed_source_fingerprint == parsed.fingerprint()


class _BrokenAgentSegmenter:
    descriptor = SegmenterDescriptor(
        segmenter_id="agent-authored-broken",
        version=1,
        config_fingerprint="code_deadbeef",
    )

    def supports(self, unit, context):
        return True

    def segment(self, unit, context):
        return SegmentationDecision(
            status="APPLIED",
            basis="agent_program",
            atoms=(
                SourceAtom(
                    atom_id=f"{unit.unit_id}@bad",
                    source_id=unit.source_id,
                    unit_id=unit.unit_id,
                    start=1,
                    end=len(unit.text),
                    text=unit.text[1:],
                    label="bad",
                ),
            ),
        )


def test_agent_authored_segmenter_cannot_silently_drop_source_text():
    parsed = MarkdownSourceParser().parse(
        SourceArtifact(
            source_id="note",
            media_type="text/markdown",
            content=b"# Note\n\nEvery character remains accounted for.",
        )
    )

    with pytest.raises(ValueError, match="not an exact partition"):
        segment_parsed_source(parsed, [_BrokenAgentSegmenter()])


class _UnversionedAgentSegmenter(_BrokenAgentSegmenter):
    descriptor = SegmenterDescriptor(segmenter_id="agent-unversioned", version=1)

    def segment(self, unit, context):
        return SegmentationDecision(
            status="APPLIED",
            basis="agent_program",
            atoms=(
                SourceAtom(
                    atom_id=f"{unit.unit_id}@whole-agent",
                    source_id=unit.source_id,
                    unit_id=unit.unit_id,
                    start=0,
                    end=len(unit.text),
                    text=unit.text,
                    label="whole",
                ),
            ),
        )


def test_agent_authored_segmenter_requires_code_fingerprint():
    parsed = MarkdownSourceParser().parse(
        SourceArtifact(
            source_id="note",
            media_type="text/markdown",
            content=b"# Note\n\nAn agent program must be identifiable.",
        )
    )

    with pytest.raises(ValueError, match="code/config fingerprint"):
        segment_parsed_source(parsed, [_UnversionedAgentSegmenter()])


class _AbstainingSegmenter:
    descriptor = SegmenterDescriptor(
        segmenter_id="agent-abstains",
        version=1,
        config_fingerprint="code_abstains",
    )

    def supports(self, unit, context):
        return True

    def segment(self, unit, context):
        return SegmentationDecision(status="ABSTAINED", basis="agent_program")


def test_abstention_preserves_whole_unit_and_surfaces_oversize():
    parsed = MarkdownSourceParser().parse(
        SourceArtifact(
            source_id="note",
            media_type="text/markdown",
            content=b"# Note\n\n" + b"x" * 80,
        )
    )
    segmented = segment_parsed_source(
        parsed,
        [_AbstainingSegmenter()],
        context=SegmentationContext(max_atom_chars=20),
    )

    oversized = [
        record
        for record in segmented.records
        if any(row.code == "oversized_passthrough" for row in record.diagnostics)
    ]
    assert oversized
    assert oversized[0].status == "ABSTAINED"
    unit = next(unit for unit in parsed.units if unit.unit_id == oversized[0].unit_id)
    atom = next(atom for atom in segmented.atoms if atom.unit_id == unit.unit_id)
    assert atom.text == unit.text
