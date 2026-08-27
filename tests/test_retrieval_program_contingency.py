"""A fallback may rebind the name it falls back for.

`CanonicalRetrievalProgram` checked assignment uniqueness across
`steps + contingency.fallback_steps`, which rejected the ordinary shape of a
contingency: look the node up exactly, and if that misses, find it lexically
and bind the SAME variable so `collect` still resolves.

Found on the m6 orders graph, where every governance pin came back `ABSENT`
with empty grounding. That reads as "the graph does not cover this" — it was a
crash inside `pipeline_b_execute` mapped to a coverage verdict, and it had
silently invalidated a pin battery and a pilot result.

Deterministic: no LLM, no network.
"""

from __future__ import annotations

import pytest

from retrieval_program import CanonicalRetrievalProgram


def _program(**overrides) -> dict:
    base = {
        "contract_version": "retrieval-v1",
        "steps": [{"tool": "exact_node_lookup",
                   "params": {"label_or_id": "DependencyDirectionRule"},
                   "assign_to": "rule_node"}],
        "collect": "$rule_node",
        "contingency": {
            "fallback_steps": [{"tool": "lexical_search",
                                "params": {"terms": ["DependencyDirectionRule"], "k": 1},
                                "assign_to": "rule_node"}],
            "fallback_collect": "$rule_node",
        },
    }
    base.update(overrides)
    return base


def test_the_planners_real_program_validates():
    """Captured verbatim from the Planner on the query that was crashing."""

    program = CanonicalRetrievalProgram.model_validate(_program())
    assert program.collect == "$rule_node"
    assert program.contingency.fallback_collect == "$rule_node"


def test_fallback_collect_is_usable_at_all():
    """Rebinding is not a nicety — `fallback_collect` can only name a variable
    a fallback step assigns, so forbidding the rebind made the field dead."""

    program = CanonicalRetrievalProgram.model_validate(_program())
    assigned = {s.assign_to for s in program.contingency.fallback_steps}
    assert program.contingency.fallback_collect.lstrip("$") in assigned


def test_duplicates_inside_the_primary_path_are_still_rejected():
    """Two primary steps writing one name is a real program defect: the second
    silently discards the first."""

    with pytest.raises(ValueError, match="duplicate assignment"):
        CanonicalRetrievalProgram.model_validate(_program(steps=[
            {"tool": "exact_node_lookup", "params": {"label_or_id": "A"},
             "assign_to": "rule_node"},
            {"tool": "exact_node_lookup", "params": {"label_or_id": "B"},
             "assign_to": "rule_node"},
        ]))


def test_duplicates_inside_the_fallback_path_are_still_rejected():
    with pytest.raises(ValueError, match="duplicate assignment"):
        CanonicalRetrievalProgram.model_validate(_program(contingency={
            "fallback_steps": [
                {"tool": "lexical_search", "params": {"terms": ["A"], "k": 1},
                 "assign_to": "rule_node"},
                {"tool": "lexical_search", "params": {"terms": ["B"], "k": 1},
                 "assign_to": "rule_node"},
            ],
            "fallback_collect": "$rule_node",
        }))


def test_a_fallback_may_still_reference_a_primary_assignment():
    """Rebinding must not break ordering: a fallback can read what the primary
    path already produced."""

    program = CanonicalRetrievalProgram.model_validate(_program(contingency={
        "fallback_steps": [{"tool": "hop_expansion",
                            "params": {"node_ids": "$rule_node", "hops": 1},
                            "assign_to": "neighbours"}],
        "fallback_collect": "$neighbours",
    }))
    assert program.contingency.fallback_steps[0].assign_to == "neighbours"


def test_forward_references_are_still_rejected():
    with pytest.raises(ValueError, match="before it is assigned"):
        CanonicalRetrievalProgram.model_validate(_program(steps=[
            {"tool": "hop_expansion", "params": {"node_ids": "$later", "hops": 1},
             "assign_to": "first"},
            {"tool": "exact_node_lookup", "params": {"label_or_id": "X"},
             "assign_to": "later"},
        ], collect="$first", contingency={}))
