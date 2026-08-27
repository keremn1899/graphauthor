"""Logs is a write record. Propose auto-commits; nothing opens demand.

Confirm, reject, requeue, and incident ack stay on leftover operator
HTTP/CLI paths. The live Logs surface must not grow those verbs back,
and the ledger must not reopen a human queue.
"""

from __future__ import annotations

import re
from pathlib import Path

LEDGER = Path("mcp_server/ledger.py")
LOGS = Path("frontend/src/product/LogsWorkspace.tsx")
SHELL = Path("frontend/src/product/ProductShell.tsx")

DISPOSITION_VERBS = (
    "confirmProposal",
    "rejectProposal",
    "requeueProposal",
    "acknowledgeIncident",
)


def _opened_demands() -> set[str]:
    return set(
        re.findall(
            r'open_actionable"\]\.append\(\{"on": "([a-z_]+)"', LEDGER.read_text()
        )
    )


def test_the_ledger_opens_no_demand():
    opened = _opened_demands()
    assert not opened, (
        f"the ledger can still open a human queue: {sorted(opened)}"
    )


def test_logs_does_not_confirm_or_reject():
    logs = LOGS.read_text()
    present = [name for name in DISPOSITION_VERBS if name in logs]
    assert not present, f"Logs grew disposition verbs: {present}"


def test_the_live_surface_is_logs():
    shell = SHELL.read_text()
    assert 'label: "Logs"' in shell
    assert 'href: "#/log?api=live"' in shell
    assert 'label: "Review"' not in shell
