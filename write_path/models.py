"""Structured types for write-path machinery (workflow/dataflow only — no UI)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def normalize_predicate(text: str) -> str:
    return " ".join(str(text or "").lower().split())


class GapHintClass(str, Enum):
    LEGISLATABLE = "LEGISLATABLE"
    INTRINSIC = "INTRINSIC"
    UNKNOWN = "UNKNOWN"


class EscalationRecord(BaseModel):
    """One typed gap from the escalation capture."""

    predicate: str
    query_id: str = ""
    case_id: str = ""
    decision_id: str = ""
    captured_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)

    @property
    def normalized_predicate(self) -> str:
        return normalize_predicate(self.predicate)


class PredicateFrequency(BaseModel):
    normalized_predicate: str
    raw_predicates: list[str] = Field(default_factory=list)
    count: int = 0
    query_ids: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    b_hint_votes: dict[str, int] = Field(default_factory=dict)

    @property
    def dominant_hint(self) -> GapHintClass:
        if not self.b_hint_votes:
            return GapHintClass.UNKNOWN
        top = max(self.b_hint_votes.items(), key=lambda kv: kv[1])[0]
        try:
            return GapHintClass(top)
        except ValueError:
            return GapHintClass.UNKNOWN


class CurationCandidate(BaseModel):
    candidate_id: str
    normalized_predicate: str
    sample_predicate: str
    occurrence_count: int
    b_hint: GapHintClass
    query_ids: list[str] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)


class RecurringIntrinsicEscalation(BaseModel):
    normalized_predicate: str
    sample_predicate: str
    occurrence_count: int
    b_hint: GapHintClass
    note: str = "standing escalation — do not encode"


class RecurrenceAnalysis(BaseModel):
    config_min_occurrences: int
    candidates: list[CurationCandidate] = Field(default_factory=list)
    recurring_intrinsic: list[RecurringIntrinsicEscalation] = Field(default_factory=list)
    below_threshold: list[PredicateFrequency] = Field(default_factory=list)


class PrimarySource(BaseModel):
    """Human-supplied policy — machinery does NOT find this."""

    policy_id: str
    policy_label: str = ""
    source_url: str = ""
    source_note: str = ""
    connectivity_notes: str = ""


class CurationDecision(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    PENDING = "PENDING"


class ConfirmedCuration(BaseModel):
    candidate_id: str
    gap_id: str
    predicate: str
    primary_source: PrimarySource
    confirmed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RejectedCuration(BaseModel):
    candidate_id: str
    reason: str
    rejected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DistractorFinding(BaseModel):
    query_id: str
    kind: str
    gov_delta: float = 0.0
    ungov_delta: float = 0.0
    flaky_only: bool = False


class CycleGateResult(BaseModel):
    distractor_clean: bool
    findings: list[DistractorFinding] = Field(default_factory=list)
    closure_ok: bool = False
    right_reason: int = 0
    governed: int = 0
    n: int = 0


class EncodeCycleResult(BaseModel):
    gap_id: str
    committed: bool
    gate: CycleGateResult
    failure_reason: str = ""
    db_path: str = ""
    captures: list[dict[str, Any]] = Field(default_factory=list)
