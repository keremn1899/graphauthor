"""Append-only activity event log (B2). The events table is TRUTH; the
activity feed is a rebuildable projection (`mcp_server/ledger.py`).

Lives in the same sqlite sidecar as the WritePathStore (one file to carry),
its own table, its own connection (cross-thread-safe like the store).
Emission sites append BEFORE any status overwrite; an event is never
updated or deleted. Acks and dismissals are events — one truth, never
UI-local state.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_events (
    event_id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    authority_type TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    conversation_id TEXT NOT NULL DEFAULT '',
    case_id TEXT NOT NULL DEFAULT '',
    gap_id TEXT NOT NULL DEFAULT '',
    handoff_id TEXT NOT NULL DEFAULT '',
    proposal_id TEXT NOT NULL DEFAULT '',
    batch_id TEXT NOT NULL DEFAULT '',
    causation_event_id TEXT NOT NULL DEFAULT '',
    graph_version_before TEXT NOT NULL DEFAULT '',
    graph_version_after TEXT NOT NULL DEFAULT '',
    subject_node_ids TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ev_ts ON activity_events (ts);
CREATE INDEX IF NOT EXISTS idx_ev_prop ON activity_events (proposal_id);
CREATE INDEX IF NOT EXISTS idx_ev_gap ON activity_events (gap_id);
"""

_COLS = ("actor", "authority_type", "trace_id", "conversation_id", "case_id",
         "gap_id", "handoff_id", "proposal_id", "batch_id",
         "causation_event_id",
         "graph_version_before", "graph_version_after", "reason")


class EventStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        # Existing sidecars predate first-class causation. CREATE TABLE IF NOT
        # EXISTS does not evolve them, so migrate additively before any writes.
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(activity_events)")
        }
        if "causation_event_id" not in columns:
            try:
                self._conn.execute(
                    "ALTER TABLE activity_events "
                    "ADD COLUMN causation_event_id TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError as exc:
                # Two first requests can race while opening the same legacy
                # sidecar. One wins the additive migration; the other may
                # safely continue only for the duplicate-column case.
                if "duplicate column" not in str(exc).lower():
                    raise
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ev_causation "
            "ON activity_events (causation_event_id)"
        )
        self._conn.commit()
        self._lock = threading.RLock()

    def emit(self, *, type: str, subject_node_ids: list[str] | None = None,
             payload: dict | None = None, ts: float | None = None, **glue: str) -> str:
        eid = f"ev_{uuid.uuid4().hex[:12]}"
        row = {c: str(glue.get(c, "") or "") for c in _COLS}
        with self._lock:
            self._conn.execute(
                "INSERT INTO activity_events (event_id, ts, type, subject_node_ids, payload, "
                + ", ".join(_COLS) + ") VALUES (?, ?, ?, ?, ?, " + ", ".join("?" * len(_COLS)) + ")",
                [eid, ts if ts is not None else time.time(), type,
                 json.dumps(subject_node_ids or []), json.dumps(payload or {}),
                 *[row[c] for c in _COLS]])
            self._conn.commit()
        return eid

    def list_events(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM activity_events ORDER BY ts, event_id")]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def emit_event(
    store_path: Path | str | None,
    *,
    required: bool = False,
    **kw,
) -> str | None:
    """Best-effort append from emission sites: an event-log failure must not
    abort a legacy path unless the caller marks the append ``required``.

    Consequential mutation paths can use ``required=True`` at a safe boundary;
    read telemetry and compatibility call sites retain best-effort behavior.
    The event id is returned so events emitted in one operation can name their
    direct cause without re-querying the log.
    """
    if not store_path:
        if required:
            raise RuntimeError("a required event has no store path")
        return
    try:
        es = EventStore(store_path)
        try:
            return es.emit(**kw)
        finally:
            es.close()
    except Exception as exc:  # pragma: no cover
        if required:
            raise
        import sys

        print(f"[event_log] append failed: {exc}", file=sys.stderr)
        return None


def latest_event_id(
    store_path: Path | str,
    *,
    types: set[str] | None = None,
    proposal_id: str = "",
    case_id: str = "",
    handoff_id: str = "",
    gap_id: str = "",
    payload_match: dict[str, str] | None = None,
) -> str:
    """Newest matching event id for linking a later human/system outcome.

    This is intentionally a small compatibility lookup, not lifecycle logic;
    the projector still derives activities solely from event rows.
    """
    store = EventStore(store_path)
    try:
        rows = store.list_events()
    finally:
        store.close()
    for row in reversed(rows):
        if types is not None and str(row.get("type") or "") not in types:
            continue
        if proposal_id and str(row.get("proposal_id") or "") != proposal_id:
            continue
        if case_id and str(row.get("case_id") or "") != case_id:
            continue
        if handoff_id and str(row.get("handoff_id") or "") != handoff_id:
            continue
        if gap_id and str(row.get("gap_id") or "") != gap_id:
            continue
        if payload_match:
            try:
                payload = json.loads(row.get("payload") or "{}")
            except (ValueError, TypeError):
                continue
            if any(
                str(payload.get(key) or "") != str(value)
                for key, value in payload_match.items()
            ):
                continue
        return str(row["event_id"])
    return ""


def record_acknowledgement(store_path: Path | str, *, subject_id: str, actor: str,
                           note: str = "") -> None:
    return


def record_escalation_disposition(store_path: Path | str, handoff_id: str,
                                  disposition: str, *, actor: str) -> None:
    return
