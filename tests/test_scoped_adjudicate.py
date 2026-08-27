"""Unit tests for structural single-node scoped adjudication (zero live LLM)."""

from __future__ import annotations

from conformance_verdict import ConformanceKind, ConformanceVerdict
from mcp_server.scoped_adjudicate import (
    adjudicate_rule_text_only,
    structural_scoped_enabled,
)


def test_structural_scoped_enabled_default(monkeypatch):
    monkeypatch.delenv("SST_SCOPED_STRUCTURAL", raising=False)
    assert structural_scoped_enabled() is True
    monkeypatch.setenv("SST_SCOPED_STRUCTURAL", "0")
    assert structural_scoped_enabled() is False


def test_adjudicate_rule_text_only_parses_verdict(monkeypatch):
    def _fake_invoke(system, user, **kwargs):
        assert "ONE rule" in system or "ONE RULE" in system.upper() or "strict" in system.lower()
        assert "NOTICE" in user and "ARTIFACT" in user
        return {"verdict": "CONFORMS", "grounding": "ships NOTICE as required"}

    monkeypatch.setattr(
        "mcp_server.json_model.invoke_json_model", _fake_invoke,
    )
    v = adjudicate_rule_text_only(
        rule_id="rule_notice",
        rule_text="You must include a readable copy of the NOTICE file.",
        rule_label="NOTICE Inclusion",
        artifact="We ship NOTICE verbatim.",
    )
    assert v.verdict == ConformanceKind.CONFORMS
    assert v.engine_verdict == "SCOPED_STRUCTURAL"
    assert "NOTICE" in v.grounding


def test_adjudicate_unknown_verdict_becomes_insufficient(monkeypatch):
    monkeypatch.setattr(
        "mcp_server.json_model.invoke_json_model",
        lambda *a, **k: {"verdict": "MAYBE", "grounding": "x"},
    )
    v = adjudicate_rule_text_only(
        rule_id="r", rule_text="must foo", rule_label="r", artifact="bar",
    )
    assert v.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE


def test_pr_gate_live_prefers_corpus_ruling():
    """Regression: live gate must read corpus_ruling / kind, not missing verdict."""
    from mcp_server.pr_gate import run_pr_gate

    seen = []

    def conf(rule_id, artifact, path):
        # Simulate what pr_gate_live's _conf extracts after fix
        out = {"corpus_ruling": "VIOLATES", "kind": "CONFORMS", "scoped_ruling": "CONFORMS"}
        for key in ("corpus_ruling", "kind", "verdict", "status"):
            val = out.get(key)
            if val:
                seen.append(key)
                return str(val).upper()
        return "UNGOVERNED"

    diff = (
        "diff --git a/src/api/x.py b/src/api/x.py\n"
        "--- a/src/api/x.py\n+++ b/src/api/x.py\n@@ -1 +1,2 @@\n a\n+b\n"
    )
    result = run_pr_gate(
        diff, ["api_rule"],
        conformance_fn=conf,
        applicability_fn=lambda r, p: p.startswith("src/api/"),
        graph_version="g1",
    )
    assert result["verdict"] == "FAIL"
    assert seen[0] == "corpus_ruling"
