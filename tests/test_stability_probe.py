from __future__ import annotations

from scripts import run_stability_probe as probe


def test_result_diagnostics_separate_trace_from_semantic_output() -> None:
    results = [
        {
            "trace_id": "trace-a",
            "graph_version": "graph-1",
            "status": "UNGOVERNED",
            "engine_verdict": "EXHAUSTED",
            "grounding_summary": "No retry rule was found.",
            "_stability_graph_content_ref": "content-1",
        },
        {
            "trace_id": "trace-b",
            "graph_version": "graph-1",
            "status": "UNGOVERNED",
            "engine_verdict": "EXHAUSTED",
            "grounding_summary": "No retry rule was found.",
            "_stability_graph_content_ref": "content-1",
        },
    ]

    diagnostics = probe._result_diagnostics(results)

    assert diagnostics["trace_ids"] == ["trace-a", "trace-b"]
    assert diagnostics["graph_versions"] == ["graph-1"]
    assert diagnostics["graph_content_refs"] == ["content-1"]
    assert diagnostics["engine_verdicts"] == ["EXHAUSTED", "EXHAUSTED"]
    assert len(set(diagnostics["grounding_fingerprints"])) == 1
    assert len(set(diagnostics["response_fingerprints"])) == 1


def test_result_diagnostics_expose_grounding_variance_without_storing_text() -> None:
    diagnostics = probe._result_diagnostics([
        {"status": "UNGOVERNED", "grounding_summary": "first explanation"},
        {"status": "UNGOVERNED", "grounding_summary": "second explanation"},
    ])

    assert len(set(diagnostics["grounding_fingerprints"])) == 2
    assert "first explanation" not in str(diagnostics)
    assert "second explanation" not in str(diagnostics)


def test_session_metadata_names_requested_route_not_unobserved_provider(monkeypatch) -> None:
    monkeypatch.setenv("SST_LLM_TEMPERATURE", "0")
    monkeypatch.setenv("PLANNER_MODEL", "provider/planner")
    monkeypatch.setenv("SQUAD_MODEL", "provider/squad")
    monkeypatch.setenv("BATTALION_MODEL", "provider/battalion")
    monkeypatch.setattr(probe, "_engine_commit", lambda: "abc1234")

    metadata = probe._session_metadata()

    assert metadata["engine_commit"] == "abc1234"
    assert metadata["temperature"] == 0.0
    assert metadata["requested_models"] == {
        "ask": "provider/battalion",
        "planner": "provider/planner",
        "squad": "provider/squad",
        "battalion": "provider/battalion",
    }
    assert metadata["provider_route"] == "openrouter"
    assert metadata["actual_provider_observed"] is False
