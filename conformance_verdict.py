"""Structured conformance verdict — typed ruling for agents and dogfood harness.

Maps engine state (governance bit + ruling + closure) to a single
``ConformanceVerdict`` with four outcomes. Preserves the load-bearing
INSUFFICIENT_EVIDENCE vs UNGOVERNED distinction from the closure property.

Handoff: design [new]/structured-verdict-dogfood-harness-handoff.md §A
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from mis_governance_rubric import _ALLOW_RE, _DENY_RE, answer_body, ruling_correct


class ConformanceKind(str, Enum):
    CONFORMS = "CONFORMS"
    VIOLATES = "VIOLATES"
    UNGOVERNED = "UNGOVERNED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ConformanceVerdict(BaseModel):
    """Agent-consumable conformance judgment — not prose."""

    verdict: ConformanceKind
    rule: str | None = None
    predicate: str | None = None
    grounding: str = ""
    confidence_note: str = ""

    governance_status: str = ""
    decision_predicate: str = ""
    applying_policy_ids: list[str] = Field(default_factory=list)
    evidence_node_ids: list[str] = Field(default_factory=list)
    authority_binding: str = ""
    unsupported_presuppositions: list[str] = Field(default_factory=list)
    unresolved_predicates: list[str] = Field(default_factory=list)
    governed_ruling: str = ""
    disposition: str = ""
    owner_decision_required: bool = False
    engine_verdict: str = ""
    planner_route: str = ""
    ruling_inferred: str = ""
    engine_degraded: bool = False
    degradation_flags: list[str] = Field(default_factory=list)
    gov_header_debug: str = ""


    def to_agent_block(self) -> str:
        head = f"CONFORMANCE: {self.verdict.value}"
        if self.rule:
            head += f"\nRULE: {self.rule}"
        if self.predicate:
            head += f"\nPREDICATE: {self.predicate}"
        if self.owner_decision_required:
            head += "\nDISPOSITION: OWNER_DECISION_REQUIRED"
        if self.unresolved_predicates:
            head += "\nUNRESOLVED: " + "; ".join(self.unresolved_predicates)
        body = self.grounding or "(no grounding)"
        if self.confidence_note:
            body += f"\n\n[{self.confidence_note}]"
        return f"{head}\n\n{body}"


_GOVERNING_APPENDIX_MARKER = "**Governing constraints (verbatim graph anchors):**"


def _bounded_grounding(answer: str, limit: int = 2000) -> str:
    """Bound synthesis prose without discarding its deterministic authority tail."""
    if len(answer) <= limit:
        return answer
    marker_at = answer.rfind(_GOVERNING_APPENDIX_MARKER)
    if marker_at < 0:
        return answer[:limit]
    appendix = answer[marker_at:].strip()
    if len(appendix) >= limit:
        # Applying authority is the SSOT payload.  In the unusual case where
        # that payload alone exceeds the prose budget, preserve it losslessly
        # instead of manufacturing a compact but incomplete ruling.
        return appendix
    separator = "\n\n"
    prefix_limit = limit - len(separator) - len(appendix)
    return f"{answer[:prefix_limit].rstrip()}{separator}{appendix}"


def _first_rule_label(node_labels: list[str], policy_ids: list[str] | None = None) -> str | None:
    labels = [str(x) for x in node_labels if x]
    for pid in policy_ids or []:
        for lab in labels:
            if pid.lower() in lab.lower():
                return lab
    for lab in labels:
        if "rule" in lab.lower():
            return lab
    return labels[0] if labels else None


def infer_ruling(
    answer: str,
    *,
    allow_signals: list[str] | None = None,
    deny_signals: list[str] | None = None,
) -> str:
    """Infer ALLOW | DENY | UNKNOWN from Battalion prose (compute-not-parse fallback)."""
    body = answer_body(answer)
    if not body:
        return "UNKNOWN"
    if re.match(r"^yes\b", body.strip(), re.I):
        return "ALLOW"
    if re.match(r"^no\b", body.strip(), re.I):
        return "DENY"
    allow_hints = allow_signals or []
    deny_hints = deny_signals or []
    has_allow = bool(_ALLOW_RE.search(body)) or any(re.search(p, body, re.I) for p in allow_hints)
    has_deny = bool(_DENY_RE.search(body)) or any(re.search(p, body, re.I) for p in deny_hints)
    if has_allow and not has_deny:
        return "ALLOW"
    if has_deny and not has_allow:
        return "DENY"
    if has_deny and has_allow:
        return "UNKNOWN"
    if has_allow:
        return "ALLOW"
    if has_deny:
        return "DENY"
    return "UNKNOWN"


def _governance_from_state(state: dict) -> tuple[str, dict]:
    conf = state.get("confirmation_response") or {}
    if hasattr(conf, "model_dump"):
        conf = conf.model_dump()
    gov = str(conf.get("governance_verdict") or "").strip().upper()
    verdict = str(conf.get("verdict") or "").strip().upper()
    if gov not in ("GOVERNED", "PARTIALLY_GOVERNED", "UNGOVERNED"):
        if verdict == "ILL_POSED" and conf.get("ungoverned_predicate"):
            gov = "UNGOVERNED"
        elif gov in ("", "ABSENT", "?"):
            if verdict in ("ILL_POSED", "UNKNOWN_TO_GRAPH"):
                gov = "ABSENT"
            elif state.get("engine_verdict") == "TIMEOUT":
                gov = "ABSENT"
            else:
                gov = "ABSENT"
    return gov, conf


def from_engine_state(
    state: dict[str, Any],
    *,
    question: str = "",
    policy_ids: list[str] | None = None,
    allow_signals: list[str] | None = None,
    deny_signals: list[str] | None = None,
) -> ConformanceVerdict:
    """Map a final EngineState dict to a ConformanceVerdict (closure preserved)."""
    from sst_degradation import has_engine_fault

    deg = [str(x) for x in (state.get("degradation_flags") or []) if x]
    degraded = has_engine_fault(deg)
    raw_conf = state.get("confirmation_response") or {}
    if hasattr(raw_conf, "model_dump"):
        raw_conf = raw_conf.model_dump()
    pkt = state.get("evidence_packet") or {}
    if hasattr(pkt, "model_dump"):
        pkt = pkt.model_dump()
    nodes = pkt.get("node_records") or []
    evidence_node_ids = list(dict.fromkeys(
        str(node.get("id") or "").strip()
        for node in nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    ))
    applying_policy_ids: list[str] = []
    for item in raw_conf.get("adjudications") or []:
        if not isinstance(item, dict):
            continue
        policy_id = str(item.get("policy_id") or "").strip()
        if policy_id and policy_id not in applying_policy_ids:
            applying_policy_ids.append(policy_id)

    def _attach(cv: ConformanceVerdict) -> ConformanceVerdict:
        return cv.model_copy(
            update={"degradation_flags": list(deg), "engine_degraded": degraded,
                    "gov_header_debug": str(state.get("gov_header_debug") or ""),
                    "decision_predicate": str(raw_conf.get("decision_predicate") or ""),
                    "applying_policy_ids": applying_policy_ids,
                    "evidence_node_ids": evidence_node_ids,
                    "authority_binding": str(raw_conf.get("authority_binding") or ""),
                    "unsupported_presuppositions": [
                        str(value)
                        for value in raw_conf.get("unsupported_presuppositions") or []
                        if str(value).strip()
                    ],
                    "unresolved_predicates": [
                        str(value)
                        for value in raw_conf.get("unresolved_predicates") or []
                        if str(value).strip()
                    ]}
        )

    if state.get("engine_verdict") == "TIMEOUT":
        return _attach(ConformanceVerdict(
            verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
            grounding="Engine query timed out before a governance judgment.",
            confidence_note="timeout",
            governance_status="ABSENT",
            engine_verdict="TIMEOUT",
        ))

    gov, conf = _governance_from_state(state)
    answer = str(state.get("final_answer") or "")
    node_labels = [str(n.get("label") or n.get("id") or "") for n in nodes if isinstance(n, dict)]
    empty_packet = len(nodes) == 0
    planner_route = str(state.get("planner_route") or "")
    engine_verdict = str(conf.get("verdict") or state.get("engine_verdict") or "")
    predicate = str(conf.get("ungoverned_predicate") or "").strip() or None
    tier_note = str(conf.get("governance_verdict_source") or "")
    structured_ruling = str(conf.get("conformance_ruling") or "").strip().upper()

    rule_label = _first_rule_label(node_labels, policy_ids)

    if gov == "UNGOVERNED":
        unresolved = [
            str(value)
            for value in raw_conf.get("unresolved_predicates") or []
            if str(value).strip()
        ]
        return _attach(ConformanceVerdict(
            verdict=ConformanceKind.UNGOVERNED,
            predicate=predicate,
            grounding=_bounded_grounding(answer) or f"No handbook rule governs: {predicate or 'unspecified predicate'}",
            confidence_note=tier_note or "",
            governance_status="UNGOVERNED",
            disposition="OWNER_DECISION_REQUIRED" if unresolved else "",
            owner_decision_required=bool(unresolved),
            engine_verdict=engine_verdict,
            planner_route=planner_route,
        ))

    if gov == "PARTIALLY_GOVERNED":
        governed_ruling = (
            structured_ruling
            if structured_ruling in ("CONFORMS", "VIOLATES")
            else ""
        )
        kind = (
            ConformanceKind.VIOLATES
            if governed_ruling == "VIOLATES"
            else ConformanceKind.INSUFFICIENT_EVIDENCE
        )
        return _attach(ConformanceVerdict(
            verdict=kind,
            rule=rule_label,
            predicate=predicate,
            grounding=_bounded_grounding(answer),
            confidence_note=(
                tier_note
                or "encoded policy governs only part of the requested decision"
            ),
            governance_status="PARTIALLY_GOVERNED",
            engine_verdict=engine_verdict,
            planner_route=planner_route,
            ruling_inferred=governed_ruling,
            governed_ruling=governed_ruling,
            disposition="OWNER_DECISION_REQUIRED",
            owner_decision_required=True,
        ))

    if gov != "GOVERNED":
        reason = "empty evidence packet" if empty_packet else f"could not ground ({engine_verdict or gov})"
        return _attach(ConformanceVerdict(
            verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
            grounding=_bounded_grounding(answer) or reason,
            confidence_note=tier_note or reason,
            governance_status=gov or "ABSENT",
            engine_verdict=engine_verdict,
            planner_route=planner_route,
        ))

    if gov == "GOVERNED" and structured_ruling in ("CONFORMS", "VIOLATES"):
        kind = (
            ConformanceKind.CONFORMS
            if structured_ruling == "CONFORMS"
            else ConformanceKind.VIOLATES
        )
        return _attach(ConformanceVerdict(
            verdict=kind,
            rule=rule_label,
            grounding=_bounded_grounding(answer),
            confidence_note=tier_note or "battalion_structured_ruling",
            governance_status="GOVERNED",
            engine_verdict=engine_verdict,
            planner_route=planner_route,
            ruling_inferred=structured_ruling,
            governed_ruling=structured_ruling,
            disposition=(
                "NONE" if structured_ruling == "CONFORMS" else "REVISE"
            ),
        ))

    ruling = infer_ruling(answer, allow_signals=allow_signals, deny_signals=deny_signals)
    if ruling == "UNKNOWN":
        return _attach(ConformanceVerdict(
            verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
            rule=rule_label,
            grounding=_bounded_grounding(answer),
            confidence_note="governed but ruling not inferable from answer",
            governance_status="GOVERNED",
            engine_verdict=engine_verdict,
            planner_route=planner_route,
            ruling_inferred=ruling,
        ))

    kind = ConformanceKind.CONFORMS if ruling == "ALLOW" else ConformanceKind.VIOLATES
    return _attach(ConformanceVerdict(
        verdict=kind,
        rule=rule_label,
        grounding=_bounded_grounding(answer),
        confidence_note=tier_note or "",
        governance_status="GOVERNED",
        engine_verdict=engine_verdict,
        planner_route=planner_route,
        ruling_inferred=ruling,
        governed_ruling=("CONFORMS" if ruling == "ALLOW" else "VIOLATES"),
        disposition=("NONE" if ruling == "ALLOW" else "REVISE"),
    ))


def expected_conformance_from_query(query: dict) -> ConformanceKind | None:
    """Derive expected ConformanceKind from mis-governance / probe pin metadata."""
    exp_gov = str(query.get("expected_governance") or query.get("expected") or "").upper()
    exp_ruling = str(query.get("expected_ruling") or "").upper()
    if exp_gov == "UNGOVERNED":
        return ConformanceKind.UNGOVERNED
    if exp_gov == "GOVERNED" and exp_ruling == "ALLOW":
        return ConformanceKind.CONFORMS
    if exp_gov == "GOVERNED" and exp_ruling in ("DENY", "EXCHANGE_ONLY"):
        return ConformanceKind.VIOLATES
    return None


def conformance_matches_query(cv: ConformanceVerdict, query: dict) -> bool | None:
    """True/False when query carries expected axes; None when not comparable."""
    expected = expected_conformance_from_query(query)
    if expected is None:
        return None
    return cv.verdict == expected


def conformance_matches_mis_governance_rec(rec: dict, query: dict) -> bool | None:
    """Cross-check structured verdict against prose-scored mis_governance record."""
    state_like = {
        "confirmation_response": {
            "governance_verdict": rec.get("governance_verdict"),
            "ungoverned_predicate": rec.get("ungoverned_predicate"),
            "verdict": rec.get("verdict"),
            "governance_verdict_source": rec.get("governance_verdict_source"),
        },
        "final_answer": rec.get("final_answer"),
        "evidence_packet": {"node_records": [{"label": l} for l in rec.get("node_labels") or []]},
        "planner_route": rec.get("planner_route"),
    }
    cv = from_engine_state(
        state_like,
        policy_ids=list(query.get("required_policies") or query.get("grounding_policy_ids") or []),
        allow_signals=list(query.get("ruling_allow_signals") or []),
        deny_signals=list(query.get("ruling_deny_signals") or []),
    )
    expected = expected_conformance_from_query(query)
    if expected is None:
        return None
    if expected == ConformanceKind.VIOLATES and cv.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE:
        # Governed + deny expected but ruling not parsed — treat as regression
        return rec.get("ruling_correct") is True
    if expected == ConformanceKind.CONFORMS and cv.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE:
        return rec.get("ruling_correct") is True
    return cv.verdict == expected
