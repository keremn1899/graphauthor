"""Candidate entities and relations found without a model reading anything.

Measured on Hrafnkels saga: 47 passages yield 34 candidate names and 56
co-occurring pairs, at zero cost, ranked by how many passages each appears in.
The top of that ranking is the protagonist, the antagonist, the farm they
fight over, the shepherd whose killing starts it, and the horse — which is a
better *importance* ordering than the per-passage extractor produced, because
frequency is information the extractor never sees.

The point is not to replace interpretation. It is to bound it. Typing a
candidate and naming what a co-occurrence means are the two jobs a model is
actually needed for, and both are bounded by entity and pair counts rather
than by corpus size. Reading every passage to discover that Hrafnkell exists
is work the corpus already did for us.

What this does NOT find: anything unnamed. Events have no canonical surface
form — each passage invents one — so no frequency rule recovers them. That is
the same hole the stateless extractor has, and it is not closed here.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

#: A capitalised word proves nothing on its own: sentences start with capitals
#: too. The discriminator is whether the word EVER appears mid-sentence. A real
#: name does — "and Hrafnkell went on" — while a sentence-starter like "Then"
#: essentially never does. So both positions are counted, and a token is
#: admitted only if it has at least one mid-sentence sighting anywhere in the
#: corpus; its frequency then counts every occurrence, including the
#: sentence-initial ones.
#:
#: The first version of this excluded sentence-initial matches outright, which
#: silently lost every occurrence of a name that happened to start its
#: sentence. On a four-passage fixture that took the protagonist from 3 to 2
#: and dropped another character below the threshold entirely.
_WORD = re.compile(r"\b([A-ZÞÐÆÖÁÉÍÓÚÝ][a-zþðæöáéíóúýA-Z-]{2,})\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?:;\"'\u2019\u201d]\s+|\n\s*)$")

STOPWORDS = frozenset({
    "The", "This", "That", "Then", "There", "Now", "But", "And", "For", "When",
    "So", "He", "She", "They", "It", "His", "Her", "Their", "Chapter", "Story",
    "Saga", "God", "One", "All", "Thus", "Which", "What", "Who", "Some", "Such",
    "After", "Before", "Here", "Yet", "Nor", "Both", "Neither", "Why", "How",
    "Answered", "Said", "Quoth", "Never", "Nay", "Yea", "Well", "Also", "Though",
})


@dataclass
class Candidates:
    """Ranked candidate entities and the pairs that share passages."""

    passages_by_name: dict[str, set[str]] = field(default_factory=dict)
    pair_counts: Counter = field(default_factory=Counter)
    passage_count: int = 0

    def ranked(self) -> list[tuple[str, int]]:
        return sorted(
            ((name, len(ps)) for name, ps in self.passages_by_name.items()),
            key=lambda row: (-row[1], row[0]),
        )

    def strong_pairs(self, minimum: int = 3) -> list[tuple[tuple[str, str], int]]:
        return sorted(
            ((pair, count) for pair, count in self.pair_counts.items() if count >= minimum),
            key=lambda row: (-row[1], row[0]),
        )


def detect(
    passages: list[tuple[str, str]],
    *,
    min_passages: int = 2,
    stopwords: frozenset[str] = STOPWORDS,
) -> Candidates:
    """`passages` is (passage_id, text). No model, no network, no state."""
    by_name: dict[str, set[str]] = defaultdict(set)
    seen_mid_sentence: set[str] = set()

    for passage_id, text in passages:
        body = text or ""
        for match in _WORD.finditer(body):
            name = match.group(1)
            if name in stopwords:
                continue
            by_name[name].add(passage_id)
            if not _SENTENCE_START.search(body[: match.start()]):
                seen_mid_sentence.add(name)

    kept = {
        name: ids
        for name, ids in by_name.items()
        if len(ids) >= min_passages and name in seen_mid_sentence
    }
    names_by_passage: dict[str, set[str]] = defaultdict(set)
    for name, ids in kept.items():
        for passage_id in ids:
            names_by_passage[passage_id].add(name)

    pairs: Counter = Counter()
    for names in names_by_passage.values():
        for left, right in itertools.combinations(sorted(names), 2):
            pairs[(left, right)] += 1

    return Candidates(
        passages_by_name=kept, pair_counts=pairs, passage_count=len(passages)
    )
