"""Single-tenant hosting helpers (v1) — consistent snapshot / restore.

The graph is an EMBEDDED database opened in-process from a local path: you host
the *server that owns the file*, not the file. The one thing hosting adds over
the C4 bundle (mcp_server.packaging) is CONSISTENCY of a *live* graph — issue
``CHECKPOINT`` (flush the WAL into the main ``.lbug``) before archiving, so a
snapshot taken while the server runs is never torn. Restore is unpack + integrity
verify.

Deterministic, no LLM. NOT multi-tenant, NOT HA — those are the B13 seam. This is
exactly: back up / move / roll back ONE hosted graph safely.

Live vs offline:
- OFFLINE (server not running): ``snapshot_graph`` opens its own connection to
  checkpoint — safe because nothing else holds the single-owner handle.
- LIVE (server running): the server must checkpoint on ITS existing connection
  under the write lock (``checkpoint_conn``), then archive — never open a second
  handle to a file a live process already owns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def checkpoint_conn(conn) -> None:
    """Flush the WAL into the main file on an EXISTING connection (the live-server
    path — call under the write lock so no write is in flight)."""
    conn.execute("CHECKPOINT")


def checkpoint(db_path: Path | str) -> None:
    """Flush the WAL for an OFFLINE / quiesced graph by opening a short-lived
    connection. Never call this against a graph a live server already owns — that
    would open a second handle to a single-owner embedded DB."""
    import real_ladybug as lb

    conn = lb.Connection(lb.Database(str(db_path)))
    try:
        checkpoint_conn(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def snapshot_graph(db_path: Path | str, out_archive: Path | str, *,
                   store_path: Path | str | None = None,
                   do_checkpoint: bool = True) -> dict[str, Any]:
    """Consistent snapshot of a hosted graph → a verifiable tar.gz bundle (the
    ``.lbug`` + cert + grain + event/proposal store + index). ``do_checkpoint``
    flushes the WAL first so the archive is not torn. Returns {archive, manifest,
    checkpointed}."""
    from mcp_server.packaging import bundle, collect_components

    if do_checkpoint:
        checkpoint(db_path)
    comps = collect_components(db_path, store_path=store_path)
    res = bundle(comps, out_archive)
    res["checkpointed"] = bool(do_checkpoint)
    return res


def restore_graph(archive: Path | str, dest: Path | str) -> dict[str, Any]:
    """Unpack a snapshot to ``dest`` and integrity-verify it against the manifest.
    Returns the unpack result plus {valid, mismatches} — a restore that fails
    verification is surfaced, never silently trusted."""
    from mcp_server.packaging import unpack, verify

    v = verify(archive)
    res = unpack(archive, dest)
    res["valid"] = v["valid"]
    res["mismatches"] = v["mismatches"]
    return res
