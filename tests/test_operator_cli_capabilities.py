from __future__ import annotations

import json
import shutil

from interaction.write_path_store import WritePathStore
from mcp_server.fixture import ensure_fixture
from mcp_server.history import extract_manifest
from mcp_server.history_cli import main as history_cli
from mcp_server.operator_capabilities import operator_cli_capability_card
from mcp_server.proposals_cli import main as proposals_cli
from mcp_server.surface import Surface


def _pending_world(tmp_path):
    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import new_proposal_id, validate_proposal

    db = tmp_path / "graph.lbug"
    store = tmp_path / "store.sqlite"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    encoding = {
        "concepts": [{
            "id": "retry_rule",
            "label": "Retry Rule",
            "text_content": "Retries require a project-approved policy.",
            "semantic_anchor": "retry governance",
        }],
        "edges": [{
            "type": "CONTAINS",
            "source_id": "order_service",
            "target_id": "retry_rule",
            "label": "declares",
        }],
    }
    prop, err = validate_proposal(encoding, db)
    assert prop is not None, err
    pid = new_proposal_id()
    records = WritePathStore(store)
    try:
        records.save_proposal({
            "proposal_id": pid,
            "target_gap_id": "retry_policy_gap",
            "encoding_json": json.dumps(prop.model_dump()),
            "generating_task": "operator CLI boundary test",
            "source_refs": [],
            "expected_graph_version": "basis",
            "expected_graph_fingerprint": graph_fingerprint(db),
            "status": "PENDING",
        })
    finally:
        records.close()
    return db, store, pid


def test_operator_cli_capability_greenlist_is_closed_and_harm_shaped() -> None:
    card = operator_cli_capability_card()

    assert set(card["proposal_cli"]["commands"]) == {
        "capabilities", "list", "show", "audit", "reject", "requeue",
        "confirm",
    }
    assert card["proposal_cli"]["commands"]["confirm"]["requires"] == [
        "graph_md_harness_or_gate_battery"
    ]
    assert set(card["proposal_cli"]["cannot"]) == {
        "propose", "escalate", "direct_encode", "revert"
    }
    assert set(card["history_cli"]["commands"]) == {
        "capabilities", "versions", "revert"
    }
    assert card["invariants"] == [
        "no_harness_or_gate_no_commit",
        "agents_propose_forward_operators_revert",
        "all_graph_mutations_append_causal_events",
    ]


def test_both_operator_clis_emit_the_same_capability_contract(capsys) -> None:
    assert proposals_cli(["capabilities"]) == 0
    proposal_card = json.loads(capsys.readouterr().out)
    assert history_cli(["capabilities"]) == 0
    history_card = json.loads(capsys.readouterr().out)

    assert proposal_card == history_card == operator_cli_capability_card()


def test_cli_confirm_without_a_battery_still_commits(tmp_path, capsys) -> None:
    db, store, proposal_id = _pending_world(tmp_path)

    status = proposals_cli([
        "confirm", str(db), str(store), proposal_id,
    ])

    assert status == 0
    records = WritePathStore(store)
    try:
        assert records.get_proposal(proposal_id)["status"] == "COMMITTED"
    finally:
        records.close()


def test_cli_namespaces_do_not_smuggle_each_others_mutations(
    tmp_path, capsys
) -> None:
    db, store, proposal_id = _pending_world(tmp_path)
    before = extract_manifest(db)

    assert proposals_cli(["revert", str(db), "some-version"]) == 2
    capsys.readouterr()
    assert history_cli(["confirm", str(db), str(store), proposal_id]) == 2
    capsys.readouterr()
    assert extract_manifest(db) == before


def test_cli_dropped_review_era_commands() -> None:
    assert proposals_cli(["confirm-batch"]) == 2
    assert proposals_cli(["confirm-batch", "db", "store", "pid"]) == 2
