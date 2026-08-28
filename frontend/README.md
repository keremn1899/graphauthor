# Local UI

React, Vite and G6 UI for Graphauthor. The UI reads graphs and shows write
history. It does not run construction.

Construction happens in the agent's workbook session: the agent authors and
runs build.py, then uses the host's mechanical validation and materialization
commands.

## Run

From the repository root:

~~~bash
uv run --extra all python scripts/run_local_product.py
~~~

This starts whichever backend or frontend process is missing and opens the
Graph route. Use --no-browser to suppress opening a tab.

Manual development:

~~~bash
SST_DB_PATH=data/sst.lbug SST_MCP_TOKEN=devtoken uv run --extra all python -m mcp_server.http --operator

cd frontend
npm run dev
~~~

## Product routes

| mode | route | entry |
|---|---|---|
| Graph | #/graph?api=live | src/product/GraphSurface.tsx |
| Logs | #/log?api=live | src/product/LogsWorkspace.tsx |
| Explorations, development only | #/explorations?api=fixture | src/explorations/ExplorationsIndex.tsx |

Production builds do not bundle exploration routes.

## Backend boundary

The frontend talks to the operator and graph planes. Agent consumers use the
equivalent MCP surface.

- Graph: graph catalogue, map and controlled open
- Logs: committed and reverted graph writes

Opening a graph performs a controlled backend swap; it does not change the
process working directory. One process owns one graph file at a time.

Executable product UI rules live in
[tests/test_design_rules.py](../tests/test_design_rules.py).
