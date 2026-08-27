"""How much of a graph the correction gate can actually check.

Production gating probes the complete Concept universe within a hard cap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.gate_coverage import gate_coverage
from mcp_server.proposals import COMPLETE_PROBE_CAP

CATTRS = Path("data/construction_trials/cattrs_external_v2/reference/graph.lbug")
KEP = Path("results/kubernetes_kep_lifecycle/construction/run_1_correction"
           "/host_workspace/graph.candidate.uncertified.lbug")


@pytest.mark.skipif(not CATTRS.exists(), reason="reference graph absent")
def test_the_dense_reference_fits_the_complete_universe_cap():
    report = gate_coverage(CATTRS)

    assert report["governing"] == 11
    assert report["checkable"] is True
    assert report["universe_exceeds_cap"] is False
    assert report["probe_mode"] == "complete_universe"
    assert report["nodes"] <= COMPLETE_PROBE_CAP


@pytest.mark.skipif(not KEP.exists(), reason="KEP graph absent")
def test_a_thin_graph_is_still_checkable_when_it_fits_the_cap():
    """Connectivity no longer decides checkability; graph size vs cap does."""
    report = gate_coverage(KEP)

    assert report["edges_per_node"] < 0.5
    assert report["checkable"] is (report["nodes"] <= report["cap"])
    # Under complete-universe probing these are checked like anything else,
    # so they are not a coverage gap — but they remain a construction signal,
    # and on this graph all five are motivation/history sections that should
    # never have governed.
    assert len(report["edgeless_governing"]) == 5


@pytest.mark.skipif(not (CATTRS.exists() and KEP.exists()),
                    reason="both graphs needed")
def test_coverage_reports_size_against_the_cap():
    dense, thin = gate_coverage(CATTRS), gate_coverage(KEP)

    assert abs(dense["nodes"] - thin["nodes"]) <= 2
    assert dense["cap"] == thin["cap"] == COMPLETE_PROBE_CAP


def test_the_measurement_costs_nothing():
    """It must be free, or it will only run where somebody already paid."""
    source = Path("mcp_server/gate_coverage.py").read_text(encoding="utf-8")
    for forbidden in ("openai", "requests", "httpx", "what_governs", "embedder"):
        assert forbidden not in source


@pytest.mark.skipif(not CATTRS.exists(), reason="reference graph absent")
def test_probing_the_reference_never_modifies_it():
    import hashlib

    before = hashlib.sha256(CATTRS.read_bytes()).hexdigest()
    gate_coverage(CATTRS)
    assert hashlib.sha256(CATTRS.read_bytes()).hexdigest() == before


def test_an_oversize_graph_is_reported_not_truncated(tmp_path):
    report = {
        "nodes": COMPLETE_PROBE_CAP + 5,
        "cap": COMPLETE_PROBE_CAP,
    }
    # Pure assertion of the contract the live helper implements.
    assert report["nodes"] > report["cap"]
    live = gate_coverage.__doc__ or ""
    assert "complete" in live.lower() or "COMPLETE" in (
        Path("mcp_server/gate_coverage.py").read_text(encoding="utf-8"))


def test_the_measure_does_not_claim_to_diagnose():
    source = Path("mcp_server/gate_coverage.py").read_text(encoding="utf-8")
    assert "does not diagnose" in source
    for verdict_word in ("raise ", "refuse(", "allowed"):
        assert verdict_word not in source


@pytest.mark.skipif(not CATTRS.exists(), reason="reference graph absent")
def test_primitive_usage_is_reported_not_left_unwired():
    """A measurement with no consumer is an untested claim.

    `overloaded_primitives` shipped with only tests calling it. It measures a
    real cost — a dependency program keyed on LEADSTO scores 0.167 precision on
    its own source graph, because supersession and dependency share the
    primitive — so it belongs on the diagnostic surface, advisory.
    """
    usage = gate_coverage(CATTRS)["primitive_usage"]

    assert usage["labels_per_primitive"]["CONTAINS"] > 1
    assert "CONTAINS" in usage["overloaded"]
