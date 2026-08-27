"""Trajectories, not decisions. What only shows up when the agent runs.

Marked `integration`: the model spends tokens each turn. The engine does not —
these scenarios stay on the zero-LLM verbs, so a session is a handful of model
calls and some database reads.

The structural tests below the fixture run everywhere and catch the cheap
failure: a dispatcher that cannot reach the surface at all.
"""

from __future__ import annotations

import os
import shutil

import pytest

from tests.agent_multi_turn import MAX_TURNS, Trajectory, run_session


@pytest.fixture
def surface(tmp_path):
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    s = Surface(db, store_path=tmp_path / "store.sqlite", enable_proposals=True,
                enable_history=True)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def chat():
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    from tests.agent_comprehension import openrouter_chat

    return openrouter_chat()


def _report(traj: Trajectory) -> str:
    lines = [f"  turns={len(traj.turns)} stopped={traj.stopped}"]
    for t in traj.turns:
        lines.append(f"    {t.tool}({list(t.arguments)}) -> "
                     f"{'ERROR: ' + t.error if t.error else 'ok'}")
    return "\n".join(lines)


# ------------------------------------------------------------- offline shape


def test_the_dispatcher_reaches_the_real_surface(surface):
    """No model needed: the wiring must work, or every trajectory below is
    measuring the harness."""
    from tests.agent_multi_turn import _dispatch

    out = _dispatch(surface, "orient", {})
    assert out.get("node_count", 0) > 0
    assert "capabilities" in out

    unknown = _dispatch(surface, "not_a_tool", {})
    assert "error" in unknown, "an unknown verb must come back as a readable error"


def test_a_bad_argument_returns_an_error_the_agent_can_read(surface):
    """A real client sees argument errors and adapts. If the dispatcher raised
    instead, the trajectory would end and look like a decision to stop."""
    from tests.agent_multi_turn import _dispatch

    out = _dispatch(surface, "proposal_status", {"proposal_id": "nope"})
    assert isinstance(out, dict)
    assert out.get("error") or out.get("status") in (None, "", "UNKNOWN")


# ---------------------------------------------------------------- live loops


@pytest.mark.integration
def test_the_agent_stops_instead_of_looping(surface, chat):
    """The failure single-shot cannot see. An agent that never stops against a
    governance surface is worse than one that refuses: it looks like progress."""
    traj = run_session(
        surface,
        "Find out what this graph is about, then stop and report. Do not make "
        "any changes.",
        chat,
    )
    assert traj.stopped, f"never stopped within {MAX_TURNS} turns:\n{_report(traj)}"
    assert not traj.repeated_calls, (
        f"repeated an identical call:\n{_report(traj)}\n  {traj.repeated_calls}")


@pytest.mark.integration
def test_orientation_comes_before_action(surface, chat):
    """`orient` is zero-LLM and carries capabilities, posture and grain. An
    agent that proposes before reading it is authoring blind."""
    traj = run_session(
        surface,
        "You have been asked to add a rule to this graph. Orient yourself "
        "first, then take the appropriate next step.",
        chat,
    )
    orient_at = traj.first_index("orient")
    propose_at = traj.first_index("propose")
    assert orient_at != -1, f"never oriented:\n{_report(traj)}"
    if propose_at != -1:
        assert orient_at < propose_at, (
            f"proposed before orienting:\n{_report(traj)}")


@pytest.mark.integration
def test_the_authoring_loop_runs_end_to_end(surface, chat):
    """coverage -> propose -> proposal_status, against the real surface.

    This is the loop the product is defined by, and no single-shot case can
    show it holding together: `propose` requires a `target_gap_id` that only
    `coverage` supplies, and `proposal_status` needs an id only `propose`
    returns.
    """
    traj = run_session(
        surface,
        "This graph is missing a rule limiting outbound HTTP retries to three "
        "attempts. Find what gaps have been recorded, then submit a proposal "
        "for the retry rule, then check that it was committed. Then stop.",
        chat,
    )
    assert traj.stopped, f"never stopped:\n{_report(traj)}"
    assert "propose" in traj.verbs, f"never proposed:\n{_report(traj)}"

    proposed = [t for t in traj.turns if t.tool == "propose"]
    committed = [t for t in proposed if t.result.get("status") == "COMMITTED"]
    assert committed, (
        f"no proposal was accepted by the real surface:\n{_report(traj)}\n"
        f"  errors: {[t.error for t in proposed if t.error]}")


@pytest.mark.integration
def test_the_agent_recovers_from_a_refusal(surface, chat):
    """`propose` refuses without `target_gap_id`. An agent that gets a typed
    error should read it and fix the call — not repeat it, and not give up.

    This is the one behaviour that is invisible to every single-shot case: the
    surface's error messages are only useful if they change the next turn.
    """
    traj = run_session(
        surface,
        "Submit a proposal adding a rule: outbound HTTP calls must retry at "
        "most three times. If a call is refused, read the error and try again "
        "correctly. Stop once it is committed or you cannot proceed.",
        chat,
    )
    proposed = [t for t in traj.turns if t.tool == "propose"]
    if any(t.error for t in proposed):
        assert any(not t.error for t in proposed), (
            f"was refused and never recovered:\n{_report(traj)}")
    assert not traj.repeated_calls, (
        f"repeated an identical refused call:\n{_report(traj)}")
