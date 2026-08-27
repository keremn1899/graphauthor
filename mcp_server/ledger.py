"""Ledger activity projector (B2) — the fold from activity-lifecycle-model.md.

Pure and deterministic over the event list: no clock reads (``now`` is a
parameter — IDLE is computed at read time, never stored), no LLM, no state
outside the events. Dropping and replaying yields identical activity_ids
(stable hash of kind + minting glue). Batch events FAN OUT to every member
proposal's arc. The activity table any BFF stores is a cache of this
function's output; the event log is the only truth.
"""

from __future__ import annotations

import interaction.event_types as event_types
import hashlib
import json
import time


def _aid(kind: str, glue: str) -> str:
    return "act_" + hashlib.sha1(f"{kind}:{glue}".encode()).hexdigest()[:12]


_TERMINAL_RESOLUTION = {
    event_types.GRAPH_COMMITTED: "committed",
    event_types.GRAPH_REVERTED: "reverted",
}
_RETIRED_PREFIXES = (
    "escalation.", "query.", "governance.", "conformance.",
    "absence.", "rationalization.", "incident.", "construction.",
    "system.", "gap.", "snapshot.", "proposal.", "gate.", "receipt.",
)
_LIVE_FAMILIES = {event_types.family(t) for t in event_types.all_event_types()}


def projects_to_activity(event_type: str) -> bool:
    """Whether an event earns a row in the activity feed."""
    t = str(event_type or "")
    if t in event_types.all_event_types():
        return True
    if not t or any(t.startswith(p) for p in _RETIRED_PREFIXES):
        return False
    if event_types.family(t) in _LIVE_FAMILIES:
        return False
    return True


def event_contract(event_type: str) -> dict[str, str]:
    """Closed lifecycle vocabulary understood by the activity projector.

    Unknown event extensions remain visible as settled ``misc`` records.
    Write events settle immediately; they never open demand.
    """
    t = str(event_type or "")
    if t in (event_types.GRAPH_COMMITTED, event_types.GRAPH_REVERTED):
        return {"activity_kind": "gap", "role": "write"}
    return {"activity_kind": "misc", "role": "unknown"}


def _fold_event_facts(a: dict) -> None:
    """Lift the WHAT and the WHEN from an activity's events onto the activity.

    `subject_node_ids`, `graph_version_before` and `graph_version_after` are
    already first-class columns on the event log — emission sites fill them (a
    write event carries the proposal's concept ids; see battery E5). They were
    simply never folded up, so a caller holding an activity could not say which
    nodes it was about without re-reading and re-joining its events.

    That fold is what lets a ledger row point at the graph: an activity's
    subjects ARE the focus set, and the version pair IS the diff to show.

    - subjects: ordered union, first mention wins, so the reading order matches
      the order things actually happened.
    - versions: `before` from the earliest event that names one and `after` from
      the latest, which spans the whole arc rather than one step inside it.
    """
    subjects: list[str] = []
    seen: set[str] = set()
    before = ""
    after = ""
    for ev in a["events"]:
        raw = ev.get("subject_node_ids") or "[]"
        try:
            ids = json.loads(raw) if isinstance(raw, str) else list(raw)
        except (ValueError, TypeError):
            ids = []
        for nid in ids:
            nid = str(nid)
            if nid and nid not in seen:
                seen.add(nid)
                subjects.append(nid)
        if not before and ev.get("graph_version_before"):
            before = str(ev["graph_version_before"])
        if ev.get("graph_version_after"):
            after = str(ev["graph_version_after"])

    a["subject_node_ids"] = subjects
    a["graph_version_before"] = before
    a["graph_version_after"] = after

    # Who acted, same reasoning: `actor` and `authority_type` are event columns
    # that were never lifted. The LAST event wins — an arc that began as an
    # agent proposal and ended in a human confirm is, as a thing needing
    # attention, a human-authority arc now.
    actor = ""
    authority = ""
    for ev in a["events"]:
        if ev.get("actor"):
            actor = str(ev["actor"])
        if ev.get("authority_type"):
            authority = str(ev["authority_type"])
    a["actor"] = actor
    a["authority_type"] = authority


def project_activities(events: list[dict], now: float | None = None,
                       idle_window: float = 3600.0) -> dict[str, dict]:
    # Callers normally receive EventStore.list_events(), which is ordered, but
    # replay/import code is allowed to hand us any event list. Lifecycle state
    # and first/last-write fold rules must describe event time, not input order.
    ordered_events = sorted(
        events,
        key=lambda ev: (float(ev.get("ts") or 0.0), str(ev.get("event_id") or "")),
    )
    now = time.time() if now is None else now
    acts: dict[str, dict] = {}
    gap_to_act: dict[str, str] = {}
    prop_to_act: dict[str, str] = {}

    def mint(kind: str, glue: str, ev: dict) -> dict:
        aid = _aid(kind, glue)
        if aid not in acts:
            acts[aid] = {"activity_id": aid, "kind": kind, "mint_glue": glue,
                         "state": "OPEN", "resolution": "", "batch_id": "",
                         "events": [], "open_actionable": [], "open_incident": [],
                         "first_seen": ev["ts"], "last_event_at": ev["ts"]}
        return acts[aid]

    def attach(a: dict, ev: dict) -> None:
        a["events"].append(ev)
        a["last_event_at"] = max(a["last_event_at"], ev["ts"])
        if ev.get("batch_id"):
            a["batch_id"] = ev["batch_id"]

    for ev in ordered_events:
        t = ev["type"]
        if not projects_to_activity(t):
            continue
        gap = ev.get("gap_id") or ""
        hid = ev.get("handoff_id") or ""
        pid = ev.get("proposal_id") or ""

        if t in (event_types.GRAPH_COMMITTED, event_types.GRAPH_REVERTED):
            aid = prop_to_act.get(pid) or gap_to_act.get(gap) or gap_to_act.get(hid)
            a = acts[aid] if aid else mint("gap", pid or gap or ev["event_id"], ev)
            if pid:
                prop_to_act[pid] = a["activity_id"]
            attach(a, ev)
            a["state"] = "SETTLED"
            a["resolution"] = _TERMINAL_RESOLUTION[t]
            a["open_actionable"] = []

        else:  # unknown extensions remain visible but never invent open demand
            glue = pid or gap or hid or ev.get("case_id") or ev.get("conversation_id") or ev["event_id"]
            a = mint("misc", glue, ev)
            attach(a, ev)
            a["state"] = "SETTLED"

    for a in acts.values():
        _fold_event_facts(a)
        if a["state"] == "OPEN" and a["kind"] == "interrogation" \
                and (now - a["last_event_at"]) > idle_window:
            a["state"] = "IDLE"
        unresolved_action = bool(a["open_actionable"]) and a["state"] == "OPEN"
        unresolved_incident = bool(a["open_incident"])
        a["needs_me"] = unresolved_action
        a["incident"] = unresolved_incident
        if a["state"] == "SETTLED":
            a["weight"] = "demanding" if unresolved_incident else "notable"
        elif a["state"] == "IDLE":
            a["weight"] = "ambient"
        else:
            a["weight"] = "demanding" if (unresolved_action or unresolved_incident) else "notable"
        a["event_count"] = len(a["events"])
    return acts
