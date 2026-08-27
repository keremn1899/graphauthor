"""Operator CLI for graph history — the ONLY revert path (never an MCP tool).

    python -m mcp_server.history_cli capabilities
    python -m mcp_server.history_cli versions <db.lbug>
    python -m mcp_server.history_cli revert   <db.lbug> <graph_version>

Revert swaps the snapshot copy back over the live path and drops the stale
structural-index sidecar; any running server must be restarted (single-owner
DB). Agents propose forward; operators move backward.
"""

from __future__ import annotations

import interaction.event_types as event_types
import json
import sys
import uuid
from pathlib import Path


def revert(
    db_path: Path | str,
    graph_version: str,
    *,
    store_path: Path | str | None = None,
    actor: str = "operator",
) -> Path:
    """Restore a recorded version and append the corresponding graph incident.

    The append is required. If it fails, the just-restored graph is compensated
    back to its captured pre-revert state rather than leaving a silent mutation.
    """
    from graph_read import graph_version as file_graph_version
    from interaction.event_log import emit_event
    from mcp_server.history import SnapshotStore

    db = Path(db_path)
    snapshots = SnapshotStore(db)
    before = f"gv_{file_graph_version(db)}"
    snapshots.capture(before)
    delta = snapshots.diff(before, graph_version)
    if "error" in delta:
        raise FileNotFoundError(delta["error"])
    subjects = {
        str(row["id"])
        for key in ("concepts_added", "concepts_removed", "concepts_changed")
        for row in delta.get(key, [])
    }
    for key in ("edges_added", "edges_removed"):
        for edge in delta.get(key, []):
            if len(edge) >= 3:
                subjects.update((str(edge[1]), str(edge[2])))

    restored = snapshots.restore(graph_version)
    try:
        emit_event(
            Path(store_path) if store_path is not None else db.with_suffix(".store.sqlite"),
            required=True,
            type=event_types.GRAPH_REVERTED,
            case_id=f"revert_{uuid.uuid4().hex[:12]}",
            actor=actor,
            authority_type="human",
            graph_version_before=before,
            graph_version_after=graph_version,
            subject_node_ids=sorted(subjects),
            reason=f"operator restored {graph_version}",
            payload={"target_graph_version": graph_version},
        )
    except Exception:
        snapshots.restore(before)
        raise
    return restored


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]
    if cmd == "capabilities" and not rest:
        from mcp_server.operator_capabilities import operator_cli_capability_card

        print(json.dumps(operator_cli_capability_card(), indent=2))
        return 0
    if cmd == "versions" and len(rest) == 1:
        from mcp_server.history import SnapshotStore

        for v in SnapshotStore(rest[0]).versions():
            print(f"{v['graph_version']}  concepts={v['concept_count']} edges={v['edge_count']}")
        return 0
    if cmd == "revert" and len(rest) == 2:
        path = revert(rest[0], rest[1])
        print(f"restored {path} to version {rest[1]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
