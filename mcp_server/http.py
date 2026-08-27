"""MCP streamable-HTTP transport — the same Surface, remotely (L2-2 / M7).

Design (contract §1 + ladder-two charter): one process = one graph = one
token audience. The transport adds NOTHING to the contract — it serves the
identical `build_server(surface)` the stdio transport serves, behind bearer
auth. Single-tenant by construction; multi-tenancy is explicitly out of
scope (its own charter).

Security posture:
- The server REFUSES TO START without `SST_MCP_TOKEN` unless
  `SST_MCP_ALLOW_INSECURE=1` (loopback development only). Secure by default.
- Bearer comparison is constant-time (`hmac.compare_digest`).
- Unauthenticated requests receive 401 before any session handling.

Run:
    SST_DB_PATH=/path/graph.lbug SST_MCP_TOKEN=$(openssl rand -hex 24) \
        python -m mcp_server.http --host 0.0.0.0 --port 8137
Env (in addition to the stdio server's): SST_MCP_TOKEN, SST_MCP_ALLOW_INSECURE.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import os
import threading
from pathlib import Path
from typing import Any

from mcp_server.stdio import build_server
from mcp_server.surface import Surface


def token_required_to_start(env: dict[str, str] | None = None) -> bool:
    """Secure default: no token, no server — unless explicitly insecure."""
    e = os.environ if env is None else env
    return str(e.get("SST_MCP_ALLOW_INSECURE", "")).strip().lower() not in ("1", "true", "yes")


def _authorized(headers: list[tuple[bytes, bytes]], token: str | None) -> bool:
    if not token:
        return True  # insecure mode was explicitly opted into at startup
    supplied = ""
    for k, v in headers:
        if k.lower() == b"authorization":
            supplied = v.decode("latin-1")
            break
    prefix = "Bearer "
    if not supplied.startswith(prefix):
        return False
    return hmac.compare_digest(supplied[len(prefix):], token)


def build_asgi_app(
    surface: Surface,
    *,
    token: str | None,
    transcript_path: str | None = None,
    operator: Any | None = None,
    graph_library_dirs: list[Path | str] | tuple[Path | str, ...] | None = None,
    graph_output_roots: list[Path | str] | tuple[Path | str, ...] | None = None,
    workspace_owner: Any | None = None,
):
    """Starlette app: bearer-auth gate → StreamableHTTPSessionManager → Server.

    When an `OperatorSurface` is supplied, the human plane mounts at `/operator`
    beside the agent plane at `/mcp` — same process, same graph owner, same
    bearer gate (contract §1: one process = one graph = one token audience). The
    operator's `reload_hook` is wired to the surface so a commit refreshes the
    engine's view (single-owner DB)."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount

    server = build_server(surface, transcript_path=transcript_path)
    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)

    async def _mcp_endpoint(scope, receive, send):
        if scope["type"] != "http":
            await send({"type": "http.response.start", "status": 400, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        try:
            async with manager.run():
                yield
        finally:
            if workspace_owner is not None:
                workspace_owner.close()

    routes = [Mount("/mcp", app=_mcp_endpoint)]
    if operator is not None:
        from mcp_server.coordination import RWLock
        from mcp_server.operator_http import operator_routes

        if getattr(operator, "_reload_hook", None) is None:
            operator._reload_hook = surface.reload  # commit → engine refreshes
        # Single-owner coordination (B13): one shared RW lock across both planes —
        # invokes read-share it, a confirm write-excludes them.
        shared = workspace_owner.lock if workspace_owner is not None else RWLock()
        surface._rw_lock = shared
        operator._rw_lock = shared
        routes.append(Mount("/operator", routes=operator_routes(operator)))

        # `/graph` — read-only map plane for the canvas. Same gate, no authority;
        # it browses the graph this process already owns rather than governing it.
        from mcp_server.graph_http import GraphCatalogue, graph_routes

        routes.append(Mount("/graph", routes=graph_routes(
            GraphCatalogue(
                getattr(operator, "_db", None) or surface._db_path,
                library_dirs=graph_library_dirs,
                output_roots=graph_output_roots,
                on_activate=workspace_owner.activate if workspace_owner is not None else None,
                rw_lock=shared,
            ),
            current_surface=surface,
            # Same single-owner lock as the other two planes: the canvas reads
            # the very file a confirm rewrites.
            rw_lock=shared,
        )))
    inner = Starlette(routes=routes, lifespan=_lifespan)

    async def _auth_gate(scope, receive, send):
        """Auth BEFORE routing: Starlette's Mount 307-redirects /mcp → /mcp/
        ahead of any endpoint code (M7 test finding), so the bearer check must
        wrap the whole app — every path, including redirects, gates at 401."""
        if scope["type"] == "http" and not _authorized(scope.get("headers") or [], token):
            resp = Response("unauthorized", status_code=401)
            await resp(scope, receive, send)
            return
        await inner(scope, receive, send)

    return _auth_gate


def serve_in_thread(
    surface: Surface,
    *,
    token: str | None,
    transcript_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[str, Any]:
    """Run the transport in a background thread (batteries / embedding).
    Returns (base_url, shutdown_fn)."""
    import socket
    import time

    import uvicorn

    if port == 0:
        with socket.socket() as s:
            s.bind((host, 0))
            port = s.getsockname()[1]

    app = build_asgi_app(surface, token=token, transcript_path=transcript_path)
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="sst-mcp-http")
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("HTTP transport failed to start within 10s")

    def _shutdown() -> None:
        server.should_exit = True
        thread.join(10)

    return f"http://{host}:{port}", _shutdown


def _env_flag(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def _load_gate_provider(
    module_ref: str,
    *,
    db_path: Path,
    store_path: Path,
):
    """Load the server-owned proposal battery.

    ``module_ref`` may be an import name or a path to a Python module. The
    browser never sees or chooses it: changing the battery requires changing
    server configuration and restarting the owner process.
    """
    import importlib
    import importlib.util

    ref = str(module_ref or "").strip()
    if not ref:
        return None
    candidate = Path(ref).expanduser()
    if candidate.suffix == ".py" or candidate.exists():
        path = candidate.resolve()
        if not path.is_file():
            raise RuntimeError(f"gate module is not a file: {path}")
        name = f"_graphauthor_gate_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load gate module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(ref)
    builder = getattr(module, "build_gate_for", None)
    if not callable(builder):
        raise RuntimeError("gate module must expose build_gate_for(db_path, proposal, store_path=...)")

    return GateProvider(builder, db_path, store_path)


class GateProvider:
    """The configured battery, bound to a graph — and re-bindable to another.

    A plain closure over one `db_path` was enough while the gate only ever ran
    at confirm time. The preflight runs the *same* battery against a throwaway
    copy of the graph, so the binding has to be movable: an approximation of the
    gate would be worse than no preflight, because an agent would trust it.
    """

    def __init__(self, builder, db_path: Path, store_path: Path) -> None:
        self._builder = builder
        self._db_path = Path(db_path)
        self._store_path = Path(store_path)

    def __call__(self, proposal):
        return self._builder(self._db_path, proposal, store_path=self._store_path)

    def rebind(self, db_path: Path | str, store_path: Path | str) -> "GateProvider":
        return GateProvider(self._builder, Path(db_path), Path(store_path))


def _default_graph_library_dirs(db_path: Path | str) -> list[Path]:
    """Curated local library for the product entry screen.

    Directories are shallow-scanned. Snapshot directories and large experiment
    trees therefore never flood the catalogue — `data/benchmarks/musique_graphs`
    alone holds over a hundred harness fixtures, which are not graphs anyone
    means to open. Deployments can replace these defaults with
    ``SST_MCP_GRAPH_LIBRARY`` (``os.pathsep`` separated).

    Output the *product itself* wrote is a different question, answered by
    `_default_graph_construction_roots`.
    """
    configured = os.environ.get("SST_MCP_GRAPH_LIBRARY", "").strip()
    if configured:
        return [Path(p).expanduser() for p in configured.split(os.pathsep) if p.strip()]

    project = Path(__file__).resolve().parent.parent
    candidates = [project / "data" / "demo"]
    out: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and resolved not in out:
            out.append(resolved)
    return out


def _default_graph_construction_roots(db_path: Path | str) -> list[Path]:
    """Trees the product writes constructed graphs into, walked in full.

    A shallow scan of `construction_runs/graphs` was hiding real work. Measured
    on this repository: 15 constructed graphs on disk, 5 of them visible. The
    rest sat one directory too deep — per-trial workspaces holding a `graph.lbug`
    each, and, most tellingly, `construction_runs/graphs/graphs/`, which is the
    exact drift `OperatorSurface.default_construction_out` documents itself as
    preventing. It happened anyway, and the graph it produced carries a recorded
    construction origin, so the product built it, logged it, and then could not
    show it to the person who asked for it.

    Depth is bounded and snapshot directories are skipped, so this stays a scan
    of *outputs* rather than a crawl of everything under `data`. Configurable
    with ``SST_MCP_GRAPH_OUTPUTS`` (``os.pathsep`` separated).
    """
    configured = os.environ.get("SST_MCP_GRAPH_OUTPUTS", "").strip()
    if configured:
        return [Path(p).expanduser() for p in configured.split(os.pathsep) if p.strip()]

    project = Path(__file__).resolve().parent.parent
    data = project / "data"
    candidates = [
        data / "demo",
    ]
    out: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and resolved not in out:
            out.append(resolved)
    return out


def build_operator_surface(
    db_path: Path | str,
    store_path: Path | str | None,
    *,
    gate_module: str = "",
    rw_lock: Any | None = None,
    reload_hook: Any | None = None,
):
    """The human plane for `main()` — review, inbox and graph reads.

    A configured gate module supplies the same ``build_gate_for`` closure the
    CLI uses. Without one, confirm still refuses on graphs that have no
    ``graph.md``. A named-traversal contract is the other license to commit."""
    from mcp_server.operator import OperatorSurface

    db = Path(db_path)
    store = Path(store_path) if store_path else db.with_suffix(".store.sqlite")
    gate_provider = _load_gate_provider(
        gate_module,
        db_path=db,
        store_path=store,
    )
    op = OperatorSurface(
        db,
        store,
        gate_provider=gate_provider,
        rw_lock=rw_lock,
        reload_hook=reload_hook,
    )

    # Optional model-backed reads use a provider credential. Precedence: an
    # explicit env var (CI, containers) > the operator's stored BYO key > a
    # local .env (developer convenience).
    if not os.environ.get("OPENROUTER_API_KEY"):
        if not op._acct().apply_key_to_env():
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:
                pass
    return op


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("SST_MCP_HTTP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("SST_MCP_HTTP_PORT", "8137")))
    ap.add_argument(
        "--operator",
        action="store_true",
        default=_env_flag("SST_MCP_OPERATOR"),
        help="Mount the human plane at /operator beside /mcp (local UI needs this).",
    )
    ap.add_argument(
        "--gate-module",
        default=os.environ.get("SST_MCP_GATE_MODULE", ""),
        help="Server-owned module name or .py path exposing build_gate_for.",
    )
    args = ap.parse_args()

    db_path = os.environ.get("SST_DB_PATH", "")
    if not db_path:
        raise SystemExit("SST_DB_PATH is required")
    token = os.environ.get("SST_MCP_TOKEN") or None
    if token is None and token_required_to_start():
        raise SystemExit(
            "SST_MCP_TOKEN is required (secure default). For loopback development "
            "only, set SST_MCP_ALLOW_INSECURE=1."
        )

    db = Path(db_path).expanduser().resolve()
    configured_store = os.environ.get("SST_MCP_STORE_PATH") or ""
    initial_store = (
        Path(configured_store).expanduser().resolve()
        if configured_store
        else db.with_suffix(".store.sqlite")
    )
    handbook = os.environ.get("SST_MCP_HANDBOOK") or None
    history_enabled = (
        os.environ.get("SST_MCP_HISTORY", "1").strip().lower()
        not in ("0", "false", "no")
    )
    proposals_enabled = _env_flag("SST_MCP_PROPOSALS")
    # The agent surface and operator surface must share the server-owned gate
    # declaration. Keep an explicit None when no module is configured: local
    # browse/review still starts. Confirmation then needs either that battery
    # or a graph.md beside the database.
    gate_provider = _load_gate_provider(
        args.gate_module,
        db_path=db,
        store_path=initial_store,
    )

    workspace_owner = None
    if args.operator:
        from mcp_server.workspace import WorkspaceOwner

        def surface_factory(path: Path, lock):
            store = initial_store if path == db else path.with_suffix(".store.sqlite")
            return Surface(
                path,
                handbook=handbook,
                store_path=store,
                enable_history=history_enabled,
                enable_proposals=proposals_enabled,
                rw_lock=lock,
                # Re-bound per workspace: the factory may open a different
                # graph than the one the battery was configured against, and a
                # preflight must gate the graph actually in front of the agent.
                gate_provider=(gate_provider.rebind(path, store)
                               if gate_provider is not None else None),
            )

        def operator_factory(path: Path, lock, reload_hook):
            store = initial_store if path == db else path.with_suffix(".store.sqlite")
            return build_operator_surface(
                path,
                store,
                gate_module=args.gate_module,
                rw_lock=lock,
                reload_hook=reload_hook,
            )

        workspace_owner = WorkspaceOwner(
            db,
            surface_factory=surface_factory,
            operator_factory=operator_factory,
        )
        surface = workspace_owner.surface_proxy
        operator = workspace_owner.operator_proxy
    else:
        surface = Surface(
            db,
            handbook=handbook,
            store_path=initial_store,
            enable_history=history_enabled,
            enable_proposals=proposals_enabled,
        )
        operator = None
    import uvicorn
    from mcp_server.memory import start as start_memory_trace

    start_memory_trace(log_path=db.with_suffix(".memory.jsonl"))

    app = build_asgi_app(
        surface,
        token=token,
        transcript_path=os.environ.get("SST_MCP_TRANSCRIPT") or None,
        operator=operator,
        graph_library_dirs=_default_graph_library_dirs(db_path),
        graph_output_roots=_default_graph_construction_roots(db_path),
        workspace_owner=workspace_owner,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
