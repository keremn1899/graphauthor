from benchmarks.external.pulse_software.deterministic_enforcement_replay_v1 import run


def test_saved_pulse_controls_replay_through_deterministic_repairs(tmp_path):
    report = run(tmp_path)

    assert report["zero_model_calls"] is True
    assert report["zero_tool_calls"] is True
    assert report["summary"]["signing_guard_full_contract_passed"] is True
    assert report["summary"]["broker_guard_failures_preserved"] == ["required_context_missing"]
    assert report["summary"]["anchor_rows_passed"] == 7
    assert report["summary"]["passed"] is True
