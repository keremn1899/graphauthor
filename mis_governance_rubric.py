"""Ruling-correct scoring for mis-governance probes.

Separates grounding-correct (right rule in packet) from ruling-correct
(allow vs deny vs conditional branch in final_answer prose).

Handoff: design [new]/governed-side-mis-governance-probe-handoff.md
"""

from __future__ import annotations

import re
from typing import Any

_RULING_TYPES = frozenset({"ALLOW", "DENY", "EXCHANGE_ONLY"})

_DENY_RE = re.compile(
    r"\b("
    r"cannot|can't|must not|may not|not permitted|not allowed|"
    r"not eligible|prohibited|not returnable|no returns?|"
    r"cannot be returned|not govern(?:ed)?.*allow|"
    r"forbidden|is denied|are denied|does not allow|do not allow|"
    r"should not|is not allowed"
    r")\b",
    re.I,
)
_ALLOW_RE = re.compile(
    r"\b("
    r"you can|may return|can return|is permitted|is allowed|"
    r"are permitted|are allowed|eligible for|entitled to|"
    r"refund is available|exchange is available|"
    r"may persist|can persist|is permitted to persist|"
    r"allowed to (?:call|invoke|import|persist|report)|"
    r"permitted to (?:call|invoke|import|persist|report)|"
    r"may (?:call|invoke|import|persist|report)|"
    r"can (?:call|invoke|import|persist|report)"
    r")\b",
    re.I,
)
_EXCHANGE_RE = re.compile(r"\bexchange\b", re.I)
_REFUND_DENY_RE = re.compile(
    r"\b("
    r"refund(?:s)? (?:is|are) not|no refund|not (?:eligible|entitled) for a refund|"
    r"cannot (?:get|receive|obtain) a refund|refund to (?:your |the )?card is not|"
    r"exchange only|only exchange|not a refund"
    r")\b",
    re.I,
)
_GOVERNED_JSON_RE = re.compile(
    r'"governance_verdict"\s*:\s*"(GOVERNED|UNGOVERNED)"',
    re.I,
)


def answer_body(text: str) -> str:
    """Prefer prose after **Answer:**; fall back to full text minus json block."""
    raw = text or ""
    m = re.search(r"\*\*Answer:\*\*\s*(.*)", raw, re.I | re.S)
    if m:
        return m.group(1).strip()
    # Drop leading governance json fence if present
    stripped = re.sub(r"```json\s*\{[^`]*\}\s*```", "", raw, count=1, flags=re.S | re.I)
    return stripped.strip()


def ruling_headline(body: str) -> str:
    """First answer paragraph — excludes provenance/background policy quotes."""
    return re.split(r"\n\s*\n|\*\*Provenance", body, maxsplit=1)[0].strip()


def grounding_correct(
    rec: dict,
    *,
    policy_ids: list[str] | None = None,
    label_tokens: list[str] | None = None,
) -> bool:
    """True when expected governing policies/rules appear in packet labels."""
    labels = [str(x).lower() for x in rec.get("node_labels", [])]
    blob = " ".join(labels) + " " + str(rec.get("final_answer", "")).lower()
    for pid in policy_ids or []:
        short = pid.split("_")[0]
        if any(pid.lower() in x or short in x for x in labels):
            return True
        if pid.lower() in blob or short in blob:
            return True
    for tok in label_tokens or []:
        if tok.lower() in blob:
            return True
    return False


def _any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def ruling_correct(answer: str, expected_ruling: str, query: dict) -> bool:
    """Score whether prose matches pre-registered ruling."""
    if expected_ruling not in _RULING_TYPES:
        return False
    body = answer_body(answer)
    if not body:
        return False

    allow_hints = query.get("ruling_allow_signals") or []
    deny_hints = query.get("ruling_deny_signals") or []
    headline = ruling_headline(body)

    has_allow = bool(_ALLOW_RE.search(body)) or _any_pattern(body, allow_hints)
    has_deny = bool(_DENY_RE.search(body)) or _any_pattern(body, deny_hints)
    has_allow_h = bool(_ALLOW_RE.search(headline)) or _any_pattern(headline, allow_hints)
    has_deny_h = bool(_DENY_RE.search(headline)) or _any_pattern(headline, deny_hints)

    if expected_ruling == "ALLOW":
        if has_deny and not has_allow:
            return False
        return has_allow or (not has_deny and _any_pattern(body, allow_hints))

    if expected_ruling == "DENY":
        # Headline must deny; background policy quotes must not override allow headline.
        if has_allow_h and not has_deny_h:
            return False
        return has_deny_h or _any_pattern(headline, deny_hints)

    if expected_ruling == "EXCHANGE_ONLY":
        has_exchange = bool(_EXCHANGE_RE.search(body)) or _any_pattern(
            body, query.get("ruling_exchange_signals") or []
        )
        refund_denied = bool(_REFUND_DENY_RE.search(body)) or _any_pattern(
            body, deny_hints
        )
        return has_exchange and refund_denied

    return False


def score_mis_governance(rec: dict, query: dict) -> dict[str, Any]:
    """Augment a capture record with mis-governance axes."""
    expected_gov = str(query.get("expected_governance") or query.get("expected") or "GOVERNED")
    expected_ruling = str(query.get("expected_ruling") or "")
    answer = str(rec.get("final_answer") or "")

    gov = str(rec.get("governance_verdict") or "ABSENT").upper()
    governed_bit_correct = gov == expected_gov.upper()

    gcorr = False
    if expected_gov.upper() == "GOVERNED":
        gcorr = grounding_correct(
            rec,
            policy_ids=list(query.get("required_policies") or query.get("grounding_policy_ids") or []),
            label_tokens=list(query.get("grounding_label_tokens") or []),
        )
    elif expected_gov.upper() == "UNGOVERNED":
        gcorr = True  # N/A for kill pins

    rcorr = False
    if governed_bit_correct and gov == "GOVERNED" and expected_ruling:
        rcorr = ruling_correct(answer, expected_ruling, query)

    mis_hit = bool(
        gov == "GOVERNED"
        and expected_ruling
        and gcorr
        and not rcorr
        and governed_bit_correct
    )

    # The mirror failure, which `mis_hit` cannot see. `mis_hit` requires
    # gov == "GOVERNED", so declining a case the corpus DOES govern scored as
    # nothing at all: `ruling_correct` came back None and the headline rate
    # stayed 0%. Measured over three full runs, that hid 6 failures against the
    # 3 it reported — the metric undercounted by 2x in the more dangerous
    # direction.
    #
    # Dangerous because a false UNGOVERNED is SILENT PERMISSION: in CI it means
    # "nothing governs your change", so the change is not gated. It is the exact
    # failure the product exists to prevent — a bounded decision treated as open
    # — and it was invisible in the number quoted as evidence.
    #
    # Observed cause on M_T_ADJ1: the right policy is retrieved (grounding is
    # correct) and the judgment still concludes UNGOVERNED because no rule names
    # the query's CATEGORY, ignoring that a general rule with no applicable
    # exception governs the case.
    false_ungoverned = bool(
        expected_gov.upper() == "GOVERNED"
        and gov != "GOVERNED"
    )

    return {
        "expected_governance": expected_gov,
        "expected_ruling": expected_ruling,
        "mis_class": query.get("mis_class", ""),
        "domain": query.get("domain", ""),
        "governed_bit_correct": governed_bit_correct,
        "grounding_correct": gcorr,
        "ruling_correct": rcorr if gov == "GOVERNED" and expected_ruling else None,
        "mis_governance_hit": mis_hit,
        "false_ungoverned": false_ungoverned,
        #: Either direction of being wrong on a governed pin. This is the number
        #: to quote: `mis_governance_hit` alone reads as a pass while the engine
        #: is silently declining to govern.
        "governed_pin_error": bool(mis_hit or false_ungoverned),
    }
