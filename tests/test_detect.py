"""The free detector: what it finds, and what it provably cannot."""

from __future__ import annotations

from source_pipeline.detect import detect


PASSAGES = [
    ("p1", "Hrafnkell rode to Adalbol. Then Einarr met Hrafnkell there."),
    ("p2", "Einarr took the horse. Hrafnkell had forbidden it at Adalbol."),
    ("p3", "The killing followed, and Samr rode to the Thing."),
    ("p4", "Samr and Hrafnkell met at the Thing. Samr spoke."),
]


def test_it_ranks_by_how_many_passages_name_a_thing():
    found = detect(PASSAGES)
    ranked = dict(found.ranked())

    assert ranked["Hrafnkell"] == 3
    assert ranked["Samr"] == 2
    # Ranking is the point: frequency is importance information the per-passage
    # extractor never sees, because it is never shown two passages at once.
    assert found.ranked()[0][0] == "Hrafnkell"


def test_a_name_in_one_passage_only_is_not_a_candidate():
    found = detect(PASSAGES, min_passages=2)

    assert "Einarr" in found.passages_by_name  # two passages
    found_strict = detect(PASSAGES, min_passages=3)
    assert "Einarr" not in found_strict.passages_by_name


def test_sentence_initial_capitals_are_not_treated_as_names():
    """The failure mode that would swamp the signal if left alone."""
    found = detect([("p1", "The man rode. Then he stopped. But Hrafnkell went on.")])

    assert "The" not in found.passages_by_name
    assert "Then" not in found.passages_by_name
    assert "But" not in found.passages_by_name


def test_co_occurrence_gives_candidate_edges():
    found = detect(PASSAGES)
    pairs = dict(found.strong_pairs(minimum=2))

    assert pairs[("Adalbol", "Hrafnkell")] == 2
    # Hrafnkell and Samr share exactly one passage, so the threshold excludes
    # them. That is the threshold doing its job, not a miss: a single shared
    # passage is the weakest possible evidence of a relationship.
    assert ("Hrafnkell", "Samr") not in pairs
    assert dict(found.strong_pairs(minimum=1))[("Hrafnkell", "Samr")] == 1


def test_it_cannot_find_an_unnamed_event():
    """The honest limit, pinned so nobody claims otherwise later.

    Each passage below describes the same killing and none of them names it.
    A frequency rule over surface forms recovers the participants and misses
    the event entirely — the same hole the stateless extractor has.
    """
    passages = [
        ("p1", "Einarr was slain by Hrafnkell on the hillside."),
        ("p2", "After the slaying, Thorbjorn sought redress from Hrafnkell."),
        ("p3", "The deed at the hillside was never atoned by Hrafnkell."),
    ]
    found = detect(passages)
    names = set(found.passages_by_name)

    assert "Hrafnkell" in names
    assert not {"slaying", "deed", "killing"} & names
