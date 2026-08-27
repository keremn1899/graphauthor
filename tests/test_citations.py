"""Which paper in a corpus names which other one.

The instrument this replaces produced nothing and said so nowhere:
`collect_references` found reference sections by `heading_path`, and a PDF
page has none. Measured on five arXiv papers -- 162 page atoms, zero heading
paths, zero citations -- which left `supports`/`contradicts` with no structural
signal and a lexical shortlist that paired the wrong papers.

The shapes below are the ones the real corpus turned out to have. Each is a
fixture rather than a corpus file so the suite does not depend on a scratch
directory, and the corpus measurement is recorded separately.
"""

from __future__ import annotations

from source_pipeline.citations import (
    Citation,
    SourceText,
    corpus_citations,
    extract_title,
)


def _source(source_id: str, *pages: str) -> SourceText:
    return SourceText(
        source_id=source_id,
        units=tuple((f"{source_id}:page:{i}", text) for i, text in enumerate(pages)),
    )


DAS = _source(
    "2303.02536",
    "Finding Alignments Between Interpretable Causal Variables\n"
    "Atticus Geiger, Zhengxuan Wu\nStanford University",
    "With DAS we find a perfect alignment to a causal model.",
)

ILLUSION = _source(
    "2311.17030",
    "Is This the Subspace You Are Looking for? An Interpretability Illusion\n"
    "Aleksandar Makelov, Georg Lange",
    "We show that the evaluation metric of arXiv:2303.02536 is misleading.",
)


def _pairs(citations: list[Citation]) -> set[tuple[str, str]]:
    return {(c.citing, c.cited) for c in citations}


def test_an_identifier_in_the_text_is_a_citation():
    found = corpus_citations([DAS, ILLUSION])
    assert _pairs(found) == {("2311.17030", "2303.02536")}
    assert found[0].how == "identifier"
    assert found[0].evidence_unit_ids == ("2311.17030:page:1",)


def test_a_paper_does_not_cite_itself_through_its_own_header():
    """DAS prints its own id on its own front page in the real corpus."""
    self_naming = _source(
        "2303.02536",
        "Finding Alignments\narXiv:2303.02536v3 [cs.LG]",
        "Body text.",
    )
    assert corpus_citations([self_naming, ILLUSION]) == [
        Citation(citing="2311.17030", cited="2303.02536", how="identifier",
                 evidence_unit_ids=("2311.17030:page:1",))
    ]


def test_a_quoted_title_is_a_citation_when_no_identifier_is_given():
    """The strongest signal in the real corpus, and the one it nearly missed.

    A Comment paper names its target in its own title and nowhere else -- no
    arXiv id, no DOI, and the authors' surnames abbreviated to `M&G` from the
    second paragraph on.
    """
    target = _source(
        "2305.14701",
        # The shape that broke the first version: no blank line between the
        # title and the author list, so the extracted block runs straight on.
        "Modeling rapid language learning by distilling Bayesian priors\n"
        "into artificial neural networks\n"
        "R. Thomas McCoy and Thomas L. Griffiths\n"
        "Department of Computer Science, Princeton University",
        "We distil a Bayesian prior into a neural network.",
    )
    comment = _source(
        "2608.12974",
        # And the shape PDF extraction produces: one word per line.
        "Comment\n \non\n \n“Modeling\n \nrapid\n \nlanguage\n \nlearning\n"
        " \nby\n \ndistilling\n \nBayesian\n \npriors\n \ninto\n \nartificial\n"
        " \nneural\n \nnetworks”\n \nOrr Well",
        "M&G's model provides a much weaker approximation.",
    )
    found = corpus_citations([target, comment])
    assert _pairs(found) == {("2608.12974", "2305.14701")}
    assert found[0].how == "title"


def test_papers_that_do_not_name_each_other_produce_nothing():
    """The control. Five parallel systems papers cite none of each other.

    Without this the detector could be returning every pair and still look
    right on the corpus that has three.
    """
    a = _source("2608.20097", "TrustRAG: Blockchain-Enhanced Retrieval\nAuthors",
                "We score credibility by committee.")
    b = _source("2608.20756", "Vis-Poison: Poisoning Visual Knowledge\nAuthors",
                "We poison a multimodal retriever.")
    assert corpus_citations([a, b]) == []


def test_a_title_too_short_to_be_distinctive_is_not_matched_on():
    """A three-word title inside another paper's prose is a coincidence."""
    short = _source("aaa", "Deep Learning\nAuthors", "Body.")
    other = _source("bbb", "Something Else Entirely\nAuthors",
                    "We use deep learning throughout this work.")
    assert corpus_citations([short, other]) == []


def test_the_title_probe_survives_running_into_the_author_list():
    """Extraction may over-run; only the first words are ever compared."""
    title = extract_title((
        ("p:0", "Modeling rapid language learning by distilling Bayesian priors\n"
                "into artificial neural networks\nR. Thomas McCoy"),
    ))
    assert title.lower().startswith("modeling rapid language learning")
    # Over-extraction is expected and harmless, so it is asserted rather than
    # quietly relied upon.
    assert "McCoy" in title


def test_venue_boilerplate_is_not_taken_for_a_title():
    title = extract_title((
        ("p:0", "Proceedings of Machine Learning Research vol 236:1-23, 2024\n"
                "Finding Alignments Between Interpretable Causal Variables\n"),
    ))
    assert title.startswith("Finding Alignments")
