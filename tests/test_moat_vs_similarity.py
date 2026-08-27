"""The moat, measured: similarity cannot decide what a graph does not cover.

`positioning.md` stakes the company on one property:

    "We can tell 'genuinely ungoverned' from 'governed but not retrieved' —
     fuzzy retrieval always returns something similar, so everyone anchored in
     RAG is architecturally locked out."

The claims register flagged it as the last unproven claim, and it was the one
that mattered most: every other promise was guarded by a test, while the
central differentiator rested on architecture.

The experiment is deliberately unflattering to us. The baseline is **our own
embedding index** — the same `google/gemini-embedding-2-preview` vectors stored
on every Concept, the same corpus, the same questions. No strawman retriever, no
handicapped competitor. If similarity could separate covered from uncovered
material, it would show up here.

What is measured is **separability**, not accuracy. A retriever does not fail by
scoring uncovered questions low; it fails because uncovered questions score
*inside the range of covered ones*, so no threshold exists that could implement
"this graph does not cover your question". That is the architectural lock-out,
and it is a property of the score distributions rather than of any one answer.

The other half of the claim — that this engine returns the honest verdict where
similarity cannot — is already covered by `honest_failure` in `benchmarks/` and
by the coverage-space tests. This file supplies the half that was missing: the
contrast.

Marked `integration`: it embeds a dozen questions through OpenRouter.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

GRAPH = Path("data/benchmarks/agreements.lbug")

# The design, stated before the run so it cannot be tuned toward a result.
#
# A first attempt used topically DISTANT uncovered questions (tax rates, HTTP
# retries) and was refuted: similarity separated them cleanly, 0.788-0.838
# against 0.561-0.625. That is worth recording — embeddings do filter
# off-topic questions, and the moat is not there.
#
# The real claim is narrower. This graph encodes exactly three predicates:
# `is_member_of`, `is_partner_in`, `is_host_of`. It says nothing about funding
# shares, voting rights, withdrawal, or intellectual property. So both sets
# below name the SAME entities and differ only in whether the *relation* they
# ask about is encoded. That is precisely "governed but not retrieved" versus
# "genuinely ungoverned", and it is what a retriever has to distinguish.

#: Questions the graph answers — encoded predicates over known entities.
COVERED = (
    "Which countries are members of the ISS?",
    "Is Germany a partner in CERN?",
    "Which country hosts ITER?",
    "Is Japan a member of the ISS?",
    "Which country hosts CERN?",
    "Is the USA a partner in ITER?",
    "Which organisations is Russia a member of?",
    "Is Switzerland the host of CERN?",
    "Which countries partner in ITER?",
    "Is France a member of the ISS?",
)

#: Questions the graph does NOT answer — the same entities, predicates that
#: were never encoded. A topical retriever sees the same words.
UNCOVERED = (
    "What share of ITER funding does Germany provide?",
    "How many votes does Japan hold on the ISS board?",
    "What is the procedure for a country to withdraw from CERN?",
    "Who owns the intellectual property produced at ITER?",
    "What is the annual budget France contributes to CERN?",
    "When did Russia ratify the ISS agreement?",
    "Which country chairs the CERN council this year?",
    "How are disputes between ITER partners arbitrated?",
    "What penalties apply if the USA misses an ISS payment?",
    "How many staff does Switzerland second to CERN?",
)


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _node_vectors(db_path: Path):
    import real_ladybug as lb

    conn = lb.Connection(lb.Database(str(db_path)))
    try:
        rows = conn.execute("MATCH (n:Concept) RETURN n.id, n.embedding")
        out = []
        while rows.has_next():
            nid, vec = rows.get_next()
            if vec:
                out.append((nid, list(vec)))
        return out
    finally:
        conn.close()


def _best_match(question_vec, node_vectors):
    """Top-1 similarity — what any retriever would rank on."""
    best_id, best_score = "", -1.0
    for nid, vec in node_vectors:
        score = _cosine(question_vec, vec)
        if score > best_score:
            best_id, best_score = nid, score
    return best_id, best_score


@pytest.fixture(scope="module")
def scores():
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    if not GRAPH.exists():
        pytest.skip(f"{GRAPH} not present")

    from engine import get_embeddings_model

    node_vectors = _node_vectors(GRAPH)
    assert node_vectors, "graph has no embeddings to retrieve against"

    embedder = get_embeddings_model()
    questions = list(COVERED) + list(UNCOVERED)
    vectors = embedder.embed_documents(questions)

    covered = [_best_match(v, node_vectors)[1] for v in vectors[:len(COVERED)]]
    uncovered = [_best_match(v, node_vectors)[1] for v in vectors[len(COVERED):]]
    return {"covered": covered, "uncovered": uncovered}


@pytest.mark.integration
def test_similarity_always_returns_something(scores):
    """The first half of "always finds something similar": every uncovered
    question still has a confident-looking nearest neighbour. A retriever has
    no way to return nothing."""
    for score in scores["uncovered"]:
        assert score > 0.3, (
            f"nearest-neighbour similarity {score:.3f} for a question the graph "
            "does not cover — the retriever still returned a match")


@pytest.mark.integration
def test_no_similarity_threshold_can_implement_ungoverned(scores):
    """The lock-out itself.

    If similarity could decide coverage, the worst covered question would still
    outscore the best uncovered one, leaving a gap to put a threshold in. It
    does not: the ranges overlap, so any cut-off either refuses questions the
    graph *can* answer or accepts questions it cannot.
    """
    worst_covered = min(scores["covered"])
    best_uncovered = max(scores["uncovered"])

    assert best_uncovered >= worst_covered, (
        "similarity separated encoded from unencoded predicates over the same "
        "entities. That is the moat claim failing on its own terms, and it "
        "should block the positioning sentence rather than be tuned away "
        f"(worst covered {worst_covered:.3f} > best uncovered {best_uncovered:.3f})")


@pytest.mark.integration
def test_the_overlap_is_reported_not_just_asserted(scores, capsys):
    """A number a human can argue with, printed for the record."""
    with capsys.disabled():
        cov, unc = scores["covered"], scores["uncovered"]
        print("\n  top-1 cosine against the same corpus")
        print(f"    covered   min={min(cov):.3f}  max={max(cov):.3f}")
        print(f"    uncovered min={min(unc):.3f}  max={max(unc):.3f}")
        overlap = min(max(cov), max(unc)) - max(min(cov), min(unc))
        print(f"    overlap   {overlap:.3f}  "
              f"({'ranges overlap — no threshold exists' if overlap > 0 else 'separable'})")
