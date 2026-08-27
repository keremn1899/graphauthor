from __future__ import annotations

import json

import battalion


def test_ungoverned_judgment_is_not_reopened_by_a_second_model_call(monkeypatch) -> None:
    """A safe refusal cannot become permission merely because two judges disagree."""

    class _Reply:
        def __init__(self, content: str):
            self.content = content

    class _LLM:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _messages):
            self.calls += 1
            return _Reply(
                "```json\n"
                + json.dumps({
                    "decision_predicate": "which TLS cipher suite to standardise on",
                    "unsupported_presuppositions": [],
                    "adjudications": [],
                    "governance_verdict": "UNGOVERNED",
                    "ungoverned_predicate": "TLS cipher-suite selection",
                })
                + "\n```\nThe retrieved credential rule is adjacent, not governing."
            )

    llm = _LLM()
    monkeypatch.setenv("SST_GOV_HEADER_NONCE", "0")
    monkeypatch.setattr(battalion, "_get_heavy_model", lambda: llm)
    monkeypatch.setattr(
        battalion,
        "get_node_payloads",
        lambda _conn, _ids: {
            "credential_rule": {
                "label": "Credential Rule",
                "text_content": "Credentials must not be logged in plaintext.",
            }
        },
    )
    state = {
        "query": "Which TLS cipher suites should we standardise on?",
        "verdict_space": "coverage",
        "compass": {"graph_profile": {"structural_character": "mixed"}},
        "confirmation_response": {"verdict": "EXHAUSTED"},
        "evidence_packet": {
            "node_records": [{"id": "credential_rule", "label": "Credential Rule"}],
            "edge_records": [],
            "path_records": [],
        },
        "company_handoff": {
            "internal_handoff": {
                "hypothesis_status": "not_confirmed",
                "confidence": "low",
                "primary_trails": [{
                    "trail_id": "trail_1",
                    "origin": "direct_path",
                    "rationale": "adjacent credential material",
                    "node_ids": ["credential_rule"],
                    "edge_types": [],
                    "edge_labels": [],
                }],
                "supporting_trails": [],
                "context_trails": [],
                "gaps": [],
            },
            "evidence_brief": {},
        },
    }

    out = battalion.battalion_synthesize(state, conn=None)

    assert llm.calls == 1
    assert out["confirmation_response"]["governance_verdict"] == "UNGOVERNED"
    assert out["deterministic_verdict"]["kind"] == "ILL_POSED"
    assert not any(
        "governance_adjudication_challenge" in flag
        for flag in out.get("degradation_flags", [])
    )


def test_governed_answer_preserves_every_adjudicated_constraint(monkeypatch) -> None:
    """Lossy synthesis cannot erase a qualifier present in graph authority."""

    class _Reply:
        content = (
            "```json\n"
            + json.dumps({
                "decision_predicate": "serializer-specific behavior location",
                "unsupported_presuppositions": [],
                "adjudications": [{
                    "policy_id": "serializer_rule",
                    "conformance_ruling": "CONFORMS",
                }],
                "governance_verdict": "GOVERNED",
                "ungoverned_predicate": "",
                "conformance_ruling": "CONFORMS",
            })
            + "\n```\nSerializer behavior belongs in preconf [Trail trail_1]."
        )

    class _LLM:
        def invoke(self, _messages):
            return _Reply()

    monkeypatch.setenv("SST_GOV_HEADER_NONCE", "0")
    monkeypatch.setattr(battalion, "_get_heavy_model", lambda: _LLM())
    monkeypatch.setattr(
        battalion,
        "get_node_payloads",
        lambda _conn, _ids: {
            "serializer_scope": {
                "label": "Serializer adapters",
                "text_content": "NAVIGATION: serializer adapter scope.",
            },
            "serializer_rule": {
                "label": "Serializer behavior rule",
                "text_content": (
                    "GOVERNING: serializer behavior belongs in preconfigured "
                    "factories whose results remain customizable."
                ),
            },
        },
    )
    state = {
        "query": "Where does serializer-specific behavior belong?",
        "verdict_space": "coverage",
        "compass": {"graph_profile": {"structural_character": "hierarchical"}},
        "confirmation_response": {"verdict": "CONFIRMED"},
        "evidence_packet": {
            "node_records": [
                {"id": "serializer_scope", "label": "Serializer adapters"},
                {"id": "serializer_rule", "label": "Serializer behavior rule"},
            ],
            "edge_records": [{
                "source_id": "serializer_scope",
                "target_id": "serializer_rule",
                "edge_type": "contains",
                "edge_label": "locates_decision",
            }],
            "path_records": [],
        },
        "company_handoff": {
            "internal_handoff": {
                "hypothesis_status": "confirmed",
                "confidence": "high",
                "primary_trails": [{
                    "trail_id": "trail_1",
                    "origin": "pipeline_b",
                    "rationale": "serializer decision",
                    "node_ids": ["serializer_scope", "serializer_rule"],
                    "edge_types": ["contains"],
                    "edge_labels": ["locates_decision"],
                }],
                "supporting_trails": [],
                "context_trails": [],
                "gaps": [],
            },
            "evidence_brief": {},
        },
    }

    out = battalion.battalion_synthesize(state, conn=None)

    assert "remain customizable" in out["final_answer"]
    assert "Governing constraints (verbatim graph anchors)" in out["final_answer"]
