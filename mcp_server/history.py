"""History for one graph: snapshots, content-based diff, operator revert.

Contract §2.7. Two artifacts per snapshot, both under ``<db>.snapshots/``:

- ``<key>.manifest.json`` — structural manifest: every Concept as
  ``id → {label, content_sha}`` and every edge as ``[type, src, tgt, label]``.
  Diffs are computed from manifests ONLY — content-based, never from version
  strings (graph_version is mtime-sensitive; a `touch` must diff empty).
- ``<key>.lbug`` — full DB copy, used exclusively by the operator revert CLI.

Agents get versions / diff / changed_since. Revert never ships as an MCP
tool: agents propose forward, operators move backward.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

import real_ladybug as lb

from mcp_server.fault import operator_fault


def _key(version: str) -> str:
    return hashlib.sha1(version.encode()).hexdigest()[:16]


def extract_manifest(db_path: Path | str) -> dict[str, Any]:
    """Read the full structural state of a graph.

    Reuses this process's owned connection when it already holds the file.
    Otherwise takes the owner lock so a second process cannot rewrite it
    mid-read.
    """
    import engine as engine_mod

    path = Path(db_path).resolve()

    def _from_conn(conn) -> dict[str, Any]:
        concepts: dict[str, dict[str, str]] = {}
        res = conn.execute(
            "MATCH (c:Concept) RETURN c.id, c.label, c.text_content, c.semantic_anchor"
        )
        while res.has_next():
            cid, label, tc, anchor = res.get_next()
            sha = hashlib.sha256(
                (str(tc or "") + "\x00" + str(anchor or "")).encode()
            ).hexdigest()[:16]
            concepts[str(cid)] = {"label": str(label or ""), "content_sha": sha}

        edges: list[list[str]] = []
        for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
            res = conn.execute(
                f"MATCH (a:Concept)-[r:{rel}]->(b:Concept) RETURN a.id, b.id, r.label"
            )
            while res.has_next():
                src, tgt, lbl = res.get_next()
                edges.append([rel, str(src), str(tgt), str(lbl or "")])
        edges.sort()
        return {"concepts": concepts, "edges": edges}

    if engine_mod.this_process_owns_graph(path) and engine_mod._connection is not None:
        return _from_conn(engine_mod._connection)

    with engine_mod.graph_owner_lock(path):
        db = lb.Database(str(path))
        conn = lb.Connection(db)
        try:
            return _from_conn(conn)
        finally:
            del conn, db


def graph_fingerprint(db_path: Path | str) -> str:
    """Full-strength global identity for proposal authoring dependencies.

    Delegates to `engine.fingerprint_connection`. If this process already owns
    the graph, reuse that connection — a second ``Database()`` on a live Ladybug
    file rewrites it, and Review confirm then disagrees with the MCP check that
    queued the proposal.

    Standalone callers (tests, a closed surface) still open and close their own
    connection.
    """
    from engine import (
        fingerprint_connection,
        migrate_claim_kind_columns,
        migrate_format_kind_column,
    )
    import engine as engine_mod

    path = Path(db_path).resolve()
    owned = getattr(engine_mod, "_db_path", None)
    conn = getattr(engine_mod, "_connection", None)
    if (
        conn is not None
        and owned is not None
        and Path(owned).resolve() == path
    ):
        return fingerprint_connection(conn)

    from engine import graph_owner_lock

    with graph_owner_lock(path):
        db = lb.Database(str(path))
        conn = lb.Connection(db)
        try:
            migrate_claim_kind_columns(conn)
            migrate_format_kind_column(conn)
            return fingerprint_connection(conn)
        finally:
            del conn, db


def diff_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Structural delta between two manifests (contract §2.7 shape)."""
    b_c, a_c = before.get("concepts", {}), after.get("concepts", {})
    b_e = {tuple(e) for e in before.get("edges", [])}
    a_e = {tuple(e) for e in after.get("edges", [])}

    concepts_added = [{"id": cid, **a_c[cid]} for cid in sorted(a_c.keys() - b_c.keys())]
    concepts_removed = [{"id": cid, **b_c[cid]} for cid in sorted(b_c.keys() - a_c.keys())]
    concepts_changed = [
        {"id": cid, "before_sha": b_c[cid]["content_sha"], "after_sha": a_c[cid]["content_sha"]}
        for cid in sorted(a_c.keys() & b_c.keys())
        if b_c[cid]["content_sha"] != a_c[cid]["content_sha"] or b_c[cid]["label"] != a_c[cid]["label"]
    ]
    edges_added = [list(e) for e in sorted(a_e - b_e)]
    edges_removed = [list(e) for e in sorted(b_e - a_e)]

    return {
        "concepts_added": concepts_added,
        "concepts_removed": concepts_removed,
        "concepts_changed": concepts_changed,
        "edges_added": edges_added,
        "edges_removed": edges_removed,
    }


class SnapshotStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.dir = self.db_path.parent / f"{self.db_path.name}.snapshots"
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- capture -----------------------------------------------------------

    def capture(self, graph_version: str) -> dict[str, Any]:
        """Snapshot the current DB under its graph_version (idempotent per version)."""
        key = _key(graph_version)
        mpath = self.dir / f"{key}.manifest.json"
        if not mpath.exists():
            manifest = extract_manifest(self.db_path)
            meta = {
                "graph_version": graph_version,
                "captured_at": time.time(),
                "concept_count": len(manifest["concepts"]),
                "edge_count": len(manifest["edges"]),
                **manifest,
            }
            mpath.write_text(json.dumps(meta))
            shutil.copy2(self.db_path, self.dir / f"{key}.lbug")
        return json.loads(mpath.read_text())

    # -- reads -------------------------------------------------------------

    def manifest(self, graph_version: str) -> dict[str, Any] | None:
        mpath = self.dir / f"{_key(graph_version)}.manifest.json"
        return json.loads(mpath.read_text()) if mpath.exists() else None

    def versions(self) -> list[dict[str, Any]]:
        out = []
        for mpath in sorted(self.dir.glob("*.manifest.json")):
            m = json.loads(mpath.read_text())
            out.append(
                {
                    "graph_version": m["graph_version"],
                    "captured_at": m["captured_at"],
                    "concept_count": m["concept_count"],
                    "edge_count": m["edge_count"],
                }
            )
        return sorted(out, key=lambda v: v["captured_at"])

    def diff(self, v_before: str, v_after: str) -> dict[str, Any]:
        b, a = self.manifest(v_before), self.manifest(v_after)
        missing = [v for v, m in ((v_before, b), (v_after, a)) if m is None]
        if missing:
            return operator_fault("not_found", f"unknown version(s): {missing}")
        return diff_manifests(b, a)

    def diff_against_live(self, v_before: str) -> dict[str, Any]:
        b = self.manifest(v_before)
        if b is None:
            return operator_fault("not_found", f"unknown version(s): ['{v_before}']")
        return diff_manifests(b, extract_manifest(self.db_path))

    # -- operator-only -----------------------------------------------------

    def restore(self, graph_version: str) -> Path:
        """Copy snapshot DB back over the live path. OPERATOR ONLY — the
        caller must close any open GraphSession first, and no other process
        may own the file."""
        from engine import GraphInUseError, graph_owner_lock, this_process_owns_graph

        src = self.dir / f"{_key(graph_version)}.lbug"
        if not src.exists():
            raise FileNotFoundError(f"no DB snapshot for version {graph_version!r}")
        if this_process_owns_graph(self.db_path):
            raise GraphInUseError(
                f"cannot restore {self.db_path}: this process still has it open; "
                "close the GraphSession first",
                path=self.db_path,
            )
        with graph_owner_lock(self.db_path):
            idx = self.db_path.parent / f"{self.db_path.name}.idx"
            if idx.exists():
                idx.unlink()
            shutil.copy2(src, self.db_path)
        return self.db_path
