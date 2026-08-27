from __future__ import annotations

import copy
import json
from pathlib import Path

from benchmarks.proposal_host.publication_feedback import publication_feedback


ROOT = Path(__file__).resolve().parents[1]
BATTERY = ROOT / "results/host_proposal_context_graph/software_write_battery_v1"


def _change_set(case_id: str) -> dict:
    return json.loads(
        (BATTERY / f"cases/{case_id}/change-set.json").read_text(encoding="utf-8")
    )


def test_saved_new_decision_exposes_both_workflow_state_leaks():
    result = publication_feedback(
        _change_set("new_owner_decision"), decision_origin="propose_new"
    )

    assert result["error_code"] == "PUBLICATION_PROJECTION_FAILED"
    assert {row["code"] for row in result["findings"]} == {
        "workflow_state_in_identity",
        "workflow_state_in_content",
    }
    assert result["authority_changed"] is False


def test_stable_post_confirm_draft_passes_without_gaining_authority():
    raw = copy.deepcopy(_change_set("new_owner_decision"))
    concept = raw["operations"][0]["concept"]
    old_id = concept["id"]
    new_id = "decision_current_async_hooks_remain_synchronous_v1"
    concept["id"] = new_id
    concept["label"] = "current:async-hooks-remain-synchronous-v1"
    concept["text_content"] = (
        "For the current Converter API, structure and unstructure hooks must "
        "remain synchronous. Async hooks are not admitted until a separate "
        "design defines cache, dispatch, cancellation, and error semantics."
    )
    raw["operations"][1]["edge"]["target_id"] = new_id
    assert old_id != new_id

    result = publication_feedback(raw, decision_origin="propose_new")

    assert result == {
        "kind": "VALID",
        "findings": [],
        "authority_changed": False,
    }


def test_domain_historical_status_is_not_mistaken_for_queue_state():
    result = publication_feedback(
        _change_set("historical_recovery"), decision_origin="recover_existing"
    )

    assert result["kind"] == "VALID"
    assert result["findings"] == []
