"""List recorded proposes. Revert is ``python -m mcp_server.history_cli revert``.

    python -m mcp_server.proposals_cli capabilities
    python -m mcp_server.proposals_cli list    <store.sqlite> [STATUS]
    python -m mcp_server.proposals_cli show    <store.sqlite> <proposal_id>
    python -m mcp_server.proposals_cli audit   <store.sqlite> [--since <version>]
"""

from __future__ import annotations

import json
import sys


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

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
