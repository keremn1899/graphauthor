"""Source-faithful Markdown blocks for workbook programs.

This parser is self-contained.  Construction policy belongs in the agent's
``build.py``; this module only exposes the document's own block and heading
structure with stable addresses.
"""

from __future__ import annotations

import hashlib
import re

from source_pipeline.contracts import (
    ParsedSource,
    ParserDescriptor,
    ParserSupport,
    SourceArtifact,
    assemble_units,
)


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_THEMATIC_BREAK = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_DIVIDER_CELL = re.compile(r"^:?-{3,}:?$")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "preamble"


def _fence_transition(
    line: str, fence: tuple[str, int] | None
) -> tuple[str, int] | None:
    match = _FENCE.match(line)
    if not match:
        return fence
    marker, info = match.group(1), match.group(2).strip()
    char, run = marker[0], len(marker)
    if fence is None:
        return None if char == "`" and "`" in info else (char, run)
    if char == fence[0] and run >= fence[1] and not info:
        return None
    return fence


def _table_cells(line: str) -> list[str]:
    value = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in value.split("|")]


def _table_rows(block: dict) -> list[dict] | None:
    lines = block["text"].splitlines()
    if len(lines) < 3:
        return None
    headers = _table_cells(lines[0])
    divider = _table_cells(lines[1])
    if not headers or len(headers) != len(divider) or not all(
        _TABLE_DIVIDER_CELL.fullmatch(cell.replace(" ", "")) for cell in divider
    ):
        return None
    rows: list[dict] = []
    for index, raw_row in enumerate(lines[2:], start=1):
        cells = _table_cells(raw_row)
        if any(cells):
            rows.append(
                {
                    **block,
                    "key": f"{block['key']}:row:{index}",
                    "start_line": block["start_line"] + index + 1,
                    "end_line": block["start_line"] + index + 1,
                    "text": raw_row.strip(),
                    "table_headers": headers,
                    "table_cells": cells,
                    "table_row": index,
                }
            )
    return rows or None


def _blocks(markdown: str) -> list[dict]:
    lines = markdown.splitlines()
    pending: list[str] = []
    start_line = 1
    per_heading: dict[str, int] = {}
    per_section: dict[str, int] = {}
    out: list[dict] = []
    fence: tuple[str, int] | None = None
    stack: list[tuple[int, str, int, str]] = []

    def section() -> dict:
        if not stack:
            return {
                "heading": "Preamble", "heading_level": 0,
                "heading_line": 0, "section_key": "",
                "section_path": [], "parent_section_key": "",
            }
        level, title, line, key = stack[-1]
        return {
            "heading": title, "heading_level": level, "heading_line": line,
            "section_key": key,
            "section_path": [entry[1] for entry in stack],
            "parent_section_key": stack[-2][3] if len(stack) > 1 else "",
        }

    def flush(end_line: int) -> None:
        nonlocal pending
        text = "\n".join(pending).strip()
        pending = []
        if not text or _THEMATIC_BREAK.fullmatch(text):
            return
        current = section()
        heading_slug = _slug(current["heading"])
        per_heading[heading_slug] = per_heading.get(heading_slug, 0) + 1
        index = per_heading[heading_slug]
        block = {
            **current, "heading_slug": heading_slug, "block_index": index,
            "key": f"{heading_slug}:{index}", "start_line": start_line,
            "end_line": end_line, "text": text,
        }
        out.extend(_table_rows(block) or [block])

    for line_number, line in enumerate(lines, start=1):
        moved = _fence_transition(line, fence)
        if moved != fence or fence is not None:
            if not pending:
                start_line = line_number
            pending.append(line)
            fence = moved
            continue
        match = _HEADING.match(line)
        if match:
            flush(line_number - 1)
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            path = [*(entry[1] for entry in stack), title]
            key = "/".join(_slug(part) for part in path)
            per_section[key] = per_section.get(key, 0) + 1
            if per_section[key] > 1:
                key = f"{key}#{per_section[key]}"
            stack.append((level, title, line_number, key))
            start_line = line_number + 1
            continue
        if not line.strip():
            flush(line_number - 1)
            start_line = line_number + 1
            continue
        if not pending:
            start_line = line_number
        pending.append(line)
    flush(len(lines))
    return out


class MarkdownSourceParser:
    """Expose Markdown blocks without assigning graph kinds or predicates."""

    descriptor = ParserDescriptor(
        parser_id="markdown-blocks",
        version=1,
        media_types=("text/markdown", "text/x-markdown"),
    )

    def supports(self, artifact: SourceArtifact) -> ParserSupport:
        media_type = artifact.media_type.split(";", 1)[0].strip().casefold()
        suffix_match = artifact.locator.casefold().endswith((".md", ".markdown"))
        supported = media_type in self.descriptor.media_types or suffix_match
        return ParserSupport(
            supported=supported,
            reason="Markdown media type or filename" if supported else "not Markdown",
        )

    def parse(self, artifact: SourceArtifact) -> ParsedSource:
        text = artifact.content.decode("utf-8")
        blocks = _blocks(text)
        if not blocks:
            raise ValueError("source contains no addressable Markdown blocks")
        records: list[dict] = []
        outline: list[dict] = []
        for index, block in enumerate(blocks, start=1):
            section_path = tuple(block.get("section_path") or ())
            locator = (
                f"{artifact.locator or 'inline.md'}#"
                f"{block['heading_slug']}:{block['block_index']}"
                f"/lines:{block['start_line']}-{block['end_line']}"
            )
            stable = hashlib.sha256(locator.encode("utf-8")).hexdigest()[:12]
            kind = "table_row" if "table_cells" in block else "markdown_block"
            records.append(
                {
                    "unit_id": f"{artifact.source_id}#md:{stable}",
                    "locator": locator,
                    "text": block["text"],
                    "kind": kind,
                    "prose": kind != "table_row",
                    "heading_path": section_path,
                    "metadata": {
                        "parser_order": index,
                        "heading": block.get("heading") or "",
                        "heading_level": block.get("heading_level") or 0,
                        "section_key": block.get("section_key") or "",
                        "parent_section_key": block.get("parent_section_key") or "",
                        **(
                            {
                                "table_headers": block["table_headers"],
                                "table_cells": block["table_cells"],
                                "table_row": block["table_row"],
                            }
                            if "table_headers" in block else {}
                        ),
                        "source_parser": self.descriptor.parser_id,
                    },
                }
            )
            heading = str(block.get("heading") or "").strip()
            if heading:
                entry = {
                    "heading": heading,
                    "level": int(block.get("heading_level") or 0),
                    "path": list(section_path),
                    "locator": locator,
                }
                if not outline or outline[-1] != entry:
                    outline.append(entry)

        representation, units = assemble_units(
            source_id=artifact.source_id,
            records=records,
        )
        return ParsedSource(
            source_id=artifact.source_id,
            artifact_fingerprint=artifact.fingerprint(),
            artifact_content_sha256=artifact.content_sha256,
            parser=self.descriptor,
            status="PARSED",
            fidelity="NORMALIZED",
            representation=representation,
            units=units,
            outline=tuple(outline),
            metadata={"encoding": "utf-8"},
        )
