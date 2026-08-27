"""Unified change-set IR (construction/evolution charter §3).

One representation, two materialization modes. `create` is a change-set
against an EMPTY base; `evolve` is a change-set against a live graph_version.
Today's `SSTProposal` (add-only concepts/edges) is exactly an evolve/add
change-set — this module lifts it into the shared shape WITHOUT changing any
behavior: `ChangeSet.from_proposal_encoding(...)` reproduces the current
proposal path bit-for-bit, and the existing gate/commit machinery keeps
consuming `SSTProposal` unchanged. New operation types (replace/remove/
supersede) and the create mode ride this IR in later steps; step 1 only
proves the representation is faithful.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from mcp_server.proposals import ProposalConcept, ProposalEdge, SSTProposal


class Materialization(str, Enum):
    CREATE = "create"   # base = EMPTY → new .lbug
    EVOLVE = "evolve"   # base = live graph_version → snapshot-atomic merge


class OpKind(str, Enum):
    ADD_CONCEPT = "add_concept"
    ADD_EDGE = "add_edge"
    # Reserved for later construction steps (charter §4); not yet gated:
    REPLACE_CONTENT = "replace_content"
    REMOVE_EDGE = "remove_edge"
    REMOVE_CONCEPT = "remove_concept"
    SUPERSEDE_RULE = "supersede_rule"
    DEPRECATE_RULE = "deprecate_rule"


_ADD_ONLY = frozenset({OpKind.ADD_CONCEPT, OpKind.ADD_EDGE})


class ChangeOp(BaseModel):
    kind: OpKind
    concept: ProposalConcept | None = None
    edge: ProposalEdge | None = None
    target_node_id: str = ""       # for replace/remove/supersede
    new_node_id: str = ""          # for supersede
    effective: str = ""            # for supersede/deprecate lifecycle
    payload: dict[str, Any] = Field(default_factory=dict)


class ChangeSet(BaseModel):
    """The unified IR. `base` distinguishes create (EMPTY) from evolve (a live
    graph_version). `operations` are typed; add-only sets are behavior-
    identical to today's proposals."""

    base: str = "EMPTY"                       # "EMPTY" or a graph_version
    materialization: Materialization = Materialization.EVOLVE
    operations: list[ChangeOp] = Field(default_factory=list)
    anchoring: list[str] = Field(default_factory=list)   # existing node ids edges attach to
    target_gaps: list[str] = Field(default_factory=list)

    def is_add_only(self) -> bool:
        return all(op.kind in _ADD_ONLY for op in self.operations)

    def is_empty(self) -> bool:
        return not self.operations

    # --- faithful bridge to the shipped proposal path -----------------------

    @classmethod
    def from_proposal_encoding(cls, encoding: dict, *, base: str = "EMPTY",
                               target_gaps: list[str] | None = None) -> "ChangeSet":
        """Lift a proposal encoding {concepts, edges} into an add-only
        change-set. base defaults EMPTY (create); pass a graph_version for
        evolve. This is the ONLY constructor today's callers need."""
        ops: list[ChangeOp] = []
        for c in (encoding.get("concepts") or []):
            ops.append(ChangeOp(kind=OpKind.ADD_CONCEPT, concept=ProposalConcept.model_validate(c)))
        for e in (encoding.get("edges") or []):
            ops.append(ChangeOp(kind=OpKind.ADD_EDGE, edge=ProposalEdge.model_validate(e)))
        mat = Materialization.CREATE if base == "EMPTY" else Materialization.EVOLVE
        return cls(base=base, materialization=mat, operations=ops,
                   target_gaps=target_gaps or [])

    def to_proposal(self) -> SSTProposal:
        """Project an add-only change-set back to the SSTProposal the existing
        validator/gate/commit machinery consumes. Faithful inverse of
        from_proposal_encoding for add-only sets; raises if a non-add op is
        present (those need the later gate profiles, not this path)."""
        if not self.is_add_only():
            raise ValueError("to_proposal() is valid only for add-only change-sets; "
                             "replace/remove/supersede require the edit gate (charter §5)")
        return SSTProposal(
            concepts=[op.concept for op in self.operations
                      if op.kind == OpKind.ADD_CONCEPT and op.concept is not None],
            edges=[op.edge for op in self.operations
                   if op.kind == OpKind.ADD_EDGE and op.edge is not None],
        )

    def to_encoding(self) -> dict:
        """Round-trip back to the proposal dict form.

        `corrections` and `edge_retypes` are always empty here: a ChangeSet
        reaching this method is add-only by `to_proposal`'s contract, and both
        travel through the proposal encoding directly rather than as change
        operations. The keys are still emitted so this stays equal to
        `SSTProposal.model_dump()`, which is what gets stored as
        `encoding_json` — omitting one breaks the stored-projection round trip,
        which is how adding `corrections` failed the first time."""
        p = self.to_proposal()
        return {"concepts": [c.model_dump() for c in p.concepts],
                "edges": [e.model_dump() for e in p.edges],
                "corrections": [c.model_dump() for c in p.corrections],
                "edge_retypes": [r.model_dump() for r in p.edge_retypes]}
