"""Shared data models: LangGraph EngineState, Pydantic LLM schemas, engine constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, NotRequired, Optional, Set, TypedDict

from interaction.gap_types import INTERNAL_GAP_TYPES

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Schema Coercion Helpers
# ---------------------------------------------------------------------------

def _coerce_optional_str(v: Any) -> str:
    return "" if v is None else str(v)


def _coerce_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    if isinstance(v, list):
        out: list[str] = []
        for item in v:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    s = str(v).strip()
    return [s] if s else []


def _coerce_dict_list(v: Any) -> list[dict]:
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [item for item in v if isinstance(item, dict)]
    return []


def _coerce_warning_list(v: Any) -> list[dict]:
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        out: list[dict] = []
        for item in v:
            if isinstance(item, dict):
                out.append(item)
            elif item is not None:
                detail = str(item).strip()
                if detail:
                    out.append({"type": "unknown", "severity": "unknown", "detail": detail})
        return out
    detail = str(v).strip()
    return [{"type": "unknown", "severity": "unknown", "detail": detail}] if detail else []


def _coerce_optional_dict(v: Any) -> Optional[dict]:
    if v in (None, "", False):
        return None
    if isinstance(v, str) and v.strip().lower() in {"none", "null", "false"}:
        return None
    return v if isinstance(v, dict) else None


def _coerce_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


_TRAIL_ORIGIN_COERCIONS: dict[str, str] = {
    "direct": "direct_path",
    "directpath": "direct_path",
    "hypothesis": "hypothesis_path",
    "neighbor": "neighbourhood",
    "neighborhood": "neighbourhood",
}


# ---------------------------------------------------------------------------
# Engine Constants
# ---------------------------------------------------------------------------

SST_EDGE_TYPES: list[str] = ["leadsto", "contains", "expresses", "nearto"]

# NEARTO hard cap — enforced at backend execution level regardless of Planner spec
NEARTO_MAX_FORWARD: int = 2
NEARTO_MAX_BACKWARD: int = 0

# Squad budget.
#
# These are counted in NODES, but the unit of meaning is a SOURCE UNIT, and the
# ratio between them is a free authoring choice. On the repo-architecture arm a
# source unit became a median of 15 nodes, so a 12-node budget could not hold
# one module interface — the frontier exhausted itself inside a single section.
# `grain_scaled_bounds` raises these when the graph declares a fine grain; they
# remain the floor for every graph that does not declare one.
SQUAD_BUDGET_MIN: int = 8
SQUAD_BUDGET_MAX: int = 20
SQUAD_ITERATION_CEILING: int = 15

# Ceiling on grain scaling. A graph with one pathological source unit must not
# be able to demand an unbounded frontier.
SQUAD_GRAIN_BUDGET_CAP: int = 40
# Below this share of nodes carrying `source_unit_ids`, the grain figures
# describe too little of the graph to size a budget from.
GRAIN_ATTRIBUTION_MIN: float = 0.5

# v6 closure: recovery termination is fixpoint-based, not count-based.
# `dialogue_round` remains as a telemetry counter (how many recovery passes
# ran) but is NOT a termination criterion. The verdict reducer terminates
# recovery when either (a) the post-recovery packet did not grow vs. its
# pre-recovery snapshot, or (b) the proposed alternative_spec has already
# been tried this query. See verdict_computation._recovery_would_reach_new_territory.

# Optional squad ablation (safe headroom; default 0 = spec baseline)
SST_SQUAD_ITERATION_CEILING_HEADROOM_MAX: int = 2
SST_SQUAD_BUDGET_HEADROOM_MAX: int = 2


# ---------------------------------------------------------------------------
# Structural Index
# ---------------------------------------------------------------------------

STRUCTURAL_ROLES = [
    "causal_origin",
    "causal_terminal",
    "causal_nexus",
    "associative_hub",
    "inter_region_bridge",
    "orphan",
    "weakly_connected",
]


@dataclass
class StructuralFacts:
    roles: list[str] = field(default_factory=list)
    betweenness_centrality: float = 0.0
    in_degree: dict[str, int] = field(default_factory=dict)   # per SST type
    out_degree: dict[str, int] = field(default_factory=dict)  # per SST type

    @property
    def total_degree(self) -> int:
        return sum(self.in_degree.values()) + sum(self.out_degree.values())

    def to_dict(self) -> dict:
        return {
            "roles": self.roles,
            "betweenness_centrality": round(self.betweenness_centrality, 4),
            "in_degree": dict(self.in_degree),
            "out_degree": dict(self.out_degree),
        }


# ---------------------------------------------------------------------------
# Graph Schema (v11)
# ---------------------------------------------------------------------------

@dataclass
class GraphSchema:
    """Schema-level summary of the graph's edge type distribution.

    Derived from the structural index at startup. Used by the Planner's
    plan-validation step to verify that a proposed relational contract is
    structurally supported before execution.
    """
    edge_types_present: set = field(default_factory=set)
    # node_id → frozenset of SST edge types that have out_degree > 0
    node_out_edge_types: dict = field(default_factory=dict)
    # node_id → frozenset of SST edge types that have in_degree > 0
    node_in_edge_types: dict = field(default_factory=dict)
    # node_id → label (for name→id resolution without a connection)
    node_labels: dict = field(default_factory=dict)
    # role → list of SST edge types that appear as outgoing from nodes with that role
    role_outgoing_edge_types: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Plan Validation (v11)
# ---------------------------------------------------------------------------

class PlanValidationResult(BaseModel):
    """Result of the deterministic plan-validation step in the Planner.

    The Planner runs this after producing a relational contract and before
    emitting the plan for execution. Validation checks whether the graph's
    structural schema supports the plan's declared edge types and source
    entities.
    """
    outcome: Literal["validated", "needs_revision", "structurally_unsupported"]
    failed_checks: list[str] = Field(default_factory=list)
    schema_gap_description: Optional[str] = Field(default=None)
    revision_hint: Optional[str] = Field(
        default=None,
        description="Injected into the reseed prompt when outcome == 'needs_revision'.",
    )


# ---------------------------------------------------------------------------
# Graph Compass
# ---------------------------------------------------------------------------

@dataclass
class Compass:
    graph_profile: dict = field(default_factory=dict)
    landmark_nodes: list[dict] = field(default_factory=list)
    metanodes: list[dict] = field(default_factory=list)
    structural_gaps: dict = field(default_factory=dict)
    node_census: list[dict] = field(default_factory=list)  # [{id, label, roles, dominant_edge}] for all nodes

    def to_dict(self) -> dict:
        return {
            "graph_profile": self.graph_profile,
            "landmark_nodes": self.landmark_nodes,
            "metanodes": self.metanodes,
            "structural_gaps": self.structural_gaps,
            "node_census": self.node_census,
        }


# ---------------------------------------------------------------------------
# Seed Diagnostic
# ---------------------------------------------------------------------------

class SeedDiagnostic(BaseModel):
    """Diagnostic emitted by backend_execute on seed-acquisition quality.

    Consumed by route_after_backend to detect zero-candidate failures before
    Squad dispatch. When seed_miss=True and reseed has not been attempted, the
    FSM routes to planner_reseed instead of squad_dispatch.
    """
    strategies_fired: list[str] = Field(default_factory=list)
    per_strategy_counts: dict[str, int] = Field(default_factory=dict)
    seed_miss: bool = Field(default=False)
    total_candidates: int = Field(default=0)


# ---------------------------------------------------------------------------
# Planner Schemas
# ---------------------------------------------------------------------------

class RetrievalStep(BaseModel):
    """A single step in the Planner's retrieval program."""
    tool: str = Field(description="Tool name from the tool library: vector_search, lexical_search, exact_node_lookup, query_structural_index, hop_expansion, find_paths, traverse_chain, get_neighbourhood, get_neighbours")
    # Defaulted, not required: a tool call with no params is well defined (the
    # tool's own defaults), whereas making this mandatory meant one omitted key
    # invalidated the whole PlannerOutput.
    params: dict = Field(default_factory=dict, description="Parameters for the tool call")
    assign_to: str = Field(description="Variable name to store the result")


class ContingencySpec(BaseModel):
    """Contingency plan if primary retrieval fails."""
    trigger: str = Field(default="false", description="Boolean expression over variable names, e.g. 'hypothesis_paths.count == 0 AND strategy_b.concepts.count > 0'")
    fallback_steps: list[RetrievalStep] = Field(default_factory=list)
    fallback_collect: str = Field(default="", description="Expression describing what to collect from fallback, e.g. '$fallback_expansion + $neighbourhood'")

    @field_validator("fallback_steps", mode="before")
    @classmethod
    def _drop_unusable_fallback_steps(cls, v):
        """An unusable CONTINGENCY step must not destroy a usable PRIMARY plan.

        A fallback step missing `assign_to` has nowhere to put its result, so it
        could never have run. But because the field was required, its absence
        failed validation for the entire `PlannerOutput` — discarding a complete,
        correct primary program and dropping the engine to `schema_fallback`.

        Measured on the hexagonal fixture: ~40% of `what_governs` calls hit this,
        every one of them answering UNGOVERNED on a question the graph governs.
        The surface reports that as a coverage verdict, so it reads as "no policy
        found" rather than "the planner was thrown away".

        Primary `steps` stay strict on purpose — they are load-bearing, and
        silently dropping one would change the answer instead of preserving it.
        """
        if not isinstance(v, list):
            return v
        kept = []
        for step in v:
            if isinstance(step, dict) and not str(step.get("assign_to") or "").strip():
                continue
            kept.append(step)
        return kept


# v7: Three-pipeline dispatch. The Planner's `route` is authoritative and
# not subject to downstream override.
V7_PLANNER_ROUTE = Literal["compass_derivation", "targeted_retrieval", "exploratory"]


class MapReaderAnswer(BaseModel):
    """Pipeline A output: the Planner's direct answer from the Compass.

    No Backend, no downstream tiers. Cites specific Compass nodes by ID
    for provenance. Short-circuits to Battalion framing.
    """
    answer_text: str = Field(description="Prose answer for the user")
    cited_node_ids: list[str] = Field(
        default_factory=list,
        description="IDs from Compass layers that substantiate the answer.",
    )
    basis_layer: Literal["L1", "L2", "L3", "L1+L2", "L1+L2+L3"] = Field(
        default="L1+L2+L3",
        description="Which Compass layers the answer actually relied on.",
    )


class ChainStep(BaseModel):
    """One hop in a multi-step relational chain (question_form: chain)."""
    edge_types: list[str] = Field(default_factory=list)
    edge_labels: list[str] = Field(
        default_factory=list,
        description="Optional whitelist of edge labels (e.g. 'directed_by', 'starred_actors'). "
                    "When set, only edges whose label matches are traversed.",
    )
    direction: Literal["outgoing", "incoming", "both"] = Field(default="outgoing")
    max_hops: int = Field(default=1, ge=1, le=4)

    @field_validator("edge_types", mode="before")
    @classmethod
    def _lower_edge_types(cls, v: Any) -> list[str]:
        raw = _coerce_str_list(v)
        return [s.strip().lower() for s in raw if s and s.strip()]


class RelationalContract(BaseModel):
    """Pipeline B contract — the Planner's declaration of the specific
    edge(s) the query is asking about. Tighter than AnswerContract.

    Consumed directly by the Backend (no second LLM planning call). Drives
    the contract-to-tool dispatch defined in v7 §5.

    question_form: chain — multi-hop deterministic traversal where each step's
    output feeds the next step's seeds. The `steps` field defines the chain.
    Intermediate node types must be known upfront; use exploratory otherwise.
    """
    question_form: Literal["proof", "enumeration", "fanout", "lookup", "chain", "count"] = Field(
        default="lookup"
    )
    source_ids: list[str] = Field(
        default_factory=list,
        description="Named source entities (proof/enumeration/fanout/chain).",
    )
    edge_types: list[str] = Field(
        default_factory=list,
        description="SST edge types involved. Lowercase: leadsto/contains/expresses/nearto.",
    )
    direction: Literal["outgoing", "incoming", "both"] = Field(default="outgoing")
    target_ids: list[str] = Field(default_factory=list)
    max_hops: int = Field(default=1, ge=1, le=4)
    expected_result_shape: Literal["yes_no", "edge_pairs", "neighbourhood"] = Field(
        default="edge_pairs"
    )
    steps: list[ChainStep] = Field(
        default_factory=list,
        description="Ordered hop specs for question_form: chain. Step N output → step N+1 seeds.",
    )
    answer_type_hint: Optional[str] = Field(
        default=None,
        description=(
            "Optional category of the final answer for question_form: chain. "
            "Set to a type label such as 'year', 'country', 'genre', 'nationality', "
            "'language', 'date', 'person' when the answer is a typed property. "
            "The Backend will attempt one extra EXPRESSES outgoing hop from the "
            "chain's terminal nodes if this hint is not already grounded."
        ),
    )
    exact_only: bool = Field(
        default=False,
        description=(
            "Internal schema fail-open: resolve the declared source nodes but "
            "perform no traversal. Planner-authored values are reset during "
            "sanitisation; only deterministic validation may enable it."
        ),
    )

    @field_validator("edge_types", mode="before")
    @classmethod
    def _lower_edge_types(cls, v: Any) -> list[str]:
        raw = _coerce_str_list(v)
        return [s.strip().lower() for s in raw if s and s.strip()]


class PlannerOutput(BaseModel):
    """Structured output from the Planner's one-shot strategy call.

    v7 adds tagged-union routing fields: ``route`` selects one of the three
    pipelines, and the pipeline-specific payload (``map_reader_answer``,
    ``relational_contract``) is present only for that route. The existing
    exploratory fields (``strategy_a``, ``strategy_b``, ``steps``,
    ``answer_contract``, ``contingency``) remain canonical for
    ``route == "exploratory"``.
    """
    reasoning_trace: str = Field(description="Full reasoning trace: query analysis, graph orientation, strategy A, strategy B, structural intent, hop depth rationale, contingency")
    query_type: Literal["semantic", "structural", "mixed"] = Field(default="semantic")
    structural_intent: Literal["overview", "bridge", "origin", "gap", "centrality", "null"] = Field(default="null")
    strategy_a: dict = Field(default_factory=dict, description="Exploratory only: explicit query concepts")
    strategy_b: dict = Field(default_factory=dict, description="Exploratory only: hypothesis concepts + reasoning_per_concept")
    steps: list[RetrievalStep] = Field(default_factory=list, description="Exploratory only: ordered retrieval steps")
    collect: str = Field(default="", description="Exploratory only: collect expression, e.g. '$hypothesis_paths + $neighbourhood'")
    contingency: ContingencySpec = Field(default_factory=ContingencySpec)
    cluster_budget_overrides: dict = Field(default_factory=dict, description="Optional per-cluster budget cap overrides: {'cluster_id': {'max_budget': N}}. N capped at 25.")
    planner_mode: Literal["nominal", "schema_fallback"] = Field(default="nominal", description="Set to schema_fallback when LLM parsing fails and deterministic fallback is used.")
    entity_intent: dict = Field(
        default_factory=dict,
        description="Option B: entity intent hints. {'entity_types': [...], 'type_hints': {'country': ['c_']}, 'source_terms': [...], 'target_terms': [...], 'require_relation_proof': bool}",
    )
    company_intent: dict = Field(
        default_factory=dict,
        description="Option B: Company-facing intent contract. {'query_mode': 'entity_listing|relation_query', 'acceptable_evidence': [...], 'proof_expectation': str}",
    )
    answer_contract: AnswerContract = Field(
        default_factory=lambda: AnswerContract(),
        description="v6: AnswerContract — exploratory route only. Downstream tiers read as a hint, never as truth.",
    )

    # v7 routing fields -----------------------------------------------------
    route: V7_PLANNER_ROUTE = Field(
        default="exploratory",
        description="v7 three-pipeline dispatch: 'compass_derivation' (Compass-only), 'targeted_retrieval' (edge-specific), 'exploratory' (full pipeline). Authoritative.",
    )
    classifier_rationale: str = Field(
        default="",
        description="v7: one-sentence explanation of why the Planner chose `route`. Surfaces low-confidence cases to Battalion framing.",
    )
    verdict_space: str = Field(
        default="",
        description=(
            "Which completeness rule the question asks for — 'confirmation', "
            "'coverage' or 'ruling'. Empty means the Planner did not classify, "
            "which leaves the graph's published default standing; it is not a "
            "vote for any space. A caller who declared one always overrides."
        ),
    )
    verdict_space_rationale: str = Field(
        default="",
        description="One sentence naming what an empty retrieval would have meant. The classification test, stated.",
    )
    map_reader_answer: Optional[MapReaderAnswer] = Field(
        default=None,
        description="v7 Pipeline A payload — present only when route == 'compass_derivation'.",
    )
    relational_contract: Optional[RelationalContract] = Field(
        default=None,
        description="v7 Pipeline B payload — present only when route == 'targeted_retrieval'.",
    )


# ---------------------------------------------------------------------------
# Squad Schemas
# ---------------------------------------------------------------------------

class SquadDecision(BaseModel):
    """Decision for a single node during squad iteration."""
    node_id: str
    label: str
    include: bool
    reason: str = Field(description="One sentence explaining inclusion/exclusion")
    terminal: bool = Field(default=False, description="True if this is a natural terminal (out-degree 0)")


class ContinuationSignal(BaseModel):
    """Squad's assessment of whether the chain was still active when it stopped."""
    worth_continuing: bool
    reason: str
    suggested_edge_type: str = Field(default="")
    suggested_direction: str = Field(default="forward")


class SquadHandoff(BaseModel):
    """Typed handoff from a single squad agent to the Company."""
    cluster_id: str
    decisions: list[SquadDecision] = Field(default_factory=list)
    termination_status: Literal["BUDGET_EXHAUSTED", "NATURAL_TERMINAL", "DEAD_END", "REDUNDANT", "COMPLETE"] = Field(default="COMPLETE")
    termination_node: Optional[dict] = Field(default=None, description="Last node processed: {id, label, anchor_preview}")
    continuation_signal: ContinuationSignal = Field(default_factory=lambda: ContinuationSignal(worth_continuing=False, reason=""))
    cluster_summary: str = Field(default="")
    cross_cluster_nodes_reached: list[str] = Field(default_factory=list, description="Node IDs flagged as cross-cluster opportunities during traversal")
    degradation_flags: list[str] = Field(default_factory=list, description="Typed degradation signals: squad_parse_error:{cluster_id}, provider_rate_limit, etc.")


# ---------------------------------------------------------------------------
# Company Schemas
# ---------------------------------------------------------------------------

class GapEntry(BaseModel):
    """Typed gap entry — required format for all Company gap inventory outputs.

    Vague prose gaps are not permitted. Validation layer checks compliance.
    """
    #: Must stay reachable from `contract.GapType` — see
    #: tests/test_gap_vocabulary.py. `vocabulary_mismatch` and `schema_gap` were
    #: once declared in the contract and absent here, so the engine could not
    #: emit them at all: pydantic rejected the value and the translation map's
    #: entries for them were dead code. `schema_gap` now has a producer;
    #: `vocabulary_mismatch` never gained one and was removed rather than left
    #: advertised.
    #: Derived from `interaction.gap_types.INTERNAL_GAP_TYPES`. Declaring a
    #: type there is the only edit needed; forgetting to map it is a test
    #: failure rather than a silent downgrade to `missing_concept`.
    gap_type: Literal[*INTERNAL_GAP_TYPES]
    specific_node_or_concept: str = Field(
        description="Non-empty: node ID, label, or specific concept name. Never a vague domain description."
    )
    actionable_suggestion: str = Field(
        description="Non-empty: one sentence the human can act on — what to add to the graph."
    )
    # v6 fix: honest audit trail for each gap. The engine may synthesise gaps
    # deterministically (e.g. the relation-proof soft gate) and the LLM may
    # produce gaps from dossier adjudication. Downstream tiers need to tell
    # these apart without reverse-engineering the source.
    provenance: dict = Field(
        default_factory=dict,
        description="Optional {source, tier, basis}. 'source' ∈ {engine, llm}. Absent means legacy/unattributed.",
    )

    @field_validator("specific_node_or_concept", "actionable_suggestion", mode="before")
    @classmethod
    def _require_non_empty(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip()
        if not s:
            raise ValueError("GapEntry fields must be non-empty strings")
        return s


class TrailRecord(BaseModel):
    """A single reasoning trail evaluated by the Company."""
    trail_id: str
    origin: Literal[
        "hypothesis_path",
        "direct_path",
        "neighbourhood",
        "structural",
        "fallback",
        "alternative",
    ]
    rationale: str
    node_ids: list[str]
    edge_types: list[str] = Field(default_factory=list)
    edge_labels: list[str] = Field(default_factory=list)

    @field_validator("trail_id", "rationale", mode="before")
    @classmethod
    def _coerce_text_fields(cls, v: Any) -> str:
        return _coerce_optional_str(v)

    @field_validator("origin", mode="before")
    @classmethod
    def _coerce_origin(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip().lower()
        return _TRAIL_ORIGIN_COERCIONS.get(s, s or "direct_path")

    @field_validator("node_ids", "edge_types", "edge_labels", mode="before")
    @classmethod
    def _coerce_list_fields(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


class TargetedExtensionSpec(BaseModel):
    """Company's targeted extension recovery spec."""
    extend_from: str = Field(description="Node ID from squad continuation signal")
    edge_type: str
    direction: Literal["forward", "backward"]
    hops: int = Field(ge=1, le=3)


class TargetedReseedSpec(BaseModel):
    """Company's targeted re-seed recovery spec."""
    search_for: str = Field(description="Concept label from gap analysis")
    connect_to: str = Field(description="Existing seed node ID")
    max_hops: int = Field(ge=2, le=4)


class CompanyInternalHandoff(BaseModel):
    """Internal handoff from Company to Battalion."""
    hypothesis_status: Literal["confirmed", "partial", "not_confirmed"] = Field(default="not_confirmed")
    hypothesis_explanation: str = Field(default="")
    primary_trails: list[TrailRecord] = Field(default_factory=list)
    supporting_trails: list[TrailRecord] = Field(default_factory=list)
    context_trails: list[TrailRecord] = Field(default_factory=list)
    pruned_trail_ids: list[str] = Field(default_factory=list)
    gaps: list[GapEntry] = Field(default_factory=list, description="Typed gap inventory — GapEntry schema required. Validated by evidence brief validation layer.")
    confidence: Literal["high", "medium", "low"] = Field(default="low")
    local_recovery_executed: dict = Field(default_factory=dict, description="Details of Company-executed local recovery: {executed, type, outcome}")
    semantic_post_mortem: str = Field(default="", description="Diagnostic summary for the Planner if results are exhausted or low-confidence")
    bridging_spec: Optional[dict] = Field(default=None, description="Recovery spec to connect disconnected clusters via find_paths")

    @field_validator("hypothesis_explanation", "semantic_post_mortem", mode="before")
    @classmethod
    def _coerce_text_fields(cls, v: Any) -> str:
        return _coerce_optional_str(v)

    @field_validator("pruned_trail_ids", mode="before")
    @classmethod
    def _coerce_pruned_trails(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)

    @field_validator("local_recovery_executed", mode="before")
    @classmethod
    def _coerce_local_recovery(cls, v: Any) -> dict:
        return _coerce_dict(v)

    @field_validator("bridging_spec", mode="before")
    @classmethod
    def _coerce_bridging_spec(cls, v: Any) -> Optional[dict]:
        return _coerce_optional_dict(v)


class EvidenceBrief(BaseModel):
    """Compact evidence brief for verdict computation / legacy confirmation (~200 tokens)."""
    strategy_b_surfaced: list[str] = Field(default_factory=list)
    strategy_b_absent: list[str] = Field(default_factory=list)
    strategy_b_reasoning_matches: list[str] = Field(default_factory=list, description="B concepts matched via reasoning (not just label): e.g. 'cortisol_regulation matched adrenal_fatigue via reasoning'")
    primary_trail_labels: list[str] = Field(default_factory=list)
    squad_continuation_signals: list[dict] = Field(default_factory=list, description="Must include ALL worth_continuing==True signals from squad handoffs — checked by validation layer")
    specific_gaps: list[GapEntry] = Field(default_factory=list, description="Typed gap entries forwarded from internal_handoff.gaps — must conform to GapEntry schema")
    local_recovery_executed: dict = Field(default_factory=dict, description="Populated if Company executed local recovery before this brief was produced")
    candidate_set_quality_warnings: list[dict] = Field(default_factory=list, description="Forwarded from backend structural audit if warnings were present")
    recovery_memo: str = Field(default="", description="Human-readable memo from recovery execution: node IDs/labels added, type, outcome. Empty if no recovery ran.")
    relation_proof_status: dict = Field(default_factory=dict, description="Option B: relation proof summary from backend, e.g. {status, matched_sources, matched_targets, proof_count}")
    evidence_status: dict = Field(default_factory=dict, description="Option B soft gate status: {relation_gate, degraded, reason}")

    @field_validator(
        "strategy_b_surfaced",
        "strategy_b_absent",
        "strategy_b_reasoning_matches",
        "primary_trail_labels",
        mode="before",
    )
    @classmethod
    def _coerce_text_lists(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)

    @field_validator("squad_continuation_signals", mode="before")
    @classmethod
    def _coerce_continuation_signals(cls, v: Any) -> list[dict]:
        return _coerce_dict_list(v)

    @field_validator("local_recovery_executed", mode="before")
    @classmethod
    def _coerce_local_recovery(cls, v: Any) -> dict:
        return _coerce_dict(v)

    @field_validator("candidate_set_quality_warnings", mode="before")
    @classmethod
    def _coerce_warnings(cls, v: Any) -> list[dict]:
        return _coerce_warning_list(v)

    @field_validator("recovery_memo", mode="before")
    @classmethod
    def _coerce_recovery_memo(cls, v: Any) -> str:
        return _coerce_optional_str(v)


class CompanyHandoff(BaseModel):
    """Full Company output."""
    internal_handoff: CompanyInternalHandoff = Field(default_factory=CompanyInternalHandoff)
    evidence_brief: EvidenceBrief = Field(default_factory=EvidenceBrief)
    recovery_spec: Optional[dict] = Field(default=None, description="Deprecated (v4): Company now executes local recovery directly. Still accepted for backward compat.")
    user_summary: str = Field(default="")
    degradation_flags_received: list[str] = Field(default_factory=list, description="Degradation flags from squad handoffs that Company received and forwarded")

    @field_validator("recovery_spec", mode="before")
    @classmethod
    def _coerce_recovery_spec(cls, v: Any) -> Optional[dict]:
        return _coerce_optional_dict(v)

    @field_validator("user_summary", mode="before")
    @classmethod
    def _coerce_user_summary(cls, v: Any) -> str:
        return _coerce_optional_str(v)

    @field_validator("degradation_flags_received", mode="before")
    @classmethod
    def _coerce_degradation_flags(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


# ---------------------------------------------------------------------------
# Planner Confirmation Schemas
# ---------------------------------------------------------------------------

class AlternativeSpec(BaseModel):
    """Planner's alternative retrieval suggestion."""
    type: Literal["entry_point", "vocabulary_correction", "null"] = Field(default="null")
    entry_point: Optional[dict] = Field(default=None, description="{'landmark_id': str, 'reason': str}")
    vocabulary_correction: Optional[dict] = Field(default=None, description="{'original_concept': str, 'graph_vocabulary': str, 'evidence': str, 'corrected_seed_query': str}")

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_none_type(cls, v: Any) -> str:
        # Provider outputs occasionally emit null for type; treat as explicit null spec.
        return "null" if v is None else str(v)


class MetanodeRecommendation(BaseModel):
    """Planner's recommendation on whether to cross a metanode."""
    cross: bool = False
    node_id: str = ""
    reason: str = ""

    @field_validator("node_id", "reason", mode="before")
    @classmethod
    def _coerce_none_str(cls, v: Any) -> str:
        return "" if v is None else str(v)


class ConfirmationResponse(BaseModel):
    """Confirmation / verdict payload (ConfirmationResponse).

    Live path: filled by deterministic verdict_computation (v7), not an LLM.
    Legacy planner_confirmation() still emits this shape for tests.

    v6: adds ILL_POSED for queries unanswerable from any graph of this shape —
    distinct from EXHAUSTED and ALTERNATIVE.
    """
    # UNKNOWN_TO_GRAPH: reserved — emitted when entity resolution finds no graph
    # nodes matching any query term after all reseeding is exhausted. Not yet
    # wired into routing; declared here so the verdict space is total.
    verdict: Literal["CONFIRMED", "EXHAUSTED", "ALTERNATIVE", "ILL_POSED", "UNKNOWN_TO_GRAPH"] = Field(default="EXHAUSTED")
    confirmed_trails: list[str] = Field(default_factory=list)
    confidence_per_trail: dict[str, str] = Field(default_factory=dict)
    alternative_spec: Optional[AlternativeSpec] = Field(default=None)
    metanode_recommendation: Optional[MetanodeRecommendation] = Field(default=None)
    exhaustion_explanation: str = Field(default="")
    planner_mode: Literal["nominal", "schema_fallback", "compass_stale", "brief_incomplete"] = Field(
        default="nominal",
        description="Reflects the planning state this confirmation was produced under. Propagates to Battalion."
    )
    compass_confidence: Optional[dict] = Field(
        default=None,
        description="On EXHAUSTED/ILL_POSED: {'computed_under': 'nominal|fallback_planning', 'note': str}. Qualifies the epistemic strength of the verdict."
    )
    ill_posed_reason: str = Field(
        default="",
        description="On ILL_POSED: one-sentence structural reason the query is unanswerable from any graph of this shape.",
    )

    @field_validator("exhaustion_explanation", "ill_posed_reason", mode="before")
    @classmethod
    def _coerce_exhaustion(cls, v: Any) -> str:
        return "" if v is None else str(v)


# ---------------------------------------------------------------------------
# v6 Information Infrastructure Schemas
# ---------------------------------------------------------------------------

# Query taxonomy — multi-dimensional classification. Soft hint only; the
# EvidencePacket remains the source of truth. Classification is set by the
# Planner, checked by semantic_validation, and read (not trusted) by Company
# and Battalion.
V6_QUERY_CLASS = Literal[
    "enumeration",         # "what nodes are connected via X"
    "relation_proof",      # "does A lead to B?"
    "fanout",              # "what does X lead to?"
    "overview",            # "what is this graph about?"
    "exclusion",           # "what does NOT lead to X?"
    "semantic_lookup",     # "tell me about X"
    "aggregation",         # "how many X are there?"
    "comparative",         # "how is X different from Y?"
    "existence",           # "is there a Y in this graph?"
    "meta_gap",            # "what's missing from the graph?"
    "composite",           # multi-intent query
    "unknown",             # classifier could not decide
]

V6_EVIDENCE_SHAPE = Literal[
    "node_set",    # flat membership
    "path",        # ordered chain
    "edge_pairs",  # canonical (source, edge_type, target, label) tuples
    "subgraph",    # localised node+edge subset
    "count",       # aggregate cardinality
    "complement",  # set difference
    "comparison",  # paired contrast of two node sets
]

V6_PROOF_MODE = Literal[
    "semantic",    # anchor content must support the answer
    "structural",  # structural fact (edge participation, role)
    "relational",  # a typed edge must exist
    "absence",     # an absence proof (no such edge/path)
    "aggregate",   # counts/sums
]

V6_SCOPE = Literal["local", "regional", "global"]


class AnswerContract(BaseModel):
    """Planner's declared expectation for what the answer should look like.

    Soft classification: the contract is a hint, not a truth claim. Downstream
    tiers compare the EvidencePacket against this contract but cannot overwrite
    either. Shape mismatch produces a ``planner_contract_drift`` degradation
    flag; truth contradictions produce ``semantic_violation`` flags.
    """
    query_class: V6_QUERY_CLASS = Field(default="unknown")
    evidence_shapes_expected: list[V6_EVIDENCE_SHAPE] = Field(
        default_factory=lambda: ["node_set"],
        description="Canonical shape(s) the backend is expected to produce.",
    )
    proof_mode: V6_PROOF_MODE = Field(default="semantic")
    scope: V6_SCOPE = Field(default="local")
    composition: str = Field(
        default="atomic",
        description="'atomic' for a single-intent query, 'composite' when the query decomposes into sub-contracts.",
    )
    determinacy: Literal["deterministic", "heuristic", "ambiguous"] = Field(default="heuristic")
    hypotheses: list[dict] = Field(
        default_factory=list,
        description="Multi-hypothesis list: [{label, rationale, expected_shape, confidence}]",
    )

    @field_validator("evidence_shapes_expected", mode="before")
    @classmethod
    def _coerce_shapes(cls, v: Any) -> list:
        if v is None:
            return ["node_set"]
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(s) for s in v if s]
        return ["node_set"]

    @field_validator("hypotheses", mode="before")
    @classmethod
    def _coerce_hypotheses(cls, v: Any) -> list[dict]:
        return _coerce_dict_list(v)


class EvidencePacket(BaseModel):
    """Canonical, immutable evidence produced by the Backend.

    Append-only: recovery rounds add to ``append_log`` and extend node/edge/
    path records but never remove. Downstream tiers read this packet as the
    source of truth; nothing may claim a relation absent that the packet
    contains.
    """
    node_records: list[dict] = Field(
        default_factory=list,
        description="[{id, label, origin, via_edge_type?, path_chain?, ...}] — dedup by id",
    )
    edge_records: list[dict] = Field(
        default_factory=list,
        description="[{source_id, target_id, edge_type, edge_label, source_label?, target_label?}] — canonical edge proofs",
    )
    path_records: list[dict] = Field(
        default_factory=list,
        description="[{node_chain, edge_chain, edge_label_chain, source, target}]",
    )
    structural_facts: dict = Field(
        default_factory=dict,
        description="{bridge_count, landmark_count, leaf_fraction, warnings: [...]}",
    )
    packet_provenance: list[dict] = Field(
        default_factory=list,
        description="[{step, tool, assign_to, added_nodes, added_edges, added_paths}] — which tool produced what",
    )
    append_log: list[dict] = Field(
        default_factory=list,
        description="[{round, phase: 'initial|recovery|append', reason, added_nodes, added_edges}] — immutable history",
    )
    degradation_flags: list[str] = Field(
        default_factory=list,
        description="Typed backend signals: packet_integrity_violation, seed_miss, tool_failure:{tool}, etc.",
    )
    judgment_view: dict = Field(
        default_factory=dict,
        description=(
            "Bounded prompt-facing projection metadata. The canonical node/edge/path "
            "records remain intact; this view only controls evidence shown to judgment tiers."
        ),
    )
    source_unit_coverage: list[dict] = Field(
        default_factory=list,
        description=(
            "[{source_unit_id, nodes_in_packet, nodes_in_graph, missing_node_ids}] — "
            "source units the packet holds only part of. Empty when every touched "
            "unit is complete AND when the graph carries no attribution at all; "
            "read `source_unit_attribution` to tell those apart."
        ),
    )
    source_unit_attribution: bool = Field(
        default=False,
        description=(
            "True when the open graph declares source_unit_ids at all. When False, "
            "an empty source_unit_coverage means unknown — never 'complete'."
        ),
    )

    @field_validator(
        "node_records",
        "edge_records",
        "path_records",
        "packet_provenance",
        "append_log",
        "source_unit_coverage",
        mode="before",
    )
    @classmethod
    def _coerce_dict_lists(cls, v: Any) -> list[dict]:
        return _coerce_dict_list(v)

    @field_validator("degradation_flags", mode="before")
    @classmethod
    def _coerce_flag_list(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


class ConfidenceProvenance(BaseModel):
    """Attaches deterministic vs LLM confidence to any artifact claim.

    Deterministic facts cannot be downgraded by LLM judgement — Battalion
    reads this to calibrate hedging in the final answer.
    """
    source: Literal["deterministic", "llm"] = Field(default="llm")
    tier: str = Field(default="")
    basis: str = Field(default="")


class CompanyDossier(BaseModel):
    """Deterministic structuring of the EvidencePacket for Company LLM intake.

    Built by ``company_prep``, not by an LLM. Contains per-cluster trails,
    per-edge participation tables, and hypothesis-vs-evidence mapping. This is
    what the Company LLM reasons about — it cannot fabricate facts inside the
    dossier, only interpret them.
    """
    model_config = ConfigDict(extra="forbid")

    packet_summary: dict = Field(
        default_factory=dict,
        description="Judgment-view counts plus canonical packet count and view status.",
    )
    edge_participation: dict = Field(
        default_factory=dict,
        description="Counts and endpoint participation grouped by edge type.",
    )
    trails: list[dict] = Field(default_factory=list, description="Linearised trail records.")
    squad_summaries: list[dict] = Field(default_factory=list)
    hypothesis_vs_evidence: list[dict] = Field(
        default_factory=list,
        description="Planner hypotheses mapped to matching judgment-view nodes.",
    )
    answer_role_grounding: list[dict] = Field(default_factory=list)
    structural_facts: dict = Field(default_factory=dict)
    answer_contract: dict = Field(default_factory=dict)
    shape_coverage: dict = Field(default_factory=dict)
    provenance: ConfidenceProvenance = Field(default_factory=ConfidenceProvenance)

    @field_validator(
        "trails",
        "squad_summaries",
        "hypothesis_vs_evidence",
        "answer_role_grounding",
        mode="before",
    )
    @classmethod
    def _coerce_list_of_dicts(cls, v: Any) -> list[dict]:
        return _coerce_dict_list(v)


class CompanyVerdict(BaseModel):
    """LLM-produced interpretation of the CompanyDossier.

    Replaces the broader CompanyHandoff for v6. Cannot contain factual claims
    that contradict the dossier — ``semantic_validation`` deterministically
    corrects any drift before the verdict reaches Planner Confirmation.
    """
    hypothesis_assessment: Literal["confirmed", "partial", "not_confirmed"] = Field(default="not_confirmed")
    hypothesis_explanation: str = Field(default="")
    primary_trail_ids: list[str] = Field(default_factory=list)
    supporting_trail_ids: list[str] = Field(default_factory=list)
    context_trail_ids: list[str] = Field(default_factory=list)
    pruned_trail_ids: list[str] = Field(default_factory=list)
    gap_inventory: list[GapEntry] = Field(default_factory=list)
    recovery_intent: Literal["local_extension", "bridging", "global_redirect", "none"] = Field(default="none")
    recovery_intent_spec: Optional[dict] = Field(
        default=None,
        description="Concrete parameters if recovery_intent != none: extend_from, target_ids, edge_type, search_for, etc.",
    )
    semantic_post_mortem: str = Field(default="")
    confidence_provenance: ConfidenceProvenance = Field(
        default_factory=lambda: ConfidenceProvenance(source="llm", tier="company", basis="dossier_interpretation")
    )

    @field_validator("hypothesis_explanation", "semantic_post_mortem", mode="before")
    @classmethod
    def _coerce_text_fields(cls, v: Any) -> str:
        return _coerce_optional_str(v)

    @field_validator(
        "primary_trail_ids",
        "supporting_trail_ids",
        "context_trail_ids",
        "pruned_trail_ids",
        mode="before",
    )
    @classmethod
    def _coerce_trail_id_lists(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)

    @field_validator("recovery_intent_spec", mode="before")
    @classmethod
    def _coerce_recovery_spec(cls, v: Any) -> Optional[dict]:
        return _coerce_optional_dict(v)


# ---------------------------------------------------------------------------
# LangGraph Engine State
# ---------------------------------------------------------------------------

#: Which verdict space the CALLER asked in. The engine used to receive only a
#: string, so it could not know, and Battalion's governance judgment was applied
#: to every query regardless — coverage space silently overwriting confirmation
#: space (see examples/baseline-similarity/
#: FINDINGS_COVERAGE_OVERWRITES_CONFIRMATION.md). Making it typed is the smallest
#: change that restores mcp-contract-v0 §2.2, and it is what any deeper fix needs
#: anyway.
#:
#: "confirmation" — can the graph answer this? (discover)
#: "coverage"     — does any policy govern this? (what_governs)
#: "ruling"       — does this artifact conform? (check_conformance)
VerdictSpace = Literal["confirmation", "coverage", "ruling"]

DEFAULT_VERDICT_SPACE: "VerdictSpace" = "coverage"


class EngineState(TypedDict):
    query: str
    #: Which of the three completeness rules this run is graded by. A caller
    #: that names one always wins; silence now resolves to the graph's own
    #: published default rather than to `coverage` regardless of corpus.
    verdict_space: str
    #: `caller` | `graph` | `fallback` — how the space above was arrived at.
    #: An autonomous caller cannot otherwise distinguish a space it chose from
    #: one it inherited, and the two deserve different trust in an ILL_POSED.
    verdict_space_source: str
    #: Instruction for the reasoning tiers (Company, Battalion) in coverage and
    #: ruling space. Empty in confirmation space. Travels beside the query
    #: rather than inside it, so retrieval is identical across all three spaces.
    governance_directive: str
    compass: dict                        # serialised Compass
    structural_index: dict               # node_id → StructuralFacts.to_dict()

    # Planner output
    planner_program: dict                # PlannerOutput as dict
    planner_reasoning: str
    planner_governing_candidates: list[dict]  # deterministic query-relevant authority prior
    retrieval_request: NotRequired[dict] # structured operator→Planner intent envelope

    # Backend output
    # v6 note: `candidate_set` is preserved for v5 compatibility but is a
    # derived view of `evidence_packet.node_records`. Prefer reading from
    # `evidence_packet` in new code — the packet is the canonical source of
    # truth. `candidate_set` may be removed in a future version.
    candidate_set: list                  # list of dicts with origin tags
    judgment_candidate_set: NotRequired[list]  # bounded LLM-facing projection; packet stays canonical
    frontier_clusters: list              # grouped by connectivity

    # Squad output
    squad_handoffs: list                 # list of SquadHandoff dicts

    # Company output
    company_handoff: dict                # CompanyHandoff as dict
    company_recovery_spec: dict          # targeted spec or empty dict

    # Verdict / confirmation payload (deterministic on live path since v7)
    confirmation_response: dict          # ConfirmationResponse as dict
    dialogue_round: int
    semantic_feedback: list[str]         # Collective summaries from previous failed rounds
    semantic_retry_attempted: bool        # v5.3: prevent semantic retry loops

    # Seed-miss recovery (optional — merged by LangGraph)
    seed_diagnostic: NotRequired[dict]       # SeedDiagnostic as dict
    reseed_attempted: NotRequired[bool]      # hard cap: 1 reseed per query

    # Dialogue stability / observability (optional — merged by LangGraph)
    company_evidence_fingerprint: NotRequired[str]
    pre_recovery_company_fingerprint: NotRequired[str]
    prev_alternative_spec: NotRequired[dict]    # snapshot of last ALTERNATIVE spec for loop detection

    # v6 closure: fixpoint-based recovery termination.
    # `pre_recovery_packet_signature` is captured at backend_execute_recovery
    # entry; the reducer compares it to the post-recovery packet to detect
    # zero-growth (post-hoc fixpoint). `recovery_plan_signatures` is the set
    # of alt_spec signatures already attempted this query; the reducer refuses
    # to re-issue an ALTERNATIVE whose plan has been tried (predictive fixpoint).
    pre_recovery_packet_signature: NotRequired[dict]    # {node_count, edge_count, path_count}
    recovery_plan_signatures: NotRequired[list[str]]    # canonical alt_spec digests

    # v5: Backend structural analysis (produced by backend_execute, consumed by Company)
    # v6 note: `candidate_set_quality` is subsumed by `evidence_packet.packet_provenance`
    # and `evidence_packet.degradation_flags`. `relation_proof_status` is now
    # derived by `company_prep` from the packet's path_records/edge_records.
    # These fields remain for v5 transitional compatibility and may be removed.
    candidate_set_quality: NotRequired[dict]       # {bridge_count, landmark_count, leaf_fraction, warnings}
    cross_cluster_opportunities: NotRequired[list]  # [{node_id, node_label, appears_in_clusters, note}]
    entity_resolution: NotRequired[dict]            # Option B: deterministic entity resolution output
    relation_proof_status: NotRequired[dict]        # Option B: relation proof output — v6: derived in company_prep
    evidence_status: NotRequired[dict]              # Option B: soft gate state
    company_intent: NotRequired[dict]               # Option B: planner-produced company intent contract

    # v5: Degradation observability (accumulated across all tiers)
    degradation_flags: NotRequired[list]    # typed signals: planner_schema_fallback, squad_parse_error:N, evidence_brief_incomplete, etc.
    validation_result: NotRequired[dict]    # output of evidence brief validation layer: {valid, degradation_flags}
    planner_mode: NotRequired[str]          # "nominal" | "schema_fallback" — set by planner_initial, read by Battalion

    # v6: Information Infrastructure (append-only canonical evidence)
    evidence_packet: NotRequired[dict]           # EvidencePacket as dict
    retrieval_program: NotRequired[dict]         # canonical retrieval-v1 program executed this round
    execution_receipt: NotRequired[dict]         # deterministic operation/count/timing receipt
    answer_contract: NotRequired[dict]           # AnswerContract from Planner
    company_dossier: NotRequired[dict]           # CompanyDossier produced by company_prep
    company_verdict: NotRequired[dict]           # CompanyVerdict produced by company_llm
    semantic_validation_result: NotRequired[dict]  # {valid, degradation_flags, corrections_applied}

    # rung-two routing: sticky governance/coverage-question signal. Set once by
    # planner_initial when the FIRST classification is meta_gap/existence/gap, it
    # survives reseed (reseed never re-emits it) so the compass_derivation→
    # Battalion demote does not regress to compass_derivation_respond after a
    # reseed loses the original query_class. See _select_pipeline_route.
    governance_question: NotRequired[bool]

    # v7: Three-pipeline dispatch + correction loops
    planner_route: NotRequired[str]                 # "compass_derivation" | "targeted_retrieval" | "exploratory"
    classifier_rationale: NotRequired[str]          # one-sentence justification from Planner
    map_reader_output: NotRequired[dict]            # Pipeline A payload (MapReaderAnswer as dict)
    relational_contract: NotRequired[dict]          # Pipeline B payload (RelationalContract as dict)
    hypothesis_grounding_result: NotRequired[dict]  # {verified_ids, missing_ids, proceed}
    tool_dispatch_validation_result: NotRequired[dict]  # {mismatches, replan_required}
    hypothesis_thread: NotRequired[dict]            # Pipeline C: Strategy B reasoning propagated to Battalion
    deterministic_verdict: NotRequired[dict]        # {kind, basis, recovery_available, terminal}
    grammar_guard_triggered: NotRequired[bool]      # v9.x: deterministic pre-Planner ILL_POSED short-circuit
    plan_validation_ill_posed: NotRequired[bool]    # v11: plan validation terminated with structurally_unsupported
    plan_validation_result: NotRequired[dict]       # v11: PlanValidationResult dict for telemetry

    # Battalion output
    final_answer: str
    provenance: list                     # trail → claim mapping
    gaps: list                           # verbatim from company


# ---------------------------------------------------------------------------
# Corpus Testing Schema (see `design [new]/testing-corpus.md`)
# ---------------------------------------------------------------------------
#
# A declarative per-case schema for the query corpus under `tests/corpus/`.
# The corpus is the source of truth for Stage-A (deterministic) and Stage-B
# (LLM-judge) evaluation runs; see `scripts/run_corpus.py` + `corpus_eval.py`.
#
# Design points:
#   * Shape is YAML-authored. This schema only validates what is committed —
#     generated proposals live under `tests/corpus/proposals/` and must be
#     promoted by a human.
#   * `ground_truth` carries deterministic facts the harness can check without
#     invoking an LLM. `rubric` carries semantic expectations evaluated by the
#     optional Stage-B LLM judge.
#   * The per-case identifier is a stable, human-meaningful slug; it is how
#     baselines, reports, and diffs cross-reference results.


class CorpusGroundTruth(BaseModel):
    """Deterministic claims about a query's correct response (Stage A checks).

    All fields are optional. The evaluator only asserts what is present — a
    case that only sets ``expected_verdict`` is valid and will be checked for
    that alone. Missing fields are not enforced.
    """
    answerable: bool = Field(
        default=True,
        description="Is this query answerable by the seed graph? `False` is a meta_gap probe.",
    )
    required_edge_types: list[str] = Field(
        default_factory=list,
        description="Edge types that MUST appear in `evidence_packet.edge_records` (case-insensitive).",
    )
    required_node_ids_any: list[str] = Field(
        default_factory=list,
        description="At least one of these node ids must appear in `node_records` (OR-semantics).",
    )
    required_node_ids_all: list[str] = Field(
        default_factory=list,
        description="All of these node ids must appear in `node_records` (AND-semantics).",
    )
    min_edge_count: int = Field(
        default=0,
        description="Packet must contain at least this many edge records overall.",
        ge=0,
    )
    min_node_count: int = Field(
        default=0,
        description="Packet must contain at least this many node records overall.",
        ge=0,
    )
    expected_verdict: list[str] = Field(
        default_factory=list,
        description="Confirmation verdicts that are considered correct, e.g. ['CONFIRMED'] or ['CONFIRMED','EXHAUSTED'].",
    )
    expected_gap_types_forbidden: list[str] = Field(
        default_factory=list,
        description="Gap types that MUST NOT appear in `company_handoff.internal_handoff.gaps` for this query.",
    )
    expected_gap_types_required: list[str] = Field(
        default_factory=list,
        description="Gap types that MUST appear (only meaningful for meta_gap / absence queries).",
    )
    degradation_flags_allowed: list[str] = Field(
        default_factory=list,
        description="Whitelist of tolerated degradation flags. Any other flag fails Stage A.",
    )
    degradation_flags_forbidden: list[str] = Field(
        default_factory=list,
        description="Explicit deny-list — takes precedence over `allowed`.",
    )
    # v8: two-axis routing expectations (§12). All optional — when unset the
    # evaluator skips the corresponding check, preserving backward compatibility
    # with v6/v7-authored cases.
    expected_retrieval_strategy: str = Field(
        default="",
        description="v8: one of 'compass_derivation', 'contract_driven', 'exploratory'. Empty = not asserted.",
    )
    expected_synthesis_mode: str = Field(
        default="",
        description="v8: one of 'factual', 'synthesised'. Empty = not asserted.",
    )
    strategy_is_hard_expectation: bool = Field(
        default=False,
        description="v8: if True, a retrieval_strategy/synthesis_mode mismatch fails Stage-A. If False, recorded as advisory symptom only.",
    )
    compass_landmark_count_expected: int = Field(
        default=0,
        ge=0,
        description="v8: for compass_derivation cases, expected minimum NodeRecord count populated from Compass landmarks. Fires compass_derivation_packet_underpopulated when packet has fewer.",
    )

    @field_validator(
        "required_edge_types",
        "required_node_ids_any",
        "required_node_ids_all",
        "expected_verdict",
        "expected_gap_types_forbidden",
        "expected_gap_types_required",
        "degradation_flags_allowed",
        "degradation_flags_forbidden",
        mode="before",
    )
    @classmethod
    def _coerce_strs(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


class CorpusRubric(BaseModel):
    """Semantic expectations for Stage-B LLM judge evaluation.

    The judge compares ``actual_answer`` against ``expected_answer_summary``
    (authored by a human after generator/drafter review). ``must_contain`` /
    ``must_not_contain`` are surface-level anchors — keep them short and
    stable; long substring checks make the corpus brittle.
    """
    expected_answer_summary: str = Field(
        default="",
        description="Free-form description of what a correct answer must cover; the judge's reference.",
    )
    must_contain: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substrings the answer should include (used both by judge and as an optional Stage-A anchor check).",
    )
    must_not_contain: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substrings the answer must not include (e.g. false-denial phrases).",
    )
    expected_aspects: list[str] = Field(
        default_factory=list,
        description="Named conceptual aspects the judge should look for (informs `missing_aspects`).",
    )

    @field_validator(
        "must_contain",
        "must_not_contain",
        "expected_aspects",
        mode="before",
    )
    @classmethod
    def _coerce_strs(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


class CorpusCase(BaseModel):
    """One row of the testing corpus — one query to run and evaluate.

    Keyed by ``id``; ``seed`` selects the graph fixture to load. ``query_class``
    reuses the same :data:`V6_QUERY_CLASS` Literal the Planner uses, so
    taxonomy drift is caught at schema-validation time rather than during a
    run.
    """
    id: str = Field(..., min_length=1, description="Stable slug, e.g. 'lotr_enum_expresses'.")
    query: str = Field(..., min_length=1, description="The user-facing question to submit to the engine.")
    seed: str = Field(..., min_length=1, description="Seed profile name, matching `seeds.get_seed_data` keys.")
    query_class: V6_QUERY_CLASS = Field(default="unknown")
    evidence_shapes_expected: list[V6_EVIDENCE_SHAPE] = Field(
        default_factory=lambda: ["node_set"],
        description="Canonical shapes the packet is expected to carry.",
    )
    proof_mode: V6_PROOF_MODE = Field(default="semantic")
    scope: V6_SCOPE = Field(default="local")
    ground_truth: CorpusGroundTruth = Field(default_factory=CorpusGroundTruth)
    rubric: CorpusRubric = Field(default_factory=CorpusRubric)
    tags: list[str] = Field(
        default_factory=list,
        description="Freeform labels (e.g. 'regression', 'long-tail'). Used only for reporting filters.",
    )
    notes: str = Field(default="", description="Human note / provenance / rationale.")

    @field_validator("evidence_shapes_expected", mode="before")
    @classmethod
    def _coerce_shapes(cls, v: Any) -> list[str]:
        if v is None:
            return ["node_set"]
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(s) for s in v if s]
        return ["node_set"]

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: Any) -> str:
        s = _coerce_optional_str(v).strip()
        if not s:
            raise ValueError("CorpusCase.id must be a non-empty string")
        return s


class JudgeVerdict(BaseModel):
    """Output of the Stage-B LLM judge for one case.

    * ``faithfulness`` — does the answer stay true to the packet?
    * ``completeness`` — does the answer cover the rubric's expected aspects?
    * ``alignment`` — does the answer match the rubric's
      ``expected_answer_summary`` in substance?

    Scores are floats in ``[0, 1]``; aggregation is by simple mean.

    The corpus infrastructure treats Stage-B as **advisory** — a drop in any
    dimension is surfaced for review but does not block merges.
    """
    faithfulness: float = Field(ge=0.0, le=1.0, default=0.0)
    completeness: float = Field(ge=0.0, le=1.0, default=0.0)
    alignment: float = Field(ge=0.0, le=1.0, default=0.0)
    hallucination_detected: bool = Field(default=False)
    hallucinated_claims: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    one_line_diagnosis: str = Field(default="")

    @field_validator(
        "hallucinated_claims",
        "missing_aspects",
        mode="before",
    )
    @classmethod
    def _coerce_strs(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)

    @field_validator("one_line_diagnosis", mode="before")
    @classmethod
    def _coerce_diag(cls, v: Any) -> str:
        return _coerce_optional_str(v)
