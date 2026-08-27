from __future__ import annotations

import hashlib

import pytest

from conformance_verdict import ConformanceKind, ConformanceVerdict
from mcp_server.selected_adjudication import (
    CLOSURE_CONTRACT_VERSION,
    FULL_GRAPH_NODE_LIMIT,
    SelectedEvidenceError,
    build_selected_packet,
    selected_result_gate,
)
from mcp_server.surface import Surface, open_fixture


FIXTURE = "runtime/hexagonal_orders.lbug"


@pytest.fixture(scope="module")
def surface() -> Surface:
    instance = open_fixture(FIXTURE)
    yield instance
    instance.close()


def _closure() -> dict:
    return {
        "contract_version": CLOSURE_CONTRACT_VERSION,
        "kind": "full_graph",
        "graph_version": "v",
        "node_count": 1,
        "node_ids_sha256": "a" * 64,
        "complete": True,
    }


def _verdict(
    kind: ConformanceKind,
    *,
    coverage: str,
    policies: list[str] | None = None,
    degraded: bool = False,
) -> ConformanceVerdict:
    return ConformanceVerdict(
        verdict=kind,
        governance_status=coverage,
        applying_policy_ids=list(policies or []),
        engine_degraded=degraded,
    )


def test_selected_packet_re_reads_exact_ids_and_binds_snapshot(surface):
    graph_version = surface.orient(context="capabilities")["graph_version"]
    packet, receipt, closure = build_selected_packet(
        surface._session.connection,
        ["dependency_direction_rule", "ports_module", "ports_module"],
        graph_version=graph_version,
    )

    assert closure is None
    assert receipt["requested_node_ids"] == [
        "dependency_direction_rule", "ports_module"
    ]
    assert receipt["graph_version"] == graph_version
    assert receipt["effective_node_count"] == 2
    assert {node["id"] for node in packet["node_records"]} == {
        "dependency_direction_rule", "ports_module"
    }
    assert packet["evidence_selection_mode"] == "host_selected"


def test_selected_packet_rejects_labels_and_unknown_ids(surface):
    graph_version = surface.orient(context="capabilities")["graph_version"]
    with pytest.raises(SelectedEvidenceError) as label_error:
        build_selected_packet(
            surface._session.connection,
            ["Dependency Direction Rule"],
            graph_version=graph_version,
        )
    assert label_error.value.code == "UNRESOLVED_EVIDENCE_ID"

    with pytest.raises(SelectedEvidenceError) as missing_error:
        build_selected_packet(
            surface._session.connection,
            ["definitely_missing_policy"],
            graph_version=graph_version,
        )
    assert missing_error.value.code == "UNRESOLVED_EVIDENCE_ID"
    assert missing_error.value.missing_ids == ["definitely_missing_policy"]


def test_full_graph_closure_is_deterministic_and_complete(surface):
    graph_version = surface.orient(context="capabilities")["graph_version"]
    first = build_selected_packet(
        surface._session.connection,
        ["dependency_direction_rule"],
        graph_version=graph_version,
        closure_mode="full_graph",
    )
    second = build_selected_packet(
        surface._session.connection,
        ["ports_module"],
        graph_version=graph_version,
        closure_mode="full_graph",
    )
    packet, receipt, closure = first

    assert closure is not None
    assert closure["complete"] is True
    assert closure["graph_version"] == graph_version
    assert closure["node_count"] == 30
    assert len(packet["node_records"]) == 30
    assert closure["node_ids_sha256"] == second[2]["node_ids_sha256"]
    assert receipt["effective_node_count"] == closure["node_count"]


def test_full_graph_closure_refuses_large_or_cross_graph_universes(monkeypatch):
    import mcp_server.selected_adjudication as selected

    monkeypatch.setattr(
        selected,
        "_all_graph_nodes",
        lambda _conn: ([f"n{i}" for i in range(FULL_GRAPH_NODE_LIMIT + 1)], False),
    )
    with pytest.raises(SelectedEvidenceError) as too_large:
        build_selected_packet(
            object(), ["n0"], graph_version="v", closure_mode="full_graph"
        )
    assert too_large.value.code == "CLOSURE_GRAPH_TOO_LARGE"

    monkeypatch.setattr(selected, "_all_graph_nodes", lambda _conn: (["n0"], True))
    with pytest.raises(SelectedEvidenceError) as metanode:
        build_selected_packet(
            object(), ["n0"], graph_version="v", closure_mode="full_graph"
        )
    assert metanode.value.code == "CLOSURE_UNSUPPORTED_METANODE"


@pytest.mark.parametrize(
    ("verdict", "closure", "kind", "safe", "blocking", "gap"),
    [
        (
            _verdict(
                ConformanceKind.CONFORMS,
                coverage="GOVERNED",
                policies=["rule"],
            ),
            None,
            "INSUFFICIENT_EVIDENCE",
            False,
            False,
            False,
        ),
        (
            _verdict(
                ConformanceKind.CONFORMS,
                coverage="GOVERNED",
                policies=["rule"],
            ),
            _closure(),
            "CONFORMS",
            True,
            False,
            False,
        ),
        (
            _verdict(
                ConformanceKind.VIOLATES,
                coverage="GOVERNED",
                policies=["rule"],
            ),
            None,
            "VIOLATES",
            False,
            True,
            False,
        ),
        (
            _verdict(ConformanceKind.UNGOVERNED, coverage="UNGOVERNED"),
            None,
            "INSUFFICIENT_EVIDENCE",
            False,
            False,
            False,
        ),
        (
            _verdict(ConformanceKind.UNGOVERNED, coverage="UNGOVERNED"),
            _closure(),
            "UNGOVERNED",
            False,
            False,
            True,
        ),
        (
            _verdict(
                ConformanceKind.INSUFFICIENT_EVIDENCE,
                coverage="PARTIALLY_GOVERNED",
                policies=["rule"],
            ),
            None,
            "INSUFFICIENT_EVIDENCE",
            False,
            False,
            False,
        ),
        (
            _verdict(
                ConformanceKind.VIOLATES,
                coverage="GOVERNED",
                policies=["rule"],
                degraded=True,
            ),
            None,
            "INSUFFICIENT_EVIDENCE",
            False,
            False,
            False,
        ),
    ],
)
def test_selected_result_gate_enforces_closure_asymmetry(
    verdict, closure, kind, safe, blocking, gap
):
    result = selected_result_gate(
        verdict, closure_receipt=closure, graph_version="v"
    )

    assert result["kind"] == kind
    assert result["safe_to_act"] is safe
    assert result["blocking"] is blocking
    assert result["gap_recordable"] is gap


def test_selected_result_gate_rejects_stale_or_malformed_closure():
    verdict = _verdict(
        ConformanceKind.CONFORMS,
        coverage="GOVERNED",
        policies=["rule"],
    )
    stale = selected_result_gate(
        verdict, closure_receipt=_closure(), graph_version="other"
    )
    malformed_receipt = {**_closure(), "node_ids_sha256": "short"}
    malformed = selected_result_gate(
        verdict, closure_receipt=malformed_receipt, graph_version="v"
    )

    assert stale["kind"] == "INSUFFICIENT_EVIDENCE"
    assert malformed["kind"] == "INSUFFICIENT_EVIDENCE"
    assert stale["closure_valid"] is False
    assert malformed["closure_valid"] is False


def test_selected_result_gate_projects_closure_and_owner_dispositions():
    conforms = selected_result_gate(
        _verdict(
            ConformanceKind.CONFORMS,
            coverage="GOVERNED",
            policies=["rule"],
        ),
        closure_receipt=None,
        graph_version="v",
    )
    negative = selected_result_gate(
        _verdict(ConformanceKind.UNGOVERNED, coverage="UNGOVERNED"),
        closure_receipt=None,
        graph_version="v",
    )
    closed_negative = selected_result_gate(
        _verdict(ConformanceKind.UNGOVERNED, coverage="UNGOVERNED"),
        closure_receipt=_closure(),
        graph_version="v",
    )
    partial = selected_result_gate(
        _verdict(
            ConformanceKind.INSUFFICIENT_EVIDENCE,
            coverage="PARTIALLY_GOVERNED",
            policies=["rule"],
        ),
        closure_receipt=None,
        graph_version="v",
    )

    assert conforms["disposition"] == "CORPUS_CLOSURE_REQUIRED"
    assert negative["disposition"] == "CORPUS_CLOSURE_REQUIRED"
    assert conforms["owner_decision_required"] is False
    assert negative["owner_decision_required"] is False
    assert closed_negative["disposition"] == "OWNER_DECISION_REQUIRED"
    assert closed_negative["owner_decision_required"] is True
    assert partial["disposition"] == "OWNER_DECISION_REQUIRED"
    assert partial["owner_decision_required"] is True


def test_surface_refuses_stale_or_missing_evidence_before_model(surface, monkeypatch):
    import battalion

    monkeypatch.setattr(
        battalion,
        "battalion_synthesize",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("invalid input reached Battalion")
        ),
    )
    stale = surface.adjudicate_selected_evidence(
        predicate="Does this conform?",
        artifact="change",
        evidence_node_ids=["dependency_direction_rule"],
        graph_version="stale",
    )
    current = surface.orient(context="capabilities")["graph_version"]
    missing = surface.adjudicate_selected_evidence(
        predicate="Does this conform?",
        artifact="change",
        evidence_node_ids=["missing_policy"],
        graph_version=current,
    )

    assert stale["input_status"] == "STALE_GRAPH"
    assert missing["input_status"] == "UNRESOLVED_EVIDENCE_ID"
    assert stale["model_invoked"] is False
    assert missing["model_invoked"] is False


def test_surface_bypasses_other_roles_and_blocks_on_selected_violation(
    surface, monkeypatch
):
    import battalion

    captured = {}

    def fake_battalion(state, _conn):
        captured.update(state)
        return {
            "final_answer": "The dependency direction rule prohibits this change.",
            "confirmation_response": {
                "verdict": "CONFIRMED",
                "governance_verdict": "GOVERNED",
                "decision_predicate": "dependency direction",
                "conformance_ruling": "VIOLATES",
                "adjudications": [{
                    "policy_id": "dependency_direction_rule",
                    "conformance_ruling": "VIOLATES",
                }],
            },
        }

    monkeypatch.setattr(battalion, "battalion_synthesize", fake_battalion)
    current = surface.orient(context="capabilities")["graph_version"]
    result = surface.adjudicate_selected_evidence(
        predicate="Does this dependency reversal conform?",
        artifact="Adapters import the domain service.",
        evidence_node_ids=["dependency_direction_rule"],
        graph_version=current,
    )

    assert result["kind"] == "VIOLATES"
    assert result["selected_ruling"] == "VIOLATES"
    assert result["blocking"] is True
    assert result["safe_to_act"] is False
    assert result["llm_roles"] == ["battalion"]
    assert "Does this dependency reversal conform?" in captured["query"]
    assert "Adapters import the domain service." in captured["query"]
    assert captured["planner_program"] == {}
    assert captured["evidence_selection_mode"] == "host_selected"


def test_surface_full_closure_can_promote_selected_permission(surface, monkeypatch):
    import battalion

    observed_packet_sizes = []

    def fake_battalion(state, _conn):
        observed_packet_sizes.append(len(state["evidence_packet"]["node_records"]))
        return {
            "final_answer": "The selected rule permits this change.",
            "confirmation_response": {
                "verdict": "CONFIRMED",
                "governance_verdict": "GOVERNED",
                "conformance_ruling": "CONFORMS",
                "adjudications": [{
                    "policy_id": "dependency_direction_rule",
                    "conformance_ruling": "CONFORMS",
                }],
            },
        }

    monkeypatch.setattr(battalion, "battalion_synthesize", fake_battalion)
    current = surface.orient(context="capabilities")["graph_version"]
    result = surface.adjudicate_selected_evidence(
        predicate="Does this conform?",
        artifact="Domain remains independent.",
        evidence_node_ids=["dependency_direction_rule"],
        graph_version=current,
        closure_mode="full_graph",
    )

    assert result["kind"] == "CONFORMS"
    assert result["safe_to_act"] is True
    assert result["closure_valid"] is True
    assert result["closure_receipt"]["node_count"] == 30
    assert observed_packet_sizes == [30]


def test_host_selected_candidates_are_neutral_until_post_fold(monkeypatch):
    import battalion

    payloads = {
        "rule": {
            "id": "rule",
            "label": "Rule",
            "text_content": (
                "GOVERNING: The adapter must not import the domain. "
                "This complete second sentence must survive the appendix."
            ),
            "semantic_anchor": "short summary",
        }
    }
    monkeypatch.setattr(
        battalion, "get_node_anchors", lambda _conn, _ids: {"rule": "exact clause"}
    )
    ordinary = battalion._edge_supported_governing_anchors(
        {"verdict_space": "ruling"}, {"edge_records": []}, payloads, object()
    )
    selected_pre_fold = battalion._edge_supported_governing_anchors(
        {
            "verdict_space": "ruling",
            "evidence_selection_mode": "host_selected",
        },
        {"edge_records": []},
        payloads,
        object(),
    )

    assert ordinary == []
    appendix = battalion._host_selected_governing_appendix(
        {
            "governance_verdict": "GOVERNED",
            "adjudications": [{
                "policy_id": "rule",
                "conformance_ruling": "VIOLATES",
            }],
        },
        {
            **payloads,
            "context": {
                "id": "context",
                "label": "Context",
                "text_content": "GOVERNING: A related mechanism exists.",
            },
        },
        object(),
    )

    assert selected_pre_fold == []
    assert "`rule`" in appendix
    assert payloads["rule"]["text_content"] in appendix
    assert "short summary" not in appendix
    assert "context" not in appendix


def test_frozen_selected_runner_inputs_validate():
    from benchmarks.external.cattrs_software.host_selected_adjudication_v1 import (
        _load_tasks,
        main,
    )

    assert len(_load_tasks()["cases"]) == 6
    assert main(["--validate-only"]) == 0


def test_selected_runner_score_rejects_permission_or_gap_without_closure():
    from benchmarks.external.cattrs_software.host_selected_adjudication_v1 import (
        score_case,
    )
    from benchmarks.external.cattrs_software.direct_surface_v3 import _oracle_by_id

    case = {
        "predicate": "p",
        "artifact": "a",
        "closure_mode": "none",
        "expected_kind": "INSUFFICIENT_EVIDENCE",
        "expected_selected_ruling": "CONFORMS",
        "expected_coverage": "GOVERNED",
        "required_applying_policy_ids": [],
        "required_context_ids": [],
        "forbidden_authority_ids": [],
        "expected_safe_to_act": False,
        "expected_disposition": "CORPUS_CLOSURE_REQUIRED",
        "owner_decision_required": False,
    }
    common = {
        "selected_ruling": "CONFORMS",
        "selected_coverage": "GOVERNED",
        "applying_policy_ids": [],
        "evidence_node_ids": [],
        "closure_receipt": None,
        "closure_valid": False,
        "safe_to_act": False,
        "owner_decision_required": False,
        "disposition": "CORPUS_CLOSURE_REQUIRED",
        "execution_path": [
            "exact_packet_build",
            "battalion_adjudication",
            "selected_scope_gate",
        ],
        "llm_roles": ["battalion"],
        "decision_predicate": "p",
        "artifact_sha256": hashlib.sha256(b"a").hexdigest(),
        "model_invoked": True,
        "engine_degraded": False,
    }
    permission = score_case(
        case, {**common, "kind": "CONFORMS"}, _oracle_by_id()
    )
    gap = score_case(
        {
            **case,
            "expected_selected_ruling": "UNGOVERNED",
            "expected_coverage": "UNGOVERNED",
        },
        {
            **common,
            "kind": "UNGOVERNED",
            "selected_ruling": "UNGOVERNED",
            "selected_coverage": "UNGOVERNED",
            "gap_recordable": True,
        },
        _oracle_by_id(),
    )

    assert permission["false_permission"] is True
    assert gap["false_gap_without_closure"] is True
