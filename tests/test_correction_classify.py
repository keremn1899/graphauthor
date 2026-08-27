"""The mechanical floor under a correction acknowledgement.

Two halves. The first replays the eleven frozen reports from the overnight
characterization — a real, paid measurement, replayed here for free — and asks
how much of it a mechanism can dispose of without any interpreter. The second is
the arm that corpus never had: corrections that *should* be refused. Every case
in the overnight run was the same benign stimulus, so on its own it can only
ever confirm.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.correction_classify import (
    CARDINAL, INTENT_RESTATE, INTENT_WITHDRAW_FORCE, OTHER, UNEVALUABLE,
    WITHDRAWAL_LOCAL, WITHDRAWAL_SPREADING, classify_moves, dispose_report,
    permitted,
)

CORPUS = Path(__file__).parent / "fixtures" / "correction_gate_replay_v1.json"


@pytest.fixture(scope="module")
def corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _dispose(case: dict, intent: str = INTENT_WITHDRAW_FORCE) -> dict:
    report = {"ran": True, "reason": case["gate_reason"], "changed": case["changed"]}
    return dispose_report(report, [case["node_id"]], case["antecedents"], intent=intent)


# --------------------------------------------------------------------------
# Replay: what the mechanism disposes of on real measured reports
# --------------------------------------------------------------------------

def test_the_corpus_is_the_whole_overnight_run(corpus):
    """A shrunken corpus would quietly raise every rate below it."""
    assert len(corpus["cases"]) == 11


def test_no_cardinal_flip_is_ever_auto_accepted(corpus):
    """The one property the whole design rests on.

    A move toward GOVERNED launders authority into the graph. No intent, and no
    interpreter, may license one inline. Overnight this fired on 2 of 11.
    """
    seen = 0
    for case in corpus["cases"]:
        result = _dispose(case)
        for predicate in case["cardinal_flips"]:
            seen += 1
            assert result["classes"][predicate] == CARDINAL
            assert predicate not in result["auto_accepted"]
            assert predicate not in result["interpretable"]
    assert seen == 3, "the corpus carries three cardinal flips across two cases"


def test_most_of_the_run_needs_no_interpreter_at_all(corpus):
    """The answer the 82% headline obscured.

    The findings file read "9 of 11 moved an undeclared verdict" as a blanket
    refusal on governing corrections. But coverage loss on the rule you just
    neutralised is the *intended* effect of that stimulus, and so is coverage
    loss on the antecedents that only reached governance through it. Once intent
    is declared before the gate runs, the majority disposes of itself.
    """
    tally: dict[str, int] = {}
    for case in corpus["cases"]:
        tally[_dispose(case)["disposition"]] = tally.get(
            _dispose(case)["disposition"], 0) + 1
    assert tally == {"clears": 6, "escalate": 2, "interpret": 2, "refused": 1}


def test_the_interpreter_surface_is_one_predicate_per_case(corpus):
    """What is actually left for an agent or a human to judge.

    Note the third entry: an escalating case can still carry an interpretable
    move alongside its cardinal one. The case escalates regardless — a cardinal
    flip is not offset by anything else in the report.
    """
    interpretable = {c["node_id"]: _dispose(c)["interpretable"]
                     for c in corpus["cases"]}
    outstanding = {k: v for k, v in interpretable.items() if v}
    assert outstanding == {
        "decision_current_abstract_set_structures_to_frozenset": ["migration_status_layer"],
        "decision_current_serializer_behavior_lives_in_preconf": ["cattrs_architecture"],
        "decision_current_converter_is_rule_registry": ["converter_registry"],
    }
    assert all(len(v) == 1 for v in outstanding.values())
    assert _dispose(next(c for c in corpus["cases"]
                         if c["node_id"] == "decision_current_converter_is_rule_registry")
                    )["disposition"] == "escalate"


def test_spreading_loss_is_not_treated_as_local(corpus):
    """Losing a container's coverage is blast radius, not the stated intent."""
    case = next(c for c in corpus["cases"]
                if c["node_id"] == "decision_current_serializer_behavior_lives_in_preconf")
    result = _dispose(case)
    assert result["classes"]["cattrs_architecture"] == WITHDRAWAL_SPREADING
    assert result["classes"][case["node_id"]] == WITHDRAWAL_LOCAL


def test_antecedents_clear_because_their_authority_ran_through_the_target(corpus):
    """A superseded decision reads as governed only via its successor."""
    case = next(c for c in corpus["cases"]
                if c["node_id"] == "decision_current_sequence_structures_to_tuple")
    assert case["antecedents"] == ["decision_superseded_sequence_structures_to_list"]
    assert _dispose(case)["disposition"] == "clears"


# --------------------------------------------------------------------------
# The arm the overnight corpus never had
# --------------------------------------------------------------------------

def test_a_restate_intent_accepts_nothing_that_moved(corpus):
    """Intent narrows what is acceptable; it cannot widen it.

    Rewording a rule without changing it should move no verdict. If one moves,
    the correction did something its author did not claim — so nothing is
    auto-acceptable under `restate`, whatever direction it went.
    """
    for case in corpus["cases"]:
        result = _dispose(case, intent=INTENT_RESTATE)
        assert result["auto_accepted"] == []
        if case["changed"]:
            assert result["disposition"] != "clears"


def test_an_interpreter_cannot_wave_through_a_cardinal_flip():
    """The invariant that makes the acknowledger's species a config choice.

    A weak interpreter must cost needless escalations, never a laundered rule.
    """
    changed = {"target": ["GOVERNED", "UNGOVERNED"],
               "elsewhere": ["UNGOVERNED", "GOVERNED"]}
    classification = classify_moves(changed, ["target"], intent=INTENT_WITHDRAW_FORCE)
    outcome = permitted(classification, ["target", "elsewhere"])
    assert outcome["refused_overreach"] == ["elsewhere"]
    assert outcome["outstanding"] == ["elsewhere"]
    assert outcome["commits"] is False


def test_promotion_from_absent_is_cardinal_too():
    """Laundering does not require an UNGOVERNED starting point."""
    result = classify_moves({"p": ["PARTIALLY_GOVERNED", "GOVERNED"]}, ["t"],
                            intent=INTENT_WITHDRAW_FORCE)
    assert result["classes"]["p"] == CARDINAL


def test_a_correction_that_governs_its_own_target_is_cardinal():
    """The smuggling case: a 'fix' that promotes the node it edits.

    Auto-accepting by identity rather than by direction would have passed this,
    which is why the corrected id is not a blanket exemption.
    """
    result = classify_moves({"target": ["UNGOVERNED", "GOVERNED"]}, ["target"],
                            intent=INTENT_WITHDRAW_FORCE)
    assert result["classes"]["target"] == CARDINAL
    assert result["auto_accepted"] == []


def test_an_unevaluable_probe_never_reads_as_clean():
    result = classify_moves({"p": ["GOVERNED", "ABSENT"]}, ["t"],
                            intent=INTENT_WITHDRAW_FORCE)
    assert result["classes"]["p"] == UNEVALUABLE
    assert result["clears_mechanically"] is False


def test_a_gate_refusal_without_a_comparison_is_not_a_pass():
    """`unevaluable_probe` and cap overflow return before any map exists.

    An empty `changed` classifies as "nothing moved" — so precedence, not
    classification, has to catch these. Without it a refusal reads as a clean
    pass, which is the silent-permission failure the cap already refuses over.
    """
    for reason in ("unevaluable_probe:some_node",
                   "region_exceeds_probe_cap",
                   "universe_exceeds_probe_cap",
                   "no_probes_available_for_governing_correction"):
        result = dispose_report({"ran": False, "reason": reason, "changed": {}},
                                ["t"], intent=INTENT_WITHDRAW_FORCE)
        assert result["disposition"] == "refused"
        assert result["compared"] is False
        assert result["clears_mechanically"] is False


def test_an_unknown_intent_refuses_rather_than_defaulting():
    """A typo in the intent must not silently pick the permissive reading."""
    with pytest.raises(ValueError):
        classify_moves({}, ["t"], intent="withdrawn")


def test_a_sideways_move_is_never_auto_accepted():
    result = classify_moves({"p": ["UNGOVERNED", "INSUFFICIENT_EVIDENCE"]}, ["p"],
                            intent=INTENT_WITHDRAW_FORCE)
    assert result["classes"]["p"] == OTHER
    assert result["auto_accepted"] == []


def test_a_suite_of_only_the_corrected_node_cannot_clear_itself():
    """Sparsity reaches the circularity that declaration-derived probes would.

    Region-derived probes exist so the gate checks somewhere the caller did not
    choose. On a graph thin enough, the region around a node IS just that node —
    measured, not hypothetical: 5 of 14 governing nodes on a Kubernetes KEP
    graph at 0.35 edges/node. The comparison then proves only that the edit did
    what the edit said, which is not a check.
    """
    report = {"ran": True, "reason": "", "changed": {"t": ["GOVERNED", "UNGOVERNED"]}}
    checked = dispose_report(report, ["t"], intent=INTENT_WITHDRAW_FORCE)
    assert checked["disposition"] == "clears"

    blind = dispose_report(report, ["t"], intent=INTENT_WITHDRAW_FORCE,
                           independent_probe=False)
    assert blind["disposition"] == "uncheckable"
    assert blind["clears_mechanically"] is False
    assert blind["auto_accepted"] == []
    # Still acknowledgeable — a thin graph must not make its own nodes
    # permanently uncorrectable, only uncertifiable without an affirmation.
    assert blind["interpretable"] == ["t"]


def test_an_uncheckable_correction_that_moved_nothing_still_needs_affirming():
    """"Nothing moved" from a gate that could not look is not evidence."""
    blind = dispose_report({"ran": True, "reason": "", "changed": {}}, ["t"],
                           intent=INTENT_WITHDRAW_FORCE, independent_probe=False)
    assert blind["disposition"] == "uncheckable"
    assert blind["clears_mechanically"] is False


def test_a_move_is_read_the_same_as_a_tuple_or_a_list():
    """The live gate emits tuples; the frozen corpus round-trips them as lists.

    Accepting only lists made every replay test pass while the real confirm path
    classified all movement as unevaluable — a corpus and a production path
    disagreeing about a container type, with the corpus reporting green.
    """
    as_list = classify_moves({"p": ["GOVERNED", "UNGOVERNED"]}, ["p"],
                             intent=INTENT_WITHDRAW_FORCE)
    as_tuple = classify_moves({"p": ("GOVERNED", "UNGOVERNED")}, ["p"],
                              intent=INTENT_WITHDRAW_FORCE)
    assert as_list["classes"] == as_tuple["classes"] == {"p": WITHDRAWAL_LOCAL}
    assert as_tuple["clears_mechanically"] is True


def test_a_malformed_move_is_unevaluable_not_clean():
    """Garbage in must not read as 'nothing moved'."""
    result = classify_moves({"p": "GOVERNED"}, ["p"], intent=INTENT_WITHDRAW_FORCE)
    assert result["classes"]["p"] == UNEVALUABLE
    assert result["clears_mechanically"] is False


def test_classification_needs_no_database_or_model():
    """Replay must stay free, or it will not be run on every change."""
    source = (Path(__file__).parent.parent / "mcp_server"
              / "correction_classify.py").read_text(encoding="utf-8")
    body = source.split("def antecedents_of")[0]
    for forbidden in ("real_ladybug", "requests", "openai", "httpx"):
        assert forbidden not in body


def test_the_gate_and_the_classifier_agree_on_what_laundering_is():
    """One definition, or the two halves drift.

    `edit_gate` names the cardinal case in its refusal string; the classifier
    decides what may never be auto-accepted. When those were written separately
    the gate's inline comparison missed PARTIALLY_GOVERNED -> GOVERNED, so an
    authority increase was reported as an ordinary verdict change.
    """
    from mcp_server.correction_classify import authority_increase

    for before, after in (("UNGOVERNED", "GOVERNED"),
                          ("PARTIALLY_GOVERNED", "GOVERNED"),
                          ("UNGOVERNED", "PARTIALLY_GOVERNED")):
        assert authority_increase(before, after) is True
        assert classify_moves({"p": [before, after]}, ["p"],
                              intent=INTENT_WITHDRAW_FORCE)["classes"]["p"] == CARDINAL
    for before, after in (("GOVERNED", "UNGOVERNED"),
                          ("GOVERNED", "PARTIALLY_GOVERNED"),
                          ("GOVERNED", "GOVERNED")):
        assert authority_increase(before, after) is False


def test_the_gate_names_a_partial_promotion_as_a_laundered_flip():
    from mcp_server.changeset import ChangeOp, ChangeSet, OpKind
    from mcp_server.edit_gate import evaluate_edit

    change_set = ChangeSet(base="m", operations=[ChangeOp(
        kind=OpKind.REPLACE_CONTENT, target_node_id="n", payload={"text": "x"})])
    verdicts = iter([{"p": "PARTIALLY_GOVERNED"}, {"p": "GOVERNED"}])
    decision = evaluate_edit(change_set, {"m": 1}, lambda _m: next(verdicts),
                             lambda m, _cs: m)

    assert decision["allowed"] is False
    assert decision["reason"] == "undeclared_governed_flip:p"
