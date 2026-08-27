/**
 * `/operator/activities` → the ledger feed's `ActivityVM`.
 *
 * The backend projection (`mcp_server/ledger.py::project_activities`) already
 * computes the lifecycle the feed assumes — OPEN/IDLE/SETTLED, resolution,
 * ambient/notable/demanding weight, needs_me, actionable vs incident demand.
 * Only the vocabulary differs, so this is a rename layer, not a second model.
 *
 * Backend rules frontend: where both sides have a notion, the backend's wins
 * and the view model widens to accept it. Nothing is invented here that the
 * server did not say — see `summary` and `family` below for the two places
 * that rule is under strain.
 */

import { getJson, postJson } from "./client";
import { readApiConfig } from "./config";
import { useEffect, useMemo, useState } from "react";
import type {
  ActivityKind,
  ActivityVM,
  ActorKind,
  AuthorityType,
  FeedEvent,
} from "../explorations/lab/ledgerFeedModel";
import { eventTypeLabel } from "../shared/protocolVocabulary";

/** One row of the event log, as the operator plane serves it. */
export type WireEvent = {
  event_id: string;
  ts: number;
  type: string;
  actor?: string;
  authority_type?: string;
  gap_id?: string;
  handoff_id?: string;
  proposal_id?: string;
  batch_id?: string;
  case_id?: string;
  conversation_id?: string;
  causation_event_id?: string;
  subject_node_ids?: string;
  graph_version_before?: string;
  graph_version_after?: string;
  reason?: string;
  payload?: string;
};

/** `project_activities` output, after the 2026-07-27 event-facts fold. */
export type WireActivity = {
  activity_id: string;
  kind: string;
  mint_glue?: string;
  state: "OPEN" | "IDLE" | "SETTLED";
  resolution?: string;
  weight?: string;
  needs_me?: boolean;
  incident?: boolean;
  batch_id?: string;
  first_seen: number;
  last_event_at: number;
  event_count?: number;
  events?: WireEvent[];
  open_actionable?: { on: string; event_id: string }[];
  open_incident?: { on: string; event_id: string }[];
  subject_node_ids?: string[];
  graph_version_before?: string;
  graph_version_after?: string;
  actor?: string;
  authority_type?: string;
};

export type ProposalStatus =
  | "PENDING"
  | "COMMITTED"
  | "REJECTED"
  | "GRAIN_FAILED"
  | "GATE_FAILED"
  | "ENCODE_FAILED";

export type WireProposal = {
  proposal_id: string;
  target_gap_id?: string;
  encoding_json: string;
  claim_level?: string;
  demotion_reason?: string;
  status: ProposalStatus | string;
  primary_source?: string;
  gate_report_json?: string;
  graph_version_before?: string;
  graph_version_after?: string;
  expected_graph_version?: string;
  traversal_receipt_json?: string;
  construction_receipt_json?: string;
  construction_evidence_json?: string;
  construction_reasons_json?: string;
  construction_edge_evidence_json?: string;
  review_exceptions_json?: string;
  review_mode?: string;
  review_required?: number | boolean;
};

export type ProposalNode = {
  id: string;
  label: string;
  text_content?: string;
  semantic_anchor?: string;
  kind?: string;
};

export type ProposalEdge = {
  type: "LEADSTO" | "CONTAINS" | "EXPRESSES" | "NEARTO";
  source_id: string;
  target_id: string;
  label?: string;
  predicate?: string;
};

export type ConstructionEvidenceSpan = {
  unit_id: string;
  quote: string;
  start: number;
  end: number;
  locator?: string;
  source_sha256?: string;
  granularity?: string;
  atom_characters?: number;
  evidence_characters?: number;
};

export type ConstructionEdgeEvidence = {
  source_id: string;
  target_id: string;
  predicate: string;
  source_unit_ids?: string[];
  inferred?: boolean;
  construction_reason?: string;
};

export type ProposalVM = {
  proposal_id: string;
  target_gap_id: string;
  claim_level: string;
  status: ProposalStatus | string;
  nodes: ProposalNode[];
  edges: ProposalEdge[];
  demotion_reason: string;
  primary_source: string;
  gate_report: unknown;
  graph_version_before: string;
  graph_version_after: string;
  expected_graph_version: string;
  traversal_receipt: Record<string, unknown>;
  construction_receipt: Record<string, unknown>;
  construction_evidence: Record<string, ConstructionEvidenceSpan[]>;
  construction_reasons: Record<string, string>;
  construction_edge_evidence: ConstructionEdgeEvidence[];
  review_mode: string;
  review_required: boolean;
  review_exceptions: Array<{ code: string; detail: string }>;
};

export type OperatorHealth = {
  ready: boolean;
  can_commit: boolean;
  pending_count: number;
  needs_me_count: number;
  incident_count: number;
  error?: string;
};

type WireVersionDiff = {
  concepts_added: { id: string; label: string; content_sha: string }[];
  concepts_removed: { id: string; label: string; content_sha: string }[];
  concepts_changed: {
    id: string;
    before_sha: string;
    after_sha: string;
  }[];
  edges_added: [string, string, string, string][];
  edges_removed: [string, string, string, string][];
};

/** Frontend vocabulary is node/edge; legacy storage names stop at the adapter. */
export type VersionDiff = {
  nodes_added: { id: string; label: string; content_sha: string }[];
  nodes_removed: { id: string; label: string; content_sha: string }[];
  nodes_changed: {
    id: string;
    before_sha: string;
    after_sha: string;
  }[];
  edges_added: [string, string, string, string][];
  edges_removed: [string, string, string, string][];
};

const iso = (epochSeconds: number) => new Date(epochSeconds * 1000).toISOString();

function recordedAuthority(value: string | undefined): AuthorityType {
  const authority = (value ?? "").toLowerCase();
  if (
    authority === "human" ||
    authority === "agent" ||
    authority === "gate" ||
    authority === "query" ||
    authority === "construction" ||
    authority === "gate_auto_l1" ||
    authority === "system"
  ) {
    return authority;
  }
  return "system";
}

/**
 * Actor kind from the authority the backend recorded, falling back to the
 * actor string's own shape. An unknown non-empty actor is not evidence that a
 * human acted; `system` is the honest fallback.
 */
function actorKindOf(a: WireActivity): ActorKind {
  const authority = (a.authority_type ?? "").toLowerCase();
  if (authority === "human") return "human";
  if (authority === "agent") return "agent";
  if (authority === "gate") return "gate";
  const actor = (a.actor ?? "").toLowerCase();
  if (actor.startsWith("agent")) return "agent";
  if (actor.startsWith("gate")) return "gate";
  if (actor === "operator") return "human";
  return "system";
}

/**
 * Family is a FEED grouping the backend has no notion of, so it is derived
 * from event types — which are real — rather than invented. Anything that does
 * not match a known type family stays `system` instead of being guessed into a
 * bucket that would then be filtered on as if it meant something.
 */
function familyOf(a: WireActivity): ActivityVM["family"] {
  const types = (a.events ?? []).map((e) => e.type);
  const has = (p: string) => types.some((t) => t.startsWith(p));
  if (has("system.fault")) return "failures";
  if (has("graph.reverted")) return "failures";
  if (has("rationalization.flagged")) return "failures";
  if (has("receipt.issued")) return "conformance";
  if (has("conformance.")) return "conformance";
  if (has("query.") || has("governance.coverage_checked")) return "queries";
  if (a.batch_id) return "batches";
  if (has("graph.created")) return "graph_writes";
  if (has("graph.committed")) return "graph_writes";
  // A draft awaiting judgement is a decision waiting, which is what this
  // family means — not a graph write, because nothing has been written yet and
  // may never be.
  if (has("construction.review")) return "decisions";
  if (has("absence.dispositioned")) return "decisions";
  if (has("proposal.dispositioned") || has("gate.completed")) return "decisions";
  if (has("proposal.submitted") || has("escalation.")) return "proposals";
  return "system";
}

/**
 * A literal presentation of the latest recorded operation, not a governance
 * interpretation.
 *
 * The backend owns summaries by the standing rule, but it does not compose one
 * yet, and the row needs a line of text. The product translates protocol syntax
 * (`graph.created`) into ordinary language (`Graph created`) while preserving
 * the exact event type on the event itself.
 */
function summaryOf(a: WireActivity): string {
  const events = a.events ?? [];
  const latest = events.length ? events[events.length - 1].type : a.kind;
  const subjects = a.subject_node_ids ?? [];
  const where =
    subjects.length === 0
      ? ""
      : subjects.length === 1
        ? ` · ${subjects[0]}`
        : ` · ${subjects.length} nodes`;
  return `${eventTypeLabel(latest)}${where}`;
}

function adaptEvent(e: WireEvent): FeedEvent {
  const authority = recordedAuthority(e.authority_type);
  const kind: ActorKind =
    authority === "human" || authority === "agent" || authority === "gate"
      ? authority
      : "system";
  return {
    event_id: e.event_id,
    type: e.type,
    occurred_at: iso(e.ts),
    // `type` remains the exact technical record; `summary` is its literal UI
    // presentation, not a second account of what happened.
    summary: eventTypeLabel(e.type),
    actor_kind: kind,
    actor_id: e.actor || undefined,
    causation_event_id: e.causation_event_id || undefined,
    // Per-event weight is not projected; the activity carries the weight.
    weight: "notable",
    evidence_refs: e.reason ? [e.reason] : undefined,
  };
}

/** Recency only — an arc that moved in the last few minutes is still warm. */
const HOT_WINDOW_MS = 5 * 60 * 1000;

function adaptActivity(a: WireActivity, now = Date.now()): ActivityVM {
  /* Whether a demand is open is the backend's word, not a re-derivation.

     `needs_me` is `open_actionable && state == "OPEN"`; this read the first
     half only. The two agree on every activity the projector can currently
     produce — nothing that idles ever carries an action, and every settling
     branch empties the list on its way out — so this is a latent divergence,
     not a bug that was showing.

     Worth closing anyway. The agreement rests on four unrelated local
     decisions in one backend function, none of them stated as a rule, none of
     them visible from here; one new terminal event that forgets to clear the
     list and the top bar reports nothing waiting while the queue shows a row.
     The nav made that reachable, because until it existed no second reading of
     the count was on screen to disagree with.

     Incidents keep the length test — that is exactly what the backend's
     `incident` flag is, with no state condition to drop.

     Pinned by `tests/test_demand_count_agrees_with_queue.py`, on the producer,
     because there is no test runner on this side. */
  const openActionable = Boolean(a.needs_me);
  const openIncident = (a.open_incident ?? []).length > 0;
  const events = a.events ?? [];
  const firstWith = (k: keyof WireEvent) =>
    events.map((e) => e[k]).find((v) => Boolean(v)) as string | undefined;

  const subjects = a.subject_node_ids ?? [];

  return {
    activity_id: a.activity_id,
    mint_glue: a.mint_glue,
    // Backend vocabulary, passed through. The feed widened to accept it rather
    // than the projection being bent to the fixture's seven categories.
    kind: a.kind as ActivityKind,
    family: familyOf(a),
    summary: summaryOf(a),
    state: a.state,
    resolution: (a.resolution || undefined) as ActivityVM["resolution"],
    weight: (a.weight ?? "notable") as ActivityVM["weight"],
    demand: openIncident
      ? { kind: "incident", open: true }
      : openActionable
        ? { kind: "actionable", open: true }
        : undefined,
    needs_me: Boolean(a.needs_me),
    hot: now - a.last_event_at * 1000 < HOT_WINDOW_MS,
    actor: {
      kind: actorKindOf(a),
      id: a.actor || undefined,
      label: a.actor || actorKindOf(a),
    },
    authority_type: recordedAuthority(a.authority_type),
    first_seen: iso(a.first_seen),
    last_updated: iso(a.last_event_at),
    graph_revision_before: a.graph_version_before || undefined,
    graph_revision_after: a.graph_version_after || undefined,
    subject_node_ids: subjects.length ? subjects : undefined,
    node_ids: subjects,
    ids: {
      proposal_id: firstWith("proposal_id"),
      gap_id: firstWith("gap_id"),
      handoff_id: firstWith("handoff_id"),
      batch_id: a.batch_id || undefined,
      conversation_id: firstWith("conversation_id"),
    },
    events: events.map(adaptEvent),
    causation: [
      ...new Set(
        events
          .map((event) => event.causation_event_id)
          .filter((eventId): eventId is string => Boolean(eventId)),
      ),
    ],
  };
}

export function isLiveMode(): boolean {
  return readApiConfig().mode === "live";
}

export async function fetchActivities(signal?: AbortSignal): Promise<ActivityVM[]> {
  const rows = await getJson<WireActivity[]>("/operator/activities", signal);
  const now = Date.now();
  return rows.map((r) => adaptActivity(r, now));
}

function parseObject(value: string | undefined): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function parseExceptions(
  value: string | undefined,
): Array<{ code: string; detail: string }> {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (item): item is { code: string; detail: string } =>
          Boolean(item) &&
          typeof item === "object" &&
          typeof item.code === "string",
      )
      .map((item) => ({
        code: item.code,
        detail: typeof item.detail === "string" ? item.detail : "",
      }));
  } catch {
    return [];
  }
}

function parseConstructionEvidence(
  value: string | undefined,
): Record<string, ConstructionEvidenceSpan[]> {
  const parsed = parseObject(value);
  return Object.fromEntries(
    Object.entries(parsed).map(([nodeId, spans]) => [
      nodeId,
      Array.isArray(spans)
        ? spans.filter(
            (span): span is ConstructionEvidenceSpan =>
              Boolean(span) &&
              typeof span === "object" &&
              typeof span.unit_id === "string" &&
              typeof span.quote === "string" &&
              typeof span.start === "number" &&
              typeof span.end === "number",
          )
        : [],
    ]),
  );
}

function parseStringMap(value: string | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(parseObject(value)).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
}

function parseConstructionEdges(
  value: string | undefined,
): ConstructionEdgeEvidence[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (edge): edge is ConstructionEdgeEvidence =>
        Boolean(edge) &&
        typeof edge === "object" &&
        typeof edge.source_id === "string" &&
        typeof edge.target_id === "string" &&
        typeof edge.predicate === "string",
    );
  } catch {
    return [];
  }
}

export function adaptProposal(row: WireProposal): ProposalVM {
  const encoding = parseObject(row.encoding_json);
  const nodes = Array.isArray(encoding.concepts)
    ? (encoding.concepts as ProposalNode[])
    : [];
  const edges = Array.isArray(encoding.edges)
    ? (encoding.edges as ProposalEdge[])
    : [];
  return {
    proposal_id: row.proposal_id,
    target_gap_id: row.target_gap_id ?? "",
    claim_level: row.claim_level ?? "L0",
    status: row.status,
    nodes,
    edges,
    demotion_reason: row.demotion_reason ?? "",
    primary_source: row.primary_source ?? "",
    gate_report: parseObject(row.gate_report_json),
    graph_version_before: row.graph_version_before ?? "",
    graph_version_after: row.graph_version_after ?? "",
    expected_graph_version: row.expected_graph_version ?? "",
    traversal_receipt: parseObject(row.traversal_receipt_json),
    construction_receipt: parseObject(row.construction_receipt_json),
    construction_evidence: parseConstructionEvidence(
      row.construction_evidence_json,
    ),
    construction_reasons: parseStringMap(row.construction_reasons_json),
    construction_edge_evidence: parseConstructionEdges(
      row.construction_edge_evidence_json,
    ),
    review_mode: row.review_mode ?? "",
    review_required: Boolean(row.review_required),
    review_exceptions: parseExceptions(row.review_exceptions_json),
  };
}

export async function fetchProposals(signal?: AbortSignal): Promise<ProposalVM[]> {
  const rows = await getJson<WireProposal[]>("/operator/proposals", signal);
  return rows.map(adaptProposal);
}

export async function fetchProposal(
  proposalId: string,
  signal?: AbortSignal,
): Promise<ProposalVM> {
  const row = await getJson<WireProposal>(
    `/operator/proposals/${encodeURIComponent(proposalId)}`,
    signal,
  );
  return adaptProposal(row);
}

export function fetchOperatorHealth(signal?: AbortSignal) {
  return getJson<OperatorHealth>("/operator/health", signal);
}

/**
 * Why does this node exist?
 *
 * A projection over the event log and proposal store — not
 * a persisted record. The backend is careful about that distinction and so is
 * this: `recorded` holds facts that were written down, `derived` says in words
 * that the chain was assembled rather than stored. Neither may be presented as
 * the other.
 *
 * Three origins, and the third is the honest one: `unprovenanced` means no
 * commit event and no certificate. It is reported plainly rather than filled in
 * with a plausible chain — a fabricated provenance is worse than none.
 *
 * Backend authority: `mcp_server/lineage.py`.
 */
export type LineageOrigin = "evolution" | "construction" | "unprovenanced";

export type LineageStep = {
  step: string;
  id?: string;
  event_id?: string;
  proposal_id?: string;
  gap_id?: string;
  handoff_id?: string;
  fingerprint?: string;
  profile?: string;
  seed_count?: number;
  primary_source?: string;
  authority_type?: string;
  graph_version_after?: string;
  generating_task?: string;
};

export type NodeLineage = {
  node_id: string;
  origin: LineageOrigin;
  chain: LineageStep[];
  /** Facts that were written down. Never inferred. */
  recorded: {
    authority_type?: string;
    primary_source?: string;
    target_gap_id?: string;
    proposal_id?: string;
    decided_at?: string;
    graph_version_before?: string;
    graph_version_after?: string;
    commit_event_id?: string;
    cert_fingerprint?: string;
    cert_profile?: string;
    structural_pass?: boolean | null;
  };
  /** How the chain was assembled, in words. Always shown beside it. */
  derived?: string;
};

export function fetchNodeLineage(nodeId: string, signal?: AbortSignal) {
  return getJson<NodeLineage>(
    `/operator/lineage/${encodeURIComponent(nodeId)}`,
    signal,
  );
}

export function fetchVersionDiff(
  vBefore: string,
  vAfter: string,
  signal?: AbortSignal,
) {
  const q = new URLSearchParams({ v1: vBefore, v2: vAfter });
  return getJson<WireVersionDiff>(`/operator/diff?${q}`, signal).then((diff) => ({
    nodes_added: diff.concepts_added,
    nodes_removed: diff.concepts_removed,
    nodes_changed: diff.concepts_changed,
    edges_added: diff.edges_added,
    edges_removed: diff.edges_removed,
  }));
}

// --- operator dispositions ------------------------------------------------
// Zero new authority: these call the same functions the CLI calls.
// On a graph.md harness, source is taken from the proposal's source_refs
// when the operator does not type one.

export function confirmProposal(proposalId: string, primarySource: string) {
  return postJson(`/operator/proposals/${encodeURIComponent(proposalId)}/confirm`, {
    primary_source: primarySource,
  });
}

export function rejectProposal(proposalId: string, reason: string) {
  return postJson(`/operator/proposals/${encodeURIComponent(proposalId)}/reject`, {
    reason,
  });
}

export function requeueProposal(proposalId: string) {
  return postJson(`/operator/proposals/${encodeURIComponent(proposalId)}/requeue`, {});
}

export function acknowledgeIncident(activityId: string, note: string) {
  return postJson(
    `/operator/incidents/${encodeURIComponent(activityId)}/acknowledge`,
    { note },
  );
}

/**
 * The open escalations, as the operator plane serves them.
 *
 * An escalation is the product's oldest demand: an agent hit a predicate it
 * could not govern and asked a person to encode one. The queue has projected
 * them since the beginning; nothing has ever *read* them, so the pane could
 * only say "Recorded — nothing to decide here" beside a badge reading AWAITING
 * YOU.
 */
export type EscalationVM = {
  handoffId: string;
  question: string;
  ungovernedPredicate: string;
  status: string;
  capturedAt: string;
};

type WireEscalation = {
  handoff_id?: string;
  question?: string;
  ungoverned_predicate?: string;
  status?: string;
  captured_at?: string;
};

export async function fetchEscalations(signal?: AbortSignal): Promise<EscalationVM[]> {
  const rows = await getJson<WireEscalation[]>("/operator/escalations", signal);
  return (rows ?? []).map((row) => ({
    handoffId: String(row.handoff_id ?? ""),
    question: String(row.question ?? ""),
    ungovernedPredicate: String(row.ungoverned_predicate ?? ""),
    status: String(row.status ?? ""),
    capturedAt: String(row.captured_at ?? ""),
  }));
}

/**
 * `dismissed` — this does not need governing. `deferred` — it does, but not now.
 *
 * Both are explicit human closures and the backend accepts nothing else. They
 * are kept apart in the UI for the same reason the backend keeps them apart: a
 * deferral that reads as a dismissal loses the fact that the gap is still real.
 */
export function disposeEscalation(
  handoffId: string,
  disposition: "dismissed" | "deferred",
) {
  return postJson(
    `/operator/escalations/${encodeURIComponent(handoffId)}/dispose`,
    { disposition },
  );
}

/**
 * The advisory prior on an absence — B8 materiality, read-only.
 *
 * Deliberately *only* the read. `POST /operator/absence/dispose` records one of
 * five categories (genuine_gap, retrieval_miss, local_choice, arch_material,
 * insufficient) and is left unwired on purpose: whether that disposition
 * replaces dismiss/defer on an escalation, or accompanies it, is a governance
 * modelling question and not a wiring one. Guessing would mint a second closure
 * vocabulary for the same decision.
 *
 * The classification hides nothing and decides nothing — the backend says so
 * itself in `note`, which is carried through rather than paraphrased.
 */
export type AbsencePrior = {
  predicate: string;
  prior: string;
  advisory: boolean;
  subjectModelled: boolean;
  declaredExclusionFound: boolean;
  note: string;
};

export async function classifyAbsence(
  predicate: string,
  signal?: AbortSignal,
): Promise<AbsencePrior> {
  const res = await getJson<{
    predicate?: string;
    prior?: string;
    advisory?: boolean;
    signals?: Record<string, unknown>;
    note?: string;
  }>(`/operator/absence/classify?predicate=${encodeURIComponent(predicate)}`, signal);
  const signals = res.signals ?? {};
  return {
    predicate: String(res.predicate ?? predicate),
    prior: String(res.prior ?? ""),
    advisory: res.advisory !== false,
    subjectModelled: signals.subject_modeled === true,
    declaredExclusionFound: signals.declared_exclusion_found === true,
    note: String(res.note ?? ""),
  };
}

/**
 * The immutable event log — the record, for export.
 *
 * The other half of "contextual + export". Reading a record *in context* — an
 * activity's own event list, a node's origin — is how an operator answers "why
 * is this here", and that shipped. Export answers a different question, asked
 * by someone who is not looking at the screen: an auditor, a regulator, the
 * version of you in six months. It has no contextual home by definition.
 *
 * Served verbatim. This is the one place the product must not summarise,
 * reorder or prettify: `events()` is described by the backend as "Truth; not a
 * projection", and an export that had been through a view model would be a
 * record of what the UI thought rather than of what happened.
 */
export function fetchEventLog(signal?: AbortSignal) {
  return getJson<WireEvent[]>("/operator/events", signal);
}

/* ---------------------------------------------------------- shared event log

   Logs polled the full log every 5s and Graph every 15s — two independent
   full reads of the same immutable record. This is one store, read by both.
   Polls pass a `?since=` cursor, so an ordinary poll moves only the new rows
   instead of the whole log again.
*/
let sharedEvents: WireEvent[] | null = null;
let sharedRequest: Promise<WireEvent[]> | null = null;
const eventListeners = new Set<() => void>();

function notifyEvents() {
  for (const listener of [...eventListeners]) listener();
}

/** Subscribe to the shared event log. Returns the unsubscribe. */
export function subscribeEventLog(listener: () => void) {
  eventListeners.add(listener);
  return () => {
    eventListeners.delete(listener);
  };
}

/**
 * One fetcher for the whole product. First read is full; after that it appends
 * from a `since` cursor. Every caller sees the same array identity between
 * polls, so a consumer can `useSyncExternalStore` against it.
 */
export function refreshEventLog(signal?: AbortSignal): Promise<WireEvent[]> {
  if (sharedRequest) return sharedRequest;
  const last = sharedEvents?.at(-1)?.event_id;
  const url = last
    ? `/operator/events?since=${encodeURIComponent(last)}`
    : "/operator/events";
  sharedRequest = getJson<WireEvent[]>(url, signal)
    .then((rows) => {
      sharedEvents = last ? [...(sharedEvents ?? []), ...rows] : rows;
      notifyEvents();
      return sharedEvents;
    })
    .finally(() => {
      sharedRequest = null;
    });
  return sharedRequest;
}

/** The current shared log without fetching — `[]` until the first read. */
export function readEventLogSnapshot(): WireEvent[] {
  return sharedEvents ?? [];
}

/** Drop the shared log (a write may have reverted it). Next read is full. */
export function resetEventLog() {
  sharedEvents = null;
}

/** A recorded graph write — commit or revert — as the log and timeline share it. */
export type WriteCheckpoint = {
  id: string;
  kind: "committed" | "reverted";
  ts: number;
  from: string;
  to: string;
  subjects: string[];
  proposalId: string;
  reason: string;
};

const WRITE_EVENT_TYPES = new Set(["graph.committed", "graph.reverted"]);

export function parseSubjectNodeIds(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  if (typeof raw !== "string" || !raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return parsed.map(String).filter(Boolean);
  } catch {
    /* comma-separated leftovers */
  }
  return raw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

export function writeCheckpointsFromEvents(events: WireEvent[]): WriteCheckpoint[] {
  return events
    .filter((event) => WRITE_EVENT_TYPES.has(event.type))
    .map((event): WriteCheckpoint => ({
      id: event.event_id,
      kind: event.type === "graph.reverted" ? "reverted" : "committed",
      ts: Number(event.ts) || 0,
      from: event.graph_version_before ?? "",
      to: event.graph_version_after ?? "",
      subjects: parseSubjectNodeIds(event.subject_node_ids),
      proposalId: event.proposal_id ?? "",
      reason: event.reason ?? "",
    }))
    .sort((a, b) => a.ts - b.ts || a.id.localeCompare(b.id));
}

export function fetchWriteCheckpoints(signal?: AbortSignal) {
  return fetchEventLog(signal).then(writeCheckpointsFromEvents);
}

/**
 * Write checkpoints from the one shared event log.
 *
 * Both Logs (5s) and Graph (15s) polled the full log independently. They now
 * read this store: one fetcher appends from a `since` cursor, and both
 * surfaces derive checkpoints from the same array. `pollMs` is the caller's
 * cadence; the store coalesces concurrent polls into one request.
 */
export function useWriteCheckpoints(pollMs: number): WriteCheckpoint[] {
  const [events, setEvents] = useState<WireEvent[]>(readEventLogSnapshot);
  useEffect(() => {
    if (pollMs <= 0) return;
    const unsubscribe = subscribeEventLog(() =>
      setEvents(readEventLogSnapshot()),
    );
    void refreshEventLog().catch(() => undefined);
    let stopped = false;
    let timer = 0;
    const tick = () => {
      if (stopped) return;
      if (!document.hidden) void refreshEventLog().catch(() => undefined);
      timer = window.setTimeout(tick, pollMs);
    };
    timer = window.setTimeout(tick, pollMs);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      unsubscribe();
    };
  }, [pollMs]);
  return useMemo(() => writeCheckpointsFromEvents(events), [events]);
}
