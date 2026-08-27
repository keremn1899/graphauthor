"""Configurable gap-resolution policy seam (domain shell on invariant core)."""

from __future__ import annotations

from typing import Protocol

from interaction.models import GapResolution, GovernanceStatus, GovernanceVerdict, ResponseAction


class GapResolutionPolicy(Protocol):
    """Given a gap verdict, prescribe agent behaviour without relaxing invariants."""

    def resolve(self, verdict: GovernanceVerdict, *, decision_id: str = "") -> GapResolution:
        ...


class TescoEscalatePolicy:
    """Tesco support policy: gap → escalate to human, continue the case."""

    def resolve(self, verdict: GovernanceVerdict, *, decision_id: str = "") -> GapResolution:
        pred = (
            (verdict.unresolved_predicates or [""])[0]
            or verdict.ungoverned_predicate
            or "the requested predicate"
        )
        if verdict.status == GovernanceStatus.ABSENT:
            msg = (
                "No governance verdict was returned for this sub-issue (empty-packet "
                "seam). Under Tesco support policy: escalate to a human; do not "
                "resolve from adjacent policies or parametric knowledge."
            )
        elif verdict.status == GovernanceStatus.PARTIALLY_GOVERNED:
            msg = (
                f"Published policy governs only part of this decision; '{pred}' "
                "still requires a human owner decision. Do not act on the compound request."
            )
        else:
            msg = (
                f"No Tesco published policy governs: {pred}. Escalating to a human "
                "with the precise ungoverned predicate; do not resolve from adjacent "
                "policies."
            )
        return GapResolution(
            action=ResponseAction.ESCALATE,
            resolution=msg,
            capture_handoff=True,
            policies_cited=[],
        )


class RefuseAndFlagPolicy:
    """Alternate domain policy for seam verification — REFUSE instead of ESCALATE."""

    def resolve(self, verdict: GovernanceVerdict, *, decision_id: str = "") -> GapResolution:
        pred = (
            (verdict.unresolved_predicates or [""])[0]
            or verdict.ungoverned_predicate
            or "the requested predicate"
        )
        return GapResolution(
            action=ResponseAction.REFUSE,
            resolution=(
                f"Cannot proceed: no policy governs '{pred}'. Flagged for review."
            ),
            capture_handoff=True,
            policies_cited=[],
        )
