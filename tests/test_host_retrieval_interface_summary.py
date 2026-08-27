from __future__ import annotations

from benchmarks.host_retrieval.summarize_interface_ablation import _percentile


def test_percentile_uses_nearest_rank():
    assert _percentile([300, 100], 0.5) == 100
    assert _percentile([300, 100], 0.95) == 300
