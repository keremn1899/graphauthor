"""Part A — predicate-frequency recurrence with B-hint composition."""

from __future__ import annotations

import re
from collections import defaultdict

from write_path.config import RecurrenceConfig
from write_path.leg_hint import b_hint_from_record
from write_path.models import (
    CurationCandidate,
    EscalationRecord,
    GapHintClass,
    PredicateFrequency,
    RecurrenceAnalysis,
    RecurringIntrinsicEscalation,
    normalize_predicate,
)

_GAP_ID_RE = re.compile(r"^(GAP\d+|LEG-PERISH|ADJ\d+)$")


def recurrence_key(rec: EscalationRecord) -> str:
    """Group key — labeled gap id when present, else normalized predicate."""
    q = (rec.query_id or "").strip()
    if _GAP_ID_RE.match(q):
        return q
    return rec.normalized_predicate


def build_frequency_table(
    records: list[EscalationRecord],
    *,
    config: RecurrenceConfig | None = None,
) -> dict[str, PredicateFrequency]:
    cfg = config or RecurrenceConfig()
    windowed = records[-cfg.window_size :] if cfg.window_size else records
    table: dict[str, PredicateFrequency] = {}

    for rec in windowed:
        key = recurrence_key(rec)
        if not key:
            continue
        if key not in table:
            table[key] = PredicateFrequency(normalized_predicate=key)
        row = table[key]
        row.count += 1
        row.raw_predicates.append(rec.predicate)
        if rec.query_id and rec.query_id not in row.query_ids:
            row.query_ids.append(rec.query_id)
        if rec.case_id and rec.case_id not in row.case_ids:
            row.case_ids.append(rec.case_id)
        hint = b_hint_from_record(rec).value
        row.b_hint_votes[hint] = row.b_hint_votes.get(hint, 0) + 1

    return table


def analyze_recurrence(
    records: list[EscalationRecord],
    *,
    config: RecurrenceConfig | None = None,
) -> RecurrenceAnalysis:
    cfg = config or RecurrenceConfig()
    table = build_frequency_table(records, config=cfg)

    candidates: list[CurationCandidate] = []
    recurring_intrinsic: list[RecurringIntrinsicEscalation] = []
    below: list[PredicateFrequency] = []

    for key, freq in sorted(table.items(), key=lambda kv: -kv[1].count):
        if freq.count < cfg.min_occurrences:
            below.append(freq)
            continue
        hint = freq.dominant_hint
        sample = freq.raw_predicates[0] if freq.raw_predicates else key
        cid = f"cand:{key[:48]}"
        if hint == GapHintClass.LEGISLATABLE:
            candidates.append(
                CurationCandidate(
                    candidate_id=cid,
                    normalized_predicate=key,
                    sample_predicate=sample,
                    occurrence_count=freq.count,
                    b_hint=hint,
                    query_ids=list(freq.query_ids),
                    provenance=[{"case_ids": freq.case_ids}],
                )
            )
        else:
            recurring_intrinsic.append(
                RecurringIntrinsicEscalation(
                    normalized_predicate=key,
                    sample_predicate=sample,
                    occurrence_count=freq.count,
                    b_hint=hint,
                )
            )

    return RecurrenceAnalysis(
        config_min_occurrences=cfg.min_occurrences,
        candidates=candidates,
        recurring_intrinsic=recurring_intrinsic,
        below_threshold=below,
    )


def records_from_capture_rows(rows: list[dict]) -> list[EscalationRecord]:
    """Convert engine capture JSON to escalation records (UNGOVERNED only)."""
    out: list[EscalationRecord] = []
    for r in rows:
        if str(r.get("governance_verdict", "")).upper() != "UNGOVERNED":
            continue
        pred = str(r.get("ungoverned_predicate") or "").strip()
        if not pred:
            continue
        prov = {
            "b_hint": (r.get("triage") or {}).get("b_hint", {}).get("gap_class")
            or (r.get("human_confirm") or {}).get("b_hint"),
            "run": r.get("run"),
            "phase": r.get("phase"),
        }
        out.append(
            EscalationRecord(
                predicate=pred,
                query_id=str(r.get("query_id") or ""),
                case_id=str(r.get("case_id") or ""),
                decision_id=str(r.get("decision_id") or ""),
                captured_at=str(r.get("captured_at") or ""),
                provenance=prov,
            )
        )
    return out


def records_from_handoffs(
    handoffs: list,
    *,
    step_index: dict | None = None,
) -> list[EscalationRecord]:
    """Convert interaction EscalationLedger handoffs → recurrence records (real seam)."""
    out: list[EscalationRecord] = []
    for h in handoffs:
        if str(getattr(h, "status", "")).upper() != "UNGOVERNED":
            continue
        pred = str(getattr(h, "ungoverned_predicate", "") or "").strip()
        if not pred or pred == "(unspecified predicate)":
            continue
        decision_id = str(getattr(h, "decision_id", "") or "")
        step = (step_index or {}).get(decision_id, {})
        gap_id = str(step.get("related_id") or "")
        out.append(
            EscalationRecord(
                predicate=pred,
                query_id=gap_id or decision_id,
                case_id=str(getattr(h, "case_id", "") or ""),
                decision_id=decision_id,
                captured_at=str(getattr(h, "captured_at", "") or ""),
                provenance={
                    "handoff_id": getattr(h, "handoff_id", ""),
                    "governance_verdict_source": getattr(h, "governance_verdict_source", ""),
                },
            )
        )
    return out
