/**
 * Shared Platform Core scenario — Screen 2 ↔ Screen 1 seams.
 *
 * Lab stand-in for /operator: ActivityVM.graph_revision_* ≡ graph_version_*.
 * Focus / proposal overlay / committed delta builders mirror
 * design/screen-2-ledger-graph-linkage.md §4.
 */

import type { EdgeData, GraphData, NodeData } from "@antv/g6";
import {
  GRAPH_CHECKPOINTS,
  type GraphCheckpoint,
} from "./architectureActivityData";
import type { ActivityVM } from "./ledgerFeedModel";

export const FOCUS_ON = 1;
export const FOCUS_OFF = 0;

/** Hash route for Screen 1 linkage lab. */
export const CANVAS_LINKAGE_HASH = "#/explorations/canvas-linkage";
export const GRAPH_MAP_HASH = "#/graph";
export const LEDGER_FEED_HASH = "#/explorations/ledger-feed";

export type SeamAction = "focus" | "proposal" | "diff" | "idle";

export type SeamParams = {
  activity?: string;
  proposal?: string;
  gap?: string;
  /** Comma-separated node ids — optional override; else derived. */
  focus?: string[];
  /**
   * graph_version_before / _after. Carried through as given: lab rows use
   * ordinal checkpoints, live rows the engine's opaque version id. Only the
   * ordinal form has a fixture checkpoint to diff against — see
   * `canOpenVersionDiff`.
   */
  from?: string | number;
  /** graph_version_after (also accepts `gv`) */
  to?: string | number;
  /** Lab tab override / seam action */
  mode?: string;
  seam?: SeamAction;
};

export type ProposalEncoding = {
  proposal_id: string;
  gap_id?: string;
  /** Committed base graph before this proposal lands. */
  base_revision: number;
  nodes: NodeData[];
  edges: EdgeData[];
  /** Concept ids in the encoding (+ focus seeds for overlay). */
  encoding_node_ids: string[];
  /**
   * Subjects after commit (encoding can be richer than what lands).
   * PROP-247: only dependency-direction-rule + package endpoints.
   */
  commit_subject_ids: string[];
};

/**
 * PROP-247 — Dependency Direction legislation.
 * Encoding cluster is richer than V13 commit (ports + import stay proposal-only).
 */
export const PROPOSAL_247: ProposalEncoding = {
  proposal_id: "PROP-247",
  gap_id: "GAP-031",
  base_revision: 12,
  encoding_node_ids: [
    "dependency-direction-rule",
    "ports-inward-policy",
    "import-boundary",
  ],
  commit_subject_ids: [
    "dependency-direction-rule",
    "domain-package",
    "adapter-package",
  ],
  nodes: [
    {
      id: "dependency-direction-rule",
      data: {
        label: "Dependency Direction",
        kind: "rule",
        proposed: true,
      },
      style: { x: 350, y: 560 },
    },
    {
      id: "ports-inward-policy",
      data: {
        label: "Ports Inward",
        kind: "rule",
        proposed: true,
      },
      style: { x: 200, y: 660 },
    },
    {
      id: "import-boundary",
      data: {
        label: "Import Boundary",
        kind: "concept",
        proposed: true,
      },
      style: { x: 500, y: 660 },
    },
  ],
  edges: [
    {
      id: "e-prop-ports-dep",
      source: "ports-inward-policy",
      target: "dependency-direction-rule",
      data: { label: "LEADSTO", proposed: true },
    },
    {
      id: "e-prop-ports-import",
      source: "ports-inward-policy",
      target: "import-boundary",
      data: { label: "CONTAINS", proposed: true },
    },
    {
      id: "e-prop-import-dep",
      source: "import-boundary",
      target: "dependency-direction-rule",
      data: { label: "EXPRESSES", proposed: true },
    },
    {
      id: "e-prop-dep-boundary",
      source: "dependency-direction-rule",
      target: "service-boundary",
      data: { label: "GOVERNS", proposed: true },
    },
    {
      id: "e-prop-import-domain",
      source: "import-boundary",
      target: "domain-package",
      data: { label: "CONSTRAINS", proposed: true },
    },
    {
      id: "e-prop-import-adapter",
      source: "import-boundary",
      target: "adapter-package",
      data: { label: "CONSTRAINS", proposed: true },
    },
  ],
};

/** Thinner second proposal — tenant isolation edge case. */
export const PROPOSAL_255: ProposalEncoding = {
  proposal_id: "PROP-255",
  gap_id: "GAP-040",
  base_revision: 12,
  encoding_node_ids: ["tenant-isolation", "checkout-api"],
  commit_subject_ids: ["tenant-isolation", "checkout-api"],
  nodes: [],
  edges: [
    {
      id: "e-prop-255-tenant-checkout",
      source: "tenant-isolation",
      target: "checkout-api",
      data: { label: "CONSTRAINS", proposed: true },
    },
  ],
};

const PROPOSALS: Record<string, ProposalEncoding> = {
  [PROPOSAL_247.proposal_id]: PROPOSAL_247,
  [PROPOSAL_255.proposal_id]: PROPOSAL_255,
};

/** Ownership revert focus cluster — matches act_ownership_revert. */
export const OWNERSHIP_FOCUS_IDS = [
  "payments-team",
  "finance-team",
  "order-ledger",
] as const;

/** Escalate-outcome gap cluster. */
export const ESCALATE_FOCUS_IDS = ["checkout-api", "order-ledger"] as const;

export function checkpoint(version: number): GraphCheckpoint | undefined {
  return GRAPH_CHECKPOINTS.find((c) => c.version === version);
}

export function cloneGraph(data: GraphData): GraphData {
  return structuredClone(data);
}

export function getProposal(proposalId: string): ProposalEncoding | undefined {
  return PROPOSALS[proposalId];
}

/**
 * §4.1 focus set — subject first, then encoding, then gap cluster, else empty.
 * Never invents a neighbourhood soup.
 */
export function focusSetForActivity(
  activity: Pick<
    ActivityVM,
    "subject_node_ids" | "node_ids" | "ids" | "cluster_node_ids"
  >,
): string[] {
  const subject =
    activity.subject_node_ids?.length
      ? activity.subject_node_ids
      : activity.node_ids;
  if (subject.length) return [...subject];

  const proposalId = activity.ids.proposal_id;
  if (proposalId) {
    const encoding = getProposal(proposalId);
    if (encoding?.encoding_node_ids.length) {
      return [...encoding.encoding_node_ids];
    }
  }

  if (activity.cluster_node_ids?.length) {
    return [...activity.cluster_node_ids];
  }

  return [];
}

/** Temporary binary focus — seeds + touching edges full paper. */
export function annotateFocus(data: GraphData, focusIds: string[]): GraphData {
  const focus = new Set(focusIds);

  const nodes = (data.nodes ?? []).map((node) => {
    const id = String(node.id);
    const intensity = focus.has(id) ? FOCUS_ON : FOCUS_OFF;
    return {
      ...node,
      data: {
        ...node.data,
        intensity,
        light: "focus",
      },
    };
  });

  const edges = (data.edges ?? []).map((edge) => {
    const connected =
      focus.has(String(edge.source)) || focus.has(String(edge.target));
    const intensity = connected ? FOCUS_ON : FOCUS_OFF;
    return {
      ...edge,
      data: {
        ...edge.data,
        intensity,
        sourceIntensity: intensity,
        targetIntensity: intensity,
        light: "focus",
      },
    };
  });

  return { nodes, edges };
}

export type ScenarioGraphView = {
  data: GraphData;
  focusIds: string[];
  camera: "fit" | "focus";
  inverted: boolean;
  label: string;
};

/** Idle landmarks — latest committed checkpoint (V13). */
export function idleView(): ScenarioGraphView {
  const live = checkpoint(13) ?? GRAPH_CHECKPOINTS[GRAPH_CHECKPOINTS.length - 1]!;
  return {
    data: cloneGraph(live.graphData),
    focusIds: [],
    camera: "fit",
    inverted: false,
    label: `Idle · ${live.shortLabel}`,
  };
}

export function focusView(
  focusIds: string[],
  baseRevision = 13,
): ScenarioGraphView {
  if (!focusIds.length) {
    return {
      ...idleView(),
      label: "Focus · no graph focus",
    };
  }
  const base = checkpoint(baseRevision) ?? checkpoint(13)!;
  return {
    data: annotateFocus(cloneGraph(base.graphData), focusIds),
    focusIds,
    camera: "focus",
    inverted: true,
    label: `Focus · ${focusIds.length} node${focusIds.length === 1 ? "" : "s"}`,
  };
}

/**
 * §4.2 Proposal ghost — graft encoding onto base revision, light encoding seeds.
 * Visual vocabulary: white focus lighting (not dotted ghosts).
 */
export function proposalOverlay(proposalId: string): ScenarioGraphView | null {
  const encoding = getProposal(proposalId);
  if (!encoding) return null;

  const base = checkpoint(encoding.base_revision);
  if (!base) return null;

  const graph = cloneGraph(base.graphData);
  const nodes: NodeData[] = [...(graph.nodes ?? [])];
  const edges: EdgeData[] = [...(graph.edges ?? [])];
  const existingNodeIds = new Set(nodes.map((n) => String(n.id)));
  const existingEdgeIds = new Set(edges.map((e) => String(e.id)));

  for (const node of encoding.nodes) {
    if (existingNodeIds.has(String(node.id))) {
      const idx = nodes.findIndex((n) => String(n.id) === String(node.id));
      if (idx >= 0) {
        nodes[idx] = {
          ...nodes[idx],
          data: { ...nodes[idx].data, ...node.data, proposed: true },
        };
      }
      continue;
    }
    nodes.push(structuredClone(node));
  }

  for (const edge of encoding.edges) {
    if (existingEdgeIds.has(String(edge.id))) continue;
    edges.push(structuredClone(edge));
  }

  const focusIds = [...encoding.encoding_node_ids];
  return {
    data: annotateFocus({ nodes, edges }, focusIds),
    focusIds,
    camera: "focus",
    inverted: true,
    label: `Proposal · ${proposalId} on V${encoding.base_revision}`,
  };
}

type DiffKind = "added" | "removed" | "touched" | "unchanged";

/**
 * §4.2 Committed delta — real checkpoint pair (no synthetic legacy nodes).
 * Optional subjectIds: focus ≈ subject ∩ (added ∪ touched ∪ removed) when both exist.
 */
export function committedDelta(
  from: number,
  to: number,
  subjectIds?: string[],
): ScenarioGraphView | null {
  const beforeCp = checkpoint(from);
  const afterCp = checkpoint(to);
  if (!beforeCp || !afterCp) return null;

  const before = cloneGraph(beforeCp.graphData);
  const after = cloneGraph(afterCp.graphData);

  const touchedHint = new Set(afterCp.changedNodeIds);

  const beforeNodes = new Map(
    (before.nodes ?? []).map((n) => [String(n.id), n]),
  );
  const beforeEdges = new Map(
    (before.edges ?? []).map((e) => [String(e.id), e]),
  );
  const afterNodeIds = new Set((after.nodes ?? []).map((n) => String(n.id)));
  const afterEdgeIds = new Set((after.edges ?? []).map((e) => String(e.id)));

  const nodes: NodeData[] = (after.nodes ?? []).map((node) => {
    const id = String(node.id);
    const added = !beforeNodes.has(id);
    const touched = !added && touchedHint.has(id);
    const diff: DiffKind = added ? "added" : touched ? "touched" : "unchanged";
    return {
      ...node,
      data: {
        ...node.data,
        intensity: added ? FOCUS_ON : FOCUS_OFF,
        diff,
        light: "focus",
      },
    };
  });

  for (const [id, node] of beforeNodes) {
    if (afterNodeIds.has(id)) continue;
    nodes.push({
      ...structuredClone(node),
      data: {
        ...node.data,
        intensity: FOCUS_OFF,
        diff: "removed" satisfies DiffKind,
        light: "focus",
      },
    });
  }

  const edges: EdgeData[] = (after.edges ?? []).map((edge) => {
    const id = String(edge.id);
    const added = !beforeEdges.has(id);
    return {
      ...edge,
      data: {
        ...edge.data,
        intensity: added ? FOCUS_ON : FOCUS_OFF,
        diff: (added ? "added" : "unchanged") as DiffKind,
        light: "focus",
        sourceIntensity: added ? FOCUS_ON : FOCUS_OFF,
        targetIntensity: added ? FOCUS_ON : FOCUS_OFF,
      },
    };
  });

  for (const [id, edge] of beforeEdges) {
    if (afterEdgeIds.has(id)) continue;
    edges.push({
      ...structuredClone(edge),
      data: {
        ...edge.data,
        intensity: FOCUS_ON,
        diff: "removed" satisfies DiffKind,
        light: "focus",
        sourceIntensity: FOCUS_ON,
        targetIntensity: FOCUS_ON,
      },
    });
  }

  const changedIds = nodes
    .filter((n) => {
      const d = String(n.data?.diff ?? "unchanged");
      return d === "added" || d === "removed" || d === "touched";
    })
    .map((n) => String(n.id));

  let focusIds = changedIds;
  if (subjectIds?.length) {
    const subject = new Set(subjectIds);
    const intersect = changedIds.filter((id) => subject.has(id));
    if (intersect.length) focusIds = intersect;
  }

  return {
    data: { nodes, edges },
    focusIds,
    camera: "focus",
    inverted: true,
    label: `Version diff · V${from}→V${to}`,
  };
}

export type ActivityLike = Pick<
  ActivityVM,
  | "activity_id"
  | "state"
  | "resolution"
  | "subject_node_ids"
  | "node_ids"
  | "cluster_node_ids"
  | "ids"
  | "graph_revision_before"
  | "graph_revision_after"
>;

/**
 * Derive canvas behaviour from activity + optional seam action (§4.2).
 * Honest empty focus when no subjects / encoding.
 */
export function viewForActivity(
  activity: ActivityLike,
  seam: SeamAction = "focus",
): ScenarioGraphView {
  const subject = focusSetForActivity(activity);
  const proposalId = activity.ids.proposal_id;
  const from = activity.graph_revision_before;
  const to = activity.graph_revision_after;

  if (seam === "proposal" && proposalId) {
    const overlay = proposalOverlay(proposalId);
    if (overlay) {
      return {
        ...overlay,
        label: `from Ledger · ${proposalId} · ${overlay.label}`,
      };
    }
  }

  if (
    seam === "diff" &&
    // Only the lab's ordinal checkpoints have snapshots to compare. A live
    // activity's opaque versions fall through to focus, which is the honest
    // subset rather than an empty or invented diff.
    typeof from === "number" &&
    typeof to === "number" &&
    from !== to
  ) {
    const delta = committedDelta(from, to, subject);
    if (delta) {
      return {
        ...delta,
        label: `from Ledger · ${activity.activity_id} · ${delta.label}`,
      };
    }
  }

  if (seam === "idle") return idleView();

  // Default / focus — and auto-pick when seam omitted but state implies
  if (
    seam === "focus" ||
    seam === "proposal" ||
    seam === "diff"
  ) {
    // `baseRevision` selects which fixture snapshot to draw behind the focus.
    // A live activity's opaque version names no fixture snapshot, so it falls
    // back to the default rather than being coerced into a checkpoint number.
    const base =
      activity.state === "SETTLED" && typeof to === "number"
        ? to
        : proposalId
          ? (getProposal(proposalId)?.base_revision ?? 13)
          : 13;

    if (
      !subject.length &&
      proposalId &&
      activity.state === "OPEN"
    ) {
      const overlay = proposalOverlay(proposalId);
      if (overlay) {
        return {
          ...overlay,
          label: `from Ledger · ${proposalId} · ${overlay.label}`,
        };
      }
    }

    if (
      activity.state === "SETTLED" &&
      from != null &&
      to != null &&
      seam === "diff"
    ) {
      // already handled
    }

    const view = focusView(subject, base);
    return {
      ...view,
      label: subject.length
        ? `from Ledger · ${activity.activity_id} · ${view.label}`
        : `from Ledger · ${activity.activity_id} · no graph focus`,
    };
  }

  return idleView();
}

/** Lab mode tabs → scenario views (manual controls). */
export function viewForLabMode(
  mode:
    | "idle"
    | "focus-group"
    | "focus-single"
    | "proposal-ghost"
    | "version-diff",
): ScenarioGraphView {
  switch (mode) {
    case "idle":
      return idleView();
    case "focus-group":
      return focusView([...OWNERSHIP_FOCUS_IDS], 13);
    case "focus-single":
      return focusView(["checkout-api"], 13);
    case "proposal-ghost": {
      const overlay = proposalOverlay("PROP-247");
      return overlay ?? idleView();
    }
    case "version-diff": {
      const delta = committedDelta(
        12,
        13,
        [...PROPOSAL_247.commit_subject_ids],
      );
      return delta ?? idleView();
    }
  }
}

export function parseSeamQuery(search: string): SeamParams {
  const q = new URLSearchParams(
    search.startsWith("?") ? search.slice(1) : search,
  );
  const focusRaw = q.get("focus");
  const fromRaw = q.get("from");
  const toRaw = q.get("to") ?? q.get("gv");
  const seamRaw = q.get("seam");
  const seam: SeamAction | undefined =
    seamRaw === "focus" ||
    seamRaw === "proposal" ||
    seamRaw === "diff" ||
    seamRaw === "idle"
      ? seamRaw
      : undefined;
  const version = (raw: string | null): string | number | undefined => {
    if (raw == null || raw === "") return undefined;
    const ordinal = Number(raw);
    return Number.isFinite(ordinal) && String(ordinal) === raw ? ordinal : raw;
  };

  return {
    activity: q.get("activity") ?? undefined,
    proposal: q.get("proposal") ?? undefined,
    gap: q.get("gap") ?? undefined,
    focus: focusRaw
      ? focusRaw.split(",").map((s) => s.trim()).filter(Boolean)
      : undefined,
    from: version(fromRaw),
    to: version(toRaw),
    mode: q.get("mode") ?? undefined,
    seam,
  };
}

/** Read seam params from the current location hash (`#/path?query`). */
export function readHashSeamParams(): SeamParams {
  const hash = window.location.hash;
  const qIndex = hash.indexOf("?");
  if (qIndex < 0) return {};
  return parseSeamQuery(hash.slice(qIndex));
}

export function buildSeamQuery(params: SeamParams): string {
  const q = new URLSearchParams();
  if (params.activity) q.set("activity", params.activity);
  if (params.proposal) q.set("proposal", params.proposal);
  if (params.gap) q.set("gap", params.gap);
  if (params.focus?.length) q.set("focus", params.focus.join(","));
  if (params.from != null) q.set("from", String(params.from));
  if (params.to != null) {
    q.set("to", String(params.to));
    q.set("gv", String(params.to));
  }
  if (params.seam) q.set("seam", params.seam);
  if (params.mode) q.set("mode", params.mode);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function buildCanvasSeamHref(params: SeamParams): string {
  return `${CANVAS_LINKAGE_HASH}${buildSeamQuery(params)}`;
}

export function buildLedgerHref(activityId?: string): string {
  if (!activityId) return LEDGER_FEED_HASH;
  return `${LEDGER_FEED_HASH}?activity=${encodeURIComponent(activityId)}`;
}

/** Href for a ledger card canvas action. */
export function seamHrefForActivity(
  activity: ActivityLike,
  seam: SeamAction,
): string {
  const focus = focusSetForActivity(activity);
  return buildCanvasSeamHref({
    activity: activity.activity_id,
    proposal: activity.ids.proposal_id,
    gap: activity.ids.gap_id,
    focus: focus.length ? focus : undefined,
    from: activity.graph_revision_before,
    to: activity.graph_revision_after,
    seam,
  });
}

/** Real committed-map target for a live ledger row. */
export function graphMapHrefForActivity(activity: ActivityLike): string {
  const focus = focusSetForActivity(activity);
  return `${GRAPH_MAP_HASH}${buildSeamQuery({
    activity: activity.activity_id,
    proposal: activity.ids.proposal_id,
    gap: activity.ids.gap_id,
    focus: focus.length ? focus : undefined,
    from: activity.graph_revision_before,
    to: activity.graph_revision_after,
    seam: "focus",
  })}`;
}

/** Real committed-map target for a backend-computed version delta. */
export function graphDiffHrefForActivity(activity: ActivityLike): string {
  const focus = focusSetForActivity(activity);
  return `${GRAPH_MAP_HASH}${buildSeamQuery({
    activity: activity.activity_id,
    focus: focus.length ? focus : undefined,
    from: activity.graph_revision_before,
    to: activity.graph_revision_after,
    seam: "diff",
  })}`;
}

export function canFocusActivity(activity: ActivityLike): boolean {
  return focusSetForActivity(activity).length > 0;
}

export function canOpenProposal(activity: ActivityLike): boolean {
  const id = activity.ids.proposal_id;
  return Boolean(id && getProposal(id));
}

/**
 * Fixture canvas diffs need two local numbered checkpoints. Live opaque engine
 * versions are handled by `/operator/diff` in the product feed and graph map;
 * this predicate remains fixture-only.
 */
export function canOpenVersionDiff(activity: ActivityLike): boolean {
  const from = activity.graph_revision_before;
  const to = activity.graph_revision_after;
  if (typeof from !== "number" || typeof to !== "number") return false;
  return from !== to && Boolean(checkpoint(from) && checkpoint(to));
}

/**
 * Resolve a canvas view from deep-link params (lab has no live BFF fetch).
 * Activity selection is source of truth when seam + glue ids are present;
 * `mode=` remains a lab-tab override.
 */
export function resolveSeamView(params: SeamParams): ScenarioGraphView {
  const labMode = params.mode;
  if (
    labMode === "idle" ||
    labMode === "focus-group" ||
    labMode === "focus-single" ||
    labMode === "proposal-ghost" ||
    labMode === "version-diff"
  ) {
    return viewForLabMode(labMode);
  }

  const seam: SeamAction =
    params.seam ??
    (params.proposal && params.from == null && params.to == null
      ? "proposal"
      : params.from != null && params.to != null
        ? "diff"
        : params.focus?.length
          ? "focus"
          : "idle");

  if (seam === "proposal" && params.proposal) {
    const overlay = proposalOverlay(params.proposal);
    if (overlay) {
      return {
        ...overlay,
        label: params.activity
          ? `from Ledger · ${params.activity} · ${overlay.label}`
          : overlay.label,
      };
    }
  }

  if (
    seam === "diff" &&
    typeof params.from === "number" &&
    typeof params.to === "number"
  ) {
    const delta = committedDelta(params.from, params.to, params.focus);
    if (delta) {
      return {
        ...delta,
        label: params.activity
          ? `from Ledger · ${params.activity} · ${delta.label}`
          : delta.label,
      };
    }
  }

  if (params.focus?.length) {
    // Same rule as above: only an ordinal checkpoint names a fixture snapshot.
    const base =
      (typeof params.to === "number" ? params.to : undefined) ??
      (params.proposal
        ? getProposal(params.proposal)?.base_revision
        : undefined) ??
      13;
    const view = focusView(params.focus, base);
    return {
      ...view,
      label: params.activity
        ? `from Ledger · ${params.activity} · ${view.label}`
        : view.label,
    };
  }

  if (seam === "proposal" && params.proposal) {
    // fallthrough already tried
  }

  return idleView();
}
