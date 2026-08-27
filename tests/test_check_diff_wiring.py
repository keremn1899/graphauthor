"""`check_conformance(diff=...)` must actually reach the gate.

The surface called `pr_gate_live(..., prior_diff_receipts=...)`; the function's
parameter is `prior_receipts`. Every call raised TypeError, was swallowed by the
surrounding `except Exception`, and came back as `INSUFFICIENT_EVIDENCE` with
`engine_fault:check_diff:TypeError`.

So the whole-change mode — the one `check_conformance`'s own description tells
an agent to prefer, and the only mode that can detect rationalization — has
never worked from the agent surface. `pr_gate_cli.py` passes the right keyword,
so CI worked and the agent path did not, which is why nothing caught it.

Found because a graph-arm run called it and the transcript recorded the fault.
"""

from __future__ import annotations

import inspect


def test_the_surface_calls_the_gate_with_parameters_it_has():
    from mcp_server.pr_gate import pr_gate_live
    from mcp_server.surface import Surface

    accepted = set(inspect.signature(pr_gate_live).parameters)
    # `check_conformance(diff=...)` delegates to `_check_diff`, which is where
    # the gate is actually called.
    source = inspect.getsource(Surface._check_diff)

    call = source.split("pr_gate_live(", 1)
    assert len(call) == 2, "_check_diff no longer calls pr_gate_live"
    passed = {part.split("=", 1)[0].strip()
              for part in call[1].split(")", 1)[0].split(",")
              if "=" in part}

    unknown = passed - accepted
    assert not unknown, (
        f"_check_diff passes {sorted(unknown)} which pr_gate_live does not "
        f"accept; it accepts {sorted(accepted)}. The surrounding except-clause "
        "turns this into INSUFFICIENT_EVIDENCE rather than a crash, so it fails "
        "silently.")


def test_the_cli_and_the_surface_agree():
    """Both paths must reach the same computation, or an agent and CI can rule
    differently on one diff — which is the property check_conformance exists to
    guarantee."""
    from mcp_server import pr_gate_cli
    from mcp_server.pr_gate import pr_gate_live

    accepted = set(inspect.signature(pr_gate_live).parameters)
    cli = inspect.getsource(pr_gate_cli).split("pr_gate_live(", 1)[1].split(")", 1)[0]
    passed = {part.split("=", 1)[0].strip() for part in cli.split(",") if "=" in part}

    assert not passed - accepted, f"pr_gate_cli passes unknown: {sorted(passed - accepted)}"
