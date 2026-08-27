"""Tests for scope-note guard — generalized property triggers."""

from battalion import _apply_scope_note_guard
from governance_scope import (
    apply_scope_note_guard,
    is_scope_note_node,
    scope_note_guard_applies,
)


def test_scope_note_guard_overrides_false_governed():
    gov = {"governance_verdict": "GOVERNED", "ungoverned_predicate": ""}
    query = (
        "Click+Collect was fine but I waited 40 minutes. "
        "Can Tesco offer a goodwill voucher for the inconvenience?"
    )
    nodes = [
        {
            "id": "t27_click_collect_basics",
            "label": "T27 — Click+Collect collection",
            "text_content": "This page does not offer goodwill vouchers for car-park wait time.",
        }
    ]
    out = _apply_scope_note_guard(gov, query, nodes)
    assert out["governance_verdict"] == "UNGOVERNED"
    assert "goodwill" in out["ungoverned_predicate"]


def test_scope_note_guard_second_node_not_t27():
    """Generality — fires on scope-note property, not T27 ID."""
    gov = {"governance_verdict": "GOVERNED", "ungoverned_predicate": ""}
    query = "Can Tesco offer a goodwill voucher for wait inconvenience?"
    nodes = [
        {
            "id": "policy_delivery_hub_scope_note",
            "label": "Delivery hub",
            "text_content": "This page describes routing only. It does not offer goodwill vouchers.",
        }
    ]
    assert is_scope_note_node(nodes[0])
    out, fired = apply_scope_note_guard(gov, query, nodes)
    assert fired
    assert out["governance_verdict"] == "UNGOVERNED"


def test_scope_note_guard_no_t27_id_without_text():
    """Without scope-note text, empty label+id alone must NOT fire."""
    gov = {"governance_verdict": "GOVERNED", "ungoverned_predicate": ""}
    query = "Can Tesco offer a goodwill voucher for Click+Collect wait inconvenience?"
    nodes = [{"id": "t27_click_collect_basics", "label": "T27", "text_content": ""}]
    would, _ = scope_note_guard_applies(gov, query, nodes)
    assert not would


def test_scope_note_guard_leaves_adjudicative_deny():
    gov = {"governance_verdict": "GOVERNED", "ungoverned_predicate": ""}
    query = "Can I return an opened DVD for a refund?"
    nodes = [
        {
            "label": "T15 — Home entertainment",
            "text_content": "Unsealed DVDs cannot be returned for change of mind.",
        }
    ]
    out = _apply_scope_note_guard(gov, query, nodes)
    assert out["governance_verdict"] == "GOVERNED"


def test_scope_note_guard_named_predicate_skips_adj1_shape():
    gov = {
        "governance_verdict": "GOVERNED",
        "ungoverned_predicate": "change-of-mind return of general merchandise",
    }
    query = (
        "I bought a Christmas decoration. Is my return governed by Tesco's "
        "returns policy or not?"
    )
    nodes = [{"label": "T01", "text_content": "This page does not offer goodwill vouchers."}]
    would, reason = scope_note_guard_applies(gov, query, nodes)
    assert not would
    assert reason == "named_predicate"
