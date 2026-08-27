/**
 * Live ledger sim: event tape → lifecycle reducer → ActivityVM[].
 * Lab-only stand-in until the real events table + reducer ship.
 */

import type {
  ActivityKind,
  ActivityFamily,
  ActivityResolution,
  ActivityState,
  ActivityVM,
  ActivityWeight,
  ActorKind,
  AuthorityType,
  DemandKind,
  FeedEvent,
} from "./ledgerFeedModel";

export const SIM_ORIGIN_MS = Date.parse("2026-07-18T08:00:00Z");
export const HOT_WINDOW_MS = 1800;
export const SIM_DURATION_MS = 180_000;

export type TapeEvent = {
  at_ms: number;
  event_id: string;
  type: string;
  summary: string;
  actor_kind: ActorKind;
  actor_id?: string;
  actor_label?: string;
  weight: ActivityWeight;
  outcome?: string;
  causation_event_id?: string;
  inferred?: boolean;
  degraded?: boolean;
  evidence_refs?: string[];
  /** Glue id — reducer never invents grouping */
  activity_id: string;
  kind?: ActivityKind;
  family?: ActivityFamily;
  activity_summary?: string;
  authority_type?: AuthorityType;
  demand?: { kind: DemandKind; open: boolean } | null;
  needs_me?: boolean;
  state?: ActivityState;
  resolution?: ActivityResolution;
  graph_revision_before?: number;
  graph_revision_after?: number;
  node_ids?: string[];
  subject_node_ids?: string[];
  cluster_node_ids?: string[];
  ids?: ActivityVM["ids"];
  evidence?: string[];
  gate_findings?: string[];
  reconstructed?: boolean;
};

export type OperatorInject =
  | {
      kind: "disposition";
      activity_id: string;
      outcome: "approved" | "rejected" | "requeued";
    }
  | { kind: "acknowledge"; activity_id: string };

function isoAt(at_ms: number) {
  return new Date(SIM_ORIGIN_MS + at_ms).toISOString();
}

/** Morning on platform-core — ambient → escalate → aging queue → legislation → incident → fault → batch */
export const MORNING_TAPE: TapeEvent[] = [
  {
    at_ms: 0,
    event_id: "ev_snap_boot",
    type: "snapshot.recorded",
    summary: "Label sst://platform-core/v12",
    actor_kind: "system",
    actor_id: "snapshots",
    actor_label: "snapshots",
    weight: "ambient",
    activity_id: "act_snap_boot",
    kind: "system",
    family: "system",
    activity_summary: "Snapshot sst://platform-core/v12 recorded",
    authority_type: "gate_auto_l1",
    state: "IDLE",
  },
  {
    at_ms: 4_000,
    event_id: "ev_orient_1",
    type: "query.orient",
    summary: "orient completed — 6 landmarks",
    actor_kind: "agent",
    actor_id: "agent.orient",
    actor_label: "orient",
    weight: "ambient",
    activity_id: "act_orient_1",
    kind: "exploration",
    family: "queries",
    activity_summary: "Agent orient — landmarks for platform-core",
    authority_type: "gate_auto_l1",
    state: "IDLE",
    node_ids: ["platform-core"],
    ids: { conversation_id: "conv_aa01" },
  },
  {
    at_ms: 14_000,
    event_id: "ev_gap_044",
    type: "gap.detected",
    summary: "UNGOVERNED predicate: outcome classification for refund path",
    actor_kind: "agent",
    actor_id: "agent.discover",
    actor_label: "discover",
    weight: "notable",
    activity_id: "act_escalate_outcome",
    kind: "gap_arc",
    family: "decisions",
    activity_summary:
      "Agent hit UNGOVERNED on outcome classification → escalated for human encode",
    authority_type: "human",
    state: "OPEN",
    subject_node_ids: ["checkout-api", "order-ledger"],
    node_ids: ["checkout-api", "order-ledger"],
    cluster_node_ids: ["checkout-api", "order-ledger"],
    ids: { gap_id: "GAP-044", conversation_id: "conv_9f2a" },
    evidence: ["discover receipt d_7c21", "predicate: refund.outcome.class"],
    reconstructed: true,
  },
  {
    at_ms: 20_000,
    event_id: "ev_esc_118",
    type: "escalation.recorded",
    summary: "Escalation HO-118 opened — Architecture Council",
    actor_kind: "agent",
    actor_id: "agent.discover",
    actor_label: "discover",
    weight: "demanding",
    causation_event_id: "ev_gap_044",
    activity_id: "act_escalate_outcome",
    activity_summary:
      "Agent hit UNGOVERNED on outcome classification → escalated for human encode",
    demand: { kind: "actionable", open: true },
    needs_me: true,
    state: "OPEN",
    ids: {
      gap_id: "GAP-044",
      handoff_id: "HO-118",
      conversation_id: "conv_9f2a",
    },
  },
  {
    at_ms: 32_000,
    event_id: "ev_prop_255",
    type: "proposal.submitted",
    summary: "PROP-255 submitted — L0 requested",
    actor_kind: "agent",
    actor_id: "agent.propose",
    actor_label: "propose",
    weight: "notable",
    activity_id: "act_await_encode",
    kind: "gap_arc",
    family: "proposals",
    activity_summary:
      "PROP-255 awaiting your disposition — tenant isolation edge case",
    authority_type: "human",
    state: "OPEN",
    demand: { kind: "actionable", open: true },
    needs_me: true,
    subject_node_ids: ["tenant-isolation", "checkout-api"],
    node_ids: ["tenant-isolation", "checkout-api"],
    ids: {
      proposal_id: "PROP-255",
      gap_id: "GAP-040",
      handoff_id: "HO-110",
    },
    reconstructed: true,
  },
  {
    at_ms: 40_000,
    event_id: "ev_gate_fail_255",
    type: "gate.completed",
    summary: "Structural gate failed — distractor collision",
    actor_kind: "gate",
    actor_label: "gate",
    weight: "demanding",
    outcome: "failed",
    causation_event_id: "ev_prop_255",
    activity_id: "act_await_encode",
    gate_findings: ["Closure: fail", "Distractor: collision on tenant pin"],
    evidence: ["Distractor report gate_d9aa"],
  },
  {
    at_ms: 48_000,
    event_id: "ev_requeue_255",
    type: "proposal.dispositioned",
    summary: "Requeued after demotion — awaiting human",
    actor_kind: "system",
    actor_label: "system",
    weight: "demanding",
    outcome: "requeued",
    causation_event_id: "ev_gate_fail_255",
    activity_id: "act_await_encode",
    needs_me: true,
    demand: { kind: "actionable", open: true },
    state: "OPEN",
  },
  {
    at_ms: 55_000,
    event_id: "ev_orient_2",
    type: "query.orient",
    summary: "orient — checkout neighborhood",
    actor_kind: "agent",
    actor_id: "agent.orient",
    actor_label: "orient",
    weight: "ambient",
    activity_id: "act_orient_2",
    kind: "exploration",
    family: "queries",
    activity_summary: "Agent orient — checkout neighborhood",
    authority_type: "gate_auto_l1",
    state: "IDLE",
    node_ids: ["checkout-api"],
  },
  {
    at_ms: 62_000,
    event_id: "ev_gap_031",
    type: "gap.detected",
    summary: "Coverage gap on domain→adapter import direction",
    actor_kind: "agent",
    actor_label: "discover",
    weight: "notable",
    inferred: true,
    activity_id: "act_dep_rule",
    kind: "legislation",
    family: "graph_writes",
    activity_summary:
      "GAP-031 domain→adapter imports — awaiting Dependency Direction legislation",
    authority_type: "human",
    state: "OPEN",
    subject_node_ids: ["domain-package", "adapter-package"],
    node_ids: ["domain-package", "adapter-package"],
    cluster_node_ids: ["domain-package", "adapter-package"],
    ids: { gap_id: "GAP-031" },
    reconstructed: true,
  },
  {
    at_ms: 72_000,
    event_id: "ev_prop_247",
    type: "proposal.submitted",
    summary: "PROP-247 submitted (L1 requested, later demoted)",
    actor_kind: "agent",
    actor_label: "propose",
    weight: "demanding",
    causation_event_id: "ev_gap_031",
    activity_id: "act_dep_rule",
    activity_summary:
      "PROP-247 pending — Ports Inward · Import Boundary · Dependency Direction",
    state: "OPEN",
    demand: { kind: "actionable", open: true },
    needs_me: true,
    subject_node_ids: [
      "dependency-direction-rule",
      "ports-inward-policy",
      "import-boundary",
    ],
    node_ids: [
      "dependency-direction-rule",
      "ports-inward-policy",
      "import-boundary",
    ],
    ids: { proposal_id: "PROP-247", gap_id: "GAP-031", handoff_id: "HO-092" },
  },
  {
    at_ms: 84_000,
    event_id: "ev_disp_247",
    type: "proposal.dispositioned",
    summary: "Human approved as L0 — package boundaries remain human-owned",
    actor_kind: "human",
    actor_id: "mara.chen",
    actor_label: "Mara Chen",
    weight: "demanding",
    outcome: "approved",
    causation_event_id: "ev_prop_247",
    activity_id: "act_dep_rule",
    needs_me: false,
    demand: { kind: "actionable", open: false },
  },
  {
    at_ms: 94_000,
    event_id: "ev_gate_8f21",
    type: "gate.completed",
    summary: "Full gate passed — 12/12 pins",
    actor_kind: "gate",
    actor_label: "gate",
    weight: "notable",
    outcome: "passed",
    causation_event_id: "ev_disp_247",
    activity_id: "act_dep_rule",
    gate_findings: ["Closure: pass", "Distractor battery: pass"],
    evidence: ["ADR-019", "Closure report gate_8f21"],
  },
  {
    at_ms: 104_000,
    event_id: "ev_commit_13",
    type: "graph.committed",
    summary: "Graph committed V12 → V13",
    actor_kind: "system",
    actor_label: "system",
    weight: "notable",
    outcome: "committed",
    causation_event_id: "ev_gate_8f21",
    activity_id: "act_dep_rule",
    activity_summary:
      "DependencyDirectionRule extended — certified L0 commit V12 → V13",
    state: "SETTLED",
    resolution: "committed",
    demand: null,
    needs_me: false,
    graph_revision_before: 12,
    graph_revision_after: 13,
    subject_node_ids: [
      "dependency-direction-rule",
      "domain-package",
      "adapter-package",
    ],
    node_ids: [
      "dependency-direction-rule",
      "domain-package",
      "adapter-package",
    ],
  },
  {
    at_ms: 118_000,
    event_id: "ev_conf_own",
    type: "conformance.completed",
    summary: "Conformance VIOLATES — dual ownership claim on Order Ledger",
    actor_kind: "gate",
    actor_label: "gate",
    weight: "demanding",
    outcome: "VIOLATES",
    activity_id: "act_ownership_revert",
    kind: "divergence",
    family: "failures",
    activity_summary:
      "Ownership conflict reverted — V10 replaced by restored V9 as V11",
    authority_type: "human",
    state: "OPEN",
    demand: { kind: "incident", open: true },
    needs_me: false,
    subject_node_ids: ["payments-team", "finance-team", "order-ledger"],
    node_ids: ["payments-team", "finance-team", "order-ledger"],
    cluster_node_ids: ["payments-team", "finance-team", "order-ledger"],
    ids: { proposal_id: "PROP-201" },
    evidence: ["Conformance report conf_441"],
    reconstructed: true,
  },
  {
    at_ms: 132_000,
    event_id: "ev_revert_11",
    type: "graph.reverted",
    summary: "Operator restored V9 as V11 — ownership conflict",
    actor_kind: "human",
    actor_id: "ops.lead",
    actor_label: "Ops lead",
    weight: "demanding",
    outcome: "reverted",
    causation_event_id: "ev_conf_own",
    activity_id: "act_ownership_revert",
    graph_revision_before: 10,
    graph_revision_after: 11,
    evidence: [
      "Conformance report conf_441",
      "Snapshot sst://platform-core/v9",
    ],
  },
  {
    at_ms: 142_000,
    event_id: "ev_fault_1",
    type: "system.fault",
    summary: "engine_degraded: SQLITE_BUSY on proposals write",
    actor_kind: "system",
    actor_id: "engine",
    actor_label: "engine",
    weight: "demanding",
    outcome: "fault",
    degraded: true,
    activity_id: "act_fault_sqlite",
    kind: "system",
    family: "system",
    activity_summary: "system.fault — SQLite lock timeout during gate batch",
    authority_type: "gate_auto_l1",
    state: "OPEN",
    demand: { kind: "incident", open: true },
    ids: { batch_id: "batch_82fa" },
  },
  {
    at_ms: 152_000,
    event_id: "ev_batch_eval",
    type: "proposal.dispositioned",
    summary: "4 closures passed · 1 proposal requeued",
    actor_kind: "gate",
    actor_label: "gate_auto_l1",
    weight: "notable",
    outcome: "mixed",
    activity_id: "act_batch_82fa",
    kind: "batch",
    family: "batches",
    activity_summary: "Batch batch_82fa committed 4 of 5 proposals",
    authority_type: "gate_auto_l1",
    state: "OPEN",
    node_ids: ["event-ordering-rule", "tenant-isolation", "retry-backoff"],
    ids: { batch_id: "batch_82fa" },
    gate_findings: ["4/5 individual closures", "1 requeued"],
    reconstructed: true,
  },
  {
    at_ms: 165_000,
    event_id: "ev_batch_commit",
    type: "graph.committed",
    summary: "Shared distractor battery passed · V11 → V12",
    actor_kind: "system",
    actor_label: "system",
    weight: "notable",
    outcome: "committed",
    causation_event_id: "ev_batch_eval",
    activity_id: "act_batch_82fa",
    state: "SETTLED",
    resolution: "committed",
    graph_revision_before: 11,
    graph_revision_after: 12,
    gate_findings: ["4/5 individual closures", "1 requeued", "Distractor: pass"],
  },
  {
    at_ms: 172_000,
    event_id: "ev_orient_3",
    type: "query.orient",
    summary: "orient — after V13 landmarks",
    actor_kind: "agent",
    actor_id: "agent.orient",
    actor_label: "orient",
    weight: "ambient",
    activity_id: "act_orient_3",
    kind: "exploration",
    family: "queries",
    activity_summary: "Agent orient — post-commit landmarks",
    authority_type: "gate_auto_l1",
    state: "IDLE",
    node_ids: ["platform-core", "dependency-direction-rule"],
  },
];

function toFeedEvent(beat: TapeEvent, at_ms: number): FeedEvent {
  return {
    event_id: beat.event_id,
    type: beat.type,
    occurred_at: isoAt(at_ms),
    summary: beat.summary,
    actor_kind: beat.actor_kind,
    actor_id: beat.actor_id,
    weight: beat.weight,
    outcome: beat.outcome,
    causation_event_id: beat.causation_event_id,
    inferred: beat.inferred,
    degraded: beat.degraded,
    evidence_refs: beat.evidence_refs,
  };
}

function applyBeat(
  activities: Map<string, ActivityVM>,
  beat: TapeEvent,
): Map<string, ActivityVM> {
  const next = new Map(activities);
  const existing = next.get(beat.activity_id);
  const occurred = isoAt(beat.at_ms);
  const feedEvent = toFeedEvent(beat, beat.at_ms);

  if (!existing) {
    const created: ActivityVM = {
      activity_id: beat.activity_id,
      kind: beat.kind ?? "system",
      family: beat.family ?? "system",
      summary: beat.activity_summary ?? beat.summary,
      state: beat.state ?? "OPEN",
      resolution: beat.resolution,
      weight: beat.weight,
      demand: beat.demand === null ? undefined : beat.demand,
      needs_me: beat.needs_me ?? false,
      hot: false,
      actor: {
        kind: beat.actor_kind,
        id: beat.actor_id,
        label: beat.actor_label ?? beat.actor_kind,
      },
      authority_type: beat.authority_type ?? "human",
      first_seen: occurred,
      last_updated: occurred,
      graph_revision_before: beat.graph_revision_before,
      graph_revision_after: beat.graph_revision_after,
      subject_node_ids: beat.subject_node_ids,
      node_ids: beat.node_ids ?? beat.subject_node_ids ?? [],
      cluster_node_ids: beat.cluster_node_ids,
      ids: beat.ids ?? {},
      events: [feedEvent],
      causation: [beat.event_id],
      evidence: beat.evidence,
      gate_findings: beat.gate_findings,
      reconstructed: beat.reconstructed,
    };
    next.set(beat.activity_id, created);
    return next;
  }

  const events = [...existing.events, feedEvent];
  const causation = beat.causation_event_id
    ? existing.causation.includes(beat.event_id)
      ? existing.causation
      : [...existing.causation, beat.event_id]
    : existing.causation.includes(beat.event_id)
      ? existing.causation
      : [...existing.causation, beat.event_id];

  const updated: ActivityVM = {
    ...existing,
    summary: beat.activity_summary ?? existing.summary,
    kind: beat.kind ?? existing.kind,
    family: beat.family ?? existing.family,
    state: beat.state ?? existing.state,
    resolution: beat.resolution ?? existing.resolution,
    weight:
      beat.weight === "demanding" || existing.weight === "demanding"
        ? "demanding"
        : beat.weight === "notable" || existing.weight === "notable"
          ? "notable"
          : "ambient",
    demand:
      beat.demand === null
        ? undefined
        : (beat.demand ?? existing.demand),
    needs_me: beat.needs_me ?? existing.needs_me,
    actor: beat.actor_label
      ? {
          kind: beat.actor_kind,
          id: beat.actor_id,
          label: beat.actor_label,
        }
      : existing.actor,
    authority_type: beat.authority_type ?? existing.authority_type,
    last_updated: occurred,
    graph_revision_before:
      beat.graph_revision_before ?? existing.graph_revision_before,
    graph_revision_after:
      beat.graph_revision_after ?? existing.graph_revision_after,
    subject_node_ids: beat.subject_node_ids ?? existing.subject_node_ids,
    node_ids: beat.node_ids ?? beat.subject_node_ids ?? existing.node_ids,
    cluster_node_ids: beat.cluster_node_ids ?? existing.cluster_node_ids,
    ids: beat.ids ? { ...existing.ids, ...beat.ids } : existing.ids,
    events,
    causation,
    evidence: beat.evidence ?? existing.evidence,
    gate_findings: beat.gate_findings ?? existing.gate_findings,
    reconstructed: beat.reconstructed ?? existing.reconstructed,
  };
  next.set(beat.activity_id, updated);
  return next;
}

function withHot(activities: ActivityVM[], clockMs: number): ActivityVM[] {
  return activities.map((activity) => {
    const last = Date.parse(activity.last_updated) - SIM_ORIGIN_MS;
    const hot = clockMs - last >= 0 && clockMs - last <= HOT_WINDOW_MS;
    return { ...activity, hot };
  });
}

export function reduceTapeToClock(
  tape: TapeEvent[],
  clockMs: number,
  injects: TapeEvent[] = [],
): ActivityVM[] {
  const combined = [...tape, ...injects]
    .filter((beat) => beat.at_ms <= clockMs)
    .sort((a, b) => a.at_ms - b.at_ms || a.event_id.localeCompare(b.event_id));

  let map = new Map<string, ActivityVM>();
  for (const beat of combined) {
    map = applyBeat(map, beat);
  }
  return withHot([...map.values()], clockMs);
}

export function buildOperatorInject(
  inject: OperatorInject,
  at_ms: number,
): TapeEvent {
  if (inject.kind === "acknowledge") {
    return {
      at_ms,
      event_id: `ev_ack_${inject.activity_id}_${at_ms}`,
      type: "incident.acknowledged",
      summary: "Incident acknowledged (lab-local operator store)",
      actor_kind: "human",
      actor_id: "you",
      actor_label: "you",
      weight: "notable",
      activity_id: inject.activity_id,
      demand: { kind: "incident", open: false },
      needs_me: false,
      state: "SETTLED",
      resolution: "committed",
    };
  }

  return {
    at_ms,
    event_id: `ev_op_${inject.activity_id}_${at_ms}`,
    type: "proposal.dispositioned",
    summary: `Operator ${inject.outcome} (lab-local — not wired to API)`,
    actor_kind: "human",
    actor_id: "you",
    actor_label: "you",
    weight: "demanding",
    outcome: inject.outcome,
    activity_id: inject.activity_id,
    demand: null,
    needs_me: false,
    state: "SETTLED",
    resolution:
      inject.outcome === "approved"
        ? "committed"
        : inject.outcome === "rejected"
          ? "rejected"
          : "failed",
  };
}

export function formatLabClock(clockMs: number) {
  const totalSec = Math.floor(clockMs / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function nextBeatAt(tape: TapeEvent[], clockMs: number) {
  return tape.find((beat) => beat.at_ms > clockMs)?.at_ms ?? null;
}
