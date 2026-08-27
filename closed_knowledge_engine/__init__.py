"""Closed Knowledge Engine — public conformance surface.

Install: ``pip install -e .`` (from this repo) or
``pip install -e .`` from this repository.

Import (recommended)::

    from closed_knowledge_engine import check_conformance, scan_conformance

Short alias::

    import closed_knowledge_engine as graphauthor
"""

from __future__ import annotations

__version__ = "0.1.0"

from conformance_check import (  # noqa: E402
    VERDICT_EXIT_CODES,
    build_case,
    check_conformance,
    frame_conformance_question,
    frame_existing_code_question,
    frame_insufficient_question,
    frame_proposed_change_question,
    frame_scope_moat_question,
    list_rule_ids,
    report_to_json,
    resolve_rule,
    run_sanity_batch,
    scan_conformance,
    structural_insufficient_reason,
    verdict_exit_code,
)
from conformance_verdict import ConformanceKind, ConformanceVerdict  # noqa: E402
from governance_dispatch import (  # noqa: E402
    DispatchRouter,
    EnforcementMechanism,
    TaggedRule,
    UnifiedConformanceReport,
)

__all__ = [
    "__version__",
    # Callable surface
    "check_conformance",
    "scan_conformance",
    "report_to_json",
    "verdict_exit_code",
    "VERDICT_EXIT_CODES",
    "run_sanity_batch",
    "structural_insufficient_reason",
    "list_rule_ids",
    "resolve_rule",
    "build_case",
    # Framing helpers
    "frame_conformance_question",
    "frame_existing_code_question",
    "frame_insufficient_question",
    "frame_proposed_change_question",
    "frame_scope_moat_question",
    # Types
    "ConformanceKind",
    "ConformanceVerdict",
    "UnifiedConformanceReport",
    "DispatchRouter",
    "EnforcementMechanism",
    "TaggedRule",
]
