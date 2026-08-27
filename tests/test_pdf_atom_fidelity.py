"""The PDF path loses no text, so a missing claim is a selection failure.

This settles boundary gap 1's open question. `supports`/`contradicts` reached
precision 2/2 and recall 2/3; the missed dispute was missed because the
critique's thesis — that the alignment is an illusion — was not among the
claims extracted for that paper. Two explanations, and they need opposite
fixes:

  (a) the thesis reached the selector and lost to weaker claims  -> selection
  (b) the thesis never reached the selector                      -> grain

(b) is a claim about this pipeline, and this pipeline is here even though that
corpus is not. Measured on a synthetic twelve-page paper with the thesis on
page one: **zero characters lost** at every segmentation setting, and the
thesis reaches an atom in all of them. (b) is false. The cause is selection.

The second number is the useful one. At the default 6000-char cap the thesis
lands in a 5,889-character atom holding roughly ninety other candidate
sentences — one page, one atom. A selector taking a few claims per atom is
choosing the paper's argument against ninety competitors with nothing marking
which is which.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from source_pipeline.contracts import SegmentationContext, SourceArtifact
from source_pipeline.pdf import PdfSourceParser
from source_pipeline.runner import parse_artifact, segment_parsed_source
from source_pipeline.segmenters import BoundedTextSegmenter

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

THESIS = ("We show that the apparent alignment is an interpretability illusion: "
          "the subspace does not encode the causal variable it appears to.")
KEY = "interpretability illusion"
FILLER = ("We evaluate on three benchmarks and report mean accuracy over five "
          "seeds. The results are consistent across model scales.")


@pytest.fixture(scope="module")
def paper(tmp_path_factory):
    """Twelve pages, thesis on page one, buried in ordinary method prose."""
    from make_text_pdf import make_pdf

    pages = []
    for p in range(1, 13):
        lines = [f"Page {p} of the critique paper.", ""]
        if p == 1:
            lines += ["Abstract", "", THESIS, "",
                      "Prior work reports a perfect alignment (100% IIA).", ""]
        lines += [f"[{p}.{i}] {FILLER}" for i in range(50)]
        pages.append(lines)

    out = tmp_path_factory.mktemp("pdf") / "critique.pdf"
    make_pdf(pages, str(out))
    return out


def _parsed(paper):
    return parse_artifact(
        SourceArtifact(source_id="critique", media_type="application/pdf",
                       content=paper.read_bytes(), locator=str(paper)),
        [PdfSourceParser()],
    )


def _atoms(paper, cap):
    return segment_parsed_source(
        _parsed(paper), [BoundedTextSegmenter()],
        context=SegmentationContext(max_atom_chars=cap),
    ).atoms


@pytest.mark.parametrize("cap", [6000, 2000, 1200, 600])
def test_segmentation_loses_no_characters(paper, cap):
    unit_chars = sum(len(u.text) for u in _parsed(paper).units)
    atom_chars = sum(len(a.text) for a in _atoms(paper, cap))
    assert unit_chars > 50_000, "the fixture is too small to be a real test"
    assert atom_chars == unit_chars, f"segmentation dropped {unit_chars - atom_chars} chars"


@pytest.mark.parametrize("cap", [6000, 2000, 1200, 600])
def test_the_thesis_reaches_an_atom_at_every_grain(paper, cap):
    assert any(KEY in a.text for a in _atoms(paper, cap))


def test_the_detector_can_report_absence(paper):
    """Positive control. Without it every assertion above passes on a substring
    check that happens to match anything."""
    atoms = _atoms(paper, 6000)
    assert not any("a phrase certainly not in this paper" in a.text for a in atoms)


def test_a_page_becomes_one_atom_holding_many_candidate_sentences(paper):
    """The shape of the selection problem, in one number.

    Not a defect on its own — a page-sized atom is a legitimate grain for a
    PDF, which carries no headings to cut on. It is why "the thesis was
    available" and "the thesis was found" are far apart.
    """
    hit = next(a for a in _atoms(paper, 6000) if KEY in a.text)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", hit.text) if len(s.strip()) > 25]
    assert len(sentences) > 50, (
        "the fixture no longer reproduces the crowding this test is about"
    )


def test_a_pdf_carries_no_heading_path_to_cut_on(paper):
    """Why the atom is page-sized: there is no structure to segment by.

    The same absence broke reference collection, which tested `heading_path`
    against /reference|bibliograph/ and matched nothing across 162 page atoms.
    """
    assert all(not u.heading_path for u in _parsed(paper).units)
