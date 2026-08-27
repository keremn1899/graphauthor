"""Is a node a rule, and is this graph a rulebook?

Two questions that sound alike. Neither is answerable from vocabulary alone,
which is the finding this module is built around rather than a caveat on it.

## The property already existed; the graph had nowhere to put it

`construction/workspace.py` has classified every node it authors as
`governing | contextual | interpretation | navigation` all along — and then
serialised the answer into an "ADJUDICATES:" text prefix, because `Concept`
carried no column for it. The prefix was never a convention we chose to
impose; it was a workaround for a missing field, and it is why authority
binding only ever worked on graphs our own pipeline built. `claim_kind` and
`claim_kind_source` are that field. The prefix survives as a legacy import
path.

## Why the lexical prior never decides anything

A regex over deontic vocabulary looks like it should work. Measured across the
eleven corpora on disk, it is unsound in both directions, and both directions
have distinct structural causes:

*It misses obligations.* NIST states them as imperatives with no modal at all
("Identify and document all security requirements", "Obtain upper management
commitment") — 25 of 42 missed. Detecting sentence-initial verbs recovers them
and then fires on "Example 1: Follow the organization's policies…" inside every
node, dropping precision to 0.70. Policy prose is worse: `policy-operations`
is unambiguously a rulebook ("may **be returned** for a full refund", "the
customer **pays** return shipping", "they are **non-returnable**") and a
modal-verb screen found 1 node in 25, because policy routinely states
obligations in the declarative present.

*It invents them.* On the Wikipedia graph-theory corpus it fires on a
**forbidden** minor (a term of art), a book titled *Who Shall Survive*, "must
contain" (mathematical necessity), "has to do with" (an idiom), and "may not
have a unique 2-colouring" (possibility). Deontic, alethic and epistemic
modality share their vocabulary and no regex separates them.

Every tightening that fixed one corpus broke another. So the prior is reported
as a hint — useful for deciding *where classification is worth running* — and
is never allowed to decide either a node's authority or a graph's character.
`grants_authority` is False for it, and `profile()` bands on declared evidence
only.

That rule is not fastidiousness. Letting a guess flip a corpus into the strict
binding regime is exactly how marking NIST *correctly* produced 26
false-UNGOVERNED in one afternoon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

#: What a node's text does. Vocabulary shared with `construction/workspace.py`,
#: which has classified nodes this way all along and then threw the answer into
#: a text prefix because `Concept` had nowhere to put it.
GOVERNING = "governing"
CONTEXTUAL = "contextual"
INTERPRETATION = "interpretation"
NAVIGATION = "navigation"
UNKNOWN = ""

CLAIM_KINDS = (GOVERNING, CONTEXTUAL, INTERPRETATION, NAVIGATION)

#: Where a classification came from. Only a `declared*` source may narrow the
#: citable set.
#:
#: `declared` was one value covering two very different situations: the graph
#: carries a `claim_kind` column, or the graph carries an "ADJUDICATES:" prefix
#: in its prose and we parsed it. The second survives only until something
#: reformats the payload, and a caller could not tell which it had. They are
#: separate values now; `DECLARED` remains as the column case so existing
#: comparisons keep meaning what they meant.
DECLARED = "declared"
DECLARED_PREFIX = "declared_prefix"
CLASSIFIED = "classified"
LEXICAL = "lexical"
NO_SOURCE = ""

#: Text prefixes the construction workspace emits. Anchored to the start of a
#: LINE, not of the text: NIST writes a markdown heading first, so anchoring to
#: the text missed all 42 of its declarations.
_PREFIX_KIND = {
    "ADJUDICATES": GOVERNING,
    "GOVERNING": GOVERNING,
    "CONTEXT": CONTEXTUAL,
    "CONTEXTUAL": CONTEXTUAL,
    "INTERPRETATION": INTERPRETATION,
    "NAVIGATION": NAVIGATION,
}

_OBLIGATION = re.compile(
    r"\b(must|shall|are required to|is required to|required to|"
    r"has to|have to|obliged to|mandator(?:y|ily))\b", re.I)
_PROHIBITION = re.compile(
    r"\b(must not|shall not|may not|is not permitted|are not permitted|"
    r"prohibited|forbidden)\b", re.I)
_PERMISSION = re.compile(
    r"\b(is permitted|are permitted|is allowed|are allowed|is entitled|"
    r"are entitled|may return|can return|may claim|may request|"
    r"may be (?:returned|refunded|cancelled|canceled|exchanged|disputed)|"
    r"non-?returnable|non-?refundable|final sale)\b", re.I)


@lru_cache(maxsize=1)
def _prefix_pattern() -> "re.Pattern[str]":
    names = "|".join(re.escape(p) for p in _PREFIX_KIND)
    return re.compile(rf"^[#>\s*_-]*({names})\s*:", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class ClaimClassification:
    kind: str
    source: str

    @property
    def is_governing(self) -> bool:
        return self.kind == GOVERNING

    @property
    def grants_authority(self) -> bool:
        """May this classification narrow which nodes are citable authority?

        Only a declaration may. A lexical guess that flipped a corpus into the
        strict regime would reproduce the NIST failure, where recognising
        authority more precisely made the engine refuse authority it had been
        correctly accepting.

        `DECLARED_PREFIX` counts. It is a weaker STORE than the column — prose
        survives only until something reformats it — but it is the same ACT of
        declaration, made by the same construction pass. Excluding it would drop
        authority on every graph published before the column existed, which is
        the regression `battalion.py` documents: prose 9/17 nodes marked, tesco
        0/28, nist_ssdf 0/66, and Tesco M_T_G1 falling 30/30 GOVERNED to 0/6.
        The distinction is for callers reporting confidence, not for eligibility.
        """
        return self.source in (DECLARED, DECLARED_PREFIX, CLASSIFIED)


NOTHING = ClaimClassification(UNKNOWN, NO_SOURCE)


def declared_claim_kind(text: str) -> str:
    """The kind a node's text explicitly declares, if any."""
    if not text:
        return UNKNOWN
    match = _prefix_pattern().search(text)
    if not match:
        return UNKNOWN
    return _PREFIX_KIND[match.group(1).upper()]


def lexical_claim_kind(text: str) -> str:
    """A cheap deontic guess. A prior, never authority — see module docstring."""
    if not text:
        return UNKNOWN
    if _PROHIBITION.search(text) or _OBLIGATION.search(text):
        return GOVERNING
    if _PERMISSION.search(text):
        return GOVERNING
    return UNKNOWN


def classify(node: dict) -> ClaimClassification:
    """Resolve one node's claim kind, strongest available source first.

    `node` is a payload dict: `claim_kind` / `claim_kind_source` columns when
    the graph carries them, `text_content` otherwise.
    """
    stored = str(node.get("claim_kind") or "").strip().lower()
    if stored in CLAIM_KINDS:
        source = str(node.get("claim_kind_source") or "").strip().lower()
        return ClaimClassification(stored, source if source else DECLARED)

    # Legacy import path: the property round-tripped through a text prefix.
    text = str(node.get("text_content") or "").lstrip()
    declared = declared_claim_kind(text)
    if declared:
        return ClaimClassification(declared, DECLARED_PREFIX)

    guessed = lexical_claim_kind(text)
    if guessed:
        return ClaimClassification(guessed, LEXICAL)
    return NOTHING


@dataclass(frozen=True)
class NormativeProfile:
    """How much of a graph states rules, and how well we actually know."""

    declared_density: float
    lexical_density: float
    character: str
    node_count: int

    def to_dict(self) -> dict:
        return {
            "normative_density": round(self.declared_density, 3),
            "normative_density_lexical": round(self.lexical_density, 3),
            "normative_character": self.character,
        }


#: A graph is only called a rulebook on DECLARED evidence.
NORMATIVE_AT_OR_ABOVE = 0.35


def normative_density(nodes: list[dict]) -> float:
    """Share of nodes with a DECLARED governing claim."""
    if not nodes:
        return 0.0
    governing = sum(
        1 for node in nodes
        if (c := classify(node)).is_governing and c.grants_authority
    )
    return governing / len(nodes)


def profile(nodes: list[dict]) -> NormativeProfile:
    """Classify a graph's normative character, including "we do not know".

    Only DECLARED evidence decides, in both directions. That symmetry is the
    whole design, and it is forced by measurement: the lexical prior is unsound
    each way.

    *False positives.* On the Wikipedia graph-theory corpus it fires on a
    **forbidden** minor (a term of art), a book titled *Who Shall Survive*,
    "must contain" (mathematical necessity), "has to do with" (an idiom) and
    "may not have a unique 2-colouring" (possibility). Deontic, alethic and
    epistemic modality share their vocabulary and no regex separates them.

    *False negatives, which matter more.* The `policy-operations` corpus is
    unambiguously a rulebook — "may **be returned** for a full refund", "the
    customer **pays** return shipping", "they are **non-returnable**" — and the
    prior found 1 node in 25. Policy prose routinely states obligations in the
    declarative present with no modal at all. An earlier version of this
    function used the prior to certify a graph rule-free and called that corpus
    `informational`, which is the dangerous direction.

    So the prior never decides. Four values:

        normative      declared governing at or above the threshold
        mixed          some declared governing, below it
        informational  declared NON-governing nodes and no declared governing
        unclassified   nothing declared at all

    `unclassified` is a request to run the classifier, not a claim about the
    graph. Both Wikipedia and English negligence land there today, which is the
    truthful state: one is certainly not a rulebook, the other probably is, and
    nothing cheap can tell them apart.
    """
    if not nodes:
        return NormativeProfile(0.0, 0.0, "informational", 0)

    declared = normative_density(nodes)
    lexical = sum(
        1 for node in nodes if classify(node).is_governing
    ) / len(nodes)
    declared_non_governing = any(
        (c := classify(node)).grants_authority and not c.is_governing
        for node in nodes
    )

    if declared >= NORMATIVE_AT_OR_ABOVE:
        character = "normative"
    elif declared > 0.0:
        character = "mixed"
    elif declared_non_governing:
        character = "informational"
    else:
        character = "unclassified"
    return NormativeProfile(declared, lexical, character, len(nodes))


def normative_character(density: float) -> str:
    """Band a declared density on its own. Prefer `profile()`, which can say
    "unclassified"; this cannot and will call an unclassified graph
    informational."""
    if density >= NORMATIVE_AT_OR_ABOVE:
        return "normative"
    return "mixed" if density > 0.0 else "informational"


def default_verdict_space(character: str) -> str:
    """Which completeness rule to grade by when the caller did not say.

    A verdict space is a property of the *question*, not the graph, so this can
    only supply a default — never override a caller who declared one. What the
    graph legitimately decides is which default is less wrong for it.

    On a graph that states no rules, `coverage` asks whether policy governs the
    question, finds none because none exists anywhere in the corpus, and grades
    a correct answer `ILL_POSED`. That is not a conservative failure: a correct
    17-component enumeration was refused this way. `confirmation` asks whether
    the graph can answer, which is the only question such a corpus can be
    asked.

    Where rules do exist the historical `coverage` default stands. Silent
    permission is the dangerous failure on a rulebook, so `mixed` — some
    declared authority, below the rulebook threshold — keeps governance
    semantics rather than rounding down to the graph's descriptive majority.
    `unclassified` means the classifier could not tell, which is not a licence
    to change how a graph is graded, so it also holds.
    """

    return "confirmation" if character == "informational" else "coverage"
