"""MCP stdio transport — protocol plumbing over ``mcp_server.surface``.

Run:  SST_DB_PATH=/path/graph.lbug python -m mcp_server.stdio
Config env:
  SST_DB_PATH            — required; the .lbug this server owns
  SST_MCP_HANDBOOK       — optional conformance handbook name
  SST_MCP_STORE_PATH     — optional WritePathStore sidecar path
  SST_MCP_DEBUG_EVIDENCE — "1" to expose the debug_evidence tool (off by default)

The transport adds nothing to the contract: it lists the product verbs,
validates arguments minimally, and returns the surface's JSON verbatim.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from engine import EmptyGraphError, GraphInUseError
from mcp_server.retrieve import Retrieve
from mcp_server.surface import Surface

#: The agent surface. Retrieval is deterministic and zero-model; writes stop at
#: a proposal. Workbook construction runs in the agent's own session; this
#: server does not execute agent-authored code.

TOOLS: list[types.Tool] = [
    types.Tool(
        name="orient",
        description=(
            "Orientation for agents: graph profile, counts, landmarks, capabilities, "
            "graph_version, and named_traversal. Zero LLM. Call before multi-step "
            "reasoning and after any graph_version change. named_traversal is the "
            "format's optional policy: run default_traversal first when it is set, "
            "attach a receipt when required_traversals applies, and otherwise walk "
            "with lookup, expand, path, and search. Search is never an implicit "
            "fallback from an exact miss. Also returns `posture` — what THIS operator "
            "wants you to do when the graph does not decide (on_ungoverned, "
            "on_insufficient_evidence, on_violates, max_claim_level, notes). "
            "Posture is instruction, capabilities are authority: follow the "
            "posture, but it can never grant you a capability you lack. "
            "On VIOLATES specifically: stop work on THAT change. Do not "
            "re-query it, and do not author a rule or exception whose effect is "
            "to make YOUR OWN failing change pass — that is rationalization "
            "however good the argument, and it is flagged downstream. Escalate "
            "instead. This narrow case aside, proposing is normal and wanted. "
            "Returns `grain` when the graph has exemplars: what one node IS "
            "here, in the same {id,label,text_content} shape propose expects. "
            "Match it when drafting a proposal. context=capabilities is the cheapest "
            "contract view; graph_card adds landmarks and is the default; full_map "
            "adds per-node centrality."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "enum": ["capabilities", "graph_card", "full_map"],
                    "default": "graph_card",
                }
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="contract",
        description=(
            "Read the active user-owned graph.md semantic contract: format id/version, "
                    "node kinds, closed predicates, deterministic predicate-to-SST "
            "mapping, orientation and named traversal declarations. Zero LLM. "
            "ABSENT means this graph has no graph.md; INVALID_CONTRACT reports the "
            "validation error. Set include_markdown=false for a compact structured view."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "include_markdown": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="lookup",
        description=(
            "Resolve exact graph-native node IDs or exact labels, deterministically "
            "with zero LLM. Ad-hoc walks are allowed: point at a node and look it "
            "up. If graph.md names a default or required recipe for this job, run "
            "that first and use lookup to probe or page bodies afterwards. "
            "EXACT_MISS is terminal: do not widen the same request to search. "
            "Set include_content only when node bodies are needed. "
            "Optional orient compass_ref and graph_version are stale-plan "
            "preconditions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "references": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 1, "maxItems": 20,
                },
                "include_content": {"type": "boolean", "default": False},
                "context_ref": {"type": "string"},
                "graph_version": {"type": "string"},
            },
            "required": ["references"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="expand",
        description=(
            "Return a bounded typed neighbourhood around explicit stable node IDs, "
            "deterministically with zero LLM and no fallback. Ad-hoc walks are "
            "allowed: pass IDs, edge type, direction, depth, and optional labels. "
            "If graph.md names a recipe for this job, run_traversal first; expand "
            "is for extra hops that are not worth naming. UNRESOLVED_SEED is "
            "terminal and never widens. EMPTY means all seeds resolved but this "
            "exact bounded neighbourhood had none. A partial neighbourhood is not "
            "proof of whole-graph absence."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "node_ids": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 1, "maxItems": 50,
                },
                "edge_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["leadsto", "contains", "expresses", "nearto"]},
                },
                "direction": {
                    "type": "string", "enum": ["outgoing", "incoming", "both"],
                    "default": "both",
                },
                "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                "edge_labels": {
                    "type": "array", "items": {"type": "string"}, "maxItems": 20,
                },
                "include_content": {"type": "boolean", "default": False},
                "context_ref": {"type": "string"},
                "graph_version": {"type": "string"},
            },
            "required": ["node_ids"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="path",
        description=(
            "Find bounded existing paths between explicit source and target node IDs, "
            "deterministically with zero LLM and no fallback. Ad-hoc walks are "
            "allowed: pass stable IDs, edge types, and hop bound. Named recipes do "
            "not replace this for a one-off pair. UNRESOLVED_ENDPOINT is terminal. "
            "EMPTY means every endpoint resolved but no path exists within these "
            "bounds. Omitting edge_types searches all types; supply it when the "
            "task names one."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_ids": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 1, "maxItems": 20,
                },
                "target_ids": {
                    "type": "array", "items": {"type": "string"},
                    "minItems": 1, "maxItems": 20,
                },
                "edge_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["leadsto", "contains", "expresses", "nearto"]},
                },
                "max_hops": {"type": "integer", "minimum": 1, "maximum": 64, "default": 4},
                "include_content": {"type": "boolean", "default": False},
                "context_ref": {"type": "string"},
                "graph_version": {"type": "string"},
            },
            "required": ["source_ids", "target_ids"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="search",
        description=(
            "Return bounded semantic (default) or lexical candidates. "
            "Candidate-only. Search is an unbound primitive, not the default "
            "opening move when graph.md names a default_traversal. It never "
            "proves identity, authority, governance, completeness, or absence, "
            "and returns CANDIDATES or NO_CANDIDATES, never EMPTY. A recipe may "
            "fall back to search only when that recipe declares when/then. Use "
            "lookup for exact references and run_traversal for a named "
            "neighbourhood. semantic uses the optional embedding index and ranks "
            "by meaning; when that index is not built it refuses with "
            "SEARCH_UNAVAILABLE. Lexical is zero-cost term matching that drops "
            "short and stopword tokens, so prefer it for identifiers rather than "
            "for questions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "mode": {
                    "type": "string", "enum": ["lexical", "semantic"],
                    "default": "semantic",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8},
                "include_content": {"type": "boolean", "default": False},
                "context_ref": {"type": "string"},
                "graph_version": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="run_traversal",
        description=(
            "Run a versioned named traversal declared in the active graph.md. "
            "The harness validates parameters, deterministically compiles the "
            "recipe to retrieval-v1, and returns the exact evidence packet plus "
            "a recipe-, format-, graph-, and result-bound execution receipt. "
            "explain=true returns the compiled plan and estimated costs without "
            "executing. Repeated identical runs on an unchanged graph are served "
            "from an in-process cache. Zero LLM. EMPTY and EXACT_MISS are "
            "bounded outcomes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "integer", "minimum": 1},
                "parameters": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "evidence": {
                    "type": "string",
                    "enum": ["summary", "packet", "content"],
                    "default": "packet",
                },
                "graph_version": {"type": "string"},
                "explain": {"type": "boolean", "default": False},
            },
            "required": ["name", "parameters"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="run_ephemeral_traversal",
        description=(
            "Run a one-shot traversal program in the graph.md recipe vocabulary "
            "without declaring it. Same primitives, bounds, evidence packet and "
            "graph-bound receipt as run_traversal, but fingerprinted (tep_) not "
            "named: its receipt never satisfies a required traversal at propose, "
            "and it cannot take a declared recipe's name. Promote a recurring "
            "program by adding it to graph.md. Zero LLM; EMPTY and EXACT_MISS "
            "are bounded outcomes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "program": {
                    "type": "object",
                    "description": (
                        "{name?, steps: [{op, assign, ...}], collect, optional "
                        "when/then/then_collect, limits and project} using the "
                        "same ops as a graph.md traversal."
                    ),
                },
                "parameters": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "evidence": {
                    "type": "string",
                    "enum": ["summary", "packet", "content"],
                    "default": "packet",
                },
                "graph_version": {"type": "string"},
                "explain": {"type": "boolean", "default": False},
            },
            "required": ["program"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="retrieve",
        description=(
            "Execute a caller-authored retrieval-v1 program directly against the "
            "graph. Deterministic and zero LLM: use it when you already know the "
            "steps; use run_traversal for a recipe graph.md names, and search "
            "for a natural-language query. Read "
            "orient.retrieval first for supported tools, edge "
            "grammar and limits. Steps assign variables; later params use "
            "$variable references; collect joins variables with +. evidence=content "
            "late-pages bounded node bodies after the thin traversal. Zero matches "
            "is a valid receipt-visible observation and never widens implicitly; "
            "use an explicit bounded contingency when another attempt is justified. "
            "Pass a prior orient's graph_version and compass_ref as "
            "preconditions so a stale plan is refused before traversal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "program": {
                    "type": "object",
                    "description": (
                        "retrieval-v1 object: {contract_version, steps: "
                        "[{tool, params, assign_to}], collect, optional contingency "
                        "and limits}."
                    ),
                },
                "evidence": {
                    "type": "string",
                    "enum": ["summary", "packet", "content"],
                    "default": "content",
                },
                "context_ref": {"type": "string"},
                "graph_version": {"type": "string"},
            },
            "required": ["program"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="read_cypher",
        description=(
            "Run one read-only Cypher statement when no typed verb expresses "
            "the question — aggregation, arbitrary property predicates, a shape "
            "nobody anticipated. Read-only is enforced by the engine: the "
            "statement runs inside a read-only transaction, so a write is "
            "refused rather than filtered, and nothing here can propose or "
            "commit. Schema: node table Concept(id, label, kind, claim_kind, "
            "semantic_anchor, text_content, source_unit_ids, centrality_score, "
            "is_metanode); rel tables LEADSTO, CONTAINS, EXPRESSES, NEARTO, "
            "each (FROM Concept TO Concept, label). Embeddings are stripped "
            "from returned nodes. Rows, characters and wall-clock truncate "
            "visibly. Zero LLM. No rows means this query matched nothing on "
            "this graph version, never that the graph lacks the thing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "parameters": {"type": "object", "additionalProperties": True},
                "max_rows": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": 200000, "default": 20000},
                "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 60000, "default": 5000},
                "graph_version": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="history",
        description=(
            "Graph change history. action=versions lists snapshots; "
            "action=diff (v1, v2) returns a content-based structural delta "
            "(concepts/edges added, removed, changed); action=changed_since "
            "(version) diffs a snapshot against the live graph — call it when "
            "graph_version moved mid-task. Zero LLM. Revert is not available "
            "here: agents propose forward, operators move backward."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["versions", "diff", "changed_since"], "default": "versions"},
                "v1": {"type": "string"},
                "v2": {"type": "string"},
                "version": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="propose",
        description=(
            "Propose a graph-contract change. Valid proposals auto-commit; "
            "this tool does not leave a human confirm queue. Revert is the "
            "backward path. With graph.md, concepts require its node kind and "
            "edges use predicate/source_id/target_id; the harness validates "
            "endpoints and derives SST. Bind expected_graph_version to the "
            "context used for drafting. If graph.md lists required_traversals "
            "for the kinds you touch, attach a fresh run_traversal receipt or "
            "propose refuses. Use dry_run=true to validate shape, endpoints, "
            "collisions and grain without writing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "encoding": {
                    "type": "object",
                    "properties": {
                        "concepts": {"type": "array", "items": {"type": "object", "properties": {
                            "id": {"type": "string"}, "label": {"type": "string"},
                            "text_content": {"type": "string"}, "semantic_anchor": {"type": "string"},
                            "kind": {"type": "string"},
                            "claim_kind": {"type": "string", "enum": [
                                "governing", "contextual", "interpretation", "navigation"
                            ]}},
                            "required": ["id", "label", "text_content"]}},
                        "edges": {"type": "array", "items": {"type": "object", "properties": {
                            "type": {"type": "string", "enum": ["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]},
                            "source_id": {"type": "string"}, "target_id": {"type": "string"},
                            "predicate": {"type": "string"},
                            "label": {"type": "string"}},
                            "required": ["source_id", "target_id"]}},
                    },
                },
                "provenance": {"type": "object", "properties": {
                    "generating_task": {"type": "string"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                    "conversation_id": {"type": "string"},
                    "decision_origin": {
                        "type": "string",
                        "enum": ["unspecified", "recover_existing", "propose_new"],
                    }}},
                "target_gap_id": {"type": "string"},
                "expected_graph_version": {
                    "type": "string",
                    "description": (
                        "Opaque graph_version used to author the proposal; a "
                        "mismatch returns STALE_GRAPH before queueing"
                    ),
                },
                "traversal_receipt": {
                    "type": "object",
                    "description": (
                        "execution_receipt from run_traversal. Required when "
                        "graph.md required_traversals applies to the kinds you "
                        "touch; optional otherwise. The server reruns and "
                        "verifies it before queueing."
                    ),
                    "additionalProperties": True,
                },
                "claim_level": {"type": "string", "enum": ["L0", "L1"], "default": "L0"},
                "dry_run": {"type": "boolean", "default": False},
                "check_gate": {"type": "boolean", "default": False},
            },
            "required": ["encoding", "target_gap_id", "expected_graph_version"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="proposal_status",
        description=(
            "Check the state of a submitted proposal: COMMITTED "
            "(graph_version_after tells you what to re-query), GATE_FAILED / "
            "ENCODE_FAILED (graph restored, see gate_report), or PENDING when "
            "dry_run held the write. Zero LLM."
        ),
        inputSchema={
            "type": "object",
            "properties": {"proposal_id": {"type": "string"}},
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
    ),
]




def build_server(
    surface: Surface | None,
    transcript_path: str | None = None,
    transcript_level: str | None = None,
) -> Server:
    server = Server("graphauthor")
    retrieve = Retrieve(surface) if surface is not None else None
    level = (transcript_level or os.environ.get("SST_MCP_TRANSCRIPT_LEVEL") or "slim").strip().lower()

    def _log(name: str, arguments: dict, out: dict) -> None:
        """Append-only jsonl transcript.

        slim (default, unchanged): verdict-level response fields — supports
        LINKAGE auditing (which tool was called before which claim).
        full: the COMPLETE response as returned to the caller — supports
        CONTENT-level claim auditing (does the claim match what the tool
        said). The wire response is already capped and stripped by the
        surface, so full mode records exactly what the caller saw and
        nothing more (L2-4 session-1 operator finding: slim responses
        prevented content-level claim verification)."""
        if not transcript_path:
            return
        try:
            if level == "full":
                response: dict = out
            else:
                response = {k: out.get(k) for k in (
                    "verdict", "status", "kind", "error", "graph_version",
                    "proposal_id", "handoff_id", "ungoverned_predicate",
                    "engine_degraded", "trace_id") if k in out}
            with open(transcript_path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "tool": name, "level": level,
                                    "arguments": arguments, "response": response},
                                   default=str) + "\n")
        except Exception:
            pass  # transcripts must never break serving

    # An operator may serve a graph without the tools that go underneath the
    # graph.md vocabulary. Hidden, not stubbed: a tool that is listed and then
    # refuses reads as a broken server. A call that arrives anyway is answered
    # with an explicit refusal rather than an unknown-tool error, so the
    # transcript records that it was attempted -- which is the interesting
    # part when the question is what an agent reaches for.
    hidden_tools = {
        name.strip()
        for name in (os.environ.get("SST_MCP_HIDE_TOOLS") or "").split(",")
        if name.strip()
    }
    # `read_cypher` is withheld unless an operator asks for it. Two probe runs
    # on one graph: with it served, a strong model used it for twenty of
    # twenty-nine calls and authored a single traversal program, scoring six of
    # seven. With it withheld, the same model authored twenty programs and
    # scored seven of seven -- it tried the raw tool once, was told the graph
    # does not serve it, and never asked again.
    #
    # The preference is understandable and it is not a need. It also costs
    # something real: a Cypher answer carries a query fingerprint and no recipe
    # or format fingerprint, so it cannot satisfy the `required_traversals`
    # receipt that `propose` demands, and both shipped research formats declare
    # one. An answer reached that way cannot reach the write path.
    if os.environ.get("SST_MCP_RAW_QUERY", "").strip().lower() not in (
        "1", "true", "yes"
    ):
        hidden_tools.add("read_cypher")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        caps = set(getattr(surface, "_capabilities", ["query"]))
        out = []
        if surface is not None:
            for t in TOOLS:
                if t.name in ("propose", "proposal_status") and "propose" not in caps:
                    continue  # absent, not stubbed, until a write policy is configured
                if t.name == "history" and "history" not in caps:
                    continue
                if t.name in hidden_tools:
                    continue
                out.append(t)
        return out

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        args = arguments or {}
        if name in hidden_tools:
            out = {
                "kind": "TOOL_WITHHELD",
                "outcome": "TOOL_WITHHELD",
                "error": f"{name} is not served by this graph",
            }
            _log(name, args, out)
            return [types.TextContent(type="text", text=json.dumps(out))]
        if surface is None:
            out = {
                "error": (
                    f"{name} needs a graph, and SST_DB_PATH names no built one. "
                    "Build a workbook graph with scripts/workbook.py, then "
                    "restart with SST_DB_PATH pointing at it."
                )
            }
        elif name == "orient":
            out = surface.orient(context=args.get("context", "graph_card"))
        elif name == "contract":
            out = surface.contract(
                include_markdown=bool(args.get("include_markdown", True))
            )
        elif name == "lookup":
            out = retrieve.lookup(
                args["references"],
                include_content=bool(args.get("include_content", False)),
                context_ref=args.get("context_ref", ""),
                graph_version=args.get("graph_version", ""),
            )
        elif name == "expand":
            out = retrieve.expand(
                args["node_ids"],
                edge_types=args.get("edge_types"),
                direction=args.get("direction", "both"),
                depth=args.get("depth", 1),
                edge_labels=args.get("edge_labels"),
                include_content=bool(args.get("include_content", False)),
                context_ref=args.get("context_ref", ""),
                graph_version=args.get("graph_version", ""),
            )
        elif name == "path":
            out = retrieve.path(
                args["source_ids"],
                args["target_ids"],
                edge_types=args.get("edge_types"),
                max_hops=args.get("max_hops", 4),
                include_content=bool(args.get("include_content", False)),
                context_ref=args.get("context_ref", ""),
                graph_version=args.get("graph_version", ""),
            )
        elif name == "search":
            out = retrieve.search(
                args["query"],
                mode=args.get("mode", "semantic"),
                limit=args.get("limit", 8),
                include_content=bool(args.get("include_content", False)),
                context_ref=args.get("context_ref", ""),
                graph_version=args.get("graph_version", ""),
            )
        elif name == "run_traversal":
            out = surface.run_traversal(
                args["name"],
                args.get("parameters") or {},
                version=args.get("version"),
                evidence=args.get("evidence", "packet"),
                graph_version=args.get("graph_version", ""),
                explain=bool(args.get("explain", False)),
            )
        elif name == "run_ephemeral_traversal":
            out = surface.run_ephemeral_traversal(
                args["program"],
                args.get("parameters") or {},
                evidence=args.get("evidence", "packet"),
                graph_version=args.get("graph_version", ""),
                explain=bool(args.get("explain", False)),
            )
        elif name == "retrieve":
            out = surface.retrieve(
                args["program"],
                evidence=args.get("evidence", "content"),
                context_ref=args.get("context_ref", ""),
                graph_version=args.get("graph_version", ""),
            )
        elif name == "read_cypher":
            out = surface.read_cypher(
                args["query"],
                args.get("parameters") or {},
                max_rows=int(args.get("max_rows") or 200),
                max_chars=int(args.get("max_chars") or 20000),
                timeout_ms=int(args.get("timeout_ms") or 5000),
                graph_version=args.get("graph_version", ""),
            )
        elif name == "history":
            out = surface.history_action(args)
        elif name == "propose":
            out = surface.propose(
                encoding=args.get("encoding") or {},
                provenance=args.get("provenance"),
                target_gap_id=args.get("target_gap_id", ""),
                claim_level=args.get("claim_level", "L0"),
                dry_run=bool(args.get("dry_run", False)),
                check_gate=bool(args.get("check_gate", False)),
                expected_graph_version=args.get("expected_graph_version", ""),
                traversal_receipt=args.get("traversal_receipt"),
            )
        elif name == "proposal_status":
            out = surface.proposal_status(args.get("proposal_id", ""))
        else:
            out = {"error": f"unknown tool: {name}"}
        _log(name, args, out if isinstance(out, dict) else {})
        return [types.TextContent(type="text", text=json.dumps(out))]

    return server


async def _amain() -> None:
    db_path = os.environ.get("SST_DB_PATH", "")
    surface: Surface | None = None
    if db_path:
        try:
            surface = Surface(
                Path(db_path),
                handbook=os.environ.get("SST_MCP_HANDBOOK") or None,
                store_path=os.environ.get("SST_MCP_STORE_PATH") or None,
                enable_history=os.environ.get("SST_MCP_HISTORY", "1").strip().lower() not in ("0", "false", "no"),
                enable_proposals=os.environ.get("SST_MCP_PROPOSALS", "").strip().lower() in ("1", "true", "yes"),
            )
        except GraphInUseError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
        except EmptyGraphError:
            # Construction is out-of-process on this branch, so an empty graph is
            # a setup error here rather than the state a construction verb would
            # have repaired in place.
            print(
                f"no built graph at {db_path}; build one with "
                "scripts/workbook.py",
                file=sys.stderr,
            )
            raise SystemExit(2)
    if surface is None:
        print(
            "SST_DB_PATH is required and must name a built graph; build one "
            "with scripts/workbook.py",
            file=sys.stderr,
        )
        raise SystemExit(2)
    server = build_server(surface, transcript_path=os.environ.get("SST_MCP_TRANSCRIPT") or None)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
