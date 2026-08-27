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
conda env create -f environment.yml
conda activate agentic-graphrag
pip install -e ".[mcp,http,construct]"

python scripts/workbook.py prepare --workbook workbook --source sources/page.html
python scripts/workbook.py validate --workbook workbook --encoding workbook/out/encoding.json
python scripts/workbook.py materialize --workbook workbook --encoding workbook/out/encoding.json
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

Add the MCP server with [`.cursor/mcp.json.example`](.cursor/mcp.json.example).
Point `SST_DB_PATH` at a materialized `graph.lbug`. Call `orient` first.

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
