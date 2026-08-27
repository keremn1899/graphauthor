"""v6 §7-Synthesis: Battalion citation-level verifier.

The verifier converts the synthesis closure guarantee from prompt-discipline
("don't cite hallucinated trails") into a deterministic gate that flags any
[Trail …] or [node_id] citation in the final answer that does not resolve
to the Company handoff or the EvidencePacket.

Production trail_ids are never bare `"1"` — Company emits `trail_1`, Pipeline B
emits `pb_node_0` / `pb_edge_0` / `pb_path_0`. The prompt still teaches ordinal
`[Trail 1]`. Resolution must accept both.
"""

from battalion import _verify_citations


def _company_shaped() -> dict:
    return {
        "primary_trails": [
            {"trail_id": "trail_1", "node_ids": ["n_a", "n_b"]},
            {"trail_id": "trail_2", "node_ids": ["n_c"]},
        ],
        "supporting_trails": [],
        "context_trails": [],
    }


def _pipeline_b_shaped() -> dict:
    return {
        "primary_trails": [
            {"trail_id": "pb_path_0", "node_ids": ["n_a", "n_b"]},
        ],
        "supporting_trails": [
            {"trail_id": "pb_edge_0", "node_ids": ["n_c"]},
        ],
        "context_trails": [
            {"trail_id": "pb_node_0", "node_ids": ["n_d"]},
        ],
    }


class TestCitationVerifier:
    def test_ordinal_against_company_shaped_ids(self):
        answer = "Alpha leads to Beta via Gamma. [Trail 1] supports this."
        out, flags = _verify_citations(
            answer=answer,
            internal=_company_shaped(),
            packet_node_ids={"n_a", "n_b", "n_c"},
        )
        assert flags == []
        assert "Citation verification" not in out

    def test_real_trail_id_cite(self):
        answer = "Supported by [Trail trail_1] and [Trail trail_2]."
        out, flags = _verify_citations(
            answer=answer,
            internal=_company_shaped(),
            packet_node_ids={"n_a", "n_b", "n_c"},
        )
        assert flags == []

    def test_ordinal_against_pipeline_b_ids(self):
        # Production SSDF-style path: trails are pb_*, model writes [Trail 1].
        answer = (
            "PS.1 from [Trail 1]. PS.2 from [Trail 3]. PS.3 from [Trail 2]."
        )
        out, flags = _verify_citations(
            answer=answer,
            internal=_pipeline_b_shaped(),
            packet_node_ids={"n_a", "n_b", "n_c", "n_d"},
        )
        assert flags == []
        assert "Citation verification" not in out

    def test_pipeline_b_id_literal(self):
        answer = "Grounded on [Trail pb_node_0]."
        out, flags = _verify_citations(
            answer=answer,
            internal=_pipeline_b_shaped(),
            packet_node_ids={"n_a", "n_b", "n_c", "n_d"},
        )
        assert flags == []

    def test_trail_id_not_in_handoff(self):
        answer = "Per [Trail 7] the chain holds."
        out, flags = _verify_citations(
            answer=answer,
            internal=_company_shaped(),
            packet_node_ids={"n_a", "n_b", "n_c"},
        )
        assert any("trail_7_missing" in f for f in flags)
        assert "Citation verification" not in out

    def test_trail_references_non_packet_node(self):
        answer = "[Trail 1] establishes the relation."
        out, flags = _verify_citations(
            answer=answer,
            internal=_company_shaped(),
            packet_node_ids={"n_a"},  # n_b absent
        )
        assert any("trail_1_node_drift" in f for f in flags)
        assert "Citation verification" not in out
        assert out == answer

    def test_bracketed_node_id_unverified(self):
        answer = "The hub [hallucinated_id_42] dominates."
        out, flags = _verify_citations(
            answer=answer,
            internal=_company_shaped(),
            packet_node_ids={"n_a"},
        )
        assert any("node_ids" in f and "hallucinated_id_42" in f for f in flags)

    def test_bracketed_node_id_recognised(self):
        answer = "The hub [n_a] dominates."
        out, flags = _verify_citations(
            answer=answer,
            internal=_company_shaped(),
            packet_node_ids={"n_a"},
        )
        assert flags == []

    def test_legacy_bare_numeric_trail_ids_still_work(self):
        # Older synthetic handoffs / tests that used trail_id "1" must remain green.
        internal = {
            "primary_trails": [{"trail_id": "1", "node_ids": ["n_a"]}],
            "supporting_trails": [],
            "context_trails": [],
        }
        out, flags = _verify_citations(
            answer="Ok [Trail 1].",
            internal=internal,
            packet_node_ids={"n_a"},
        )
        assert flags == []


def test_ill_posed_does_not_write_an_engine_essay():
    from battalion import battalion_synthesize

    out = battalion_synthesize(
        {
            "query": "What is the set difference?",
            "company_handoff": {
                "internal_handoff": {
                    "gaps": [{
                        "gap_type": "schema_gap",
                        "specific_node_or_concept": "set difference",
                        "actionable_suggestion": "Extend the graph schema.",
                    }],
                },
            },
            "confirmation_response": {
                "verdict": "ILL_POSED",
                "ill_posed_reason": "operator not in grammar",
            },
            "compass": {},
            "evidence_packet": {"node_records": [{"id": "n", "label": "Alpha"}]},
        },
        conn=None,
    )
    assert out["final_answer"] == ""
    assert out["gaps"]


def test_trail_connector_is_ordinary_english():
    from battalion import _trail_connector

    assert _trail_connector("LEADSTO") == "--[leads to]-->"
    assert _trail_connector("LEADSTO", "correction") == "--[leads to: correction]-->"
    assert _trail_connector("CONTAINS") == "--[contains]-->"
