"""Universal response semantics: governed → act traceably; gap → gap policy."""

from __future__ import annotations

from typing import Literal

from interaction.gap_policy import GapResolutionPolicy
from interaction.models import (
    DecisionRecord,
    GapResolution,
    GovernanceStatus,
    GovernanceVerdict,
    ResponseAction,
)


def apply_response_semantics(
    verdict: GovernanceVerdict,
    *,
    decision_id: str,
    order: int,
    label: str,
    gap_policy: GapResolutionPolicy,
    agent_action: ResponseAction | str = "",
    resolution: str = "",
    policies_cited: list[str] | None = None,
    expected_status: GovernanceStatus | None = None,
) -> DecisionRecord:
    """Map engine verdict + domain policy → bound agent action (invariant-preserving)."""
    agent = _coerce_action(agent_action)
    cited = list(policies_cited or [])

    if verdict.status == GovernanceStatus.GOVERNED:
        bound = agent if agent else ResponseAction.ACT
        res = resolution or "Act on the governing policy grounding traceably."
        confab = False
    else:
        gap_res = gap_policy.resolve(verdict, decision_id=decision_id)
        bound = gap_res.action
        res = resolution or gap_res.resolution
        if not cited:
            cited = list(gap_res.policies_cited)
        confab = (
            verdict.status in (
                GovernanceStatus.PARTIALLY_GOVERNED,
                GovernanceStatus.UNGOVERNED,
            )
            and agent == ResponseAction.ACT
        )

    verdict_ok = (
        expected_status is None or verdict.status == expected_status
    )

    return DecisionRecord(
        decision_id=decision_id,
        order=order,
        label=label,
        question=verdict.question,
        verdict=verdict,
        agent_action=agent,
        bound_action=bound,
        resolution=res,
        policies_cited=cited,
        confabulation=confab,
        verdict_ok=verdict_ok,
        expected_status=expected_status,
    )


def structural_decision(
    verdict: GovernanceVerdict,
    *,
    decision_id: str,
    order: int,
    label: str,
    gap_policy: GapResolutionPolicy,
    expected_status: GovernanceStatus | None = None,
) -> DecisionRecord:
    """Harness: oracle agent follows semantics exactly (no LLM)."""
    if verdict.status == GovernanceStatus.GOVERNED:
        agent = ResponseAction.ACT
    else:
        agent = gap_policy.resolve(verdict, decision_id=decision_id).action
    return apply_response_semantics(
        verdict,
        decision_id=decision_id,
        order=order,
        label=label,
        gap_policy=gap_policy,
        agent_action=agent,
        expected_status=expected_status,
    )


def _coerce_action(raw: ResponseAction | str) -> ResponseAction | Literal[""]:
    if not raw:
        return ""
    if isinstance(raw, ResponseAction):
        return raw
    try:
        return ResponseAction(str(raw).upper())
    except ValueError:
        return ""
