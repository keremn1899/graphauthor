"""Callable conformance surface — rule + real file → typed verdict."""

from conformance_check.framing import (
    build_case,
    frame_conformance_question,
    frame_existing_code_question,
    frame_insufficient_question,
    frame_proposed_change_question,
    frame_scope_moat_question,
    list_rule_ids,
    resolve_rule,
)
from conformance_check.surface import (
    VERDICT_EXIT_CODES,
    check_conformance,
    report_to_json,
    run_sanity_batch,
    scan_conformance,
    structural_insufficient_reason,
    verdict_exit_code,
)

__all__ = [
    "VERDICT_EXIT_CODES",
    "build_case",
    "check_conformance",
    "scan_conformance",
    "structural_insufficient_reason",
    "frame_conformance_question",
    "frame_existing_code_question",
    "frame_insufficient_question",
    "frame_proposed_change_question",
    "frame_scope_moat_question",
    "list_rule_ids",
    "report_to_json",
    "resolve_rule",
    "run_sanity_batch",
    "verdict_exit_code",
]
