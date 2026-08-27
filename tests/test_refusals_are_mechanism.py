"""Two refusals that were prose and are now arithmetic.

The model-tier run measured what prose-level refusals are worth across provider
families: 17 of 26 comprehension cases travel, and the ones that do not are the
refusals the product is sold on. `verdict_shopping_is_refused` passed on the
model every description was tuned against and failed on the other three.

A guardrail that depends on how a reader interprets a paragraph is guidance. The
two here now change the *outcome* instead, so they hold whatever model is
pointed at the server:

- **Verdict shopping** — the same artifact under the same `graph_version` cannot
  have a different ruling, so the earlier one is returned unchanged. Re-asking
  in new words stops being a way to get a new answer, which is the only reason
  to do it.
- **An untrusted pass** — a PASS reached only because governance moved under
  unchanged code is downgraded to `INSUFFICIENT_EVIDENCE`. It was a field the
  caller was trusted to honour, and a GPT-4.1-mini agent did not.

Deterministic: no LLM. The memo and the downgrade are pure logic over recorded
state.
"""

from __future__ import annotations

import shutil

import pytest

DIFF = """diff --git a/core/orders.py b/core/orders.py
--- a/core/orders.py
+++ b/core/orders.py
@@ -1,2 +1,3 @@
 import os
+from adapters.payments_http import charge
"""


@pytest.fixture
def surface(tmp_path):
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    s = Surface(db, store_path=tmp_path / "store.sqlite")
    try:
        yield s
    finally:
        s.close()


# ------------------------------------------------------- verdict shopping


def test_re_asking_returns_the_same_ruling(surface):
    """The mechanism. A second identical question is answered from the first
    answer, so there is nothing to gain by asking again."""
    key = (surface._artifact_hash("x = 1", "core/orders.py"), "r1", "")
    surface._remember_verdict(key, {
        "kind": "VIOLATES", "graph_version": surface._base()["graph_version"],
        "rule_id": "r1",
    })

    again = surface._recall_verdict(key)
    assert again is not None, "an identical re-ask must not re-adjudicate"
    assert again["kind"] == "VIOLATES"
    assert again["reasked"] is True
    assert again["reask_note"]


def test_a_moved_graph_earns_a_fresh_ruling(surface):
    """Not a cache for its own sake. A changed graph is a real reason for a
    different answer, so the memo must yield rather than entrench a stale one."""
    key = (surface._artifact_hash("x = 1", "core/orders.py"), "r1", "")
    surface._remember_verdict(key, {"kind": "VIOLATES",
                                    "graph_version": "some_older_version"})

    assert surface._recall_verdict(key) is None


def test_a_different_artifact_is_a_different_question(surface):
    key_a = (surface._artifact_hash("x = 1", "a.py"), "r1", "")
    key_b = (surface._artifact_hash("x = 2", "a.py"), "r1", "")
    surface._remember_verdict(key_a, {
        "kind": "VIOLATES", "graph_version": surface._base()["graph_version"]})

    assert surface._recall_verdict(key_b) is None, (
        "changing the code must still be adjudicated")


def test_a_degraded_verdict_is_never_remembered(surface):
    """Entrenching an answer the engine could not stand behind would make a
    transient fault permanent."""
    version = surface._base()["graph_version"]
    for bad in ({"kind": "VIOLATES", "graph_version": version, "error": "boom"},
                {"kind": "VIOLATES", "graph_version": version,
                 "engine_degraded": True}):
        key = (f"h{bad.get('error', 'deg')}", "r1", "")
        surface._remember_verdict(key, bad)
        assert surface._recall_verdict(key) is None


# --------------------------------------------------- the untrusted pass


def test_an_untrusted_pass_is_downgraded_not_flagged(surface, monkeypatch):
    """The whole point: the caller cannot act on it by mistake, because there is
    no pass to act on."""
    import mcp_server.pr_gate as pr_gate

    monkeypatch.setattr(pr_gate, "pr_gate_live", lambda *a, **k: {
        "verdict": "PASS", "trusted": False, "diff_hash": "d1",
        "file_count": 1, "conforming": [{"rule_id": "r1"}],
        "blocking": [], "gaps": [], "needs_attention": [],
        "receipts": [{"rule_id": "r1"}],
        "rationalizations": [{"rule_id": "r1", "prior_verdict": "VIOLATES"}],
    })

    out = surface.check_conformance(diff=DIFF)
    assert out["kind"] == "INSUFFICIENT_EVIDENCE", (
        "a pass reached only because the graph moved is not a pass")
    assert out["downgraded_from"] == "CONFORMS"
    assert out["trusted"] is False
    assert out["rationalizations"]


def test_a_trusted_pass_is_left_alone(surface, monkeypatch):
    """Guard against the downgrade firing always, which would make every clean
    run unactionable."""
    import mcp_server.pr_gate as pr_gate

    monkeypatch.setattr(pr_gate, "pr_gate_live", lambda *a, **k: {
        "verdict": "PASS", "trusted": True, "diff_hash": "d1", "file_count": 1,
        "conforming": [{"rule_id": "r1"}], "blocking": [], "gaps": [],
        "needs_attention": [], "receipts": [], "rationalizations": [],
    })

    out = surface.check_conformance(diff=DIFF)
    assert out["kind"] == "CONFORMS"
    assert "downgraded_from" not in out


def test_a_violation_is_not_masked_by_the_downgrade(surface, monkeypatch):
    """VIOLATES outranks everything; the downgrade must not soften it."""
    import mcp_server.pr_gate as pr_gate

    monkeypatch.setattr(pr_gate, "pr_gate_live", lambda *a, **k: {
        "verdict": "FAIL", "trusted": False, "diff_hash": "d1", "file_count": 1,
        "blocking": [{"rule_id": "r1"}], "conforming": [], "gaps": [],
        "needs_attention": [], "receipts": [], "rationalizations": [{"x": 1}],
    })

    out = surface.check_conformance(diff=DIFF)
    assert out["kind"] == "VIOLATES"
