"""PDF parser: pages become units, with offsets into a text representation.

The constraint every parser here works under is that a unit's text must be an
exact slice of `representation` — the evidence protocols pin quotes by offset,
so a parser that paraphrases or reflows its own output breaks pinning silently.

PDF makes that harder than HTML, because there is no text until an extractor
produces one. The resolution is that **the extracted text IS the
representation**: `pypdf`'s per-page output is concatenated with a recorded
separator, and every offset is measured against that concatenation rather than
against anything in the file. The representation is therefore reproducible for
a given pypdf version and pinned as such — a fact recorded in the parser's
`config_fingerprint`, because a pypdf upgrade can legitimately change
extraction and must invalidate downstream fingerprints rather than silently
shift them.

`fidelity` is EXTRACTED, not EXACT. A PDF's bytes are not its text, tables and
multi-column layouts are flattened, and nothing here pretends otherwise.
"""

from __future__ import annotations

import hashlib
import io

from source_pipeline.contracts import (
    ParseDiagnostic,
    ParsedSource,
    ParserDescriptor,
    ParserSupport,
    SourceArtifact,
    SourceUnit,
)

#: Between pages. Two newlines so a page break reads as a paragraph break to
#: every downstream segmenter, and a fixed width so offsets are predictable.
PAGE_SEPARATOR = "\n\n"


def _config_fingerprint(*, extractor: str, version: str, separator: str) -> str:
    payload = f"{extractor}:{version}:{separator!r}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class PdfSourceParser:
    """One unit per page, located by offset into the extracted text."""

    def __init__(self, *, page_separator: str = PAGE_SEPARATOR) -> None:
        self.page_separator = page_separator
        try:
            import pypdf

            version = getattr(pypdf, "__version__", "unknown")
        except ImportError:  # declared, but not installed
            version = "absent"
        self._pypdf_version = version
        self.descriptor = ParserDescriptor(
            parser_id="pdf-pages",
            version=1,
            media_types=("application/pdf",),
            config_fingerprint=_config_fingerprint(
                extractor="pypdf", version=version, separator=page_separator
            ),
        )

    def supports(self, artifact: SourceArtifact) -> ParserSupport:
        media_type = artifact.media_type.split(";", 1)[0].strip().casefold()
        suffix_match = artifact.locator.casefold().endswith(".pdf")
        # A PDF is also identifiable from its own first bytes, which is the
        # only signal that survives a wrong media type on a downloaded file.
        magic = artifact.content[:5] == b"%PDF-"
        supported = media_type in self.descriptor.media_types or suffix_match or magic
        return ParserSupport(
            supported=supported,
            reason="PDF media type, filename or header" if supported else "not PDF",
        )

    def parse(self, artifact: SourceArtifact) -> ParsedSource:
        from pypdf import PdfReader

        diagnostics: list[ParseDiagnostic] = []
        reader = PdfReader(io.BytesIO(artifact.content))

        pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                pages.append(page.extract_text() or "")
            except Exception as error:
                # One unreadable page must not lose the document. It becomes an
                # empty page and a recorded diagnostic, so the gap is visible
                # in the ledger rather than inferred from a short unit count.
                pages.append("")
                diagnostics.append(
                    ParseDiagnostic(
                        code="page_extraction_failed",
                        severity="warning",
                        message=f"{type(error).__name__}: {error}",
                        locator=f"{artifact.locator}#page:{index}",
                        details={"page": index},
                    )
                )

        representation = self.page_separator.join(pages)
        units: list[SourceUnit] = []
        cursor = 0
        empty_pages = 0
        for index, text in enumerate(pages, start=1):
            start = cursor
            end = start + len(text)
            cursor = end + len(self.page_separator)
            stripped = text.strip()
            if not stripped:
                empty_pages += 1
                continue
            # Trim inward so the unit carries no leading or trailing
            # whitespace, while its offsets still address `representation`
            # exactly. Never rewrite the text to achieve that.
            lead = len(text) - len(text.lstrip())
            trail = len(text) - len(text.rstrip())
            units.append(
                SourceUnit(
                    unit_id=f"{artifact.source_id}:page:{index}",
                    source_id=artifact.source_id,
                    kind="page",
                    # A page of an extracted text PDF is running text. It is
                    # coarser than a paragraph, and that is a grain question
                    # for the segmenter, not a reason to call it non-prose.
                    prose=True,
                    locator=f"{artifact.locator}#page:{index}",
                    text=representation[start + lead : end - trail],
                    start=start + lead,
                    end=end - trail,
                    metadata={
                        "source_parser": self.descriptor.parser_id,
                        "page": index,
                        "pypdf_version": self._pypdf_version,
                    },
                )
            )

        if empty_pages:
            diagnostics.append(
                ParseDiagnostic(
                    code="empty_pages",
                    severity="info" if empty_pages < len(pages) else "error",
                    message=(
                        f"{empty_pages} of {len(pages)} pages yielded no text; "
                        "a scanned PDF needs OCR, which this parser does not do"
                    ),
                    locator=artifact.locator,
                    details={"empty_pages": empty_pages, "pages": len(pages)},
                )
            )

        return ParsedSource(
            source_id=artifact.source_id,
            parser=self.descriptor,
            artifact_fingerprint=artifact.fingerprint(),
            artifact_content_sha256=artifact.content_sha256,
            status="PARSED" if units else "ABSTAINED",
            # Not EXACT: a PDF's bytes are not its text. Columns and tables are
            # flattened and the caller should know that from the record.
            fidelity="EXTRACTED",
            representation=representation,
            units=tuple(units),
            diagnostics=tuple(diagnostics),
            metadata={
                "title": str(artifact.metadata.get("title") or artifact.source_id),
                "pages": len(pages),
                "extractor": f"pypdf {self._pypdf_version}",
            },
        )
