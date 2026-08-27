"""M7 HTTP transport tests — auth unit level + one live loopback round-trip.

The executable source of truth is scripts/run_m7_battery.py (M7_PASS 16/16);
these keep the auth invariants and the thread-safety fix in the pytest loop.
"""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from mcp_server.http import _authorized, serve_in_thread, token_required_to_start


def _h(value: str | None):
    return [(b"authorization", value.encode())] if value is not None else []


def test_authorized_semantics():
    tok = "secret-token-value"
    assert _authorized(_h(f"Bearer {tok}"), tok)
    assert not _authorized(_h("Bearer wrong"), tok)
    assert not _authorized(_h(tok), tok)          # missing scheme
    assert not _authorized(_h(f"bearer {tok}"), tok)  # scheme is case-sensitive by policy
    assert not _authorized([], tok)
    # explicit-insecure mode: no token configured → everything authorized
    assert _authorized([], None)


def test_secure_default_requires_token():
    assert token_required_to_start(env={}) is True
    assert token_required_to_start(env={"SST_MCP_ALLOW_INSECURE": "1"}) is False
    assert token_required_to_start(env={"SST_MCP_ALLOW_INSECURE": "0"}) is True


def test_loopback_roundtrip_and_cross_thread_store(tmp_path):
    """One authenticated orient + one store-writing call over HTTP, then a
    MAIN-thread close — the exact sequence that crashed the thread-affine
    store (M7). `escalate` was the writing verb until the governance surface
    was removed; `propose` is this surface's write path and exercises the same
    thread boundary."""
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(db, store_path=str(tmp_path / "store"), enable_proposals=True)
    base, shutdown = serve_in_thread(surface, token="tok-abc")
    try:
        async def _go():
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(base + "/mcp", headers={"Authorization": "Bearer tok-abc"}) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    o = json.loads((await s.call_tool("orient", {})).content[0].text)
                    e = json.loads((await s.call_tool("propose", {
                        "encoding": {"concepts": [
                            {"id": "probe", "label": "P", "text_content": "t"}]},
                        "target_gap_id": "m7_probe",
                        "expected_graph_version": o["graph_version"],
                    })).content[0].text)
                    return o, e

        o, e = asyncio.run(_go())
        assert o["node_count"] == 30 and o["contract_version"] == "mcp-v0"
        assert e["proposal_id"]  # written from the server thread
    finally:
        shutdown()
        surface.close()  # main thread — must not raise sqlite thread-affinity


def test_unauthenticated_rejected_before_session(tmp_path):
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(db)
    base, shutdown = serve_in_thread(surface, token="tok-abc")
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(base + "/mcp", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 401
    finally:
        shutdown()
        surface.close()
