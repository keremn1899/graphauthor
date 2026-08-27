from __future__ import annotations

from scripts.software_ssot_moat import (
    CREDENTIAL_CASES,
    ENGINE_PINS,
    RULE_ID,
    _score_report,
    score_implementation,
    score_proposal_encoding,
)


def _encoding(text: str) -> dict:
    return {
        "concepts": [{
            "id": RULE_ID,
            "label": "PaymentRetryRule",
            "text_content": text,
            "semantic_anchor": "payment retry policy",
        }],
        "edges": [{
            "type": "NEARTO",
            "source_id": RULE_ID,
            "target_id": "stripe_payment_adapter",
            "label": "governs adapter",
        }],
    }


def test_preregistered_pins_are_balanced_around_one_intentional_closure():
    expected = {key: value[1] for key, value in ENGINE_PINS.items()}
    assert expected == {
        "anchor_dependency_direction": "GOVERNED",
        "anchor_status_ownership": "GOVERNED",
        "target_payment_retry": "UNGOVERNED",
        "moat_webhook_idempotency": "UNGOVERNED",
        "moat_http_error_mapping": "UNGOVERNED",
    }


def test_credential_regression_has_both_verdict_and_action_directions():
    assert {case["engine_expected"] for case in CREDENTIAL_CASES} == {
        "GOVERNED", "UNGOVERNED"
    }
    assert {case["agent_expected"] for case in CREDENTIAL_CASES} == {
        "IMPLEMENT", "REFUSE", "ESCALATE"
    }


def test_proposal_score_requires_exact_atomic_decision_and_typed_join():
    good = _encoding(
        "ADJUDICATES: StripePaymentAdapter may retry at most three times with "
        "backoff 1s, 2s, 4s, then report permanent failure through PaymentPort; "
        "it must not swallow failure."
    )
    assert score_proposal_encoding(good) == []

    fused = _encoding("ADJUDICATES: use three retries.")
    fused["edges"][0]["target_id"] = "order_controller"
    failures = score_proposal_encoding(fused)
    assert any("PaymentPort" in failure or "paymentport" in failure for failure in failures)
    assert any("stripe_payment_adapter" in failure for failure in failures)


def test_implementation_score_is_semantic_not_prose_judged():
    good = {
        "action": "IMPLEMENT",
        "max_retries": 3,
        "backoff_seconds": [1, 2, 4],
        "terminal_failure": "Report permanent failure inward through PaymentPort",
        "swallow_failure": False,
    }
    assert score_implementation(good) == []
    assert score_implementation({**good, "max_retries": 4})
    assert score_implementation({**good, "swallow_failure": True})


def test_safe_gate_refusal_is_partial_not_an_unaccounted_mutation():
    report = {
        "baseline_rows": {
            pin_id: [{"governance_verdict": expected}] * 3
            for pin_id, (_, expected) in ENGINE_PINS.items()
        },
        "gap_agent_rows": [{"passed": True}] * 3,
        "authority": {
            "proposal_pending_before_confirm": True,
            "manifest_unchanged_before_confirm": True,
            "graph_restored_after_gate_failure": True,
        },
        "confirm": {"status": "GATE_FAILED"},
        "gate_capture": {
            "closure_rows": [{"governance_verdict": "GOVERNED"}] * 3,
            "post_rows": {
                pin_id: [{"governance_verdict": expected}] * 3
                for pin_id, (_, expected) in ENGINE_PINS.items()
                if pin_id != "target_payment_retry"
            },
        },
        "graph_implementation_rows": [],
        "credential_rows": [],
    }
    outcome, failures = _score_report(report, 3)
    assert outcome.startswith("SSOT_MOAT_PARTIAL:")
    assert "confirm status: GATE_FAILED" in failures
