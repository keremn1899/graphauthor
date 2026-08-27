"""What the agent is told before it acts, and what it carries away after.

Three gaps closed together, because they are one idea: the system specified what
an agent MAY do and never what it should KNOW.

- **posture** — the operator's intent had no home, so it lived in a system
  prompt outside anything the product could see or audit. Fragments of it were
  enforced as runtime errors, meaning agents discovered policy by failing.
- **dry_run** — the gate runs at operator confirm, so a bad encoding cost a
  human their scarcest action before the agent learned anything.
- **receipts** — `positioning.md` claims every verdict carries one. That was
  true of the CI path and not of the surface agents actually use.

Deterministic: no LLM, no network.
"""

from __future__ import annotations

import pytest

from mcp_server.account import Account


# ------------------------------------------------------------------- posture


def test_posture_is_always_complete(tmp_path):
    """An agent must never have to guess what an unset posture means."""
    posture = Account(tmp_path).posture()
    assert posture["on_ungoverned"] == "escalate"
    assert posture["on_insufficient_evidence"] == "stop"
    assert posture["max_claim_level"] == "L0"


def test_posture_survives_a_partial_write(tmp_path):
    account = Account(tmp_path)
    account.set_posture(on_ungoverned="propose")
    posture = account.posture()
    assert posture["on_ungoverned"] == "propose"
    assert posture["on_insufficient_evidence"] == "stop"  # untouched default


def test_a_typo_is_refused_rather_than_stored(tmp_path):
    """Silently storing an unknown field would leave the operator believing
    they had set a policy that nothing reads."""
    account = Account(tmp_path)
    with pytest.raises(ValueError):
        account.set_posture(on_ungoverned="yolo")
    with pytest.raises(ValueError):
        account.set_posture(on_unicorn="escalate")
    with pytest.raises(ValueError):
        account.set_posture(max_claim_level="L9")
    assert account.posture()["on_ungoverned"] == "escalate"


def test_posture_is_not_stored_in_the_graph(tmp_path):
    """Operator configuration is not graph content: it changes without the
    graph changing, and it must not move topology_version or a receipt."""
    Account(tmp_path).set_posture(on_ungoverned="propose")
    assert (tmp_path / "account.json").exists()
    assert not list(tmp_path.glob("*.lbug"))


def test_the_cli_can_author_posture(tmp_path):
    from mcp_server.posture_cli import main

    assert main(["set", str(tmp_path), "--on-ungoverned", "propose"]) == 0
    assert Account(tmp_path).posture()["on_ungoverned"] == "propose"
    assert main(["set", str(tmp_path), "--on-ungoverned", "nonsense"]) == 1
    assert main(["show", str(tmp_path)]) == 0


# ------------------------------------------------------------------ receipts


def _receipt(**over):
    base = {"rule_id": "r1", "artifact_path": "a.py", "verdict": "CONFORMS",
            "diff_hash": "abc123", "graph_version": "v1",
            "issued_at": "2026-07-28T00:00:00Z"}
    base.update(over)
    return base


def test_a_receipt_dies_when_the_graph_moves_under_it():
    """`graph_changed` is the anti-rationalization signal: governance moved
    under code that was already checked, so the ruling must not be trusted."""
    from mcp_server.pr_gate import receipt_status

    same = receipt_status(_receipt(), current_diff_hash="abc123",
                          current_graph_version="v1")
    assert same == {"valid": True, "stale_reason": ""}

    moved = receipt_status(_receipt(), current_diff_hash="abc123",
                           current_graph_version="v2")
    assert moved["valid"] is False and moved["stale_reason"] == "graph_changed"

    edited = receipt_status(_receipt(), current_diff_hash="zzz",
                            current_graph_version="v1")
    assert edited["valid"] is False and edited["stale_reason"] == "diff_changed"


def test_mcp_and_ci_issue_the_same_receipt_shape():
    """One shape both ways, so a receipt issued by an agent can be revalidated
    in CI and vice versa."""
    from mcp_server.pr_gate import make_receipt

    receipt = make_receipt(rule_id="r1", artifact_path="a.py",
                           verdict="VIOLATES", dhash="d1", graph_version="v1")
    assert set(receipt) == {"rule_id", "artifact_path", "verdict", "diff_hash",
                            "graph_version", "issued_at"}


# ------------------------------------------------------------------- dry run


def test_the_propose_tool_offers_a_dry_run():
    """The preflight has to be discoverable from the schema, or agents will
    keep spending human confirms to find their own mistakes."""
    from mcp_server.stdio import TOOLS

    tool = next(t for t in TOOLS if t.name == "propose")
    assert "dry_run" in tool.inputSchema["properties"]
    assert "dry_run" in str(tool.description)


def test_orient_advertises_posture():
    from mcp_server.stdio import TOOLS

    tool = next(t for t in TOOLS if t.name == "orient")
    assert "posture" in str(tool.description)


# ------------------------------------------------------- dry-run grain gate


def _graph_with_grain(tmp_path):
    """Built here rather than copied from `data/construction_runs/`, which is a
    gitignored build output — these two tests were green only on a machine that
    had run a construction, and skipped silently everywhere else."""
    from tests.graph_fixtures import graph_with_grain

    return graph_with_grain(tmp_path)


def _surface(tmp_path):
    from mcp_server.surface import Surface

    return Surface(_graph_with_grain(tmp_path),
                   store_path=tmp_path / "store.sqlite", enable_proposals=True)


def _concept(cid, text):
    return {"concepts": [{"id": cid, "label": cid, "text_content": text}],
            "edges": []}






