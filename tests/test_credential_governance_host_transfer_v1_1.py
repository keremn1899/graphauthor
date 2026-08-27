from benchmarks.external.credential_governance.host_transfer_v1_1 import _load_saved_replay


def test_v1_1_replay_advances_kernel_without_new_selection_calls():
    _, correction, source, corrected = _load_saved_replay()

    assert source["stopped_after"] == "selection"
    assert not source["adjudication_rows"]
    assert correction["corrected_context_policy"] == "kernel"
    assert len(corrected) == 7
    assert all(row["score"]["passed"] for row in corrected)


def test_v1_1_exception_is_only_length_truncated_final():
    _, correction, _, corrected = _load_saved_replay()
    target = next(row for row in corrected if row["task_id"] == correction["allowed_transport_exception"]["task_id"])

    assert target["original_score"]["failures"] == ["invalid_tool_call"]
    assert target["score"]["transport_exception"] == "length_truncated_final_recovered_next_turn"
    assert not target["score"]["missing_required_ids"]
    assert not target["score"]["validation_errors"]
