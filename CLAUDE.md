# CLAUDE.md

Guidance for working in this repository.

## Product boundary

Graphauthor is a local, source-cited graph context layer. The editor agent owns
interpretation and authors construction programs. The host owns source
identity, mechanical encoding validation, deterministic traversal, receipts
and proposal persistence. A human owns publication.

The only current product design authorities are:

- product/graph-harness-product.md
- product/harness-contract.md
- product/named-traversal-contract.md

Benchmarks are evidence, not specifications. Do not recover product behavior
from deleted design history, old branches, trial outputs, or database fixtures.

## One construction model

Construction is a workbook containing sources, an optional prepared atom
stream, the agent-authored build.py, and out/encoding.json.

The agent program may use supplied parsers and segmenters, its own code, models,
or other permitted libraries. The product never authors or runs build.py. The
host validates and materializes its output. There are no domain format packs,
server-owned construction jobs, staged constructors, or one-shot LLM graph
generators in this branch.

Never add another construction path. Extend parser/segmenter protocols or the
workbook boundary instead.

## Authority rules

- Retrieval and traversal do not call a model.
- Exact misses remain exact misses; search results remain candidates.
- Parsers, segmenters and workbook programs have no graph-write authority.
- Durable changes enter through propose, which auto-commits; revert is the backward path.
- Node kinds and predicates are chosen by the workbook program.
- One process owns a Ladybug graph file at a time.

## Environment

Use the agentic-graphrag conda environment:

~~~bash
conda run --no-capture-output -n agentic-graphrag python scripts/run_local_product.py
conda run --no-capture-output -n agentic-graphrag pytest tests/ -m "not integration"
~~~

Workbook commands:

~~~bash
python scripts/workbook.py prepare --workbook workbook --source source.html
python scripts/workbook.py validate --workbook workbook --encoding workbook/out/encoding.json
python scripts/workbook.py materialize --workbook workbook --encoding workbook/out/encoding.json
~~~

## Current implementation surfaces

| Path | Role |
|---|---|
| source_pipeline/ | source and workbook boundary |
| graph_storage/ | graph records, schema and materialization only |
| mcp_server/ | retrieval, traversal, proposals and HTTP/MCP surfaces |
| frontend/ | Graph and Logs UI |
| benchmarks/ | frozen measurements only |

## Repository hygiene

Generated graphs, sidecars, layouts, caches and run outputs are not source.
Opening a tracked Ladybug graph may modify it even during read-only inspection.
Preserve unrelated worktree changes and never restore graph binaries without
establishing their ownership.

Install the repository guard once per clone:

~~~bash
git config core.hooksPath scripts/hooks
~~~
