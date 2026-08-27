import shutil
import tempfile
from pathlib import Path

import pytest

from benchmarks.external.credential_governance.host_transfer_v1 import ARMS, POLICIES
from benchmarks.external.pulse_software.host_transfer_v1 import (
    _compatibility_gate,
    _load_frozen,
    _load_task_binding,
    prerequisites_present,
)


def test_pulse_binding_covers_seven_cases_and_three_arms():
    frozen = _load_task_binding()

    assert len(frozen["cases"]) == 7
    assert tuple(frozen["selection"]["context_policies"]) == POLICIES
    assert tuple(frozen["adjudication"]["arms"]) == ARMS


def test_pulse_binding_covers_multi_policy_and_full_closure_cases():
    frozen = _load_task_binding()

    assert sum(len(case["required_applying_policy_ids"]) > 1 for case in frozen["cases"]) == 3
    assert sum(case["closure_mode"] == "full_graph" for case in frozen["cases"]) == 2
    assert "http_delivery_outcome_policy" in {
        node_id for case in frozen["cases"] for node_id in case["required_candidate_ids"]
    }


def test_pulse_frozen_substrate_passes_deterministic_compatibility_gate():
    # The substrate is a graph and an application checkout at absolute paths
    # outside this repository. Elsewhere the honest outcome is a skip naming
    # what is absent; failing would report a portability fact as a regression
    # in what the benchmark measures.
    missing = prerequisites_present()
    if missing:
        pytest.skip(missing)

    frozen = _load_frozen()

    with tempfile.TemporaryDirectory(prefix="pulse-transfer-test-") as room:
        copied = Path(room) / "pulse_webhooks.lbug"
        shutil.copy2(Path(frozen["provenance"]["graph_path"]), copied)
        report = _compatibility_gate(copied, frozen)

    assert report["passed"] is True
    assert len(report["checks"]) == 13
