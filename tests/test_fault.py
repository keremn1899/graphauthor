"""Fault envelope: kind is the status, the sentence is the copy."""

from mcp_server.fault import (
    ensure_kind,
    is_fault_payload,
    kind_of,
    operator_fault,
    status_of,
)


def test_operator_fault_carries_kind_and_sentence():
    body = operator_fault("not_found", "unknown node", node_id="n1")
    assert body == {
        "kind": "not_found",
        "error": "unknown node",
        "node_id": "n1",
    }
    assert status_of(body) == 404


def test_job_record_with_null_error_is_not_a_fault():
    assert is_fault_payload({"job_id": "j1", "error": None}) is False
    assert is_fault_payload({"error": ""}) is False
    assert is_fault_payload("nope") is False


def test_missing_kind_unknown_prefix_is_not_found():
    assert kind_of({"error": "unknown incident: x"}) == "not_found"
    assert status_of({"error": "unknown incident: x"}) == 404


def test_missing_kind_otherwise_is_invalid():
    assert kind_of({"error": "source is empty"}) == "invalid"
    assert status_of({"error": "source is empty"}) == 400


def test_ensure_kind_does_not_rewrite_a_declared_kind():
    body = ensure_kind(operator_fault("conflict", "already acknowledged"))
    assert body["kind"] == "conflict"
    assert status_of(body) == 409


def test_json_result_uses_kind_for_status():
    import json

    import pytest

    pytest.importorskip("starlette")
    from mcp_server.fault import json_result

    fault = json_result(operator_fault("unavailable", "store down"))
    assert fault.status_code == 503
    assert json.loads(fault.body.decode())["kind"] == "unavailable"
    assert json_result({"ready": True}).status_code == 200
    assert json_result({"job_id": "j"}, ok=202).status_code == 202
