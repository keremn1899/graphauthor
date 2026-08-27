"""Which paper in this corpus names which other one.

Not reference-list parsing. A reference list is the wrong instrument for the
only citation that can become an edge: one whose target is *also in the
corpus*. That question is answerable directly -- does A's text carry B's
identifier or B's title -- and it needs no heading structure, no bibliography
section and no entry grammar.

Which matters because the instrument it replaces silently produced nothing.
`collect_references` found reference sections by `heading_path`, and a PDF
page has none: 162 page atoms across five papers, zero heading paths, zero
citations, and therefore no citation signal for anything downstream to use.
That is the fifth time a rule written against HTML structure has matched
nothing on a PDF and reported success.

Measured on a corpus of five arXiv papers containing three real disputes: all
three citing pairs are found here, two by identifier and one by title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: arXiv ids and DOIs, the two identifiers a paper carries into another's text.
_ARXIV = re.compile(r"(?:arxiv[:\s]*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;)\]]+)", re.IGNORECASE)

#: Matching is done on the first N words of the title, not the whole of it.
#: Finding where a title *ends* is the hard part -- a PDF page puts the author
#: list on the line after it with no blank between, so the extracted block ran
#: `...artificial neural networks R. Thomas McCoy1* and Thomas L. Griffiths...`
#: and a paper that quotes the title verbatim in its own first line did not
#: match it. A prefix needs no boundary. Eight consecutive content words of a
#: paper title is not a coincidence, and over-extraction past the title costs
#: nothing because the extra words are never compared.
_TITLE_PROBE_WORDS = 8
_MAX_TITLE_CHARS = 400

# `comment` is deliberately absent: for a Comment paper "Comment on <title>"
# is the title, and it is also the line that names the paper being commented
# on -- the single most useful line in a dispute corpus.
_TITLE_NOISE = re.compile(
    r"^\s*(?:proceedings\b.*|preprint|under review.*|published as.*|"
    r"workshop paper.*|arxiv[:\s].*|\d+\s*(?:st|nd|rd|th)\s+conference.*|"
    r"technical report.*)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Citation:
    """One corpus paper naming another, with what said so."""

    citing: str
    cited: str
    #: "identifier" or "title" -- kept because they are not equally strong and
    #: a caller ranking pairs should be able to tell them apart.
    how: str
    evidence_unit_ids: tuple[str, ...] = ()


@dataclass
class SourceText:
    """The minimum a source has to expose to be scanned."""

    source_id: str
    #: (unit_id, text) in document order. The first is treated as the front
    #: matter that carries the title.
    units: Sequence[tuple[str, str]] = field(default_factory=tuple)


def _normalise(text: str) -> str:
    """Collapse whitespace and drop punctuation that PDF extraction invents.

    A PDF title arrives as `Comment\\n \\non\\n \\n"Modeling\\n \\nrapid...`,
    one word per line with a space between every character run. Comparing
    those raw fails on a title that is plainly present.
    """
    lowered = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(lowered.split())


def _identifiers(text: str) -> set[str]:
    out = {match.lower() for match in _DOI.findall(text)}
    out |= {match for match in _ARXIV.findall(text)}
    return out


def extract_title(units: Sequence[tuple[str, str]]) -> str:
    """The paper's own title, from its front matter.

    Deliberately conservative: venue lines, `Preprint` and similar are skipped,
    and the first substantial line after them is taken. A wrong title here
    costs a missed citation, never a false one, because a title match also has
    to clear `_MIN_TITLE_WORDS`.
    """
    if not units:
        return ""
    head = units[0][1]
    lines = [line.strip() for line in head.splitlines()]
    collected: list[str] = []
    for line in lines:
        if not line:
            if collected:
                break
            continue
        if _TITLE_NOISE.match(line):
            if collected:
                break
            continue
        collected.append(line)
        if len(" ".join(collected)) > _MAX_TITLE_CHARS:
            break
    return " ".join(collected)[:_MAX_TITLE_CHARS].strip()


def corpus_citations(sources: Iterable[SourceText]) -> list[Citation]:
    """Every case of one corpus paper naming another. Zero model calls.

    A paper naming itself is not a citation, and neither is the identifier a
    paper prints in its own header -- both are excluded by source id rather
    than by hoping the front matter was stripped.
    """
    catalogue = list(sources)
    titles = {source.source_id: extract_title(source.units) for source in catalogue}
    normalised_titles = {}
    for source_id, title in titles.items():
        words = _normalise(title).split()
        if len(words) >= _TITLE_PROBE_WORDS:
            normalised_titles[source_id] = " ".join(words[:_TITLE_PROBE_WORDS])
    #: A source's own identifiers, so its header does not cite itself.
    own_ids = {
        source.source_id: _identifiers(source.units[0][1]) if source.units else set()
        for source in catalogue
    }
    #: The id a source is filed under counts as its identifier: a workbook
    #: names an arXiv paper by its id, and the paper's own text may never
    #: print it.
    for source in catalogue:
        own_ids.setdefault(source.source_id, set()).update(
            _identifiers(source.source_id)
        )

    found: dict[tuple[str, str, str], list[str]] = {}
    for source in catalogue:
        for unit_id, text in source.units:
            ids = _identifiers(text)
            normalised = _normalise(text)
            for other in catalogue:
                if other.source_id == source.source_id:
                    continue
                if ids & own_ids.get(other.source_id, set()):
                    found.setdefault(
                        (source.source_id, other.source_id, "identifier"), []
                    ).append(unit_id)
                    continue
                title = normalised_titles.get(other.source_id)
                if title and title in normalised:
                    found.setdefault(
                        (source.source_id, other.source_id, "title"), []
                    ).append(unit_id)
    return [
        Citation(citing=citing, cited=cited, how=how,
                 evidence_unit_ids=tuple(units))
        for (citing, cited, how), units in sorted(found.items())
    ]
