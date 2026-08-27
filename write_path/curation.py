"""Part B — curation workflow/dataflow (thin function surface, no UI)."""

from __future__ import annotations

from write_path.models import (
    ConfirmedCuration,
    CurationCandidate,
    CurationDecision,
    GapHintClass,
    PrimarySource,
    RecurrenceAnalysis,
    RejectedCuration,
)


class CurationWorkflow:
    """Candidates → human confirm-with-source → hand off to encode cycle."""

    def __init__(self, analysis: RecurrenceAnalysis):
        self._analysis = analysis
        self._candidates = {c.candidate_id: c for c in analysis.candidates}
        self._confirmed: dict[str, ConfirmedCuration] = {}
        self._rejected: dict[str, RejectedCuration] = {}
        self._deferred: set[str] = set()

    def list_candidates(self) -> list[CurationCandidate]:
        return [
            c for cid, c in self._candidates.items()
            if cid not in self._rejected and cid not in self._confirmed
            and cid not in self._deferred
        ]

    def list_recurring_intrinsic(self):
        return list(self._analysis.recurring_intrinsic)

    def get_candidate(self, candidate_id: str) -> CurationCandidate | None:
        return self._candidates.get(candidate_id)

    def confirm(
        self,
        candidate_id: str,
        *,
        gap_id: str,
        primary_source: PrimarySource,
    ) -> ConfirmedCuration:
        cand = self._candidates.get(candidate_id)
        if cand is None:
            raise KeyError(f"unknown candidate {candidate_id}")
        if cand.b_hint != GapHintClass.LEGISLATABLE:
            raise ValueError("cannot confirm non-legislatable-hinted candidate")
        rec = ConfirmedCuration(
            candidate_id=candidate_id,
            gap_id=gap_id,
            predicate=cand.sample_predicate,
            primary_source=primary_source,
        )
        self._confirmed[candidate_id] = rec
        self._deferred.discard(candidate_id)
        return rec

    def reject(self, candidate_id: str, *, reason: str) -> RejectedCuration:
        if candidate_id not in self._candidates:
            raise KeyError(f"unknown candidate {candidate_id}")
        rec = RejectedCuration(candidate_id=candidate_id, reason=reason)
        self._rejected[candidate_id] = rec
        self._deferred.discard(candidate_id)
        return rec

    def defer(self, candidate_id: str) -> CurationDecision:
        if candidate_id not in self._candidates:
            raise KeyError(f"unknown candidate {candidate_id}")
        self._deferred.add(candidate_id)
        return CurationDecision.DEFERRED

    def status(self, candidate_id: str) -> CurationDecision:
        if candidate_id in self._confirmed:
            return CurationDecision.CONFIRMED
        if candidate_id in self._rejected:
            return CurationDecision.REJECTED
        if candidate_id in self._deferred:
            return CurationDecision.DEFERRED
        return CurationDecision.PENDING

    def confirmed_for_encode(self) -> list[ConfirmedCuration]:
        return list(self._confirmed.values())
