"""Nobody builds an engine state by hand.

Six call sites used to construct this dict independently — the product surface,
the CLI, two benchmark harnesses, the coverage adapter and two scripts. They
drifted, silently, because every one of them looked reasonable on its own: the
benchmark harness omitted `structural_index` as a memory optimisation, not
knowing three modules read it from state. The result was that every benchmark
number came from an engine the product does not run.

A guard on "did you remember the field" would have missed it — the field was
omitted deliberately. The only thing that closes this class is having one
builder, so there is nothing to drift from.

See examples/baseline-similarity/FINDINGS_COVERAGE_OVERWRITES_CONFIRMATION.md.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Where an engine run is legitimately configured.
_BUILDER = "engine_state.py"

#: Not production. Historical probes keep their own state on purpose — they are
#: records of what was run at the time and must not be rewritten. Tests build
#: minimal states deliberately.
# "build/" and "dist/" are setuptools' copies of the tree. Building a
# wheel put a second copy of every module under build/lib, and this scan
# found the same violations there — so packaging the project failed its
# own suite, which is a bad thing to discover while publishing.
_EXEMPT_PREFIXES = ("tests/", "examples/", "archive/", "scratch/", "demo/",
                    "build/", "dist/")


def _hand_rolled_state_files() -> list[str]:
    hits = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel == _BUILDER or rel.startswith(_EXEMPT_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # The signature of a hand-rolled EngineState: a dict literal carrying
        # the pipeline's own scratch fields.
        if re.search(r'"planner_program"\s*:\s*\{\}', text) and \
           re.search(r'"squad_handoffs"\s*:\s*\[\]', text):
            hits.append(rel)
    return sorted(hits)


def test_production_never_builds_an_engine_state_by_hand():
    hand_rolled = _hand_rolled_state_files()
    assert not hand_rolled, (
        "these build an EngineState directly instead of calling "
        f"engine_state.build_initial_state: {hand_rolled}. A harness that "
        "constructs its own state will diverge from the engine it claims to "
        "measure, and the divergence will be silent.")


def test_the_builder_carries_every_field_the_engine_expects():
    """The builder must satisfy the same shape contract the state test pins."""
    from engine_state import build_initial_state
    from models import EngineState

    state = build_initial_state("q")
    annotated = set(EngineState.__annotations__)
    for key in state:
        assert key in annotated, f"builder emits {key!r}, which EngineState does not declare"


def test_the_builder_defaults_to_legacy_verdict_space():
    from engine_state import build_initial_state

    assert build_initial_state("q")["verdict_space"] == "coverage"
    assert build_initial_state(
        "q", verdict_space="confirmation")["verdict_space"] == "confirmation"


def test_the_structural_index_survives_the_builder():
    """The specific omission that started this: it must arrive populated."""
    from engine_state import build_initial_state, serialise_structural_index

    class _Facts:
        def to_dict(self):
            return {"roles": ["orphan"]}

    state = build_initial_state(
        "q", structural_index=serialise_structural_index({"n1": _Facts()}))
    assert state["structural_index"] == {"n1": {"roles": ["orphan"]}}
    # already-serialised input passes through untouched
    assert serialise_structural_index({"n1": {"roles": []}}) == {"n1": {"roles": []}}
