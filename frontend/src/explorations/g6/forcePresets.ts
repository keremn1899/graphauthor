import type { D3ForceLayoutOptions, Graph, LayoutOptions } from "@antv/g6";

/**
 * Master switch for whether any lab page runs a live d3-force simulation.
 *
 * Was off for a while: dragging a node while a force layout was live kept
 * re-opening ways for the rest of the graph to get disturbed (or for a
 * removed node's orphaned simulation to spin forever — see G6SeedLabPage
 * history: the id mismatch, the alpha=0.15 stall, the stale
 * `instances[]` layout, the mid-drag death race). Those were fixed one by
 * one (matching layout id, `animation: true`, the `refreshFieldMembership`
 * + `withFieldQueue` mutex, drag-deferred death) — re-enabled on Glide
 * Loose to see if it now holds up under birth/death/drag together.
 *
 * Flip back to `false` if drag/birth/death interactions misbehave again.
 */
export const PHYSICS_ENABLED = true;

export type ForcePresetId = "glide" | "glide-loose" | "anchor" | "taut" | "drift";

export interface ForcePresetDef {
  id: ForcePresetId;
  label: string;
  metaphor: string;
  /** Glide family is the design default; others are contrast / exploration only. */
  recommended?: boolean;
  layout: D3ForceLayoutOptions & { type: "d3-force" };
}

/**
 * The Glide family is the intended character for Field:
 * enough physics to feel alive (or barely), soft enough that the user stays in control.
 * Other presets stay available as contrast in the physics lab — not proposals.
 */
export const FORCE_PRESETS: Record<ForcePresetId, ForcePresetDef> = {
  glide: {
    id: "glide",
    label: "Glide",
    metaphor: "Topology-led — motion travels through links, with no ambient charge",
    recommended: true,
    layout: {
      type: "d3-force",
      link: { distance: 220, strength: 0.09, iterations: 1 },
      manyBody: false,
      collide: { radius: 48, strength: 1, iterations: 3 },
      center: false,
      alphaDecay: 0.035,
      velocityDecay: 0.42,
      alphaTarget: 0,
    },
  },
  "glide-loose": {
    id: "glide-loose",
    label: "Glide loose",
    metaphor: "Link-only slack — connected neighbors yield, unrelated nodes stay still",
    recommended: true,
    layout: {
      type: "d3-force",
      link: { distance: 260, strength: 0.07, iterations: 1 },
      manyBody: false,
      collide: { radius: 48, strength: 1, iterations: 3 },
      center: false,
      alphaDecay: 0.035,
      velocityDecay: 0.48,
      alphaTarget: 0,
    },
  },
  anchor: {
    id: "anchor",
    label: "Anchor",
    metaphor: "Contrast — firm, settles hard (too physical for Field)",
    layout: {
      type: "d3-force",
      link: { distance: 130, strength: 0.4 },
      manyBody: { strength: -220 },
      collide: { radius: 42, strength: 1 },
      alphaDecay: 0.02,
      velocityDecay: 0.4,
      alphaTarget: 0,
    },
  },
  taut: {
    id: "taut",
    label: "Taut",
    metaphor: "Contrast — rubber-band yank (too elastic for Field)",
    layout: {
      type: "d3-force",
      link: { distance: 90, strength: 0.85 },
      manyBody: { strength: -260 },
      collide: { radius: 46, strength: 0.9 },
      alphaDecay: 0.025,
      velocityDecay: 0.15,
      alphaTarget: 0,
    },
  },
  drift: {
    id: "drift",
    label: "Drift",
    metaphor: "Contrast — ambient wander (too little user control)",
    layout: {
      type: "d3-force",
      link: { distance: 160, strength: 0.08 },
      manyBody: { strength: -80 },
      collide: { radius: 40, strength: 0.4 },
      alphaDecay: 0.01,
      velocityDecay: 0.5,
      alphaTarget: 0.015,
    },
  },
};

export const FORCE_PRESET_IDS = Object.keys(FORCE_PRESETS) as ForcePresetId[];
export const DEFAULT_FORCE_PRESET: ForcePresetId = "glide";

export interface ForceTuning {
  manyBodyStrength: number;
  linkDistance: number;
  linkStrength: number;
  collideRadius: number;
  collideStrength: number;
  velocityDecay: number;
  alphaDecay: number;
  alphaTarget: number;
}

/** Soft reheat after topology change — felt as a sigh, not an explosion. */
export const SETTLE_ALPHA = 0.06;

export const DEFAULT_FORCE_TUNING: ForceTuning = forceTuningFromPresetValues(
  FORCE_PRESETS.glide.layout,
);

function forceTuningFromPresetValues(
  preset: D3ForceLayoutOptions & { type: "d3-force" },
): ForceTuning {
  const manyBody = preset.manyBody === false ? undefined : preset.manyBody;
  const link = preset.link === false ? undefined : preset.link;
  const collide = preset.collide === false ? undefined : preset.collide;
  return {
    manyBodyStrength: asNumber(manyBody?.strength, -120),
    linkDistance: asNumber(link?.distance, 170),
    linkStrength: asNumber(link?.strength, 0.14),
    collideRadius: asNumber(collide?.radius, 46),
    collideStrength: asNumber(collide?.strength, 0.28),
    velocityDecay: preset.velocityDecay ?? 0.34,
    alphaDecay: preset.alphaDecay ?? 0.018,
    alphaTarget: preset.alphaTarget ?? 0.004,
  };
}

function asNumber(value: number | ((...args: never[]) => number) | undefined, fallback: number) {
  return typeof value === "number" ? value : fallback;
}

export function forceTuningFromPreset(presetId: ForcePresetId): ForceTuning {
  return forceTuningFromPresetValues(FORCE_PRESETS[presetId].layout);
}

export function layoutFromTuning(tuning: ForceTuning): D3ForceLayoutOptions & { type: "d3-force" } {
  return {
    type: "d3-force",
    link: { distance: tuning.linkDistance, strength: tuning.linkStrength },
    manyBody: { strength: tuning.manyBodyStrength },
    collide: { radius: tuning.collideRadius, strength: tuning.collideStrength },
    velocityDecay: tuning.velocityDecay,
    alphaDecay: tuning.alphaDecay,
    alphaTarget: tuning.alphaTarget,
  };
}

/**
 * Soft reheat after a *relationship* change that should be felt (new edge tug).
 *
 * Do NOT call after Seed / aperture birth — Tier-1/`onCreate` scale owns that
 * moment. Reheating d3-force mid-scale (draw() does not await onCreate WAAPI)
 * reads as a second, harder gesture: the “clear cut” after birth.
 *
 * Prefer: place the newborn near its parent and leave force idle (`draw` only).
 */
export function softSettle(graph: Graph) {
  if (!PHYSICS_ENABLED) return;
  if (!graph || graph.destroyed) return;
  graph.setLayout((prev: LayoutOptions) => {
    const base = Array.isArray(prev) ? prev[0] : prev;
    return {
      ...(typeof base === "object" && base ? base : {}),
      type: "d3-force",
      alpha: SETTLE_ALPHA,
    } as LayoutOptions;
  });
  graph.layout().catch(() => {});
}

/**
 * World position for a quiet birth: beside `nearId`, no force reheat required.
 * Existing nodes stay put; the scale animation is the only motion.
 */
export function birthPositionNear(
  graph: Graph,
  nearId: string,
  distance = 260,
): { x: number; y: number } {
  const positionOf = (id: string) => {
    try {
      const pos = graph.getElementPosition(id);
      if (Array.isArray(pos) && pos.length >= 2) {
        const x = Number(pos[0]);
        const y = Number(pos[1]);
        if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
      }
    } catch {
      /* fall through to model coordinates */
    }
    const data = graph.getNodeData(id);
    const style = data?.style as { x?: number; y?: number } | undefined;
    if (typeof style?.x === "number" && typeof style?.y === "number") {
      return { x: style.x, y: style.y };
    }
    return undefined;
  };

  const parent = positionOf(nearId) ?? { x: 200, y: 200 };
  const occupied = graph
    .getNodeData()
    .map((node) => positionOf(String(node.id)))
    .filter((point): point is { x: number; y: number } => Boolean(point));
  const clearance = 116;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  let hash = 2166136261;
  for (const char of `${nearId}:${occupied.length}`) {
    hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  }
  const startAngle = ((hash >>> 0) / 2 ** 32) * Math.PI * 2;
  let best = { x: parent.x + distance, y: parent.y, clearance: -Infinity };

  for (let ring = 0; ring < 4; ring += 1) {
    const radius = distance + ring * clearance;
    for (let slot = 0; slot < 16; slot += 1) {
      const angle = startAngle + slot * goldenAngle;
      const candidate = {
        x: parent.x + Math.cos(angle) * radius,
        y: parent.y + Math.sin(angle) * radius,
      };
      const nearest = occupied.reduce(
        (minimum, point) =>
          Math.min(minimum, Math.hypot(candidate.x - point.x, candidate.y - point.y)),
        Infinity,
      );
      if (nearest >= clearance) return candidate;
      if (nearest > best.clearance) best = { ...candidate, clearance: nearest };
    }
  }

  return { x: best.x, y: best.y };
}
