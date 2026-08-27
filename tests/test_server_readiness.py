"""Server-readiness regression tests.

Covers four defects found in the pre-MCP audit (branch opus/server-readiness):

1. ``sys.exit(1)`` in the seed path could kill the whole process from library
   code (a Planner Zone-2 lookup on an empty DB without an API key was fatal).
2. ``get_connection`` silently auto-seeded a *default demo corpus* at any
   empty/wrong path — the ops-level twin of false-GOVERNED. Now a typed
   refusal (``EmptyGraphError``) unless explicitly opted in.
3. ``check_distractors`` silently skipped pinned queries with no post rows —
   an encode that makes an anchor *crash* (rather than flip) passed the gate.
4. ``EngineAdapter`` used ``signal.SIGALRM`` for timeouts — main-thread-only,
   one alarm per process, unusable under any concurrent server.
"""

from __future__ import annotations

import threading
import time

import pytest


# ---------------------------------------------------------------------------
# 1 + 2: connection open on an empty DB is a typed refusal, never process death
# ---------------------------------------------------------------------------


def _fresh_engine(monkeypatch, tmp_path):
    import engine

    engine.reset_connection()
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SST_AUTO_SEED", raising=False)
    monkeypatch.setenv("SST_DB_PATH", str(tmp_path / "empty_graph.lbug"))
    return engine


def test_empty_db_refuses_instead_of_seeding_default_corpus(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with pytest.raises(engine.EmptyGraphError):
        engine.get_connection()
    # The refusal must not cache a half-open connection to an empty graph.
    with pytest.raises(engine.EmptyGraphError):
        engine.get_connection()
    engine.reset_connection()


def test_opted_in_seed_failure_is_typed_not_system_exit(monkeypatch, tmp_path):
    """With auto_seed=True but no API key, seeding fails as SeedingError —
    never SystemExit — and leaves no cached connection behind."""
    engine = _fresh_engine(monkeypatch, tmp_path)
    with pytest.raises(engine.SeedingError):
        engine.get_connection(auto_seed=True)
    # State must be reset so a later call re-evaluates rather than silently
    # returning a connection to an unseeded graph.
    with pytest.raises(engine.EmptyGraphError):
        engine.get_connection()
    engine.reset_connection()


def test_env_var_opt_in_reaches_seed_path(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setenv("SST_AUTO_SEED", "1")
    # No API key: the seed path is entered (proving the env opt-in works) and
    # fails as a typed, pre-mutation error.
    with pytest.raises(engine.SeedingError):
        engine.get_connection()
    engine.reset_connection()




# ---------------------------------------------------------------------------
# 3: gate coverage — crashed/missing pinned queries block
# ---------------------------------------------------------------------------


def _rows(verdict: str, n: int = 5) -> list[dict]:
    return [{"governance_verdict": verdict} for _ in range(n)]


def test_gate_blocks_when_pinned_anchor_produces_no_rows():
    from write_path.distractor import check_distractors

    baseline = {
        "anchor_governed": {"n": 5, "GOVERNED": 1.0, "UNGOVERNED": 0.0, "ABSENT": 0.0},
        "moat_intrinsic": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0},
    }
    post = {
        # anchor_governed crashed post-encode: no rows at all.
        "moat_intrinsic": _rows("UNGOVERNED"),
    }
    clean, findings = check_distractors(
        baseline,
        post,
        encoded_gap_ids=["gap_target"],
        gap_anchor_ids=("moat_intrinsic",),
        flaky_anchor_ids=(),
        intentional_closure_ids=("gap_target",),
        intrinsic_ids=("moat_intrinsic",),
    )
    assert clean is False
    kinds = {f.query_id: f.kind for f in findings}
    assert kinds.get("anchor_governed") == "anchor_unanswerable"


def test_gate_missing_flaky_anchor_is_advisory_only():
    from write_path.distractor import check_distractors

    baseline = {"flaky_pin": {"n": 5, "GOVERNED": 0.4, "UNGOVERNED": 0.6, "ABSENT": 0.0}}
    post: dict = {}
    clean, findings = check_distractors(
        baseline,
        post,
        encoded_gap_ids=[],
        gap_anchor_ids=(),
        flaky_anchor_ids=("flaky_pin",),
        intentional_closure_ids=(),
        intrinsic_ids=(),
    )
    assert clean is True
    assert any(f.kind == "anchor_unanswerable" and f.flaky_only for f in findings)


def test_gate_clean_run_stays_clean():
    from write_path.distractor import check_distractors

    baseline = {
        "anchor_governed": {"n": 5, "GOVERNED": 1.0, "UNGOVERNED": 0.0, "ABSENT": 0.0},
        "moat_intrinsic": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0},
    }
    post = {
        "anchor_governed": _rows("GOVERNED"),
        "moat_intrinsic": _rows("UNGOVERNED"),
        "gap_target": _rows("GOVERNED"),
    }
    clean, findings = check_distractors(
        baseline,
        post,
        encoded_gap_ids=["gap_target"],
        gap_anchor_ids=("moat_intrinsic",),
        flaky_anchor_ids=(),
        intentional_closure_ids=("gap_target",),
        intrinsic_ids=("moat_intrinsic",),
    )
    assert clean is True
    assert not [f for f in findings if not f.flaky_only]


# ---------------------------------------------------------------------------
# 4: adapter deadline is thread-safe and works off the main thread
# ---------------------------------------------------------------------------


class _SlowGraph:
    def invoke(self, state, config=None):
        time.sleep(3)
        return {"confirmation_response": {}, "final_answer": "late"}


class _FastGraph:
    def invoke(self, state, config=None):
        return {
            "confirmation_response": {"governance_verdict": "UNGOVERNED"},
            "final_answer": "fast",
        }


def _make_adapter(graph, timeout_s: int):
    from interaction.engine_adapter import EngineAdapter

    return EngineAdapter(
        graph,
        compass={},
        structural_index={},
        query_frame="{q}",
        timeout_s=timeout_s,
    )


def test_timeout_returns_absent_verdict_from_worker_thread():
    """SIGALRM only worked on the main thread; the deadline must not."""
    adapter = _make_adapter(_SlowGraph(), timeout_s=1)
    out: dict = {}

    def _run():
        out["verdict"] = adapter.query("is this governed?")

    t = threading.Thread(target=_run)
    t.start()
    t.join(10)
    assert not t.is_alive()
    verdict = out["verdict"]
    assert verdict.engine_verdict == "TIMEOUT"
    assert verdict.status.value.upper() == "ABSENT"


def test_concurrent_queries_each_get_correct_outcome():
    """One slow (times out) + one fast (completes) in parallel — impossible
    under a single process-wide alarm."""
    slow = _make_adapter(_SlowGraph(), timeout_s=1)
    fast = _make_adapter(_FastGraph(), timeout_s=5)
    results: dict = {}

    def _slow():
        results["slow"] = slow.query("slow question")

    def _fast():
        results["fast"] = fast.query("fast question")

    ts = [threading.Thread(target=_slow), threading.Thread(target=_fast)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert results["slow"].engine_verdict == "TIMEOUT"
    assert results["fast"].engine_verdict != "TIMEOUT"


def test_engine_error_surfaces_in_callers_frame():
    class _BrokenGraph:
        def invoke(self, state, config=None):
            raise ValueError("boom")

    adapter = _make_adapter(_BrokenGraph(), timeout_s=5)
    with pytest.raises(ValueError, match="boom"):
        adapter.query("q")
