from benchmarks.external.cattrs_software.plist_direction_v1_1 import _load,run
def test_corrected_wire_oracle_has_no_applying_authority(tmp_path):
    cases,_=_load(); wire=cases["plist-direction:serialize-tuple-wire"]
    assert wire["required_applying_policy_ids"]==[]
    assert wire["expected_selected_ruling"]=="UNGOVERNED"
    report=run(tmp_path)
    assert report["summary"]["host_guarded_segmented"]["passed"]==2
    assert report["summary"]["server_owned"]["passed"]==2
