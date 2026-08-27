from benchmarks.external.cattrs_software.scoped_adjudication_reliability_v1 import (
    ARMS,
    _case_catalog,
    _load_frozen,
    _promotion,
)


def test_reliability_binding_has_seven_direction_specific_cases():
    frozen, _, cases, _ = _load_frozen()

    assert len(cases) == 7
    assert frozen["repetitions"] == 3
    assert tuple(frozen["arms"]) == ARMS
    assert "selected:new-plistlib-backend" not in cases


def test_wire_case_uses_corrected_ungoverned_oracle():
    wire = _case_catalog()["plist-direction:serialize-tuple-wire"]

    assert wire["required_applying_policy_ids"] == []
    assert wire["expected_selected_ruling"] == "UNGOVERNED"
    assert wire["expected_coverage"] == "UNGOVERNED"
    assert "decision_current_serializer_behavior_lives_in_preconf" in wire["forbidden_authority_ids"]


def test_controls_are_first_and_remaining_orders_are_permutations():
    frozen, _, _, _ = _load_frozen()
    controls = frozen["control_task_ids"]
    remaining = frozen["remaining_task_orders"]

    assert controls == [
        "selected:per-class-strict-keys-no-closure",
        "selected:async-candidate-only",
    ]
    assert all(set(order) == set(remaining[0]) for order in remaining)
    assert not set(controls) & set(remaining[0])


def test_promotion_ignores_raw_but_requires_complete_guarded_and_server():
    frozen, _, _, _ = _load_frozen()
    good = {
        "rows": 21,
        "passed": 21,
        "cardinal_failures": 0,
        "engine_degradations": 0,
    }
    summary = {
        "host_owned_segmented": {**good, "passed": 0},
        "host_guarded_segmented": dict(good),
        "server_owned": dict(good),
    }

    assert _promotion(summary, frozen)["passed"] is True
    summary["server_owned"]["engine_degradations"] = 1
    assert _promotion(summary, frozen) == {
        "passed": False,
        "failures": ["server_owned:engine_degradation"],
    }
