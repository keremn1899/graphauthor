"""Operator CLI for queued proposals and recorded commits.

    python -m mcp_server.proposals_cli capabilities
    python -m mcp_server.proposals_cli list    <store.sqlite> [STATUS]
    python -m mcp_server.proposals_cli show    <store.sqlite> <proposal_id>
    python -m mcp_server.proposals_cli reject  <store.sqlite> <proposal_id> --reason "..."
    python -m mcp_server.proposals_cli requeue <store.sqlite> <proposal_id>
    python -m mcp_server.proposals_cli audit   <store.sqlite> [--since <version>]
    python -m mcp_server.proposals_cli confirm <db.lbug> <store.sqlite> <proposal_id> \
        [--gate-module <module>]

Green add-only proposes auto-commit through this same confirm path. What stays
queued — corrections, sourceless rows, graph.md review holds — is confirmed or
rejected here. Confirm does not take a primary source. License is a graph.md
harness beside the database, or ``--gate-module``. Revert is
``python -m mcp_server.history_cli revert``. Stop any server on this graph
first (one owner per Ladybug file).
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]

    from interaction.write_path_store import WritePathStore

    if cmd == "capabilities" and not rest:
        from mcp_server.operator_capabilities import operator_cli_capability_card

        print(json.dumps(operator_cli_capability_card(), indent=2))
        return 0

    if cmd == "list" and rest:
        store = WritePathStore(rest[0])
        for r in store.list_proposals(status=rest[1] if len(rest) > 1 else None):
            print(f"{r['proposal_id']}  {r['status']:<13} gap={r['target_gap_id'] or '-'}  task={r['generating_task'][:40]}")
        store.close()
        return 0

    if cmd == "show" and len(rest) == 2:
        store = WritePathStore(rest[0])
        rec = store.get_proposal(rest[1])
        store.close()
        print(json.dumps(rec, indent=2) if rec else f"unknown proposal: {rest[1]}")
        return 0 if rec else 1

    if cmd == "requeue" and len(rest) == 2:
        from mcp_server.proposals import requeue_proposal

        res = requeue_proposal(rest[0], rest[1])
        if "error" in res:
            print(res["error"])
            return 1
        print(json.dumps(res))
        return 0

    if cmd == "reject" and len(rest) >= 2:
        from mcp_server.proposals import reject_proposal

        reason = ""
        if "--reason" in rest:
            reason = rest[rest.index("--reason") + 1]
        print(json.dumps(reject_proposal(rest[0], rest[1], reason=reason)))
        return 0

    if cmd == "audit" and rest:
        store = WritePathStore(rest[0])
        try:
            since = rest[rest.index("--since") + 1] if "--since" in rest else ""
            rows = [r for r in store.list_proposals(status="COMMITTED")]
            if since:
                seen = False
                kept = []
                for r in rows:
                    if seen:
                        kept.append(r)
                    if since in (r["graph_version_before"], r["graph_version_after"]):
                        seen = True
                rows = kept if seen else rows
            for r in rows:
                print(f"{r['proposal_id']}  gap={r['target_gap_id'] or '-'}")
                print(f"    versions: {r['graph_version_before']} -> {r['graph_version_after']}")
                print(f"    revert:   python -m mcp_server.history_cli revert <db.lbug> "
                      f"'{r['graph_version_before']}'")
            print(f"({len(rows)} commit(s))")
            return 0
        finally:
            store.close()

    if cmd == "confirm" and len(rest) >= 3:
        db, store_path, pid = rest[0], rest[1], rest[2]
        gate = None
        if "--gate-module" in rest:
            mod = importlib.import_module(rest[rest.index("--gate-module") + 1])
            if hasattr(mod, "build_gate_for"):
                store = WritePathStore(store_path)
                try:
                    rec = store.get_proposal(pid)
                finally:
                    store.close()
                gate = mod.build_gate_for(Path(db), rec or {}, store_path=Path(store_path))
            else:
                gate = mod.build_gate(Path(db))
        from mcp_server.proposals import confirm_proposal

        embedder = None if gate is not None else (lambda _text: [0.0] * 3072)
        out = confirm_proposal(
            db, store_path, pid, gate=gate, embedder=embedder, actor="operator",
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("status") == "COMMITTED" else 1

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
