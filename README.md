# Graphauthor

Graphauthor is an open-source, source-cited graph context layer for agents.

A user supplies sources. An agent writes a normal program that authors the
graph representation useful for that user's work. Graphauthor provides source
preparation, a mechanical output boundary, deterministic graph traversal,
provenance, and proposal-based publication.

It does not claim to be a better general retrieval system. The value is that
accepted identities and relationships can be reused directly: an agent can
walk who belongs to an organisation, which paper disputes a claim, what code a
change affects, or which events connect two people without reconstructing those
relations from the source on every task.

## Construction is a workbook program

There is one construction model:

~~~text
sources
  -> workbook/atoms.jsonl          optional prepared view
  -> workbook/build.py             authored and run by the agent
  -> workbook/out/encoding.json    durable program output
  -> workbook/out/traversals.json  optional recurring context programs
  -> validation + materialization  host-owned, mechanical
  -> graph.lbug + source/traversal sidecars
~~~

The agent owns build.py. It may use Graphauthor's HTML, Markdown, PDF and text
parsers, write its own parser or segmenter, call a model, use other permitted
libraries, and iterate over the corpus many times. Graphauthor does not author
or execute that program.

The host checks only properties it can know mechanically: stable unique ids,
real edge endpoints, valid SST geometry, one SST geometry per predicate, and
provenance pointing to admitted workbook units (or an explicit reason that a
row is synthetic). It does not prescribe domain node kinds or predicates.
`GraphDraft` is an optional constructor-neutral helper for citation merging,
requirements, and semantic diffs; it does not infer the representation.

Prepare and inspect a workbook:

~~~bash
conda run --no-capture-output -n agentic-graphrag   python scripts/workbook.py prepare --workbook workbook   --source sources/page.html sources/paper.pdf

conda run --no-capture-output -n agentic-graphrag   python scripts/workbook.py stats --workbook workbook
~~~

After the agent writes and runs workbook/build.py:

~~~bash
python scripts/workbook.py validate --workbook workbook   --encoding workbook/out/encoding.json
python scripts/workbook.py audit --workbook workbook   --encoding workbook/out/encoding.json
python scripts/workbook.py materialize --workbook workbook   --encoding workbook/out/encoding.json
~~~

The workbook refuses a prepared atom stream if its source bytes have changed.
`audit` returns mechanical errors plus bidirectional coverage observations as
JSON. This supports an agent-owned edit → run → audit → repair loop without the
host executing arbitrary workbook code or pretending unused text is always a
construction failure.
The materialized graph travels with a source sidecar so cited units can be
resolved after the graph is moved.

## Encoding boundary

Nodes choose their own kind; edges choose their own semantic predicate and one
of four portable structural projections:

- LEADSTO: causal, sequential, temporal, or dependency
- CONTAINS: hierarchy, membership, or classification
- EXPRESSES: property, state, role, or assertion
- NEARTO: symmetric proximity, similarity, or conflict

The encoding is the construction record. LadybugDB is its traversal projection.

## Traversal

Retrieval is deterministic and model-free. Exact lookup stays exact; bounded
search returns candidates rather than pretending to prove absence. Agents can
compose bounded programs from lookup, expansion, paths, traversal, set
operations, filtering, sorting, limiting and projection.

Named traversals are versioned programs for recurring context jobs. A workbook
may emit them as `out/traversals.json`; materialization validates their kinds
and predicates against the observed encoding and binds the sidecar to its
encoding hash. This is not a domain format or a separately declared ontology.
Ephemeral traversals let an agent write a bounded program for a one-off
question. Every execution returns a graph-version-bound receipt.

For example, against a graph that declares the `about` predicate, an agent can
ask for a topic and its directly related material without inventing a new
server verb:

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

## Authority

- The agent interprets sources, chooses the representation, and authors the
  construction and traversal programs.
- The host pins source identity, validates output, executes bounded graph
  operations, and records receipts.
- A human controls publication of durable changes.

Parsers, segmenters and workbook programs never acquire graph-write authority.

## Product boundary

The first useful domains are deliberately different:

- narrative worlds: characters, places, events and chronology
- research: papers, claims, methods, citations and disagreements
- software: components, decisions, dependencies and change impact
- organisations or investigations: people, entities, events, evidence and
  explicit relationships

Graphauthor does not guarantee truth, completeness, freshness, universal ontology,
or superior retrieval. The property to improve is reliability of a user-chosen
relational representation: can it be built repeatably, traced to sources,
traversed exactly, inspected, repaired and reused in real agent work?

## Run

~~~bash
conda env create -f environment.yml
SST_DB_PATH=/absolute/path/to/graph.lbug   conda run --no-capture-output -n agentic-graphrag graphauthor-mcp
conda run --no-capture-output -n agentic-graphrag   python scripts/run_local_product.py
~~~

One process owns one graph file at a time. See [CLAUDE.md](CLAUDE.md) for
repository rules and [product/](product/) for the small product contract.

## Discover

Clone the public repository and add Graphauthor as an MCP server in Cursor
(or another MCP client) using [`.cursor/mcp.json.example`](.cursor/mcp.json.example).
Point `SST_DB_PATH` at a materialized `graph.lbug`. After that, `orient` is
the first tool: it reports the graph profile, named traversals, and the
operations the host will actually run.

A graph is discoverable the same way. Publication writes `graph.lbug` plus
source and traversal sidecars. An agent finds what the graph is for by
calling `orient` and `contract`, then running a named traversal when the
workbook declared one.

GitHub topics and the first paragraph of this README are how a stranger finds
the project. There is no marketplace listing yet. A later `pip install graphauthor`
would use the same package name.

## Repository layout

| Path | Role |
|---|---|
| source_pipeline/ | parser/segmenter protocols, supplied adapters, workbook, draft SDK and mechanical boundaries |
| scripts/workbook.py | prepare, inspect, validate and materialize a workbook |
| graph_storage/ | constructor-free Ladybug records and storage utilities |
| mcp_server/ | deterministic retrieval, traversal, proposals and receipts |
| frontend/ | Graph and Logs views |
| product/ | current product and traversal contracts |
| benchmarks/ | measurements, not product authority |
