from __future__ import annotations

from benchmarks.proposal_host.post_publication_reader_v1 import preflight


def test_post_publication_reader_preflight_is_zero_model_and_exact(tmp_path):
    report = preflight(tmp_path / "reader")

    assert report["overall"] == "PASS"
    assert report["model_calls"] == 0
    assert report["reference_node_count"] == 24
    assert report["published_node_count"] == 25
    assert all(report["checks"].values())
