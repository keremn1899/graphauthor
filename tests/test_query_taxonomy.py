"""v6 Phase 9: query-taxonomy coverage tests.

These are deterministic (no LLM) tests that exercise the end-to-end information
infrastructure for each query_class in the v6 taxonomy. They validate three
guarantees per class:

1. AnswerContract shapes are accepted and propagated.
2. EvidencePacket integrity holds (every edge references packet nodes).
3. semantic_validation catches contradictions for that shape.

The tests here do not call the LLM; they exercise the deterministic layers
(Backend packet, semantic validation, Squad routing). The failing EXPRESSES
enumeration query is converted here into a permanent regression as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixture_db import create_fixture_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(
    *,
    query_class: str,
    shapes: list[str],
    proof_mode: str = "semantic",
    scope: str = "local",
    determinacy: str = "heuristic",
    composition: str = "atomic",
) -> dict:
    return {
        "query_class": query_class,
        "evidence_shapes_expected": shapes,
        "proof_mode": proof_mode,
        "scope": scope,
        "composition": composition,
        "determinacy": determinacy,
        "hypotheses": [],
    }


def _minimal_state(contract: dict, packet: dict, verdict: dict | None = None) -> dict:
    return {
        "answer_contract": contract,
        "evidence_packet": packet,
        "company_verdict": verdict or {},
        "degradation_flags": [],
    }


# ---------------------------------------------------------------------------
# AnswerContract accepts every declared query_class
# ---------------------------------------------------------------------------

TAXONOMY_CLASSES = [
    "enumeration",
    "relation_proof",
    "fanout",
    "overview",
    "exclusion",
    "semantic_lookup",
    "aggregation",
    "comparative",
    "existence",
    "meta_gap",
    "composite",
    "unknown",
]


@pytest.mark.parametrize("qclass", TAXONOMY_CLASSES)
def test_answer_contract_accepts_all_query_classes(qclass: str) -> None:
    from models import AnswerContract

    ac = AnswerContract(
        query_class=qclass,  # type: ignore[arg-type]
        evidence_shapes_expected=["node_set"],
        proof_mode="semantic",
        scope="local",
    )
    assert ac.query_class == qclass


# ---------------------------------------------------------------------------
# Shape coverage + semantic_validation per class
# ---------------------------------------------------------------------------











# ---------------------------------------------------------------------------
# Router: Squad bypass triggered by non-trail contracts
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# EXPRESSES enumeration regression (deterministic half — no LLM)
# ---------------------------------------------------------------------------

def test_expresses_enumeration_packet_preserves_edges(tmp_path: Path) -> None:
    """The failing query was 'what nodes are connected via an expresses
    connection'. Ensure the deterministic backend path preserves all
    EXPRESSES edges as canonical edge_records."""
    from backend_tools import build_evidence_packet, verify_packet_integrity
    from tools import get_nodes_by_edge_type

    conn = create_fixture_db("lotr", tmp_path / "expr_enum.lbug")
    try:
        variables = {"all_expresses": get_nodes_by_edge_type(conn, "expresses")}
        program = {
            "steps": [
                {
                    "tool": "get_nodes_by_edge_type",
                    "params": {"edge_type": "expresses"},
                    "assign_to": "all_expresses",
                }
            ]
        }
        # Simulate backend_execute's tool result adapter: attach edges to the
        # first node so build_evidence_packet can consume them.
        result = variables["all_expresses"]
        assert isinstance(result, dict)
        nodes = list(result.get("node_records") or [])
        edges = list(result.get("edge_records") or [])
        if nodes:
            nodes[0] = dict(nodes[0])
            nodes[0]["_edge_records"] = edges
        collected_ids = [str(n.get("id", "")) for n in nodes if n.get("id")]
        variables_adapted = {"all_expresses": nodes}

        packet = build_evidence_packet(conn, variables_adapted, program, collected_ids)
    finally:
        conn.close()

    assert len(packet["edge_records"]) >= 5, (
        f"expected >=5 EXPRESSES edges preserved, got {len(packet['edge_records'])}"
    )
    integrity = verify_packet_integrity(packet)
    assert integrity["valid"], f"packet integrity violated: {integrity['violations']}"


