"""Operator surface — trusted human reads over the same process that owns the graph.

`/operator` is a second door on the server that already owns the `.lbug`.
Propose auto-commits on the agent plane; revert stays on the history CLI.
Reads fold the event log live. This surface does not confirm, reject, or requeue.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from mcp_server.fault import operator_fault
from mcp_server.proposals import GateSpec


def _serialize(obj: Any) -> dict[str, Any]:
    """EscalationHandoff / pydantic / dataclass → plain JSON-able dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {"value": str(obj)}


class OperatorSurface:
    """Reads over store, ledger, and history. Propose auto-commits on Surface."""

    def __init__(
        self,
        db_path: Path | str,
        store_path: Path | str,
        *,
        gate_provider: Callable[[dict[str, Any]], GateSpec | None] | None = None,
        embedder: Callable[[str], list[float]] | None = None,
        reload_hook: Callable[[], None] | None = None,
        enable_history: bool = True,
        rw_lock: Any | None = None,
        account: Any | None = None,
    ) -> None:
        self._db = Path(db_path)
        self._store = Path(store_path)
        self._gate_provider = gate_provider
        self._embedder = embedder
        self._reload_hook = reload_hook
        self._history_enabled = bool(enable_history)
        # Write side of the single-owner RW lock (B13): a confirm excludes
        # in-flight MCP invokes for its snapshot-bounded duration.
        self._rw_lock = rw_lock
        # Account / settings / BYO-key (v1 bill-later plumbing). Lazily defaulted
        # via _acct() so a bare surface never touches ~/.graphauthor until settings are used.
        self._account = account

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _open_store(self):
        from interaction.write_path_store import WritePathStore

        return WritePathStore(self._store)

    def _events(self) -> list[dict[str, Any]]:
        from interaction.event_log import EventStore

        es = EventStore(self._store)
        try:
            return es.list_events()
        finally:
            es.close()

    def _current_actor(self) -> str:
        """Configured local identity, without creating account files merely
        because the operator performed an action."""
        return self._account.current_actor() if self._account is not None else "operator"

    # ------------------------------------------------------------------
    # reads — no engine mutation, no authority
    # ------------------------------------------------------------------

    def list_proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        store = self._open_store()
        try:
            return store.list_proposals(status=status)
        finally:
            store.close()

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        store = self._open_store()
        try:
            return store.get_proposal(proposal_id)
        finally:
            store.close()

    def list_escalations(self, *, case_id: str | None = None) -> list[dict[str, Any]]:
        store = self._open_store()
        try:
            return [_serialize(h) for h in store.list_handoffs(case_id=case_id)]
        finally:
            store.close()

    def events(self) -> list[dict[str, Any]]:
        """The immutable event log, chronological. Truth; not a projection."""
        return self._events()

    def activities(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Live fold of the event log → activity arcs, newest last-event first."""
        from mcp_server.ledger import project_activities

        acts = project_activities(self._events(), now=now)
        return sorted(acts.values(), key=lambda a: a["last_event_at"], reverse=True)

    def inbox(self, *, now: float | None = None) -> dict[str, Any]:
        """The 'needs me' summary: unresolved demands and open incidents."""
        acts = self.activities(now=now)
        needs_me = [a for a in acts if a.get("needs_me")]
        incidents = [a for a in acts if a.get("incident")]
        return {
            "needs_me_count": len(needs_me),
            "incident_count": len(incidents),
            "needs_me": needs_me,
            "incidents": incidents,
        }

    def audit(self, proposal_id: str) -> dict[str, Any]:
        """Gate report + recorded authority for one proposal (recorded, not
        inferred). Lineage assembly is deferred per the B3 decision."""
        import json

        rec = self.get_proposal(proposal_id)
        if rec is None:
            return operator_fault("not_found", f"unknown proposal: {proposal_id}")
        gate_report: Any = rec.get("gate_report_json") or "{}"
        try:
            gate_report = json.loads(gate_report)
        except (ValueError, TypeError):
            pass
        return {
            "proposal_id": proposal_id,
            "status": rec.get("status"),
            "primary_source": rec.get("primary_source") or "",
            "target_gap_id": rec.get("target_gap_id") or "",
            "graph_version_before": rec.get("graph_version_before") or "",
            "graph_version_after": rec.get("graph_version_after") or "",
            "gate_report": gate_report,
            "decided_at": rec.get("decided_at") or "",
        }

    def history(self) -> dict[str, Any]:
        """Snapshot inventory (read-only). Revert stays a CLI operator action."""
        if not self._history_enabled:
            return operator_fault("invalid", "history is not enabled on this server")
        from mcp_server.history import SnapshotStore

        snaps = SnapshotStore(self._db)
        return {"versions": snaps.versions()}

    def diff(self, v_before: str, v_after: str) -> dict[str, Any]:
        """Content-true structural delta between two recorded snapshots.

        Read-only and already part of the MCP surface; exposing the same
        manifest diff on the human plane adds no authority. Revert remains CLI.
        """
        if not self._history_enabled:
            return operator_fault("invalid", "history is not enabled on this server")
        if not v_before or not v_after:
            return operator_fault("invalid", "v1 and v2 are required")
        from mcp_server.history import SnapshotStore

        return SnapshotStore(self._db).diff(v_before, v_after)

    def health(self) -> dict[str, Any]:
        """Readiness + capability introspection. No filesystem paths leak to
        the browser layer — booleans and counts only."""
        try:
            props = self.list_proposals()
            pending = len([p for p in props if p.get("status") == "PENDING"])
            store_ok = True
        except Exception as exc:  # pragma: no cover - store fault is the signal
            props, pending, store_ok = [], 0, False
            return {"ready": False, "store_ok": False, "error": f"{type(exc).__name__}: {exc}"}
        inbox = self.inbox()
        return {
            "ready": bool(self._db.exists()) and store_ok,
            "graph_present": self._db.exists(),
            "store_ok": store_ok,
            "history_enabled": self._history_enabled,
            "can_commit": self._gate_provider is not None
            or self._has_graph_contract(),
            "proposal_count": len(props),
            "pending_count": pending,
            "needs_me_count": inbox["needs_me_count"],
            "incident_count": inbox["incident_count"],
        }

    def _has_graph_contract(self) -> bool:
        return (self._db.parent / "graph.md").exists()

    def _acct(self):
        if self._account is None:
            from mcp_server.account import default_account
            self._account = default_account()
        return self._account

    def settings(self) -> dict[str, Any]:
        """Non-secret settings (actor, subscription, model_prefs, key METADATA).
        Never contains the key itself — the key lives encrypted off this record."""
        return self._acct().load()

    def entitlement(self) -> dict[str, Any]:
        a = self._acct()
        return {"entitled": a.is_entitled(), **a.load().get("subscription", {})}

    def set_key(self, key: str, *, validate: bool = True) -> dict[str, Any]:
        """Set the operator's BYO OpenRouter key — validated (a cheap auth ping),
        encrypted at rest, never returned. Returns status only.

        A stored key is also applied to this process's environment, so the next
        derive/construct uses it without a restart. Storing without applying is
        what made the key path inert: it was set, and nothing ever read it."""
        from mcp_server.account import openrouter_validator
        acct = self._acct()
        meta = acct.set_key(key, validator=openrouter_validator if validate else None)
        if meta.get("set"):
            acct.apply_key_to_env()
        return meta

    def key_status(self) -> dict[str, Any]:
        return self._acct().key_status()

    def clear_key(self) -> dict[str, Any]:
        """Clear the stored key AND drop it from the environment — otherwise a
        'cleared' key would keep working until the process restarted."""
        import os

        self._acct().clear_key()
        os.environ.pop("OPENROUTER_API_KEY", None)
        return self._acct().key_status()

    def set_actor(self, actor: str) -> dict[str, Any]:
        self._acct().set_actor(actor)
        return {"actor": self._acct().current_actor()}

    def set_model_prefs(self, **prefs: Any) -> dict[str, Any]:
        return {"model_prefs": self._acct().set_model_prefs(**prefs)}

    def posture(self) -> dict[str, Any]:
        return {"posture": self._acct().posture()}

    def set_posture(self, **fields: Any) -> dict[str, Any]:
        """Author the operator's intent for agents. Zero new authority: posture
        is advisory instruction, and loosening it can never grant an agent a
        capability the write path does not already allow."""
        try:
            return {"posture": self._acct().set_posture(**fields)}
        except ValueError as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
