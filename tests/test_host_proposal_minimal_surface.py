"""Zero-model contract for the minimal host proposal surface."""

from __future__ import annotations

from benchmarks.proposal_host.minimal_write_audit import run


def test_preregistered_minimal_write_audit_passes() -> None:
    report = run()
    assert report["overall"] == "PASS", {
        case_id: case for case_id, case in report["cases"].items()
        if not case["pass"]
    }
    assert report["passed"] == report["total"] == 7
    assert report["model_calls"] == 0
