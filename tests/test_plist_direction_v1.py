from benchmarks.external.cattrs_software.plist_direction_v1 import _load_frozen,_selection

def test_direction_probe_has_opposite_tuple_expectations_on_same_packet():
    frozen,source=_load_frozen(); selection=_selection(frozen,source); structure,wire=frozen["cases"]
    tuple_id="decision_current_sequence_structures_to_tuple"
    assert len(selection["compiled"]["compiled_packet_ids"])==8
    assert tuple_id in structure["required_applying_policy_ids"]
    assert tuple_id in wire["forbidden_authority_ids"]
    assert structure["expected_selected_ruling"]=="CONFORMS"
    assert wire["expected_coverage"]=="PARTIALLY_GOVERNED"
