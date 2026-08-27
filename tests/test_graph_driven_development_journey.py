"""The V1 product loop: code exposes a gap, propose writes it into the graph.

This deliberately crosses subsystem boundaries. Unit tests already prove each
verb; this proves they form one durable software-development record after all
in-memory engine state has been discarded.
"""

from __future__ import annotations

import shutil

from interaction.event_log import EventStore
from interaction.event_types import GRAPH_COMMITTED
from mcp_server.fixture import ensure_fixture
from mcp_server.surface import Surface


DIFF = """diff --git a/adapters/payments_http.py b/adapters/payments_http.py
--- a/adapters/payments_http.py
+++ b/adapters/payments_http.py
@@ -1 +1,4 @@
 def charge(order):
+    for attempt in range(10):
+        try_charge(order)
+    return None
"""

GAP_ID = "component_governance:adapters/payments_http.py"
RULE_ID = "outbound_http_retry_policy"
ENCODING = {
    "concepts": [{
        "id": RULE_ID,
        "label": "Outbound HTTP Retry Policy",
        "text_content": (
            "Outbound HTTP adapters must make at most three retry attempts "
            "and must use exponential backoff between attempts."
        ),
        "semantic_anchor": "at most three outbound HTTP retries with exponential backoff",
    }],
    "edges": [{
        "type": "EXPRESSES",
        "source_id": RULE_ID,
        "target_id": "stripe_payment_adapter",
        "label": "governs retry behaviour of",
    }],
}


def test_diff_gap_to_ratified_graph_survives_a_fresh_engine(tmp_path, monkeypatch):
    from mcp_server import pr_gate

    db_path = tmp_path / "architecture.lbug"
    store_path = tmp_path / "architecture.sqlite"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db_path)

    # Make the detection phase deterministic: this component has no applicable
    # rule. The Surface still performs its real whole-diff aggregation.
    monkeypatch.setattr(
        pr_gate,
        "pr_gate_live",
        lambda surface, diff, **kwargs: pr_gate.run_pr_gate(
            diff,
            [],
            conformance_fn=lambda *_: "CONFORMS",
            graph_version=surface.orient()["graph_version"],
        ),
    )

    surface = Surface(
        db_path, store_path=store_path,
        enable_history=True, enable_proposals=True,
    )
    initial_version = surface.orient()["graph_version"]
    finding = surface.check_conformance(diff=DIFF)
    assert finding["kind"] == "UNGOVERNED"
    assert finding["gaps"][0]["gap_id"] == GAP_ID

    handoff = surface.escalate(
        question="What retry policy governs the payments HTTP adapter?",
        ungoverned_predicate=finding["gaps"][0]["gap_id"],
        status="UNGOVERNED",
        engine_verdict="UNGOVERNED",
        provenance=[{"diff_hash": finding["diff_hash"]}],
    )
    assert handoff.get("stored")
    proposal = surface.propose(
        encoding=ENCODING,
        target_gap_id=GAP_ID,
        provenance={
            "generating_task": "govern an ungoverned software diff",
            "source_refs": [f"diff:{finding['diff_hash']}", "ADR:retry-policy"],
            "conversation_id": "v1-journey",
            "decision_origin": "propose_new",
        },
    )
    assert proposal["status"] == "COMMITTED"
    proposal_id = proposal["proposal_id"]
    assert surface.proposal_status(proposal_id)["target_gap_id"] == GAP_ID
    assert surface.proposal_status(proposal_id)["decision_origin"] == "propose_new"
    committed = proposal
    surface.close()

    # Destroy the old reader and prove a new process-shaped reader sees the
    # rule, its source, its graph delta, and can adjudicate against that node.
    fresh = Surface(
        db_path, store_path=store_path,
        enable_history=True, enable_proposals=True,
    )
    try:
        retrieved = fresh.retrieve({
            "contract_version": "retrieval-v1",
            "steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": [RULE_ID]},
                "assign_to": "rule",
            }],
            "collect": "$rule",
        }, evidence="content")
        assert retrieved["kind"] == "RETRIEVED"
        assert [node["id"] for node in retrieved["evidence"]["node_payloads"]] == [RULE_ID]
        assert "three retry attempts" in \
            retrieved["evidence"]["node_payloads"][0]["text_content"]

        lineage = fresh.lineage(RULE_ID)
        assert lineage["origin"] == "evolution"
        assert lineage["recorded"]["primary_source"].startswith("diff:")
        assert lineage["recorded"]["target_gap_id"] == GAP_ID
        assert lineage["recorded"]["decision_origin"] == "propose_new"
        assert any(
            step.get("step") == "gap" and step.get("gap_id") == GAP_ID
            for step in lineage["chain"]
        )
        assert not any(step.get("step") == "escalation" for step in lineage["chain"])

        delta = fresh.diff(
            committed["graph_version_before"], committed["graph_version_after"])
        assert [node["id"] for node in delta["concepts_added"]] == [RULE_ID]
        assert fresh.orient()["graph_version"] != initial_version

        monkeypatch.setenv("SST_CONFORMANCE_SKIP_CORPUS", "1")
        monkeypatch.setattr(
            "mcp_server.json_model.invoke_json_model",
            lambda *args, **kwargs: {
                "verdict": "VIOLATES",
                "grounding": "ten retries exceed the encoded maximum of three",
            },
        )
        ruling = fresh.check_conformance(
            rule_id=RULE_ID,
            artifact="for attempt in range(10): try_charge(order)",
            artifact_path="adapters/payments_http.py",
        )
        assert ruling["kind"] == "VIOLATES"
        assert ruling["attributed_rule"] == RULE_ID
        assert ruling["receipt"]["graph_version"] == fresh.orient()["graph_version"]
    finally:
        fresh.close()

    events = EventStore(store_path)
    try:
        rows = events.list_events()
    finally:
        events.close()
    commit_event = next(row for row in rows if row["type"] == GRAPH_COMMITTED)
    assert not any(row["type"] == "escalation.recorded" for row in rows)
    assert commit_event["proposal_id"] == proposal_id
    assert commit_event["actor"] == "gate:auto-encode"
