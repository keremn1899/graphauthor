# Install Graphauthor for agent clients

Graphauthor has one local installation and one MCP server command. Cursor,
Claude Code, and Codex all use that same server; only the registration step is
client-specific.

## Install once

Install [uv](https://docs.astral.sh/uv/) once, then install the checkout and
its MCP, HTML, and PDF support:

```bash
uv tool install --editable '.[cursor]'
```

`graphauthor` is not published to PyPI yet. After the first PyPI release, the
same installation becomes `uv tool install 'graphauthor[cursor]'`.

Attach Graphauthor to any existing workspace:

```bash
cd my-existing-project
graphauthor attach --client cursor
```

Attach creates only `.graphauthor/` plus the selected MCP configuration. It
does not create a second project, copy sources, or prescribe a source folder.
The agent uses relevant files already in the workspace, keeps its construction
program in `.graphauthor/build.py`, and materializes `.graphauthor/graph.lbug`.

## Cursor

`graphauthor attach --client cursor` merges one entry into `.cursor/mcp.json`.
Open the project in Cursor and enable **graphauthor** in the MCP tools list.

Cursor uses the project-local configuration; no further terminal command is
needed. [Cursor MCP documentation](https://docs.cursor.com/context/model-context-protocol)

## Claude Code

Run `graphauthor attach --client claude`. It merges one entry into the
project-local `.mcp.json` expected by Claude Code. Start Claude Code from that
directory and approve the proposed **graphauthor** server if prompted.

For an existing project without `.mcp.json`, run this from that project:

```bash
claude mcp add --scope project graphauthor \
  -e "SST_DB_PATH=$PWD/graph.lbug" -- "$(command -v graphauthor-mcp)"
```

The `--scope project` setting keeps the graph connection with that project
rather than exposing it to every Claude Code workspace.

## Codex

Codex registers local stdio MCP servers with its CLI. From the graph-project
directory, run:

```bash
codex mcp add graphauthor-my-graph-project \
  --env "SST_DB_PATH=$PWD/graph.lbug" -- "$(command -v graphauthor-mcp)"
```

Use a distinct server name for each graph project. Confirm it with:

```bash
codex mcp list
```

Then start Codex in the project and tell it to use Graphauthor for the current
workspace. Codex supports MCP tools; this registration gives it the same
Graphauthor operations as the other clients. [OpenAI documentation](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)

## The shared server definition

Every configuration reduces to the same local process and environment value:

```text
command: graphauthor-mcp
environment: SST_DB_PATH=/absolute/path/to/graph.lbug
```

The generated Cursor and Claude Code files use an absolute Python path rather
than relying on a GUI process inheriting the terminal `PATH`. Codex and Claude
Code CLI commands resolve `graphauthor-mcp` first and record its absolute path.

Only one Graphauthor MCP server may own a given `.lbug` file at a time. A graph
rebuild does not need re-registration; reconnect or restart the MCP client only
if it had the old graph open during materialization.
