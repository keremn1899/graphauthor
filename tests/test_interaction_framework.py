"""Deterministic interaction-framework unit tests (no LLM, no engine)."""

from interaction.escalation import EscalationLedger
from interaction.gap_policy import RefuseAndFlagPolicy, TescoEscalatePolicy
from interaction.models import GovernanceStatus, GovernanceVerdict, ResponseAction
from interaction.response_semantics import apply_response_semantics, structural_decision


def _verdict(status: GovernanceStatus, pred: str = "") -> GovernanceVerdict:
    return GovernanceVerdict(
        status=status,
        question="test?",
        ungoverned_predicate=pred,
        governance_verdict_source="battalion_synthesis",
    )


def test_governed_maps_to_act():
    rec = structural_decision(
        _verdict(GovernanceStatus.GOVERNED),
        decision_id="d1",
        order=1,
        label="x",
        gap_policy=TescoEscalatePolicy(),
    )
    assert rec.bound_action == ResponseAction.ACT
    assert not rec.confabulation


def test_ungoverned_escalates_under_tesco():
    rec = structural_decision(
        _verdict(GovernanceStatus.UNGOVERNED, "price match"),
        decision_id="d1",
        order=1,
        label="x",
        gap_policy=TescoEscalatePolicy(),
    )
    assert rec.bound_action == ResponseAction.ESCALATE
    assert "price match" in rec.resolution


def test_partially_governed_cannot_be_bound_to_act():
    verdict = _verdict(GovernanceStatus.PARTIALLY_GOVERNED)
    verdict.unresolved_predicates = ["exact wire semantics"]
    rec = apply_response_semantics(
        verdict,
        decision_id="d1",
        order=1,
        label="x",
        gap_policy=TescoEscalatePolicy(),
        agent_action=ResponseAction.ACT,
    )
    assert rec.bound_action == ResponseAction.ESCALATE
    assert rec.confabulation
    assert "exact wire semantics" in rec.resolution


def test_confabulation_detected():
    rec = apply_response_semantics(
        _verdict(GovernanceStatus.UNGOVERNED, "goodwill"),
        decision_id="d1",
        order=1,
        label="x",
        gap_policy=TescoEscalatePolicy(),
        agent_action=ResponseAction.ACT,
    )
    assert rec.confabulation


def test_policy_seam_swappable():
    v = _verdict(GovernanceStatus.UNGOVERNED, "redirect delivery")
    tesco = structural_decision(
        v, decision_id="d1", order=1, label="x", gap_policy=TescoEscalatePolicy(),
    )
    refuse = structural_decision(
        v, decision_id="d1", order=1, label="x", gap_policy=RefuseAndFlagPolicy(),
    )
    assert tesco.bound_action == ResponseAction.ESCALATE
    assert refuse.bound_action == ResponseAction.REFUSE


def test_escalation_ledger_typed_predicate():
    ledger = EscalationLedger()
    v = _verdict(GovernanceStatus.UNGOVERNED, "goodwill compensation")
    h = ledger.record(
        case_id="ST1",
        decision_id="ST1a",
        verdict=v,
        resolution="escalate",
    )
    assert h.ungoverned_predicate == "goodwill compensation"
    assert "goodwill compensation" in h.human_summary()
    assert ledger.all_have_typed_predicate()
