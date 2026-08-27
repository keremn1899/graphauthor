"""Operator BFF HTTP transport smoke (B1). Deterministic; no LLM, no network.
Proves the transport concerns the surface battery can't: bearer auth (401/200),
routing to reads, and that the write loop over HTTP keeps the same
zero-authority guarantee — a gated commit succeeds, a no-gate-provider confirm
is refused with 400 before the graph is touched.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from starlette.testclient import TestClient  # noqa: E402

TOKEN = "test-token"
ENC = lambda cid: {"concepts": [{"id": cid, "label": cid, "text_content": f"{cid} body", "semantic_anchor": cid}],
                   "edges": [{"type": "CONTAINS", "source_id": "order_service", "target_id": cid, "label": "declares"}]}
EMB = lambda t: [0.0] * 3072
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _gate(green=True):
    from mcp_server.proposals import GateSpec
    c = lambda: [{"governance_verdict": "GOVERNED", "grounding": "gap_x adjudicates"}] * 3
    p = lambda: {"moat": [{"governance_verdict": "UNGOVERNED" if green else "GOVERNED"}] * 3}
    return GateSpec(target_gap_id="gap_x", policy_id="gap_x",
                    policy_in_grounding=lambda r, pid, also=None: True,
                    adjacent_only=lambda r, *a: False, runner=lambda: (c(), p()),
                    baseline={"moat": {"n": 3, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}},
                    intrinsic_ids=("moat",), encoded_gap_ids=("gap_x",),
                    intentional_closure_ids=("gap_x",), closure_runner=c, pins_runner=p)


def _world(tmp_path: Path):
    from mcp_server.fixture import ensure_fixture
    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    return db, tmp_path / "store.sqlite"


def _seed_pending(db, store, cid="c_http"):
    import json

    from interaction.write_path_store import WritePathStore
    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import new_proposal_id, validate_proposal
    from mcp_server.surface import Surface

    s = Surface(db, enable_history=True, enable_proposals=True, store_path=store)
    s.escalate(question="q", ungoverned_predicate="gap_x")
    s.close()
    encoding = ENC(cid)
    prop, err = validate_proposal(encoding, db)
    assert prop is not None, err
    pid = new_proposal_id()
    records = WritePathStore(store)
    try:
        records.save_proposal({
            "proposal_id": pid,
            "target_gap_id": "gap_x",
            "encoding_json": json.dumps(prop.model_dump()),
            "generating_task": "t",
            "source_refs": [],
            "expected_graph_version": "basis",
            "expected_graph_fingerprint": graph_fingerprint(db),
            "status": "PENDING",
        })
    finally:
        records.close()
    return pid


def _app(db, store, *, gate_provider):
    from mcp_server.operator import OperatorSurface
    from mcp_server.operator_http import build_operator_app
    op = OperatorSurface(db, store, gate_provider=gate_provider, embedder=EMB)
    return build_operator_app(op, token=TOKEN)


def test_auth_gate_401_without_bearer(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    assert client.get("/operator/health").status_code == 401
    assert client.get("/operator/health", headers=AUTH).status_code == 200


def test_reads_route(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    health = client.get("/operator/health", headers=AUTH).json()
    assert health["can_commit"] is True and health["pending_count"] == 1
    mem = client.get("/operator/memory", headers=AUTH).json()
    assert mem["pid"] > 0 and "rss_bytes" in mem
    props = client.get("/operator/proposals", headers=AUTH).json()
    assert len(props) == 1 and props[0]["status"] == "PENDING"
    esc = client.get("/operator/escalations", headers=AUTH).json()
    assert any(e.get("ungoverned_predicate") == "gap_x" for e in esc)


def test_gated_commit_over_http(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    pid = _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    r = client.post(f"/operator/proposals/{pid}/confirm", headers=AUTH,
                    json={"primary_source": "ADR-1"})
    assert r.status_code == 200 and r.json()["status"] == "COMMITTED"
    acts = client.get("/operator/activities", headers=AUTH).json()
    gaps = [a for a in acts if a["kind"] == "gap"]
    assert len(gaps) == 1 and gaps[0]["state"] == "SETTLED"
    audit = client.get(f"/operator/proposals/{pid}/audit", headers=AUTH).json()
    delta = client.get(
        "/operator/diff",
        headers=AUTH,
        params={
            "v1": audit["graph_version_before"],
            "v2": audit["graph_version_after"],
        },
    )
    assert delta.status_code == 200
    assert [row["id"] for row in delta.json()["concepts_added"]] == ["c_http"]


def test_diff_requires_two_known_versions(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    missing = client.get("/operator/diff", headers=AUTH)
    unknown = client.get(
        "/operator/diff",
        headers=AUTH,
        params={"v1": "not-a-version", "v2": "also-not-a-version"},
    )
    assert missing.status_code == 400 and "error" in missing.json()
    assert unknown.status_code == 404 and unknown.json()["kind"] == "not_found"


def test_zero_authority_confirm_refused_over_http(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    pid = _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=None))  # no gate provider
    r = client.post(f"/operator/proposals/{pid}/confirm", headers=AUTH,
                    json={"primary_source": "ADR-1"})
    assert r.status_code == 400 and "error" in r.json()
    # graph untouched: proposal still PENDING
    assert client.get(f"/operator/proposals/{pid}", headers=AUTH).json()["status"] == "PENDING"


def test_lineage_over_http(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    pid = _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    client.post(f"/operator/proposals/{pid}/confirm", headers=AUTH, json={"primary_source": "ADR-1"})
    lin = client.get("/operator/lineage/c_http", headers=AUTH).json()
    assert lin["origin"] == "evolution"
    assert lin["recorded"]["primary_source"] == "ADR-1"
    assert lin["recorded"]["authority_type"] == "human"


def test_lineage_refuses_a_node_that_does_not_exist(tmp_path, monkeypatch):
    """The lineage projection must not fabricate records for unknown ids."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    r = client.get("/operator/lineage/no_such_node_at_all", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["error"] == "unknown node"
    assert r.json()["kind"] == "not_found"


def test_materialized_node_without_proposal_is_honestly_unprovenanced(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    lin = client.get("/operator/lineage/order_service", headers=AUTH).json()
    assert lin["origin"] == "unprovenanced"
    assert "no commit event" in lin["derived"]


def test_absence_disposition_over_http(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    # advisory prior, never hides
    prior = client.get("/operator/absence/classify", headers=AUTH,
                       params={"predicate": "which retry backoff constant to use"}).json()
    assert prior["advisory"] is True and "signals" in prior
    # sourced dismissal accepted; unsourced refused (process cardinal)
    good = client.post("/operator/absence/dispose", headers=AUTH,
                       json={"predicate": "retry backoff", "category": "local_choice",
                             "primary_source": "ADR-7"})
    bad = client.post("/operator/absence/dispose", headers=AUTH,
                      json={"predicate": "retry backoff", "category": "local_choice"})
    assert good.status_code == 200 and good.json()["category"] == "local_choice"
    assert bad.status_code == 400 and "error" in bad.json()


def test_reject_over_http(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    pid = _seed_pending(db, store)
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    r = client.post(f"/operator/proposals/{pid}/reject", headers=AUTH, json={"reason": "dup"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"


def test_escalation_does_not_mint_an_activity(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    from mcp_server.surface import Surface

    surface = Surface(db, enable_history=True, enable_proposals=True, store_path=store)
    surface.escalate(question="q", ungoverned_predicate="gap_x")
    surface.close()
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    handoffs = client.get("/operator/escalations", headers=AUTH).json()
    assert handoffs and handoffs[0]["handoff_id"]
    activities = client.get("/operator/activities", headers=AUTH).json()
    assert activities == []


def test_incident_events_do_not_mint_an_activity(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    from interaction.event_log import EventStore

    events = EventStore(store)
    events.emit(
        type="system.fault", case_id="case_7", actor="engine",
        authority_type="system", reason="index unavailable")
    events.close()
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    assert client.get("/operator/activities", headers=AUTH).json() == []
    result = client.post(
        "/operator/incidents/case_7/acknowledge",
        headers=AUTH,
        json={"note": "investigated"},
    )
    assert result.status_code == 404


def test_rationalization_events_do_not_mint_an_activity(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    from interaction.event_log import EventStore

    events = EventStore(store)
    events.emit(
        type="rationalization.flagged", actor="gate", authority_type="gate",
        payload={"rule_id": "rule_1", "artifact_path": "src/a.py"})
    events.close()
    client = TestClient(_app(db, store, gate_provider=lambda rec: _gate(True)))
    assert client.get("/operator/activities", headers=AUTH).json() == []


def test_combined_app_mounts_operator_beside_mcp(tmp_path, monkeypatch):
    """`build_asgi_app(..., operator=...)` serves the human plane at /operator
    under the same bearer gate as /mcp. This is the shape `main --operator`
    builds — without it there is no local server for the UI to talk to."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)

    from mcp_server.http import build_asgi_app, build_operator_surface
    from mcp_server.surface import Surface

    surface = Surface(db, enable_history=True, store_path=store)
    app = build_asgi_app(surface, token=TOKEN,
                         operator=build_operator_surface(db, store))
    client = TestClient(app)

    assert client.get("/operator/health", headers=AUTH).status_code == 200
    assert client.get("/operator/health").status_code == 401  # gate covers it
    surface.close()


def test_operator_surface_defaults_store_beside_db(tmp_path):
    """No SST_MCP_STORE_PATH → the store sits beside the .lbug, so a bare
    `SST_DB_PATH=... main --operator` is a complete local setup."""
    from mcp_server.http import build_operator_surface

    op = build_operator_surface(tmp_path / "g.lbug", None)
    assert op._store == tmp_path / "g.store.sqlite"


def test_normal_server_can_load_a_server_owned_gate_module(tmp_path, monkeypatch):
    """The standard local entry point can complete confirmation when its owner
    pins a battery. The module remains server configuration, never request
    data supplied by the browser."""
    import sys
    import types

    from mcp_server.http import build_operator_surface

    expected = object()
    module = types.ModuleType("test_declared_gate")
    module.build_gate_for = lambda db, proposal, store_path=None: expected
    monkeypatch.setitem(sys.modules, module.__name__, module)

    op = build_operator_surface(
        tmp_path / "g.lbug",
        tmp_path / "store.sqlite",
        gate_module=module.__name__,
    )
    assert op.health()["can_commit"] is True
    assert op._gate_provider({"proposal_id": "p"}) is expected


def test_set_key_applies_to_env_and_clear_removes_it(tmp_path, monkeypatch):
    """A stored BYO key must reach the environment, or derive/construct fail at
    the model call with a key that the operator believes is set. Clearing must
    also drop it, or a 'cleared' key keeps working until restart."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SST_MCP_ACCOUNT_PATH", str(tmp_path / "acct"))
    import os

    from mcp_server.operator import OperatorSurface

    op = OperatorSurface(tmp_path / "g.lbug", tmp_path / "store.sqlite")
    assert op.set_key("sk-or-v1-testkey", validate=False)["set"] is True
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-testkey"

    op.clear_key()
    assert "OPENROUTER_API_KEY" not in os.environ


def test_operator_surface_picks_up_stored_key(tmp_path, monkeypatch):
    """`main --operator` boots with the operator's own credential applied."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SST_MCP_ACCOUNT_PATH", str(tmp_path / "acct"))
    import os

    from mcp_server.account import default_account
    from mcp_server.http import build_operator_surface

    default_account().set_key("sk-or-v1-stored")
    build_operator_surface(tmp_path / "g.lbug", tmp_path / "store.sqlite")
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-stored"
