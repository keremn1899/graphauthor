"""A truncated chain must report itself as a gap.

Pipeline B already detects the case to decide the verdict — it walks the chain,
the next hop returns nothing, and `_compute_verdict` returns EXHAUSTED with the
basis "intermediate entity found but terminal property absent". That detection
was never turned into a gap, so `chain_truncated` could only ever arise by
*correcting* a `coverage_shallow` the Company LLM had already guessed at, and a
chain question producing no LLM gap produced none at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interaction.gap_types import translate  # noqa: E402
from pipeline_b import _chain_truncation_gap  # noqa: E402

_CHAIN = {"question_form": "chain", "source_ids": ["checkout"],
          "target_ids": ["db_user"]}


def test_a_truncated_chain_produces_a_gap():
    gap = _chain_truncation_gap(_CHAIN, True, True)
    assert gap is not None
    assert gap["gap_type"] == "chain_truncated"
    assert gap["specific_node_or_concept"] == "db_user"


def test_it_reaches_the_wire_as_coverage_shallow():
    """The contract vocabulary has no `chain_truncated`; the translation is
    what makes this reportable, and it says 'we reached less than the question
    needed' rather than 'the concept is missing'."""
    assert translate("chain_truncated") == "coverage_shallow"


def test_a_chain_that_completed_produces_nothing():
    assert _chain_truncation_gap(_CHAIN, False, True) is None


def test_a_chain_that_never_started_produces_nothing():
    """Nothing was reached, so nothing was truncated — that is a seeding
    failure, and reporting it as a short chain would misdescribe it."""
    assert _chain_truncation_gap(_CHAIN, True, False) is None


def test_a_non_chain_question_is_untouched():
    assert _chain_truncation_gap(
        {"question_form": "lookup", "source_ids": ["x"]}, True, True) is None
