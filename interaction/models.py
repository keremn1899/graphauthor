"""Structured types for the interaction framework."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class GovernanceStatus(str, Enum):
    GOVERNED = "GOVERNED"
    PARTIALLY_GOVERNED = "PARTIALLY_GOVERNED"
    UNGOVERNED = "UNGOVERNED"
    ABSENT = "ABSENT"


class ResponseAction(str, Enum):
    ACT = "ACT"
    ESCALATE = "ESCALATE"
    REFUSE = "REFUSE"


class GovernanceVerdict(BaseModel):
    """Structured verdict returned by ``what_governs`` — agent-consumable, not prose."""

    status: GovernanceStatus
    question: str
    ungoverned_predicate: str = ""
    grounding_summary: str = ""
    engine_verdict: str = ""
    governance_verdict_source: str = ""
    decision_predicate: str = ""
    applying_policy_ids: list[str] = Field(default_factory=list)
    authority_binding: str = ""
    unsupported_presuppositions: list[str] = Field(default_factory=list)
    unresolved_predicates: list[str] = Field(default_factory=list)
    coverage_sufficient: bool = True
    coverage_withheld_reason: str = ""
    planner_route: str = ""
    evidence_node_ids: list[str] = Field(default_factory=list)
    evidence_node_labels: list[str] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    degradation_flags: list[str] = Field(default_factory=list)
    engine_degraded: bool = False
    gov_header_debug: str = ""


    @property
    def is_gap(self) -> bool:
        return self.status in (
            GovernanceStatus.PARTIALLY_GOVERNED,
            GovernanceStatus.UNGOVERNED,
            GovernanceStatus.ABSENT,
        )

    def to_agent_block(self) -> str:
        """Visible block the agent reasons over (structured header + summary)."""
        head = f"GOVERNANCE STATUS: {self.status.value}"
        if self.status == GovernanceStatus.UNGOVERNED and self.ungoverned_predicate:
            head += f"\nUNGOVERNED PREDICATE: {self.ungoverned_predicate}"
        if self.status == GovernanceStatus.PARTIALLY_GOVERNED:
            head += "\nOWNER DECISION REQUIRED: true"
            if self.unresolved_predicates:
                head += "\nUNRESOLVED PREDICATES: " + "; ".join(
                    self.unresolved_predicates
                )
        body = self.grounding_summary or "(no grounding summary)"
        return f"{head}\n\n{body}"


class GapResolution(BaseModel):
    """Output of a configurable gap policy — maps a gap to agent behaviour."""

    action: ResponseAction
    resolution: str
    capture_handoff: bool = True
    policies_cited: list[str] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    """One grounded sub-decision inside a sustained case."""

    decision_id: str
    order: int
    label: str
    question: str
    verdict: GovernanceVerdict
    agent_action: ResponseAction | Literal[""] = ""
    bound_action: ResponseAction
    resolution: str = ""
    policies_cited: list[str] = Field(default_factory=list)
    confabulation: bool = False
    verdict_ok: bool | None = None
    expected_status: GovernanceStatus | None = None

    def check_invariants(self) -> list[str]:
        violations: list[str] = []
        if self.confabulation:
            violations.append("confabulation_on_gap")
        if (
            self.verdict.status in (
                GovernanceStatus.PARTIALLY_GOVERNED,
                GovernanceStatus.UNGOVERNED,
            )
            and self.agent_action == ResponseAction.ACT
        ):
            violations.append("agent_act_on_governance_gap")
        return violations


class CaseResult(BaseModel):
    case_id: str
    shape: str
    decisions: list[DecisionRecord] = Field(default_factory=list)
    all_queried: bool = False
    invariant_violations: list[str] = Field(default_factory=list)

    @property
    def confabulation_count(self) -> int:
        return sum(1 for d in self.decisions if d.confabulation)
