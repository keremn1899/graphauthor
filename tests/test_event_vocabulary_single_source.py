"""One definition of the event vocabulary. Emitters build from it; consumers
match against it; a raw literal anywhere else fails here.

The live set is the published graph: a proposal that became a version, and
an operator restore of an earlier version.
"""

from __future__ import annotations

import re
from pathlib import Path

import interaction.event_types as ev

ROOT = Path(__file__).resolve().parent.parent

#: Where the vocabulary is allowed to appear as literal text.
_DEFINITION = "interaction/event_types.py"

#: Not shipping code. Historical probes record what was run at the time and are
#: not rewritten; tests construct events deliberately.
_EXEMPT = ("tests/", "examples/", "archive/", "scratch/", "scripts/", "demo/",
           "benchmarks/", "build/", "dist/")

#: An event-type-shaped string: `family.action` optionally `:member`.
_EVENT_LITERAL = re.compile(r'"([a-z_]+\.[a-z_]+(?::[A-Za-z_]+)?)"')

#: Dotted strings that are not event types.
_NOT_EVENTS = re.compile(
    r"^[a-z_]+\.(py|json|lbug|md|yaml|yml|sqlite|txt|idx|enc|secret)$")


def _production_files():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == _DEFINITION or rel.startswith(_EXEMPT):
            continue
        yield rel, path.read_text(encoding="utf-8")


def test_no_module_hardcodes_an_event_type():
    """The structural check. A literal here means a second definition, which is
    how every one of the four defects became possible."""
    offenders: dict[str, set[str]] = {}
    known = ev.all_event_types()
    families = {ev.family(t) for t in known}

    for rel, text in _production_files():
        for literal in _EVENT_LITERAL.findall(text):
            if _NOT_EVENTS.match(literal):
                continue
            if literal in known or ev.family(literal) in families:
                offenders.setdefault(rel, set()).add(literal)

    assert not offenders, (
        "event types are hardcoded outside interaction/event_types.py:\n"
        + "\n".join(f"  {f}: {sorted(v)}" for f, v in sorted(offenders.items()))
        + "\nImport the constant or call the builder instead.")


def test_every_family_has_a_builder_or_a_constant():
    """A family with neither is a family somebody will spell by hand."""
    for event_type in ev.all_event_types():
        assert ev.family(event_type), f"{event_type} has no family"
        assert "." in event_type, f"{event_type} is not a dotted event type"


def test_the_live_set_is_committed_and_reverted():
    assert ev.all_event_types() == {ev.GRAPH_COMMITTED, ev.GRAPH_REVERTED}


def test_family_and_member_round_trip():
    assert ev.family(ev.GRAPH_COMMITTED) == "graph"
    assert ev.member(ev.GRAPH_COMMITTED) == ""
    assert ev.family("graph.reverted:prior") == "graph"
    assert ev.member("graph.reverted:prior") == "prior"
