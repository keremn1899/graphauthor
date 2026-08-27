"""Operator HTTP: bearer auth, reads, and settings. Propose auto-commits elsewhere."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from starlette.testclient import TestClient  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _world(tmp_path: Path):
    from mcp_server.fixture import ensure_fixture

    db = ensure_fixture(tmp_path / "g.lbug")
    return db, tmp_path / "store.sqlite"


def _app(db, store):
    from mcp_server.operator import OperatorSurface
    from mcp_server.operator_http import build_operator_app

    op = OperatorSurface(db, store)
    return build_operator_app(op, token=TOKEN)


def test_auth_gate_401_without_bearer(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    client = TestClient(_app(db, store))
    assert client.get("/operator/health").status_code == 401
    assert client.get("/operator/health", headers=AUTH).status_code == 200


def test_reads_route(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    client = TestClient(_app(db, store))
    health = client.get("/operator/health", headers=AUTH).json()
    assert health["store_ok"] is True
    mem = client.get("/operator/memory", headers=AUTH).json()
    assert mem["pid"] > 0 and "rss_bytes" in mem
    assert client.get("/operator/proposals", headers=AUTH).status_code == 200
    assert client.get("/operator/events", headers=AUTH).status_code == 200
    assert client.get("/operator/history", headers=AUTH).status_code == 200


def test_write_loop_routes_are_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)
    client = TestClient(_app(db, store))
    assert client.post("/operator/proposals/x/confirm", headers=AUTH).status_code == 404
    assert client.post("/operator/proposals/x/reject", headers=AUTH).status_code == 404
    assert client.post("/operator/proposals/x/requeue", headers=AUTH).status_code == 404


def test_combined_app_mounts_operator_beside_mcp(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    db, store = _world(tmp_path)

    from mcp_server.http import build_asgi_app, build_operator_surface
    from mcp_server.surface import Surface

    surface = Surface(db, enable_history=True, store_path=store)
    app = build_asgi_app(surface, token=TOKEN,
                         operator=build_operator_surface(db, store))
    client = TestClient(app)

    assert client.get("/operator/health", headers=AUTH).status_code == 200
    assert client.get("/operator/health").status_code == 401
    surface.close()


def test_operator_surface_defaults_store_beside_db(tmp_path):
    from mcp_server.http import build_operator_surface

    op = build_operator_surface(tmp_path / "g.lbug", None)
    assert op._store == tmp_path / "g.store.sqlite"


def test_set_key_applies_to_env_and_clear_removes_it(tmp_path, monkeypatch):
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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SST_MCP_ACCOUNT_PATH", str(tmp_path / "acct"))
    import os

    from mcp_server.account import default_account
    from mcp_server.http import build_operator_surface

    default_account().set_key("sk-or-v1-stored")
    build_operator_surface(tmp_path / "g.lbug", tmp_path / "store.sqlite")
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-stored"
