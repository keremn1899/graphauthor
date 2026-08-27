"""First-class escalation/handoff — typed gap travels to the human."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from interaction.models import GovernanceVerdict, ResponseAction


class EscalationHandoff(BaseModel):
    """Precise gap context for human review — write-path seam (capture only, no update)."""

    handoff_id: str
    decision_id: str
    case_id: str = ""
    question: str
    ungoverned_predicate: str
    status: str
    resolution: str
    governance_verdict_source: str = ""
    engine_verdict: str = ""
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    captured_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_decision(
        cls,
        *,
        handoff_id: str,
        case_id: str,
        decision_id: str,
        verdict: GovernanceVerdict,
        resolution: str,
    ) -> EscalationHandoff:
        return cls(
            handoff_id=handoff_id,
            decision_id=decision_id,
            case_id=case_id,
            question=verdict.question,
            ungoverned_predicate=verdict.ungoverned_predicate or "(unspecified predicate)",
            status=verdict.status.value,
            resolution=resolution,
            governance_verdict_source=verdict.governance_verdict_source,
            engine_verdict=verdict.engine_verdict,
            provenance=list(verdict.provenance),
        )

    def human_summary(self) -> str:
        return (
            f"ESCALATION — no policy governs: {self.ungoverned_predicate}\n"
            f"Question: {self.question[:300]}\n"
            f"Source: {self.governance_verdict_source or 'engine'}"
        )


class EscalationLedger(BaseModel):
    """Accumulates escalations across a sustained case — first-class path, not afterthought."""

    handoffs: list[EscalationHandoff] = Field(default_factory=list)

    def record(
        self,
        *,
        case_id: str,
        decision_id: str,
        verdict: GovernanceVerdict,
        resolution: str,
    ) -> EscalationHandoff:
        hid = f"{case_id}:{decision_id}:{len(self.handoffs)}"
        handoff = EscalationHandoff.from_decision(
            handoff_id=hid,
            case_id=case_id,
            decision_id=decision_id,
            verdict=verdict,
            resolution=resolution,
        )
        self.handoffs.append(handoff)
        return handoff

    def batch_summary(self) -> str:
        if not self.handoffs:
            return "No escalations in this case."
        lines = [f"Escalations ({len(self.handoffs)}):"]
        for h in self.handoffs:
            lines.append(f"  • {h.ungoverned_predicate}")
        return "\n".join(lines)

    def all_have_typed_predicate(self) -> bool:
        return all(
            h.ungoverned_predicate
            and h.ungoverned_predicate != "(unspecified predicate)"
            for h in self.handoffs
            if h.status == "UNGOVERNED"
        )
