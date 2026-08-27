"""Deterministic grammar-violation guard.

Runs before ``planner_initial`` and short-circuits the pipeline to an
``ILL_POSED`` verdict when the query contains patterns that are
unambiguously outside the canonical retrieval grammar (see
``design [new]/invariants.md`` — Canonical Retrieval Verb Vocabulary).

The LLM Planner's confirmation pass already knows how to emit
``ILL_POSED``, but in practice it frequently over-accommodates
GQL-style predicates, arithmetic aggregations, graph-algorithm
invocations, and counterfactual graph edits — returning CONFIRMED with
confabulated content. This deterministic pre-check catches the
obvious cases so the engine can honestly refuse.

Only patterns with near-zero false-positive risk belong here. Anything
ambiguous is left to the Planner/confirmation LLM.
"""

from __future__ import annotations

import re
from typing import Any

from sst_debug import log_event

# Each entry: (compiled_regex, reason_template, gap_type, suggestion)
_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (
        re.compile(r"\bdegree\s*(?:is\s+)?(?:greater|less|more|fewer|at\s+least|at\s+most|>|<|>=|<=|=)\b", re.I),
        "Degree-filter predicates are GQL-style operations, not canonical retrieval verbs.",
        "schema_gap",
        "Express the question as a traversal from a named concept, or use an external graph analytics tool.",
    ),
    (
        re.compile(r"\b(in|part\s+of|member\s+of)\s+\w[\w\s]*\s+but\s+not\s+in\b", re.I),
        "Set-difference over edge/role types is outside the canonical grammar.",
        "schema_gap",
        "Ask about a single relation type or enumerate both sets explicitly.",
    ),
    (
        re.compile(r"\b(average|mean|sum|median|variance|std(?:dev)?|top[- ]?\d+)\s+(?:of|across|over)?\s*(?:the\s+)?(?:all\s+)?(?:nodes?|edges?|centrality|degree|weights?)\b", re.I),
        "Aggregation arithmetic over graph state is not a canonical retrieval verb.",
        "schema_gap",
        "Ask about a specific concept or relation instead of aggregating over all nodes.",
    ),
    (
        re.compile(r"\b(pagerank|page\s*rank|eigenvector\s+centrality|louvain|community\s+detection|clustering\s+coefficient|shortest\s+path\s+algorithm)\b", re.I),
        "Named graph algorithms are out of scope for the retrieval grammar.",
        "schema_gap",
        "Use structural landmark roles from the Compass, or run the algorithm externally.",
    ),
    (
        # The object matters, and this rule used to ignore it. "If I changed
        # how backend_tools builds the packet" is a question about the subject
        # the graph describes, answerable from current state as an ordinary
        # fanout — and on an architecture graph it is *the* question, since the
        # construction purpose for that corpus is "a graph a coding agent can
        # check a proposed change against". Refusing it was a false positive
        # against this module's own bar of near-zero false-positive risk.
        #
        # What stays out of scope is a hypothetical edit to the *graph*: adding
        # a node, deleting an edge, renaming a concept. So the graph vocabulary
        # must appear close enough to the verb to be its object.
        re.compile(
            r"\bif\s+i\s+(?:added|removed|deleted|inserted|changed|renamed)\b"
            r"[^.?!]{0,40}?\b(?:nodes?|edges?|concepts?|relations?|graph|"
            r"leadsto|contains|expresses|nearto)\b",
            re.I,
        ),
        "Counterfactual graph edits (write-proposal reasoning) are out of scope in this phase.",
        "schema_gap",
        "Query the current graph state; write-proposal testing is a future phase.",
    ),
    (
        re.compile(r"\bcompute\s+(pagerank|centrality|betweenness|closeness|eigenvector)\b", re.I),
        "Algorithmic computation verbs are not canonical retrieval verbs.",
        "schema_gap",
        "Read the Compass landmark roles or run the algorithm externally.",
    ),
]


def _detect(query: str) -> tuple[str, str, str] | None:
    if not query:
        return None
    for pat, reason, gap_type, suggestion in _PATTERNS:
        if pat.search(query):
            return reason, gap_type, suggestion
    return None


def grammar_guard_node(state: dict) -> dict[str, Any]:
    """Detect grammar violations and, if any, populate ILL_POSED verdict state.

    Returns state patch with:
      * ``confirmation_response.verdict = "ILL_POSED"`` (+ reason) so
        Battalion's existing ILL_POSED branch fires.
      * ``grammar_guard_triggered`` flag for routing + telemetry.
      * A single ``schema_gap`` gap entry surfaced through
        ``company_verdict.gap_inventory`` (Battalion reads from there when
        no internal_handoff is present).
    """
    query = state.get("query", "")
    hit = _detect(query)
    if hit is None:
        return {"grammar_guard_triggered": False}

    reason, gap_type, suggestion = hit
    gap = {
        "gap_type": gap_type,
        "specific_node_or_concept": "(grammar violation)",
        "actionable_suggestion": suggestion,
        "severity": "blocking",
    }
    log_event(
        "grammar_guard_trigger",
        reason=reason,
        gap_type=gap_type,
        query=query[:160],
    )
    print(f"\n[GrammarGuard] ILL_POSED — {reason}")
    return {
        "grammar_guard_triggered": True,
        "confirmation_response": {
            "verdict": "ILL_POSED",
            "ill_posed_reason": reason,
            "reasoning": "Deterministic grammar-guard rejection.",
        },
        "company_verdict": {
            "gap_inventory": [gap],
            "hypothesis_assessment": "grammar_violation",
        },
        "degradation_flags": list(state.get("degradation_flags") or []) + ["grammar_guard:ill_posed"],
    }


def route_after_grammar_guard(state: dict) -> str:
    return "battalion_synthesize" if state.get("grammar_guard_triggered") else "planner_initial"
