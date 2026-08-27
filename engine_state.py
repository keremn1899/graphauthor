"""The one place an engine run is set up.

Six call sites used to build this dict independently — the product surface, the
CLI, two benchmark harnesses and two scripts — and they drifted. The benchmark
harness omitted `structural_index` as a memory optimisation, not knowing that
`verdict_computation.py`, `pipeline_a.py` and `correction_loops.py` read it
*from state*. With an empty index the deterministic verdict logic took a
different path, so **every benchmark number was produced by an engine the
product does not run**, and a case that answers correctly in production came
back wrong in the benchmark.

The lesson is not "remember to pass the index". It is that a harness which
constructs its own state will diverge from the thing it claims to measure, and
the divergence will be silent because both dicts look reasonable.

So: one builder, one shape. A caller chooses the query and the verdict space.
Everything else is the engine's business, and no caller can accidentally leave a
field out — or quietly add one the engine has never seen.

See `examples/baseline-similarity/FINDINGS_COVERAGE_OVERWRITES_CONFIRMATION.md`.
"""

from __future__ import annotations

from typing import Any

from models import DEFAULT_VERDICT_SPACE


def directive_from_frame(frame: str) -> str:
    """The standing instruction inside a governance frame, without the question.

    A configured frame is a template wrapped around a query
    (``"Resolve strictly per the encoded policy graph...: {q}"``). The reasoning
    tiers need the instruction alone: interpolating the question would put it
    back inside the query, which is what made the three verdict spaces retrieve
    different text for the same question.

    Lives here, next to the builder, because anything constructing engine state
    needs the same derivation — the adapter for the product path, and any probe
    that wants to measure what the product actually runs.
    """
    text = str(frame or "").replace("{q}", "").strip()
    return text.rstrip(":").strip()


def build_initial_state(
    query: str,
    *,
    compass: dict[str, Any] | None = None,
    structural_index: dict[str, Any] | None = None,
    verdict_space: str | None = None,
    governance_directive: str = "",
) -> dict[str, Any]:
    """A complete, canonical initial `EngineState`.

    `compass` and `structural_index` are passed already-serialised because
    callers hold them in different forms (a `Compass` object, a dict, or a
    connection they resolve themselves). Both default to empty rather than
    raising: an engine run with no compass is degraded, not invalid, and the
    honest-failure paths handle it.

    `verdict_space` is which of the three spaces the caller asked in —
    `confirmation` (can the graph answer this?), `coverage` (does any policy
    govern it?) or `ruling` (does this artifact conform?). A caller who names
    one always wins.

    `None` means "not asked", and is no longer the same as asking for
    `coverage`. It resolves to the graph's own default, published on the
    Compass from measured normative character, because the alternative was a
    corpus that states no rules being graded on whether policy governs the
    question — which refused correct answers rather than failing safe. With no
    compass to read, the historical default stands.

    `verdict_space_source` records which of those happened. An autonomous
    caller cannot otherwise tell whether it chose the grading rule or inherited
    it, and the two warrant different trust in an `ILL_POSED`.
    """
    declared = str(verdict_space or "").strip().lower()
    graph_default = str(
        ((compass or {}).get("graph_profile") or {}).get("default_verdict_space") or ""
    ).strip().lower()
    if declared:
        resolved, source = declared, "caller"
    elif graph_default:
        resolved, source = graph_default, "graph"
    else:
        resolved, source = DEFAULT_VERDICT_SPACE, "fallback"
    return {
        "query": query,
        "verdict_space": resolved,
        "verdict_space_source": source,
        # Standing instruction for the tiers that REASON, kept out of the query
        # so the tiers that RETRIEVE see the question as asked. It used to be
        # wrapped around the query itself, which meant coverage and confirmation
        # planned and retrieved against different text for the same question.
        #
        # Relocated rather than deleted, on architectural grounds: all three
        # verdict spaces now retrieve identical text for the same question, and
        # the directive demonstrably reaches Company and Battalion.
        #
        # An earlier note here claimed deleting it *cost ruling correctness*.
        # That was retracted: the probe measuring it hand-rolled its own state
        # and never executed this code, so the pin's swing was noise. A
        # controlled A/B on the path that does change found the two
        # configurations indistinguishable (n=8: 3/5 vs 2/6). No claim is made
        # that deleting it would have been worse.
        # See FINDINGS_PHASE2_UNFRAMING.md § CORRECTION.
        "governance_directive": governance_directive,
        "compass": compass or {},
        "structural_index": structural_index or {},

        # Planner
        "planner_program": {},
        "planner_reasoning": "",
        "planner_governing_candidates": [],

        # Backend
        "candidate_set": [],
        "judgment_candidate_set": [],
        "frontier_clusters": [],

        # Squad
        "squad_handoffs": [],

        # Company
        "company_handoff": {},
        "company_recovery_spec": {},

        # Verdict computation
        "confirmation_response": {},
        "dialogue_round": 0,

        # Battalion
        "final_answer": "",
        "provenance": [],
        "gaps": [],
    }


def serialise_structural_index(index: dict[str, Any] | None) -> dict[str, Any]:
    """`{node_id: StructuralFacts}` → `{node_id: dict}`, tolerating either form.

    Callers hold the index in both shapes depending on whether they came through
    `get_structural_index` or already serialised it. Normalising here means no
    call site has to remember which it has.
    """
    if not index:
        return {}
    return {
        nid: (facts.to_dict() if hasattr(facts, "to_dict") else facts)
        for nid, facts in index.items()
    }
