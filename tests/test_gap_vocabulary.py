"""The engine's gap vocabulary and the contract's must agree.

Gaps are a primary product output — an operator acts on them, and
`propose(target_gap_id=…)` binds to them — so a gap type the contract advertises
and the engine cannot emit is a promise with no implementation.

Two were exactly that. `vocabulary_mismatch` and `schema_gap` were declared in
`contract.GapType`, consumed downstream, and absent from `models.GapEntry`, so
pydantic rejected any attempt to produce one and the translation map's identity
entries for them were dead. This is the third instance of the same shape found
in this codebase — after `system.fault` (consumer built, producer missing) and
`gate.completed:gate_failed` (a vocabulary the ledger watched for and nothing
emitted) — which is why it gets a test rather than a fix.
"""

from __future__ import annotations

import typing


def _literal_values(annotation) -> set[str]:
    return set(typing.get_args(annotation))


def test_both_literals_derive_from_the_single_source():
    """The structural check. Two hand-maintained Literals plus a hand-maintained
    map is the arrangement that let the contract advertise types the engine
    could not emit; deriving both removes the second list."""
    import typing

    from contract import GapType
    from interaction.gap_types import CONTRACT_GAP_TYPES, INTERNAL_GAP_TYPES
    from models import GapEntry

    assert set(typing.get_args(GapType)) == set(CONTRACT_GAP_TYPES)
    assert set(_literal_values(
        GapEntry.model_fields["gap_type"].annotation)) == set(INTERNAL_GAP_TYPES)


def test_every_contract_gap_type_is_emittable_by_the_engine():
    """A type the contract promises must be one the engine can actually put in
    a GapEntry, or it is unreachable by construction."""
    from contract import GapType
    from models import GapEntry

    contract_types = _literal_values(GapType)
    internal_types = _literal_values(GapEntry.model_fields["gap_type"].annotation)

    unreachable = sorted(contract_types - internal_types)
    assert not unreachable, (
        f"the contract advertises gap types the engine cannot emit: {unreachable}")


def test_every_internal_gap_type_reaches_the_contract():
    """And nothing internal may vanish silently — it must translate to
    something, even if that something is broader."""
    from interaction.gap_types import INTERNAL_GAP_TYPES, TRANSLATION

    internal_types = set(INTERNAL_GAP_TYPES)
    untranslated = sorted(internal_types - set(TRANSLATION))
    assert not untranslated, (
        f"these internal gap types have no contract translation and would "
        f"silently become 'missing_concept': {untranslated}")


def test_the_translation_map_has_no_dead_entries():
    """A map entry for a type nothing can produce reads as support that does
    not exist."""
    from interaction.gap_types import INTERNAL_GAP_TYPES, TRANSLATION

    dead = sorted(set(TRANSLATION) - set(INTERNAL_GAP_TYPES))
    assert not dead, f"translation entries for unproducible types: {dead}"


def test_broadening_translations_are_deliberate():
    """Two internal types intentionally collapse to `coverage_shallow`. Pinned
    so the loss is a decision rather than an accident."""
    from interaction.gap_types import TRANSLATION

    assert TRANSLATION["chain_truncated"] == "coverage_shallow"
    assert TRANSLATION["metanode_not_crossed"] == "coverage_shallow"


def test_unknown_types_fall_back_visibly_to_missing_concept():
    from contract import _translate_gap_type

    assert _translate_gap_type("not_a_real_type") == "missing_concept"
    assert _translate_gap_type("") == "missing_concept"


def _emitted_gap_types() -> set[str]:
    """Every gap_type literal the production code actually emits."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    skip = ("tests/", "examples/", "archive/", "scratch/", "scripts/", "demo/",
            "build/", "dist/")  # setuptools' copy of the tree
    found: set[str] = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(skip):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found |= set(re.findall(r'"gap_type":\s*"([a-z_]+)"', text))
        found |= set(re.findall(r'gap_type="([a-z_]+)"', text))
    return found


def test_every_emitted_gap_type_has_a_translation():
    """A gap type the engine emits and the map does not know is SILENTLY
    downgraded to `missing_concept` — so the engine types the gap correctly and
    the contract reports it generically.

    This is the inverse of how `typed_gap` 6/9 reads at face value: the failure
    was in the translation, not in the typing. `missing_source_coverage`,
    `structural_absence` and `requires_content_arithmetic` were all being
    flattened this way.
    """
    from interaction.gap_types import TRANSLATION

    # `genuine_gap` belongs to the materiality disposition vocabulary
    # (genuine_gap / retrieval_miss / local_choice / arch_material /
    # insufficient), not to gap typing. It is not a GapEntry type.
    materiality_categories = {"genuine_gap"}

    untranslated = sorted(
        _emitted_gap_types() - set(TRANSLATION) - materiality_categories
    )
    assert not untranslated, (
        f"these gap types are emitted and silently become 'missing_concept': "
        f"{untranslated}")
