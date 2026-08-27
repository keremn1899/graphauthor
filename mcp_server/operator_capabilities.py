"""Closed capability contract for the trusted operator-host CLIs."""

from __future__ import annotations

from copy import deepcopy


OPERATOR_CLI_CONTRACT_VERSION = "operator-cli-v2"

_CARD = {
    "contract_version": OPERATOR_CLI_CONTRACT_VERSION,
    "plane": "operator_host",
    "proposal_cli": {
        "commands": {
            "capabilities": {"effect": "read"},
            "list": {"effect": "read"},
            "show": {"effect": "read"},
            "audit": {"effect": "read"},
            "reject": {"effect": "proposal_disposition", "authority": "human"},
            "requeue": {"effect": "proposal_disposition", "authority": "human"},
            "confirm": {
                "effect": "licensed_graph_commit",
                "authority": "human",
                "requires": ["graph_md_harness_or_gate_battery"],
            },
        },
        "cannot": ["propose", "escalate", "direct_encode", "revert"],
    },
    "history_cli": {
        "commands": {
            "capabilities": {"effect": "read"},
            "versions": {"effect": "read"},
            "revert": {
                "effect": "snapshot_restore",
                "authority": "human",
                "requires": ["recorded_snapshot", "required_event_append"],
            },
        },
        "cannot": ["propose", "confirm", "direct_encode"],
    },
    "invariants": [
        "no_harness_or_gate_no_commit",
        "agents_propose_forward_operators_revert",
        "all_graph_mutations_append_causal_events",
    ],
}


def operator_cli_capability_card() -> dict:
    """Return a caller-mutable copy of the frozen operator-host contract."""
    return deepcopy(_CARD)
