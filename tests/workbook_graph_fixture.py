"""Constructor-free graph fixtures for traversal/runtime tests.

These are test data, not bundled domain formats. They exercise the transitional
graph-local recipe loader until recipe storage is separated from graph.md.
"""

from __future__ import annotations

from pathlib import Path

from graph_storage.records import GraphEdge, MaterializedGraph, GraphNode
from graph_storage.writer import write_graph_records


def _node(node_id: str, kind: str, label: str) -> GraphNode:
    return GraphNode(id=node_id, kind=kind, label=label, text_content=label)


PERSONAL_RECIPE_CONTRACT = """---
format_id: workbook-research-fixture
format_version: 1
review_mode: exceptions
required_traversals:
  - recipe: prepare_topic_edit
    when_kinds: [topic, claim, question]
    parameter: topic_id
node_kinds:
  paper: {id_pattern: "paper:<slug>"}
  topic: {id_pattern: "topic:<slug>"}
  claim: {id_pattern: "claim:<slug>"}
  question: {id_pattern: "question:<slug>"}
predicates:
  cites:
    {sst: LEADSTO, directed: true, source_kinds: [paper], target_kinds: [paper]}
  asserts:
    {sst: EXPRESSES, directed: true, source_kinds: [paper], target_kinds: [claim]}
  supports:
    {sst: LEADSTO, directed: true, source_kinds: [claim], target_kinds: [claim]}
  contradicts:
    {sst: NEARTO, symmetric: true, source_kinds: [claim], target_kinds: [claim]}
  about:
    {sst: NEARTO, symmetric: true, source_kinds: [claim, question], target_kinds: [topic]}
orientation:
  pinned_nodes: []
  default_traversal: prepare_topic_edit
traversals:
  prepare_topic_edit:
    version: 1
    parameters:
      topic_id: {type: node_id, kinds: [topic, claim, question]}
    steps:
      - {op: lookup, references: [$topic_id], assign: seed}
      - op: traverse
        from: $seed
        strategy: bfs
        sst_types: [NEARTO]
        direction: both
        max_depth: 2
        max_nodes: 30
        assign: region
      - op: expand
        from: $region
        predicates: [supports, contradicts, cites, asserts]
        direction: both
        depth: 1
        max_nodes: 30
        assign: evidence
    collect: "$seed + $region + $evidence"
    limits: {max_steps: 8, max_hops: 3, max_nodes: 50}
    empty_means: bounded_no_result
---
# Graph-local recipe fixture
"""


def personal_graph() -> MaterializedGraph:
    nodes = {
        row.id: row for row in [
            _node("topic:named-traversal", "topic", "Named traversal"),
            _node("question:review-context", "question", "Review context"),
            _node("paper:graph-retrieval-survey", "paper", "Graph Retrieval Survey"),
            _node("paper:human-ai-provenance", "paper", "Human-AI Provenance"),
            _node("claim:edges-select-context", "claim", "Edges select context"),
            _node("claim:receipts-bind-observation", "claim", "Receipts bind observations"),
            _node("claim:reviewed-mutation", "claim", "Reviewed mutation"),
        ]
    }
    edges = [
        GraphEdge("claim:edges-select-context", "topic:named-traversal", "nearto", "about"),
        GraphEdge("claim:receipts-bind-observation", "topic:named-traversal", "nearto", "about"),
        GraphEdge("question:review-context", "topic:named-traversal", "nearto", "about"),
        GraphEdge("paper:graph-retrieval-survey", "claim:edges-select-context", "expresses", "asserts"),
        GraphEdge("paper:human-ai-provenance", "claim:receipts-bind-observation", "expresses", "asserts"),
        GraphEdge("paper:human-ai-provenance", "claim:reviewed-mutation", "expresses", "asserts"),
        GraphEdge("claim:receipts-bind-observation", "claim:reviewed-mutation", "leadsto", "supports"),
        GraphEdge("paper:human-ai-provenance", "paper:graph-retrieval-survey", "leadsto", "cites"),
    ]
    return MaterializedGraph(id="workbook-research-fixture", domain="research", nodes=nodes, edges=edges)


NARRATIVE_RECIPE_CONTRACT = """---
format_id: workbook-narrative-fixture
format_version: 1
review_mode: exceptions
required_traversals: []
node_kinds:
  character: {id_pattern: "character:<slug>"}
  faction: {id_pattern: "faction:<slug>"}
  event: {id_pattern: "event:<slug>"}
  place: {id_pattern: "place:<slug>"}
predicates:
  causes:
    {sst: LEADSTO, directed: true, source_kinds: [event], target_kinds: [event]}
  includes:
    {sst: CONTAINS, directed: true, source_kinds: [faction], target_kinds: [character]}
  participates_in:
    {sst: EXPRESSES, directed: true, source_kinds: [character], target_kinds: [event]}
  occurs_at:
    {sst: EXPRESSES, directed: true, source_kinds: [event], target_kinds: [place]}
traversals:
  how_are_they_connected:
    version: 1
    parameters:
      from_id: {type: node_id, kinds: [character, faction, event, place]}
      to_id: {type: node_id, kinds: [character, faction, event, place]}
    steps:
      - {op: lookup, references: [$from_id], assign: left}
      - {op: lookup, references: [$to_id], assign: right}
      - {op: find_paths, from: $left, to: $right, direction: both, max_hops: 5, assign: paths}
    collect: "$left + $right + $paths"
    answers: [paths]
    limits: {max_steps: 8, max_hops: 5, max_nodes: 60}
  what_led_to:
    version: 1
    parameters:
      event_id: {type: node_id, kinds: [event]}
    steps:
      - {op: lookup, references: [$event_id], assign: seed}
      - {op: traverse, from: $seed, strategy: bfs, predicates: [causes], direction: incoming, max_depth: 4, max_nodes: 40, assign: antecedents}
      - {op: expand, from: $antecedents, predicates: [participates_in, occurs_at], direction: both, depth: 1, max_nodes: 40, assign: cast}
    collect: "$seed + $antecedents + $cast"
    limits: {max_steps: 8, max_hops: 5, max_nodes: 80}
  who_bridges:
    version: 1
    parameters:
      left_id: {type: node_id, kinds: [faction, event]}
      right_id: {type: node_id, kinds: [faction, event]}
    steps:
      - {op: lookup, references: [$left_id], assign: left_seed}
      - {op: lookup, references: [$right_id], assign: right_seed}
      - {op: expand, from: $left_seed, direction: both, depth: 1, max_nodes: 60, kinds: [character], assign: left_side}
      - {op: expand, from: $right_seed, direction: both, depth: 1, max_nodes: 60, kinds: [character], assign: right_side}
      - {op: intersection, of: $left_side, with: $right_side, assign: bridges}
    collect: "$bridges"
    answers: [bridges]
    limits: {max_steps: 8, max_hops: 3, max_nodes: 60}
  who_was_at_both_places:
    version: 1
    parameters:
      left_id: {type: node_id, kinds: [place]}
      right_id: {type: node_id, kinds: [place]}
    steps:
      - {op: lookup, references: [$left_id], assign: left_seed}
      - {op: lookup, references: [$right_id], assign: right_seed}
      - {op: expand, from: $left_seed, predicates: [occurs_at], direction: incoming, depth: 1, max_nodes: 60, kinds: [event], assign: left_events}
      - {op: expand, from: $left_events, predicates: [participates_in], direction: incoming, depth: 1, max_nodes: 60, kinds: [character], assign: left_side}
      - {op: expand, from: $right_seed, predicates: [occurs_at], direction: incoming, depth: 1, max_nodes: 60, kinds: [event], assign: right_events}
      - {op: expand, from: $right_events, predicates: [participates_in], direction: incoming, depth: 1, max_nodes: 60, kinds: [character], assign: right_side}
      - {op: intersection, of: $left_side, with: $right_side, assign: bridges}
    collect: "$bridges"
    answers: [bridges]
    limits: {max_steps: 10, max_hops: 4, max_nodes: 120}
---
# Graph-local recipe fixture
"""


def narrative_graph() -> MaterializedGraph:
    nodes = {
        row.id: row for row in [
            _node("character:ilma", "character", "Ilma"),
            _node("character:torv", "character", "Torv"),
            _node("character:hesk", "character", "Hesk"),
            _node("faction:the-quay", "faction", "The Quay"),
            _node("faction:the-uplands", "faction", "The Uplands"),
            _node("event:the-summons", "event", "The Summons"),
            _node("event:the-refusal", "event", "The Refusal"),
            _node("event:the-tally-count", "event", "The Tally Count"),
            _node("event:the-breaking", "event", "The Breaking"),
            _node("place:the-landing", "place", "The Landing"),
            _node("place:the-terrace", "place", "The Terrace"),
        ]
    }
    edges = [
        GraphEdge("event:the-summons", "event:the-refusal", "leadsto", "causes"),
        GraphEdge("event:the-refusal", "event:the-breaking", "leadsto", "causes"),
        GraphEdge("faction:the-quay", "character:ilma", "contains", "includes"),
        GraphEdge("faction:the-uplands", "character:ilma", "contains", "includes"),
        GraphEdge("faction:the-uplands", "character:torv", "contains", "includes"),
        GraphEdge("character:ilma", "event:the-summons", "expresses", "participates_in"),
        GraphEdge("character:torv", "event:the-summons", "expresses", "participates_in"),
        GraphEdge("character:ilma", "event:the-refusal", "expresses", "participates_in"),
        GraphEdge("character:ilma", "event:the-breaking", "expresses", "participates_in"),
        GraphEdge("character:torv", "event:the-breaking", "expresses", "participates_in"),
        GraphEdge("character:hesk", "event:the-tally-count", "expresses", "participates_in"),
        GraphEdge("event:the-refusal", "place:the-landing", "expresses", "occurs_at"),
        GraphEdge("event:the-tally-count", "place:the-landing", "expresses", "occurs_at"),
        GraphEdge("event:the-breaking", "place:the-terrace", "expresses", "occurs_at"),
    ]
    return MaterializedGraph(id="workbook-narrative-fixture", domain="narrative", nodes=nodes, edges=edges)


def write_graph_with_recipe_contract(
    out: Path,
    *,
    graph: MaterializedGraph,
    contract_text: str,
) -> tuple[Path, Path]:
    write_graph_records(out, graph, embed=False)
    contract = out.with_suffix(".recipes.md")
    contract.write_text(contract_text)
    return out, contract


def personal_fixture(out: Path) -> tuple[Path, Path]:
    return write_graph_with_recipe_contract(
        out, graph=personal_graph(), contract_text=PERSONAL_RECIPE_CONTRACT
    )


def narrative_fixture(out: Path) -> tuple[Path, Path]:
    return write_graph_with_recipe_contract(
        out, graph=narrative_graph(), contract_text=NARRATIVE_RECIPE_CONTRACT
    )
