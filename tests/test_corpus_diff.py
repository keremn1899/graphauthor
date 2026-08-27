"""Integration tests for `scripts/corpus_diff.py` using synthetic run dirs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.corpus_diff as diff
from scripts.corpus_diff import (
    _collect_run_snapshot,
    _write_diff_stage_a,
    _write_diff_stage_b,
    _write_new_cases,
    cmd_diff,
    cmd_promote,
)


def _make_case(
    run_root: Path,
    case_id: str,
    *,
    passed: bool,
    symptoms: list[str] | None = None,
    judge: dict | None = None,
    seed: str = "lotr",
    query_class: str = "enumeration",
) -> None:
    case_dir = run_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "stage_a.json").write_text(
        json.dumps(
            {
                "case_id": case_id,
                "passed": passed,
                "symptoms": symptoms or [],
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "meta.json").write_text(
        json.dumps({"seed": seed, "query_class": query_class}), encoding="utf-8"
    )
    if judge is not None:
        (case_dir / "judge.json").write_text(json.dumps(judge), encoding="utf-8")


def test_diff_writes_reports_when_no_baseline(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "run1"
    (run_root / "reports").mkdir(parents=True)
    _make_case(run_root, "case_a", passed=True)
    _make_case(run_root, "case_b", passed=False, symptoms=["verdict_mismatch"])
    monkeypatch.setattr(diff, "BASELINE_PATH", tmp_path / "baseline.json")

    code = cmd_diff(run_root, threshold=0.1)
    assert code == 0
    assert (run_root / "reports" / "new_cases.md").exists()


def test_promote_then_diff_detects_regression(tmp_path: Path, monkeypatch) -> None:
    baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(diff, "BASELINE_PATH", baseline_path)

    # First run — good state becomes baseline.
    run1 = tmp_path / "run1"
    (run1 / "reports").mkdir(parents=True)
    _make_case(
        run1,
        "case_a",
        passed=True,
        judge={"faithfulness": 0.9, "completeness": 0.9, "alignment": 0.9},
    )
    cmd_promote(run1)
    assert baseline_path.exists()

    # Second run — case_a regresses on Stage A, and judge alignment drops.
    run2 = tmp_path / "run2"
    (run2 / "reports").mkdir(parents=True)
    _make_case(
        run2,
        "case_a",
        passed=False,
        symptoms=["required_edge_type_missing"],
        judge={"faithfulness": 0.9, "completeness": 0.9, "alignment": 0.5},
    )
    _make_case(run2, "case_new", passed=True)
    code = cmd_diff(run2, threshold=0.1)
    assert code == 0

    stage_a = (run2 / "reports" / "diff_stage_a.md").read_text(encoding="utf-8")
    assert "Regressions" in stage_a
    assert "case_a" in stage_a

    stage_b = (run2 / "reports" / "diff_stage_b.md").read_text(encoding="utf-8")
    assert "alignment" in stage_b
    assert "-0.40" in stage_b  # delta = 0.5 - 0.9

    new_cases = (run2 / "reports" / "new_cases.md").read_text(encoding="utf-8")
    assert "case_new" in new_cases


def test_collect_run_snapshot_handles_missing_files(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    (run_root / "cases" / "case_x").mkdir(parents=True)
    snap = _collect_run_snapshot(run_root)
    assert "case_x" in snap
    assert snap["case_x"]["stage_a_passed"] is False
    assert snap["case_x"]["judge"] is None
