# Graph harness mechanical contract

**Recorded:** 2026-08-25
**Status:** branch contract

## Construction boundary

A workbook contains:

~~~text
workbook.json       pinned sources and atom-stream producer
atoms.jsonl         optional shared addressable source view
build.py            agent-owned program; never authored or executed by host
out/encoding.json   canonical construction record
out/graph.lbug      traversal projection
out/graph.lbug.sources.json
~~~

The agent program may use Graphauthor parsers, custom parsers/segmenters, permitted
libraries and model calls. If it replaces the prepared atom stream, the
manifest records the actual producer so inspection and construction do not
silently use different source views.

The host validates only:

- concepts and edges are lists
- concept ids are non-empty and unique
- every concept declares a non-empty kind
- edge endpoints name concepts in the encoding
- every edge declares a semantic predicate
- sst_type is LEADSTO, CONTAINS, EXPRESSES or NEARTO
- each source-derived node and edge cites known source_unit_ids
- a source-free row instead gives a non-empty synthetic_reason
- a row cannot be both source-backed and synthetic

The host does not validate whether domain vocabulary, grain or interpretation
is good. Those properties require cases, task experiments and human judgement
outside the mechanical boundary.

## Source protocols

A parser pins input bytes and emits non-overlapping addressable units over its
canonical representation. A segmenter emits an exact partition of a unit.
Failure, abstention and oversized passthrough are explicit; neither extension
point can write a graph.

Supplied adapters cover HTML, Markdown, PDF and plain text. They are tools, not
mandatory paths. An agent program may use something else and must identify the
producer of the stream it actually consumes.

## Traversal contract

The stable read surface includes exact lookup, bounded expansion, bounded
paths, candidate search, named traversal and ephemeral traversal. Traversal is
deterministic, read-only and model-free.

- Exact miss is terminal for exact lookup.
- Search is candidate discovery and cannot prove absence.
- A completed bounded traversal may return a genuine empty result.
- Bounds and graph version are recorded in the execution receipt.

## Write aperture

Workbook materialization produces a provisional graph artifact. It does not
publish into an active graph. Durable changes enter through propose, which
validates and commits. ``confirm_proposal`` is the apply function; there is
no human approval queue. A declared encode battery is optional and, when
present, still restores the snapshot on red. Parser, segmenter, model and
agent capabilities do not widen this authority. Mechanical refusals
(invalid encoding, grain, convention, stale graph, cardinal correction)
remain errors. Revert restores an earlier snapshot.

## Storage

The encoding is the construction record. LadybugDB is a disposable traversal
projection. Source excerpts and locators travel in a sidecar. A stale workbook
is refused before materialization.

## Local limits

- one process owns one Ladybug graph at a time
- trusted local agent code; no server sandbox or remote code runner
- no completeness, truth or freshness guarantee
- no documentary-status policy in the mechanical boundary
- no resume/checkpoint protocol beyond what the agent writes in build.py
