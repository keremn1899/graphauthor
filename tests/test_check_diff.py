"""Ruling a whole change, not one file at a time.

A PR is not N independent questions. `pr_gate._rationalizations` compares
receipts ACROSS a diff and across graph versions to catch governance bent to
bless code it had already refused — a check that cannot exist when an agent asks
file by file, because nothing holds the set together. That, not call-count, is
why the whole-diff mode belongs on the agent surface and not only in CI.

Deterministic: the aggregation and the trust flag are pure. The adjudication
they aggregate is not, and is tested elsewhere.
"""

from __future__ import annotations

DIFF = """diff --git a/core/orders.py b/core/orders.py
--- a/core/orders.py
+++ b/core/orders.py
@@ -1,2 +1,3 @@
 import os
+from adapters.payments_http import charge
"""


def test_a_diff_decomposes_into_files():
    from mcp_server.pr_gate import decompose_diff

    files = decompose_diff(DIFF)
    assert [f["path"] for f in files] == ["core/orders.py"]
    assert "payments_http" in files[0]["added_text"]


def test_only_violates_fails_the_gate():
    """The product's fail policy. UNGOVERNED and INSUFFICIENT are honest
    outputs, not failures — a gate that failed on them would punish operators
    for gaps the graph has not filled yet."""
    from mcp_server.pr_gate import run_pr_gate

    def conf(verdict):
        return lambda rule_id, artifact, path: verdict

    for verdict, expected in (("VIOLATES", "FAIL"), ("UNGOVERNED", "PASS"),
                              ("INSUFFICIENT_EVIDENCE", "PASS"),
                              ("CONFORMS", "PASS")):
        report = run_pr_gate(DIFF, ["r1"], conformance_fn=conf(verdict),
                             graph_version="v1")
        assert report["verdict"] == expected, f"{verdict} should be {expected}"


def test_every_diff_gap_has_a_stable_proposal_target():
    """A gap that cannot be named cannot travel through escalation/proposal."""
    from mcp_server.pr_gate import run_pr_gate

    no_rule = run_pr_gate(DIFF, [], conformance_fn=lambda *_: "CONFORMS")
    assert no_rule["gaps"] == [{
        "artifact_path": "core/orders.py",
        "verdict": "UNGOVERNED",
        "gap_id": "component_governance:core/orders.py",
        "reason": "no rule applies to this component",
    }]

    named = run_pr_gate(
        DIFF, ["retry_rule"],
        conformance_fn=lambda *_: {
            "verdict": "UNGOVERNED",
            "ungoverned_predicate": "outbound_http_retry_policy",
        },
    )
    assert named["gaps"][0]["gap_id"] == "outbound_http_retry_policy"


def test_a_pass_reached_only_because_the_graph_moved_is_untrusted():
    """The two-checkpoint check, and the reason whole-diff mode exists: the same
    code, previously refused, now passing under a newer graph."""
    from mcp_server.pr_gate import diff_hash, make_receipt, run_pr_gate

    prior = [make_receipt(rule_id="r1", artifact_path="core/orders.py",
                          verdict="VIOLATES", dhash=diff_hash(DIFF),
                          graph_version="v1")]
    report = run_pr_gate(
        DIFF, ["r1"],
        conformance_fn=lambda *_: "CONFORMS",
        graph_version="v2",           # graph moved, diff did not
        prior_receipts=prior,
    )
    assert report["verdict"] == "PASS"
    assert report["trusted"] is False, (
        "a PASS reached only because governance moved must not be trusted")
    assert report["rationalizations"]


def test_an_unchanged_graph_keeps_a_pass_trusted():
    """Guard against the flag being permanently on — it would stop meaning
    anything."""
    from mcp_server.pr_gate import diff_hash, make_receipt, run_pr_gate

    prior = [make_receipt(rule_id="r1", artifact_path="core/orders.py",
                          verdict="CONFORMS", dhash=diff_hash(DIFF),
                          graph_version="v1")]
    report = run_pr_gate(DIFF, ["r1"], conformance_fn=lambda *_: "CONFORMS",
                         graph_version="v1", prior_receipts=prior)
    assert report["trusted"] is True


def test_the_surface_aggregates_into_the_ruling_space():
    """Whatever the per-file detail, `kind` must be a ruling-space member, and
    the order must follow the fail policy: VIOLATES outranks everything, and an
    honest 'cannot tell' outranks a clean bill built on ungoverned files."""
    from mcp_server.surface import RULING_SPACE, Surface

    assert set(Surface._DIFF_KINDS) == RULING_SPACE
    assert Surface._DIFF_KINDS[0] == "VIOLATES"
    assert Surface._DIFF_KINDS.index("INSUFFICIENT_EVIDENCE") < \
        Surface._DIFF_KINDS.index("CONFORMS")
