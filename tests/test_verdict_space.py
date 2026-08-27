"""A verdict space is declared by the caller, never inferred from the words.

`discover` used to return ILL_POSED for questions the engine had answered. The
engine received only a string, so it could not know which of the three spaces
the caller asked in, and Battalion's governance judgment — "no policy governs
the identity of the Ring-bearer", true and irrelevant on a knowledge graph —
was applied to every query and overwrote the verdict.

See examples/baseline-similarity/FINDINGS_COVERAGE_OVERWRITES_CONFIRMATION.md.
Measured end to end by the `baseline_similarity` benchmark: 0/8 covered
questions answered before, 8/8 after.

Deterministic: no LLM, no network.
"""

from __future__ import annotations


def test_discover_cannot_have_its_verdict_decided_by_the_governance_space():
    """The invariant, under either implementation of `discover`.

    This used to assert the literal ``verdict_space="confirmation"`` in the
    source, which was the fix while `discover` invoked the exploratory FSM: the
    engine got only a string, so it could not know which space was being asked
    and Battalion's governance judgement overwrote the verdict.

    `discover` is Ask now — four retrieval ops, then a claim — and that path
    never reaches Battalion, so the overwrite is impossible by construction
    rather than prevented by a declaration. Asserting the old string would
    demand a fix for a bug the code can no longer have.

    So assert what actually matters, and keep the original guard alive for the
    engine path in case `discover` ever goes back to it.
    """
    import inspect

    from mcp_server.surface import Surface

    src = inspect.getsource(Surface.discover)

    if "self._invoke(" in src:
        assert 'verdict_space="confirmation"' in src, (
            "discover invokes the engine without declaring confirmation space; "
            "the governance fold will decide its verdict")
        return

    assert "run_ask" in src, (
        f"discover uses neither the engine nor Ask; this test no longer knows "
        f"what invariant to hold it to")
    ask_src = inspect.getsource(__import__("mcp_server.ask", fromlist=["ask"]))
    for coupling in ("battalion", "governance", "verdict_space"):
        assert coupling not in ask_src, (
            f"the Ask path gained a {coupling!r} coupling; a confirmation answer "
            f"can now be overwritten by the governance space again")


def test_the_engine_defaults_to_legacy_behaviour():
    """An undeclared space keeps the historical mapping, so callers that predate
    this are unaffected."""
    from models import DEFAULT_VERDICT_SPACE

    assert DEFAULT_VERDICT_SPACE == "coverage"








def test_the_state_readers_that_made_that_matter_still_read_from_state():
    """Guard the guard: if these ever stop reading from state the test above
    becomes vacuous, and if a fourth reader appears it inherits the same trap."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    readers = [p for p in ("verdict_computation.py", "pipeline_a.py",
                           "correction_loops.py")
               if 'state.get("structural_index")' in (root / p).read_text()]
    assert readers, (
        "no module reads structural_index from state any more — the benchmark "
        "divergence this guards may no longer exist; re-check before deleting")


# --------------------------------------------------- the directive relocation


def test_the_governance_instruction_travels_beside_the_query_not_inside_it():
    """Retrieval must see the question as asked.

    The frame used to be wrapped around the question and became state["query"],
    so coverage planned and retrieved against different text than confirmation
    for the same question — the three spaces were three retrievals, not three
    projections of one.
    """
    import inspect

    from interaction.engine_adapter import EngineAdapter

    src = inspect.getsource(EngineAdapter.query)
    assert "self._frame.format" not in src, (
        "the frame must not be interpolated into the query any more")
    assert "_invoke_with_deadline(question" in src, (
        "the question must reach the engine as asked")


def test_the_instruction_is_relocated_not_deleted():
    """Deleting it cost ruling correctness on the allow_looks_deny class —
    grounding held, the ruling flipped. It is instruction the reasoning tiers
    need, so it must still arrive."""
    from interaction.engine_adapter import EngineAdapter
    from mcp_server.surface import DEFAULT_GOV_FRAME

    adapter = EngineAdapter.__new__(EngineAdapter)
    adapter._frame = DEFAULT_GOV_FRAME
    directive = adapter._directive()

    assert "{q}" not in directive, "the placeholder must be stripped"
    assert "no policy governs it" in directive, (
        "the instruction itself must survive the relocation")




def test_confirmation_space_gets_no_directive():
    """An instruction about policy coverage would be answering a question
    nobody asked."""
    from engine_state import build_initial_state

    assert build_initial_state("q")["governance_directive"] == ""
    assert build_initial_state(
        "q", governance_directive="resolve strictly"
    )["governance_directive"] == "resolve strictly"
