"""Claim kind, the lexical prior's boundaries, and graph normative character.

The prior is unsound in both directions and the tests that matter are the ones
that pin it OUT of every decision. Each false-positive and false-negative case
below is a real string from a real corpus on disk, not an invented adversary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import normative  # noqa: E402
from normative import (  # noqa: E402
    CLASSIFIED,
    DECLARED,
    LEXICAL,
    classify,
    declared_claim_kind,
    lexical_claim_kind,
    normative_density,
    profile,
)


def _node(text: str = "", **extra) -> dict:
    return {"text_content": text, **extra}


# ---------------------------------------------------------------------------
# The resolution ladder
# ---------------------------------------------------------------------------

def test_the_column_wins_over_the_text_prefix():
    """Once a graph carries the property, the prefix is not consulted.

    The prefix exists because `Concept` had no column. With a column, a node
    whose text still carries a stale prefix must follow the column.
    """
    node = _node("ADJUDICATES: something", claim_kind="contextual",
                 claim_kind_source="classified")
    result = classify(node)
    assert result.kind == normative.CONTEXTUAL
    assert result.source == CLASSIFIED
    assert not result.is_governing


def test_a_stored_kind_with_no_source_is_treated_as_declared():
    """A column written by a constructor that predates the source field still
    represents a deliberate act, not a guess."""
    assert classify(_node("", claim_kind="governing")).source == DECLARED


def test_the_text_prefix_is_the_legacy_path():
    result = classify(_node("# PW.7.1 heading\n\nADJUDICATES: perform review."))
    assert result.kind == normative.GOVERNING
    # A prefix hit used to report plain `declared`, indistinguishable from a
    # column hit. Same ACT of declaration, weaker STORE: prose survives only
    # until something reformats it, so a caller reporting confidence needs to
    # know which answered. It still grants authority — see the next assertion.
    assert result.source == normative.DECLARED_PREFIX
    assert result.grants_authority


def test_the_lexical_prior_is_the_last_resort():
    result = classify(_node("Every production release must be signed by CI."))
    assert result.kind == normative.GOVERNING
    assert result.source == LEXICAL


def test_nothing_at_all_resolves_to_unknown():
    result = classify(_node("Gandalf travelled to Rivendell in the autumn."))
    assert result.kind == normative.UNKNOWN
    assert result.source == normative.NO_SOURCE


def test_an_unrecognised_stored_kind_falls_through_rather_than_being_trusted():
    """A typo in the column must not silently become a claim kind."""
    result = classify(_node("ADJUDICATES: x", claim_kind="govrening"))
    assert result.kind == normative.GOVERNING
    # Fell through to the prefix, and now says so rather than claiming the
    # column answered. `engine.write_nodes` refuses such a value at the write
    # boundary, because the readers disagree about it: this resolves it as
    # governing while `certify._looks_like_rule` reads it as not-a-rule.
    assert result.source == normative.DECLARED_PREFIX


# ---------------------------------------------------------------------------
# The rule the whole module exists to enforce
# ---------------------------------------------------------------------------

def test_a_lexical_hit_never_grants_authority():
    """This is the load-bearing invariant.

    Letting a guess narrow the citable set is how marking NIST correctly
    produced 26 false-UNGOVERNED. A lexical hit may inform a hint and nothing
    else.
    """
    guessed = classify(_node("Every release must be signed."))
    assert guessed.is_governing
    assert not guessed.grants_authority, (
        "a lexical guess was allowed to confer authority")


def test_declared_and_classified_both_grant_authority():
    assert classify(_node("ADJUDICATES: x")).grants_authority
    assert classify(_node("", claim_kind="governing",
                          claim_kind_source="classified")).grants_authority


def test_declared_density_ignores_lexical_hits_entirely():
    nodes = [_node("Every release must be signed by CI.") for _ in range(10)]
    assert normative_density(nodes) == 0.0, (
        "lexical hits leaked into the declared density")


# ---------------------------------------------------------------------------
# False positives — real strings from the Wikipedia graph-theory corpus.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,why", [
    ("Related result is the Robertson-Seymour theorem, implying the existence "
     "of a forbidden minor for every property of graphs.", "term of art"),
    ("Redesigned network strictly based on Moreno (1934), Who Shall Survive.",
     "book title"),
    ("The crossing number is the number of intersections that a drawing of the "
     "graph in the plane must contain.", "mathematical necessity"),
    ("Another class of problems has to do with the extent to which various "
     "generalizations of graphs are determined.", "idiom"),
    ("However, unless the graph is connected, it may not have a unique "
     "2-coloring.", "alethic possibility"),
])
def test_the_prior_fires_on_non_deontic_text(text, why):
    """Documenting the unsoundness rather than pretending it is fixed.

    Deontic, alethic and epistemic modality share a vocabulary. Each of these
    is a real string from a real corpus, and each one fires. That is precisely
    why `grants_authority` is False for the lexical tier and why `profile()`
    bands on declared evidence only — not because the regex is untuned.
    """
    assert lexical_claim_kind(text) == normative.GOVERNING, why
    assert not classify(_node(text)).grants_authority


# ---------------------------------------------------------------------------
# False negatives — real strings from the policy-operations corpus.
# ---------------------------------------------------------------------------

def test_a_real_rulebook_can_read_as_silent_to_the_prior():
    """`policy-operations` is unambiguously a rulebook and a modal-verb screen
    found 1 node in 25. Policy states obligations in the declarative present.

    The consequence is the one that matters: a graph the prior finds nothing in
    must NOT be certified rule-free.
    """
    silent_but_normative = _node(
        "P02 Return Shipping Cost. For a standard return, the customer pays "
        "return shipping. Meridian pays it when the item arrived damaged."
    )
    assert lexical_claim_kind(silent_but_normative["text_content"]) == \
        normative.UNKNOWN
    assert profile([silent_but_normative]).character == "unclassified", (
        "a rulebook the prior cannot read was certified as informational")


# ---------------------------------------------------------------------------
# Graph character
# ---------------------------------------------------------------------------

def test_declared_rules_make_a_graph_normative():
    nodes = [_node("ADJUDICATES: rule.") for _ in range(7)] + \
            [_node("plain descriptive text") for _ in range(3)]
    result = profile(nodes)
    assert result.character == "normative"
    assert result.declared_density == pytest.approx(0.7)


def test_a_few_declared_rules_make_it_mixed():
    nodes = [_node("ADJUDICATES: rule.")] + \
            [_node("plain descriptive text") for _ in range(19)]
    assert profile(nodes).character == "mixed"


def test_informational_requires_declared_non_governing_evidence():
    """Symmetric with `normative`: we claim "not a rulebook" only on a
    declaration, never on the prior's silence."""
    declared_context = [_node("CONTEXT: background note.") for _ in range(5)]
    assert profile(declared_context).character == "informational"


def test_nothing_declared_is_unclassified_not_informational():
    """The honest default, and the one that keeps a false 'informational' off
    a real governance corpus."""
    assert profile([_node("Gandalf rode to Rivendell.")]).character == \
        "unclassified"
    assert profile([_node("Every release must be signed.")]).character == \
        "unclassified"


def test_the_prior_cannot_move_the_character():
    """Identical declared evidence, wildly different prior — same character."""
    quiet = [_node("Gandalf rode to Rivendell.") for _ in range(10)]
    loud = [_node("Every release must be signed and shall be reviewed.")
            for _ in range(10)]
    assert profile(quiet).character == profile(loud).character
    assert profile(quiet).lexical_density != profile(loud).lexical_density


def test_an_empty_graph_is_not_a_rulebook():
    result = profile([])
    assert result.character == "informational"
    assert result.declared_density == 0.0
    assert result.node_count == 0


def test_the_profile_reports_the_prior_even_though_it_decides_nothing():
    """The hint is the actionable part: it says where classification is worth
    spending money."""
    nodes = [_node("Every release must be signed.") for _ in range(4)] + \
            [_node("descriptive") for _ in range(6)]
    payload = profile(nodes).to_dict()
    assert payload["normative_character"] == "unclassified"
    assert payload["normative_density"] == 0.0
    assert payload["normative_density_lexical"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Prefix parsing boundaries
# ---------------------------------------------------------------------------

def test_a_prefix_under_a_markdown_heading_still_counts():
    assert declared_claim_kind("# PW.7.1 Scope\n\nADJUDICATES: do the thing.") \
        == normative.GOVERNING


def test_a_prefix_mid_sentence_confers_nothing():
    text = ("# Authoring note\n\nRule nodes should begin their body with "
            "ADJUDICATES: followed by the obligation.")
    assert declared_claim_kind(text) == normative.UNKNOWN


def test_context_and_navigation_are_declared_non_governing():
    ctx = classify(_node("CONTEXT: a release could historically use one approval."))
    assert ctx.kind == normative.CONTEXTUAL
    assert ctx.grants_authority and not ctx.is_governing
    nav = classify(_node("NAVIGATION: see the returns topic."))
    assert nav.kind == normative.NAVIGATION
