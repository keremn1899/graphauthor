"""Unit tests for mis-governance ruling rubric (no API)."""

from __future__ import annotations

from mis_governance_rubric import grounding_correct, ruling_correct, score_mis_governance


def test_ruling_allow_detected():
    q = {"expected_ruling": "ALLOW", "ruling_allow_signals": [r"may return"]}
    ans = '```json\n{"governance_verdict": "GOVERNED"}\n```\n**Answer:** You may return the item within 30 days.'
    assert ruling_correct(ans, "ALLOW", q)


def test_ruling_deny_detected():
    q = {"expected_ruling": "DENY", "ruling_deny_signals": [r"cannot return"]}
    ans = "**Answer:** Opened DVDs cannot be returned for change of mind."
    assert ruling_correct(ans, "DENY", q)


def test_ruling_exchange_only():
    q = {
        "expected_ruling": "EXCHANGE_ONLY",
        "ruling_exchange_signals": [r"exchange"],
        "ruling_deny_signals": [r"no refund"],
    }
    ans = "**Answer:** You may exchange the toothbrush but no refund to your card is available."
    assert ruling_correct(ans, "EXCHANGE_ONLY", q)


def test_mis_governance_hit_when_grounded_but_wrong_ruling():
    q = {
        "expected": "GOVERNED",
        "expected_governance": "GOVERNED",
        "expected_ruling": "ALLOW",
        "required_policies": ["t01_base_change_of_mind"],
        "ruling_allow_signals": [r"may return"],
    }
    rec = {
        "governance_verdict": "GOVERNED",
        "node_labels": ["t01_base_change_of_mind"],
        "final_answer": "**Answer:** Seasonal items cannot be returned.",
    }
    scored = score_mis_governance(rec, q)
    assert scored["grounding_correct"]
    assert scored["mis_governance_hit"]


def test_false_ungoverned_is_counted_as_governed_pin_error():
    query = {
        "expected_governance": "GOVERNED",
        "expected_ruling": "ALLOW",
        "required_policies": ["t01_base_change_of_mind"],
        "ruling_allow_signals": [r"may return"],
    }
    record = {
        "governance_verdict": "UNGOVERNED",
        "node_labels": ["t01_base_change_of_mind"],
        "final_answer": "No policy names seasonal items as a category.",
    }

    scored = score_mis_governance(record, query)

    assert scored["grounding_correct"] is True
    assert scored["false_ungoverned"] is True
    assert scored["governed_pin_error"] is True
    assert scored["mis_governance_hit"] is False
    assert scored["ruling_correct"] is None


def test_expected_ungoverned_is_not_silent_permission():
    query = {
        "expected_governance": "UNGOVERNED",
        "expected_ruling": "",
    }
    record = {
        "governance_verdict": "UNGOVERNED",
        "node_labels": [],
        "final_answer": "No admitted policy governs this predicate.",
    }

    scored = score_mis_governance(record, query)

    assert scored["false_ungoverned"] is False
    assert scored["governed_pin_error"] is False


def test_ruling_deny_rejects_allow_headline_with_background_deny():
    q = {"expected_ruling": "DENY", "ruling_deny_signals": [r"not accepted"]}
    ans = (
        "**Answer:** Yes, you can exchange your toothbrush.\n\n"
        "**Provenance:**\n- T13 notes change-of-mind returns are not accepted on hygiene items."
    )
    assert not ruling_correct(ans, "DENY", q)


def test_grounding_on_policy_id():
    rec = {"node_labels": ["t09_chilled_frozen_instore"], "final_answer": ""}
    assert grounding_correct(rec, policy_ids=["t09_chilled_frozen_instore"])
