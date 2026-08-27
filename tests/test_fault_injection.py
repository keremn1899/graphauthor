"""Fault injection tests for graceful degradation and fault labeling."""

from __future__ import annotations

import pytest

from reporting import classify_fault


def test_fault_category_timeout():
    case = {"error_type": "TimeoutError", "forbidden_violations": 0}
    assert classify_fault(case) == "timeout"


def test_fault_category_provider():
    case = {"error_type": "OpenRouterProviderError"}
    assert classify_fault(case) == "provider_failure"


def test_fault_category_abstention_failure():
    case = {"answerable": False, "gap_reported": False}
    assert classify_fault(case) == "abstention_failure"


def test_run_query_propagates_explicit_errors():
    from main import run_query

    class BrokenGraph:
        def invoke(self, state, config=None):  # noqa: ANN001
            raise TimeoutError("provider timed out")

    with pytest.raises(TimeoutError, match="timed out"):
        run_query(BrokenGraph(), "why timeout?", {}, {})




