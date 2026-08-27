"""The gap vocabulary, defined once — internal, contract, and the map between.

The same shape that produced the event-type defects: `models.GapEntry.gap_type`
and `contract.GapType` were two hand-maintained Literals with a hand-maintained
dict between them, and nothing made the three agree. What that cost:

- `vocabulary_mismatch` and `schema_gap` were declared in the contract and
  absent from the internal Literal, so pydantic rejected either and no tier
  could produce one. The map's entries for them were dead code, and
  `contract.py` *consumed* `vocabulary_mismatch` that nothing emitted.

  `schema_gap` earned its place — `contract.py` synthesises it on `ILL_POSED`.
  `vocabulary_mismatch` did not, and is now **removed**. Making it *emittable*
  did not make it *produced*: the honest derivation ("seed resolution found
  nothing lexically and fell back to semantic search") was measured on the three
  failing cases and refuted — none of them used `vector_search` at all, so the
  signal the derivation needs does not exist. A heuristic over finished gaps was
  drafted and discarded for trading one wrong label for another.

  Advertising a type nothing emits is the same defect as a consumer with no
  producer, and everywhere else in this codebase that was closed by making the
  two agree. Here agreement means removal. Re-add it with its producer, not
  before — the distinction is real (add an alias, not a node) and worth having
  the day something can derive it.
- `missing_source_coverage`, `structural_absence` and
  `requires_content_arithmetic` were emitted by `pipeline_b` and known to
  neither list, so each defaulted to `missing_concept`. The engine was typing
  gaps MORE specifically than the contract reported — the opposite of how
  `typed_gap` 6/9 reads at face value.

Both Literals are now *derived* from the tuples here, so there is no second
list to drift. Adding a gap type is one edit; forgetting to map it is a type
error rather than a silent downgrade to `missing_concept`.

Gaps are a primary product output — an operator acts on them and
`propose(target_gap_id=…)` binds to them — so a gap the engine typed precisely
and the contract reported vaguely is lost product value, not cosmetics.
"""

from __future__ import annotations

# --------------------------------------------------------------- contract
#
# What an agent may receive. Closed, and narrower than the internal set on
# purpose: consumers should not have to learn every distinction the pipeline
# draws internally.

CONTRACT_GAP_TYPES: tuple[str, ...] = (
    "missing_concept",
    "missing_relationship",
    "coverage_shallow",
    "schema_gap",
)

# --------------------------------------------------------------- internal
#
# What a tier may emit. Every member must appear in TRANSLATION below.

INTERNAL_GAP_TYPES: tuple[str, ...] = (
    "missing_concept",
    "missing_relationship",
    "metanode_not_crossed",
    "coverage_shallow",
    "chain_truncated",
    "schema_gap",
    # Emitted by pipeline_b as raw dicts, bypassing validation entirely until
    # they were declared here.
    "missing_source_coverage",
    "structural_absence",
    "requires_content_arithmetic",
    # Battalion's governance gap.
    "ungoverned_predicate",
)

# ------------------------------------------------------------ translation
#
# Internal → contract. Mapped from what each emission site SAYS it means, not
# from what its name suggests.

TRANSLATION: dict[str, str] = {
    "missing_concept": "missing_concept",
    "missing_relationship": "missing_relationship",
    "coverage_shallow": "coverage_shallow",
    "schema_gap": "schema_gap",
    # Deliberate broadening: both are shapes of "we reached less than the
    # question needed".
    "chain_truncated": "coverage_shallow",
    "metanode_not_crossed": "coverage_shallow",
    # pipeline_b: "no edges of type X found originating at <src>" — the node
    # exists, the relation does not.
    "missing_source_coverage": "missing_relationship",
    # pipeline_b: "requires edge types that do not exist in the graph" — the
    # schema cannot express the question.
    "structural_absence": "schema_gap",
    # pipeline_b: needs arithmetic over content the graph holds but cannot
    # compute over.
    "requires_content_arithmetic": "schema_gap",
    # battalion: no policy governs the predicate. `coverage_shallow` was tried
    # and is wrong on meaning — shallow is "found some, not enough", and an
    # ungoverned predicate is absent, not shallow.
    "ungoverned_predicate": "missing_concept",
}

#: Where an unknown type lands. Deliberately the vaguest member: a gap we
#: cannot classify must not masquerade as a precise one.
FALLBACK_GAP_TYPE = "missing_concept"


def translate(raw: str) -> str:
    """Internal gap type → contract gap type, defaulting visibly."""
    return TRANSLATION.get((raw or "").strip().lower(), FALLBACK_GAP_TYPE)
