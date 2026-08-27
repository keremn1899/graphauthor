"""CLI entry — ``graphauthor`` dispatches product subcommands; legacy flags stay intact.

  graphauthor gate …     → mcp_server.pr_gate_cli (PR / CI packaging)
  graphauthor --scan …   → conformance_check (existing handbook scan)
  graphauthor --list-rules …

Legacy console scripts ``aporta`` and ``cke`` still point here.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_imports() -> None:
    """Editable installs must include ``mcp_server``; if a stale shim is on
    PATH, fall back to the repo root beside this file."""
    try:
        import mcp_server  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    root = Path(__file__).resolve().parent.parent
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "gate":
        _ensure_repo_imports()
        from mcp_server.pr_gate_cli import main as gate_main

        return gate_main(args[1:])

    from conformance_check.__main__ import main as conformance_main

    return conformance_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
