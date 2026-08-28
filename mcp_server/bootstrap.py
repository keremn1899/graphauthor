"""Attach Graphauthor to an existing agent workspace.

``graphauthor attach`` never creates a second project. It adds an empty,
hidden ``.graphauthor`` sidecar for the agent's construction program and merges
one MCP entry into the selected client configuration. Source files stay exactly
where the user already keeps them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


def _entry(db: Path) -> dict[str, Any]:
    return {
        "command": str(Path(sys.executable).resolve()),
        "args": ["-m", "mcp_server.stdio"],
        "env": {"SST_DB_PATH": str(db)},
    }


def _merge_mcp_config(path: Path, db: Path) -> None:
    """Add only our server, preserving a user's other MCP connections."""
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} is not valid JSON; refusing to overwrite it") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("mcpServers", {}), dict):
            raise ValueError(f"{path} must contain an object named mcpServers")
    else:
        payload = {"mcpServers": {}}
    payload.setdefault("mcpServers", {})["graphauthor"] = _entry(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _codex_name(workspace: Path) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in workspace.name.lower())
    return "graphauthor-" + (slug.strip("-") or "workspace")


def _attach_codex(workspace: Path, db: Path) -> str:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Codex CLI is not on PATH; install it, then run attach --client codex")
    name = _codex_name(workspace)
    command = [
        codex, "mcp", "add", name, "--env", f"SST_DB_PATH={db}", "--",
        str(Path(sys.executable).resolve()), "-m", "mcp_server.stdio",
    ]
    subprocess.run(command, check=True)
    return name


def attach_workspace(workspace: Path | str, clients: Iterable[str]) -> dict[str, Any]:
    """Attach selected MCP clients to an existing workspace without scaffolding it."""
    workspace = Path(workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"{workspace} is not a directory")
    selected = set(clients)
    if "all" in selected:
        selected = {"cursor", "claude", "codex"}
    unknown = selected - {"cursor", "claude", "codex"}
    if unknown:
        raise ValueError(f"unknown client(s): {', '.join(sorted(unknown))}")

    sidecar = workspace / ".graphauthor"
    sidecar.mkdir(exist_ok=True)
    db = sidecar / "graph.lbug"
    attached: list[str] = []
    if "cursor" in selected:
        _merge_mcp_config(workspace / ".cursor" / "mcp.json", db)
        attached.append("cursor")
    if "claude" in selected:
        _merge_mcp_config(workspace / ".mcp.json", db)
        attached.append("claude")
    if "codex" in selected:
        attached.append(_attach_codex(workspace, db))

    command = f'"{Path(sys.executable).resolve()}" -m scripts.atoms'
    return {
        "workspace": str(workspace),
        "sidecar": str(sidecar),
        "db_path": str(db),
        "attached": attached,
        "agent_prompt": (
            "Use Graphauthor for this workspace. Keep the construction program in "
            "`.graphauthor/build.py`; use the relevant files already in this workspace "
            f"as sources. Prepare with `{command} prepare --workbook .graphauthor "
            "--source ...`, validate with `"
            f"{command} validate --workbook .graphauthor --encoding "
            ".graphauthor/out/encoding.json`, then materialize with `"
            f"{command} materialize --workbook .graphauthor --encoding "
            ".graphauthor/out/encoding.json --out .graphauthor/graph.lbug`. "
            "Call `orient` before graph questions."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphauthor", description=__doc__)
    commands = parser.add_subparsers(dest="command")
    attach = commands.add_parser("attach", help="add Graphauthor to an existing workspace")
    attach.add_argument("path", nargs="?", default=".", help="workspace directory (default: current)")
    attach.add_argument(
        "--client", action="append", choices=("cursor", "claude", "codex", "all"),
        default=[], help="agent client to configure; repeat for more than one",
    )
    args = parser.parse_args(argv)
    if args.command != "attach":
        parser.print_help()
        return 2
    try:
        result = attach_workspace(args.path, args.client or ("cursor",))
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
