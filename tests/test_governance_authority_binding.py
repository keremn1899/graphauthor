"""Authority binding must not require a construction-time text convention.

`_fold_governance_adjudications` (640e0a7) binds a GOVERNED verdict to policy
nodes actually present in the packet — the right idea, and it closed a
deterministic presupposition leak on the prose corpus.

But a node only becomes citable when its `text_content` starts with
`ADJUDICATES:` / `GOVERNING:`, or it carries a `governing` flag. That is a
convention emitted by the new construction workspace. Measured across the
corpora on disk:

    prose-workspace       9 of 17 nodes citable
    tesco                 0 of 28
    hexagonal_governance  0 of 25
    nist_ssdf             0 of 66

On a corpus without the convention `by_ref` is empty, every adjudication is
dropped, and the fold takes the else-branch: **UNGOVERNED, deterministically,
for every governed question.** Measured: Tesco `M_T_G1` went from 30/30 GOVERNED
across three full runs to 0/6, and `M_T_ADJ1` from ~7/10 to 0/10 — with the
prose answer still correctly saying the return *is* governed.

That is silent permission, applied to every graph not built by the current
constructor, which is the exact failure the change was made to prevent.

The convention is a legitimate strengthening where it exists. It cannot be a
precondition for a policy node to count as authority at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from battalion import (  # noqa: E402
    _fold_governance_adjudications,
    _payload_node_records_for_governance,
)

#: A Tesco-shaped policy node: real markdown, no construction prefix.
_LEGACY_NODES = [
    {
        "id": "t01_base_change_of_mind",
        "label": "T01 — Standard change-of-mind window",
        "text_content": (
            "# T01 Standard change-of-mind window\n\n"
            "If you change your mind, you can return the product with your "
            "proof of purchase within 30 days."
        ),
    }
]

#: The same node as the current constructor would emit it.
_MARKED_NODES = [
    {
        "id": "rc_1_review_rule",
        "label": "Standard Release Review Rule",
        "text_content": (
            "ADJUDICATES: Every production release MUST receive approval from "
            "two reviewers who did not author the change."
        ),
    }
]


def _governance(policy_id: str) -> dict:
    return {
        "governance_verdict": "GOVERNED",
        "ungoverned_predicate": "",
        "decision_predicate": "change-of-mind returnability of general merchandise",
        "adjudications": [{"policy_id": policy_id, "conformance_ruling": "CONFORMS"}],
    }


def test_a_marked_policy_node_binds():
    """Guard the guard — if this ever fails the test below proves nothing."""
    out, invalid = _fold_governance_adjudications(
        _governance("rc_1_review_rule"), _MARKED_NODES)
    assert out["governance_verdict"] == "GOVERNED", out
    assert not invalid


def test_paged_structured_authority_survives_the_battalion_projection():
    records = _payload_node_records_for_governance(
        {
            "new_rule": {
                "label": "current:new-rule",
                "text_content": "The operation must remain synchronous.",
                "claim_kind": "governing",
                "claim_kind_source": "declared",
            }
        }
    )

    out, invalid = _fold_governance_adjudications(
        {
            "governance_verdict": "GOVERNED",
            "adjudications": [
                {"policy_id": "new_rule", "conformance_ruling": "VIOLATES"}
            ],
        },
        records,
    )

    assert out["governance_verdict"] == "GOVERNED"
    assert out["conformance_ruling"] == "VIOLATES"
    assert out["authority_binding"] == "marked"
    assert invalid == []


def test_an_unmarked_policy_node_still_binds():
    """A corpus without the ADJUDICATES convention must not lose its authority.

    Three of the four graphs on disk have zero marked nodes. If citing one of
    their policy nodes cannot produce GOVERNED, every governed question on those
    corpora returns UNGOVERNED — silent permission by construction convention.
    """
    out, invalid = _fold_governance_adjudications(
        _governance("t01_base_change_of_mind"), _LEGACY_NODES)
    assert out["governance_verdict"] == "GOVERNED", (
        "a real retrieved policy node was rejected as authority because its "
        f"text lacks an ADJUDICATES: prefix -> {out}, invalid={invalid}")


def test_a_citation_to_a_node_outside_the_packet_never_binds():
    """The strictness that matters is retained: authority must be IN the packet.

    Relaxing the convention must not relax this — a model naming a policy the
    packet does not contain is exactly what the binding exists to refuse.
    """
    out, invalid = _fold_governance_adjudications(
        _governance("low_risk_service_exemption"), _LEGACY_NODES)
    assert out["governance_verdict"] == "UNGOVERNED", out
    assert invalid == ["low_risk_service_exemption"], invalid


def test_a_context_node_is_refused_even_on_an_unmarked_corpus():
    """The two guards have to compose, and this is where they meet.

    Relaxing the marking requirement must not relax the *exclusion*. A corpus
    with no `ADJUDICATES:` nodes at all may still mark what is NOT normative —
    `legacy_deployment_context` says "CONTEXT: A release could historically use
    one approval", a superseded permission. If the unmarked-corpus fallback
    swept that in, the fix for silent permission would grant permission from a
    retired document, which is worse than what it repaired.
    """
    nodes = [
        {
            "id": "legacy_deployment_context",
            "label": "Legacy Deployment Context",
            "text_content": "CONTEXT: A release could historically use one approval.",
        },
        # unmarked policy alongside it, so the corpus genuinely has no marking
        {
            "id": "t01_base_change_of_mind",
            "label": "T01 — Standard change-of-mind window",
            "text_content": "# T01\n\nReturn within 30 days with proof of purchase.",
        },
    ]
    out, invalid = _fold_governance_adjudications(
        _governance("legacy_deployment_context"), nodes)
    assert out["governance_verdict"] == "UNGOVERNED", (
        f"a CONTEXT node was accepted as authority: {out}")
    assert invalid == ["legacy_deployment_context"], invalid

    # …while the unmarked policy node beside it still binds.
    out2, _ = _fold_governance_adjudications(
        _governance("t01_base_change_of_mind"), nodes)
    assert out2["governance_verdict"] == "GOVERNED", out2


def test_the_binding_regime_is_reported():
    """A reader of the verdict should be able to tell which regime produced it —
    the strict one, or the weaker fallback a corpus without marking gets."""
    marked, _ = _fold_governance_adjudications(
        _governance("rc_1_review_rule"), _MARKED_NODES)
    legacy, _ = _fold_governance_adjudications(
        _governance("t01_base_change_of_mind"), _LEGACY_NODES)
    assert marked["authority_binding"] == "marked"
    assert legacy["authority_binding"] == "unmarked_corpus"


# ---------------------------------------------------------------------------
# A marker under a heading is still a marker.
# ---------------------------------------------------------------------------
#
# The NIST SSDF corpus writes its nodes as markdown documents:
#
#     # PW.7.1 · Code Review Scope
#
#     ADJUDICATES: Determine whether code review ... should be used.
#
# `text_content.startswith("ADJUDICATES:")` is False for all 66 of them, so the
# corpus read as UNMARKED and silently took the permissive regime — where every
# retrieved node is citable authority, including the 24 group and practice
# containers that state no obligation at all. The corpus declared its authority
# in 42 places and the engine used none of them.
#
# Every other corpus on disk happens to put the marker on line 1, which is why
# nothing caught this: prose 9/9, tesco 24/24, hexagonal 2/2 identical either
# way. Only NIST moved — 0 → 42.

_SSDF_NODES = [
    {
        "id": "ssdf_pw_7_1",
        "label": "PW.7.1 · Code Review Scope",
        "text_content": (
            "# PW.7.1 · Code Review Scope\n\n"
            "ADJUDICATES: Determine whether code review and/or code analysis "
            "should be used, as defined by the organization.\n\n"
            "## NIST notional implementation examples\n\n"
            "Example 1: Follow the organization's policies for when code "
            "review should be performed."
        ),
    },
    {
        # A practice container: a heading and a restatement of the group's
        # intent. It declares no obligation and must not be citable.
        "id": "ssdf_pw_7",
        "label": "PW.7 · Human-Readable Code Review",
        "text_content": (
            "# PW.7 · Human-Readable Code Review\n\n"
            "Review and/or Analyze Human-Readable Code to Identify "
            "Vulnerabilities and Verify Compliance with Security "
            "Requirements."
        ),
    },
]


def test_a_marker_under_a_heading_still_marks():
    out, _ = _fold_governance_adjudications(
        _governance("ssdf_pw_7_1"), _SSDF_NODES)
    assert out["governance_verdict"] == "GOVERNED", out
    assert out["authority_binding"] == "marked", (
        "42 ADJUDICATES: declarations were invisible because a markdown "
        f"heading preceded them: {out}")


def test_an_unmarked_container_is_not_authority_beside_a_marked_rule():
    """The consequence of the miss, not just the miss itself.

    Reading the corpus as unmarked does not merely lose precision — it admits
    the practice/group containers as citable authority, so a verdict can rest
    on a node that states no obligation.
    """
    out, invalid = _fold_governance_adjudications(
        _governance("ssdf_pw_7"), _SSDF_NODES)
    assert out["governance_verdict"] == "UNGOVERNED", (
        f"a practice container was cited as authority: {out}")
    assert invalid == ["ssdf_pw_7"], invalid


def test_a_marker_mid_sentence_confers_nothing():
    """Line-anchoring is the loosening; it is not a substring search.

    Prose that merely mentions the convention must never become authority, or
    the marker means nothing at all.
    """
    nodes = [
        {
            "id": "style_note",
            "label": "Authoring note",
            "text_content": (
                "# Authoring note\n\n"
                "Rule nodes should begin their body with ADJUDICATES: followed "
                "by the obligation."
            ),
        },
    ]
    out, invalid = _fold_governance_adjudications(_governance("style_note"), nodes)
    assert out["authority_binding"] == "unmarked_corpus", out
    # Unmarked regime, so it is citable — but as an ordinary retrieved node,
    # never as a declared rule. The distinction the regime flag exists to carry.
    assert invalid == [], invalid


def test_the_binding_regime_reaches_a_reader():
    """The flag is only worth computing if it leaves the function.

    `_fold_governance_adjudications` sets `authority_binding` under a comment
    saying a reader of the verdict should be able to tell which regime produced
    it. Battalion then copied `governance_verdict`, `decision_predicate`,
    `unsupported_presuppositions`, `adjudications` and `conformance_ruling` onto
    the confirmation — and not this one. It was computed on every governed query
    and observable by nobody, which is indistinguishable from not computing it.
    """
    import inspect

    import battalion

    src = inspect.getsource(battalion.battalion_synthesize)
    assert 'new_confirmation["authority_binding"]' in src, (
        "authority_binding is folded but never surfaced on the confirmation")


# ---------------------------------------------------------------------------
# Citation grain repair.
# ---------------------------------------------------------------------------
#
# Marking the corpus correctly created a NEW silent permission, which is worth
# stating plainly: the line-anchored fix above took NIST from 0 to 42 marked
# nodes, and the model cites the *practice* ("PW.7 · Human-Readable Code
# Review") while only the *tasks* beneath it carry ADJUDICATES:. The citation
# was dropped and the fold returned UNGOVERNED for "we merge pull requests and
# nobody reads the diff" — with PW.7.1 and PW.7.2 sitting in the same packet.
#
# That is a disagreement about grain, not about authority, and the two must not
# have the same consequence.

_SSDF_EDGES = [
    {"source_id": "ssdf_pw_7", "target_id": "ssdf_pw_7_1", "edge_type": "CONTAINS"},
    {"source_id": "ssdf_pw_7", "target_id": "ssdf_pw_7_2", "edge_type": "CONTAINS"},
]

_SSDF_GRAIN_NODES = _SSDF_NODES + [
    {
        "id": "ssdf_pw_7_2",
        "label": "PW.7.2 · Code Review Execution",
        "text_content": (
            "# PW.7.2 · Code Review Execution\n\n"
            "ADJUDICATES: Perform the code review and/or code analysis based on "
            "the organization's secure coding standards."
        ),
    },
]


def test_a_citation_at_the_wrong_grain_binds_to_the_rules_beneath_it():
    out, invalid = _fold_governance_adjudications(
        _governance("ssdf_pw_7"), _SSDF_GRAIN_NODES, _SSDF_EDGES)
    assert out["governance_verdict"] == "GOVERNED", (
        f"a container citation was dropped while its marked rules were in the "
        f"same packet: {out}")
    cited = {a["policy_id"] for a in out["adjudications"]}
    assert cited == {"ssdf_pw_7_1", "ssdf_pw_7_2"}, cited
    assert invalid == [], invalid
    assert out["citation_grain_repaired"] == ["ssdf_pw_7"], out


def test_repair_binds_to_marked_rules_and_never_to_the_container():
    """The repair must not become a way to launder an unmarked node into
    authority. The resulting policy_id is always a marked rule."""
    out, _ = _fold_governance_adjudications(
        _governance("ssdf_pw_7"), _SSDF_GRAIN_NODES, _SSDF_EDGES)
    assert "ssdf_pw_7" not in {a["policy_id"] for a in out["adjudications"]}


def test_a_citation_to_something_absent_from_the_packet_is_still_rejected():
    """The anti-hallucination rule is untouched: repair needs the cited node to
    be IN the packet. A name that is simply not there stays invalid."""
    out, invalid = _fold_governance_adjudications(
        _governance("ssdf_rv_9_9"), _SSDF_GRAIN_NODES, _SSDF_EDGES)
    assert out["governance_verdict"] == "UNGOVERNED", out
    assert invalid == ["ssdf_rv_9_9"], invalid


def test_a_container_with_no_marked_rules_in_the_packet_is_not_repaired():
    """Repair is bounded by the packet, not by the graph. If the marked rules
    were not retrieved, there is nothing to bind to and the honest answer is
    still that no authority was cited."""
    packet = [
        # the cited container …
        next(n for n in _SSDF_GRAIN_NODES if n["id"] == "ssdf_pw_7"),
        # … and an unrelated marked rule, so the corpus still reads as marked
        # and we are testing the repair rather than the unmarked fallback.
        {
            "id": "ssdf_rv_1_3",
            "label": "RV.1.3 · Vulnerability Disclosure Policy",
            "text_content": (
                "# RV.1.3 · Vulnerability Disclosure Policy\n\n"
                "ADJUDICATES: Have a policy that addresses vulnerability "
                "disclosure and remediation."
            ),
        },
    ]
    out, invalid = _fold_governance_adjudications(
        _governance("ssdf_pw_7"),
        packet,
        # The CONTAINS edge exists, but PW.7.1 was never retrieved.
        [{"source_id": "ssdf_pw_7", "target_id": "ssdf_pw_7_1",
          "edge_type": "CONTAINS"}],
    )
    assert out["authority_binding"] == "marked", out
    assert out["governance_verdict"] == "UNGOVERNED", out
    assert invalid == ["ssdf_pw_7"], invalid


def test_repair_follows_contains_and_not_other_edge_types():
    """A NEARTO neighbour is not a rule 'beneath' anything. Following any edge
    type would let embedding proximity confer authority."""
    out, invalid = _fold_governance_adjudications(
        _governance("ssdf_pw_7"),
        _SSDF_GRAIN_NODES,
        [{"source_id": "ssdf_pw_7", "target_id": "ssdf_pw_7_1",
          "edge_type": "NEARTO"}],
    )
    assert out["governance_verdict"] == "UNGOVERNED", out
    assert invalid == ["ssdf_pw_7"], invalid


# ---------------------------------------------------------------------------
# `ungoverned_because` — the qualifier, not a fourth verdict value.
# ---------------------------------------------------------------------------
#
# UNGOVERNED is overloaded. "No rule covers your case" is a finding about a
# rulebook; "this graph states no rules at all" is a finding about the graph.
# Ask a governance question of a Wikipedia graph today and you get the first,
# which is false — it implies a rulebook that happens not to reach you.
#
# A qualifier rather than a new enum value, so `governance_verdict` keeps its
# two values and no existing consumer breaks.

from battalion import (  # noqa: E402
    UNGOVERNED_NOT_A_RULEBOOK,
    UNGOVERNED_NO_RULE,
    UNGOVERNED_UNCLASSIFIED,
)

_NO_RULES_CITED = [
    {"id": "n1", "label": "Rivendell", "text_content": "# Rivendell\n\nAn elven refuge."},
]


def test_an_absence_in_a_rulebook_says_no_rule_covers_it():
    out, _ = _fold_governance_adjudications(
        _governance("nope"), _MARKED_NODES, None, {"normative_character": "normative"})
    assert out["governance_verdict"] == "UNGOVERNED"
    assert out["ungoverned_because"] == UNGOVERNED_NO_RULE


def test_an_absence_of_a_rulebook_says_so():
    out, _ = _fold_governance_adjudications(
        _governance("nope"), _NO_RULES_CITED, None,
        {"normative_character": "informational"})
    assert out["ungoverned_because"] == UNGOVERNED_NOT_A_RULEBOOK, (
        "a graph that declares itself rule-free still reported an absence as "
        "though it were a rulebook that failed to cover the case")


def test_an_unclassified_graph_admits_it_rather_than_guessing():
    """The honest middle. Most graphs on disk are here, and reporting either
    strong answer would be a claim the evidence does not support."""
    out, _ = _fold_governance_adjudications(
        _governance("nope"), _NO_RULES_CITED, None,
        {"normative_character": "unclassified"})
    assert out["ungoverned_because"] == UNGOVERNED_UNCLASSIFIED


def test_a_declared_rule_in_the_packet_beats_an_unclassified_profile():
    """Evidence beats the aggregate. If a retrieved node was declared a rule,
    this graph demonstrably states rules whatever its overall profile says."""
    out, _ = _fold_governance_adjudications(
        _governance("nope"), _MARKED_NODES, None,
        {"normative_character": "unclassified"})
    assert out["ungoverned_because"] == UNGOVERNED_NO_RULE


def test_no_normative_content_is_never_claimed_from_the_lexical_prior():
    """The strong claim needs a declaration.

    `normative.profile` never emits `informational` on the prior alone, so a
    corpus full of unmarked obligations — policy-operations was exactly this —
    can never be reported as stating no rules.
    """
    import normative

    rulebook_the_prior_misreads = [
        {"text_content": "P02. For a standard return, the customer pays "
                         "return shipping."}
    ]
    character = normative.profile(rulebook_the_prior_misreads).character
    assert character != "informational"
    out, _ = _fold_governance_adjudications(
        _governance("nope"), _NO_RULES_CITED, None,
        {"normative_character": character})
    assert out["ungoverned_because"] != UNGOVERNED_NOT_A_RULEBOOK


def test_the_qualifier_does_not_appear_on_a_governed_verdict():
    out, _ = _fold_governance_adjudications(
        _governance("rc_1_review_rule"), _MARKED_NODES, None,
        {"normative_character": "normative"})
    assert out["governance_verdict"] == "GOVERNED"
    assert "ungoverned_because" not in out


def test_the_verdict_enum_is_unchanged():
    """The compatibility promise: a qualifier, not a fourth value."""
    for character in ("normative", "informational", "unclassified", ""):
        out, _ = _fold_governance_adjudications(
            _governance("nope"), _NO_RULES_CITED, None,
            {"normative_character": character})
        assert out["governance_verdict"] in ("GOVERNED", "UNGOVERNED"), out


# ------------------------------------------------- citation spelling, not authority


def test_a_policy_cited_by_its_own_name_resolves_to_the_retrieved_node():
    """Punctuation must not produce silent permission.

    Construction labels the node `DependencyDirectionRule (structural)` under id
    `dependency_direction_rule`; the model cites the policy the way the node
    states it, `DependencyDirectionRule`. Exact-string lookup matched neither,
    so a correct adjudication over a RETRIEVED rule was dropped and the fold
    returned UNGOVERNED — while the prose in the very same response said "is
    governed by ... Gaps: None".

    Measured on the hexagonal fixture: both governed anchors 0/3 before, 3/3
    after, moats unchanged at UNGOVERNED 3/3.
    """

    from battalion import _fold_governance_adjudications as fold

    nodes = [{"id": "dependency_direction_rule",
              "label": "DependencyDirectionRule (structural)",
              "text_content": "ADJUDICATES: dependencies point inward"}]
    out, _ = fold(
        {"adjudications": [{"policy_id": "DependencyDirectionRule",
                            "conformance_ruling": "CONFORMS"}],
         "decision_predicate": "dependency direction"},
        nodes,
    )
    assert out["governance_verdict"] == "GOVERNED"
    assert out["adjudications"] == [
        {"policy_id": "dependency_direction_rule", "conformance_ruling": "CONFORMS"}
    ], "the verdict must bind to the real node id, not the cited spelling"


def test_an_ambiguous_citation_confers_nothing():
    """Relaxed matching must refuse, not guess.

    If a squashed citation reaches two different nodes, choosing one would be
    inventing which policy was cited — and this path grants authority.
    """

    from battalion import _fold_governance_adjudications as fold

    out, _ = fold(
        {"adjudications": [{"policy_id": "thing", "conformance_ruling": "CONFORMS"}],
         "decision_predicate": "p"},
        [{"id": "rule_a", "label": "Thing (x)", "text_content": ""},
         {"id": "rule_b", "label": "T-h-i-n-g", "text_content": ""}],
    )
    assert out["governance_verdict"] == "UNGOVERNED"
    assert out["adjudications"] == []


def test_a_citation_absent_from_the_packet_is_still_refused():
    """The anti-hallucination rule is unchanged: relaxed spelling widens how a
    RETRIEVED node may be named, never what may be cited."""

    from battalion import _fold_governance_adjudications as fold

    out, _ = fold(
        {"adjudications": [{"policy_id": "NotInPacket",
                            "conformance_ruling": "CONFORMS"}],
         "decision_predicate": "p"},
        [{"id": "dependency_direction_rule",
          "label": "DependencyDirectionRule (structural)", "text_content": ""}],
    )
    assert out["governance_verdict"] == "UNGOVERNED"
