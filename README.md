# Graphauthor

Graphauthor is a local, source-cited graph context layer for agents.

You supply sources. An agent writes a normal Python program that authors a
graph for that work. Graphauthor prepares the sources, checks the program's
output mechanically, stores the graph, and lets agents traverse it exactly.

It is not a better general search engine. The point is reuse: once identities
and relationships are accepted, an agent can walk them instead of reconstructing
them from the sources on every task.

## Construction

There is one construction model:

```
sources
  -> workbook/atoms.jsonl          optional prepared view
  -> workbook/build.py             written and run by the agent
  -> workbook/out/encoding.json    durable program output
  -> workbook/out/traversals.json  optional named traversals
  -> validate + materialize        host-owned, mechanical
  -> graph.lbug + sidecars
```

The agent owns `build.py`. Graphauthor does not write or run it. The host
checks only what it can know mechanically: unique ids, real edge endpoints,
valid structural types, and provenance to admitted source units.

```bash
uv tool install --editable '.[cursor]'
graphauthor init my-graph-project

graphauthor-workbook prepare --workbook workbook --source sources/page.html
graphauthor-workbook validate --workbook workbook --encoding workbook/out/encoding.json
graphauthor-workbook materialize --workbook workbook --encoding workbook/out/encoding.json --out graph.lbug
```

This installs the current checkout for development and evaluation. The package
is not published to PyPI yet. After the first PyPI release, users will instead
install it by name:

```bash
uv tool install 'graphauthor[cursor]'
```

## Traversal

Retrieval does not call a model. Exact lookup stays exact. Search returns
candidates; it does not prove absence.

Named traversals are versioned programs for recurring jobs. Ephemeral
traversals are one-off programs. Every run returns a receipt bound to a graph
version.

```json
{
  "steps": [
    {
      "op": "lookup",
      "references": ["topic:named-traversal"],
      "assign": "seed"
    },
    {
      "op": "expand",
      "from": "$seed",
      "predicates": ["about"],
      "direction": "both",
      "depth": 1,
      "assign": "related"
    }
  ],
  "collect": "$seed + $related",
  "answers": ["related"],
  "limits": {"max_steps": 4, "max_hops": 2, "max_nodes": 20}
}
```

For installation and setup across Cursor, Claude Code, and Codex, see the
[agent-client guide](docs/AGENT_CLIENTS.md). The Cursor-specific workflow is in
[the Cursor guide](docs/CURSOR_GUIDE.md). Point `SST_DB_PATH` at a materialized
`graph.lbug`, and have the agent call `orient` first.

```bash
SST_DB_PATH=/absolute/path/to/graph.lbug graphauthor-mcp
python scripts/run_local_product.py
```

One process owns one graph file at a time.

## Authority

- The agent interprets sources and authors construction and traversal programs.
- The host pins source identity, validates output, runs bounded graph
  operations, and records receipts.
- Durable writes go through `propose`, which auto-commits. Revert is the
  backward path.
- Parsers, segmenters, and workbook programs cannot write the graph.

## Layout

| Path | Role |
|---|---|
| `source_pipeline/` | parsers, workbook, mechanical boundaries |
| `scripts/workbook.py` | prepare, validate, materialize |
| `mcp_server/` | retrieval, traversal, propose, receipts |
| `frontend/` | Graph and Logs |
| `product/` | product contract |
