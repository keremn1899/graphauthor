"""The event vocabulary, defined once.

Emitters construct from here, consumers match against here, and a raw
event-type literal outside this module is a test failure.

The live set is the published graph: a proposal that became a version, and
an operator restore of an earlier version. Propose auto-commits; there is
no human approval event, no gate event, and no proposal-queue event.
"""

from __future__ import annotations

# ---------------------------------------------------------------- prefixes
#
# The part before the colon. Consumers that match a family rather than a member
# use these, so a new member never needs a consumer change.

GRAPH = "graph"


# ------------------------------------------------------------ simple types

GRAPH_COMMITTED = f"{GRAPH}.committed"
GRAPH_REVERTED = f"{GRAPH}.reverted"


# ----------------------------------------------------------------- helpers


def family(event_type: str) -> str:
    """The prefix of an event type — `graph.committed` → `graph`."""
    return str(event_type or "").split(".", 1)[0]


def member(event_type: str) -> str:
    """The part after the colon, or "" when the type has no member."""
    _, _, suffix = str(event_type or "").partition(":")
    return suffix


def all_event_types() -> set[str]:
    """Every type this vocabulary can produce."""
    return {GRAPH_COMMITTED, GRAPH_REVERTED}
