"""Canonical ``graph.md`` semantic-contract parsing.

The graph contract is user-owned semantics over the harness-owned mechanical
envelope. Parsing is deterministic and zero-LLM: YAML frontmatter becomes a
strict model, explanatory markdown is preserved, and both bind the fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SSTType = Literal["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]
ReviewMode = Literal["direct", "exceptions", "gated"]
_SLUG = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_RECIPE_OPS = {
    "lookup",
    "search",
    "select_landmarks",
    "expand",
    "traverse",
    "shortest_path",
    "find_paths",
    "walk_sequence",
    "union",
    "difference",
    "intersection",
    "filter",
    "sort",
    "limit",
    "project",
}

#: The keys each op reads, so a key it does not read is refused rather than
#: dropped. A probe agent wrote `{"op": "lookup", "pattern": "character:"}`;
#: it compiled, planned, and would have resolved an empty reference list --
#: an invented field and a real answer of "nothing found" are the same output.
#: Every op also takes `op` and `assign`.
_RECIPE_OP_KEYS: dict[str, set[str]] = {
    "lookup": {"references"},
    "search": {"query", "limit", "k"},
    # `roles` is deliberately absent: the structural-role taxonomy is not
    # exposed in v1. See mcp_server/traversal_compiler.py.
    "select_landmarks": {"include_pinned", "limit"},
    "expand": {"from", "predicates", "sst_types", "direction", "depth",
               "max_depth", "max_nodes", "kinds", "kind_prefixes",
               "properties", "strategy"},
    "traverse": {"from", "predicates", "sst_types", "direction", "depth",
                 "max_depth", "max_nodes", "kinds", "kind_prefixes",
                 "properties", "strategy"},
    "shortest_path": {"from", "to", "source", "target", "predicates",
                      "sst_types", "max_hops", "direction", "excluding"},
    "find_paths": {"from", "to", "source", "target", "predicates",
                   "sst_types", "max_hops", "direction", "excluding"},
    "walk_sequence": {"from", "predicates", "sst_types", "direction",
                      "max_hops", "max_nodes", "kinds", "kind_prefixes",
                      "properties", "cycle"},
    "union": {"of", "with", "left", "right", "from"},
    "difference": {"of", "minus", "left", "right", "from"},
    "intersection": {"of", "with", "left", "right", "from"},
    "filter": {"of", "from", "kinds", "kind_prefixes", "properties"},
    "sort": {"of", "from", "by", "order"},
    "limit": {"of", "from", "limit", "k", "n"},
    "project": {"of", "from"},
}

_UNIVERSAL_STEP_KEYS = {"op", "assign"}

#: What the vocabulary declines to express. Two probe agents spent five calls
#: between them discovering the first of these by exhausting guesses -- `all`,
#: `scan`, `complement`, `get_all_node_ids` -- against a compiler that could
#: only say "not a primitive". Saying so costs a line.
_RECIPE_LIMITS = (
    "No op names the whole graph: every program starts from a lookup, a "
    "search or a landmark, so 'every node of kind X' cannot be written. A "
    "provenance predicate that every node carries can stand in for one.",
    "sort takes id or label only, so nothing can be ranked by a computed "
    "quantity such as degree.",
)


def traversal_vocabulary() -> dict[str, Any]:
    """The ops and the keys each one reads, from the table that enforces them.

    Returned by `contract` rather than written into each format's prose. A
    graph.md is per-format; this vocabulary is not, and a copy in every format
    is a copy that rots. Derived from `_RECIPE_OP_KEYS`, so a new op or a
    renamed argument reaches the agent that has to write it.
    """
    return {
        "ops": {
            op: sorted(keys) for op, keys in sorted(_RECIPE_OP_KEYS.items())
        },
        "every_step_takes": sorted(_UNIVERSAL_STEP_KEYS),
        "notes": [
            "A step reads only the keys listed for its op; any other key is "
            "refused rather than ignored.",
            "kinds narrows what an op returns, on every op that takes it. It "
            "does not constrain the walk -- the predicates already do.",
            "answers names the variables carrying the answer. Without it the "
            "outcome is decided on packet size, and a packet holding only the "
            "endpoints of a question with no answer reads as FOUND.",
        ],
        "cannot": list(_RECIPE_LIMITS),
    }


def unknown_step_keys(step: dict[str, Any]) -> list[str]:
    """Keys this step's op does not read. Empty for a well-formed step."""
    op = str(step.get("op") or "").strip()
    allowed = _RECIPE_OP_KEYS.get(op)
    if allowed is None:
        return []
    return sorted(
        key for key in step
        if key not in allowed and key not in _UNIVERSAL_STEP_KEYS
    )


class GraphContractError(ValueError):
    """The semantic contract is absent, malformed or internally inconsistent."""


def _non_empty(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


class NodeKindSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_pattern: str

    @field_validator("id_pattern")
    @classmethod
    def _valid_id_pattern(cls, value: str) -> str:
        return _non_empty(value, "id_pattern")


class PredicateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sst: SSTType
    directed: bool = False
    symmetric: bool = False
    source_kinds: list[str] = Field(default_factory=list)
    target_kinds: list[str] = Field(default_factory=list)

    @field_validator("source_kinds", "target_kinds")
    @classmethod
    def _clean_kinds(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("kind constraints must not contain duplicates")
        return cleaned

    @model_validator(mode="after")
    def _valid_geometry(self):
        if self.directed and self.symmetric:
            raise ValueError("predicate cannot be both directed and symmetric")
        if self.symmetric and self.sst != "NEARTO":
            raise ValueError("symmetric predicates must map to NEARTO")
        return self


class RecipeParameterSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    kinds: list[str] = Field(default_factory=list)
    required: bool = True

    @field_validator("type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        return _non_empty(value, "parameter type")


class RecipeFixtureExpectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    contains: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    # `contains`/`excludes` read the evidence packet, which is deliberately
    # wider than the answer: it carries the context the walk passed through.
    # For a recipe whose `collect` narrows — an intersection, a difference —
    # that makes the actual result unassertable, because the nodes it ruled
    # out are legitimately still in the packet. `collects` names the exact
    # collected set instead. Every recipe written before this collected a
    # union of everything it computed, so the two sets coincided and no
    # fixture could tell them apart.
    collects: list[str] | None = None
    truncated: bool | None = None

    @field_validator("outcome")
    @classmethod
    def _valid_outcome(cls, value: str) -> str:
        outcome = _non_empty(value, "fixture outcome")
        allowed = {"FOUND", "EMPTY", "EXACT_MISS", "INVALID_RECIPE"}
        if outcome not in allowed:
            raise ValueError(
                f"fixture outcome must be one of {sorted(allowed)}"
            )
        return outcome


class RecipeFixtureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expect: RecipeFixtureExpectSpec

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        text = _non_empty(value, "fixture name")
        if not _SLUG.fullmatch(text):
            raise ValueError(f"invalid fixture name {text!r}")
        return text


class TraversalRecipeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    purpose: str = ""
    host_instruction: str = ""
    parameters: dict[str, RecipeParameterSpec] = Field(default_factory=dict)
    steps: list[dict[str, Any]]
    collect: str
    # One explicit deterministic fallback branch. It maps directly to the
    # retrieval-v1 contingency and is always receipt-visible.
    when: str = ""
    then: list[dict[str, Any]] = Field(default_factory=list)
    then_collect: str = ""
    project: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    #: Which assigned variables carry the *answer*, as opposed to the context
    #: the packet legitimately also holds. Measured on a real graph:
    #: `how_are_they_connected` between two characters four hops apart
    #: returned FOUND with zero paths, because looking up the two endpoints
    #: put two nodes in the packet and the outcome was decided on packet size.
    #: A caller reading FOUND would conclude they are connected.
    #:
    #: Naming the answer lets an empty one be reported as empty even when the
    #: packet is full. Absent, the outcome falls back to packet size, which is
    #: right for traversals whose answer *is* the neighbourhood.
    answers: list[str] = Field(default_factory=list)
    empty_means: str = "bounded_no_result"
    fixtures: list[RecipeFixtureSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _answers_are_assigned(self) -> "RecipeSpec":
        """An answer variable that no step assigns would always read empty."""
        assigned = {
            str(step.get("assign") or "").lstrip("$")
            for step in list(self.steps) + list(self.then)
        }
        unknown = [
            name for name in self.answers if name.lstrip("$") not in assigned
        ]
        if unknown:
            raise ValueError(
                f"traversal declares answers {unknown} that no step assigns"
            )
        return self

    @field_validator("steps")
    @classmethod
    def _valid_steps(cls, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not steps:
            raise ValueError("traversal recipe requires at least one step")
        assignments: set[str] = set()
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"step {index} must be an object")
            op = str(step.get("op") or "").strip()
            if op not in _RECIPE_OPS:
                raise ValueError(f"step {index} uses unsupported op {op!r}")
            stray = unknown_step_keys(step)
            if stray:
                raise ValueError(
                    f"step {index} ({op}) has unknown key(s) {stray}"
                )
            assign = str(step.get("assign") or "").strip()
            if assign:
                if not _SLUG.fullmatch(assign):
                    raise ValueError(f"step {index} has invalid assignment {assign!r}")
                if assign in assignments:
                    raise ValueError(f"duplicate assignment {assign!r}")
                assignments.add(assign)
        return steps

    @field_validator("then")
    @classmethod
    def _valid_fallback_steps(
        cls, steps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not steps:
            return steps
        return cls._valid_steps(steps)

    @model_validator(mode="after")
    def _valid_fallback(self):
        if bool(self.when) != bool(self.then):
            raise ValueError("when and then must be declared together")
        if self.then_collect and not self.then:
            raise ValueError("then_collect requires a then branch")
        names = [fixture.name for fixture in self.fixtures]
        if len(names) != len(set(names)):
            raise ValueError("traversal fixtures must have unique names")
        for fixture in self.fixtures:
            unknown = sorted(set(fixture.parameters) - set(self.parameters))
            if unknown:
                raise ValueError(
                    f"fixture {fixture.name!r} has unknown parameter(s): {unknown}"
                )
            missing = [
                name
                for name, parameter in self.parameters.items()
                if parameter.required and name not in fixture.parameters
            ]
            if missing:
                raise ValueError(
                    f"fixture {fixture.name!r} is missing required "
                    f"parameter(s): {missing}"
                )
        return self

    @field_validator("collect")
    @classmethod
    def _valid_collect(cls, value: str) -> str:
        return _non_empty(value, "collect")

    @field_validator("limits")
    @classmethod
    def _valid_limits(cls, limits: dict[str, int]) -> dict[str, int]:
        for name, value in limits.items():
            if int(value) < 1:
                raise ValueError(f"limit {name!r} must be positive")
        return limits


class OrientationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instructions: str = ""
    pinned_nodes: list[str] = Field(default_factory=list)
    default_traversal: str = ""


class RequiredTraversalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe: str
    when_kinds: list[str] = Field(default_factory=list)
    parameter: str = ""

    @field_validator("recipe")
    @classmethod
    def _valid_recipe(cls, value: str) -> str:
        return _non_empty(value, "required traversal recipe")

    @field_validator("when_kinds")
    @classmethod
    def _valid_kinds(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("required traversal kinds must not contain duplicates")
        return cleaned


#: The closed set of acceptance checks. Each name maps to one function in
#: `mcp_server/acceptance.py`; adding a name here without adding the function
#: is refused at import there rather than at run time.
AcceptanceCheck = Literal[
    "every_node_has_a_source_unit",
    "every_node_has_a_declared_kind",
    "every_edge_has_a_declared_predicate",
    "node_count_per_source_unit",
    "nodes_per_kind",
    "edges_per_node",
    "no_isolated_nodes",
    "label_appears_in_source",
    "no_duplicate_labels_within_kind",
]

#: Checks that are meaningless without a bound, so an unbounded one is a
#: mistake rather than a permissive default.
_BOUNDED_CHECKS = frozenset({
    "node_count_per_source_unit",
    "nodes_per_kind",
    "edges_per_node",
})


class AcceptancePredicateSpec(BaseModel):
    """One checkable statement about what a conforming graph looks like.

    Grain has been prose until now: "one independently citable claim" is a
    sentence a person can agree with and no program can decide. A predicate is
    the executable half — the constructor's acceptance test, and the only thing
    that makes a grain a grain rather than a wish.

    Deliberately a small closed vocabulary rather than an expression language.
    An expression language would need its own parser, its own errors and its
    own sandbox, and this has to be readable by whoever ratifies it. Checks
    that cannot be said here are a signal to add a named check, not to add
    syntax.
    """

    model_config = ConfigDict(extra="forbid")

    check: AcceptanceCheck
    #: Scope the predicate to one node kind or predicate name where the check
    #: supports it. Absent means "every node" / "every edge".
    kind: str = ""
    predicate: str = ""
    min: int | None = None
    max: int | None = None
    #: Predicates that do not count toward a degree check. A format that
    #: declares a provenance predicate every node carries -- `attested_by`
    #: here -- makes a minimum-degree check unfailable, because the edge that
    #: satisfies it is one every conforming program emits. Measured: 92 of 92
    #: nodes passed `edges_per_node >= 1` while 44 of them had no edge to
    #: anything but their source.
    ignoring: list[str] = Field(default_factory=list)
    #: Why this exists. Carried into the failure report, because a failing
    #: check whose point nobody remembers gets deleted rather than fixed.
    because: str = ""

    @model_validator(mode="after")
    def _bounds_make_sense(self) -> "AcceptancePredicateSpec":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("acceptance predicate min exceeds max")
        if self.ignoring and self.check != "edges_per_node":
            raise ValueError(
                f"acceptance check {self.check!r} does not read `ignoring`"
            )
        if self.check in _BOUNDED_CHECKS and self.min is None and self.max is None:
            raise ValueError(
                f"acceptance check {self.check!r} needs min and/or max"
            )
        return self


class GraphFormatSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_id: str
    format_version: int = Field(ge=1)
    review_mode: ReviewMode = "exceptions"
    oversized_batch: int = Field(default=12, ge=1)
    node_kinds: dict[str, NodeKindSpec]
    predicates: dict[str, PredicateSpec]
    orientation: OrientationSpec = Field(default_factory=OrientationSpec)
    traversals: dict[str, TraversalRecipeSpec] = Field(default_factory=dict)
    required_traversals: list[RequiredTraversalSpec] = Field(default_factory=list)
    #: What a conforming graph looks like. Empty means the format makes no
    #: checkable claim about construction — permitted, and reported as
    #: UNCHECKED rather than as a pass, because nothing was verified.
    acceptance: list[AcceptancePredicateSpec] = Field(default_factory=list)

    @field_validator("format_id")
    @classmethod
    def _valid_format_id(cls, value: str) -> str:
        text = _non_empty(value, "format_id")
        if not _SLUG.fullmatch(text):
            raise ValueError("format_id must be a stable slug")
        return text

    @field_validator("node_kinds", "predicates", "traversals")
    @classmethod
    def _valid_named_maps(cls, value: dict[str, Any]) -> dict[str, Any]:
        for name in value:
            if not _SLUG.fullmatch(str(name)):
                raise ValueError(f"invalid contract name {name!r}")
        return value

    @model_validator(mode="after")
    def _references_exist(self):
        if not self.node_kinds:
            raise ValueError("at least one node kind is required")
        if not self.predicates:
            raise ValueError("at least one predicate is required")
        known_kinds = set(self.node_kinds)
        for name, predicate in self.predicates.items():
            unknown = (set(predicate.source_kinds) | set(predicate.target_kinds)) - known_kinds
            if unknown:
                raise ValueError(
                    f"predicate {name!r} references unknown kinds: {sorted(unknown)}"
                )
        if (
            self.orientation.default_traversal
            and self.orientation.default_traversal not in self.traversals
        ):
            raise ValueError(
                "orientation.default_traversal must name a declared traversal"
            )
        for requirement in self.required_traversals:
            if requirement.recipe not in self.traversals:
                raise ValueError(
                    f"required traversal {requirement.recipe!r} is not declared"
                )
            unknown = set(requirement.when_kinds) - known_kinds
            if unknown:
                raise ValueError(
                    f"required traversal {requirement.recipe!r} references "
                    f"unknown kinds: {sorted(unknown)}"
                )
            recipe = self.traversals[requirement.recipe]
            parameter = str(requirement.parameter or "").strip()
            if parameter and parameter not in recipe.parameters:
                raise ValueError(
                    f"required traversal {requirement.recipe!r} parameter "
                    f"{parameter!r} is not declared"
                )
        for recipe_name, recipe in self.traversals.items():
            for parameter_name, parameter in recipe.parameters.items():
                unknown = set(parameter.kinds) - known_kinds
                if unknown:
                    raise ValueError(
                        f"traversal {recipe_name!r} parameter {parameter_name!r} "
                        f"references unknown kinds: {sorted(unknown)}"
                    )
            for index, step in enumerate(recipe.steps + recipe.then):
                unknown = set(step.get("predicates") or []) - set(self.predicates)
                if unknown:
                    raise ValueError(
                        f"traversal {recipe_name!r} step {index} references "
                        f"unknown predicates: {sorted(unknown)}"
                    )
                unknown = set(step.get("kinds") or []) - known_kinds
                if unknown:
                    raise ValueError(
                        f"traversal {recipe_name!r} step {index} references "
                        f"unknown kinds: {sorted(unknown)}"
                    )
        return self


class GraphContractDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    specification: GraphFormatSpec
    markdown: str
    fingerprint: str
    content_sha256: str

    def wire(self, *, include_markdown: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "format_id": self.specification.format_id,
            "format_version": self.specification.format_version,
            "review_mode": self.specification.review_mode,
            "oversized_batch": self.specification.oversized_batch,
            "required_traversals": [
                item.model_dump(mode="json")
                for item in self.specification.required_traversals
            ],
            "fingerprint": self.fingerprint,
            "content_sha256": self.content_sha256,
            "node_kinds": sorted(self.specification.node_kinds),
            "predicates": {
                name: spec.model_dump(mode="json")
                for name, spec in sorted(self.specification.predicates.items())
            },
            "orientation": self.specification.orientation.model_dump(mode="json"),
            "traversals": {
                name: {
                    "version": recipe.version,
                    "purpose": recipe.purpose,
                    "parameters": {
                        parameter_name: parameter.model_dump(mode="json")
                        for parameter_name, parameter in sorted(recipe.parameters.items())
                    },
                    "step_count": len(recipe.steps),
                    "limits": recipe.limits,
                    "empty_means": recipe.empty_means,
                    "fixtures": [fixture.name for fixture in recipe.fixtures],
                }
                for name, recipe in sorted(self.specification.traversals.items())
            },
            "grain_excerpt": markdown_section(self.markdown, "Grain", limit=600),
            "traversal_vocabulary": traversal_vocabulary(),
        }
        if include_markdown:
            out["markdown"] = self.markdown
            out["frontmatter"] = self.specification.model_dump(mode="json")
        return out


PRIMITIVE_TRAVERSAL_TOOLS = ("lookup", "expand", "path", "search")


def named_traversal_card(
    document: GraphContractDocument | None,
) -> dict[str, Any]:
    """Agent-facing traversal policy. Optional: unspecified means primitives."""
    primitives = list(PRIMITIVE_TRAVERSAL_TOOLS)
    if document is None:
        return {
            "available": False,
            "default_traversal": None,
            "required_traversals": [],
            "recipes": [],
            "primitives": primitives,
            "opening": (
                "no graph.md; walk with lookup, expand, path, and search"
            ),
            "search": (
                "unbound primitive; never an implicit fallback from an exact miss"
            ),
            "propose": "no named recipe is required",
        }
    spec = document.specification
    default = str(spec.orientation.default_traversal or "").strip() or None
    recipes = [
        {
            "name": name,
            "version": recipe.version,
            "purpose": recipe.purpose,
            "parameters": {
                parameter_name: parameter.model_dump(mode="json")
                for parameter_name, parameter in sorted(recipe.parameters.items())
            },
        }
        for name, recipe in sorted(spec.traversals.items())
    ]
    required = [
        item.model_dump(mode="json") for item in spec.required_traversals
    ]
    if default:
        opening = (
            f"for the usual job on this graph, run_traversal {default} first; "
            "lookup, expand, and path remain for ad-hoc walks"
        )
    elif recipes:
        opening = (
            "this format names recipes but no default_traversal; "
            "use a named recipe when it matches the job, otherwise primitives"
        )
    else:
        opening = (
            "this format names no recipes; walk with lookup, expand, path, "
            "and search"
        )
    return {
        "available": True,
        "default_traversal": default,
        "required_traversals": required,
        "recipes": recipes,
        "primitives": primitives,
        "opening": opening,
        "search": (
            "unbound primitive; a recipe may fall back to search only when "
            "that recipe declares when/then"
        ),
        "propose": (
            "propose refuses unless a fresh matching receipt is attached "
            "when required_traversals applies"
            if required
            else "a traversal receipt is optional"
        ),
    }


def kind_id_prefix(kind: str, specification: GraphFormatSpec) -> str:
    """Literal id prefix for a declared kind, before any ``<placeholder>``."""
    kind_spec = specification.node_kinds.get(str(kind))
    if kind_spec is None:
        return ""
    pattern = kind_spec.id_pattern.strip()
    placeholder = pattern.find("<")
    return pattern[:placeholder] if placeholder >= 0 else pattern


def node_id_matches_kind(
    node_id: str, kind: str, specification: GraphFormatSpec
) -> bool:
    """Match the stable id convention declared for a node kind.

    Starter contracts use readable templates such as ``topic:<stable-slug>``.
    The harness treats the literal prefix before the first placeholder as the
    compatibility boundary and requires a non-empty suffix.
    """
    literal_prefix = kind_id_prefix(kind, specification)
    candidate = str(node_id or "").strip()
    if kind not in specification.node_kinds:
        return False
    if not literal_prefix:
        return bool(candidate)
    return candidate.startswith(literal_prefix) and len(candidate) > len(literal_prefix)


def lower_predicates(
    predicates: list[str], specification: GraphFormatSpec
) -> tuple[list[str], list[str]]:
    """Return deterministic retrieval filters: SST tables and edge predicates."""
    cleaned = [str(name).strip() for name in predicates if str(name).strip()]
    unknown = sorted(set(cleaned) - set(specification.predicates))
    if unknown:
        raise GraphContractError(f"unknown predicate(s): {unknown}")
    sst_types = sorted({specification.predicates[name].sst.lower() for name in cleaned})
    return sst_types, sorted(set(cleaned))


def parse_graph_contract(text: str, *, path: Path | str = "graph.md") -> GraphContractDocument:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise GraphContractError("graph.md must begin with YAML frontmatter delimiter '---'")
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        raise GraphContractError("graph.md frontmatter has no closing '---' delimiter")
    yaml_text = "\n".join(lines[1:closing])
    markdown = "\n".join(lines[closing + 1 :]).strip() + "\n"
    if not markdown.strip():
        raise GraphContractError("graph.md requires explanatory markdown after frontmatter")
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise GraphContractError(f"invalid graph.md YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise GraphContractError("graph.md frontmatter must be an object")
    try:
        specification = GraphFormatSpec.model_validate(raw)
    except Exception as exc:
        raise GraphContractError(f"invalid graph contract: {exc}") from exc
    canonical = {
        "frontmatter": specification.model_dump(mode="json"),
        "markdown": markdown,
    }
    canonical_bytes = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return GraphContractDocument(
        path=str(Path(path)),
        specification=specification,
        markdown=markdown,
        fingerprint=f"gfmt_{digest[:16]}",
        content_sha256=digest,
    )


def load_graph_contract(path: Path | str) -> GraphContractDocument:
    contract_path = Path(path)
    if not contract_path.exists():
        raise GraphContractError(f"graph contract does not exist: {contract_path}")
    return parse_graph_contract(
        contract_path.read_text(encoding="utf-8"),
        path=contract_path,
    )


def resolve_graph_contract_path(
    db_path: Path | str,
    *,
    repo_root: Path | str | None = None,
    explicit_path: Path | str | None = None,
) -> Path:
    configured = explicit_path or os.environ.get("SST_GRAPH_CONTRACT")
    if configured:
        return Path(configured).expanduser()
    if repo_root:
        return Path(repo_root) / "graph.md"
    return Path(db_path).parent / "graph.md"


def markdown_section(markdown: str, heading: str, *, limit: int = 600) -> str:
    wanted = str(heading).strip().lower()
    lines = str(markdown or "").splitlines()
    collected: list[str] = []
    active = False
    level = 0
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            current_level = len(match.group(1))
            title = match.group(2).strip().lower()
            if active and current_level <= level:
                break
            if title == wanted:
                active = True
                level = current_level
                continue
        elif active:
            collected.append(line)
    text = "\n".join(collected).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
