#!/usr/bin/env python3
"""Run the local product as one supervised backend/frontend pair.

Usage from the repository root:

    conda run --no-capture-output -n agentic-graphrag \
      python scripts/run_local_product.py

The launcher reuses healthy processes already listening on the two development
ports, starts whichever half is missing, opens Graph in the default browser,
and only terminates children it started itself.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BACKEND = "http://127.0.0.1:8137"
FRONTEND = "http://127.0.0.1:5173"


def _get(url: str, token: str = "") -> tuple[int, bytes]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError):
        return 0, b""


def _wait(url: str, token: str, process: subprocess.Popen | None) -> bytes:
    deadline = time.time() + 20
    while time.time() < deadline:
        status, body = _get(url, token)
        if status == 200:
            return body
        if process is not None and process.poll() is not None:
            raise SystemExit(f"Process exited before {url} became ready.")
        time.sleep(0.15)
    raise SystemExit(f"Timed out waiting for {url}.")


def _listening_pid(port: int) -> int | None:
    """The pid holding a listening socket on `port`, via /proc.

    Matched by socket inode rather than by scanning process names. Picking "the
    first vite process" would have been simpler and wrong: a second dev server
    on another port is exactly the situation this guard exists for, and that
    version answered confidently about the wrong process.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    wanted = f"{port:04X}"
    inodes: set[str] = set()
    for table in ("net/tcp", "net/tcp6"):
        try:
            lines = (proc / table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            # state 0A is LISTEN
            if fields[3] != "0A" or not fields[1].endswith(":" + wanted):
                continue
            inodes.add(fields[9])
    if not inodes:
        return None
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for fd in (entry / "fd").iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return int(entry.name)
        except OSError:
            continue
    return None


def _dev_server_root() -> Path | None:
    """Which checkout the process on 5173 is serving, if it can be told.

    Returns `None` when it cannot be determined — an unknown answer must not be
    reported as a match, because the whole point is that a wrong answer here is
    invisible.
    """
    pid = _listening_pid(5173)
    if pid is None:
        return None
    try:
        cwd = Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return None
    if cwd.name == "frontend":
        return cwd
    if (cwd / "frontend").is_dir():
        return cwd / "frontend"
    return cwd


def _refuse_a_foreign_dev_server() -> None:
    """A healthy dev server is not necessarily *this* product's dev server.

    The launcher reuses whatever is listening on 5173. That is right when it is
    your own; it is silently wrong when it belongs to another checkout, which
    is the ordinary case with git worktrees — you get this backend under that
    branch's UI, and every change you just made appears not to have happened.

    Port 8137 already refuses to be reused when it cannot prove it owns the
    right graph. The frontend had no equivalent check, and the asymmetry cost a
    session: the browser was served master while the backend served the branch.
    """
    if _listening_pid(5173) is None:
        return  # nothing to reuse; the launcher will start its own
    serving = _dev_server_root()
    mine = (ROOT / "frontend").resolve()
    if serving is None:
        print(
            "Note: reusing the dev server already on 5173. Could not tell "
            "which checkout it serves — if the UI looks stale, stop it and "
            "re-run.",
            file=sys.stderr,
        )
        return
    if serving == mine:
        return
    raise SystemExit(
        "Port 5173 is serving a different checkout:\n"
        f"  it is serving: {serving}\n"
        f"  this launcher: {mine}\n"
        "Reusing it would put that branch's UI in front of this backend, so "
        "every change here would look like it had not happened. Stop it and "
        "re-run:\n"
        "  pkill -f 'vite --host 127.0.0.1'"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local product")
    parser.add_argument("--db", default="data/demo/organisation-ops/graph.lbug")
    parser.add_argument("--token", default="devtoken")
    parser.add_argument("--gate-module", default="")
    parser.add_argument("--page", choices=("graph", "review", "construct"), default="graph")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    db = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    if not db.is_file():
        raise SystemExit(f"No graph at {db}")

    # Checked before anything is started: a refusal after spawning the backend
    # would orphan it on 8137, and the next run would then fail for a second,
    # unrelated reason.
    _refuse_a_foreign_dev_server()

    children: list[subprocess.Popen] = []
    backend_status, _ = _get(f"{BACKEND}/graph/graphs", args.token)
    if backend_status == 0:
        env = os.environ.copy()
        env.update({
            "SST_DB_PATH": str(db),
            "SST_MCP_TOKEN": args.token,
            "PYTHONFAULTHANDLER": "1",
            "SST_MEMORY_TRACE": os.environ.get("SST_MEMORY_TRACE", "1"),
        })
        if args.gate_module:
            env["SST_MCP_GATE_MODULE"] = args.gate_module
        backend = subprocess.Popen(
            [sys.executable, "-m", "mcp_server.http", "--operator"],
            cwd=ROOT,
            env=env,
        )
        children.append(backend)
    elif backend_status != 200:
        raise SystemExit(
            f"Port 8137 is occupied but the configured token was rejected "
            f"(HTTP {backend_status}). Stop that process or pass its token."
        )
    elif args.db != parser.get_default("db") or args.gate_module:
        raise SystemExit(
            "Port 8137 already has a healthy product backend. The launcher cannot "
            "prove that it owns the requested graph and gate configuration, so it "
            "will not silently reuse that process. Stop it before launching this "
            "scenario."
        )

    frontend_status, _ = _get(FRONTEND)
    if frontend_status == 0:
        frontend = subprocess.Popen(
            ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
            cwd=ROOT / "frontend",
        )
        children.append(frontend)
    elif frontend_status != 200:
        raise SystemExit(f"Port 5173 is occupied by an unhealthy process.")

    body = _wait(
        f"{BACKEND}/graph/graphs",
        args.token,
        children[0] if children else None,
    )
    _wait(FRONTEND, "", children[-1] if children else None)
    # The node reader needs GET /graph/node. A reused older backend answers the
    # catalogue but has no such route (raw 404). Fail early rather than letting
    # the panel report a confusing "Not found".
    node_status, node_body = _get(f"{BACKEND}/graph/node", args.token)
    if node_status not in (400, 200):
        raise SystemExit(
            f"/graph/node returned HTTP {node_status} — this product frontend "
            f"needs a current operator backend. Stop the process on port 8137 "
            f"and re-run this launcher "
            f"(got: {node_body[:180]!r})."
        )
    try:
        graphs = json.loads(body).get("graphs", [])
    except (ValueError, AttributeError):
        graphs = []

    url = f"{FRONTEND}/#/{args.page}?api=live&apiToken={args.token}"
    print()
    print(f"Ready: {url}")
    print(f"Current graph: {db}")
    print(f"Catalogue: {len(graphs)} graph(s)")
    print("Press Ctrl-C to stop the processes started by this launcher.")
    print()
    if not args.no_browser:
        webbrowser.open(url)

    def stop(*_args) -> None:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        deadline = time.time() + 5
        for child in reversed(children):
            remaining = max(0, deadline - time.time())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            for child in children:
                code = child.poll()
                if code is not None:
                    raise SystemExit(f"Child process exited with status {code}.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
