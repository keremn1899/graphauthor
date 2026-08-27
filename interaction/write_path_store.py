"""Write-path persistence sidecar — EscalationHandoff + CurationDecision durable store.

Owned by the server / MCP layer (not the engine library). Schema mirrors
``EscalationHandoff`` and curation decision fields + optional proposal provenance.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from interaction.escalation import EscalationHandoff
from write_path.models import ConfirmedCuration, CurationDecision, RejectedCuration


_SCHEMA = """
CREATE TABLE IF NOT EXISTS escalation_handoffs (
    handoff_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    case_id TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    ungoverned_predicate TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    governance_verdict_source TEXT NOT NULL DEFAULT '',
    engine_verdict TEXT NOT NULL DEFAULT '',
    provenance_json TEXT NOT NULL DEFAULT '[]',
    captured_at TEXT NOT NULL,
    proposal_task TEXT NOT NULL DEFAULT '',
    proposal_source_material TEXT NOT NULL DEFAULT '',
    proposal_conversation_id TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    target_gap_id TEXT NOT NULL DEFAULT '',
    encoding_json TEXT NOT NULL,
    claim_level TEXT NOT NULL DEFAULT 'L0',
    demotion_reason TEXT NOT NULL DEFAULT '',
    generating_task TEXT NOT NULL DEFAULT '',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    conversation_id TEXT NOT NULL DEFAULT '',
    decision_origin TEXT NOT NULL DEFAULT 'unspecified',
    expected_graph_version TEXT NOT NULL DEFAULT '',
    expected_graph_fingerprint TEXT NOT NULL DEFAULT '',
    traversal_receipt_json TEXT NOT NULL DEFAULT '{}',
    construction_receipt_json TEXT NOT NULL DEFAULT '{}',
    construction_evidence_json TEXT NOT NULL DEFAULT '{}',
    construction_reasons_json TEXT NOT NULL DEFAULT '{}',
    construction_edge_evidence_json TEXT NOT NULL DEFAULT '[]',
    review_exceptions_json TEXT NOT NULL DEFAULT '[]',
    review_mode TEXT NOT NULL DEFAULT '',
    review_required INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    primary_source TEXT NOT NULL DEFAULT '',
    gate_report_json TEXT NOT NULL DEFAULT '',
    graph_version_before TEXT NOT NULL DEFAULT '',
    graph_version_after TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS curation_decisions (
    candidate_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL,
    gap_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    proposal_task TEXT NOT NULL DEFAULT '',
    proposal_source_material TEXT NOT NULL DEFAULT '',
    proposal_conversation_id TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WritePathStore:
    """SQLite sidecar for pending-write / escalation state across process restarts."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # HTTP transport serves from worker threads (M7 finding: a thread-affine
        # connection crashed on cross-thread close). Single process, low
        # contention: shared connection + close-lock is the right tradeoff;
        # individual execute/commit calls serialize at the sqlite3 C level.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._close_lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        # Additive migrations (idempotent) — L2-3 batch audit fields.
        for col, ddl in (("batch_id", "TEXT NOT NULL DEFAULT ''"),
                         ("gate_tier", "TEXT NOT NULL DEFAULT ''"),
                         ("authority", "TEXT NOT NULL DEFAULT 'human'"),
                         ("decision_origin", "TEXT NOT NULL DEFAULT 'unspecified'"),
                         ("expected_graph_version", "TEXT NOT NULL DEFAULT ''"),
                         ("expected_graph_fingerprint", "TEXT NOT NULL DEFAULT ''"),
                         ("traversal_receipt_json", "TEXT NOT NULL DEFAULT '{}'"),
                         ("construction_receipt_json", "TEXT NOT NULL DEFAULT '{}'"),
                         ("construction_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
                         ("construction_reasons_json", "TEXT NOT NULL DEFAULT '{}'"),
                         ("construction_edge_evidence_json", "TEXT NOT NULL DEFAULT '[]'"),
                         ("review_exceptions_json", "TEXT NOT NULL DEFAULT '[]'"),
                         ("review_mode", "TEXT NOT NULL DEFAULT ''"),
                         ("review_required", "INTEGER NOT NULL DEFAULT 0")):
            try:
                self._conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} {ddl}")
            except Exception:
                pass
        self._conn.commit()

    def close(self) -> None:
        with self._close_lock:
            self._conn.close()

    def __enter__(self) -> "WritePathStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def save_handoff(
        self,
        handoff: EscalationHandoff,
        *,
        proposal_task: str = "",
        proposal_source_material: str = "",
        proposal_conversation_id: str = "",
    ) -> None:
        data = handoff.model_dump()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO escalation_handoffs (
                handoff_id, decision_id, case_id, question, ungoverned_predicate,
                status, resolution, governance_verdict_source, engine_verdict,
                provenance_json, captured_at,
                proposal_task, proposal_source_material, proposal_conversation_id,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["handoff_id"],
                data["decision_id"],
                data.get("case_id") or "",
                data.get("question") or "",
                data.get("ungoverned_predicate") or "",
                data.get("status") or "",
                data.get("resolution") or "",
                data.get("governance_verdict_source") or "",
                data.get("engine_verdict") or "",
                json.dumps(data.get("provenance") or []),
                data.get("captured_at") or _now(),
                proposal_task,
                proposal_source_material,
                proposal_conversation_id,
                _now(),
            ),
        )
        self._conn.commit()

    def list_handoffs(self, *, case_id: str | None = None) -> list[EscalationHandoff]:
        if case_id:
            rows = self._conn.execute(
                "SELECT * FROM escalation_handoffs WHERE case_id = ? ORDER BY recorded_at",
                (case_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM escalation_handoffs ORDER BY recorded_at"
            ).fetchall()
        out: list[EscalationHandoff] = []
        for r in rows:
            out.append(
                EscalationHandoff(
                    handoff_id=r["handoff_id"],
                    decision_id=r["decision_id"],
                    case_id=r["case_id"],
                    question=r["question"],
                    ungoverned_predicate=r["ungoverned_predicate"],
                    status=r["status"],
                    resolution=r["resolution"],
                    governance_verdict_source=r["governance_verdict_source"],
                    engine_verdict=r["engine_verdict"],
                    provenance=json.loads(r["provenance_json"] or "[]"),
                    captured_at=r["captured_at"],
                )
            )
        return out

    def save_proposal(self, record: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO proposals (
                proposal_id, target_gap_id, encoding_json, claim_level,
                demotion_reason, generating_task, source_refs_json,
                conversation_id, decision_origin, expected_graph_version,
                expected_graph_fingerprint, traversal_receipt_json,
                construction_receipt_json, construction_evidence_json,
                construction_reasons_json,
                construction_edge_evidence_json,
                review_exceptions_json, review_mode, review_required, status,
                submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["proposal_id"],
                record.get("target_gap_id", ""),
                record["encoding_json"],
                record.get("claim_level", "L0"),
                record.get("demotion_reason", ""),
                record.get("generating_task", ""),
                json.dumps(record.get("source_refs", [])),
                record.get("conversation_id", ""),
                record.get("decision_origin", "unspecified"),
                record.get("expected_graph_version", ""),
                record.get("expected_graph_fingerprint", ""),
                json.dumps(record.get("traversal_receipt") or {}),
                json.dumps(record.get("construction_receipt") or {}),
                json.dumps(record.get("construction_evidence") or {}),
                json.dumps(record.get("construction_reasons") or {}),
                json.dumps(record.get("construction_edge_evidence") or []),
                json.dumps(record.get("review_exceptions") or []),
                record.get("review_mode", ""),
                1 if record.get("review_required") else 0,
                record.get("status", "PENDING"),
                record.get("submitted_at") or _now(),
            ),
        )
        self._conn.commit()

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def list_proposals(self, *, status: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM proposals" + (" WHERE status = ?" if status else "") + " ORDER BY submitted_at"
        cur = self._conn.execute(q, (status,) if status else ())
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def update_proposal(self, proposal_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE proposals SET {cols} WHERE proposal_id = ?",
            (*fields.values(), proposal_id),
        )
        self._conn.commit()

    def save_curation_decision(
        self,
        *,
        candidate_id: str,
        decision: CurationDecision | str,
        payload: ConfirmedCuration | RejectedCuration | dict[str, Any] | None = None,
        gap_id: str = "",
        proposal_task: str = "",
        proposal_source_material: str = "",
        proposal_conversation_id: str = "",
    ) -> None:
        dec = decision.value if isinstance(decision, CurationDecision) else str(decision)
        if hasattr(payload, "model_dump"):
            body = payload.model_dump()  # type: ignore[union-attr]
            gap_id = gap_id or str(body.get("gap_id") or "")
        elif isinstance(payload, dict):
            body = payload
            gap_id = gap_id or str(body.get("gap_id") or "")
        else:
            body = {}
        self._conn.execute(
            """
            INSERT OR REPLACE INTO curation_decisions (
                candidate_id, decision, gap_id, payload_json,
                proposal_task, proposal_source_material, proposal_conversation_id,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                dec,
                gap_id,
                json.dumps(body),
                proposal_task,
                proposal_source_material,
                proposal_conversation_id,
                _now(),
            ),
        )
        self._conn.commit()

    def list_curation_decisions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM curation_decisions ORDER BY recorded_at"
        ).fetchall()
        return [
            {
                "candidate_id": r["candidate_id"],
                "decision": r["decision"],
                "gap_id": r["gap_id"],
                "payload": json.loads(r["payload_json"] or "{}"),
                "proposal_task": r["proposal_task"],
                "proposal_source_material": r["proposal_source_material"],
                "proposal_conversation_id": r["proposal_conversation_id"],
                "recorded_at": r["recorded_at"],
            }
            for r in rows
        ]
