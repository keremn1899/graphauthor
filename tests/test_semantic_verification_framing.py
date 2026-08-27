"""Deterministic tests for semantic verification framing templates."""

from __future__ import annotations

from conformance_check.framing import (
    frame_existing_code_question,
    frame_insufficient_question,
    frame_proposed_change_question,
    frame_scope_moat_question,
)


def test_scope_moat_suffix_demands_ungoverned():
    q = frame_scope_moat_question("must X use Y?")
    assert "UNGOVERNED" in q
    assert "do not invent" in q.lower()


def test_insufficient_suffix_forbids_guessing():
    q = frame_insufficient_question("can you determine conformance?")
    assert "INSUFFICIENT" in q
    assert "do not guess" in q.lower()


def test_existing_code_prefix():
    q = frame_existing_code_question(
        "PacketImmutabilityRule",
        "backend_tools.py",
        "does append_to_evidence_packet conform?",
    )
    assert "Existing code" in q
    assert "backend_tools.py" in q


def test_proposed_change_prefix():
    q = frame_proposed_change_question(
        "PacketImmutabilityRule",
        "battalion.py",
        "may battalion append to the packet?",
    )
    assert "Proposed change" in q
    assert "battalion.py" in q
