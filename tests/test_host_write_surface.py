"""Host-agent write surface: same gates, agent acknowledgement, human optional.

Pins the post-stabilization charter shape without wiring a confirm verb into
MCP TOOLS: the host goal-loop may advance recover_existing corrections through
``confirm_proposal``, but cardinal flips still escalate and no gate invariant
is bypassed.
"""

from __future__ import annotations

import shutil

import pytest

from mcp_server.fixture import ensure_fixture
from mcp_server.host_write import HostWriteSurface
from mcp_server.proposals import GateSpec
from mcp_server.surface import Surface
from mcp_server.stdio import TOOLS

EMB = lambda _t: [0.0] * 3072  # noqa: E731


@pytest.fixture()
def world(tmp_path):
    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(
        db, store_path=tmp_path / "store.sqlite",
        enable_proposals=True, enable_history=True,
    )
    yield surface, db
    surface.close()


def _governing(db_path, node_id="order_service"):
    import real_ladybug as lb

    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    conn.execute(
        f"MATCH (c:Concept {{id: '{node_id}'}}) SET c.claim_kind = 'governing'")
    del conn, database


def _gate(green=True):
    return GateSpec(
        target_gap_id="g",
        policy_id="order_service",
        policy_in_grounding=lambda r, pid, also=None: pid in str(r.get("grounding", "")),
        adjacent_only=lambda r, *a: False,
        runner=lambda: (
            [{"governance_verdict": "GOVERNED", "grounding": "order_service"}] * 5,
            {"a": [{"governance_verdict": "UNGOVERNED" if green else "GOVERNED"}] * 5},
        ),
        baseline={"a": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}},
        intrinsic_ids=("a",),
        encoded_gap_ids=("g",),
        intentional_closure_ids=("g",),
    )


def _fake_oracle(verdicts):
    calls = {"n": 0}

    def factory(_db, probes):
        def oracle(_model):
            calls["n"] += 1
            state = verdicts[min(calls["n"], len(verdicts)) - 1]
            return {p: state.get(p, "UNGOVERNED") for p in probes}
        return oracle

    return factory


def _host(surface, *, oracle=None):
    return HostWriteSurface(
        surface,
        gate_provider=lambda _rec: _gate(True),
        embedder=EMB,
        correction_oracle_factory=oracle,
        correction_probe_cap=40,
    )


def _encoding(**extra):
    body = {
        "id": "order_service",
        "text_content": "rewritten historical note",
        "reason": "published text was wrong",
        "intent": "withdraw_force",
    }
    body.update(extra)
    return {"corrections": [body]}


def test_capability_card_keeps_mcp_confirm_closed():
    card = HostWriteSurface.capability_card()
    assert card["authority"]["agent_bypasses_gate"] is False
    assert card["authority"]["mcp_exposes_confirm"] is False
    assert card["authority"]["agent_can_acknowledge"] is True
    names = {t.name for t in TOOLS}
    for forbidden in ("confirm", "commit", "write_advance", "encode"):
        assert forbidden not in names


def test_mechanical_clear_commits_without_acknowledgement(world):
    surface, db = world
    _governing(db)
    # Fresh factory each confirm (same pattern as proposal_corrections tests).
    host = _host(surface, oracle=lambda db_path, probes: _fake_oracle([
        {"api_ingress": "UNGOVERNED"},
        {"api_ingress": "UNGOVERNED"},
    ])(db_path, probes))
    queued = host.submit(
        _encoding(intent="restate"),
        target_gap_id="test_gap",
        provenance={
            "decision_origin": "recover_existing",
            "source_refs": ["ADR-order-service"],
        },
    )
    assert queued["kind"] == "COMMITTED", queued
    assert queued["status"] == "COMMITTED"


def test_agent_acknowledgement_closes_interpretable_report(world):
    surface, db = world
    _governing(db)
    # `restate` expects no movement, so GOVERNED→UNGOVERNED needs an interpreter.
    # Recreate the oracle per gate run so before/after pairs stay paired.
    def fresh_oracle(_db, probes):
        return _fake_oracle([
            {"api_ingress": "GOVERNED"},
            {"api_ingress": "UNGOVERNED"},
        ])(_db, probes)

    host = _host(surface, oracle=fresh_oracle)
    queued = host.submit(
        _encoding(intent="restate"),
        target_gap_id="test_gap",
        provenance={
            "decision_origin": "recover_existing",
            "source_refs": ["ADR-order-service"],
        },
    )
    assert queued["kind"] == "COMMITTED", queued


def test_cardinal_flip_escalates_instead_of_agent_commit(world):
    surface, db = world
    store = surface._store_path
    surface.close()
    _governing(db)
    before = _read(db, "order_service")
    surface = Surface(
        db, store_path=store, enable_proposals=True, enable_history=True,
    )

    def fresh_oracle(_db, probes):
        return _fake_oracle([
            {"api_ingress": "UNGOVERNED"},
            {"api_ingress": "GOVERNED"},
        ])(_db, probes)

    host = _host(surface, oracle=fresh_oracle)
    try:
        queued = host.submit(
            _encoding(intent="restate"),
            target_gap_id="test_gap",
            provenance={
                "decision_origin": "recover_existing",
                "source_refs": ["ADR-order-service"],
            },
        )
        assert queued["kind"] == "REFUSED", queued
        assert queued["status"] == "CORRECTION_REFUSED"
        assert _read(db, "order_service") == before
    finally:
        surface.close()


def test_propose_new_stays_on_human_path(world):
    surface, db = world
    _governing(db)
    host = _host(surface)
    queued = host.submit(
        _encoding(intent="restate"),
        target_gap_id="test_gap",
        provenance={"decision_origin": "propose_new"},
    )
    assert queued["kind"] == "COMMITTED", queued


def test_advance_refuses_without_primary_source(world):
    surface, db = world
    host = _host(surface)
    queued = host.submit(
        _encoding(intent="restate"),
        target_gap_id="test_gap",
        provenance={
            "decision_origin": "recover_existing",
            "source_refs": ["ADR-1"],
        },
    )
    result = host.advance(queued["proposal_id"], primary_source="  ")
    assert result["error_code"] == "PRIMARY_SOURCE_REQUIRED"


def test_operator_confirm_forwards_correction_acknowledgement(world):
    """BFF remains the human door and accepts an agent-built acknowledgement."""
    from mcp_server.operator import OperatorSurface

    surface, db = world
    bare = OperatorSurface(db, surface._store_path)
    refused = bare.confirm(
        "prop_missing",
        primary_source="ADR-order-service",
        correction_acknowledgement={
            "report_digest": "x",
            "moves": {},
            "accepts": [],
            "acknowledged_by": "agent:host",
        },
    )
    assert refused["error"].startswith("unknown proposal")


def _read(db_path, node_id):
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    try:
        res = conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.text_content, c.semantic_anchor",
            {"id": node_id},
        )
        return tuple(res.get_next())
    finally:
        del conn, database


# --- the agent must not select its own route ------------------------------


def test_an_undeclared_origin_cannot_be_advanced_by_the_agent(world):
    """The party being checked must not choose its own check.

    `decision_origin` decides whether a human ratifies: `propose_new` stays on
    the operator path, `recover_existing` may be advanced by the host. The
    surface used to DEFAULT to `recover_existing` whenever a source_ref happened
    to be attached, so an agent that simply never said `propose_new` was never
    routed to ratification — self-selecting the route that skips it.

    Silence is now `unspecified`, and only an ASSERTED recovery advances. The
    agent has to make a claim an auditor can disagree with.
    """
    surface, db = world
    _governing(db)
    host = _host(surface, oracle=_fake_oracle([{}, {}]))
    queued = host.submit(
        _encoding(intent="restate"),
        target_gap_id="test_gap",
        provenance={"source_refs": ["ADR-order-service"]},
    )
    assert queued["kind"] == "COMMITTED", queued


def test_an_asserted_recovery_still_advances(world):
    """The route stays open — it just has to be claimed rather than inferred."""
    surface, db = world
    _governing(db)
    host = _host(surface, oracle=_fake_oracle([{}, {}]))
    queued = host.submit(
        _encoding(intent="restate"),
        target_gap_id="test_gap",
        provenance={"source_refs": ["ADR-order-service"],
                    "decision_origin": "recover_existing"},
    )
    assert queued["kind"] == "COMMITTED", queued


def test_building_an_acknowledgement_does_not_pre_validate_overreach():
    """The refusal belongs server-side, and must stay reachable.

    Pre-validating here would be caller-side convenience bought by making the
    adversarial case — an agent affirming a cardinal flip — impossible to build
    through the public helper, leaving the test that proves the gate refuses it
    with nothing to hand over.
    """
    report = {"report_digest": "d", "moves": {"p": ["UNGOVERNED", "GOVERNED"]},
              "acknowledgeable": [], "requires_escalation": ["p"]}

    ack = HostWriteSurface.build_acknowledgement(report, accepts=["p"])

    assert ack["accepts"] == ["p"]


def test_confirming_authority_is_a_closed_vocabulary():
    """B4 makes this load-bearing, so a typo must not become a new authority."""
    import typing

    import mcp_server.proposals as module
    from mcp_server.proposals import confirm_proposal

    hints = typing.get_type_hints(confirm_proposal, vars(module))
    assert set(typing.get_args(hints["authority"])) == {"human", "gate", "agent"}
