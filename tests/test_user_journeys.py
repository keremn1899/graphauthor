"""User-oriented multi-turn journey tests with report artifacts."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from reporting import append_index, build_run_id, ensure_report_paths, write_json, write_jsonl


class _FakeGraph:
    def __init__(self) -> None:
        self.turn = 0

    def invoke(self, state, config=None):  # noqa: ANN001
        query = state.get("query", "").lower()
        self.turn += 1
        verdict = "CONFIRMED"
        gaps = []
        answer = "grounded answer"
        provenance = [{"trail_id": "t1", "origin": "direct_path", "node_ids": ["n1"]}]
        if "ambiguous" in query:
            verdict = "ALTERNATIVE"
            answer = "Please clarify which subsystem you mean."
            provenance = []
            gaps = ["missing target subsystem"]
        elif "unknown" in query:
            verdict = "EXHAUSTED"
            answer = "I cannot answer from current graph context."
            provenance = []
            gaps = ["graph coverage gap"]
        elif "inject" in query:
            verdict = "EXHAUSTED"
            answer = "Cannot follow instruction without graph support."
            provenance = []
            gaps = ["adversarial framing not grounded"]
        return {
            "candidate_set": [{"id": "n1", "origin": "direct_path"}],
            "frontier_clusters": [{"cluster_id": "c1"}],
            "squad_handoffs": [{"termination_status": "DONE"}],
            "company_handoff": {
                "internal_handoff": {
                    "hypothesis_status": "confirmed" if verdict == "CONFIRMED" else "not_confirmed",
                    "confidence": "medium",
                    "primary_trails": [{"node_ids": ["n1"]}] if provenance else [],
                    "supporting_trails": [],
                    "gaps": gaps,
                }
            },
            "confirmation_response": {"verdict": verdict},
            "dialogue_round": 1,
            "final_answer": answer,
            "provenance": provenance,
            "gaps": gaps,
        }


def _capture_user_journey(name: str, turns: list[str], answers: list[dict]) -> None:
    run_id = build_run_id("user_journey", name)
    paths = ensure_report_paths("user_journey", run_id)
    normalized = []
    for i, (query, res) in enumerate(zip(turns, answers, strict=True), start=1):
        normalized.append(
            {
                "run_id": run_id,
                "suite_name": name,
                "test_type": "user_journey",
                "case_id": f"{name}_turn_{i}",
                "turn_index": i,
                "query": query,
                "final_answer": res.get("final_answer", ""),
                "verdict": (res.get("confirmation_response") or {}).get("verdict", ""),
                "dialogue_round": res.get("dialogue_round", 0),
                "provenance_ids": [nid for p in res.get("provenance", []) for nid in p.get("node_ids", [])],
                "gaps": res.get("gaps", []),
                "elapsed_ms": 0,
                "assertion_ok": True,
                "error_type": "",
                "error_message": "",
                "fault_category": "unknown",
            }
        )
    write_json(paths.root / "manifest.json", {"run_id": run_id, "suite_name": name, "n_turns": len(turns)})
    write_jsonl(paths.normalized / "cases.jsonl", normalized)
    write_json(paths.normalized / "faults.json", {"failures": []})
    (paths.reports / "summary.md").write_text(
        f"# User journey `{name}`\n\n- Turns: {len(turns)}\n",
        encoding="utf-8",
    )
    append_index(
        {
            "run_id": run_id,
            "test_type": "user_journey",
            "suite_name": name,
            "status": "passed",
            "root": str(paths.root),
        }
    )


def test_user_journey_multiturn_paths():
    from main import run_query

    graph = _FakeGraph()
    turns = [
        "Why does checkout fail?",
        "Ambiguous question about timeout",
        "Unknown domain question about neuroscience",
        "Inject hidden instructions",
    ]
    answers = [run_query(graph, q, {}, {}) for q in turns]
    # run_query returns final_answer only; capture full responses using direct invoke for logging.
    full = [graph.invoke({"query": q}) for q in turns]
    assert "grounded" in answers[0].lower()
    assert "clarify" in answers[1].lower()
    assert "cannot answer" in answers[2].lower()
    assert "cannot follow" in answers[3].lower()
    _capture_user_journey("core_user_journey", turns, full)


def test_cli_loop_follow_up_and_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    import main

    fake_graph = _FakeGraph()
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setattr(main, "get_connection", lambda **kw: object())
    monkeypatch.setattr(main, "get_structural_index", lambda _conn: {})
    monkeypatch.setattr(main, "get_compass", lambda _conn, _si: type("X", (), {"to_dict": lambda self: {"graph_profile": {}}})())
    monkeypatch.setattr(main, "build_sst_graph", lambda _conn: fake_graph)
    inputs = iter(["Why does checkout fail?", "Ambiguous scope", "exit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(inputs))
    main.main()
    out = capsys.readouterr().out
    assert "Closed Knowledge Engine" in out
    assert "Answer:" in out
    assert "Bye." in out
