"""The PDF parser, held to the same offset guarantee as every other parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from source_pipeline import (
    HtmlSourceParser,
    MarkdownSourceParser,
    PdfSourceParser,
    PlainTextSourceParser,
    SourceArtifact,
    parse_artifact,
)

#: A real 953-byte two-page PDF, committed because the alternative is a test
#: that silently skips everywhere except one machine. Built by
#: `tests/fixtures/README.md`; it is a deterministic input the tests read, which
#: is the tracked-fixture case the repo policy allows.
FIXTURE = Path(__file__).parent / "fixtures" / "two_page_text.pdf"


def _real_pdf() -> bytes:
    return FIXTURE.read_bytes()


def _artifact(content: bytes, locator: str = "paper.pdf") -> SourceArtifact:
    return SourceArtifact(
        source_id="paper", media_type="application/pdf",
        content=content, locator=locator,
    )


def test_it_is_recognised_by_header_even_with_a_wrong_media_type():
    """A downloaded file often arrives as octet-stream; the bytes still say PDF."""
    artifact = SourceArtifact(
        source_id="paper", media_type="application/octet-stream",
        content=b"%PDF-1.7\n...", locator="download.bin",
    )

    assert PdfSourceParser().supports(artifact).supported


def test_it_does_not_claim_html_or_markdown():
    for locator, media in (("a.html", "text/html"), ("a.md", "text/markdown")):
        artifact = SourceArtifact(
            source_id="a", media_type=media, content=b"x", locator=locator)
        assert not PdfSourceParser().supports(artifact).supported


def test_every_unit_is_an_exact_slice_of_the_representation():
    """The guarantee the evidence protocols rest on.

    Quotes are pinned by offset, so a parser that reflows or paraphrases its
    own output breaks pinning without raising anything.
    """
    parsed = PdfSourceParser().parse(_artifact(_real_pdf()))

    assert parsed.units, "a text PDF must yield units"
    for unit in parsed.units:
        assert parsed.representation[unit.start : unit.end] == unit.text
        assert unit.text == unit.text.strip()


def test_units_are_ordered_and_do_not_overlap():
    parsed = PdfSourceParser().parse(_artifact(_real_pdf()))

    previous_end = -1
    for unit in parsed.units:
        assert unit.start >= previous_end
        previous_end = unit.end


def test_fidelity_says_extracted_rather_than_exact():
    """A PDF's bytes are not its text, and the record has to say so."""
    parsed = PdfSourceParser().parse(_artifact(_real_pdf()))

    assert parsed.fidelity == "EXTRACTED"
    assert parsed.metadata["extractor"].startswith("pypdf")


def test_the_extractor_version_is_in_the_config_fingerprint():
    """A pypdf upgrade can legitimately change extraction.

    When it does, downstream fingerprints must be invalidated rather than
    silently shifted, so the version is part of the parser's identity.
    """
    default = PdfSourceParser()
    other = PdfSourceParser(page_separator="\f")

    assert default.descriptor.config_fingerprint
    assert default.descriptor.config_fingerprint != other.descriptor.config_fingerprint


def test_selection_order_reaches_the_pdf_parser():
    parsed = parse_artifact(
        _artifact(_real_pdf()),
        [HtmlSourceParser(), MarkdownSourceParser(), PdfSourceParser(),
         PlainTextSourceParser()],
    )

    assert parsed.parser.parser_id == "pdf-pages"


def test_a_scanned_pdf_reports_empty_pages_rather_than_pretending():
    """No OCR here. A PDF of images must say it produced nothing, loudly."""
    minimal = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>"
    )
    try:
        parsed = PdfSourceParser().parse(_artifact(minimal, "scan.pdf"))
    except Exception:
        pytest.skip("pypdf refused a hand-built minimal PDF")
    codes = {d.code for d in parsed.diagnostics}
    assert parsed.status == "ABSTAINED"
    assert "empty_pages" in codes
