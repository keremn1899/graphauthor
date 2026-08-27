"""Coverage / gap ledger — the lead engine as a pure deterministic fold.

The honest gaps ARE the roadmap. Every ``what_governs`` / ``check_conformance``
verdict that comes back without coverage (`UNGOVERNED` / `ABSENT` /
`INSUFFICIENT_EVIDENCE`) is recorded as an event by the surface; this folds those
events into a ranked gap ledger.

The one thing that matters (and the only non-obvious part): recurrence is keyed
on the **ungoverned predicate**, not the raw question — so "what governs refunds?"
and "is the refund window governed?" collapse to one recurring lead instead of
two. When no predicate is present the fold falls back to a normalised question.
No LLM anywhere: record, then aggregate.
"""

from __future__ import annotations

import json
import re

# Verdicts that mean "the graph does not cover this" — the roadmap signal.
# Verdicts that mean "the graph does not cover this" — the roadmap signal.
#
# ILL_POSED and UNKNOWN_TO_GRAPH are confirmation-space absences: the question
# cannot be asked of this graph's shape, or the content simply is not there.
# Both are as much roadmap as an ungoverned predicate is, and neither was
# counted until `discover` began recording.
#
# EXHAUSTED is deliberately NOT here. "We searched and the answer is no" is
# often a correct answer, not a gap, and counting it would drown the ledger in
# legitimate negatives.
GAP_VERDICTS = ("UNGOVERNED", "ABSENT", "INSUFFICIENT_EVIDENCE", "INSUFFICIENT",
                "ILL_POSED", "UNKNOWN_TO_GRAPH")
# A different signal: a governed thing was broken. Tracked separately.
VIOLATION_VERDICTS = ("VIOLATES",)
_GAP_PREFIXES = ("conformance.completed:", "governance.coverage_checked:",
                 "query.completed:")

# A gap becomes a "lead" once it recurs — one-offs are noise, repetition is signal.
LEAD_THRESHOLD = 2

_WS = re.compile(r"\s+")


def _norm(q: str) -> str:
    return _WS.sub(" ", str(q or "").strip().lower())


def _verdict_of(evtype: str) -> str:
    for p in _GAP_PREFIXES:
        if evtype.startswith(p):
            return evtype[len(p):].upper()
    return ""


def _payload(ev: dict) -> dict:
    p = ev.get("payload")
    if isinstance(p, str):
        try:
            return json.loads(p or "{}")
        except ValueError:
            return {}
    return p or {}


def project_coverage(events: list[dict], *, lead_threshold: int = LEAD_THRESHOLD) -> dict:
    """Fold the event log into a ranked gap ledger. Pure and deterministic:
    dropping and replaying the same events yields the same output."""
    gaps: dict[str, dict] = {}
    violations: dict[str, dict] = {}

    for ev in events or []:
        verdict = _verdict_of(str(ev.get("type") or ""))
        if not verdict:
            continue
        pl = _payload(ev)
        question = str(pl.get("question") or pl.get("subject") or "")
        # recurrence key: the predicate (indexed gap_id column) first, the
        # normalised question only as a fallback.
        key = (str(ev.get("gap_id") or "").strip()) or _norm(question)
        if not key:
            continue
        try:
            ts = float(ev.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0

        if verdict in VIOLATION_VERDICTS:
            bucket = violations
        elif verdict in GAP_VERDICTS:
            bucket = gaps
        else:
            continue

        g = bucket.get(key)
        if g is None:
            g = bucket[key] = {"key": key, "count": 0, "kinds": set(),
                               "examples": [], "first_seen": ts, "last_seen": ts}
        g["count"] += 1
        g["kinds"].add(verdict)
        g["first_seen"] = min(g["first_seen"], ts) if g["first_seen"] else ts
        g["last_seen"] = max(g["last_seen"], ts)
        if question and question not in g["examples"] and len(g["examples"]) < 3:
            g["examples"].append(question)

    def _finish(d: dict[str, dict]) -> list[dict]:
        rows = []
        for g in d.values():
            r = dict(g)
            r["kinds"] = sorted(r["kinds"])
            r["is_lead"] = r["count"] >= lead_threshold
            rows.append(r)
        # most-recurring first; stable tiebreak on key
        rows.sort(key=lambda x: (-x["count"], x["key"]))
        return rows

    glist = _finish(gaps)
    vlist = _finish(violations)
    return {
        "gaps": glist,
        "violations": vlist,
        "summary": {
            "distinct_gaps": len(glist),
            "total_gap_events": sum(g["count"] for g in glist),
            "leads": sum(1 for g in glist if g["is_lead"]),
            "distinct_violations": len(vlist),
        },
    }
