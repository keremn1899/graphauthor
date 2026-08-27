"""Direct tests for `mcp_server.grain` — the deterministic grain vector.

The module had no dedicated test file; it was exercised only through retired
constructor-era batteries, which is how a hard gate went blind.
"""

def test_the_fusion_gate_reports_when_it_could_not_run():
    """A hard gate that cannot fire must not read as a clean pass.

    `rule_fusion` counts ADJUDICATES markers in the payload. Those markers were
    the workaround for `Concept` having no column for governing role, and a
    graph built since `claim_kind` exists carries none — measured, the newest
    reference graph has 0 markers across 24 nodes with `claim_kind` set on all
    24. So the one verdict-critical hard structural gate silently could not fire
    on any modern graph, and `conforms` said nothing about it.

    The count is not recoverable downstream: the workspace knows the per-node
    governing-claim count exactly and the graph keeps a single string, so this
    reports the blind spot rather than papering over it.
    """
    from mcp_server.grain import grain_check, node_features

    modern = {"id": "n1", "text_content": "Approvers must sign off.",
              "claim_kind": "governing"}
    legacy = {"id": "n2", "text_content": "ADJUDICATES a. ADJUDICATES b."}

    assert node_features(modern)["fusion_measurable"] is False
    assert node_features(legacy)["fusion_measurable"] is True

    report = grain_check([modern], added_edges=[])
    assert report["fusion_gate"]["unevaluable"] == 1
    assert report["fusion_gate"]["of"] == 1
    assert report["fusion_gate"]["reason"]

    # a legacy payload still counts, and still trips the hard gate
    legacy_report = grain_check([legacy], added_edges=[])
    assert legacy_report["fusion_gate"]["unevaluable"] == 0
    assert any(v["kind"] == "rule_fusion" for v in legacy_report["hard_violations"])
    assert legacy_report["conforms"] is False
