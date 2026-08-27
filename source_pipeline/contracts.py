"""Portable contracts for source parsing and segmentation.

There are three deliberately separate claims in this module:

* an artifact pins the bytes supplied by a caller;
* a parser exposes a canonical, addressable representation of those bytes;
* a segmenter partitions one addressable unit for bounded construction.

Only the last two are extensibility points.  Neither has graph-write authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _fingerprint(prefix: str, payload: Any) -> str:
    blob = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(blob).hexdigest()[:24]}"


class SourceArtifact(BaseModel):
    """Pinned raw input before any parser normalizes or extracts it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    media_type: str
    content: bytes
    locator: str = ""
    source_uri: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty_identity(self) -> "SourceArtifact":
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.media_type.strip():
            raise ValueError("media_type must not be empty")
        return self

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def fingerprint(self) -> str:
        return _fingerprint(
            "src",
            {
                "source_id": self.source_id,
                "media_type": self.media_type.casefold(),
                "content_sha256": self.content_sha256,
                "locator": self.locator,
                "source_uri": self.source_uri,
            },
        )


class ParseDiagnostic(BaseModel):
    """Visible parser/segmenter degradation or accounting information."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Literal["info", "warning", "error"] = "info"
    message: str
    locator: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ParserDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parser_id: str
    version: int = Field(ge=1)
    media_types: tuple[str, ...]
    config_fingerprint: str = ""


class ParserSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supported: bool
    reason: str


class SourceUnit(BaseModel):
    """One parser-addressable slice of a canonical representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    source_id: str
    locator: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    kind: str = "block"
    heading_path: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    #: Navigation, boilerplate, licence footers — content the document carries
    #: about itself rather than content it is about. Set by the PARSER, which
    #: knows: an HTML parser can see a <nav> ancestor, while a downstream rule
    #: can only guess. The guess we shipped was "no heading path", which is
    #: right for one site's HTML and silently discarded every page of a PDF,
    #: because PDF units have no heading path at all.
    #:
    #: Advisory, never a filter here. It is left in the stream and flagged, so
    #: that a program skipping it is making a visible choice and `atoms
    #: coverage` can report chrome that nonetheless produced nodes — which is
    #: how a translator's name ends up as a character.
    chrome: bool = False
    #: Does this unit carry running prose, as opposed to a heading, a table
    #: row, a caption or a code block?
    #:
    #: Same argument as `chrome`, and found the same way. Each parser has its
    #: own `kind` vocabulary -- HTML emits `p`/`text`/`list_item`/`heading`,
    #: Markdown emits `markdown_block`, plain text emits `block`, PDF emits
    #: `page` -- and nothing declared the correspondence. A program written
    #: against one parser selected prose with
    #: `kind in {"p", "text", "list_item"}`, which is correct for HTML and
    #: matches nothing a PDF produces. Measured: 162 pages of real papers,
    #: 1,440 sentences that scored as claims, and zero claims in the output,
    #: because every atom was skipped before scoring.
    #:
    #: A parser knows whether it just emitted prose. A downstream rule can
    #: only guess from a tag name it did not define.
    prose: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_span(self) -> "SourceUnit":
        if not self.unit_id.strip():
            raise ValueError("unit_id must not be empty")
        if self.end < self.start:
            raise ValueError("source unit end precedes start")
        if self.end - self.start != len(self.text):
            raise ValueError("source unit offsets do not match text length")
        return self

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class ParsedSource(BaseModel):
    """A parser result whose offsets are checked against its representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    artifact_fingerprint: str
    artifact_content_sha256: str
    parser: ParserDescriptor
    status: Literal["PARSED", "PARTIAL", "ABSTAINED", "FAILED"]
    fidelity: Literal["EXACT", "NORMALIZED", "EXTRACTED"]
    representation: str
    units: tuple[SourceUnit, ...] = ()
    outline: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[ParseDiagnostic, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_units(self) -> "ParsedSource":
        seen: set[str] = set()
        previous_end = 0
        for unit in self.units:
            if unit.source_id != self.source_id:
                raise ValueError("parsed unit belongs to a different source")
            if unit.unit_id in seen:
                raise ValueError(f"duplicate parsed unit id: {unit.unit_id}")
            seen.add(unit.unit_id)
            if unit.end > len(self.representation):
                raise ValueError(f"parsed unit is outside representation: {unit.unit_id}")
            if self.representation[unit.start : unit.end] != unit.text:
                raise ValueError(f"parsed unit text does not match representation: {unit.unit_id}")
            if unit.start < previous_end:
                raise ValueError(f"parsed units overlap: {unit.unit_id}")
            previous_end = unit.end
        if self.status in {"PARSED", "PARTIAL"} and not self.units:
            raise ValueError("successful parse must contain at least one source unit")
        return self

    def fingerprint(self) -> str:
        return _fingerprint(
            "parse",
            {
                "artifact_fingerprint": self.artifact_fingerprint,
                "artifact_content_sha256": self.artifact_content_sha256,
                "parser": self.parser.model_dump(mode="json"),
                "status": self.status,
                "fidelity": self.fidelity,
                "representation_sha256": hashlib.sha256(
                    self.representation.encode("utf-8")
                ).hexdigest(),
                "units": [
                    {
                        "id": unit.unit_id,
                        "locator": unit.locator,
                        "text_sha256": unit.text_sha256,
                    }
                    for unit in self.units
                ],
            },
        )


class SegmenterDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segmenter_id: str
    version: int = Field(ge=1)
    config_fingerprint: str = ""


class SegmentationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_atom_chars: int = Field(default=6000, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceAtom(BaseModel):
    """One exact slice of a source unit, never a graph assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    atom_id: str
    source_id: str
    unit_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_span(self) -> "SourceAtom":
        if self.end < self.start:
            raise ValueError("source atom end precedes start")
        if self.end - self.start != len(self.text):
            raise ValueError("source atom offsets do not match text length")
        return self


class SegmentationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["APPLIED", "ABSTAINED", "FAILED"]
    atoms: tuple[SourceAtom, ...] = ()
    basis: Literal["source_structure", "syntax", "heuristic", "agent_program"]
    diagnostics: tuple[ParseDiagnostic, ...] = ()

    @model_validator(mode="after")
    def _status_shape(self) -> "SegmentationDecision":
        if self.status == "APPLIED" and not self.atoms:
            raise ValueError("APPLIED segmentation requires atoms")
        if self.status != "APPLIED" and self.atoms:
            raise ValueError("only APPLIED segmentation may return atoms")
        return self


class SegmentationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    status: Literal["APPLIED", "PASSTHROUGH", "ABSTAINED", "FAILED"]
    attempted_segmenters: tuple[SegmenterDescriptor, ...] = ()
    selected_segmenter: SegmenterDescriptor | None = None
    atom_ids: tuple[str, ...] = ()
    diagnostics: tuple[ParseDiagnostic, ...] = ()


class SegmentedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parsed_source_fingerprint: str
    atoms: tuple[SourceAtom, ...]
    records: tuple[SegmentationRecord, ...]

    def fingerprint(self) -> str:
        return _fingerprint(
            "segments",
            {
                "parsed_source_fingerprint": self.parsed_source_fingerprint,
                "atoms": [atom.model_dump(mode="json") for atom in self.atoms],
                "records": [record.model_dump(mode="json") for record in self.records],
            },
        )


@runtime_checkable
class SourceParser(Protocol):
    descriptor: ParserDescriptor

    def supports(self, artifact: SourceArtifact) -> ParserSupport: ...

    def parse(self, artifact: SourceArtifact) -> ParsedSource: ...


@runtime_checkable
class UnitSegmenter(Protocol):
    descriptor: SegmenterDescriptor

    def supports(self, unit: SourceUnit, context: SegmentationContext) -> bool: ...

    def segment(
        self,
        unit: SourceUnit,
        context: SegmentationContext,
    ) -> SegmentationDecision: ...


def assemble_units(
    *,
    source_id: str,
    records: list[dict[str, Any]],
) -> tuple[str, tuple[SourceUnit, ...]]:
    """Build one canonical representation and exact non-overlapping spans."""

    pieces: list[str] = []
    units: list[SourceUnit] = []
    cursor = 0
    for index, record in enumerate(records):
        text = str(record["text"])
        if index:
            separator = "\n\n"
            pieces.append(separator)
            cursor += len(separator)
        start = cursor
        pieces.append(text)
        cursor += len(text)
        units.append(
            SourceUnit(
                unit_id=str(record["unit_id"]),
                source_id=source_id,
                locator=str(record["locator"]),
                text=text,
                start=start,
                end=cursor,
                kind=str(record.get("kind") or "block"),
                heading_path=tuple(record.get("heading_path") or ()),
                links=tuple(record.get("links") or ()),
                chrome=bool(record.get("chrome", False)),
                prose=bool(record.get("prose", False)),
                metadata=dict(record.get("metadata") or {}),
            )
        )
    return "".join(pieces), tuple(units)
