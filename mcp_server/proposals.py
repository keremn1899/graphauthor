"""Propose verb machinery — contract §2.6 + write-autonomy-reversal-v1 (L0).

Flow:

    agent propose (MCP)  →  PENDING in WritePathStore  →  confirm_proposal
    (snapshot → apply → optional encode battery) → COMMITTED, or restore
    on mechanical refusal (invalid encoding, grain, convention, red battery).

Propose is the write. There is no human approval queue. MCP still has no
confirm verb; ``confirm_proposal`` is the apply function propose calls.
A declared gate battery is optional: without one, a valid encoding still
commits. Cardinal correction flips (toward governed) still refuse.

Doctrinal commitments in code:
- Proposals are SST-shaped (typed concepts + four edge primitives); free-text
  and unknown-edge-type payloads are schema-invalid and never stored.
- ``propose`` does not apply encodings itself. Commit is ``confirm_proposal``.
- L1 claims are demoted to L0 with a recorded reason; the write still proceeds.
- A declared encode battery is optional. Red still restores the snapshot.
- Atomicity by snapshot-restore: the pre-encode snapshot is restored on any
  gate red or apply failure, so a failed encode leaves no partial state.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

import interaction.event_types as event_types
from pydantic import BaseModel, Field, field_validator

SST_EDGE_TYPES = ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO")

L1_ADMISSION_INCOMPLETE = (
    "L1 not admitted: write-autonomy-reversal-v1 §4 checklist incomplete "
    "(live nonce verification and a real domain encode adapter are open); "
    "demoted to L0 human-confirm queue"
)


# ---------------------------------------------------------------------------
# Typed proposal
# ---------------------------------------------------------------------------


class ProposalConcept(BaseModel):
    id: str
    label: str
    text_content: str
    semantic_anchor: str = ""
    # User-format kind from graph.md. This is deliberately distinct from
    # claim_kind, which records normative authority.
    kind: str = ""
    claim_kind: Literal[
        "", "governing", "contextual", "interpretation", "navigation"
    ] = ""

    @field_validator("id", "label", "text_content")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("must be non-empty")
        return v


class ProposalEdge(BaseModel):
    # Contract-bound callers name the semantic predicate; the harness derives
    # the SST primitive. `type` remains accepted for legacy graphs.
    type: Literal["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"] | None = None
    source_id: str
    target_id: str
    predicate: str = ""
    label: str = ""


class EdgeRetype(BaseModel):
    """Move an EXISTING edge to a different SST primitive.

    The last object with no repair route. A wrong primitive is not cosmetic:
    `cattrs-built` authored four supersession relations on NEARTO instead of
    LEADSTO, and a LEADSTO-keyed supersession program scored **0.20 recall** on
    it while the correction path's `antecedents_of` saw **1 of 4**. Retyping
    those four edges and changing nothing else took recall to 1.00 and
    antecedents to 5.

    Deliberately a RETYPE, not a delete-and-add. The relation is not in dispute
    — its source, target and label are all correct — only the primitive carrying
    it is wrong. Expressing that as a removal plus an addition would lose the
    fact that they are the same assertion, and would let a caller quietly change
    the endpoints or the label in the same breath.

    `to_type` is validated against the graph's own convention by
    `edge_convention`: a retype that CREATES a split is refused exactly like an
    inconsistent add.
    """

    source_id: str
    target_id: str
    label: str
    from_type: Literal["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]
    to_type: Literal["LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"]
    reason: str

    @field_validator("label", "reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("must be non-empty")
        return v


class ProposalCorrection(BaseModel):
    """Replace the content of an EXISTING node — a factual repair.

    Deliberately distinct from supersession. Supersession records that a claim
    was true and later stopped being so; a correction says it was never true,
    and preserving the false text as history would itself be false.

    Mutating does not cost the audit trail: `confirm_proposal` snapshots
    pre-encode and `SnapshotStore.restore(graph_version)` exists, so the prior
    graph version remains the record of what the graph said at decision time.
    Node-level immutability is not what buys the audit here.
    """

    id: str
    text_content: str
    reason: str
    label: str = ""
    semantic_anchor: str = ""
    # What this correction is FOR, stated before the gate runs. This ordering is
    # the whole reason a move can be auto-accepted without the gate approving
    # its own findings: the acceptance rule exists before the finding does.
    # `restate` is the default because it is the strict one — it expects nothing
    # to move, so a typo'd or omitted intent cannot buy permission.
    intent: Literal["restate", "withdraw_force"] = "restate"
    # Retag the node's role. Empty leaves it alone — the common case, and the
    # safe default, since silently retagging on every correction would make a
    # typo fix able to change what a node IS.
    #
    # DEMOTION (governing -> contextual) is the repair the gate exists for: a
    # node that should never have carried authority. PROMOTION is the direction
    # that needs watching, and it used to slip past entirely — the gate sized
    # itself on the node's CURRENT kind, so promoting a contextual node made it
    # governing without any before/after comparison at all.
    # `interpretation` was missing here while `ProposalConcept` accepted it, so
    # a node could be proposed as interpretation and then never corrected back
    # to it. The commit that introduced this list (3ef8088) explains the
    # promotion gate at length and never mentions the omission, so it was an
    # oversight rather than a decision.
    #
    # Merging interpretation and navigation into one `authored` kind was tested
    # as the alternative, since nothing distinguishes them. It is worse: 141
    # `navigation` and 36 `interpretation` nodes exist across 24 graphs on disk,
    # so the stored values need an alias map to keep resolving, and the removed
    # constants need to stay exported for callers — leaving five names for three
    # values, which is more vocabulary than the four it replaced.
    claim_kind: Literal[
        "", "governing", "contextual", "interpretation", "navigation"
    ] = ""
    # Predicates whose governance verdict this correction is expected to move.
    #
    # Measured across every governing decision in the cattrs reference, 9 of 11
    # corrections moved a verdict nobody had declared — asking a caller to fill
    # this in was asking for the computation the gate performs. It is retained
    # for callers that genuinely know, and unioned with what the gate itself
    # reports; the workflow no longer depends on it being complete.
    declared_changes: list[str] = Field(default_factory=list)

    @field_validator("id", "text_content", "reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("must be non-empty")
        return v


class SSTProposal(BaseModel):
    concepts: list[ProposalConcept] = Field(default_factory=list)
    edges: list[ProposalEdge] = Field(default_factory=list)
    corrections: list[ProposalCorrection] = Field(default_factory=list)
    edge_retypes: list[EdgeRetype] = Field(default_factory=list)

    @field_validator("edges")
    @classmethod
    def _something(cls, v, info):
        return v

    def is_empty(self) -> bool:
        return (not self.concepts and not self.edges and not self.corrections
                and not self.edge_retypes)

    def is_add_only(self) -> bool:
        # A retype changes an existing assertion's structural operation, so it
        # is not add-only and must face the same gate a correction does — the
        # oracle reads structure, and moving an edge onto an undirected
        # primitive changes what a program retrieves.
        return not self.corrections and not self.edge_retypes


class ProposalProvenance(BaseModel):
    generating_task: str = ""
    source_refs: list[str] = Field(default_factory=list)
    conversation_id: str = ""
    decision_origin: Literal[
        "unspecified", "recover_existing", "propose_new"
    ] = "unspecified"


# ---------------------------------------------------------------------------
# Gate spec — pin battery + runner, domain-parameterized
# ---------------------------------------------------------------------------


@dataclass
class GateSpec:
    """Everything the encode gate needs. ``runner`` produces
    ``(closure_rows, post_rows)`` — live batteries invoke the engine per pin;
    harness batteries inject rows (label them as such in findings)."""

    target_gap_id: str
    policy_id: str
    policy_in_grounding: Callable[[dict, str], bool]
    adjacent_only: Callable[[dict], bool]
    runner: Callable[[], tuple[list[dict], dict[str, list[dict]]]]
    baseline: dict[str, dict]
    gap_anchor_ids: tuple = ()
    flaky_anchor_ids: tuple = ()
    intrinsic_ids: tuple = ()
    intentional_closure_ids: tuple = ()
    encoded_gap_ids: tuple = ()
    also_valid: list[str] = field(default_factory=list)
    wrong_adjacent: list[str] = field(default_factory=list)
    min_gov_rate: float = 0.7
    # L2-3 split runners (additive; batch commits REQUIRE them so the pin
    # battery can run once per batch): closure_runner() -> closure_rows,
    # pins_runner() -> post_rows. When absent, `runner` remains the
    # single-proposal path unchanged.
    closure_runner: Callable[[], list[dict]] | None = None
    pins_runner: Callable[[], dict[str, list[dict]]] | None = None


# ---------------------------------------------------------------------------
# Validation against the live graph
# ---------------------------------------------------------------------------


class UninitialisedGraphError(RuntimeError):
    """The path holds no Concept table, so there is no graph to propose against.

    Distinct from `engine.EmptyGraphError`, which means a real graph with no
    rows. This one means no schema at all — the state a greenfield project is
    in before its first write, and the only state from which the very first
    constitution node must be authored.

    It exists because that path used to surface as a raw Ladybug
    `Binder exception: Table Concept does not exist`, which says nothing about
    what to do. A proposal against a schema-initialised graph holding zero
    nodes is accepted, so the fix is one step and worth naming: create the
    graph through `engine`, which builds the current schema — including
    `claim_kind`, without which nothing authored here can ever carry authority.
    """


def _existing_ids(db_path: Path) -> set[str]:
    import real_ladybug as lb

    db = lb.Database(str(db_path))
    conn = lb.Connection(db)
    try:
        res = conn.execute("MATCH (c:Concept) RETURN c.id")
    except RuntimeError as exc:
        if "Concept" in str(exc) and "not exist" in str(exc):
            raise UninitialisedGraphError(
                f"no Concept table at {db_path} — the graph has no schema yet. "
                "Create it through engine (which writes the current schema, "
                "claim_kind included) before proposing; an empty graph with a "
                "schema accepts writes."
            ) from exc
        raise
    out = set()
    while res.has_next():
        out.add(str(res.get_next()[0]))
    del conn, db
    return out


def _existing_format_kinds(db_path: Path) -> dict[str, str]:
    """Read stored format kinds; legacy graphs without the column return empty."""
    import real_ladybug as lb

    db = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(db)
    out: dict[str, str] = {}
    try:
        try:
            res = conn.execute("MATCH (c:Concept) RETURN c.id, c.kind")
        except RuntimeError:
            return out
        while res.has_next():
            node_id, kind = res.get_next()
            out[str(node_id)] = str(kind or "").strip()
        return out
    finally:
        del conn, db


def validate_proposal(
    raw_encoding: dict,
    db_path: Path,
    *,
    graph_contract_path: Path | str | None = None,
) -> tuple[SSTProposal | None, str]:
    """Returns (proposal, "") or (None, error). Never stores anything."""
    try:
        prop = SSTProposal.model_validate(raw_encoding or {})
    except Exception as exc:
        return None, f"invalid encoding: {exc}"
    if prop.is_empty():
        return None, (
            "invalid encoding: proposal must add at least one concept or edge, "
            "or correct at least one existing node"
        )
    try:
        existing = _existing_ids(db_path)
    except UninitialisedGraphError as exc:
        # Kept inside the (proposal, error) contract every caller already
        # handles, rather than propagating — the greenfield first write is the
        # one place this happens, and it should read as a refusal with a next
        # step, not as a stack trace.
        return None, str(exc)
    known = existing | {c.id for c in prop.concepts}
    for e in prop.edges:
        for endpoint in (e.source_id, e.target_id):
            if endpoint not in known:
                return None, f"unknown node reference: {endpoint!r} (not in graph or proposal)"
    # Checked before the add/correct rules below, because "you listed this id
    # as both" is the actionable message; either of those would otherwise fire
    # first and report a symptom.
    corrected = {c.id for c in prop.corrections}
    collide = corrected & {c.id for c in prop.concepts}
    if collide:
        return None, (
            f"invalid encoding: id(s) both added and corrected: {sorted(collide)} "
            "— add introduces a new node, correct repairs an existing one"
        )
    dup = {c.id for c in prop.concepts} & existing
    if dup:
        return None, f"invalid encoding: concept id(s) already exist in graph: {sorted(dup)}"
    # Corrections are the exact inverse of adds: the id MUST already exist,
    # because a correction repairs a published claim rather than introducing one.
    missing = corrected - existing
    if missing:
        return None, (
            f"invalid encoding: correction target(s) not in graph: {sorted(missing)} "
            "— a correction repairs an existing node; add it as a concept instead"
        )
    if len(corrected) != len(prop.corrections):
        return None, "invalid encoding: duplicate correction target(s)"
    # A mixed proposal would compare only the correction half in the gate while
    # committing concepts and edges as well — the compared edit would not be the
    # committed edit. Keep those as separate proposals.
    if prop.corrections and (prop.concepts or prop.edges):
        return None, (
            "invalid encoding: corrections cannot be mixed with concept or "
            "edge additions — submit them as separate proposals so the gate "
            "compares exactly what would commit"
        )
    # Retypes obey the same rule and for the same reason: a mixed proposal would
    # gate one half and commit both.
    if prop.edge_retypes and (prop.concepts or prop.edges or prop.corrections):
        return None, (
            "invalid encoding: edge retypes cannot be mixed with other "
            "operations — submit them as a separate proposal so the gate "
            "compares exactly what would commit"
        )
    if prop.edge_retypes:
        error = _validate_retypes(prop, db_path)
        if error:
            return None, error
    if graph_contract_path and Path(graph_contract_path).exists():
        from mcp_server.graph_contract import (
            GraphContractError,
            load_graph_contract,
            node_id_matches_kind,
        )

        try:
            contract = load_graph_contract(graph_contract_path)
        except GraphContractError as exc:
            return None, f"invalid graph contract: {exc}"
        spec = contract.specification
        kinds = _existing_format_kinds(db_path)
        for concept in prop.concepts:
            concept.kind = str(concept.kind or "").strip()
            if concept.kind not in spec.node_kinds:
                return None, (
                    f"invalid encoding: concept {concept.id!r} kind "
                    f"{concept.kind!r} is not declared by graph.md"
                )
            if not node_id_matches_kind(concept.id, concept.kind, spec):
                return None, (
                    f"invalid encoding: concept id {concept.id!r} does not match "
                    f"kind {concept.kind!r} pattern "
                    f"{spec.node_kinds[concept.kind].id_pattern!r}"
                )
            kinds[concept.id] = concept.kind

        def _kind_for(node_id: str) -> str:
            stored = kinds.get(node_id, "")
            if stored:
                return stored
            # Compatibility adapter: pre-contract nodes can participate when
            # their stable id unambiguously identifies a declared kind.
            matches = [
                name
                for name in spec.node_kinds
                if node_id_matches_kind(node_id, name, spec)
            ]
            return matches[0] if len(matches) == 1 else ""

        for edge in prop.edges:
            predicate = str(edge.predicate or edge.label or "").strip()
            if predicate not in spec.predicates:
                return None, (
                    f"invalid encoding: edge predicate {predicate!r} is not "
                    "declared by graph.md"
                )
            predicate_spec = spec.predicates[predicate]
            if edge.type is not None and edge.type != predicate_spec.sst:
                return None, (
                    f"invalid encoding: predicate {predicate!r} derives SST "
                    f"{predicate_spec.sst}, not caller-supplied {edge.type}"
                )
            source_kind = _kind_for(edge.source_id)
            target_kind = _kind_for(edge.target_id)
            if not source_kind or not target_kind:
                return None, (
                    "invalid encoding: contract-bound edges require known endpoint "
                    f"kinds ({edge.source_id!r}={source_kind or 'unknown'}, "
                    f"{edge.target_id!r}={target_kind or 'unknown'})"
                )
            if (
                predicate_spec.source_kinds
                and source_kind not in predicate_spec.source_kinds
            ):
                return None, (
                    f"invalid encoding: predicate {predicate!r} does not allow "
                    f"source kind {source_kind!r}"
                )
            if (
                predicate_spec.target_kinds
                and target_kind not in predicate_spec.target_kinds
            ):
                return None, (
                    f"invalid encoding: predicate {predicate!r} does not allow "
                    f"target kind {target_kind!r}"
                )
            edge.predicate = predicate
            edge.label = predicate
            edge.type = predicate_spec.sst
    else:
        missing_types = [
            f"{edge.source_id}->{edge.target_id}"
            for edge in prop.edges
            if edge.type is None
        ]
        if missing_types:
            return None, (
                "invalid encoding: legacy graphs require edge type; "
                f"missing for {missing_types}"
            )
    return prop, ""


def _validate_retypes(prop: SSTProposal, db_path: Path) -> str:
    """The named edge must exist, on the type the caller says it is on.

    `from_type` is required rather than inferred so a retype cannot silently
    act on a different edge than the author was looking at — the same reason
    the correction path binds an acknowledgement to a content hash.
    """
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    present: set[tuple[str, str, str, str]] = set()
    try:
        for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
            result = conn.execute(
                f"MATCH (a:Concept)-[e:{rel}]->(b:Concept) "
                "RETURN a.id, b.id, e.label")
            while result.has_next():
                s, d, label = result.get_next()
                present.add((rel, str(s), str(d), str(label or "").strip().lower()))
    finally:
        del conn, database

    seen: set[tuple[str, str, str]] = set()
    for retype in prop.edge_retypes:
        key = (retype.from_type, retype.source_id, retype.target_id,
               retype.label.strip().lower())
        if key not in present:
            return (
                f"invalid encoding: no {retype.from_type} edge "
                f"{retype.source_id}->{retype.target_id} labelled "
                f"{retype.label!r} in graph — retype names an existing edge"
            )
        if retype.from_type == retype.to_type:
            return (
                f"invalid encoding: retype of {retype.source_id}->"
                f"{retype.target_id} changes nothing ({retype.from_type})"
            )
        identity = (retype.source_id, retype.target_id, retype.label.strip().lower())
        if identity in seen:
            return "invalid encoding: duplicate edge retype"
        seen.add(identity)
    return ""


# ---------------------------------------------------------------------------
# Apply + gate + commit (operator path only)
# ---------------------------------------------------------------------------


def _commit_subjects(prop: SSTProposal) -> tuple[list[str], dict[str, Any]]:
    """Subjects and payload for a GRAPH_COMMITTED event.

    Corrections rewrite existing ids — they must appear in ``subject_node_ids``
    or lineage cannot find the commit and D1's "mutation is honest because
    history records it" claim fails for live readers of the node.
    """
    node_ids = [c.id for c in prop.concepts] + [c.id for c in prop.corrections]
    payload: dict[str, Any] = {
        "subject_edge_refs": [
            f"{e.type}:{e.source_id}->{e.target_id}" for e in prop.edges
        ],
    }
    if prop.corrections:
        payload["subject_correction_ids"] = [c.id for c in prop.corrections]
        payload["correction_reasons"] = [
            {
                "id": c.id,
                "reason": c.reason,
                "intent": c.intent,
                "claim_kind": c.claim_kind,
            }
            for c in prop.corrections
        ]
    return node_ids, payload


def _apply(db_path: Path, prop: SSTProposal, embedder: Callable[[str], list[float]]) -> None:
    import real_ladybug as lb

    db = lb.Database(str(db_path))
    conn = lb.Connection(db)
    for c in prop.concepts:
        conn.execute(
            "CREATE (:Concept {id: $id, label: $label, text_content: $tc, "
            "semantic_anchor: $a, kind: $format_kind, claim_kind: $kind, "
            "claim_kind_source: $kind_source, embedding: $emb, token_count: $tok, "
            "centrality_score: 0.0, is_metanode: false, linked_graph_id: ''})",
            {
                "id": c.id,
                "label": c.label,
                "tc": c.text_content,
                "a": c.semantic_anchor or c.text_content[:180],
                "format_kind": c.kind,
                "kind": c.claim_kind,
                "kind_source": "declared" if c.claim_kind else "",
                "emb": embedder(c.text_content),
                "tok": max(1, len(c.text_content) // 4),
            },
        )
    for e in prop.edges:
        if e.type is None:
            raise ValueError(
                f"edge {e.source_id}->{e.target_id} has no derived SST type"
            )
        conn.execute(
            f"MATCH (a:Concept {{id: $s}}), (b:Concept {{id: $t}}) "
            f"CREATE (a)-[:{e.type} {{label: $l}}]->(b)",
            {"s": e.source_id, "t": e.target_id, "l": e.label or None},
        )
    for retype in prop.edge_retypes:
        # Delete then create, because the SST primitive is the REL TABLE itself
        # — there is no ALTER for an edge's type. The label, endpoints and
        # direction are carried across unchanged: this moves one assertion to a
        # different structural operation, it does not author a new one.
        conn.execute(
            f"MATCH (a:Concept)-[e:{retype.from_type}]->(b:Concept) "
            "WHERE a.id = $s AND b.id = $t DELETE e",
            {"s": retype.source_id, "t": retype.target_id},
        )
        conn.execute(
            f"MATCH (a:Concept), (b:Concept) WHERE a.id = $s AND b.id = $t "
            f"CREATE (a)-[:{retype.to_type} {{label: $l}}]->(b)",
            {"s": retype.source_id, "t": retype.target_id,
             "l": retype.label or None},
        )
    for corr in prop.corrections:
        # The embedding MUST be recomputed. Leaving the old vector in place
        # would keep vector search answering with the text we just declared
        # false — a correction that is invisible to retrieval is not a
        # correction. token_count and the anchor follow the new text for the
        # same reason.
        conn.execute(
            "MATCH (c:Concept {id: $id}) SET c.text_content = $tc, "
            "c.label = CASE WHEN $label = '' THEN c.label ELSE $label END, "
            "c.claim_kind = CASE WHEN $kind = '' THEN c.claim_kind ELSE $kind END, "
            "c.claim_kind_source = CASE WHEN $kind = '' THEN c.claim_kind_source "
            "ELSE 'declared' END, "
            "c.semantic_anchor = $a, c.embedding = $emb, c.token_count = $tok",
            {
                "id": corr.id,
                "tc": corr.text_content,
                "kind": corr.claim_kind,
                "label": corr.label,
                "a": corr.semantic_anchor or corr.text_content[:180],
                "emb": embedder(corr.text_content),
                "tok": max(1, len(corr.text_content) // 4),
            },
        )
    del conn, db


def _claim_kinds(db_path: Path, ids: set[str]) -> dict[str, str]:
    import real_ladybug as lb

    if not ids:
        return {}
    db = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(db)
    out: dict[str, str] = {}
    try:
        res = conn.execute("MATCH (c:Concept) RETURN c.id, c.claim_kind")
        while res.has_next():
            row = res.get_next()
            node_id = str(row[0] or "")
            if node_id in ids:
                out[node_id] = str(row[1] or "")
    finally:
        del conn, db
    return out


def _scratch_copy(db_path: Path) -> Path:
    """A throwaway copy of the graph and its sidecars, for gate evaluation."""
    import shutil
    import tempfile

    scratch_dir = Path(tempfile.mkdtemp(prefix="correction_gate_"))
    target = scratch_dir / db_path.name
    for sibling in db_path.parent.iterdir():
        if sibling.name == db_path.name or sibling.name.startswith(db_path.name + "."):
            if sibling.is_file():
                shutil.copy2(sibling, scratch_dir / sibling.name)
    return target


#: Probes are engine calls, so the region sweep is bounded.
#:
#: TWO hops, not one, and that default is measured rather than guessed. On the
#: cattrs reference graph, correcting a governing decision moved
#: `decision_current_asymmetric_fallbacks` from UNGOVERNED to GOVERNED — the
#: cardinal laundered-authority direction — and that node is two hops out. A
#: one-hop sweep reported the correction as touching one neighbour and would
#: have let the flip through.
REGION_PROBE_HOPS = 2
#: Exceeding the cap REFUSES rather than truncating. A partial comparison that
#: reports "no verdict change" for probes it never ran is the silent-permission
#: failure this engine exists to prevent, and disclosure alone does not stop a
#: caller acting on it. Raise `probe_cap` deliberately to proceed.
REGION_PROBE_CAP = 12
_SST_TYPES = ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO")


#: SUPERSEDED — retained because four benchmarks import it and their runs must
#: stay reproducible. NOT called by the write path: `_complete_probe_universe`
#: replaced it. Falsified in two steps — at 1 hop it missed a cardinal flip two
#: hops out; at 2 hops it still missed one entirely, because an EDGELESS
#: governing node moved two verdicts including a cardinal. Influence travels by
#: embedding proximity, not along edges.
def _region_probes(
    db_path: Path, node_ids: set[str], *,
    hops: int = REGION_PROBE_HOPS, cap: int = REGION_PROBE_CAP
) -> dict[str, Any]:
    """Derive a probe suite from the graph region around the corrected nodes.

    Deliberately NOT derived from what the change declares. The gate exists to
    catch UNDECLARED movement, so a declaration-shaped probe set would verify
    only the honest cases — it would check exactly where the caller already
    told the truth. Structure is the independent signal: a correction can only
    move verdicts for predicates its node can reach.

    Bounded and disclosed: `excluded` names what the cap dropped, so an
    under-covering sweep is visible rather than silent. A too-narrow probe set
    fails in the dangerous direction — it misses a governing move and reads as
    "no verdict change".
    """
    import real_ladybug as lb

    frontier = set(node_ids)
    seen = set(node_ids)
    # READ ONLY. This is a probe: it must never be able to touch the graph it
    # is measuring. Opening read-write here silently modified a frozen
    # reference fixture and tripped its digest guard in 19 unrelated tests.
    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    try:
        for _hop in range(max(0, hops)):
            if not frontier:
                break
            found: set[str] = set()
            for rel in _SST_TYPES:
                for direction in (
                    f"MATCH (a:Concept)-[:{rel}]->(b:Concept) "
                    "WHERE a.id IN $ids RETURN b.id",
                    f"MATCH (a:Concept)<-[:{rel}]-(b:Concept) "
                    "WHERE a.id IN $ids RETURN b.id",
                ):
                    res = conn.execute(direction, {"ids": sorted(frontier)})
                    while res.has_next():
                        found.add(str(res.get_next()[0] or ""))
            frontier = {i for i in found if i and i not in seen}
            seen |= frontier
    finally:
        del conn, database

    ordered = sorted(seen)
    return {
        "probes": ordered[:cap],
        "excluded": ordered[cap:],
        "hops": hops,
        "cap": cap,
        "region_size": len(ordered),
    }


#: How many semantic neighbours join the probe suite.
#:
#: Region-derived probes assume a correction can only move verdicts for
#: predicates its node reaches THROUGH EDGES. That was measured and is FALSE
#: (`semantic_probe_gap_v1_1`): with every edge stripped — region size one — a
#: neutralising rewrite still moved two other verdicts, one of them a cardinal
#: UNGOVERNED->GOVERNED. The oracle is `what_governs`, which answers through the
#: full engine including vector search, and vector search is not edge-gated.
#:
#: No hop count fixes this. A node with degree zero is at distance infinity from
#: everything at every depth, so D5's two hops answer the wrong question. The
#: movers sat at cosine ranks 1 and 4, which is why this is 5 rather than 2.
SEMANTIC_PROBE_K = 10

#: Below this node count the gate probes EVERY node instead of guessing a
#: neighbourhood. Measured (`contextual_influence_v1`, 272 engine calls):
#: movers appeared at cosine ranks 1, 2, 3, 4, 5, 6, 9 and 10 — and 10 was the
#: search depth, so the distribution is right-censored and K cannot be
#: calibrated from it at all. Rank 10 was already 42% of a 24-node graph.
#:
#: There is therefore no cheap sound subset at this scale, and pretending
#: otherwise is how the last three probe-suite defaults were wrong. Exhaustive
#: is also barely more expensive than the guess it replaces: the widest
#: neighbourhood suite measured was 19 probes against 24 nodes.


def _claim_kinds_any_governing(db_path: Path) -> bool:
    """Does this graph hold any governing claim at all?

    The only skip the evidence supports. A correction cannot move a governing
    verdict on a graph that has none.
    """
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    try:
        result = conn.execute(
            "MATCH (n:Concept) WHERE n.claim_kind = 'governing' RETURN count(*)")
        return int(result.get_next()[0]) > 0
    finally:
        del conn, database


def _node_count(db_path: Path) -> int:
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    try:
        return int(conn.execute("MATCH (n:Concept) RETURN count(*)").get_next()[0])
    finally:
        del conn, database


def _all_node_ids(db_path: Path) -> list[str]:
    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    out: list[str] = []
    try:
        result = conn.execute("MATCH (n:Concept) RETURN n.id")
        while result.has_next():
            node_id = str(result.get_next()[0] or "")
            if node_id:
                out.append(node_id)
    finally:
        del conn, database
    return sorted(out)


#: Hard ceiling on the COMPLETE probe universe (every Concept.id, plus any
#: caller-supplied probes). Exceeding it REFUSES rather than truncating or
#: falling back to a neighbourhood guess.
#:
#: Region / top-K heuristics were measured and found unsound: influence travels
#: by embedding proximity as well as edges, and movers appeared across the full
#: similarity ranking on a 24-node graph (`contextual_influence_v1`). At this
#: scale the only sound suite is the whole graph; above the ceiling the product
#: must refuse until the operator raises the cap deliberately.
#: One name for the cap. `EXHAUSTIVE_PROBE_CEILING` was the alias left by the
#: merge that introduced complete-universe probing; it is kept pointing here so
#: nothing imports a second source of truth for the same number.
COMPLETE_PROBE_CAP = 40
EXHAUSTIVE_PROBE_CEILING = COMPLETE_PROBE_CAP


def _complete_probe_universe(
    db_path: Path,
    supplied: list[str] | None = None,
    *,
    cap: int = COMPLETE_PROBE_CAP,
) -> dict[str, Any]:
    """Every graph-addressable Concept.id, unioned with caller probes.

    Never truncates. If the suite is larger than ``cap``, ``exceeds`` is True
    and ``excluded`` names the full suite so the refusal is auditable.
    """
    graph_ids = _all_node_ids(db_path)
    extra = [p for p in (supplied or []) if str(p).strip()]
    suite = sorted(set(graph_ids) | set(extra))
    if len(suite) > cap:
        return {
            "probes": [],
            "excluded": suite,
            "graph_size": len(graph_ids),
            "universe_size": len(suite),
            "cap": cap,
            "exceeds": True,
            "mode": "complete_universe",
        }
    return {
        "probes": suite,
        "excluded": [],
        "graph_size": len(graph_ids),
        "universe_size": len(suite),
        "cap": cap,
        "exceeds": False,
        "mode": "complete_universe",
    }


#: SUPERSEDED — measurement only, not called by the write path. Top-K could not
#: be calibrated at all: observed movers reached cosine rank 10 out of 24 nodes,
#: which was the search limit, so the distribution is right-censored. That is why
#: the gate probes the complete universe and refuses above a cap rather than
#: guessing a sufficient subset.
def _semantic_probes(db_path: Path, node_ids: set[str],
                     k: int = SEMANTIC_PROBE_K) -> list[dict[str, Any]]:
    """Nearest nodes by the embeddings ALREADY STORED in the graph.

    Retained for characterization benchmarks. Production correction gating uses
    ``_complete_probe_universe`` instead — top-K is not a sound safety bound.

    Costs nothing: the vectors are read, never recomputed.
    READ ONLY, like every probe derivation here.
    """
    import math

    import real_ladybug as lb

    database = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(database)
    vectors: dict[str, list[float]] = {}
    try:
        result = conn.execute("MATCH (n:Concept) RETURN n.id, n.embedding")
        while result.has_next():
            node_id, embedding = result.get_next()
            vector = list(embedding) if embedding else []
            if vector and any(vector):
                vectors[str(node_id)] = vector
    finally:
        del conn, database

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0

    scored: dict[str, float] = {}
    for corrected in node_ids:
        reference = vectors.get(corrected)
        if not reference:
            continue
        for candidate, vector in vectors.items():
            if candidate in node_ids:
                continue
            similarity = cosine(reference, vector)
            if similarity > scored.get(candidate, -1.0):
                scored[candidate] = similarity
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return [{"id": i, "similarity": round(s, 4)} for i, s in ranked]


def _correction_gate(
    db_path: Path,
    prop: SSTProposal,
    probes: list[str] | None,
    embedder: Callable[[str], list[float]],
    oracle_factory: Callable[[Any, list[str]], Callable[[Any], dict[str, str]]] | None = None,
    probe_cap: int = COMPLETE_PROBE_CAP,
    probe_hops: int = REGION_PROBE_HOPS,
) -> dict[str, Any]:
    """Run the edit gate over a correction against the complete probe universe.

    Probe selection is exhaustive within ``probe_cap``: every Concept.id on the
    graph, unioned with caller-supplied probes. Neighbourhood heuristics are not
    used on the production path — they under-covered oracle reachability.

    ``probe_hops`` is retained for call-site compatibility with older benchmarks
    and is ignored.

    Returns a decision dict; ``allowed`` False means do not apply.
    """
    from mcp_server.changeset import ChangeOp, ChangeSet, OpKind
    from mcp_server.edit_gate import evaluate_edit, live_oracle

    del probe_hops  # retained for signature compatibility only

    if prop.is_add_only():
        return {"ran": False, "allowed": True, "reason": "add_only_no_corrections"}

    # A retype has no corrected NODE, but it changes what the oracle retrieves
    # around both endpoints — moving a relation onto NEARTO makes it undirected
    # and 4.6x over-retrieving at depth 3 — so the endpoints are what this edit
    # can move verdicts through.
    retype_endpoints = {r.source_id for r in prop.edge_retypes} | {
        r.target_id for r in prop.edge_retypes}
    kinds = _claim_kinds(db_path,
                         {c.id for c in prop.corrections} | retype_endpoints)
    proposed = {c.id: c.claim_kind for c in prop.corrections if c.claim_kind}
    governing = sorted({i for i, k in kinds.items() if k == "governing"}
                       | {i for i, k in proposed.items() if k == "governing"})
    # The only sound skip: a graph with no governing claim anywhere. Measured
    # (`contextual_influence_v1`): non-governing text corrections can still
    # move governing verdicts through retrieval.
    # `governing` matters here, not just the live graph. Checking only what the
    # graph already holds let a correction that CREATES the first governing
    # claim skip the gate entirely — precisely the edit that turns an ungoverned
    # graph into a governing one, unchecked.
    if not governing and not _claim_kinds_any_governing(db_path):
        return {
            "ran": False,
            "allowed": True,
            "reason": "graph_has_no_governing_claim",
            "corrected": sorted(kinds),
            "claim_kinds": kinds,
        }
    supplied = [p for p in (probes or []) if str(p).strip()]
    universe = _complete_probe_universe(db_path, supplied, cap=probe_cap)
    if universe["exceeds"]:
        return {
            "ran": False,
            "allowed": False,
            "reason": "universe_exceeds_probe_cap",
            "governing_targets": governing,
            "universe": universe,
            "probe_mode": "complete_universe",
            "detail": (
                f"the complete probe universe holds {universe['universe_size']} "
                f"predicates but the probe cap is {universe['cap']}; raise "
                "probe_cap to check them all, or narrow the graph"
            ),
        }
    suite = list(universe["probes"])
    if not suite:
        return {
            "ran": False,
            "allowed": False,
            "reason": "no_probes_available_for_governing_correction",
            "governing_targets": governing,
            "universe": universe,
            "probe_mode": "complete_universe",
            "detail": (
                "correcting a claim can move a verdict, and the graph yielded "
                "no probe to compare"
            ),
        }

    declared: list[str] = []
    for corr in prop.corrections:
        declared.extend(corr.declared_changes)
    change_set = ChangeSet(
        base=str(db_path),
        operations=[
            ChangeOp(
                kind=OpKind.REPLACE_CONTENT,
                target_node_id=corr.id,
                payload={"text": corr.text_content,
                         "declared_changes": corr.declared_changes},
            )
            for corr in prop.corrections
        ] + [
            # REMOVE_EDGE is in the gate's edit-op set, so this stops a
            # retype-only proposal reading as add-only and skipping comparison.
            ChangeOp(
                kind=OpKind.REMOVE_EDGE,
                target_node_id=retype.source_id,
                payload={"retype": f"{retype.from_type}->{retype.to_type}",
                         "label": retype.label,
                         "declared_changes": []},
            )
            for retype in prop.edge_retypes
        ],
    )

    # Every scratch copy is a full copy of the graph. They MUST be removed:
    # leaking one per gate run filled a 7GB tmpfs during a single test suite
    # and took 133 unrelated tests down with a disk-quota error.
    scratch_dirs: list[Path] = []

    def _apply_to_scratch(model: Any, _cs: ChangeSet) -> Any:
        scratch = _scratch_copy(Path(str(model)))
        scratch_dirs.append(scratch.parent)
        _apply(scratch, SSTProposal(corrections=prop.corrections), embedder)
        return str(scratch)

    # Injected for the same reason `evaluate_edit` injects its own: the gate's
    # logic must be provable without the engine. Each probe is a `what_governs`
    # call, so a real suite is real model spend.
    make_oracle = oracle_factory or live_oracle
    try:
        decision = evaluate_edit(
            change_set, str(db_path), make_oracle(str(db_path), suite),
            _apply_to_scratch,
        )
    finally:
        import shutil

        for directory in scratch_dirs:
            shutil.rmtree(directory, ignore_errors=True)
    decision["ran"] = True
    decision["probes"] = suite
    decision["probes_supplied"] = sorted(set(supplied))
    decision["probes_region"] = []  # legacy key; production no longer region-sweeps
    decision["probes_semantic"] = []  # legacy key; production no longer top-K
    decision["probes_excluded_by_cap"] = universe["excluded"]
    decision["universe"] = universe
    decision["probe_mode"] = "complete_universe"
    decision["probe_completeness"] = "exhaustive"
    decision["graph_nodes"] = universe["graph_size"]
    decision["region"] = {
        "hops": 0,
        "cap": universe["cap"],
        "region_size": universe["universe_size"],
        "excluded": universe["excluded"],
    }
    decision["governing_targets"] = governing
    decision.setdefault("declared_changes", sorted(set(declared)))
    decision["disposition"] = _dispose_correction(db_path, prop, decision)
    return decision


def _correction_acknowledgement_check(
    db_path: Path, prop: SSTProposal, report: dict[str, Any],
    acknowledgement: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Does this correction have standing to commit?

    Three outcomes. It clears mechanically and commits with nobody in the loop;
    it carries a valid acknowledgement covering the rest and commits; or it does
    not, and the caller gets the report plus the digest to acknowledge against.

    The digest is always returned, including on success, so a caller can bind a
    follow-up without having to reconstruct it.
    """
    from mcp_server import correction_ack

    disposition = report.get("disposition") or {}
    shas = correction_ack.corrected_node_shas(db_path, [c.id for c in prop.corrections])
    digest = correction_ack.report_digest(prop.corrections, shas)
    # Non-comparison refusals have nothing honest to affirm.
    if disposition.get("disposition") == "refused" or (
        disposition.get("compared") is False
        and disposition.get("disposition") != "skipped"
    ):
        return {
            "ok": False,
            "reason": correction_ack.NOT_ACKNOWLEDGEABLE,
            "detail": (
                "this report is not a verdict comparison that can be "
                f"acknowledged; disposition={disposition.get('disposition')}"
            ),
            "report_digest": digest,
            "disposition": disposition,
            "moves": report.get("changed") or {},
            "acknowledgeable": [],
            "requires_escalation": sorted(
                set(disposition.get("cardinal") or ())
                | set(disposition.get("unevaluable") or ())
            ),
        }
    if disposition.get("clears_mechanically"):
        return {"ok": True, "reason": "clears_mechanically", "detail": "",
                "report_digest": digest, "disposition": disposition,
                "declared": disposition.get("auto_accepted") or []}
    outcome = correction_ack.verify(
        acknowledgement, expected_digest=digest,
        rerun_changed=report.get("changed") or {}, classification=disposition)
    return {**outcome, "report_digest": digest, "disposition": disposition,
            "moves": report.get("changed") or {},
            "detail": outcome.get("detail", ""),
            # Everything a caller needs to produce an acknowledgement, so the
            # report is actionable rather than merely informative.
            "acknowledgeable": disposition.get("interpretable") or [],
            "requires_escalation": sorted(
                set(disposition.get("cardinal") or ())
                | set(disposition.get("unevaluable") or ()))}


def _dispose_correction(db_path: Path, prop: SSTProposal,
                        decision: dict[str, Any]) -> dict[str, Any]:
    """Classify what the gate found, mechanically, before anyone interprets it.

    Attached to every gate decision so the report carries its own disposition —
    a caller reading `changed` should never have to re-derive which of those
    moves are laundering and which are the intended effect of the edit.

    Intents are per-correction but the report is per-proposal, so a proposal
    mixing intents is disposed under the STRICTEST one present. Mixing is not
    forbidden, but it must not let a permissive intent on one node license a
    move caused by another.
    """
    from mcp_server.correction_classify import (
        INTENT_RESTATE, antecedents_of, dispose_report,
    )

    intents = {c.intent for c in prop.corrections}
    intent = INTENT_RESTATE if len(intents) != 1 else intents.pop()
    corrected = [c.id for c in prop.corrections]
    # The mechanism may certify a correction as clear only when it actually
    # looked everywhere it needed to. Two ways it did not:
    #
    #   * the suite held nothing but the corrected nodes, so the edit was
    #     compared only against itself;
    #   * the graph was too large to probe exhaustively, so the suite is a
    #     NEIGHBOURHOOD — and measurement says a neighbourhood cannot be known
    #     to be sufficient (movers reached 42% of a 24-node graph, at the search
    #     limit, so that distribution is right-censored).
    #
    # Either way the correction can still proceed; it just needs an affirmation
    # rather than the mechanism's own word.
    independent = bool(set(decision.get("probes") or ()) - set(corrected))
    complete = decision.get("probe_completeness") == "exhaustive"
    return dispose_report(decision, corrected,
                          antecedents_of(db_path, corrected), intent=intent,
                          independent_probe=independent and complete)


def default_embedder() -> Callable[[str], list[float]]:
    """Live embedder via the engine (requires OPENROUTER_API_KEY)."""
    from engine import get_embeddings_model

    model = get_embeddings_model()

    def _embed(text: str) -> list[float]:
        return model.embed_query(text)

    return _embed


def proposal_basis_refusal(
    rec: dict[str, Any], db_path: Path | str
) -> dict[str, Any] | None:
    """Return a pre-mutation refusal when a PENDING judgment is stale.

    The wire version is persisted for attribution.  Equality is enforced with
    the content-true global manifest fingerprint because the wire version also
    includes Ladybug file mtime and can move on a harmless database open.
    """

    expected_version = str(rec.get("expected_graph_version") or "")
    expected_fingerprint = str(rec.get("expected_graph_fingerprint") or "")
    if not expected_version or not expected_fingerprint:
        return {
            "proposal_id": rec.get("proposal_id", ""),
            "status": "PENDING",
            "kind": "REFUSED",
            "error_code": "EXPECTED_GRAPH_BASIS_REQUIRED",
            "error": (
                "proposal has no persisted checked graph basis; resubmit it "
                "against fresh context before confirmation"
            ),
            "retryable": True,
            "agent_mutated_graph": False,
        }

    from mcp_server.history import graph_fingerprint

    current_fingerprint = graph_fingerprint(db_path)
    if current_fingerprint == expected_fingerprint:
        return None
    return {
        "proposal_id": rec.get("proposal_id", ""),
        "status": "PENDING",
        "kind": "REFUSED",
        "error_code": "STALE_GRAPH",
        "error": (
            "graph changed after this proposal was checked; refresh the "
            "regional context, re-check, and submit a new proposal"
        ),
        "expected_graph_version": expected_version,
        "expected_graph_fingerprint": expected_fingerprint,
        "current_graph_fingerprint": current_fingerprint,
        "retryable": True,
        "agent_mutated_graph": False,
    }


def _emit(store_path, **kw):
    from interaction.event_log import emit_event

    return emit_event(store_path, **kw)


def confirm_proposal(
    db_path: Path | str,
    store_path: Path | str,
    proposal_id: str,
    *,
    primary_source: str = "",
    gate: GateSpec | None = None,
    embedder: Callable[[str], list[float]] | None = None,
    authority: Literal["human", "gate", "agent"] = "human",
    actor: str = "operator",
    correction_probes: list[str] | None = None,
    correction_oracle_factory: Callable[..., Any] | None = None,
    correction_probe_cap: int = COMPLETE_PROBE_CAP,
    correction_acknowledgement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Commit a queued proposal through the licensed encode path.

    The CLI and green auto-encode both call this. MCP has no confirm verb.
    Propose auto-commits through this function; there is no human queue.

    `correction_probes` is the predicate suite the edit gate compares before
    and after when the proposal CORRECTS a governing claim. It is required in
    that case and ignored otherwise; see `_correction_gate`.

    A correction that only needs interpretation commits without an
    acknowledgement. A cardinal flip toward governed, or a comparison the
    gate never made, still refuses. `correction_acknowledgement` remains
    accepted for leftover callers and is not a product gate.

    `authority` is the EXPLICIT confirming authority (B4): "human" for an
    operator confirm, "gate" for auto-encode, "agent" for a host-agent
    advance through `HostWriteSurface`. It is recorded on the proposal and on
    the events.

    Typed as a Literal rather than a free string precisely because B4 makes it
    load-bearing: an unconstrained field would record a typo as a novel
    authority, silently, on the one attribute the audit trail exists to pin.

    A declared encode battery is optional. ``primary_source`` is optional
    audit copy, filled from the proposal's ``source_refs`` when omitted.
    Restores the pre-encode snapshot on gate red or apply failure.
    """
    from interaction.write_path_store import WritePathStore
    from mcp_server import correction_ack as ack_reasons
    from mcp_server.history import SnapshotStore, extract_manifest
    from write_path.distractor import check_closure, check_distractors

    db_path = Path(db_path)
    store = WritePathStore(store_path)
    try:
        rec = store.get_proposal(proposal_id)
        if rec is None:
            return {"error": f"unknown proposal: {proposal_id}"}
        if rec["status"] not in ("PENDING",):
            return {"error": f"proposal is {rec['status']}, not PENDING"}
        if not str(primary_source).strip():
            refs = []
            try:
                refs = json.loads(rec.get("source_refs_json") or "[]")
            except (TypeError, ValueError):
                refs = []
            primary_source = next(
                (str(ref).strip() for ref in refs if str(ref).strip()),
                "",
            )
        basis_refusal = proposal_basis_refusal(rec, db_path)
        if basis_refusal is not None:
            return basis_refusal
        from interaction.event_log import latest_event_id

        proposal_cause = latest_event_id(store_path, proposal_id=proposal_id)

        prop, err = validate_proposal(json.loads(rec["encoding_json"]), db_path)
        if prop is None:
            store.update_proposal(proposal_id, status="REJECTED", demotion_reason=f"stale: {err}")
            return {"error": f"proposal no longer valid against the live graph: {err}", "status": "REJECTED"}

        # Evolve-ADD grain gate: the new node must fit the graph's local grain +
        # persisted seeds. Hard violations (sanity / rule fusion) refuse BEFORE
        # any mutation; soft drift is advisory (an incremental add slightly off
        # grain is flagged in the result, not blocked). Same grain_check as
        # create-cert — construction is editing against the empty graph.
        from mcp_server.grain import grain_gate as _grain_gate

        _added = [{"id": c.id, "label": c.label, "text_content": c.text_content} for c in prop.concepts]
        _added_edges = [(e.type, e.source_id, e.target_id, e.label) for e in prop.edges]
        grain_rep = _grain_gate(db_path, _added, _added_edges)
        if not grain_rep["allowed"]:
            store.update_proposal(proposal_id, status="GRAIN_FAILED", demotion_reason=grain_rep["reason"],
                                  decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            return {"proposal_id": proposal_id, "status": "GRAIN_FAILED", "grain": grain_rep,
                    "error": f"grain check failed: {grain_rep['reason']}"}

        # Edge primitive convention. The four SST types survive every ablation
        # run this session, but they are used INCONSISTENTLY, and the cost is
        # measured: a program keyed on LEADSTO for supersession returns 0.20
        # recall on a graph that authored supersession as NEARTO, and
        # `antecedents_of` sees 1 of 4 such relations on `cattrs-built`.
        #
        # The fix belongs here rather than in the schema. Every edge label sits
        # on exactly one primitive in all 37 graphs measured — a convention every
        # author kept by accident — so it can be read off the graph and enforced
        # without inventing a taxonomy. Only COLLISIONS block; a new label has
        # nothing to contradict and is reported, never refused.
        from mcp_server.edge_convention import check_edges as _check_edge_primitives

        _retyped_edges = [(r.to_type, r.source_id, r.target_id, r.label)
                          for r in prop.edge_retypes]
        convention_rep = _check_edge_primitives(db_path,
                                                _added_edges + _retyped_edges)
        if not convention_rep["allowed"]:
            store.update_proposal(
                proposal_id, status="EDGE_CONVENTION_FAILED",
                demotion_reason=convention_rep["reason"],
                decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            return {"proposal_id": proposal_id, "status": "EDGE_CONVENTION_FAILED",
                    "edge_convention": convention_rep,
                    "error": (
                        "edge primitive collision: "
                        + "; ".join(f["repair"] for f in convention_rep["collisions"])
                    )}

        # Correction gate: a correction rewrites a published claim, so an
        # undeclared verdict move must refuse BEFORE any mutation. Add-only
        # proposals skip it exactly as the edit gate's own contract says.
        correction_report = _correction_gate(
            db_path, prop, correction_probes, embedder or default_embedder(),
            oracle_factory=correction_oracle_factory,
            probe_cap=correction_probe_cap,
        )
        disposition = correction_report.get("disposition") or {}
        # Route by disposition/audit state, not the overloaded `ran` flag.
        # `evaluate_edit` marks unevaluable comparisons as ran=True with an
        # empty changed map; treating that as acknowledgeable is silent
        # permission.
        hard_refuse = (
            disposition.get("disposition") == "refused"
            or (
                not correction_report.get("allowed", True)
                and disposition.get("compared") is not True
            )
        )
        if hard_refuse and not correction_report.get("ran"):
            # Never compared (universe overflow, no probes, ...).
            store.update_proposal(
                proposal_id, status="CORRECTION_REFUSED",
                demotion_reason=correction_report.get("reason", ""),
                decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            return {"proposal_id": proposal_id, "status": "CORRECTION_REFUSED",
                    "correction_gate": correction_report,
                    "error": (
                        "correction refused: "
                        f"{correction_report.get('reason', 'undeclared change')}"
                    ),
                    "agent_mutated_graph": False}
        if correction_report.get("ran") or disposition.get("compared"):
            reported = _correction_acknowledgement_check(
                db_path, prop, correction_report, correction_acknowledgement)
            if not reported["ok"]:
                refuse_reasons = {
                    ack_reasons.OVERREACH,
                    ack_reasons.NOT_ACKNOWLEDGEABLE,
                }
                if (
                    reported["reason"] in refuse_reasons
                    or disposition.get("disposition") in ("refused", "escalate")
                ):
                    store.update_proposal(
                        proposal_id, status="CORRECTION_REFUSED",
                        demotion_reason=reported["reason"],
                        decided_at=time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                    return {
                        "proposal_id": proposal_id,
                        "status": "CORRECTION_REFUSED",
                        "correction_gate": correction_report,
                        "correction_report": reported,
                        "error": reported["detail"],
                        "agent_mutated_graph": False,
                    }
                # No human ack step: an interpretable finding does not hold
                # the write. Cardinal toward-governed still refuses above.
        elif not correction_report.get("allowed", True):
            store.update_proposal(
                proposal_id, status="CORRECTION_REFUSED",
                demotion_reason=correction_report.get("reason", ""),
                decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            return {"proposal_id": proposal_id, "status": "CORRECTION_REFUSED",
                    "correction_gate": correction_report,
                    "error": (
                        "correction refused: "
                        f"{correction_report.get('reason', 'undeclared change')}"
                    ),
                    "agent_mutated_graph": False}

        snaps = SnapshotStore(db_path)
        pre_label = f"pre-encode:{proposal_id}"
        snaps.capture(pre_label)
        version_before = pre_label

        status = ""
        gate_report: dict[str, Any] = {}
        try:
            _apply(db_path, prop, embedder or default_embedder())
        except Exception as exc:
            snaps.restore(pre_label)
            status = "ENCODE_FAILED"
            gate_report = {"error": f"apply failed: {type(exc).__name__}: {exc}"}
        else:
            if gate is None:
                status = "COMMITTED"
                gate_report = {"governance_gate": "not_applicable"}
            else:
                closure_rows, post_rows = gate.runner()
                closure = check_closure(
                    gate.target_gap_id,
                    closure_rows,
                    policy_id=gate.policy_id,
                    also_valid=gate.also_valid,
                    wrong_adjacent=gate.wrong_adjacent,
                    policy_in_grounding=gate.policy_in_grounding,
                    adjacent_only=gate.adjacent_only,
                    min_gov_rate=gate.min_gov_rate,
                )
                clean, findings = check_distractors(
                    gate.baseline,
                    post_rows,
                    encoded_gap_ids=list(gate.encoded_gap_ids),
                    gap_anchor_ids=gate.gap_anchor_ids,
                    flaky_anchor_ids=gate.flaky_anchor_ids,
                    intentional_closure_ids=gate.intentional_closure_ids,
                    intrinsic_ids=gate.intrinsic_ids,
                )
                gate_report = {
                    "closure": closure,
                    "distractors_clean": bool(clean),
                    "findings": [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in findings],
                }
                if closure.get("closes_cleanly") and clean:
                    status = "COMMITTED"
                else:
                    snaps.restore(pre_label)
                    status = "GATE_FAILED"

        version_after = ""
        if status == "COMMITTED":
            post_label = f"post-encode:{proposal_id}"
            snaps.capture(post_label)
            version_after = post_label
        else:
            # restored: live content equals pre snapshot — assert, don't assume
            live = extract_manifest(db_path)
            pre = snaps.manifest(pre_label)
            if pre and (live["concepts"].keys() != pre["concepts"].keys()):
                gate_report["restore_warning"] = "post-restore manifest mismatch"

        if status == "COMMITTED":
            try:
                subject_ids, commit_payload = _commit_subjects(prop)
                _emit(
                    store_path, required=True,
                    type=event_types.GRAPH_COMMITTED, proposal_id=proposal_id,
                    gap_id=rec["target_gap_id"],
                    graph_version_before=version_before, graph_version_after=version_after,
                    actor=actor,
                    authority_type=authority,
                    causation_event_id=proposal_cause,
                    subject_node_ids=subject_ids,
                    payload=commit_payload,
                )
            except Exception as exc:
                # The graph and sidecar cannot share one transaction. Preserve
                # the stronger invariant—no unrecorded graph mutation—by
                # compensating to the pre-encode snapshot.
                snaps.restore(pre_label)
                status = "ENCODE_FAILED"
                version_after = ""
                gate_report["event_append_error"] = f"{type(exc).__name__}: {exc}"
        store.update_proposal(
            proposal_id,
            status=status,
            primary_source=primary_source,
            authority=authority,
            gate_report_json=json.dumps(gate_report),
            graph_version_before=version_before,
            graph_version_after=version_after,
            decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return {"proposal_id": proposal_id, "status": status, "gate_report": gate_report,
                "grain": grain_rep,
                "graph_version_before": version_before, "graph_version_after": version_after}
    finally:
        store.close()


def new_proposal_id() -> str:
    return f"prop_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
def attempt_green_auto_commit(
    db_path: Path | str,
    store_path: Path | str,
    proposal_id: str,
    *,
    gate: GateSpec | None = None,
    embedder: Callable[[str], list[float]] | None = None,
    correction_oracle_factory: Callable[..., Any] | None = None,
    correction_probe_cap: int = COMPLETE_PROBE_CAP,
) -> dict[str, Any]:
    """Commit a queued proposal through the operator confirm path.

    The caller must close any live GraphSession first. Mechanical refusals
    — grain, convention, red battery, cardinal correction — are returned as
    ``confirm_proposal`` returned them. The proposal is not rewritten into
    a quieter status.
    """
    return confirm_proposal(
        db_path,
        store_path,
        proposal_id,
        gate=gate,
        embedder=embedder,
        authority="gate",
        actor="gate:auto-encode",
        correction_oracle_factory=correction_oracle_factory,
        correction_probe_cap=correction_probe_cap,
    )
