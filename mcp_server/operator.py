"""Operator BFF surface (B1) — the trusted human plane over the engine.

Design (post-ladder-two backlog B1 + the six locked BFF decisions):

- **Same process, second surface.** The BFF is not its own deployable; it is a
  second door on the server that already owns the graph (`/operator` mounted
  beside `/mcp`). One process = one owner of the `.lbug`.
- **Zero new authority.** Every write calls the SAME function the CLI calls,
  with the SAME license. `confirm` goes through `confirm_proposal`.
  Governance graphs still need a declared gate battery. A graph with `graph.md`
  confirms without that battery. The BFF adds no privileged path.
- **Live-compute reads.** The activities feed folds the event log on every read
  (`mcp_server.ledger.project_activities`). The event log is the only truth; the
  projection is a rebuildable cache we deliberately do not persist yet.
- **Displays and disposes, never invents.** No verdicts are produced here. The
  BFF surfaces proposals, escalations, gate reports, activities, and history,
  and routes confirm/reject/requeue back through the gated machinery.

Single-owner-DB note: `confirm` mutates the graph exclusively (snapshot
capture/restore). In-process the engine owner must release the connection for
the duration and refresh afterwards; `reload_hook` is that seam. The battery
exercises the path directly (no co-mounted engine), matching how the CLI and
the events battery drive `confirm_proposal`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from mcp_server.fault import operator_fault
from mcp_server.proposals import (
    GateSpec,
    confirm_proposal,
    reject_proposal,
    requeue_proposal,
)


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
    """Zero-new-authority composition over store / ledger / proposals / history.

    The gate provider is configured on the SERVER (never supplied by a browser):
    a callable mapping a proposal record → the ``GateSpec`` that proposal must
    survive to commit. Without it, confirm still refuses on graphs that have no
    ``graph.md``; a named-traversal contract is the other license to commit.
    """

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

    def lineage(self, node_id: str) -> dict[str, Any]:
        """Why does this node exist? (B3/B4) — inferred provenance chain folded
        from the event log + proposal store. The result is
        labelled 'derived'; authority_type/primary_source are 'recorded'.

        Existence is checked HERE, not in the assembler: `node_lineage` is a
        pure projection that never opens the graph, so it cannot know whether
        the id it was handed is real. Without this check it answered any id at
        all. Fabricating a provenance record is the one failure this path exists
        to prevent.
        """
        from mcp_server.crossing import _all_nodes, _connect
        from mcp_server.lineage import node_lineage

        conn = _connect(self._db)
        try:
            known = _all_nodes(conn)
        finally:
            conn.close()
        if node_id not in known:
            return operator_fault("not_found", "unknown node", node_id=node_id)
        return node_lineage(node_id, store_path=self._store, db_path=self._db)

    def classify_absence(self, predicate: str) -> dict[str, Any]:
        """B8 — advisory, deterministic prior on an UNGOVERNED absence. Never
        hides: the absence stays fully visible; this only labels it."""
        from mcp_server.crossing import _all_nodes, _connect
        from mcp_server.materiality import classify_absence

        conn = _connect(self._db)
        try:
            nodes = _all_nodes(conn)
        finally:
            conn.close()
        return classify_absence(predicate, nodes)

    def dispose_absence(self, *, predicate: str, category: str,
                        primary_source: str = "", reasoning: str = "") -> dict[str, Any]:
        """B8 — record the operator's disposition of an absence. The operator is
        a human authority; the false-benign cardinal (sourced, non-engine
        dismissal) is enforced in the materiality layer."""
        from mcp_server.materiality import dispose_absence

        return dispose_absence(self._store, predicate=predicate, category=category,
                               actor=self._current_actor(), primary_source=primary_source,
                               reasoning=reasoning, db_path=self._db)

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
        from mcp_server.graph_contract import resolve_graph_contract_path

        return resolve_graph_contract_path(self._db).exists()

    def _confirm_embedder(self):
        if self._embedder is not None:
            return self._embedder
        if os.environ.get("OPENROUTER_API_KEY"):
            return None
        return lambda _text: [0.0] * 3072

    # ------------------------------------------------------------------
    # writes — thin transport; zero new authority
    # ------------------------------------------------------------------

    def confirm(
        self,
        proposal_id: str,
        *,
        primary_source: str = "",
        correction_acknowledgement: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Human confirm → encode. License is a gate battery or a graph.md
        harness. A typed source is optional audit copy; ``source_refs`` on the
        proposal fill it when omitted. A declared-exclusion proposal (B8)
        routes to the VERDICT-NEUTRALITY gate instead.

        ``correction_acknowledgement`` is the same binding the host-agent write
        surface uses: digest + moves + accepts. Who built it is audit
        (``acknowledged_by``); this plane still cannot fabricate a governance
        bypass on a graph that has no contract.
        """
        import contextlib

        rec = self.get_proposal(proposal_id)
        if rec is None:
            return operator_fault("not_found", f"unknown proposal: {proposal_id}")
        is_exclusion = str(rec.get("target_gap_id") or "").startswith("exclusion:")
        harness = self._has_graph_contract()
        if not is_exclusion and self._gate_provider is None and not harness:
            return {
                "error": "operator plane has no gate provider configured: the BFF "
                "commits only through a graph.md harness or the same battery "
                "the CLI requires (zero new authority)"
            }
        if not str(primary_source).strip():
            try:
                refs = json.loads(rec.get("source_refs_json") or "[]")
            except (TypeError, ValueError):
                refs = []
            primary_source = next(
                (str(ref).strip() for ref in refs if str(ref).strip()),
                "",
            )
        # Single-owner DB (B13): the mutation + engine reload happen under the
        # write side of the shared RW lock, excluding in-flight MCP invokes.
        write_ctx = self._rw_lock.write() if self._rw_lock is not None else contextlib.nullcontext()
        with write_ctx:
            if is_exclusion:
                from mcp_server.materiality import commit_exclusion

                result = commit_exclusion(self._db, self._store, proposal_id,
                                          primary_source=primary_source, embedder=self._embedder,
                                          actor=self._current_actor())
            else:
                gate = self._gate_provider(rec) if self._gate_provider is not None else None
                result = confirm_proposal(
                    self._db, self._store, proposal_id,
                    primary_source=primary_source, gate=gate,
                    embedder=self._confirm_embedder(),
                    actor=self._current_actor(),
                    correction_acknowledgement=correction_acknowledgement,
                )
            if result.get("status") == "COMMITTED" and self._reload_hook is not None:
                self._reload_hook()
        return result

    def reject(self, proposal_id: str, *, reason: str = "") -> dict[str, Any]:
        return reject_proposal(
            self._store, proposal_id, reason=reason, actor=self._current_actor())

    def requeue(self, proposal_id: str) -> dict[str, Any]:
        return requeue_proposal(
            self._store, proposal_id, actor=self._current_actor())

    def acknowledge_incident(self, subject_id: str, *, note: str = "") -> dict[str, Any]:
        """Acknowledge an open incident by its domain subject or activity id."""
        incident = next(
            (
                activity for activity in self.activities()
                if activity.get("kind") == "incident"
                and subject_id in {
                    str(activity.get("mint_glue") or ""),
                    str(activity.get("activity_id") or ""),
                }
            ),
            None,
        )
        if incident is None:
            return operator_fault("not_found", f"unknown incident: {subject_id}")
        if not incident.get("incident"):
            return operator_fault(
                "conflict", f"incident is already acknowledged: {subject_id}"
            )

        rationalization = next(
            (
                event for event in incident.get("events", [])
                if event.get("type") == "rationalization.flagged"
            ),
            None,
        )
        if rationalization is not None:
            import json

            try:
                payload = json.loads(rationalization.get("payload") or "{}")
            except (ValueError, TypeError):
                payload = {}
            from mcp_server.pr_gate import acknowledge_rationalization

            result = acknowledge_rationalization(
                self._store,
                rule_id=str(payload.get("rule_id") or ""),
                artifact_path=str(payload.get("artifact_path") or ""),
                actor=self._current_actor(),
                reasoning=note,
            )
            if "error" in result:
                return result
            return {"subject_id": str(incident["mint_glue"]), "status": "ACKNOWLEDGED"}

        from interaction.event_log import record_acknowledgement

        subject = str(incident["mint_glue"])
        record_acknowledgement(
            self._store, subject_id=subject, actor=self._current_actor(), note=note)
        return {"subject_id": subject, "status": "ACKNOWLEDGED"}

    def dispose_escalation(self, handoff_id: str, *, disposition: str) -> dict[str, Any]:
        """Dismiss or defer an escalation; both are explicit human closures."""
        if disposition not in {"dismissed", "deferred"}:
            return operator_fault(
                "invalid", "disposition must be dismissed or deferred"
            )
        if not any(
            str(row.get("handoff_id") or "") == handoff_id
            for row in self.list_escalations()
        ):
            return operator_fault("not_found", f"unknown escalation: {handoff_id}")
        activity = next(
            (
                row for row in self.activities()
                if any(
                    str(event.get("handoff_id") or "") == handoff_id
                    for event in row.get("events", [])
                )
            ),
            None,
        )
        if activity is None or not any(
            demand.get("on") == "escalation"
            for demand in activity.get("open_actionable", [])
        ):
            return operator_fault(
                "conflict",
                f"escalation has already progressed or settled: {handoff_id}",
            )

        from interaction.event_log import record_escalation_disposition

        record_escalation_disposition(
            self._store, handoff_id, disposition, actor=self._current_actor())
        return {"handoff_id": handoff_id, "status": disposition.upper()}

    # ------------------------------------------------------------------
    # account / settings / BYO-key (v1 bill-later plumbing)
    # ------------------------------------------------------------------

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
