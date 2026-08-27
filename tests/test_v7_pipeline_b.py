"""v7 Phase 5 — Pipeline B (Targeted Retrieval) tests.

All question_forms exercised against the deterministic dependencies fixture.
"""

from __future__ import annotations

from pipeline_b import (
    _normalise_contract,
    compute_verdict_pipeline_b,
    pipeline_b_execute,
)


def _base_state(contract: dict, **overrides):
    base = {
        "query": "pipeline-b probe",
        "planner_route": "targeted_retrieval",
        "relational_contract": contract,
        "compass": {
            "graph_profile": {
                "node_count": 10,
                "total_edges": 10,
                "edge_counts": {"leadsto": 7, "contains": 0},
            },
        },
        "structural_index": {},
        "degradation_flags": [],
        "reseed_attempted": False,
        "planner_program": {},
        "evidence_packet": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Contract normalisation
# ---------------------------------------------------------------------------


def test_normalise_contract_coerces_defaults():
    c = _normalise_contract({"question_form": "UNKNOWN", "direction": "weird"})
    assert c["question_form"] == "lookup"
    assert c["direction"] == "outgoing"
    assert c["edge_types"] == []
    assert c["max_hops"] == 1


def test_normalise_contract_lowercases_edge_types():
    c = _normalise_contract({"edge_types": ["LEADSTO", " Contains "]})
    assert c["edge_types"] == ["leadsto", "contains"]


# ---------------------------------------------------------------------------
# Pipeline B dispatch
# ---------------------------------------------------------------------------


def test_pipeline_b_fanout_builds_packet_with_edges(deps_conn):
    state = _base_state({
        "question_form": "fanout",
        "source_ids": ["svc_gateway"],
        "edge_types": ["leadsto"],
        "direction": "outgoing",
        "max_hops": 1,
    })
    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    assert packet["edge_records"], "fanout must surface edge_records"
    # Every edge must be of declared type.
    assert all(e["edge_type"] == "leadsto" for e in packet["edge_records"])
    # Deterministic verdict is CONFIRMED.
    verdict = out["deterministic_verdict"]
    assert verdict["kind"] == "CONFIRMED"
    # Confirmation response mirrored so Battalion sees the verdict.
    assert out["confirmation_response"]["verdict"] == "CONFIRMED"
    # company_handoff has at least one primary or supporting trail.
    internal = out["company_handoff"]["internal_handoff"]
    assert internal["primary_trails"] or internal["supporting_trails"]


def test_pipeline_b_proof_finds_path(deps_conn):
    state = _base_state({
        "question_form": "proof",
        "source_ids": ["svc_gateway"],
        "target_ids": ["svc_auth"],
        "edge_types": ["leadsto"],
        "direction": "outgoing",
        "max_hops": 2,
    })
    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    # Paths should be populated.
    assert packet["path_records"], "proof must surface path_records"
    verdict = out["deterministic_verdict"]
    assert verdict["kind"] == "CONFIRMED"


def test_pipeline_b_enumeration_returns_typed_edges(deps_conn):
    state = _base_state({
        "question_form": "enumeration",
        "edge_types": ["leadsto"],
        "source_ids": [],
        "direction": "outgoing",
        "max_hops": 1,
    })
    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    assert packet["edge_records"]
    assert all(e["edge_type"] == "leadsto" for e in packet["edge_records"])


def test_pipeline_b_lookup_returns_nodes_and_neighbours(deps_conn):
    state = _base_state({
        "question_form": "lookup",
        "source_ids": ["svc_gateway"],
        "edge_types": [],
    })
    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    ids = {n["id"] for n in (packet.get("node_records") or [])}
    assert "svc_gateway" in ids


def test_pipeline_b_lookup_resolves_human_labels(deps_conn):
    """Planner often emits short labels; lookup must resolve like fanout/proof."""
    state = _base_state({
        "question_form": "lookup",
        "source_ids": ["API Gateway"],
        "edge_types": [],
    })
    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    ids = {n["id"] for n in (packet.get("node_records") or [])}
    assert "svc_gateway" in ids


def test_governance_lookup_closes_reached_subject_to_incoming_rules(deps_conn):
    deps_conn.execute(
        "MATCH (context:Concept {id: 'svc_gateway'}), "
        "(subject:Concept {id: 'svc_order'}) "
        "CREATE (context)-[:NEARTO {label: 'uses_process'}]->(subject)"
    )
    deps_conn.execute(
        "MATCH (rule:Concept {id: 'svc_payment'}), "
        "(subject:Concept {id: 'svc_order'}) "
        "CREATE (rule)-[:EXPRESSES {label: 'ADJUDICATES:'}]->(subject)"
    )
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["svc_gateway"],
            "edge_types": ["nearto"],
        },
        verdict_space="coverage",
    )

    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    ids = {node["id"] for node in packet["node_records"]}

    assert "svc_payment" in ids
    assert any(
        edge["source_id"] == "svc_payment"
        and edge["target_id"] == "svc_order"
        and edge["edge_type"] == "expresses"
        for edge in packet["edge_records"]
    )


def test_governance_lookup_closes_architecture_boundary_to_current_decision(
    deps_conn,
):
    """A nearby architecture boundary contributes only authoritative truth.

    This is the construction shape used by the frozen Cattrs reference graph:
    an adapter is NEARTO a boundary component which CONTAINS both the current
    decision and historical alternatives.
    """
    for node_id, label, text in (
        (
            "edge_boundary",
            "Edge concern boundary",
            "Validation and serialization stay outside business models.",
        ),
        (
            "current_boundary_decision",
            "Current boundary decision",
            "GOVERNING: keep edge concerns outside business models.",
        ),
        (
            "rejected_boundary_decision",
            "Rejected boundary decision",
            "CONTEXT: rejected model-coupled serialization alternative.",
        ),
        (
            "other_component",
            "Other component",
            "A structurally connected but semantically different component.",
        ),
        (
            "other_governing_decision",
            "Other governing decision",
            "GOVERNING: an unrelated component rule.",
        ),
    ):
        deps_conn.execute(
            "CREATE (c:Concept {id: $id, label: $label, text_content: $text, "
            "semantic_anchor: $text, token_count: 12, centrality_score: 0.0, "
            "is_metanode: false, linked_graph_id: ''})",
            {"id": node_id, "label": label, "text": text},
        )
    deps_conn.execute(
        "MATCH (adapter:Concept {id: 'svc_gateway'}), "
        "(boundary:Concept {id: 'edge_boundary'}), "
        "(current:Concept {id: 'current_boundary_decision'}), "
        "(rejected:Concept {id: 'rejected_boundary_decision'}), "
        "(other:Concept {id: 'other_component'}), "
        "(other_rule:Concept {id: 'other_governing_decision'}) "
        "CREATE (adapter)-[:NEARTO {label: 'honors_boundary'}]->(boundary), "
        "(boundary)-[:CONTAINS {label: 'locates_decision'}]->(current), "
        "(boundary)-[:CONTAINS {label: 'locates_decision'}]->(rejected), "
        "(adapter)-[:LEADSTO {label: 'unrelated'}]->(other), "
        "(other)-[:CONTAINS {label: 'locates_decision'}]->(other_rule)"
    )
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["svc_gateway"],
            "edge_types": ["nearto"],
            "direction": "outgoing",
        },
        verdict_space="coverage",
    )

    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    ids = {node["id"] for node in packet["node_records"]}

    assert "edge_boundary" in ids
    assert "current_boundary_decision" in ids
    assert "rejected_boundary_decision" not in ids
    assert "other_governing_decision" not in ids
    assert {
        (edge["source_id"], edge["edge_type"], edge["target_id"])
        for edge in packet["edge_records"]
    } >= {
        ("svc_gateway", "nearto", "edge_boundary"),
        ("edge_boundary", "contains", "current_boundary_decision"),
    }


def test_confirmation_lookup_does_not_apply_governance_rule_closure(deps_conn):
    deps_conn.execute(
        "MATCH (rule:Concept {id: 'svc_payment'}), "
        "(subject:Concept {id: 'svc_order'}) "
        "CREATE (rule)-[:EXPRESSES {label: 'ADJUDICATES:'}]->(subject)"
    )
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["svc_gateway"],
            "edge_types": [],
        },
        verdict_space="confirmation",
    )

    out = pipeline_b_execute(state, deps_conn)
    edge_types = {
        edge["edge_type"] for edge in out["evidence_packet"]["edge_records"]
    }

    assert "expresses" not in edge_types


def test_pipeline_b_preserves_declared_semantic_target_beside_broad_traversal(
    deps_conn,
):
    """The contract backend must not discard an exact answer entity named by
    the same Planner merely because its relational path starts elsewhere."""
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["API Gateway"],
            "edge_types": [],
        },
        planner_program={
            "answer_contract": {"query_class": "semantic_lookup"},
            "entity_intent": {"target_terms": ["Auth Service"]},
        },
    )
    out = pipeline_b_execute(state, deps_conn)
    ids = [n["id"] for n in out["evidence_packet"]["node_records"]]
    assert "svc_auth" in ids
    assert ids.index("svc_auth") < ids.index("svc_gateway")


def _add_content_hierarchy(conn):
    for node_id, label, text in (
        ("doc_root", "Source document", "# Source document\n\nSource: fixture"),
        ("doc_section", "§4 Server requirements", "# §4 Server requirements\n\nSource: fixture §4"),
        (
            "doc_paragraph",
            "§4 paragraph 1",
            "An origin server should limit its output to the well-behaved "
            "profile unless it has a documented reason to do otherwise.",
        ),
    ):
        conn.execute(
            "CREATE (c:Concept {id: $id, label: $label, text_content: $text, "
            "semantic_anchor: $label, token_count: 20, centrality_score: 0.0, "
            "is_metanode: false, linked_graph_id: ''})",
            {"id": node_id, "label": label, "text": text},
        )
    conn.execute(
        "MATCH (root:Concept {id: 'doc_root'}), "
        "(section:Concept {id: 'doc_section'}), "
        "(paragraph:Concept {id: 'doc_paragraph'}) "
        "CREATE (root)-[:CONTAINS {label: 'section'}]->(section), "
        "(section)-[:CONTAINS {label: 'paragraph'}]->(paragraph)"
    )


def test_contains_content_lookup_preserves_exact_scope_and_descends(deps_conn):
    """A broad contract must not discard the precise section in Planner steps."""
    _add_content_hierarchy(deps_conn)
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["doc_root"],
            "edge_types": ["contains"],
            "direction": "outgoing",
            "max_hops": 1,
        },
        planner_program={
            "steps": [{
                "tool": "exact_node_lookup",
                "params": {"label_or_id": ["doc_section"]},
                "assign_to": "policy_nodes",
            }],
        },
        verdict_space="confirmation",
    )

    out = pipeline_b_execute(state, deps_conn)
    packet = out["evidence_packet"]
    ids = [node["id"] for node in packet["node_records"]]

    assert "doc_section" in ids
    assert "doc_paragraph" in ids
    # The targeted contract is the executable truth. The precise section named
    # by the Planner remains a bounded content refinement beside that traversal.
    assert "doc_root" in ids
    assert packet["retrieval_assessment"]["content_status"] == "content_retrieved"
    assert packet["retrieval_assessment"]["semantic_completeness"] == "not_assessed"
    assert out["deterministic_verdict"]["retrieval_status"] == "CONTENT_RETRIEVED"


def test_contains_structural_fanout_keeps_declared_one_hop(deps_conn):
    """Content hydration must not change immediate-membership questions."""
    _add_content_hierarchy(deps_conn)
    state = _base_state({
        "question_form": "fanout",
        "source_ids": ["doc_root"],
        "edge_types": ["contains"],
        "direction": "outgoing",
        "max_hops": 1,
    }, verdict_space="confirmation")

    out = pipeline_b_execute(state, deps_conn)
    ids = {node["id"] for node in out["evidence_packet"]["node_records"]}

    assert "doc_section" in ids
    assert "doc_paragraph" not in ids
    assert out["evidence_packet"]["retrieval_assessment"]["content_status"] == "not_required"
    assert out["deterministic_verdict"]["retrieval_status"] == "STRUCTURAL_ONLY"


def test_contains_content_lookup_reports_unresolved_payload(deps_conn):
    deps_conn.execute(
        "CREATE (c:Concept {id: 'empty_section', label: 'Empty section', "
        "text_content: '# Empty section\\n\\nSource: fixture', "
        "semantic_anchor: 'empty section', token_count: 5, "
        "centrality_score: 0.0, is_metanode: false, linked_graph_id: ''})"
    )
    state = _base_state({
        "question_form": "lookup",
        "source_ids": ["empty_section"],
        "edge_types": ["contains"],
        "direction": "outgoing",
    }, verdict_space="confirmation")

    out = pipeline_b_execute(state, deps_conn)

    assert out["evidence_packet"]["retrieval_assessment"]["content_status"] == "unresolved"
    assert out["deterministic_verdict"]["kind"] == "CONFIRMED"
    assert out["deterministic_verdict"]["retrieval_status"] == "NO_CONTENT"
    assert "contains_payload_unresolved" in out["degradation_flags"]


def test_non_contains_lookup_does_not_trigger_content_descent(deps_conn):
    state = _base_state({
        "question_form": "lookup",
        "source_ids": ["svc_gateway"],
        "edge_types": ["leadsto"],
        "direction": "outgoing",
    }, verdict_space="confirmation")

    out = pipeline_b_execute(state, deps_conn)

    assessment = out["evidence_packet"]["retrieval_assessment"]
    assert assessment["content_refinement_required"] is False
    assert assessment["content_status"] == "not_required"


def test_pipeline_b_does_not_turn_conditional_reasoning_into_missing_gap(deps_conn):
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["API Gateway"],
            "edge_types": [],
        },
        planner_program={
            "strategy_b": {
                "reasoning_per_concept": {
                    "Auth Service": (
                        "If Auth Service is missing, the service hierarchy is broken. "
                        "Its absence would imply incomplete ingestion."
                    ),
                },
            },
        },
    )
    out = pipeline_b_execute(state, deps_conn)
    gaps = out["company_handoff"]["internal_handoff"]["gaps"]
    assert not any(g.get("gap_type") == "missing_concept" for g in gaps)


def test_pipeline_b_graph_identity_overrules_stale_missing_claim(deps_conn):
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["API Gateway"],
            "edge_types": [],
        },
        planner_program={
            "strategy_b": {
                "reasoning_per_concept": {
                    "Auth Service": "Auth Service is not present in the graph.",
                },
            },
        },
    )
    out = pipeline_b_execute(state, deps_conn)
    gaps = out["company_handoff"]["internal_handoff"]["gaps"]
    assert not any(g.get("gap_type") == "missing_concept" for g in gaps)


def test_pipeline_b_preserves_actual_missing_concept_claim(deps_conn):
    state = _base_state(
        {
            "question_form": "lookup",
            "source_ids": ["API Gateway"],
            "edge_types": [],
        },
        planner_program={
            "strategy_b": {
                "reasoning_per_concept": {
                    "Nonexistent Policy": (
                        "Nonexistent Policy is not present in the graph."
                    ),
                },
            },
        },
    )
    out = pipeline_b_execute(state, deps_conn)
    gaps = out["company_handoff"]["internal_handoff"]["gaps"]
    assert any(
        g.get("gap_type") == "missing_concept"
        and g.get("specific_node_or_concept") == "Nonexistent Policy"
        for g in gaps
    )


def test_pipeline_b_empty_packet_with_missing_edge_type_is_ill_posed():
    """When Compass shows the edge type is absent, verdict is ILL_POSED."""
    state = {
        "evidence_packet": {"node_records": [], "edge_records": [], "path_records": []},
        "relational_contract": {"edge_types": ["contains"], "source_ids": ["x"]},
        "compass": {"graph_profile": {"edge_counts": {"leadsto": 7, "contains": 0}}},
    }
    verdict = compute_verdict_pipeline_b(state)
    assert verdict["kind"] == "ILL_POSED"
    assert verdict["terminal"] is True


def test_pipeline_b_empty_packet_with_populated_edge_type_is_exhausted():
    state = {
        "evidence_packet": {"node_records": [], "edge_records": [], "path_records": []},
        "relational_contract": {"edge_types": ["leadsto"], "source_ids": ["x"]},
        "compass": {"graph_profile": {"edge_counts": {"leadsto": 7}}},
    }
    verdict = compute_verdict_pipeline_b(state)
    assert verdict["kind"] == "EXHAUSTED"


def test_pipeline_b_partial_coverage_still_confirmed(deps_conn):
    """source_ids include a node that has no leadsto edges → partial gap recorded."""
    state = _base_state({
        "question_form": "fanout",
        "source_ids": ["svc_gateway", "svc_not_real"],
        "edge_types": ["leadsto"],
        "direction": "outgoing",
        "max_hops": 1,
    })
    out = pipeline_b_execute(state, deps_conn)
    verdict = out["deterministic_verdict"]
    assert verdict["kind"] == "CONFIRMED"
    # svc_not_real is missing from coverage.
    assert "svc_not_real" in verdict.get("missing_sources", [])


def test_pipeline_b_coverage_compares_resolved_ids_not_planner_labels(deps_conn):
    state = _base_state({
        "question_form": "fanout",
        "source_ids": ["API Gateway"],
        "edge_types": ["leadsto"],
        "direction": "outgoing",
        "max_hops": 1,
    })
    out = pipeline_b_execute(state, deps_conn)
    assert out["deterministic_verdict"]["kind"] == "CONFIRMED"
    assert out["deterministic_verdict"].get("missing_sources") == []
    gaps = out["company_handoff"]["internal_handoff"]["gaps"]
    assert not any(g.get("gap_type") == "missing_source_coverage" for g in gaps)
