/**
 * Screen 2 — Ledger feed contract (design/ledger-feed-build-spec.md).
 * The feed renders only ActivityVM; it never recomputes lifecycle or invents urgency.
 */

export type ActivityState = "OPEN" | "IDLE" | "SETTLED";
export type ActivityResolution =
  | "committed"
  | "rejected"
  | "failed"
  | "reverted"
  /** Backend also settles incidents by acknowledgement. */
  | "acked";
export type ActivityWeight = "ambient" | "notable" | "demanding";
export type DemandKind = "actionable" | "incident";
export type ActorKind = "human" | "agent" | "gate" | "system";
/**
 * Values emitted by the event log today, plus the fixture's legacy L1 label.
 * Keep these as recorded authority, rather than collapsing every non-human
 * event into "gate_auto_l1".
 */
export type AuthorityType =
  | "human"
  | "agent"
  | "gate"
  | "query"
  | "construction"
  | "gate_auto_l1"
  | "system";
/**
 * The first four are what `project_activities` actually mints; the rest are
 * fixture categories kept so the lab tape still type-checks. Backend rules
 * frontend — a live row carries the backend's kind unchanged.
 */
export type ActivityKind =
  | "gap"
  | "incident"
  /** A construction run that built a draft and stopped for a person. */
  | "construction"
  | "interrogation"
  | "misc"
  | "gap_arc"
  | "legislation"
  | "conformance"
  | "divergence"
  | "exploration"
  | "batch"
  | "system";

export type ActivityFamily =
  | "decisions"
  | "proposals"
  | "graph_writes"
  | "conformance"
  | "failures"
  | "l1_autonomous"
  | "batches"
  | "queries"
  | "system";

export type FeedEvent = {
  event_id: string;
  type: string;
  occurred_at: string;
  summary: string;
  actor_kind: ActorKind;
  actor_id?: string;
  weight: ActivityWeight;
  outcome?: string;
  causation_event_id?: string;
  inferred?: boolean;
  degraded?: boolean;
  evidence_refs?: string[];
};

export type ActivityVM = {
  activity_id: string;
  /** What the activity was minted against — a job id for a construction
   *  demand, so the row can name the run it is about. */
  mint_glue?: string;
  kind: ActivityKind;
  family: ActivityFamily;
  summary: string;
  state: ActivityState;
  resolution?: ActivityResolution;
  weight: ActivityWeight;
  demand?: { kind: DemandKind; open: boolean };
  needs_me: boolean;
  hot: boolean;
  actor: { kind: ActorKind; id?: string; label: string };
  authority_type: AuthorityType;
  first_seen: string;
  last_updated: string;
  /**
   * ≡ graph_version_before / _after.
   *
   * Two representations are genuinely in play: the lab tape uses ordinal
   * checkpoints (`platformCoreScenario.checkpoint(n)`), while a LIVE row
   * carries the engine's opaque version identifier. Neither is a quantity —
   * they are only compared for equality or handed back to `diff` — so the
   * union is accurate rather than lazy. Never do arithmetic on these.
   */
  graph_revision_before?: string | number;
  graph_revision_after?: string | number;
  /**
   * Subject nodes — preferred focus set (§4.1).
   * Falls back to `node_ids` when omitted.
   */
  subject_node_ids?: string[];
  /** Legacy alias / fallback for subject ids. */
  node_ids: string[];
  /** Optional gap / problem cluster when subjects are empty. */
  cluster_node_ids?: string[];
  ids: {
    proposal_id?: string;
    gap_id?: string;
    handoff_id?: string;
    batch_id?: string;
    conversation_id?: string;
  };
  events: FeedEvent[];
  causation: string[];
  evidence?: string[];
  gate_findings?: string[];
  reconstructed?: boolean;
};

export type FeedPreset =
  | "living"
  | "watch_live"
  | "needs_me"
  | "incidents"
  | "all";

export type FeedFacets = {
  weights: ActivityWeight[];
  actorKinds: ActorKind[];
  families: ActivityFamily[];
  authorities: AuthorityType[];
};

export const EMPTY_FACETS: FeedFacets = {
  weights: [],
  actorKinds: [],
  families: [],
  authorities: [],
};

export const PRESETS: Record<
  FeedPreset,
  { label: string; note: string; facets: FeedFacets; sort: "newest" | "oldest_waiting" }
> = {
  all: {
    label: "All activities",
    note: "Every recorded activity, newest first",
    facets: {
      weights: [],
      actorKinds: [],
      families: [],
      authorities: [],
    },
    sort: "newest",
  },
  living: {
    label: "Living",
    note: "Notable and demanding — ambient hidden",
    facets: {
      weights: ["notable", "demanding"],
      actorKinds: [],
      families: [],
      authorities: [],
    },
    sort: "newest",
  },
  watch_live: {
    label: "Watch live",
    note: "Living plus ambient heartbeat",
    facets: {
      weights: ["ambient", "notable", "demanding"],
      actorKinds: [],
      families: [],
      authorities: [],
    },
    sort: "newest",
  },
  needs_me: {
    label: "Needs me",
    note: "Open actionable demand — oldest waiting first",
    facets: {
      weights: ["demanding"],
      actorKinds: [],
      families: [],
      authorities: [],
    },
    sort: "oldest_waiting",
  },
  incidents: {
    label: "Incidents",
    note: "Unresolved incident demand",
    facets: {
      weights: ["demanding"],
      actorKinds: [],
      families: [],
      authorities: [],
    },
    sort: "newest",
  },
};

/** Fixture VMs — stand-in for events[] → lifecycle reducer → ActivityVM[]. */
export const LEDGER_FEED_FIXTURES: ActivityVM[] = [
  {
    activity_id: "act_escalate_outcome",
    kind: "gap_arc",
    family: "decisions",
    summary:
      "Agent hit UNGOVERNED on outcome classification → escalated for human encode",
    state: "OPEN",
    weight: "demanding",
    demand: { kind: "actionable", open: true },
    needs_me: true,
    hot: true,
    actor: { kind: "agent", id: "agent.discover", label: "discover" },
    authority_type: "human",
    first_seen: "2026-07-18T07:12:00Z",
    last_updated: "2026-07-18T07:14:00Z",
    subject_node_ids: ["checkout-api", "order-ledger"],
    node_ids: ["checkout-api", "order-ledger"],
    cluster_node_ids: ["checkout-api", "order-ledger"],
    ids: {
      gap_id: "GAP-044",
      handoff_id: "HO-118",
      conversation_id: "conv_9f2a",
    },
    events: [
      {
        event_id: "ev_gap_044",
        type: "gap.detected",
        occurred_at: "2026-07-18T07:12:00Z",
        summary: "UNGOVERNED predicate: outcome classification for refund path",
        actor_kind: "agent",
        actor_id: "agent.discover",
        weight: "notable",
      },
      {
        event_id: "ev_esc_118",
        type: "escalation.recorded",
        occurred_at: "2026-07-18T07:14:00Z",
        summary: "Escalation HO-118 opened — Architecture Council",
        actor_kind: "agent",
        actor_id: "agent.discover",
        weight: "demanding",
        causation_event_id: "ev_gap_044",
      },
    ],
    causation: ["ev_gap_044", "ev_esc_118"],
    evidence: ["discover receipt d_7c21", "predicate: refund.outcome.class"],
    reconstructed: true,
  },
  {
    activity_id: "act_dep_rule",
    kind: "legislation",
    family: "graph_writes",
    summary: "DependencyDirectionRule extended — certified L0 commit V12 → V13",
    state: "SETTLED",
    resolution: "committed",
    weight: "notable",
    needs_me: false,
    hot: false,
    actor: { kind: "human", id: "mara.chen", label: "Mara Chen" },
    authority_type: "human",
    first_seen: "2026-07-17T08:10:00Z",
    last_updated: "2026-07-17T09:42:00Z",
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
    ids: {
      proposal_id: "PROP-247",
      gap_id: "GAP-031",
      handoff_id: "HO-092",
    },
    events: [
      {
        event_id: "ev_gap_031",
        type: "gap.detected",
        occurred_at: "2026-07-17T08:10:00Z",
        summary: "Coverage gap on domain→adapter import direction",
        actor_kind: "agent",
        weight: "notable",
        inferred: true,
      },
      {
        event_id: "ev_prop_247",
        type: "proposal.submitted",
        occurred_at: "2026-07-17T08:40:00Z",
        summary: "PROP-247 submitted (L1 requested, later demoted)",
        actor_kind: "agent",
        weight: "notable",
        causation_event_id: "ev_gap_031",
      },
      {
        event_id: "ev_disp_247",
        type: "proposal.dispositioned",
        occurred_at: "2026-07-17T09:05:00Z",
        summary: "Human approved as L0 — package boundaries remain human-owned",
        actor_kind: "human",
        actor_id: "mara.chen",
        weight: "demanding",
        outcome: "approved",
        causation_event_id: "ev_prop_247",
      },
      {
        event_id: "ev_gate_8f21",
        type: "gate.completed",
        occurred_at: "2026-07-17T09:28:00Z",
        summary: "Full gate passed — 12/12 pins",
        actor_kind: "gate",
        weight: "notable",
        outcome: "passed",
        causation_event_id: "ev_disp_247",
      },
      {
        event_id: "ev_commit_13",
        type: "graph.committed",
        occurred_at: "2026-07-17T09:42:00Z",
        summary: "Graph committed V12 → V13",
        actor_kind: "system",
        weight: "notable",
        outcome: "committed",
        causation_event_id: "ev_gate_8f21",
      },
    ],
    causation: [
      "ev_gap_031",
      "ev_prop_247",
      "ev_disp_247",
      "ev_gate_8f21",
      "ev_commit_13",
    ],
    evidence: ["ADR-019", "Closure report gate_8f21"],
    gate_findings: ["Closure: pass", "Distractor battery: pass"],
    reconstructed: true,
  },
  {
    activity_id: "act_ownership_revert",
    kind: "divergence",
    family: "failures",
    summary: "Ownership conflict reverted — V10 replaced by restored V9 as V11",
    state: "OPEN",
    weight: "demanding",
    demand: { kind: "incident", open: true },
    needs_me: false,
    hot: false,
    actor: { kind: "human", id: "ops.lead", label: "Ops lead" },
    authority_type: "human",
    first_seen: "2026-07-16T16:02:00Z",
    last_updated: "2026-07-16T16:18:00Z",
    graph_revision_before: 10,
    graph_revision_after: 11,
    subject_node_ids: ["payments-team", "finance-team", "order-ledger"],
    node_ids: ["payments-team", "finance-team", "order-ledger"],
    cluster_node_ids: ["payments-team", "finance-team", "order-ledger"],
    ids: { proposal_id: "PROP-201" },
    events: [
      {
        event_id: "ev_conf_own",
        type: "conformance.completed",
        occurred_at: "2026-07-16T16:02:00Z",
        summary: "Conformance VIOLATES — dual ownership claim on Order Ledger",
        actor_kind: "gate",
        weight: "demanding",
        outcome: "VIOLATES",
      },
      {
        event_id: "ev_revert_11",
        type: "graph.reverted",
        occurred_at: "2026-07-16T16:18:00Z",
        summary: "Operator restored V9 as V11 — ownership conflict",
        actor_kind: "human",
        weight: "demanding",
        outcome: "reverted",
        causation_event_id: "ev_conf_own",
      },
    ],
    causation: ["ev_conf_own", "ev_revert_11"],
    evidence: ["Conformance report conf_441", "Snapshot sst://platform-core/v9"],
    reconstructed: true,
  },
  {
    activity_id: "act_batch_82fa",
    kind: "batch",
    family: "batches",
    summary: "Batch batch_82fa committed 4 of 5 proposals",
    state: "SETTLED",
    resolution: "committed",
    weight: "notable",
    needs_me: false,
    hot: false,
    actor: { kind: "gate", id: "gate.auto-L1", label: "gate_auto_l1" },
    authority_type: "gate_auto_l1",
    first_seen: "2026-07-15T11:00:00Z",
    last_updated: "2026-07-15T11:48:00Z",
    graph_revision_before: 11,
    graph_revision_after: 12,
    node_ids: ["event-ordering-rule", "tenant-isolation", "retry-backoff"],
    ids: { batch_id: "batch_82fa" },
    events: [
      {
        event_id: "ev_batch_eval",
        type: "proposal.dispositioned",
        occurred_at: "2026-07-15T11:20:00Z",
        summary: "4 closures passed · 1 proposal requeued",
        actor_kind: "gate",
        weight: "notable",
        outcome: "mixed",
      },
      {
        event_id: "ev_batch_commit",
        type: "graph.committed",
        occurred_at: "2026-07-15T11:48:00Z",
        summary: "Shared distractor battery passed · V11 → V12",
        actor_kind: "system",
        weight: "notable",
        outcome: "committed",
        causation_event_id: "ev_batch_eval",
      },
    ],
    causation: ["ev_batch_eval", "ev_batch_commit"],
    gate_findings: ["4/5 individual closures", "1 requeued", "Distractor: pass"],
    reconstructed: true,
  },
  {
    activity_id: "act_receipt_091",
    kind: "conformance",
    family: "conformance",
    summary: "Receipt RCPT-0091 issued against graph V11",
    state: "SETTLED",
    resolution: "committed",
    weight: "notable",
    needs_me: false,
    hot: false,
    actor: { kind: "system", id: "harness", label: "harness" },
    authority_type: "human",
    first_seen: "2026-07-14T14:02:00Z",
    last_updated: "2026-07-14T14:05:00Z",
    graph_revision_before: 11,
    graph_revision_after: 11,
    node_ids: ["service-boundary"],
    ids: {},
    events: [
      {
        event_id: "ev_conf_ok",
        type: "conformance.completed",
        occurred_at: "2026-07-14T14:02:00Z",
        summary: "Diff a812f60 GOVERNED against V11",
        actor_kind: "gate",
        weight: "notable",
        outcome: "GOVERNED",
      },
      {
        event_id: "ev_rcpt",
        type: "receipt.issued",
        occurred_at: "2026-07-14T14:05:00Z",
        summary: "Receipt RCPT-0091 valid",
        actor_kind: "system",
        weight: "notable",
        causation_event_id: "ev_conf_ok",
      },
    ],
    causation: ["ev_conf_ok", "ev_rcpt"],
    reconstructed: true,
  },
  {
    activity_id: "act_fault_sqlite",
    kind: "system",
    family: "system",
    summary: "system.fault — SQLite lock timeout during gate batch",
    state: "OPEN",
    weight: "demanding",
    demand: { kind: "incident", open: true },
    needs_me: false,
    hot: false,
    actor: { kind: "system", id: "engine", label: "engine" },
    authority_type: "gate_auto_l1",
    first_seen: "2026-07-18T06:55:00Z",
    last_updated: "2026-07-18T06:55:00Z",
    node_ids: [],
    ids: { batch_id: "batch_82fa" },
    events: [
      {
        event_id: "ev_fault_1",
        type: "system.fault",
        occurred_at: "2026-07-18T06:55:00Z",
        summary: "engine_degraded: SQLITE_BUSY on proposals write",
        actor_kind: "system",
        weight: "demanding",
        degraded: true,
        outcome: "fault",
      },
    ],
    causation: ["ev_fault_1"],
    reconstructed: false,
  },
  {
    activity_id: "act_orient_read",
    kind: "exploration",
    family: "queries",
    summary: "Agent orient — landmarks for platform-core (ambient read)",
    state: "IDLE",
    weight: "ambient",
    needs_me: false,
    hot: false,
    actor: { kind: "agent", id: "agent.orient", label: "orient" },
    authority_type: "gate_auto_l1",
    first_seen: "2026-07-18T08:01:00Z",
    last_updated: "2026-07-18T08:01:00Z",
    node_ids: ["platform-core"],
    ids: { conversation_id: "conv_aa01" },
    events: [
      {
        event_id: "ev_orient_1",
        type: "query.orient",
        occurred_at: "2026-07-18T08:01:00Z",
        summary: "orient completed — 6 landmarks",
        actor_kind: "agent",
        weight: "ambient",
      },
    ],
    causation: ["ev_orient_1"],
    reconstructed: false,
  },
  {
    activity_id: "act_snapshot_idle",
    kind: "system",
    family: "system",
    summary: "Snapshot sst://platform-core/v13 recorded",
    state: "IDLE",
    weight: "ambient",
    needs_me: false,
    hot: false,
    actor: { kind: "system", id: "snapshots", label: "snapshots" },
    authority_type: "gate_auto_l1",
    first_seen: "2026-07-17T09:43:00Z",
    last_updated: "2026-07-17T09:43:00Z",
    node_ids: [],
    ids: {},
    events: [
      {
        event_id: "ev_snap_13",
        type: "snapshot.recorded",
        occurred_at: "2026-07-17T09:43:00Z",
        summary: "Label sst://platform-core/v13",
        actor_kind: "system",
        weight: "ambient",
      },
    ],
    causation: ["ev_snap_13"],
    reconstructed: false,
  },
  {
    activity_id: "act_await_encode",
    kind: "gap_arc",
    family: "proposals",
    summary: "PROP-255 awaiting your disposition — tenant isolation edge case",
    state: "OPEN",
    weight: "demanding",
    demand: { kind: "actionable", open: true },
    needs_me: true,
    hot: false,
    actor: { kind: "agent", id: "agent.propose", label: "propose" },
    authority_type: "human",
    first_seen: "2026-07-16T09:00:00Z",
    last_updated: "2026-07-17T18:20:00Z",
    subject_node_ids: ["tenant-isolation", "checkout-api"],
    node_ids: ["tenant-isolation", "checkout-api"],
    ids: {
      proposal_id: "PROP-255",
      gap_id: "GAP-040",
      handoff_id: "HO-110",
    },
    events: [
      {
        event_id: "ev_prop_255",
        type: "proposal.submitted",
        occurred_at: "2026-07-16T09:00:00Z",
        summary: "PROP-255 submitted — L0 requested",
        actor_kind: "agent",
        weight: "notable",
      },
      {
        event_id: "ev_gate_fail_255",
        type: "gate.completed",
        occurred_at: "2026-07-16T10:12:00Z",
        summary: "Structural gate failed — distractor collision",
        actor_kind: "gate",
        weight: "demanding",
        outcome: "failed",
        causation_event_id: "ev_prop_255",
      },
      {
        event_id: "ev_requeue_255",
        type: "proposal.dispositioned",
        occurred_at: "2026-07-17T18:20:00Z",
        summary: "Requeued after demotion — awaiting human",
        actor_kind: "system",
        weight: "demanding",
        outcome: "requeued",
        causation_event_id: "ev_gate_fail_255",
      },
    ],
    causation: ["ev_prop_255", "ev_gate_fail_255", "ev_requeue_255"],
    evidence: ["Distractor report gate_d9aa"],
    gate_findings: ["Closure: fail", "Distractor: collision on tenant pin"],
    reconstructed: true,
  },
];

function facetMatch(activity: ActivityVM, facets: FeedFacets) {
  if (facets.weights.length && !facets.weights.includes(activity.weight)) {
    return false;
  }
  if (
    facets.actorKinds.length &&
    !facets.actorKinds.includes(activity.actor.kind)
  ) {
    return false;
  }
  if (facets.families.length && !facets.families.includes(activity.family)) {
    return false;
  }
  if (
    facets.authorities.length &&
    !facets.authorities.includes(activity.authority_type)
  ) {
    return false;
  }
  return true;
}

export function filterActivities(
  activities: ActivityVM[],
  preset: FeedPreset,
  facets: FeedFacets,
): ActivityVM[] {
  const presetDef = PRESETS[preset];
  const merged: FeedFacets = {
    weights: facets.weights.length ? facets.weights : presetDef.facets.weights,
    actorKinds: facets.actorKinds.length
      ? facets.actorKinds
      : presetDef.facets.actorKinds,
    families: facets.families.length
      ? facets.families
      : presetDef.facets.families,
    authorities: facets.authorities.length
      ? facets.authorities
      : presetDef.facets.authorities,
  };

  let next = activities.filter((activity) => facetMatch(activity, merged));

  if (preset === "needs_me") {
    next = next.filter((activity) => activity.needs_me);
  }
  if (preset === "incidents") {
    next = next.filter(
      (activity) =>
        activity.demand?.kind === "incident" && activity.demand.open,
    );
  }

  const sort = presetDef.sort;
  next = [...next].sort((a, b) => {
    const aTime = Date.parse(a.last_updated);
    const bTime = Date.parse(b.last_updated);
    if (sort === "oldest_waiting") {
      return Date.parse(a.first_seen) - Date.parse(b.first_seen);
    }
    return bTime - aTime;
  });

  return next;
}

export function relativeTime(iso: string, now = Date.now()) {
  const delta = Math.max(0, now - Date.parse(iso));
  const minutes = Math.floor(delta / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function stateLabel(activity: ActivityVM) {
  if (activity.needs_me) return "awaiting you";
  if (activity.state === "OPEN" && activity.demand?.kind === "incident") {
    return "incident open";
  }
  if (activity.state === "OPEN") return "in progress";
  if (activity.state === "IDLE") return "idle";
  if (activity.resolution) return activity.resolution;
  return "settled";
}

export function kindLabel(kind: ActivityKind) {
  switch (kind) {
    case "gap":
    case "gap_arc":
      return "gap";
    case "incident":
      return "incident";
    case "interrogation":
      return "query";
    case "misc":
      return "activity";
    case "legislation":
      return "legislation";
    case "conformance":
      return "conformance";
    case "divergence":
      return "divergence";
    case "exploration":
      return "exploration";
    case "batch":
      return "batch";
    case "system":
      return "system";
  }
}
