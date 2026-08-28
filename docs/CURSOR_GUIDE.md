# Graphauthor with Cursor

Graphauthor is a local tool for Cursor Agent. The user supplies source files
and an outcome; the agent creates the graph-building program and then uses the
graph through MCP. Users do not need to hand-author a schema, `encoding.json`,
or graph query.

## Install

Install [uv](https://docs.astral.sh/uv/) once, then install the checkout as an
isolated command-line tool:

```bash
uv tool install --editable '.[cursor]'
```

`graphauthor` is not published to PyPI yet. After its first release, the
equivalent public command will be `uv tool install 'graphauthor[cursor]'`.
`uv tool` manages Graphauthor's Python environment separately from the user's
projects, so it does not alter the system Python or require a separate
environment manager.

## Attach to an existing project

```bash
cd my-existing-project
graphauthor attach --client cursor
```

The command leaves the project structure alone. It creates only:

```text
my-existing-project/
  .cursor/mcp.json       merged Cursor Graphauthor connection
  .graphauthor/          agent construction program and graph output
```

Open the existing project in Cursor and start an Agent chat. The agent uses
the source files already in the workspace; no copying is required. For example:

> Build a Graphauthor graph from the relevant files already in this workspace
> for answering questions about
> our architecture decisions. Inspect the sources first. Create and run
> `.graphauthor/build.py`, validate its output, materialize the graph, and report
> what it captured and what remains ambiguous.

The agent is expected to follow this lifecycle:

```text
workspace files → .graphauthor/atoms.jsonl → .graphauthor/build.py
                → .graphauthor/out/encoding.json → validation → graph.lbug
```

The agent owns interpretation and `build.py`; Graphauthor mechanically
validates source provenance and graph integrity, then materializes the graph.

## Connect and use it in Cursor

`graphauthor attach` has merged `.cursor/mcp.json`. It uses the exact
Python environment that installed Graphauthor, which works even when Cursor
was launched from its GUI. Once the agent materializes `graph.lbug`, reload the
Cursor window if needed and enable **graphauthor** in the MCP tools list.

Start graph tasks with a prompt like:

> Use the Graphauthor tools. Call `orient` first, then answer my question from
> the graph with source-backed evidence. State clearly if the graph cannot
> establish the answer.

The MCP server gives Agent deterministic operations including `orient`,
`lookup`, `expand`, `path`, and `search`. Search returns candidates, not proof;
the agent should report uncertainty rather than inventing missing relations.

For Claude Code and Codex setup, see the [general agent-client guide](AGENT_CLIENTS.md).

## Existing project configuration

For a project where you do not want to run `graphauthor attach`, use
`.cursor/mcp.json.example` as the starting point. Set `SST_DB_PATH` to the
absolute path of its materialized `.graphauthor/graph.lbug`. Cursor supports
project-local MCP configuration at `.cursor/mcp.json`. [Cursor MCP documentation](https://docs.cursor.com/context/model-context-protocol)

## Boundaries

Graphauthor is local and one server process owns one `.lbug` graph file at a
time. Humans should review graphs before publishing them or using them for
high-consequence decisions.
