"""Canonical, deterministic retrieval-program contract.

One program can be authored by product code, a calling agent, the Planner, a
Squad recovery pass, or a human.  Authorship changes; validation, execution and
the EvidencePacket do not.

This module intentionally contains no LLM calls and no routing policy.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend_tools import (
    SUPPORTED_TOOL_NAMES,
    _resolve_collect,
    _resolve_variable,
    build_evidence_packet,
    execute_tool,
)
from engine import get_structural_index
from models import ContingencySpec, RetrievalStep


RETRIEVAL_PROGRAM_VERSION = "retrieval-v1"
MAX_PROGRAM_STEPS = 12
_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_ASSIGNMENT = re.compile(rf"^{_NAME_PATTERN}$")
_REFERENCE = re.compile(rf"^\$({_NAME_PATTERN})$")
_COLLECT_EXPRESSION = re.compile(
    rf"^\s*\${_NAME_PATTERN}(?:\s*[+\-&]\s*\${_NAME_PATTERN})*\s*$"
)


class RetrievalLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=MAX_PROGRAM_STEPS, ge=1, le=MAX_PROGRAM_STEPS)
    # The ceiling was 6, which made a true answer unreachable rather than
    # expensive: a causal chain 30 hops long on a real saga graph could not be
    # walked by any program, named or one-shot, whatever it asked for. The
    # ceiling was not buying safety either -- `get_neighbourhood`,
    # `traverse_chain` and `find_paths` are all BFS with a visited set, so
    # their cost is bounded by the graph, not by the hop count, and
    # `find_paths` stops at the first path per endpoint pair. The real bound
    # is `max_nodes_per_step`. `walk_sequence` is the one op whose intermediate
    # state grows multiplicatively, and it is bounded directly in `tools.py`
    # rather than by holding every other op down to six hops.
    #
    # The default stays 4: modest by default, and `bounds_applied` now says
    # when it bound, so a caller who needs more can see that they need it.
    max_hops_per_step: int = Field(default=4, ge=1, le=64)
    max_nodes_per_step: int = Field(default=300, ge=1, le=3000)
    max_results_per_search: int = Field(default=25, ge=1, le=100)
    max_recovery_rounds: int = Field(default=1, ge=0, le=2)


class CanonicalRetrievalProgram(BaseModel):
    """The only executable retrieval representation.

    ``expected_coverage`` is deliberately soft.  It tells a later critic what
    the author hoped to cover, but it cannot alter tool execution or turn an
    incomplete packet into a factual verdict.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["retrieval-v1"] = RETRIEVAL_PROGRAM_VERSION
    author: Literal["direct", "planner", "contract_lowering", "squad", "human"] = "direct"
    steps: list[RetrievalStep]
    collect: str = ""
    contingency: ContingencySpec = Field(default_factory=ContingencySpec)
    expected_coverage: list[str] = Field(default_factory=list)
    limits: RetrievalLimits = Field(default_factory=RetrievalLimits)

    @field_validator("expected_coverage", mode="before")
    @classmethod
    def _coverage_strings(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @model_validator(mode="after")
    def _validate_program(self):
        all_steps = list(self.steps) + list(self.contingency.fallback_steps)
        if not self.steps:
            raise ValueError("retrieval program requires at least one step")
        if len(all_steps) > self.limits.max_steps:
            raise ValueError(
                f"program has {len(all_steps)} steps; limit is {self.limits.max_steps}"
            )

        # Assignment names are unique WITHIN the primary steps and WITHIN the
        # fallback steps — but a fallback may rebind a name the primary path
        # assigned, because that is what a fallback IS: another way to fill the
        # same slot. Checking uniqueness across the combined list rejected the
        # single most natural contingency the Planner emits —
        #
        #   steps:          exact_node_lookup  -> rule_node     collect $rule_node
        #   fallback_steps: lexical_search     -> rule_node     fallback_collect $rule_node
        #
        # and `fallback_collect` can only reference the name it rebinds, so the
        # rule made a documented field unusable. The failure was invisible in
        # the worst way: the ValidationError surfaced as `ABSENT` with empty
        # grounding and an `engine_fault` flag, which reads as "the graph does
        # not cover this" — a crash wearing an answer's clothes.
        n_primary = len(self.steps)
        seen: tuple[set[str], set[str]] = (set(), set())
        available: set[str] = set()
        for index, step in enumerate(all_steps):
            tool = str(step.tool or "").strip().lower()
            if tool not in SUPPORTED_TOOL_NAMES:
                raise ValueError(f"step {index} uses unsupported tool {tool!r}")
            if not _ASSIGNMENT.fullmatch(str(step.assign_to or "")):
                raise ValueError(f"step {index} has invalid assign_to {step.assign_to!r}")
            scope = seen[1] if index >= n_primary else seen[0]
            if step.assign_to in scope:
                raise ValueError(f"duplicate assignment {step.assign_to!r}")
            for reference in _references(step.params):
                if reference not in available:
                    raise ValueError(
                        f"step {index} references ${reference} before it is assigned"
                    )
            scope.add(step.assign_to)
            available.add(step.assign_to)

        # Collection is deliberately a tiny set algebra: left-to-right union,
        # difference, and intersection. `_resolve_collect` used to scan for recognised
        # `+`/`-` tokens and ignore everything else, so an agent-authored
        # `$left & $right` program validated and executed as `$left`.  That is
        # an unsupported operator wearing a successful receipt.  Validate the
        # whole expression before extracting references; empty remains legal
        # for compatibility with exploratory programs that collect implicitly.
        if self.collect and not _COLLECT_EXPRESSION.fullmatch(self.collect):
            raise ValueError(
                "unsupported collect expression; use only $variable joined "
                "by + (union), - (difference), or & (intersection)"
            )
        collect_refs = _collect_references(self.collect)
        unknown_collect = collect_refs - available
        if unknown_collect:
            raise ValueError(
                "collect references unknown variables: "
                + ", ".join(sorted(unknown_collect))
            )
        fallback_collect = str(self.contingency.fallback_collect or "")
        if fallback_collect and not _COLLECT_EXPRESSION.fullmatch(fallback_collect):
            raise ValueError(
                "unsupported fallback_collect expression; use only $variable "
                "joined by + (union), - (difference), or & (intersection)"
            )
        unknown_fallback = _collect_references(fallback_collect) - available
        if unknown_fallback:
            raise ValueError(
                "fallback_collect references unknown variables: "
                + ", ".join(sorted(unknown_fallback))
            )
        return self


def retrieval_capability_card() -> dict[str, Any]:
    """Compact, stable instructions for an agent authoring a direct program."""
    return {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "execution": "deterministic_zero_llm",
        "edge_types": ["leadsto", "contains", "expresses", "nearto"],
        "tools": sorted(SUPPORTED_TOOL_NAMES),
        "references": (
            "Assign every step to a variable; later params reference it as "
            "$variable. collect is a + expression over assigned variables."
        ),
        "default_limits": RetrievalLimits().model_dump(),
        "content": (
            "Traversal is anchor-thin. Request evidence=content to page the "
            "selected node bodies after traversal."
        ),
        "empty_result": {
            "meaning": "valid_bounded_observation",
            "policy": (
                "Zero matches is not an execution failure and never authorizes "
                "implicit widening. Inspect collected_node_count, empty_variables, "
                "and resolve_miss_count; author an explicit bounded contingency "
                "when another retrieval is justified."
            ),
        },
        "proof": {
            "success_evidence": "path_record",
            "empty_policy": (
                "A genuine proof request with no returned path stays an empty "
                "proof; it is not silently converted into endpoint lookup."
            ),
        },
        "judgment_view": {
            "packet_truth": "append_only",
            "applies_to": ["coverage_lookup", "ruling_lookup"],
            "bypasses": [
                "enumeration",
                "fanout",
                "proof",
                "chain",
                "count",
                "content_arithmetic",
                "confirmation",
            ],
            "policy": (
                "Prompt budgeting may project a smaller auditable view for "
                "governance lookup judgment; it never trims the EvidencePacket."
            ),
        },
        "terminal_outcomes": {
            "discover": ["ILL_POSED", "EXHAUSTED", "UNKNOWN_TO_GRAPH"],
            "policy": (
                "These are completed evidence outcomes, not instructions to "
                "retry, widen traversal, or invent a connection."
            ),
        },
    }


def _references(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        match = _REFERENCE.fullmatch(value.strip())
        if match:
            found.add(match.group(1))
    elif isinstance(value, list):
        for item in value:
            found |= _references(item)
    elif isinstance(value, dict):
        for item in value.values():
            found |= _references(item)
    return found


def _collect_references(expression: str) -> set[str]:
    return set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]{0,63})", str(expression or "")))


def _safe_trigger(trigger: str, variables: dict[str, list], program_context: dict) -> bool:
    text = str(trigger or "").strip()
    if not text or text.lower() == "false":
        return False
    if text.lower() == "true":
        return True

    strategy_a = program_context.get("strategy_a") or {}
    strategy_b = program_context.get("strategy_b") or {}
    text = text.replace(
        "strategy_a.concepts.count", str(len(strategy_a.get("concepts") or []))
    ).replace(
        "strategy_b.concepts.count", str(len(strategy_b.get("concepts") or []))
    )
    for name in sorted(variables, key=len, reverse=True):
        value = variables.get(name)
        count = len(value) if isinstance(value, list) else 0
        # Planner outputs in the wild use both ``results.count == 0`` and
        # JavaScript-like ``$results == null`` for the same empty-result test.
        # They are surface syntax over one value: the deterministic result
        # count.  Normalise before parsing; no variable value is ever eval'd.
        text = re.sub(
            rf"\$?{re.escape(name)}\s*(?:==|is)\s*(?:null|none)",
            str(count == 0),
            text,
            flags=re.IGNORECASE,
        )
        text = text.replace(f"${name}.count", str(count))
        text = text.replace(f"{name}.count", str(count))
        text = re.sub(rf"\${re.escape(name)}\b", str(count), text)
    text = re.sub(r"\bnull\b", "None", text, flags=re.IGNORECASE)
    text = text.replace(" AND ", " and ").replace(" OR ", " or ")

    def evaluate(node: ast.AST) -> bool | int:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.BoolOp):
            values = [bool(evaluate(item)) for item in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not bool(evaluate(node.operand))
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = int(evaluate(node.left))
            right = int(evaluate(node.comparators[0]))
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.Lt):
                return left < right
        if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int)):
            return node.value
        if isinstance(node, ast.Name) and node.id.lower() in {"true", "false"}:
            return node.id.lower() == "true"
        raise ValueError(f"unsupported contingency expression: {type(node).__name__}")

    try:
        tree = ast.parse(text, mode="eval")
        return bool(evaluate(tree))
    except Exception:
        return False


def _resolve_params(params: dict, variables: dict[str, list]) -> dict:
    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str) and value.startswith("$"):
            resolved[key] = _resolve_variable(value, variables)
        elif isinstance(value, list):
            items: list[Any] = []
            for item in value:
                if isinstance(item, str) and item.startswith("$"):
                    items.extend(_resolve_variable(item, variables))
                else:
                    items.append(item)
            resolved[key] = items
        else:
            resolved[key] = value
    return resolved


def _apply_limits(
    params: dict, tool: str, limits: RetrievalLimits
) -> tuple[dict, list[dict]]:
    """Bound one step's parameters, and say which bounds actually bound.

    The clamps below were silent. A probe agent asked a `traverse` step for
    `max_depth: 8`, received a six-node answer to a question whose true answer
    is forty-one events thirty hops down, and was told `truncated: false` --
    because `truncated` reports packet *projection*, which is a different
    thing from the walk being cut short. It noticed anyway and dropped to raw
    Cypher, which is the expensive way to find out.

    Only a clamp that changed what the caller asked for is recorded. Filling
    in a default is not evidence of anything; being given less than you asked
    for is.
    """
    bounded = dict(params)
    clamps: list[dict] = []

    def _clamp(key: str, requested, applied) -> None:
        if requested is not None and applied != requested:
            clamps.append({"param": key, "requested": requested, "applied": applied})

    if tool in {"vector_search", "lexical_search", "id_pattern_lookup"}:
        bounded["k"] = min(
            max(1, int(bounded.get("k", 5))), limits.max_results_per_search
        )
    if tool == "get_neighbourhood":
        asked_depth = bounded.get("depth")
        bounded["depth"] = min(
            max(1, int(bounded.get("depth", 1))), limits.max_hops_per_step
        )
        _clamp("depth", asked_depth, bounded["depth"])
        asked_nodes = bounded.get("max_nodes")
        bounded["max_nodes"] = min(
            max(1, int(bounded.get("max_nodes", limits.max_nodes_per_step))),
            limits.max_nodes_per_step,
        )
        _clamp("max_nodes", asked_nodes, bounded["max_nodes"])
    if tool == "find_paths":
        asked_hops = bounded.get("max_hops")
        bounded["max_hops"] = min(
            max(1, int(bounded.get("max_hops", 6))), limits.max_hops_per_step
        )
        _clamp("max_hops", asked_hops, bounded["max_hops"])
    if tool == "traverse_chain":
        asked_depth = bounded.get("max_depth")
        bounded["max_depth"] = min(
            max(1, int(bounded.get("max_depth", 5))), limits.max_hops_per_step
        )
        _clamp("max_depth", asked_depth, bounded["max_depth"])
    if tool == "walk_sequence":
        hops = list(bounded.get("hops") or [])
        if len(hops) > limits.max_hops_per_step:
            bounded["hops"] = hops[: limits.max_hops_per_step]
            _clamp("hops", len(hops), limits.max_hops_per_step)
        asked_nodes = bounded.get("max_nodes")
        bounded["max_nodes"] = min(
            max(1, int(bounded.get("max_nodes", limits.max_nodes_per_step))),
            limits.max_nodes_per_step,
        )
        _clamp("max_nodes", asked_nodes, bounded["max_nodes"])
    if tool == "select_landmarks":
        bounded["limit"] = min(
            max(1, int(bounded.get("limit", 8))), limits.max_nodes_per_step
        )
    if tool == "limit_nodes":
        bounded["limit"] = min(
            max(0, int(bounded.get("limit", 0))), limits.max_nodes_per_step
        )
    return bounded, clamps


def _legacy_program_payload(raw: dict, *, author: str) -> dict:
    steps = list(raw.get("steps") or [])
    contingency = raw.get("contingency") or {}
    assigned = [str(step.get("assign_to")) for step in steps if step.get("assign_to")]
    collect = str(raw.get("collect") or "")
    if not collect:
        collect = " + ".join(f"${name}" for name in assigned)
    expected = raw.get("expected_coverage") or []
    answer_contract = raw.get("answer_contract") or {}
    if not expected and isinstance(answer_contract, dict):
        expected = [str(item) for item in answer_contract.get("hypotheses") or []]
    return {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "author": author,
        "steps": steps,
        "collect": collect,
        "contingency": contingency,
        "expected_coverage": expected,
        "limits": raw.get("limits") or {},
    }


def canonicalise_program(raw: dict, *, author: str = "direct") -> CanonicalRetrievalProgram:
    """Validate a direct program or project the executable part of PlannerOutput."""
    if not isinstance(raw, dict):
        raise ValueError("retrieval program must be an object")
    if raw.get("contract_version") == RETRIEVAL_PROGRAM_VERSION:
        payload = dict(raw)
        payload.setdefault("author", author)
    else:
        payload = _legacy_program_payload(raw, author=author)
    return CanonicalRetrievalProgram.model_validate(payload)


def lower_relational_contract(contract: dict) -> CanonicalRetrievalProgram:
    """Compatibility lowering from the legacy Pipeline-B contract.

    The lowering is deterministic: the LLM is never asked to author both a
    program and a second independently executable representation.
    """
    c = dict(contract or {})
    form = str(c.get("question_form") or "lookup").lower()
    sources = [str(item) for item in c.get("source_ids") or [] if str(item)]
    targets = [str(item) for item in c.get("target_ids") or [] if str(item)]
    edge_types = [str(item).lower() for item in c.get("edge_types") or [] if str(item)]
    direction = str(c.get("direction") or "outgoing").lower()
    if direction not in {"outgoing", "incoming", "both"}:
        direction = "outgoing"
    max_hops = max(1, min(int(c.get("max_hops") or 1), 4))
    steps: list[dict] = []
    collected: list[str] = []
    contingency: dict[str, Any] = {}

    if form == "enumeration" and not sources:
        for index, edge_type in enumerate(edge_types or ["leadsto", "contains", "expresses", "nearto"]):
            name = f"enumeration_{index}_{edge_type}"
            steps.append({
                "tool": "get_nodes_by_edge_type",
                "params": {"edge_type": edge_type},
                "assign_to": name,
            })
            collected.append(name)
    else:
        steps.append({
            "tool": "exact_node_lookup",
            "params": {"label_or_id": sources},
            "assign_to": "sources",
        })
        collected.append("sources")

        if form == "lookup" and bool(c.get("exact_only")):
            # A schema-rejected lookup still has useful identity evidence, but
            # an empty edge-type list must not widen into an all-edge sweep.
            pass
        elif form == "proof":
            steps.append({
                "tool": "exact_node_lookup",
                "params": {"label_or_id": targets},
                "assign_to": "targets",
            })
            steps.append({
                "tool": "find_paths",
                "params": {
                    "source_set": "$sources",
                    "target_set": "$targets",
                    "max_hops": max_hops,
                    "edge_types": edge_types,
                },
                "assign_to": "paths",
            })
            collected.extend(["targets", "paths"])
        elif form == "chain" and c.get("steps"):
            previous = "$sources"
            for index, hop in enumerate(c.get("steps") or []):
                name = f"chain_{index + 1}"
                params = {
                    "node_ids": previous,
                    "depth": max(1, min(int(hop.get("max_hops") or 1), 4)),
                    "edge_types": [str(item).lower() for item in hop.get("edge_types") or []],
                    "direction": str(hop.get("direction") or "outgoing").lower(),
                    "edge_labels": list(hop.get("edge_labels") or []),
                }
                steps.append({"tool": "get_neighbourhood", "params": params, "assign_to": name})
                collected.append(name)
                previous = f"${name}"
            # Preserve the old Pipeline-B bounded micro-retry without hiding it
            # inside a tool.  A chain whose terminal hop is empty is replayed
            # once with symmetric direction and without guessed labels.  The
            # canonical receipt records that the contingency fired.
            fallback_steps: list[dict] = []
            previous = "$sources"
            for index, hop in enumerate(c.get("steps") or []):
                name = f"chain_{index + 1}"
                fallback_steps.append({
                    "tool": "get_neighbourhood",
                    "params": {
                        "node_ids": previous,
                        "depth": max(1, min(int(hop.get("max_hops") or 1), 4)),
                        "edge_types": [
                            str(item).lower()
                            for item in hop.get("edge_types") or []
                        ],
                        "direction": "both",
                        "edge_labels": [],
                    },
                    "assign_to": name,
                })
                previous = f"${name}"
            terminal_name = f"chain_{len(c.get('steps') or [])}"
            contingency = {
                "trigger": f"${terminal_name}.count == 0",
                "fallback_steps": fallback_steps,
                "fallback_collect": " + ".join(
                    ["$sources"]
                    + [f"$chain_{i + 1}" for i in range(len(fallback_steps))]
                ),
            }
        else:
            steps.append({
                "tool": "get_neighbourhood",
                "params": {
                    "node_ids": "$sources",
                    "depth": max_hops,
                    "edge_types": edge_types,
                    "direction": direction,
                },
                "assign_to": "neighbourhood",
            })
            collected.append("neighbourhood")
            # A Planner direction error must not turn a source-only packet into
            # a successful relation answer. Retry the same typed traversal once
            # in both directions; never widen edge types here.
            if direction != "both":
                contingency = {
                    "trigger": "$neighbourhood.count == 0",
                    "fallback_steps": [{
                        "tool": "get_neighbourhood",
                        "params": {
                            "node_ids": "$sources",
                            "depth": max_hops,
                            "edge_types": edge_types,
                            "direction": "both",
                        },
                        "assign_to": "neighbourhood",
                    }],
                    "fallback_collect": "$sources + $neighbourhood",
                }

    return CanonicalRetrievalProgram.model_validate({
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "author": "contract_lowering",
        "steps": steps,
        "collect": " + ".join(f"${name}" for name in collected),
        "contingency": contingency,
        "expected_coverage": [],
    })


def program_for_targeted_state(state: dict) -> CanonicalRetrievalProgram:
    """Compile targeted retrieval from its one semantic contract.

    Planner ``steps`` belong to the exploratory route.  Executing them on
    Pipeline B while using ``relational_contract`` for verdicts created two
    independent truths: a governance proof could be demoted to lookup in the
    contract yet still execute the Planner's stale ``find_paths`` program.
    Targeted retrieval therefore always lowers the sanitised contract into the
    canonical executable grammar.
    """
    return lower_relational_contract(state.get("relational_contract") or {})


def execute_retrieval_program(
    conn,
    program: CanonicalRetrievalProgram | dict,
    *,
    structural_index: dict | None = None,
    program_context: dict | None = None,
) -> dict:
    """Execute one validated program and return packet, variables and receipt."""
    canonical = (
        program if isinstance(program, CanonicalRetrievalProgram)
        else canonicalise_program(program)
    )
    if structural_index is None:
        structural_index = get_structural_index(conn)
    context = dict(program_context or {})
    variables: dict[str, list] = {}
    operations: list[dict] = []
    started = time.perf_counter()

    def run_step(step: RetrievalStep, phase: str) -> None:
        tool = str(step.tool).strip().lower()
        resolved = _resolve_params(dict(step.params or {}), variables)
        bounded, clamps = _apply_limits(resolved, tool, canonical.limits)
        t0 = time.perf_counter()
        result = execute_tool(conn, tool, bounded, structural_index or {})
        variables[step.assign_to] = result
        operation = {
            "phase": phase,
            "tool": tool,
            "assign_to": step.assign_to,
            "result_count": len(result),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
        }
        # A walk that stopped because it hit its node budget is the same
        # family as a clamped hop count: the caller asked for a walk and got
        # part of one. Reported the same way, so there is one place to look.
        budget = next(
            (row.get("_node_budget_reached") for row in result
             if isinstance(row, dict) and row.get("_node_budget_reached")),
            None,
        )
        if budget:
            clamps = list(clamps) + [
                {"param": "max_nodes", "requested": "more than the budget",
                 "applied": budget}
            ]
        if clamps:
            operation["bounds_applied"] = clamps
        if tool == "exact_node_lookup":
            raw_values = bounded.get("label_or_id", [])
            requested = raw_values if isinstance(raw_values, list) else [raw_values]
            requested_count = len([item for item in requested if str(item or "").strip()])
            operation["requested_count"] = requested_count
            operation["resolve_miss_count"] = max(0, requested_count - len(result))
        operations.append(operation)

    for step in canonical.steps:
        run_step(step, "primary")

    contingency_triggered = _safe_trigger(
        canonical.contingency.trigger, variables, context
    )
    collect = canonical.collect
    if contingency_triggered:
        for step in canonical.contingency.fallback_steps:
            run_step(step, "fallback")
        collect = canonical.contingency.fallback_collect or collect

    collected_ids = _resolve_collect(collect, variables)
    packet_program = {
        "steps": [step.model_dump() for step in canonical.steps]
        + [step.model_dump() for step in canonical.contingency.fallback_steps],
        "contingency": canonical.contingency.model_dump(),
    }
    packet = build_evidence_packet(conn, variables, packet_program, collected_ids)
    serialised = canonical.model_dump(mode="json")
    program_hash = hashlib.sha256(
        json.dumps(serialised, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    recovery_reasons: set[str] = set()
    if contingency_triggered:
        primary_by_assignment = {
            step.assign_to: dict(step.params or {}) for step in canonical.steps
        }
        for step in canonical.contingency.fallback_steps:
            before = primary_by_assignment.get(step.assign_to) or {}
            after = dict(step.params or {})
            if (
                str(before.get("direction") or "") != str(after.get("direction") or "")
                and str(after.get("direction") or "") == "both"
            ):
                recovery_reasons.add("direction_retry")
            if before.get("edge_labels") and not after.get("edge_labels"):
                recovery_reasons.add("edge_label_retry")
    receipt = {
        "contract_version": RETRIEVAL_PROGRAM_VERSION,
        "program_hash": program_hash,
        "author": canonical.author,
        "operations": operations,
        "contingency_triggered": contingency_triggered,
        "collected_node_count": len(collected_ids),
        "packet_node_count": len(packet.get("node_records") or []),
        "packet_edge_count": len(packet.get("edge_records") or []),
        "packet_path_count": len(packet.get("path_records") or []),
        "empty_variables": sorted(
            name for name, value in variables.items() if not value
        ),
        "resolve_miss_count": sum(
            int(operation.get("resolve_miss_count") or 0)
            for operation in operations
        ),
        "recovery_reasons": sorted(recovery_reasons),
        "limits": canonical.limits.model_dump(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    packet["retrieval_program"] = serialised
    packet["execution_receipt"] = receipt
    return {
        "program": serialised,
        "variables": variables,
        "collected_ids": collected_ids,
        "evidence_packet": packet,
        "execution_receipt": receipt,
    }
