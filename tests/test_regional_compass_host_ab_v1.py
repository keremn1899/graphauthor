from __future__ import annotations

from benchmarks.host_retrieval.regional_compass_host_ab_v1 import (
    _controls_advance,
    _load_cases,
    _score,
)


def test_frozen_regional_host_ab_binds_fifteen_cases():
    cases = _load_cases()
    assert len(cases) == 15
    assert sum(case["graph"] == "cattrs" for case in cases) == 8
    assert sum(case["graph"] == "pulse" for case in cases) == 7
    assert sum(case["task_id"] == "gap:async-hook-contract" and case["exact_gap"] for case in cases) == 1


def test_score_requires_grounded_complete_selection_and_preserves_gap():
    case = {
        "required_ids": ["a", "b"],
        "forbidden_ids": ["old"],
        "exact_gap": False,
    }
    passed = _score(case, {"evidence_node_ids": ["a", "b"]}, {"a", "b"})
    assert passed["passed"] is True
    failed = _score(case, {"evidence_node_ids": ["a", "old", "invented"]}, {"a", "old"})
    assert set(failed["failures"]) == {"missing_required", "forbidden_selected", "ungrounded_selected"}

    gap = {"required_ids": [], "forbidden_ids": [], "exact_gap": True}
    assert _score(gap, {"evidence_node_ids": []}, set())["passed"] is True
    assert _score(gap, {"evidence_node_ids": ["x"]}, {"x"})["exact_gap_ok"] is False


def test_control_gate_is_asymmetric_and_requires_regional_recall():
    def row(arm: str, passed: bool = True, selected: int = 1):
        return {
            "arm": arm,
            "score": {
                "passed": passed,
                "required_selected": selected,
                "forbidden_selected_ids": [],
                "ungrounded_selected_ids": [],
                "exact_gap_ok": True,
            },
            "telemetry": {"invalid_calls": 0},
        }

    rows = [row("bare") for _ in range(6)] + [row("global") for _ in range(6)] + [row("regional") for _ in range(6)]
    assert _controls_advance(rows) == (True, [])
    rows[-1]["score"]["required_selected"] = 0
    assert _controls_advance(rows)[0] is False


def test_frozen_graphs_have_distinct_identity_sentinels():
    from pathlib import Path
    import shutil
    import tempfile

    from benchmarks.host_retrieval.regional_compass_host_ab_v1 import (
        CATTRS_GRAPH,
        PULSE_GRAPH,
    )
    from mcp_server.host_retrieval import HostRetrievalSurface
    from mcp_server.surface import Surface

    with tempfile.TemporaryDirectory(prefix="regional-ab-identity-") as room:
        for source, present, absent in (
            (CATTRS_GRAPH, "cattrs_architecture", "pulse_system"),
            (PULSE_GRAPH, "pulse_system", "cattrs_architecture"),
        ):
            copied = Path(room) / (present + ".lbug")
            shutil.copy2(source, copied)
            surface = Surface(copied, store_path=Path(room) / (present + ".sqlite"))
            try:
                host = HostRetrievalSurface(surface)
                assert host.lookup([present])["outcome"] == "FOUND"
                assert host.lookup([absent])["outcome"] == "EXACT_MISS"
            finally:
                surface.close()
