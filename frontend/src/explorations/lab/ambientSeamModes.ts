import type { EdgeData, GraphData, NodeData } from "@antv/g6";
import {
  annotateFocus,
  getProposal,
  PROPOSAL_247,
} from "./platformCoreScenario";

/**
 * Canvas-linkage seam modes, overlaid on the ambient fixture.
 * Focus lighting is binary white/black (grayDark) — separate from mauve dark theme.
 */

export type AmbientSeamMode =
  | "idle"
  | "focus-group"
  | "focus-single"
  | "proposal"
  | "version-diff";

export const AMBIENT_SEAM_MODES: Array<{
  id: AmbientSeamMode;
  label: string;
  note: string;
}> = [
  { id: "idle", label: "Idle", note: "Theme colours · no focus overlay" },
  {
    id: "focus-group",
    label: "Focus · group",
    note: "Field inverts (white/black); ownership cluster lit",
  },
  {
    id: "focus-single",
    label: "Focus · single",
    note: "Point focus — checkout-api and its edges",
  },
  {
    id: "proposal",
    label: "Proposal",
    note: "PROP-247 encoding grafted · lit seeds",
  },
  {
    id: "version-diff",
    label: "Version diff",
    note: "Added / removed / touched on ambient fixture",
  },
];

/** Ambient stand-in for ownership actor cluster (payments-team etc. aren't in fixture). */
export const AMBIENT_FOCUS_GROUP_IDS = [
  "ownership-rule",
  "order-ledger",
  "checkout-api",
] as const;

export const AMBIENT_FOCUS_SINGLE_IDS = ["checkout-api"] as const;

const FOCUS_ON = 1;
const FOCUS_OFF = 0;

type DiffKind = "added" | "removed" | "touched" | "unchanged";

function cloneGraph(data: GraphData): GraphData {
  return structuredClone(data);
}

function graftProposal(data: GraphData, proposalId = "PROP-247"): GraphData {
  const encoding = getProposal(proposalId);
  if (!encoding) return data;

  const graph = cloneGraph(data);
  const nodes: NodeData[] = [...(graph.nodes ?? [])];
  const edges: EdgeData[] = [...(graph.edges ?? [])];
  const existingNodeIds = new Set(nodes.map((n) => String(n.id)));
  const existingEdgeIds = new Set(edges.map((e) => String(e.id)));

  for (const node of encoding.nodes) {
    const id = String(node.id);
    if (existingNodeIds.has(id)) {
      const idx = nodes.findIndex((n) => String(n.id) === id);
      if (idx >= 0) {
        nodes[idx] = {
          ...nodes[idx],
          data: { ...nodes[idx]!.data, ...node.data, proposed: true },
        };
      }
      continue;
    }
    nodes.push({
      ...structuredClone(node),
      data: {
        ...node.data,
        importance: 0.7,
        is_landmark: true,
        region_id: "ops",
      },
    });
  }

  for (const edge of encoding.edges) {
    if (existingEdgeIds.has(String(edge.id))) continue;
    // Skip CONTAINS grafts when hulls already express membership as combos —
    // still fine as drawn edges on the edge-mode ambient fixture.
    edges.push(structuredClone(edge));
  }

  return { ...graph, nodes, edges };
}

/**
 * Demo delta on the ambient snapshot (no V12 checkpoint here):
 * graft PROP-247 newcomers as added, mark commit subjects touched,
 * park one retired leaf as removed.
 */
function ambientVersionDiff(data: GraphData): GraphData {
  const graph = graftProposal(cloneGraph(data), PROPOSAL_247.proposal_id);
  const addedIds = new Set(["ports-inward-policy", "import-boundary"]);
  const touchedIds = new Set(PROPOSAL_247.commit_subject_ids);
  const removedId = "funnel-jobs";

  const nodes: NodeData[] = (graph.nodes ?? []).map((node) => {
    const id = String(node.id);
    let diff: DiffKind = "unchanged";
    if (addedIds.has(id)) diff = "added";
    else if (touchedIds.has(id)) diff = "touched";
    return {
      ...node,
      data: {
        ...node.data,
        intensity: diff === "added" ? FOCUS_ON : FOCUS_OFF,
        diff,
        light: "focus",
      },
    };
  });

  const removed = (graph.nodes ?? []).find((n) => String(n.id) === removedId);
  if (removed) {
    const idx = nodes.findIndex((n) => String(n.id) === removedId);
    if (idx >= 0) {
      nodes[idx] = {
        ...nodes[idx]!,
        data: {
          ...nodes[idx]!.data,
          intensity: FOCUS_OFF,
          diff: "removed" satisfies DiffKind,
          light: "focus",
        },
      };
    }
  }

  const edges: EdgeData[] = (graph.edges ?? []).map((edge) => {
    const s = String(edge.source);
    const t = String(edge.target);
    const added =
      addedIds.has(s) ||
      addedIds.has(t) ||
      String(edge.id).startsWith("e-prop-");
    const removed = s === removedId || t === removedId;
    const diff: DiffKind = added ? "added" : removed ? "removed" : "unchanged";
    const intensity = added || removed ? FOCUS_ON : FOCUS_OFF;
    return {
      ...edge,
      data: {
        ...edge.data,
        intensity,
        sourceIntensity: intensity,
        targetIntensity: intensity,
        diff,
        light: "focus",
      },
    };
  });

  return { ...graph, nodes, edges };
}

export function applyAmbientSeamMode(
  base: GraphData,
  mode: AmbientSeamMode,
): { data: GraphData; inverted: boolean; focusIds: string[]; label: string } {
  if (mode === "idle") {
    return {
      data: cloneGraph(base),
      inverted: false,
      focusIds: [],
      label: "Idle",
    };
  }

  if (mode === "focus-group") {
    const focusIds = [...AMBIENT_FOCUS_GROUP_IDS];
    return {
      data: annotateFocus(cloneGraph(base), focusIds),
      inverted: true,
      focusIds,
      label: `Focus · ${focusIds.length} nodes`,
    };
  }

  if (mode === "focus-single") {
    const focusIds = [...AMBIENT_FOCUS_SINGLE_IDS];
    return {
      data: annotateFocus(cloneGraph(base), focusIds),
      inverted: true,
      focusIds,
      label: "Focus · checkout-api",
    };
  }

  if (mode === "proposal") {
    const focusIds = [...PROPOSAL_247.encoding_node_ids];
    return {
      data: annotateFocus(graftProposal(base, PROPOSAL_247.proposal_id), focusIds),
      inverted: true,
      focusIds,
      label: "Proposal · PROP-247",
    };
  }

  // version-diff
  return {
    data: ambientVersionDiff(base),
    inverted: true,
    focusIds: [
      ...PROPOSAL_247.commit_subject_ids,
      "ports-inward-policy",
      "import-boundary",
      "funnel-jobs",
    ],
    label: "Version diff · ambient demo",
  };
}

export function intensityOf(datum: { data?: Record<string, unknown> }) {
  const value = Number(datum.data?.intensity);
  return Number.isFinite(value) ? value : 1;
}

export function isFocusLit(datum: { data?: Record<string, unknown> }) {
  return intensityOf(datum) >= FOCUS_ON;
}

export function diffOf(
  datum: { data?: Record<string, unknown> },
): DiffKind {
  const value = String(datum.data?.diff ?? "unchanged");
  if (value === "added" || value === "removed" || value === "touched") {
    return value;
  }
  return "unchanged";
}
