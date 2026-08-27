"""Packaging tests for ``graphauthor gate`` / ``mcp_server.pr_gate_cli`` (zero LLM)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.pr_gate_cli import (
    ATTRIBUTION_CAVEAT,
    EXIT_FAIL,
    EXIT_PASS,
    EXIT_UNTRUSTED,
    EXIT_USAGE,
    enrich_report,
    exit_code_for_result,
    load_diff_text,
    main as gate_main,
    run_stub_gate,
)

ROOT = Path(__file__).resolve().parent.parent

VIOL_DIFF = """diff --git a/src/api/x.py b/src/api/x.py
--- a/src/api/x.py
+++ b/src/api/x.py
@@ -1 +1,2 @@
 a
+b
"""

README_DIFF = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 t
+u
"""

MIXED_DIFF = """diff --git a/src/api/handler.py b/src/api/handler.py
--- a/src/api/handler.py
+++ b/src/api/handler.py
@@ -1 +1,2 @@
 x
+y
diff --git a/src/db/model.py b/src/db/model.py
--- a/src/db/model.py
+++ b/src/db/model.py
@@ -1 +1,2 @@
 x
+y
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 t
+u
"""


def _stub(**overrides):
    base = {
        "rules": ["api_rule", "db_rule"],
        "graph_version": "gv_test",
        "applicability": {
            "api_rule": ["src/api/"],
            "db_rule": ["src/db/"],
        },
        "verdicts": {},
    }
    base.update(overrides)
    return base


def test_exit_code_fail_pass_untrusted():
    assert exit_code_for_result({"verdict": "FAIL", "trusted": True}) == EXIT_FAIL
    assert exit_code_for_result({"verdict": "PASS", "trusted": True}) == EXIT_PASS
    assert exit_code_for_result({"verdict": "PASS", "trusted": False}) == EXIT_PASS
    assert (
        exit_code_for_result({"verdict": "PASS", "trusted": False}, fail_untrusted=True)
        == EXIT_UNTRUSTED
    )


def test_enrich_report_carries_attribution_caveat():
    report = enrich_report({"verdict": "PASS", "trusted": True})
    assert report["packaging"]["fail_policy"] == "VIOLATES_only"
    assert "provisional" in report["packaging"]["attribution_caveat"]
    assert ATTRIBUTION_CAVEAT in report["packaging"]["attribution_caveat"]


def test_stub_ungoverned_only_passes(tmp_path: Path):
    stub = _stub()
    result = run_stub_gate(README_DIFF, stub)
    assert result["verdict"] == "PASS"
    assert result["blocking"] == []
    assert len(result["gaps"]) == 1
    assert result["gaps"][0]["artifact_path"] == "README.md"
    assert exit_code_for_result(result) == EXIT_PASS


def test_stub_violates_fails(tmp_path: Path):
    stub = _stub(verdicts={"api_rule|src/api/x.py": "VIOLATES"})
    result = run_stub_gate(VIOL_DIFF, stub)
    assert result["verdict"] == "FAIL"
    assert len(result["blocking"]) == 1
    assert exit_code_for_result(result) == EXIT_FAIL


def test_stub_insufficient_and_conforms_pass():
    stub = _stub(
        verdicts={
            "api_rule|src/api/handler.py": "INSUFFICIENT_EVIDENCE",
            "db_rule|src/db/model.py": "CONFORMS",
        }
    )
    result = run_stub_gate(MIXED_DIFF, stub)
    assert result["verdict"] == "PASS"
    assert len(result["needs_attention"]) == 1
    assert len(result["conforming"]) == 1
    assert any(g.get("artifact_path") == "README.md" for g in result["gaps"])


def test_cli_stub_writes_report_and_exit_codes(tmp_path: Path):
    diff_path = tmp_path / "pr.diff"
    stub_path = tmp_path / "stub.json"
    out_path = tmp_path / "report.json"
    diff_path.write_text(VIOL_DIFF, encoding="utf-8")
    stub_path.write_text(
        json.dumps(_stub(verdicts={"api_rule|src/api/x.py": "VIOLATES"})),
        encoding="utf-8",
    )

    code = gate_main(
        ["--diff-file", str(diff_path), "--stub", str(stub_path),
         "--out", str(out_path), "--quiet"]
    )
    assert code == EXIT_FAIL
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "FAIL"
    assert report["packaging"]["fail_policy"] == "VIOLATES_only"
    assert report["receipts"]
    assert all(r["graph_version"] == "gv_test" for r in report["receipts"])

    stub_path.write_text(json.dumps(_stub()), encoding="utf-8")
    diff_path.write_text(README_DIFF, encoding="utf-8")
    code = gate_main(
        ["--diff-file", str(diff_path), "--stub", str(stub_path),
         "--out", str(out_path), "--quiet"]
    )
    assert code == EXIT_PASS


def test_cli_usage_without_diff():
    assert gate_main([]) == EXIT_USAGE


def test_cli_fail_untrusted(tmp_path: Path):
    from mcp_server.pr_gate import run_pr_gate

    viol = VIOL_DIFF
    rules = ["api_rule"]
    prior = run_pr_gate(
        viol, rules,
        conformance_fn=lambda r, a, p: "VIOLATES",
        applicability_fn=lambda r, p: p.startswith("src/api/"),
        graph_version="gA",
    )
    stub = _stub(
        rules=["api_rule"],
        applicability={"api_rule": ["src/api/"]},
        verdicts={"api_rule|src/api/x.py": "CONFORMS"},
        graph_version="gB",
    )
    # Direct library path with prior receipts
    result = run_stub_gate(viol, stub)  # no prior → trusted
    assert result["trusted"] is True

    from mcp_server.pr_gate import run_pr_gate as rpg

    flagged = rpg(
        viol, ["api_rule"],
        conformance_fn=lambda r, a, p: "CONFORMS",
        applicability_fn=lambda r, p: True,
        graph_version="gB",
        prior_receipts=prior["receipts"],
    )
    assert flagged["verdict"] == "PASS"
    assert flagged["trusted"] is False
    assert exit_code_for_result(flagged, fail_untrusted=True) == EXIT_UNTRUSTED


def test_cke_gate_dispatch_subprocess(tmp_path: Path):
    diff_path = tmp_path / "pr.diff"
    stub_path = tmp_path / "stub.json"
    out_path = tmp_path / "report.json"
    diff_path.write_text(README_DIFF, encoding="utf-8")
    stub_path.write_text(json.dumps(_stub()), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable, "-m", "closed_knowledge_engine", "gate",
            "--diff-file", str(diff_path),
            "--stub", str(stub_path),
            "--out", str(out_path),
            "--quiet",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_PASS, proc.stderr
    assert json.loads(out_path.read_text())["verdict"] == "PASS"


def test_load_diff_file(tmp_path: Path):
    p = tmp_path / "d.diff"
    p.write_text(VIOL_DIFF, encoding="utf-8")
    assert "src/api/x.py" in load_diff_text(diff_file=p, git_diff=False, staged=False)
