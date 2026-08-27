/**
 * Ambient Canvas LOD fixture — large enough that far-zoom leaf soup would hurt.
 * Previous labs top out ~13–20 nodes; this graph is ~90 nodes / ~120 edges.
 *
 * importance / is_landmark mimic map_overview (§5) until a BFF payload exists.
 * No verdict / role colours — layout + LOD only.
 */

import type { EdgeData, GraphData, NodeData } from "@antv/g6";
import { lensVisualKindOf } from "../g6/lensEdgeOptions";

export type AmbientLodNodeData = {
  label: string;
  kind: string;
  /** 0…1 — betweenness stand-in; landmarks near 1. */
  importance: number;
  is_landmark: boolean;
  /** CONTAINS parent / region root id. */
  region_id?: string;
};

type Spec = {
  id: string;
  label: string;
  kind: string;
  region?: string;
  /** Raw score before normalize — higher = more important. */
  score: number;
  landmark?: boolean;
  x: number;
  y: number;
};

type EdgeSpec = {
  id: string;
  source: string;
  target: string;
  label: string;
};

const REGION_ROOTS: Spec[] = [
  {
    id: "platform-core",
    label: "Platform Core",
    kind: "system",
    score: 100,
    landmark: true,
    x: 900,
    y: 80,
  },
  {
    id: "commerce",
    label: "Commerce",
    kind: "region",
    region: "platform-core",
    score: 88,
    landmark: true,
    x: 280,
    y: 260,
  },
  {
    id: "payments",
    label: "Payments",
    kind: "region",
    region: "platform-core",
    score: 86,
    landmark: true,
    x: 700,
    y: 260,
  },
  {
    id: "identity",
    label: "Identity",
    kind: "region",
    region: "platform-core",
    score: 84,
    landmark: true,
    x: 1100,
    y: 260,
  },
  {
    id: "messaging",
    label: "Messaging",
    kind: "region",
    region: "platform-core",
    score: 80,
    landmark: true,
    x: 1500,
    y: 260,
  },
  {
    id: "analytics",
    label: "Analytics",
    kind: "region",
    region: "platform-core",
    score: 78,
    landmark: true,
    x: 500,
    y: 520,
  },
  {
    id: "ops",
    label: "Platform Ops",
    kind: "region",
    region: "platform-core",
    score: 76,
    landmark: true,
    x: 1300,
    y: 520,
  },
  {
    id: "service-boundary",
    label: "Service Boundary",
    kind: "concept",
    region: "platform-core",
    score: 72,
    landmark: true,
    x: 900,
    y: 400,
  },
];

function leafGrid(
  region: string,
  prefix: string,
  kind: string,
  count: number,
  originX: number,
  originY: number,
  cols: number,
  scoreBase: number,
): Spec[] {
  const out: Spec[] = [];
  for (let i = 0; i < count; i++) {
    const col = i % cols;
    const row = Math.floor(i / cols);
    out.push({
      id: `${prefix}-${i + 1}`,
      label: `${prefix.replace(/-/g, " ")} ${i + 1}`,
      kind,
      region,
      score: scoreBase - i * 0.35,
      x: originX + col * 88,
      y: originY + row * 78,
    });
  }
  return out;
}

const HUBS: Spec[] = [
  {
    id: "checkout-api",
    label: "Checkout API",
    kind: "service",
    region: "commerce",
    score: 64,
    x: 200,
    y: 420,
  },
  {
    id: "order-ledger",
    label: "Order Ledger",
    kind: "service",
    region: "commerce",
    score: 66,
    x: 360,
    y: 420,
  },
  {
    id: "cart-service",
    label: "Cart Service",
    kind: "service",
    region: "commerce",
    score: 52,
    x: 160,
    y: 540,
  },
  {
    id: "catalog-api",
    label: "Catalog API",
    kind: "service",
    region: "commerce",
    score: 50,
    x: 400,
    y: 540,
  },
  {
    id: "payment-gateway",
    label: "Payment Gateway",
    kind: "service",
    region: "payments",
    score: 62,
    x: 640,
    y: 420,
  },
  {
    id: "settlement",
    label: "Settlement",
    kind: "service",
    region: "payments",
    score: 58,
    x: 800,
    y: 420,
  },
  {
    id: "auth-service",
    label: "Auth Service",
    kind: "service",
    region: "identity",
    score: 60,
    x: 1040,
    y: 420,
  },
  {
    id: "session-store",
    label: "Session Store",
    kind: "service",
    region: "identity",
    score: 48,
    x: 1200,
    y: 420,
  },
  {
    id: "event-bus",
    label: "Event Bus",
    kind: "service",
    region: "messaging",
    score: 61,
    x: 1440,
    y: 420,
  },
  {
    id: "notify-worker",
    label: "Notify Worker",
    kind: "service",
    region: "messaging",
    score: 46,
    x: 1600,
    y: 420,
  },
  {
    id: "metrics-lake",
    label: "Metrics Lake",
    kind: "service",
    region: "analytics",
    score: 54,
    x: 440,
    y: 680,
  },
  {
    id: "funnel-jobs",
    label: "Funnel Jobs",
    kind: "service",
    region: "analytics",
    score: 42,
    x: 600,
    y: 680,
  },
  {
    id: "deploy-control",
    label: "Deploy Control",
    kind: "service",
    region: "ops",
    score: 55,
    x: 1240,
    y: 680,
  },
  {
    id: "slo-board",
    label: "SLO Board",
    kind: "service",
    region: "ops",
    score: 44,
    x: 1400,
    y: 680,
  },
  {
    id: "ownership-rule",
    label: "Ownership Rule",
    kind: "rule",
    region: "service-boundary",
    score: 56,
    x: 860,
    y: 560,
  },
  {
    id: "tenant-isolation",
    label: "Tenant Isolation",
    kind: "rule",
    region: "identity",
    score: 57,
    x: 1120,
    y: 560,
  },
  {
    id: "dependency-direction-rule",
    label: "Dependency Direction",
    kind: "rule",
    region: "platform-core",
    score: 59,
    x: 920,
    y: 680,
  },
  {
    id: "domain-package",
    label: "Domain Package",
    kind: "concept",
    region: "platform-core",
    score: 53,
    x: 760,
    y: 680,
  },
  {
    id: "adapter-package",
    label: "Adapter Package",
    kind: "concept",
    region: "platform-core",
    score: 51,
    x: 1080,
    y: 680,
  },
];

const LEAVES: Spec[] = [
  ...leafGrid("commerce", "sku", "concept", 10, 40, 640, 5, 28),
  ...leafGrid("commerce", "promo", "concept", 8, 40, 820, 4, 24),
  ...leafGrid("payments", "rail", "concept", 9, 560, 540, 3, 26),
  ...leafGrid("payments", "fx", "concept", 6, 560, 800, 3, 20),
  ...leafGrid("identity", "claim", "concept", 8, 980, 640, 4, 25),
  ...leafGrid("identity", "mfa", "concept", 6, 980, 820, 3, 18),
  ...leafGrid("messaging", "topic", "concept", 10, 1380, 540, 5, 22),
  ...leafGrid("messaging", "dlq", "concept", 5, 1380, 720, 5, 16),
  ...leafGrid("analytics", "cohort", "concept", 8, 300, 800, 4, 19),
  ...leafGrid("ops", "runbook", "concept", 7, 1180, 800, 4, 17),
];

function buildEdges(nodes: Spec[]): EdgeSpec[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: EdgeSpec[] = [];
  let n = 0;
  const add = (source: string, target: string, label: string) => {
    if (!byId.has(source) || !byId.has(target)) return;
    edges.push({ id: `e-${n++}`, source, target, label });
  };

  for (const node of nodes) {
    if (node.region && byId.has(node.region)) {
      add(node.region, node.id, "CONTAINS");
    }
  }

  // Cross-region / governance spines (landmark–landmark connectivity at far zoom)
  add("service-boundary", "checkout-api", "BOUNDS");
  add("service-boundary", "order-ledger", "BOUNDS");
  add("service-boundary", "payment-gateway", "BOUNDS");
  add("service-boundary", "auth-service", "BOUNDS");
  add("ownership-rule", "order-ledger", "GOVERNS");
  add("tenant-isolation", "auth-service", "CONSTRAINS");
  add("tenant-isolation", "checkout-api", "CONSTRAINS");
  add("dependency-direction-rule", "service-boundary", "GOVERNS");
  add("domain-package", "adapter-package", "CONSTRAINS");
  add("checkout-api", "order-ledger", "LEADSTO");
  add("checkout-api", "payment-gateway", "LEADSTO");
  add("payment-gateway", "settlement", "LEADSTO");
  add("order-ledger", "event-bus", "LEADSTO");
  add("auth-service", "checkout-api", "LEADSTO");
  add("event-bus", "notify-worker", "LEADSTO");
  add("event-bus", "metrics-lake", "LEADSTO");
  add("cart-service", "checkout-api", "LEADSTO");
  add("catalog-api", "cart-service", "LEADSTO");
  add("funnel-jobs", "metrics-lake", "LEADSTO");
  add("deploy-control", "slo-board", "NEARTO");
  add("commerce", "payments", "NEARTO");
  add("identity", "commerce", "NEARTO");
  add("messaging", "analytics", "NEARTO");

  // Attach a few leaves to hubs so topology isn't only CONTAINS
  for (const leaf of nodes.filter((node) => node.score < 30)) {
    const hub =
      leaf.region === "commerce"
        ? "order-ledger"
        : leaf.region === "payments"
          ? "payment-gateway"
          : leaf.region === "identity"
            ? "auth-service"
            : leaf.region === "messaging"
              ? "event-bus"
              : leaf.region === "analytics"
                ? "metrics-lake"
                : leaf.region === "ops"
                  ? "deploy-control"
                  : "platform-core";
    if (leaf.id.endsWith("-1") || leaf.id.endsWith("-2") || leaf.id.endsWith("-3")) {
      add(hub, leaf.id, "EXPRESSES");
    }
  }

  return edges;
}

function finalize(specs: Spec[]): {
  nodes: NodeData[];
  edges: EdgeData[];
  landmarks: string[];
  graph_version: number;
} {
  // Deduplicate region CONTAINS edges that REGION_ROOTS already imply via region field
  const unique = new Map<string, Spec>();
  for (const spec of specs) unique.set(spec.id, spec);
  const list = [...unique.values()];
  const maxScore = Math.max(...list.map((s) => s.score));
  const minScore = Math.min(...list.map((s) => s.score));
  const span = Math.max(1e-6, maxScore - minScore);

  const nodes: NodeData[] = list.map((spec) => {
    const importance = (spec.score - minScore) / span;
    return {
      id: spec.id,
      data: {
        label: spec.label,
        kind: spec.kind,
        importance,
        is_landmark: Boolean(spec.landmark),
        region_id: spec.region,
      } satisfies AmbientLodNodeData,
      style: { x: spec.x, y: spec.y },
    };
  });

  const edges = buildEdges(list).map((edge): EdgeData => {
    const label = edge.label;
    const kind = lensVisualKindOf({
      source: edge.source,
      target: edge.target,
      data: { label },
    });
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: { label, kind },
    };
  });

  const landmarks = list.filter((s) => s.landmark).map((s) => s.id);
  return { nodes, edges, landmarks, graph_version: 13 };
}

const BUILT = finalize([...REGION_ROOTS, ...HUBS, ...LEAVES]);

export const AMBIENT_LOD_GRAPH_VERSION = BUILT.graph_version;
export const AMBIENT_LOD_LANDMARKS = BUILT.landmarks;
export const AMBIENT_LOD_NODE_COUNT = BUILT.nodes.length;
export const AMBIENT_LOD_EDGE_COUNT = BUILT.edges.length;

export function createAmbientLodGraph(): GraphData {
  return structuredClone({
    nodes: BUILT.nodes,
    edges: BUILT.edges,
  });
}

export function importanceOf(datum: NodeData): number {
  const value = Number(datum.data?.importance);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

export function isLandmark(datum: NodeData): boolean {
  return Boolean(datum.data?.is_landmark);
}

export function labelOf(datum: NodeData): string {
  return String(datum.data?.label ?? datum.id);
}
