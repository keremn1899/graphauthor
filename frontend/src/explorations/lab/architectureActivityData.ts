import type { GraphData } from "@antv/g6";

export type EventTone = "success" | "warning" | "danger" | "info" | "neutral";

export type DomainEventType =
  | "gap.detected"
  | "escalation.recorded"
  | "proposal.submitted"
  | "proposal.dispositioned"
  | "gate.completed"
  | "graph.committed"
  | "graph.reverted"
  | "conformance.completed"
  | "receipt.issued"
  | "system.fault";

export type DomainEvent = {
  id: string;
  type: DomainEventType;
  time: string;
  summary: string;
  actor: string;
  tone: EventTone;
  payload: string;
};

export type Activity = {
  id: string;
  date: string;
  time: string;
  title: string;
  description: string;
  category:
    | "decisions"
    | "proposals"
    | "graph"
    | "conformance"
    | "failures"
    | "batches"
    | "system";
  tone: EventTone;
  outcome: string;
  actor: string;
  authority: string;
  graph: string;
  version?: string;
  reference: string;
  rationale: string;
  evidence: string[];
  graphDiff?: { added: string[]; changed: string[]; removed: string[] };
  findings?: string[];
  actions: string[];
  events: DomainEvent[];
  badges?: string[];
  l1?: boolean;
  human?: boolean;
};

export const ACTIVITIES: readonly Activity[] = [
  {
    id: "activity_dep_rule",
    date: "Today · 17 July",
    time: "09:42",
    title: "DependencyDirectionRule extended",
    description:
      "A recurring coverage gap was resolved with a certified L0 rule and committed to the architecture graph.",
    category: "graph",
    tone: "success",
    outcome: "Committed",
    actor: "Mara Chen",
    authority: "Architecture Council",
    graph: "platform-core",
    version: "V12 → V13",
    reference: "WORK-1842 · GAP-031 · PROP-247",
    rationale:
      "Three conformance runs found imports flowing from domain packages into adapter packages without an explicit governing decision. The proposed L1 rule was demoted because package boundaries remain a human-owned policy surface.",
    evidence: [
      "3 recurring violations across checkout-api and ledger-worker",
      "ADR-019: Ports remain inward-facing",
      "Closure report gate_8f21 · 12/12 pins passed",
    ],
    graphDiff: {
      added: [
        "Concept: DependencyDirectionRule",
        "CONSTRAINS DomainPackage → AdapterPackage",
      ],
      changed: ["PackageBoundary now governed by DependencyDirectionRule"],
      removed: [],
    },
    findings: [
      "Individual closure passed",
      "Shared distractor battery passed",
      "No contradiction with LayeringRule",
    ],
    actions: ["Open graph V13", "View proposal", "Inspect gate report"],
    badges: ["Human decision", "Full gate"],
    human: true,
    events: [
      {
        id: "evt_01HT8J1",
        type: "gap.detected",
        time: "08:51:04",
        summary: "Dependency direction had no governing predicate",
        actor: "conformance-worker",
        tone: "warning",
        payload:
          '{ "gap_id": "GAP-031", "predicate": "CONSTRAINS", "classification": "potentially_legislatable", "recurrence_count": 3 }',
      },
      {
        id: "evt_01HT8K9",
        type: "escalation.recorded",
        time: "08:54:19",
        summary: "Gap assigned to Architecture Council",
        actor: "policy-router",
        tone: "info",
        payload:
          '{ "gap_id": "GAP-031", "requested_authority": "architecture_council", "owner": "mara.chen" }',
      },
      {
        id: "evt_01HT8P2",
        type: "proposal.submitted",
        time: "09:06:42",
        summary: "L1 rule proposed for dependency direction",
        actor: "builder-agent-07",
        tone: "info",
        payload:
          '{ "proposal_id": "PROP-247", "requested_level": "L1", "concepts": 1, "edges": 1 }',
      },
      {
        id: "evt_01HT8R7",
        type: "proposal.dispositioned",
        time: "09:14:08",
        summary: "Proposal demoted from L1 to L0 and approved",
        actor: "mara.chen",
        tone: "warning",
        payload:
          '{ "prior_status": "submitted_l1", "new_status": "approved_l0", "reason": "policy ownership requires human authority" }',
      },
      {
        id: "evt_01HT8V4",
        type: "gate.completed",
        time: "09:38:33",
        summary: "Full certification gate passed",
        actor: "gate-runner",
        tone: "success",
        payload:
          '{ "gate_tier": "full", "outcome": "pass", "closure": "pass", "distractor": "pass", "pins": 12, "duration_ms": 48311 }',
      },
      {
        id: "evt_01HT8W0",
        type: "graph.committed",
        time: "09:42:17",
        summary: "Certified change committed as graph V13",
        actor: "mara.chen",
        tone: "success",
        payload:
          '{ "graph_version_before": 12, "graph_version_after": 13, "proposal_id": "PROP-247", "snapshot": "sst://platform-core/v13" }',
      },
    ],
  },
  {
    id: "activity_batch_82fa",
    date: "Today · 17 July",
    time: "08:16",
    title: "Batch batch_82fa committed 4 of 5 proposals",
    description:
      "Four independent closures passed; one ownership proposal was requeued after failing semantic closure.",
    category: "batches",
    tone: "warning",
    outcome: "Partial commit",
    actor: "Graph writer",
    authority: "L1 autonomous",
    graph: "platform-core",
    version: "V11 → V12",
    reference: "BATCH-82FA · 5 proposals",
    rationale:
      "The batch shared one distractor battery, but each proposal retained an independent closure result. PROP-241 could not establish that TeamOwnsService was entailed by the current evidence.",
    evidence: [
      "4/5 individual closures passed",
      "1 shared distractor battery passed",
      "PROP-241 requeued with two missing evidence references",
    ],
    graphDiff: {
      added: [
        "EventOrderingRule",
        "TenantIsolationBoundary",
        "RetryBackoffPolicy",
        "ServiceOwnershipRule",
      ],
      changed: ["ServiceBoundary cardinality clarified"],
      removed: [],
    },
    findings: [
      "PROP-241: closure failed",
      "Ownership evidence names a team alias absent from the graph",
    ],
    actions: ["Open batch", "Review requeued proposal", "Compare V11 / V12"],
    badges: ["Batch", "L1"],
    l1: true,
    events: [
      {
        id: "evt_01HT71A",
        type: "gate.completed",
        time: "08:11:22",
        summary: "Batch gate passed with one proposal-level failure",
        actor: "gate-runner",
        tone: "warning",
        payload:
          '{ "batch_id": "batch_82fa", "covered": 5, "closure_passed": 4, "closure_failed": 1, "distractor": "pass" }',
      },
      {
        id: "evt_01HT72B",
        type: "proposal.dispositioned",
        time: "08:12:03",
        summary: "PROP-241 requeued for missing ownership evidence",
        actor: "gate-runner",
        tone: "danger",
        payload:
          '{ "proposal_id": "PROP-241", "prior_status": "gating", "new_status": "requeued", "reason": "closure_failed" }',
      },
      {
        id: "evt_01HT75D",
        type: "graph.committed",
        time: "08:16:48",
        summary: "Four certified proposals committed as V12",
        actor: "graph-writer",
        tone: "success",
        payload:
          '{ "graph_version_before": 11, "graph_version_after": 12, "batch_id": "batch_82fa", "proposal_count": 4 }',
      },
    ],
  },
  {
    id: "activity_conformance_checkout",
    date: "Today · 17 July",
    time: "07:34",
    title: "Checkout retry change is not governed",
    description:
      "Conformance blocked receipt eligibility because the retry budget is absent from graph V11.",
    category: "failures",
    tone: "danger",
    outcome: "Blocked",
    actor: "Conformance worker",
    authority: "Policy gate",
    graph: "platform-core",
    version: "Against V11",
    reference: "WORK-1839 · diff 7c4d9e1",
    rationale:
      "The code diff introduces a five-attempt retry loop for payment authorization. Existing decisions govern idempotency and backoff shape, but not the maximum attempt budget.",
    evidence: [
      "Diff 7c4d9e1 · payments/authorize.ts +18 −4",
      "Ungoverned literal: MAX_ATTEMPTS = 5",
      "Related rule RetryBackoffPolicy covers delay only",
    ],
    findings: [
      "1 architectural gap detected",
      "2 governed changes passed",
      "Receipt ineligible until the gap is dispositioned",
    ],
    actions: ["Open diff", "Escalate gap", "View conformance report"],
    badges: ["Failure", "Receipt withheld"],
    events: [
      {
        id: "evt_01HT5M0",
        type: "gap.detected",
        time: "07:33:51",
        summary: "Retry attempt budget lacks architectural coverage",
        actor: "conformance-worker",
        tone: "warning",
        payload:
          '{ "gap_id": "GAP-030", "predicate": "LIMITS", "concepts": ["PaymentAuthorization", "RetryAttempt"], "classification": "potentially_legislatable" }',
      },
      {
        id: "evt_01HT5M8",
        type: "conformance.completed",
        time: "07:34:09",
        summary: "Diff failed conformance against graph V11",
        actor: "conformance-worker",
        tone: "danger",
        payload:
          '{ "revision": "7c4d9e1", "graph_version": 11, "verdict": "ungoverned", "violations": 0, "gaps": 1, "receipt_eligible": false }',
      },
    ],
  },
  {
    id: "activity_receipt_issued",
    date: "Yesterday · 16 July",
    time: "17:08",
    title: "Receipt issued for ledger partitioning change",
    description:
      "Revision a812f60 was certified against graph V11 and may proceed while that graph version remains valid.",
    category: "conformance",
    tone: "success",
    outcome: "Receipt issued",
    actor: "Receipt issuer",
    authority: "Policy gate",
    graph: "platform-core",
    version: "Graph V11",
    reference: "WORK-1828 · a812f60 · RCPT-0091",
    rationale:
      "The partitioning change follows the governing EventOrderingRule and preserves the committed tenant isolation boundary.",
    evidence: [
      "Conformance report conf_71b9",
      "Graph snapshot sst://platform-core/v11",
      "Code revision a812f60",
    ],
    findings: ["0 violations", "0 gaps", "4 governing decisions matched"],
    actions: ["Open receipt", "View governed decisions", "Inspect diff"],
    badges: ["Conformant"],
    events: [
      {
        id: "evt_01HSWQ3",
        type: "conformance.completed",
        time: "17:07:31",
        summary: "Ledger partitioning diff passed conformance",
        actor: "conformance-worker",
        tone: "success",
        payload:
          '{ "revision": "a812f60", "graph_version": 11, "verdict": "governed", "violations": 0, "gaps": 0, "receipt_eligible": true }',
      },
      {
        id: "evt_01HSWQ9",
        type: "receipt.issued",
        time: "17:08:02",
        summary: "Receipt RCPT-0091 issued",
        actor: "receipt-issuer",
        tone: "success",
        payload:
          '{ "receipt_id": "RCPT-0091", "graph_version": 11, "revision": "a812f60", "status": "valid" }',
      },
    ],
  },
  {
    id: "activity_revert_v10",
    date: "Yesterday · 16 July",
    time: "14:22",
    title: "Graph V10 reverted after ownership conflict",
    description:
      "An operator restored the V9 snapshot as V11; the original V10 commit remains in the audit chronology.",
    category: "graph",
    tone: "danger",
    outcome: "Reverted",
    actor: "Iris Okafor",
    authority: "Graph operator",
    graph: "platform-core",
    version: "V10 → V11 (restores V9)",
    reference: "INC-204 · COMMIT-00A7",
    rationale:
      "V10 assigned OrderLedger to Payments while the service registry retained Finance as owner. The conflict invalidated ownership-sensitive receipts issued after V10.",
    evidence: [
      "Service registry owner: Finance",
      "Graph V10 owner: Payments",
      "Incident INC-204 approved emergency restoration",
    ],
    graphDiff: {
      added: ["Finance OWNS OrderLedger"],
      changed: ["Active snapshot restored to V9 contents"],
      removed: ["Payments OWNS OrderLedger"],
    },
    findings: [
      "3 receipts marked for re-conformance",
      "V10 preserved as an immutable historical snapshot",
    ],
    actions: ["Compare snapshots", "Open incident", "Review affected receipts"],
    badges: ["Operator action", "Re-conformance required"],
    human: true,
    events: [
      {
        id: "evt_01HSTN1",
        type: "graph.reverted",
        time: "14:22:44",
        summary: "V9 contents restored in new graph version V11",
        actor: "iris.okafor",
        tone: "danger",
        payload:
          '{ "version_replaced": 10, "version_restored": 9, "version_created": 11, "reason": "ownership conflict", "affected_commits": ["COMMIT-00A7"] }',
      },
    ],
  },
] as const;

const V10_DATA: GraphData = {
  nodes: [
    { id: "platform-core", data: { label: "Platform Core", kind: "system" }, style: { x: 350, y: 90 } },
    { id: "domain-package", data: { label: "Domain Package", kind: "concept" }, style: { x: 200, y: 220 } },
    { id: "adapter-package", data: { label: "Adapter Package", kind: "concept" }, style: { x: 450, y: 220 } },
    { id: "service-boundary", data: { label: "Service Boundary", kind: "concept" }, style: { x: 350, y: 280 } },
    { id: "order-ledger", data: { label: "Order Ledger", kind: "service" }, style: { x: 280, y: 420 } },
    { id: "checkout-api", data: { label: "Checkout API", kind: "service" }, style: { x: 400, y: 420 } },
    { id: "payments-team", data: { label: "Payments", kind: "actor" }, style: { x: 200, y: 580 } },
    { id: "finance-team", data: { label: "Finance", kind: "actor" }, style: { x: 450, y: 580 } },
  ],
  edges: [
    { id: "e-platform-domain", source: "platform-core", target: "domain-package", data: { label: "CONTAINS" } },
    { id: "e-platform-adapter", source: "platform-core", target: "adapter-package", data: { label: "CONTAINS" } },
    { id: "e-boundary-ledger", source: "service-boundary", target: "order-ledger", data: { label: "BOUNDS" } },
    { id: "e-boundary-checkout", source: "service-boundary", target: "checkout-api", data: { label: "BOUNDS" } },
    { id: "e-payments-ledger", source: "payments-team", target: "order-ledger", data: { label: "OWNS" } },
  ],
};

const V11_DATA: GraphData = {
  nodes: structuredClone(V10_DATA.nodes),
  edges: [
    ...(structuredClone(V10_DATA.edges) ?? []).filter(
      (edge) => edge.id !== "e-payments-ledger",
    ),
    {
      id: "e-finance-ledger",
      source: "finance-team",
      target: "order-ledger",
      data: { label: "OWNS" },
    },
  ],
};

const V12_DATA: GraphData = {
  nodes: [
    ...(structuredClone(V11_DATA.nodes) ?? []),
    { id: "event-ordering-rule", data: { label: "Event Ordering Rule", kind: "rule" }, style: { x: 100, y: 350 } },
    { id: "tenant-isolation", data: { label: "Tenant Isolation", kind: "rule" }, style: { x: 450, y: 350 } },
    { id: "retry-backoff", data: { label: "Retry Backoff", kind: "rule" }, style: { x: 100, y: 500 } },
    { id: "ownership-rule", data: { label: "Ownership Rule", kind: "rule" }, style: { x: 450, y: 500 } },
  ],
  edges: [
    ...(structuredClone(V11_DATA.edges) ?? []),
    { id: "e-ordering-ledger", source: "event-ordering-rule", target: "order-ledger", data: { label: "GOVERNS" } },
    { id: "e-tenant-ledger", source: "tenant-isolation", target: "order-ledger", data: { label: "CONSTRAINS" } },
    { id: "e-tenant-checkout", source: "tenant-isolation", target: "checkout-api", data: { label: "CONSTRAINS" } },
    { id: "e-retry-checkout", source: "retry-backoff", target: "checkout-api", data: { label: "GOVERNS" } },
    { id: "e-ownership-finance", source: "ownership-rule", target: "finance-team", data: { label: "AUTHORIZES" } },
    { id: "e-ownership-payments", source: "ownership-rule", target: "payments-team", data: { label: "AUTHORIZES" } },
    { id: "e-boundary-rule", source: "service-boundary", target: "ownership-rule", data: { label: "REQUIRES" } },
  ],
};

const V13_DATA: GraphData = {
  nodes: [
    ...(structuredClone(V12_DATA.nodes) ?? []),
    {
      id: "dependency-direction-rule",
      data: { label: "Dependency Direction", kind: "rule" },
      style: { x: 350, y: 580 },
    },
  ],
  edges: [
    ...(structuredClone(V12_DATA.edges) ?? []),
    {
      id: "e-dependency-direction",
      source: "domain-package",
      target: "adapter-package",
      data: { label: "CONSTRAINS" },
    },
    {
      id: "e-dependency-boundary",
      source: "dependency-direction-rule",
      target: "service-boundary",
      data: { label: "GOVERNS" },
    },
  ],
};

export type GraphCheckpoint = {
  id: string;
  version: number;
  label: string;
  shortLabel: string;
  occurredAt: string;
  eventType: "baseline" | "graph.committed" | "graph.reverted";
  activityId?: string;
  graphData: GraphData;
  changedNodeIds: string[];
  changedEdgeIds: string[];
};

export const GRAPH_CHECKPOINTS: readonly GraphCheckpoint[] = [
  {
    id: "checkpoint-v10",
    version: 10,
    label: "Ownership change active",
    shortLabel: "V10",
    occurredAt: "16 Jul · 13:47",
    eventType: "baseline",
    graphData: V10_DATA,
    changedNodeIds: [],
    changedEdgeIds: [],
  },
  {
    id: "checkpoint-v11",
    version: 11,
    label: "Ownership conflict reverted",
    shortLabel: "V11",
    occurredAt: "16 Jul · 14:22",
    eventType: "graph.reverted",
    activityId: "activity_revert_v10",
    graphData: V11_DATA,
    changedNodeIds: ["order-ledger", "payments-team", "finance-team"],
    changedEdgeIds: ["e-payments-ledger", "e-finance-ledger"],
  },
  {
    id: "checkpoint-v12",
    version: 12,
    label: "Batch batch_82fa committed",
    shortLabel: "V12",
    occurredAt: "17 Jul · 08:16",
    eventType: "graph.committed",
    activityId: "activity_batch_82fa",
    graphData: V12_DATA,
    changedNodeIds: [
      "event-ordering-rule",
      "tenant-isolation",
      "retry-backoff",
      "ownership-rule",
    ],
    changedEdgeIds: [
      "e-ordering-ledger",
      "e-tenant-ledger",
      "e-tenant-checkout",
      "e-retry-checkout",
      "e-ownership-finance",
      "e-ownership-payments",
      "e-boundary-rule",
    ],
  },
  {
    id: "checkpoint-v13",
    version: 13,
    label: "DependencyDirectionRule extended",
    shortLabel: "V13",
    occurredAt: "17 Jul · 09:42",
    eventType: "graph.committed",
    activityId: "activity_dep_rule",
    graphData: V13_DATA,
    changedNodeIds: ["dependency-direction-rule", "domain-package", "adapter-package"],
    changedEdgeIds: ["e-dependency-direction", "e-dependency-boundary"],
  },
] as const;

export const ACTIVITY_BY_ID = new Map(
  ACTIVITIES.map((activity) => [activity.id, activity]),
);

export const GRAPH_WRITE_ACTIVITIES = GRAPH_CHECKPOINTS.flatMap((checkpoint) => {
  if (!checkpoint.activityId) return [];
  const activity = ACTIVITY_BY_ID.get(checkpoint.activityId);
  return activity ? [activity] : [];
});
