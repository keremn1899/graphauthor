"""The counterfactual rule must refuse graph edits and allow subject changes.

`grammar_guard` sets its own bar in its docstring: "Only patterns with
near-zero false-positive risk belong here." This rule matched `if i changed`
with no regard for what was being changed, so it refused "what would break if
I changed how backend_tools builds the evidence packet" — a question answered
entirely from current state by following LEADSTO, and the question the
repo-architecture construction contract exists to serve ("a graph a coding
agent can check a proposed change against").

The distinction is the object. A hypothetical edit to the *graph* is out of
scope. A hypothetical change to the *subject the graph describes* is the
product.
"""

from __future__ import annotations

import pytest

from grammar_guard import _PATTERNS

_COUNTERFACTUAL = next(
    pattern for pattern, reason, _gap, _fix in _PATTERNS if "Counterfactual" in reason
)


@pytest.mark.parametrize(
    "query",
    [
        "If I added a node for retries, what would connect to it?",
        "What happens if I removed the NEARTO edges between these concepts?",
        "if i renamed this concept in the graph, what breaks?",
        "If I deleted the planner node from the graph?",
    ],
)
def test_hypothetical_graph_edits_are_refused(query):
    assert _COUNTERFACTUAL.search(query)


@pytest.mark.parametrize(
    "query",
    [
        # The one that was refused in the packet-direct run, verbatim.
        "What does backend_tools depend on, and what would break if I changed "
        "how it builds the evidence packet?",
        "If I changed the retry budget in planner.py, which modules are affected?",
        "If I renamed build_evidence_packet, what calls it?",
        "If I removed the Squad bypass, which routing rules would no longer hold?",
        "Which modules import models?",
    ],
)
def test_changes_to_the_subject_matter_are_not_graph_edits(query):
    assert not _COUNTERFACTUAL.search(query)
