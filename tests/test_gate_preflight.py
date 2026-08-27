"""The encode gate, run before a human spends a confirm (C2, second half).

Shape and grain can be checked without encoding. Closure and distractors cannot:
they measure what the graph *answers* once the proposal is in it. So the gate was
left to operator confirm, and the cost of a bad encoding fell on the wrong party
— the agent submits, a human supplies a PrimarySource, and only then does the
gate go red.

The preflight encodes into a throwaway copy and runs the identical battery
there. These tests are about the three things that make that trustworthy: it
predicts the real outcome, it does not touch the live graph, and it grants no
authority.

Deterministic: stub embedder, injected gate rows, no LLM.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.http import GateProvider  # noqa: E402
from mcp_server.proposals import GateSpec  # noqa: E402

EMB = lambda t: [0.0] * 3072  # noqa: E731

ENCODING = {
    "concepts": [{"id": "replay_port", "label": "ReplayPort",
                  "text_content": "Inbound port accepting replay requests for "
                                  "dead-lettered deliveries.",
                  "semantic_anchor": "replay port"}],
    "edges": [],
}


def _battery(green: bool):
    """A build_gate_for(db, proposal, store_path=...) that passes or fails.

    Rows are injected rather than measured: what is under test is whether the
    preflight runs the battery against the copy and reports its verdict
    faithfully, not whether the engine agrees about any particular graph.
    """
    def closure():
        return [{"governance_verdict": "GOVERNED",
                 "grounding": "auto_probe adjudicates"}] * 3

    def pins():
        return {"moat": [{"governance_verdict":
                          "UNGOVERNED" if green else "GOVERNED"}] * 3}

    def build_gate_for(db_path, proposal, store_path=None):
        return GateSpec(
            target_gap_id="x", policy_id="auto_probe",
            policy_in_grounding=lambda r, pid, also=None: True,
            adjacent_only=lambda r, *a: False,
            runner=lambda: (closure(), pins()),
            baseline={"moat": {"n": 3, "GOVERNED": 0.0,
                               "UNGOVERNED": 1.0, "ABSENT": 0.0}},
            intrinsic_ids=("moat",), encoded_gap_ids=("x",),
            intentional_closure_ids=("x",),
            closure_runner=closure, pins_runner=pins,
        )

    return build_gate_for


def _surface(tmp_path, *, green: bool | None = True):
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    store = tmp_path / "store.sqlite"
    provider = (None if green is None
                else GateProvider(_battery(green), db, store))
    surface = Surface(db, store_path=store, enable_proposals=True,
                      gate_provider=provider)
    surface._preflight_embedder = EMB
    return surface, db


def _preflight(surface, gap="x"):
    return surface.propose(encoding=ENCODING, target_gap_id=gap,
                           dry_run=True, check_gate=True)


def test_a_green_gate_is_predicted_green(tmp_path):
    surface, _db = _surface(tmp_path, green=True)
    try:
        out = _preflight(surface)
    finally:
        surface.close()

    assert out.get("gate_checked") is True, out
    report = out["gate_preflight"]
    assert report["ran"] is True, report
    assert report["would_pass"] is True, report
    assert not out.get("error"), out["error"]


def test_a_red_gate_is_caught_before_a_human_is_spent(tmp_path):
    """The whole point. A distractor regression must surface here, not at confirm."""
    surface, _db = _surface(tmp_path, green=False)
    try:
        out = _preflight(surface)
    finally:
        surface.close()

    report = out["gate_preflight"]
    assert report["ran"] is True, report
    assert report["would_pass"] is False, report
    assert out.get("error"), "a gate that would fail must be reported as an error"
    assert "WOULD FAIL" in out.get("note", "")


def test_the_live_graph_is_untouched_by_either_outcome(tmp_path):
    """A preflight that mutated the real graph — even transiently, even with a
    restore — would be a write on the read plane.

    Compared by content manifest rather than by file digest. The bytes of a
    `.lbug` are not stable under a no-op: LadybugDB checkpoints on open and on
    close, so a digest changes when nothing logical has. The manifest is the
    claim being made, and it is the same comparison `confirm_proposal` uses to
    assert its own restore was clean.
    """
    from mcp_server.history import extract_manifest

    for green in (True, False):
        room = tmp_path / f"green_{green}"
        room.mkdir()
        surface, db = _surface(room, green=green)
        surface.orient()                      # open before measuring
        before = extract_manifest(db)
        try:
            _preflight(surface)
            after = extract_manifest(db)
        finally:
            surface.close()
        assert after == before, (
            f"the live graph's content changed during a preflight (green={green})")


def test_a_preflight_queues_nothing(tmp_path):
    """A preflight that left a record would fill the operator's inbox with
    unreviewed attempts — the queue it exists to keep clean."""
    surface, _db = _surface(tmp_path, green=True)
    try:
        _preflight(surface)
        pending = surface._get_store().list_proposals()
    finally:
        surface.close()
    assert pending == [], f"the preflight queued something: {pending}"


def test_without_a_battery_the_preflight_refuses_honestly(tmp_path):
    """Silence would read as a pass. `gate_checked` must stay false and say why."""
    surface, _db = _surface(tmp_path, green=None)
    try:
        out = _preflight(surface)
    finally:
        surface.close()

    assert out.get("gate_checked") is False, out
    assert out["gate_preflight"]["ran"] is False
    assert out["gate_preflight"]["reason"], "a refusal must carry a reason"
    assert "did not run" in out.get("note", "")


def test_the_cheap_preflight_stays_cheap(tmp_path):
    """`check_gate` is opt-in: a plain dry run must not run a battery."""
    ran: list[bool] = []
    surface, _db = _surface(tmp_path, green=True)
    original = surface._gate_preflight

    def _spy(*a, **k):
        ran.append(True)
        return original(*a, **k)

    surface._gate_preflight = _spy
    try:
        out = surface.propose(encoding=ENCODING, target_gap_id="x", dry_run=True)
    finally:
        surface.close()

    assert not ran, "a plain dry run ran the gate battery"
    assert out.get("gate_checked") is False


def test_the_preflight_predicts_what_the_real_confirm_does(tmp_path):
    """The claim that makes this worth having.

    `would_pass` is only useful if it agrees with the confirm it is predicting.
    Anything less — a heuristic, a partial battery, a shape check dressed up as
    a gate — would be worse than no preflight at all, because an agent would
    act on it.

    So: preflight the proposal, then propose the same encoding against the
    live graph with the same battery, and require the two verdicts to agree.
    """

    for green, expected in ((True, "COMMITTED"), (False, "GATE_FAILED")):
        room = tmp_path / f"predict_{green}"
        room.mkdir()
        surface, db = _surface(room, green=green)
        try:
            predicted = _preflight(surface)["gate_preflight"]

            actual = surface.propose(encoding=ENCODING, target_gap_id="x")
        finally:
            surface.close()

        assert predicted["would_pass"] is (expected == "COMMITTED"), predicted
        assert actual.get("status") == expected, actual
        assert predicted["would_pass"] is (actual.get("status") == "COMMITTED"), (
            f"preflight said would_pass={predicted['would_pass']} but propose "
            f"returned {actual.get('status')}")
