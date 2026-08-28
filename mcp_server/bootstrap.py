"""Create a new local Graphauthor project for use from Cursor Agent.

The scaffold contains no graph and no construction code. The user supplies
sources and tells their agent what the graph should help with; the agent owns
``workbook/build.py``. The generated Cursor configuration uses the exact Python
executable running this command, so a GUI-launched Cursor does not depend on an
activated shell or a particular environment manager.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _mcp_config(db: Path) -> str:
    return json.dumps({
        "mcpServers": {
            "graphauthor": {
                "command": str(Path(sys.executable).resolve()),
                "args": ["-m", "mcp_server.stdio"],
                "env": {"SST_DB_PATH": str(db)},
            }
        }
    }, indent=2) + "\n"


def _agent_prompt() -> str:
    command = f'"{Path(sys.executable).resolve()}" -m scripts.atoms'
    return f"""# Build this graph

The files in `sources/` are the user-provided evidence. Ask the user any
essential question about their desired outcome, then:

1. Inspect and prepare the sources with `{command} prepare`.
2. Write and run `workbook/build.py`. You own its interpretation, graph grain,
   node kinds, predicates, and source citations.
3. Run `{command} validate` and repair any mechanical errors.
4. Run `{command} materialize` with `--out graph.lbug`.
5. Summarise what the graph represents, its limitations, and useful questions
   it can answer.

Do not claim that a search result proves a relationship. Once the graph is
materialized, use the Graphauthor MCP tools: call `orient` before a multi-step
graph task, use exact `lookup` for known names, and report uncertainty when the
graph does not establish an answer.
"""


def _next_steps() -> str:
    return """# Next steps

1. Copy the files you want the agent to use into `sources/`.
2. Open this folder in Cursor, Claude Code, or Codex and start an agent session.
3. Paste the contents of `AGENT_PROMPT.md` into the session.
4. After materialization, reload or reconnect the MCP server if Graphauthor
   was previously unavailable, then ask the agent to call `orient`.

The project contains `.cursor/mcp.json` for Cursor and `.mcp.json` for Claude
Code. Codex uses the same command through `codex mcp add`; see the general
installation guide. All configurations point at `graph.lbug`. Only one server
process may own that graph file at a time.
"""


def init_project(project_dir: Path | str) -> dict[str, Any]:
    """Create an empty, non-destructive agent project and return its manifest."""
    project_dir = Path(project_dir).expanduser().resolve()
    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(
            f"{project_dir} is not empty; choose a new directory so init cannot overwrite work"
        )

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "sources").mkdir()
    (project_dir / "workbook").mkdir()
    cursor_dir = project_dir / ".cursor"
    cursor_dir.mkdir()
    db = project_dir / "graph.lbug"
    config = _mcp_config(db)
    (cursor_dir / "mcp.json").write_text(config, encoding="utf-8")
    (project_dir / ".mcp.json").write_text(config, encoding="utf-8")
    (project_dir / "AGENT_PROMPT.md").write_text(_agent_prompt(), encoding="utf-8")
    (project_dir / "NEXT_STEPS.md").write_text(_next_steps(), encoding="utf-8")

    return {
        "project_dir": str(project_dir),
        "db_path": str(db),
        "created": [
            "sources/", "workbook/", ".cursor/mcp.json", ".mcp.json",
            "AGENT_PROMPT.md", "NEXT_STEPS.md",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphauthor", description=__doc__)
    commands = parser.add_subparsers(dest="command")
    init = commands.add_parser("init", help="create a Cursor-ready graph project")
    init.add_argument("project_dir", help="a new or empty directory")
    args = parser.parse_args(argv)
    if args.command != "init":
        parser.print_help()
        return 2
    try:
        manifest = init_project(args.project_dir)
    except FileExistsError as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2))
    print(f"\nOpen {manifest['project_dir']} in Cursor, then read NEXT_STEPS.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
