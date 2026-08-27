# Graphauthor graph context layer

**Recorded:** 2026-08-25
**Status:** product direction for this branch

## Product claim

Graphauthor helps an agent and its user turn chosen sources into a reliable,
source-cited relational context layer, then reuse that layer through exact,
bounded traversal programs.

It is not a claim of superior general retrieval. Users choose graph form
because explicit identities and relationships are useful for their domain.
Graphauthor's duty is to make that representation repeatable, attributable,
inspectable, repairable and safe to publish.

## Primary workflow

1. The user gives an agent sources and a purpose.
2. A workbook pins the source bytes and may expose them through supplied or
   custom parsers and segmenters.
3. The agent writes and runs build.py. It may iterate, inspect coverage, call
   models, use libraries, or rewrite its source transformation.
4. The program emits encoding.json with domain-chosen kinds, predicates, SST
   projections and source-unit citations.
5. The host performs mechanical validation and materialization.
6. Agents reuse the accepted graph through named or ephemeral traversals.
7. Humans inspect sources, graph structure and changes before publication.

Construction is not one-shot. The program is the durable, revisable account of
how this source becomes this graph.

## Why a graph

The graph earns its cost when work repeatedly depends on relations that are
expensive or unreliable to reconstruct from prose each time. Examples:

- narrative worlds: who was where, which event caused another, chronology
- research: which paper supports or disputes a claim, method and citation paths
- software: component ownership, dependencies, decisions and change impact
- organisations/investigations: people, entities, events, evidence and links

These domains should drive experiments. They are not bundled schemas. A useful
construction program may choose radically different grain and vocabulary for
two corpora in the same domain.

## Product properties to optimize

- Traceability: every source-derived row resolves to admitted source units.
- Reproducibility: the program and pinned sources can rebuild the encoding.
- Relational utility: real tasks benefit from explicit identities and edges.
- Repairability: errors can be located in parser, segmentation, program,
  encoding or source, then rebuilt without hand-editing the graph.
- Bounded execution: traversal has explicit limits and honest empty/miss
  semantics.
- Human legibility: the graph and exact selected context can be inspected, but
  visualization remains secondary to backend capability.

Useful evaluations begin with a task benefit, freeze sources and questions,
compare representations, and inspect failure modes. They do not begin by
declaring a universal ontology or by testing whatever capability happens to
exist.

## Authority boundary

- Agent: interpretation, construction program, traversal program, conclusions.
- Host: source fingerprints, mechanical validation, deterministic execution,
  receipts and proposal storage.
- Human: publication and disputed semantic choices.

The host does not prescribe domain formats, adjudicate truth, or run hidden LLM
construction. The agent program can be powerful because its output boundary is
narrow and inspectable.

## Non-goals

- universal or automatically correct ontology
- completeness or freshness guarantees
- hosted collaboration and multi-user authorization
- arbitrary code execution by the server
- replacing vector, lexical or database retrieval in general
- visualizing every graph before relational utility is demonstrated
