"""Interaction framework — sustained agent loop over the SST governance engine.

Universal invariant core + configurable gap-resolution policy. See
``design [new]/interaction-framework-design-handoff.md``.
"""

from interaction.escalation import EscalationLedger, EscalationHandoff
from interaction.gap_policy import GapResolutionPolicy, TescoEscalatePolicy, RefuseAndFlagPolicy
from interaction.loop import InteractionSession, CaseResult
from interaction.models import (
    GovernanceStatus,
    GovernanceVerdict,
    ResponseAction,
    DecisionRecord,
)
from interaction.response_semantics import apply_response_semantics
from interaction.tool_surface import GovernanceTool, WHAT_GOVERNS_TOOL_SCHEMA

__all__ = [
    "GovernanceStatus",
    "GovernanceVerdict",
    "ResponseAction",
    "DecisionRecord",
    "GovernanceTool",
    "WHAT_GOVERNS_TOOL_SCHEMA",
    "apply_response_semantics",
    "GapResolutionPolicy",
    "TescoEscalatePolicy",
    "RefuseAndFlagPolicy",
    "EscalationLedger",
    "EscalationHandoff",
    "InteractionSession",
    "CaseResult",
]
