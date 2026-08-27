"""Deterministic applicability filters — the WHEN/WHERE spine (design: node-properties.md).

A query carries a CONTEXT (``as_of`` time, later ``artifact_path`` / structural
scope, …). A rule carries optional applicability properties. A rule governs a
query only if the context DETERMINISTICALLY satisfies every declared property;
otherwise it drops from the governing set. Zero LLM — this is the deterministic
tier that extends the existing rule×component applicability gate.

The governing law (see the design): a property is structured here ONLY because a
deterministic check consumes it. WHEN (temporal) is the first attribute. Every
property is OPTIONAL: an empty bound is open, both empty is timeless — a rule with
no temporal fields behaves exactly as today.

Malformed windows (unparseable dates, ``until < from``) are caught by
certification (``temporal_malformed``) and never published, so at query time
``rule_applies_at`` is lenient (a malformed bound is treated as open) rather than
silently dropping a rule.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# sentinel: a non-empty value that could not be parsed as a date
_INVALID = object()


def parse_date(s: str | None):
    """'' / None → None (an open bound). A parseable ISO-8601 date/datetime →
    ``date``. A non-empty unparseable value → the ``_INVALID`` sentinel (a data
    error certification will flag)."""
    s = (s or "").strip()
    if not s:
        return None
    # date granularity is enough for governance windows; take the date part of a
    # datetime and tolerate a trailing Z.
    head = s[:10]
    try:
        return date.fromisoformat(head)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return _INVALID


def _as_of_date(as_of: str | None) -> date:
    """The reference time a query is evaluated at: an explicit ``as_of`` (parsed),
    else today. An unparseable ``as_of`` falls back to today rather than erroring
    the whole query."""
    d = parse_date(as_of)
    if isinstance(d, date):
        return d
    return date.today()


def rule_applies_at(effective_from: str | None, effective_until: str | None,
                    as_of: str | None = None) -> bool:
    """Is a rule with this window in force at ``as_of``? Inclusive bounds; an
    empty/None bound is open; both empty → always in force. A malformed bound is
    treated as open (cert is the guard, not this)."""
    a = _as_of_date(as_of)
    af = parse_date(effective_from)
    au = parse_date(effective_until)
    if af is _INVALID:
        af = None
    if au is _INVALID:
        au = None
    if af is not None and a < af:
        return False
    if au is not None and a > au:
        return False
    return True


def temporal_malformed(effective_from: str | None, effective_until: str | None) -> bool:
    """A window is malformed if a non-empty bound is unparseable, or the closing
    bound precedes the opening one. This is what certification blocks on."""
    af = parse_date(effective_from)
    au = parse_date(effective_until)
    if af is _INVALID or au is _INVALID:
        return True
    if isinstance(af, date) and isinstance(au, date) and au < af:
        return True
    return False


# Optional applicability keys a rule node may carry (all empty = unconstrained).
APPLICABILITY_KEYS = ("effective_from", "effective_until")


def rule_is_applicable(rule: dict, context: dict | None) -> tuple[bool, str]:
    """Deterministically decide whether one rule applies under ``context``.
    Returns (applies, reason) — reason is '' when it applies, else the filter that
    excluded it (extensible: WHERE-structural will add its own reason here)."""
    ctx = context or {}
    if not rule_applies_at(rule.get("effective_from", ""), rule.get("effective_until", ""),
                           ctx.get("as_of")):
        return False, "temporal_out_of_window"
    return True, ""


def filter_applicable(rules: list[dict], context: dict | None) -> dict[str, Any]:
    """Partition ``rules`` into those that apply under ``context`` and those a
    deterministic filter excluded (each with its reason). Pure and order-preserving.

    ``rules`` are dicts carrying the optional applicability keys; unrelated keys
    (id, label, text_content, …) pass through untouched."""
    applicable: list[dict] = []
    filtered: list[dict] = []
    for r in rules:
        ok, reason = rule_is_applicable(r, context)
        if ok:
            applicable.append(r)
        else:
            filtered.append({**r, "filtered_reason": reason})
    return {"applicable": applicable, "filtered": filtered,
            "context": {"as_of": (context or {}).get("as_of") or _as_of_date(
                (context or {}).get("as_of")).isoformat()}}
