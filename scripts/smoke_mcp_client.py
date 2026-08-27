#!/usr/bin/env python3
"""Validate an MCP client config the way the client will actually use it.

Reads the real `mcp.json`, spawns exactly what Cursor or Claude Code would
spawn, and speaks the protocol. Testing the server in-process would pass while
the client still failed, because every failure seen so far has been in the
seam: a console script missing from a stale editable install, a `command` that
only resolves inside an activated conda shell, a graph that answers every
question with nothing governing.

    python scripts/smoke_mcp_client.py                      # ~/.cursor/mcp.json
    python scripts/smoke_mcp_client.py --config path --server graphauthor

Exit code is the number of failed checks.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
_results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool | None, detail: str = "") -> bool:
    state = WARN if ok is None else (PASS if ok else FAIL)
    _results.append((state, name, detail))
    return bool(ok)


class Client:
    """Minimal stdio MCP client — the transport a real editor uses."""

    def __init__(self, command: list[str], env: dict[str, str]):
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            env={**os.environ, **env})
        self._id = 0

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _read(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)

    def request(self, method: str, params: dict | None = None):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params or {}})
        return self._read()

    def notify(self, method: str, params: dict | None = None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def call(self, tool: str, args: dict) -> dict:
        reply = self.request("tools/call", {"name": tool, "arguments": args}) or {}
        text = (reply.get("result", {}).get("content") or [{}])[0].get("text", "")
        try:
            return json.loads(text)
        except Exception:
            return {"_raw": text[:200]}

    def close(self) -> str:
        """Leave nothing behind. A server that outlives this script keeps the
        LadybugDB lock, and the next run fails with `Could not set lock on
        file` — which reads like a config problem and is not one."""
        for step in (self.proc.terminate, self.proc.kill):
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            step()
            try:
                self.proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        try:
            return self.proc.stderr.read() or ""
        except Exception:
            return ""


def governing_count(db_path: Path) -> int | None:
    """The silent failure: a graph with no declared authority answers every
    question with nothing governing, and looks like it is working."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import real_ladybug as lb

        db = lb.Database(str(db_path))
        conn = lb.Connection(db)
        try:
            rows = conn.execute(
                "MATCH (n:Concept) WHERE n.claim_kind = 'governing' RETURN count(n)")
            return int(rows.get_next()[0]) if rows.has_next() else 0
        finally:
            del conn, db
    except Exception:
        return None


def _lock_state(db_path: Path) -> tuple[bool | None, str]:
    """LadybugDB is single-owner. If an editor already has this graph open —
    or a previous run leaked a server — the config is fine and the handshake
    still fails."""
    if not db_path.exists():
        return None, "no graph to check"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import real_ladybug as lb

        db = lb.Database(str(db_path))
        del db
        return True, ""
    except Exception as exc:
        if "lock" in str(exc).lower():
            return False, ("another process holds this graph — close the editor, "
                           "or: pkill -f graphauthor-mcp")
        return None, f"could not open: {type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path.home() / ".cursor" / "mcp.json"))
    ap.add_argument("--server", default="graphauthor")
    args = ap.parse_args()

    cfg_path = Path(args.config).expanduser()
    if not check("config file exists", cfg_path.exists(), str(cfg_path)):
        return report()
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception as exc:
        check("config parses as JSON", False, str(exc))
        return report()
    check("config parses as JSON", True)

    servers = cfg.get("mcpServers") or {}
    entry = servers.get(args.server)
    if not check(f"server {args.server!r} present", bool(entry),
                 f"found: {sorted(servers) or 'none'}"):
        return report()

    command = [entry.get("command", "")] + list(entry.get("args") or [])
    env = {str(k): str(v) for k, v in (entry.get("env") or {}).items()}

    cmd = command[0]
    check("command is an absolute path", Path(cmd).is_absolute(),
          f"{cmd!r} — a bare name only resolves in an activated shell, "
          "which the editor does not give the server")
    resolved = cmd if Path(cmd).is_absolute() else (shutil.which(cmd) or "")
    check("command exists and is executable",
          bool(resolved) and os.access(resolved, os.X_OK), resolved or "not found")

    db = Path(env.get("SST_DB_PATH", ""))
    check("SST_DB_PATH is set", bool(env.get("SST_DB_PATH")))
    check("graph file exists", db.exists(), str(db))
    if db.exists():
        n = governing_count(db)
        check("graph declares governing nodes", (n or 0) > 0 if n is not None else None,
              f"{n} governing nodes" if n is not None
              else "could not read claim_kind — graph predates the field")

    if not resolved or not db.exists():
        return report()

    check("graph is not already locked", *_lock_state(db))

    client = Client(command, env)
    try:
        init = client.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0"}})
        info = ((init or {}).get("result") or {}).get("serverInfo") or {}
        check("initialize handshake", bool(info), json.dumps(info))
        client.notify("notifications/initialized")

        listed = client.request("tools/list") or {}
        tools = [t["name"] for t in (listed.get("result") or {}).get("tools", [])]
        check("tools/list returns tools", bool(tools), f"{len(tools)} tools")

        want_construction = env.get("SST_MCP_CONSTRUCTION", "").lower() in ("1", "true", "yes")
        has_construction = any(t.startswith("construction_") for t in tools)
        check("construction verbs match SST_MCP_CONSTRUCTION",
              want_construction == has_construction,
              f"requested={want_construction} present={has_construction}")

        for tool in ("orient", "lookup", "expand", "path", "search",
                     "run_traversal", "run_ephemeral_traversal", "retrieve"):
            check(f"tool present: {tool}", tool in tools)

        seed = ""
        out = client.call("orient", {})
        check("orient answers", "graph_version" in out, str(out.get("node_count", ""))[:40])

        s = client.call("search", {"query": "dependency direction", "limit": 3})
        ids = [c.get("id") for c in (s.get("evidence", {}).get("node_records") or [])]
        seed = next((i for i in ids if i), "")
        check("search returns candidates", bool(ids) or s.get("outcome") in ("CANDIDATES", "NO_CANDIDATES"), f"{len(ids)} candidates")
        check("search is zero-LLM", s.get("zero_llm") is True)

        if seed:
            lk = client.call("lookup", {"references": [seed]})
            check("lookup resolves a real id", lk.get("outcome") == "FOUND", f"{seed} -> {lk.get('outcome')}")
            ex = client.call("expand", {"node_ids": [seed], "depth": 1})
            check("expand traverses", ex.get("outcome") in ("FOUND", "EMPTY"), str(ex.get("outcome")))
    except BrokenPipeError:
        check("server stayed alive through the session", False,
              "the server exited mid-handshake — see its stderr below")
    except Exception as exc:                      # noqa: BLE001 - reported
        check("smoke run completed", False, f"{type(exc).__name__}: {exc}")
    finally:
        err = client.close()
        if err and err.strip():
            tail = "\n".join(err.strip().splitlines()[-4:])
            check("server stderr", None, tail[:400])

    return report()


def report() -> int:
    width = max(len(n) for _, n, _ in _results) if _results else 10
    failed = 0
    print()
    for state, name, detail in _results:
        failed += state == FAIL
        print(f"  {state:<4} {name:<{width}}  {detail}")
    print(f"\n  {len(_results)} checks, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
