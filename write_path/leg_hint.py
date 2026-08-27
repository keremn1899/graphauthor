"""Two-tier B-hint — heuristic mid tier (no LLM required for machinery tests)."""

from __future__ import annotations

import re

from write_path.models import EscalationRecord, GapHintClass

_GOODWILL_RE = re.compile(
    r"goodwill|compensation|inconvenience|voucher.*wait|gesture|credit.*late",
    re.I,
)
_PROCEDURE_RE = re.compile(
    r"price.?match|competitor|redirect|address|delivery|refund|return|perishable|"
    r"use.?by|faulty|unfit|procedure|entitlement|rule",
    re.I,
)


def b_hint_heuristic(record: EscalationRecord) -> GapHintClass:
    """Free mid-tier hint — mirrors ``candidate_a_classify`` in legislatable probe."""
    pred = record.predicate
    if _GOODWILL_RE.search(pred):
        return GapHintClass.INTRINSIC
    if _PROCEDURE_RE.search(pred):
        return GapHintClass.LEGISLATABLE
    return GapHintClass.LEGISLATABLE


def b_hint_from_record(
    record: EscalationRecord,
    *,
    hint_override: GapHintClass | None = None,
) -> GapHintClass:
    if hint_override is not None:
        return hint_override
    prov = record.provenance or {}
    stored = str(prov.get("b_hint") or prov.get("gap_class") or "").upper()
    if stored in ("LEGISLATABLE", "INTRINSIC"):
        return GapHintClass(stored)
    return b_hint_heuristic(record)
