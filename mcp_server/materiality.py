"""Architectural-materiality disposition (backlog B8).

The engine already DETECTS absence richly (UNGOVERNED / ABSENT / ILL_POSED /
INSUFFICIENT_EVIDENCE + typed gaps + moats). B8 is a different axis: DISPOSITION
— is a given absence a genuine gap, a retrieval miss, a local implementation
choice, an architecturally material decision, or not-yet-decidable? The engine
returns UNGOVERNED identically for "which retry constant to use" (benign) and
"which service owns dead-letter retention" (a missing decision). This layer
names that difference.

Founder decisions (this session):

- **Pre-classify, never hide.** `classify_absence` emits an ADVISORY structural
  prior + the raw signals behind it. It is never terminal, never suppresses:
  the absence and its evidence are unchanged and fully visible. Zero LLM — a
  model classifier would become an authoritative-feeling judge users trust to
  hide things, which violates the principle.
- **Only a sourced human act disposes.** `dispose_absence` records a human's
  disposition as an event. The engine never authors a disposition.
- **Local-choice is a gated, sourced, supersedable declared exclusion.** "This
  is intentionally ungoverned" is a recorded decision (`DOES NOT GOVERN`), not a
  shrug — and it stays UNGOVERNED for conformance (never flips the ruling
  space).
- **The false-benign cardinal is a PROCESS invariant, not a verdict gate.**
  Materiality is a judgment about intent, not a structural fact, so "never
  dismiss a material gap" cannot be a deterministic gate. What IS enforced: no
  dismissal is silent, unattributed, or engine-authored.
"""

from __future__ import annotations

import interaction.event_types as event_types
import re
from typing import Any

# The five B8 categories (terminal dispositions — only a human sets these).
CATEGORIES = ("genuine_gap", "retrieval_miss", "local_choice", "arch_material", "insufficient")
# Benign dismissals: an absence declared not-to-matter. These bear the process
# cardinal — sourced + human + recorded, never engine-authored or silent.
DISMISSALS = ("local_choice",)

_EXCLUSION_MARKER = re.compile(r"DOES NOT GOVERN\s*:\s*([^\n.;]*)", re.I)
_OPEN_QUESTION_MARKER = re.compile(r"OPEN QUESTION\s*:\s*([^\n.;]*)", re.I)
_ADJUDICATES = re.compile(r"ADJUDICATES", re.I)
_STOP = {"the", "and", "for", "which", "what", "does", "this", "that", "with",
         "from", "into", "should", "when", "whether", "govern", "governs",
         "governed", "policy", "rule", "who", "owns"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{4,}", str(text).lower()) if t not in _STOP}


def _subject_match(pred_tokens: set[str], node: dict) -> bool:
    """Deterministic, transparent token overlap between the ungoverned predicate
    and a node's identity (label/anchor/id). Not semantic — advisory only."""
    node_tokens = _tokens(f"{node.get('label','')} {node.get('semantic_anchor','')} {node.get('id','')}")
    shared = pred_tokens & node_tokens
    return any(len(t) >= 5 for t in shared) or len(shared) >= 2


def declared_exclusion_marker(predicate: str) -> str:
    """The graph text a LOCAL_CHOICE disposition materializes (via the gated
    write path). Deliberately NOT rule-shaped — it carries no ADJUDICATES, so it
    can never be mistaken for governance."""
    return f"DOES NOT GOVERN: {predicate.strip()}"


def is_excluded(graph_nodes: dict[str, dict], predicate: str) -> bool:
    """Does the graph already declare this predicate intentionally ungoverned?"""
    pred_tokens = _tokens(predicate)
    for n in graph_nodes.values():
        for m in _EXCLUSION_MARKER.finditer(str(n.get("text_content") or "")):
            if _tokens(m.group(1)) & pred_tokens:
                return True
    return False


def open_question_marker(predicate: str) -> str:
    """The graph text an ARCH_MATERIAL disposition materializes.

    The mirror of `declared_exclusion_marker`, and the opposite instruction.
    An exclusion says *we decided not to rule here, use your judgement*; this
    says *we know this needs deciding and have not decided*. Both are
    non-governing, and the difference is what an agent should do next: proceed,
    versus stop.

    Without it the graph could declare only one of the two. "Deliberately open"
    materialized as a node; "known gap, undecided" lived in the event log, so an
    agent reading the graph saw plain silence and fell back to a structural
    guess. That is the same half-right position the whole module exists to fix,
    one level up: the guess is right about as often as it is wrong, and nothing
    tells the halves apart.

    Deliberately not rule-shaped — no ADJUDICATES, and materialized with no
    edges — so like the exclusion it can never be mistaken for governance or
    flip a ruling.
    """
    return f"OPEN QUESTION: {predicate.strip()}"


def is_open_question(graph_nodes: dict[str, dict], predicate: str) -> bool:
    """Does the graph already declare this predicate a known, undecided gap?"""
    pred_tokens = _tokens(predicate)
    for n in graph_nodes.values():
        for m in _OPEN_QUESTION_MARKER.finditer(str(n.get("text_content") or "")):
            if _tokens(m.group(1)) & pred_tokens:
                return True
    return False


def classify_absence(predicate: str, graph_nodes: dict[str, dict], *,
                     moat_confirmed: bool | None = None) -> dict[str, Any]:
    """Deterministic, advisory pre-classification of an UNGOVERNED absence.

    NEVER terminal, NEVER hides: returns a structural `prior` plus the raw
    `signals` behind it, so a human sees the evidence and decides. `prior` is
    drawn from an advisory vocabulary distinct from the terminal CATEGORIES."""
    pred_tokens = _tokens(predicate)
    subject_nodes = [nid for nid, n in graph_nodes.items()
                     if not n.get("is_metanode") and _subject_match(pred_tokens, n)]
    excluded = is_excluded(graph_nodes, predicate)
    open_question = is_open_question(graph_nodes, predicate)
    signals = {
        "subject_modeled": bool(subject_nodes),
        "subject_nodes": subject_nodes[:5],
        "declared_exclusion_found": excluded,
        "open_question_found": open_question,
        "moat_confirmed_real": moat_confirmed,
    }
    if excluded and open_question:
        # Both declarations about one predicate is an authoring contradiction —
        # the graph says proceed and stop at once. Surfaced rather than resolved
        # by precedence: silently preferring either would hide the defect and
        # hand the agent a confident instruction the graph does not support.
        prior = "declared_conflict"
    elif open_question:
        prior = "declared_open"             # a prior arch_material disposition
    elif excluded:
        prior = "already_excluded"          # a prior local-choice disposition
    elif moat_confirmed is False:
        prior = "possible_retrieval_miss"    # the absence was not moat-confirmed
    elif subject_nodes:
        prior = "likely_material"            # graph models the subject, lacks a ruling
    else:
        prior = "likely_local"               # subject not modeled — below grain / out of scope
    return {
        "predicate": predicate,
        "prior": prior,
        "advisory": True,
        "signals": signals,
        "note": ("advisory structural prior; the absence and its evidence are "
                 "unchanged and fully visible; only a sourced human disposition "
                 "is authoritative"),
    }


def _effect(category: str, predicate: str) -> dict[str, Any]:
    if category == "local_choice":
        return {"kind": "declared_exclusion", "marker": declared_exclusion_marker(predicate),
                "gated": True, "supersedable": True,
                "note": "materialize through the gated proposal path; stays UNGOVERNED for conformance"}
    if category in ("genuine_gap", "arch_material"):
        return {"kind": "escalate_to_proposal",
                "note": "route to the write path — a decision must be legislated"}
    if category == "retrieval_miss":
        return {"kind": "retrieval_fix",
                "note": "coverage exists; fix retrieval, do not add to the graph"}
    return {"kind": "defer", "note": "await evidence"}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s[:40] or "predicate"


def _materialize_marker_node(db_path, store_path, *, predicate: str,
                             primary_source: str, reasoning: str,
                             actor: str, causation_event_id: str,
                             emit_submission: bool,
                             kind: str, marker: str) -> dict[str, Any]:
    """Route a disposition into the gated write path as a non-governing node.

    Shared by the declared exclusion and the open question, which differ only in
    their marker text and their identifiers. They were nearly written as two
    copies; the retrieval surface in this tree spent months as two copies of one
    contract and a repair reached one of them, so the shape stays single.

    The node rides the SAME propose -> confirm -> gate path every write takes —
    no new privileged path. It is deliberately not rule-shaped (no ADJUDICATES,
    no edges): it stays UNGOVERNED for conformance and must never flip the
    ruling space.
    """
    import json as _json

    from interaction.write_path_store import WritePathStore
    from mcp_server.proposals import new_proposal_id, validate_proposal

    slug = _slug(predicate)
    node_id = f"{kind}_{slug}"
    body = marker + (f"\n\n{reasoning}" if reasoning else "")
    label_prefix = "exclusion" if kind == "exclusion" else "open question"
    encoding = {"concepts": [{"id": node_id,
                              "label": f"{label_prefix}: {predicate.strip()}"[:80],
                              "text_content": body,
                              "semantic_anchor": predicate.strip()[:60]}],
                "edges": []}
    prop, err = validate_proposal(encoding, db_path)
    if prop is None:
        return {"error": f"{label_prefix} did not validate: {err}"}
    pid = new_proposal_id()
    from mcp_server.history import graph_fingerprint

    expected_fingerprint = graph_fingerprint(db_path)
    category = "local_choice" if kind == "exclusion" else "arch_material"
    store = WritePathStore(store_path)
    try:
        store.save_proposal({
            "proposal_id": pid,
            "target_gap_id": f"{kind}:{slug}",
            "encoding_json": _json.dumps(prop.model_dump()),
            "generating_task": f"absence_disposition:{category}",
            "source_refs": [primary_source] if primary_source else [],
            "expected_graph_version": f"global:{expected_fingerprint[:12]}",
            "expected_graph_fingerprint": expected_fingerprint,
            "status": "PENDING",
        })
    finally:
        store.close()
    target_gap_id = f"{kind}:{slug}"
    return {"proposal_id": pid, "status": "PENDING", "node_id": node_id,
            "target_gap_id": target_gap_id, "marker": marker}


def materialize_exclusion(db_path, store_path, *, predicate: str,
                          primary_source: str, reasoning: str = "",
                          actor: str = "operator",
                          causation_event_id: str = "",
                          emit_submission: bool = True) -> dict[str, Any]:
    """A LOCAL_CHOICE disposition as a graph node: "we decided not to rule here"."""
    return _materialize_marker_node(
        db_path, store_path, predicate=predicate, primary_source=primary_source,
        reasoning=reasoning, actor=actor, causation_event_id=causation_event_id,
        emit_submission=emit_submission,
        kind="exclusion", marker=declared_exclusion_marker(predicate))


def materialize_open_question(db_path, store_path, *, predicate: str,
                              primary_source: str, reasoning: str = "",
                              actor: str = "operator",
                              causation_event_id: str = "",
                              emit_submission: bool = True) -> dict[str, Any]:
    """An ARCH_MATERIAL disposition as a graph node: "known gap, still undecided".

    Materializing this is what lets a *later* agent — one that never saw the
    escalation — read the graph and find a declaration instead of silence. The
    escalation itself is an event, and events are not what an agent consults
    before it writes code.

    It is retired by supersession, not deletion, when the decision lands:
    `ChangeSet.SUPERSEDE_RULE` carries target/new/effective, so the history
    still shows the gap was known and when it closed. Deleting would erase
    exactly the fact worth keeping.
    """
    return _materialize_marker_node(
        db_path, store_path, predicate=predicate, primary_source=primary_source,
        reasoning=reasoning, actor=actor, causation_event_id=causation_event_id,
        emit_submission=emit_submission,
        kind="open_question", marker=open_question_marker(predicate))


def is_verdict_neutral_exclusion(prop) -> tuple[bool, str]:
    """A structurally non-governing add is verdict-neutral BY CONSTRUCTION: no
    ADJUDICATES (not a rule) and no governance-conferring edge (only NEARTO or
    none). This is stronger than a probe-based before/after — it cannot change
    any GOVERNED verdict, and it blocks laundering governance through the
    exclusion path."""
    for c in prop.concepts:
        if _ADJUDICATES.search(c.text_content or ""):
            return False, f"exclusion node {c.id} is rule-shaped (carries ADJUDICATES)"
    for e in prop.edges:
        if e.type != "NEARTO":
            return False, f"exclusion carries a governance-conferring edge {e.type}:{e.source_id}->{e.target_id}"
    return True, ""


def commit_exclusion(db_path, store_path, proposal_id: str, *, primary_source: str,
                     embedder=None, authority: str = "human",
                     actor: str = "operator") -> dict[str, Any]:
    """Commit a declared-exclusion proposal through the VERDICT-NEUTRALITY gate
    (not the governance-closure gate): the exclusion must be structurally
    non-governing, so it provably changes no GOVERNED verdict. Snapshot-atomic;
    a non-neutral 'exclusion' is refused, never committed."""
    import json as _json
    import time as _time

    from interaction.event_log import emit_event
    from interaction.write_path_store import WritePathStore
    from mcp_server.history import SnapshotStore
    from mcp_server.proposals import (
        _apply,
        default_embedder,
        proposal_basis_refusal,
        validate_proposal,
    )

    if not str(primary_source).strip():
        return {"error": "primary_source is required: an exclusion is a sourced decision"}
    now = lambda: _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    store = WritePathStore(store_path)
    try:
        rec = store.get_proposal(proposal_id)
        if rec is None:
            return {"error": f"unknown proposal: {proposal_id}"}
        if rec["status"] != "PENDING":
            return {"error": f"proposal is {rec['status']}, not PENDING"}
        basis_refusal = proposal_basis_refusal(rec, db_path)
        if basis_refusal is not None:
            return basis_refusal
        from interaction.event_log import latest_event_id

        proposal_cause = latest_event_id(store_path, proposal_id=proposal_id)
        prop, err = validate_proposal(_json.loads(rec["encoding_json"]), db_path)
        if prop is None:
            return {"error": f"proposal no longer valid: {err}"}

        neutral, why = is_verdict_neutral_exclusion(prop)
        if not neutral:
            store.update_proposal(proposal_id, status="GATE_FAILED",
                                  demotion_reason=f"not verdict-neutral: {why}", decided_at=now())
            return {"proposal_id": proposal_id, "status": "GATE_FAILED",
                    "error": f"not verdict-neutral: {why}"}

        snaps = SnapshotStore(db_path)
        pre = f"pre-exclusion:{proposal_id}"
        snaps.capture(pre)
        try:
            _apply(db_path, prop, embedder or default_embedder())
        except Exception as exc:
            snaps.restore(pre)
            store.update_proposal(proposal_id, status="ENCODE_FAILED",
                                  demotion_reason=f"apply failed: {exc}", decided_at=now())
            return {"proposal_id": proposal_id, "status": "ENCODE_FAILED", "error": str(exc)}

        post = f"post-exclusion:{proposal_id}"
        snaps.capture(post)
        try:
            emit_event(
                store_path, required=True,
                type=event_types.GRAPH_COMMITTED, proposal_id=proposal_id,
                gap_id=rec["target_gap_id"],
                graph_version_before=pre, graph_version_after=post,
                actor=actor, authority_type=authority,
                causation_event_id=proposal_cause,
                subject_node_ids=[c.id for c in prop.concepts])
        except Exception as exc:
            snaps.restore(pre)
            store.update_proposal(
                proposal_id, status="ENCODE_FAILED",
                demotion_reason=f"event append failed: {type(exc).__name__}: {exc}",
                decided_at=now())
            return {
                "proposal_id": proposal_id,
                "status": "ENCODE_FAILED",
                "error": "commit event append failed; graph restored",
            }
        store.update_proposal(proposal_id, status="COMMITTED", primary_source=primary_source,
                              authority=authority, graph_version_before=pre,
                              graph_version_after=post, decided_at=now())
        return {"proposal_id": proposal_id, "status": "COMMITTED", "gate": "verdict_neutrality",
                "graph_version_before": pre, "graph_version_after": post}
    finally:
        store.close()


def dispose_absence(store_path, *, predicate: str, category: str, actor: str,
                    primary_source: str = "", reasoning: str = "",
                    handoff_id: str = "", db_path=None) -> dict[str, Any]:
    """Record a human's disposition of an absence as an event, and name its
    effect. Enforces the false-benign PROCESS cardinal: a benign dismissal is
    sourced, human, and recorded — never engine-authored or silent.

    When ``db_path`` is supplied, a local_choice ALSO materializes: it creates a
    PENDING declared-exclusion proposal on the gated write path and links its
    proposal_id into the disposition event."""
    if category not in CATEGORIES:
        return {"error": f"unknown disposition category: {category}"}
    engine_authored = actor.strip().lower().startswith(("engine", "system", "gate"))
    if category in DISMISSALS:
        if engine_authored:
            return {"error": "benign dismissal requires a human authority — the engine "
                    "never dismisses an absence on its own (false-benign cardinal)"}
        if not primary_source.strip():
            return {"error": "local_choice requires a PrimarySource: 'intentionally "
                    "ungoverned' is a sourced decision, not a shrug"}

    materialized: dict[str, Any] | None = None
    if db_path is not None and category in ("local_choice", "arch_material"):
        # Both declared states materialize; neither is a dismissal in the same
        # sense. An exclusion closes the question, an open question keeps it
        # open — but both are written into the graph so a later agent reads a
        # declaration instead of silence, and both are graph writes, so both
        # need a source.
        if not primary_source.strip():
            return {"error": f"{category} cannot be written to the graph without a "
                             "PrimarySource — a declaration in the graph is a sourced "
                             "act, not a note"}
        writer = (materialize_exclusion if category == "local_choice"
                  else materialize_open_question)
        materialized = writer(db_path, store_path, predicate=predicate,
                              primary_source=primary_source, reasoning=reasoning,
                              actor=actor, emit_submission=False)

    authority = "gate" if actor.strip().lower().startswith("gate") else "human"
    return {
        "predicate": predicate,
        "category": category,
        "actor": actor,
        "authority_type": authority,
        "primary_source": primary_source,
        "reasoning": reasoning,
        "effect": _effect(category, predicate),
        "materialized": materialized,   # PENDING exclusion proposal, if db_path given
        "verdict_unchanged": True,       # a disposition never touches the ruling space
    }


def latest_disposition(events: list[dict], predicate: str) -> dict | None:
    """The most recent disposition of a predicate — supports the lifecycle: a
    local_choice today can be superseded by arch_material tomorrow, and the
    history is never erased (every disposition is its own event)."""
    import json

    pred_tokens = _tokens(predicate)
    latest = None
    for ev in events:
        if not str(ev.get("type", "")).startswith("absence.dispositioned:"):
            continue
        try:
            payload = json.loads(ev.get("payload") or "{}")
        except (ValueError, TypeError):
            payload = {}
        if _tokens(payload.get("predicate", "")) & pred_tokens:
            latest = ev  # events arrive in ts order
    return latest
