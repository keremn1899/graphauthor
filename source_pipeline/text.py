"""Plain-text parser: the fallback that stops a corpus being refused by suffix.

`parse_artifact` selects the first declaring parser and raises when none
accepts, so before this a `.txt` or `.rst` corpus was refused for a filename
reason rather than a content one. This parser claims nothing structural — it
finds blank-line-separated blocks and calls them blocks. Anything that wants
headings, sections or native identifiers should be parsed by a format-aware
parser instead; this exists so that "we cannot read that file type" stops being
a reason a domain cannot be tried.

It declares narrow media types on purpose. Registering it as a catch-all would
make it shadow every future parser in selection order, and silently degrading a
Markdown document to undifferentiated blocks is worse than refusing it.
"""

from __future__ import annotations

import re

from source_pipeline.contracts import (
    ParsedSource,
    ParserDescriptor,
    ParserSupport,
    SourceArtifact,
    SourceUnit,
)

_BLOCK = re.compile(r"\n\s*\n")


class PlainTextSourceParser:
    """Expose blank-line-separated blocks of a text artifact, losslessly."""

    descriptor = ParserDescriptor(
        parser_id="plain-text-blocks",
        version=1,
        media_types=("text/plain", "text/x-rst", "text/restructuredtext"),
    )

    def supports(self, artifact: SourceArtifact) -> ParserSupport:
        media_type = artifact.media_type.split(";", 1)[0].strip().casefold()
        suffix_match = artifact.locator.casefold().endswith((".txt", ".text", ".rst"))
        supported = media_type in self.descriptor.media_types or suffix_match
        return ParserSupport(
            supported=supported,
            reason="plain-text media type or filename" if supported else "not text",
        )

    def parse(self, artifact: SourceArtifact) -> ParsedSource:
        text = artifact.content.decode("utf-8")
        units: list[SourceUnit] = []
        index = 0
        for start, end in self._block_spans(text):
            index += 1
            units.append(
                SourceUnit(
                    unit_id=f"{artifact.source_id}:block:{index}",
                    source_id=artifact.source_id,
                    kind="block",
                    prose=True,
                    locator=f"{artifact.locator}#block:{index}",
                    text=text[start:end],
                    start=start,
                    end=end,
                    metadata={"source_parser": self.descriptor.parser_id},
                )
            )
        return ParsedSource(
            source_id=artifact.source_id,
            parser=self.descriptor,
            artifact_fingerprint=artifact.fingerprint(),
            artifact_content_sha256=artifact.content_sha256,
            status="PARSED" if units else "ABSTAINED",
            fidelity="EXACT",
            representation=text,
            units=tuple(units),
            metadata={
                "title": str(artifact.metadata.get("title") or artifact.source_id)
            },
        )

    @staticmethod
    def _block_spans(text: str) -> list[tuple[int, int]]:
        """Spans of the non-blank blocks, measured against `text` itself.

        Offsets are derived from separator positions rather than accumulated
        while splitting: a split discards the separator, so an accumulated
        cursor drifts by exactly the bytes it dropped and every later unit
        fails the representation check. Leading and trailing whitespace is
        trimmed by moving the bounds inward, never by rewriting the text, so
        `representation[start:end] == text` holds for every unit.
        """

        spans: list[tuple[int, int]] = []
        bounds: list[tuple[int, int]] = []
        cursor = 0
        for separator in _BLOCK.finditer(text):
            bounds.append((cursor, separator.start()))
            cursor = separator.end()
        bounds.append((cursor, len(text)))
        for start, end in bounds:
            block = text[start:end]
            lead = len(block) - len(block.lstrip())
            trail = len(block) - len(block.rstrip())
            inner_start, inner_end = start + lead, end - trail
            if inner_end > inner_start:
                spans.append((inner_start, inner_end))
        return spans
