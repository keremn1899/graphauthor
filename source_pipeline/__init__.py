"""Source preparation primitives for agent-authored workbook programs.

The package does not contain a graph constructor. It provides deterministic
parsers, segmenters, workbook storage, and mechanical encoding helpers that a
program authored by the user's agent may choose to use.
"""

from source_pipeline.contracts import (
    ParseDiagnostic,
    ParsedSource,
    ParserDescriptor,
    ParserSupport,
    SegmentationContext,
    SegmentationDecision,
    SegmentationRecord,
    SegmentedSource,
    SegmenterDescriptor,
    SourceArtifact,
    SourceAtom,
    SourceParser,
    SourceUnit,
    UnitSegmenter,
)
from source_pipeline.html import HtmlSourceParser
from source_pipeline.markdown import MarkdownSourceParser
from source_pipeline.pdf import PdfSourceParser
from source_pipeline.runner import parse_artifact, segment_parsed_source
from source_pipeline.segmenters import BoundedTextSegmenter
from source_pipeline.text import PlainTextSourceParser
from source_pipeline.workbook import Atom, StaleAtomStream, Workbook, write_workbook
from source_pipeline.draft import GraphDraft, GraphDraftError, SemanticDiff, semantic_diff
from source_pipeline.traversals import (
    WorkbookTraversalError,
    bind_workbook_traversals,
    load_bound_workbook_traversals,
)

__all__ = [
    "Atom",
    "BoundedTextSegmenter",
    "HtmlSourceParser",
    "GraphDraft",
    "GraphDraftError",
    "MarkdownSourceParser",
    "ParseDiagnostic",
    "ParsedSource",
    "ParserDescriptor",
    "ParserSupport",
    "PdfSourceParser",
    "PlainTextSourceParser",
    "SegmentationContext",
    "SegmentationDecision",
    "SegmentationRecord",
    "SegmentedSource",
    "SegmenterDescriptor",
    "SourceArtifact",
    "SourceAtom",
    "SourceParser",
    "SourceUnit",
    "SemanticDiff",
    "StaleAtomStream",
    "UnitSegmenter",
    "Workbook",
    "WorkbookTraversalError",
    "bind_workbook_traversals",
    "load_bound_workbook_traversals",
    "parse_artifact",
    "segment_parsed_source",
    "semantic_diff",
    "write_workbook",
]
