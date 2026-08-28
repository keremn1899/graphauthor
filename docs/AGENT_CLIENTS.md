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

Create a project for one graph:

```bash
graphauthor init my-graph-project
cd my-graph-project
```

The initializer creates a `sources/` directory, an `AGENT_PROMPT.md` shared by
all clients, and MCP configuration pointing at this project's future
`graph.lbug`. Put source files in `sources/` and give the agent the shared
prompt. The agent creates `workbook/build.py`, validates it, and materializes
`graph.lbug`.

## Cursor

`graphauthor init` writes `.cursor/mcp.json`. Open the project in Cursor,
enable **graphauthor** in the MCP tools list, and paste `AGENT_PROMPT.md` into
an Agent chat. Reload Cursor after the graph is first materialized if the tool
was previously unavailable.

Cursor uses the project-local configuration; no further terminal command is
needed. [Cursor MCP documentation](https://docs.cursor.com/context/model-context-protocol)

## Claude Code

`graphauthor init` also writes the project-local `.mcp.json` expected by Claude
Code. Start Claude Code from the graph-project directory, approve the proposed
**graphauthor** server if prompted, and paste `AGENT_PROMPT.md` into the
session.

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

Then start Codex in the project and paste `AGENT_PROMPT.md` into the session.
Codex supports MCP tools; this registration gives it the same Graphauthor
operations as the other clients. [OpenAI documentation](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)

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
