from __future__ import annotations

from battalion import (
    _answer_after_governance_repair,
    _battalion_completion_budget,
    _extract_governance_header,
    _fold_governance_adjudications,
    _governing_constraints_appendix,
    _governance_repair_budget,
)
from conformance_verdict import ConformanceKind, from_engine_state


POLICY_ID = "preconf_placement"
POLICY_NODES = [{
    "id": POLICY_ID,
    "label": "Preconfigured serializer placement",
    "text_content": "ADJUDICATES: Serializer-specific behavior belongs in preconf.",
}]


def test_battalion_budget_finishes_complex_headers_but_stays_bounded(monkeypatch):
    monkeypatch.delenv("SST_BATTALION_MAX_TOKENS", raising=False)
    assert _battalion_completion_budget() == 3000
    monkeypatch.setenv("SST_BATTALION_MAX_TOKENS", "2048")
    assert _battalion_completion_budget() == 2048
    monkeypatch.setenv("SST_BATTALION_MAX_TOKENS", "not-an-int")
    assert _battalion_completion_budget() == 3000
    monkeypatch.setenv("SST_BATTALION_MAX_TOKENS", "999999")
    assert _battalion_completion_budget() == 8000

    monkeypatch.delenv("SST_GOVERNANCE_REPAIR_MAX_TOKENS", raising=False)
    assert _governance_repair_budget() == 2000
    monkeypatch.setenv("SST_GOVERNANCE_REPAIR_MAX_TOKENS", "999999")
    assert _governance_repair_budget() == 2000


def test_successful_repair_discards_only_an_unterminated_machine_header():
    raw = '```json\n{"unresolved_predicates": ["bytes"'
    assert _answer_after_governance_repair(raw, raw, "no_fence") == ""
    prose = "The requested decision remains unresolved."
    assert _answer_after_governance_repair(prose, prose, "no_fence") == prose


def _header(*, ruling: str = "CONFORMS", unresolved: list[str] | None = None):
    return {
        "decision_predicate": "add a plist adapter and define its wire semantics",
        "unsupported_presuppositions": [],
        "unresolved_predicates": list(unresolved or []),
        "adjudications": [{
            "policy_id": POLICY_ID,
            "conformance_ruling": ruling,
        }],
        "governance_verdict": "GOVERNED",
        "ungoverned_predicate": "",
        "conformance_ruling": ruling,
    }


def _state(confirmation: dict):
    return {
        "confirmation_response": {
            **confirmation,
            "verdict": "CONFIRMED",
            "governance_verdict_source": "battalion_synthesis",
        },
        "final_answer": "Placement is governed; exact wire semantics are not.",
        "evidence_packet": {"node_records": POLICY_NODES},
        "planner_route": "targeted_retrieval",
    }


def test_header_parser_preserves_bounded_unresolved_predicates():
    raw = """```json
{"governance_verdict":"PARTIALLY_GOVERNED","ungoverned_predicate":"",
"decision_predicate":"plist proposal","unsupported_presuppositions":[],
"unresolved_predicates":["date wire semantics","date wire semantics","bytes semantics"],
"adjudications":[{"policy_id":"preconf_placement","conformance_ruling":"CONFORMS"}],
"conformance_ruling":"CONFORMS"}
```
Answer."""
    parsed, answer, reason = _extract_governance_header(raw)
    assert reason == ""
    assert parsed is not None
    assert parsed["unresolved_predicates"] == [
        "date wire semantics", "bytes semantics"
    ]
    assert answer == "Answer."


def test_valid_conforms_plus_unresolved_folds_to_partial():
    folded, invalid = _fold_governance_adjudications(
        _header(unresolved=["exact plist wire semantics"]), POLICY_NODES
    )
    assert not invalid
    assert folded["governance_verdict"] == "PARTIALLY_GOVERNED"
    assert folded["conformance_ruling"] == "CONFORMS"
    assert folded["unresolved_predicates"] == ["exact plist wire semantics"]

    verdict = from_engine_state(_state(folded))
    assert verdict.verdict == ConformanceKind.INSUFFICIENT_EVIDENCE
    assert verdict.governance_status == "PARTIALLY_GOVERNED"
    assert verdict.governed_ruling == "CONFORMS"
    assert verdict.disposition == "OWNER_DECISION_REQUIRED"
    assert verdict.owner_decision_required is True
    assert verdict.unresolved_predicates == ["exact plist wire semantics"]


def test_partial_governance_preserves_exact_governed_anchor():
    appendix = _governing_constraints_appendix(
        {
            "governance_verdict": "PARTIALLY_GOVERNED",
            "adjudications": [{
                "policy_id": POLICY_ID,
                "conformance_ruling": "CONFORMS",
            }],
        },
        [(POLICY_ID, "Preconfigured placement", POLICY_NODES[0]["text_content"])],
    )
    assert "Governing constraints (verbatim graph anchors)" in appendix
    assert POLICY_NODES[0]["text_content"] in appendix


def test_valid_violation_plus_unresolved_remains_blocking_violation():
    folded, invalid = _fold_governance_adjudications(
        _header(
            ruling="VIOLATES",
            unresolved=["exact plist wire semantics"],
        ),
        POLICY_NODES,
    )
    assert not invalid
    assert folded["governance_verdict"] == "PARTIALLY_GOVERNED"

    verdict = from_engine_state(_state(folded))
    assert verdict.verdict == ConformanceKind.VIOLATES
    assert verdict.governed_ruling == "VIOLATES"
    assert verdict.owner_decision_required is True


def test_unsupported_premise_alone_does_not_create_partial_coverage():
    header = _header()
    header["unsupported_presuppositions"] = ["a nonexistent blanket exemption"]
    folded, invalid = _fold_governance_adjudications(header, POLICY_NODES)
    assert not invalid
    assert folded["governance_verdict"] == "GOVERNED"
    assert "unresolved_predicates" not in folded
    assert from_engine_state(_state(folded)).verdict == ConformanceKind.CONFORMS


def test_unresolved_only_is_ungoverned_not_partial():
    header = _header(unresolved=["async dispatch contract"])
    header["adjudications"] = []
    folded, invalid = _fold_governance_adjudications(header, POLICY_NODES)
    assert not invalid
    assert folded["governance_verdict"] == "UNGOVERNED"
    assert folded["ungoverned_predicate"]
    verdict = from_engine_state(_state(folded))
    assert verdict.disposition == "OWNER_DECISION_REQUIRED"
    assert verdict.owner_decision_required is True


def test_invalid_policy_citation_cannot_create_partial_coverage():
    header = _header(unresolved=["exact plist wire semantics"])
    header["adjudications"][0]["policy_id"] = "invented_policy"
    folded, invalid = _fold_governance_adjudications(header, POLICY_NODES)
    assert invalid == ["invented_policy"]
    assert folded["governance_verdict"] == "UNGOVERNED"


def test_fully_governed_dispositions_remain_separate_from_rulings():
    conforms = from_engine_state(_state(_header()))
    assert conforms.verdict == ConformanceKind.CONFORMS
    assert conforms.governed_ruling == "CONFORMS"
    assert conforms.disposition == "NONE"

    violates = from_engine_state(_state(_header(ruling="VIOLATES")))
    assert violates.verdict == ConformanceKind.VIOLATES
    assert violates.governed_ruling == "VIOLATES"
    assert violates.disposition == "REVISE"
