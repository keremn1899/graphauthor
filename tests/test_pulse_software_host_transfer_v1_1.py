from benchmarks.external.pulse_software.host_transfer_v1_1 import _load_saved_replay


def test_v1_1_replay_advances_kernel_without_new_calls():
    _, correction, source, corrected = _load_saved_replay()

    assert source["stopped_after"] == "selection"
    assert not source["adjudication_rows"]
    assert correction["corrected_context_policy"] == "kernel"
    assert len(corrected) == 7
    assert all(row["score"]["passed"] for row in corrected)


def test_v1_1_correction_removes_only_closure_supplied_system_context():
    _, correction, _, corrected = _load_saved_replay()
    task_id = correction["allowed_oracle_correction"]["task_id"]
    target = next(row for row in corrected if row["task_id"] == task_id)

    assert target["original_score"]["failures"] == ["missing_required_candidate"]
    assert target["original_score"]["missing_required_ids"] == ["pulse_system"]
    assert target["selected_candidate_ids"] == ["retry_ownership_rule"]
    assert target["score"]["oracle_correction"] == "closure_supplied_generic_context_not_selection_required"
    assert not target["score"]["failures"]
    assert not target["score"]["missing_required_ids"]
