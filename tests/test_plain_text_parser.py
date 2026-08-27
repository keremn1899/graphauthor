"""The fallback parser: exact offsets, and no silent shadowing of better ones."""

from __future__ import annotations

import pytest

from source_pipeline import (
    HtmlSourceParser,
    MarkdownSourceParser,
    PlainTextSourceParser,
    SourceArtifact,
    parse_artifact,
)


def _artifact(name: str, body: bytes, media_type: str = "text/plain"):
    return SourceArtifact(
        source_id="notes",
        media_type=media_type,
        content=body,
        locator=name,
    )


def test_every_unit_is_an_exact_slice_of_the_representation():
    """The property the whole contract rests on, and the one a cursor breaks.

    Splitting discards the separator, so a cursor accumulated while splitting
    drifts by exactly the bytes it dropped and every unit after the first fails
    this check. Offsets are taken from separator positions instead.
    """
    parsed = PlainTextSourceParser().parse(
        _artifact("notes.txt", b"One.\n\nTwo.\n\n\n  Three.  \n\nFour.")
    )

    assert len(parsed.units) == 4
    for unit in parsed.units:
        assert parsed.representation[unit.start : unit.end] == unit.text
        assert unit.text == unit.text.strip()


def test_blank_input_abstains_rather_than_inventing_a_unit():
    parsed = PlainTextSourceParser().parse(_artifact("empty.txt", b"\n\n   \n"))

    assert parsed.units == ()
    assert parsed.status == "ABSTAINED"


def test_it_does_not_claim_markdown_or_html():
    """Registering a catch-all would shadow every format-aware parser.

    Degrading a Markdown document to undifferentiated blocks loses its heading
    path, which is the thing that makes its units addressable — worse than
    refusing the file outright, and silent.
    """
    text = PlainTextSourceParser()

    assert not text.supports(_artifact("a.md", b"# H", "text/markdown")).supported
    assert not text.supports(_artifact("a.html", b"<p>x</p>", "text/html")).supported


@pytest.mark.parametrize("name", ["a.txt", "a.text", "a.rst"])
def test_it_claims_the_suffixes_that_previously_raised(name):
    artifact = _artifact(name, b"Body.", media_type="application/octet-stream")

    assert PlainTextSourceParser().supports(artifact).supported


def test_selection_order_keeps_markdown_with_the_markdown_parser():
    parsed = parse_artifact(
        _artifact("doc.md", b"# Title\n\nBody.", "text/markdown"),
        [HtmlSourceParser(), MarkdownSourceParser(), PlainTextSourceParser()],
    )

    assert parsed.parser.parser_id == "markdown-blocks"


def test_a_text_file_no_longer_ends_the_run():
    """Before this parser, parse_artifact raised on anything not HTML/Markdown,
    so a corpus was refused for a filename reason rather than a content one."""
    artifact = _artifact("plain.txt", b"A paragraph.\n\nAnother.")

    with pytest.raises(ValueError, match="no source parser accepted"):
        parse_artifact(artifact, [HtmlSourceParser(), MarkdownSourceParser()])

    parsed = parse_artifact(
        artifact,
        [HtmlSourceParser(), MarkdownSourceParser(), PlainTextSourceParser()],
    )
    assert [unit.text for unit in parsed.units] == ["A paragraph.", "Another."]
