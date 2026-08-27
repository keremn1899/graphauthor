"""Probes must build engine state the way the product does, or say they don't.

The `structural_index` divergence and the Phase 2 retraction were the same
mistake seen twice: a probe hand-rolls its own state dict, `graph.invoke` accepts
it, and the run measures an engine the product does not ship. Nothing failed.
The benchmark harness omitted `structural_index` and three modules silently read
an empty one; `probe_mis_governance` omitted `verdict_space` and
`governance_directive`, so it measured coverage space with a framed query while
`check_conformance` ships ruling space with a directive beside it.

Both looked authoritative — real corpora, real models, real numbers — and both
were pointed at the wrong engine. A hand-rolled dict cannot fail this way once;
it fails this way every time a field is added.

So: anything under `examples/` or `scripts/` that invokes the engine must either
use `engine_state.build_initial_state`, or appear in `HAND_ROLLED_STATE` below.
The allowlist is the point — it turns silent drift into a listed, dated debt, and
a NEW probe cannot join it by accident.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

#: Probes known to hand-roll state, with what that costs them. Their historical
#: numbers describe whatever engine shape existed when they were written, so
#: those numbers are not citable as product behaviour without a re-run.
#:
#: Shrinking this list is the work. Adding to it needs a reason in writing.
HAND_ROLLED_STATE: dict[str, str] = {
    "examples/credential-governance/dump_evidence_packets.py": "packet dump",
    "examples/hexagonal-orders/run_discovery_path_probe.py": "discovery-path probe",
    "examples/policy-operations/probe_empty_packet.py": "empty-packet probe",
    "examples/policy-operations/probe_false_governed.py": "false-GOVERNED probe",
    "examples/policy-operations/probe_framing_seam.py": "framing-seam probe",
    "examples/policy-operations/probe_predicate_identity.py": "predicate-identity probe",
    "examples/policy-operations/run_rung_three.py": "rung-three runner",
    "examples/policy-operations/rung_one_engine.py": "rung-one engine",
    "examples/policy-operations/rung_two_engine.py": "rung-two engine",
    "examples/tesco-returns/probe_pinned_predicates.py": "pinned-predicate probe",
    "examples/tesco-returns/probe_sustained_task.py": "sustained-task probe",
    "examples/tesco-returns/probe_tesco_generalization.py": "generalisation probe",
}

#: Building the SST graph is the precise signal. Matching `.invoke(` alone
#: catches every LangChain LLM call — `judge_corpus`, `gen_queries` and
#: `draft_rubrics` all invoke a model client and never touch engine state.
_BUILDS_ENGINE = re.compile(r"\bbuild_sst_graph\b")
_INVOKES = re.compile(r"\.invoke\s*\(")
_BUILDER = "build_initial_state"


def _engine_invokers() -> list[Path]:
    """Files that construct the SST graph AND invoke something."""
    out: list[Path] = []
    for folder in ("examples", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if _BUILDS_ENGINE.search(text) and _INVOKES.search(text):
                out.append(path)
    return out


def test_probes_use_the_one_state_builder_or_are_listed():
    offenders: list[str] = []
    for path in _engine_invokers():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _BUILDER in text or rel in HAND_ROLLED_STATE:
            continue
        offenders.append(rel)

    assert not offenders, (
        "these invoke the engine with hand-rolled state and are not on the "
        "allowlist — they will measure a different engine than the product the "
        "moment a state field is added. Use engine_state.build_initial_state, "
        "or add them to HAND_ROLLED_STATE with a reason:\n  "
        + "\n  ".join(offenders)
    )




