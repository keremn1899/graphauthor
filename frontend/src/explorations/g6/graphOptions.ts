import type { BehaviorOptions, EdgeOptions, NodeOptions } from "@antv/g6";
import { FONT_SANS_FAMILY } from "../../styles/typography";
import { buildSpineAnimations, type SpineId } from "./motionSpines";
import { edgeStyleMapper } from "./edgeKinds";
import { ensureSeedCircleRegistered } from "./seedCircle";

function asElementAnimation(animations: ReturnType<typeof buildSpineAnimations>["node"]) {
  return animations as unknown as NodeOptions["animation"];
}

/** Label faces for node trials. Circle-suitable sans live in CIRCLE_NODE_FONT_IDS. */
export const NODE_FONT_IDS = [
  "sans",
  "plexCondensed",
  "jost",
  "leagueSpartan",
  "josefinSans",
  "cabin",
  "brandonGrotesque",
  "switzer",
  "satoshi",
  "generalSans",
  "splineSans",
  "asap",
  "asapCondensed",
  "chivo",
  "archivo",
  "archivoNarrow",
  "dmSans",
  "melodrama",
  "erode",
  "zodiak",
  "gambetta",
  "instrument",
] as const;
export type NodeFontId = (typeof NODE_FONT_IDS)[number];

export const NODE_FONTS: Record<
  NodeFontId,
  { id: NodeFontId; label: string; family: string; note: string; weight: number }
> = {
  sans: {
    id: "sans",
    label: "App sans",
    family: FONT_SANS_FAMILY,
    note: "App default (--font-sans / typography.ts) — switch once there",
    weight: 600,
  },
  plexCondensed: {
    id: "plexCondensed",
    label: "Plex Cond.",
    family: '"IBM Plex Sans Condensed", "Arial Narrow", sans-serif',
    note: "IBM — condensed neo-grotesk; fits longer labels without shrinking type",
    weight: 600,
  },
  jost: {
    id: "jost",
    label: "Jost",
    family: FONT_SANS_FAMILY,
    note: "Same token as app sans while Jost is the default",
    weight: 600,
  },
  leagueSpartan: {
    id: "leagueSpartan",
    label: "League Spartan",
    family: '"League Spartan", "Helvetica Neue", Helvetica, sans-serif',
    note: "Google / The League — strong geometric sans; compact caps for circle labels",
    weight: 600,
  },
  josefinSans: {
    id: "josefinSans",
    label: "Josefin",
    family: '"Josefin Sans", "Helvetica Neue", Helvetica, sans-serif',
    note: "Google — geometric with a tall x-height and stylish terminals; display-leaning in discs",
    weight: 600,
  },
  cabin: {
    id: "cabin",
    label: "Cabin",
    family: "Cabin, sans-serif",
    note: "Google — humanist grotesque; soft terminals that stay calm at node sizes",
    weight: 600,
  },
  brandonGrotesque: {
    id: "brandonGrotesque",
    label: "Brandon",
    family: '"Brandon Grotesque", "Helvetica Neue", Helvetica, sans-serif',
    note: "HvD trial — geometric with rounded terminals; trial only, no commercial use",
    weight: 500,
  },
  switzer: {
    id: "switzer",
    label: "Switzer",
    family: "Switzer, sans-serif",
    note: "Fontshare — neutral Swiss sans; open apertures, calm in tight circles",
    weight: 600,
  },
  satoshi: {
    id: "satoshi",
    label: "Satoshi",
    family: "Satoshi, sans-serif",
    note: "Fontshare — soft geometric; short words sit evenly in a disc",
    weight: 600,
  },
  generalSans: {
    id: "generalSans",
    label: "General",
    family: '"General Sans", sans-serif',
    note: "Fontshare — grounded UI sans; no flare that fights a circular crop",
    weight: 600,
  },
  splineSans: {
    id: "splineSans",
    label: "Spline",
    family: '"Spline Sans", sans-serif',
    note: "Fontshare — open, compact grotesk designed for small UI text",
    weight: 600,
  },
  asap: {
    id: "asap",
    label: "Asap",
    family: "Asap, sans-serif",
    note: "Omnibus-Type — rounded humanist sans with clear small-text forms",
    weight: 600,
  },
  asapCondensed: {
    id: "asapCondensed",
    label: "Asap Cond.",
    family: '"Asap Condensed", sans-serif',
    note: "Omnibus-Type — true condensed companion for longer node labels",
    weight: 600,
  },
  chivo: {
    id: "chivo",
    label: "Chivo",
    family: "Chivo, sans-serif",
    note: "Omnibus-Type — sturdy neo-grotesk with no official narrow variant",
    weight: 600,
  },
  archivo: {
    id: "archivo",
    label: "Archivo",
    family: "Archivo, sans-serif",
    note: "Omnibus-Type — compact grotesk with even spacing for interface labels",
    weight: 600,
  },
  archivoNarrow: {
    id: "archivoNarrow",
    label: "Archivo Narrow",
    family: '"Archivo Narrow", sans-serif',
    note: "Omnibus-Type — official narrow companion; efficient for longer labels",
    weight: 600,
  },
  dmSans: {
    id: "dmSans",
    label: "DM Sans",
    family: '"DM Sans", sans-serif',
    note: "Google — low-contrast geometric; round forms echo circular nodes",
    weight: 600,
  },
  melodrama: {
    id: "melodrama",
    label: "Melodrama",
    family: "Melodrama, sans-serif",
    note: "Fontshare — high-contrast geometric display (better as a page label than in-node)",
    weight: 600,
  },
  erode: {
    id: "erode",
    label: "Erode",
    family: "Erode, Georgia, serif",
    note: "Fontshare — contemporary modern serif, works small and large",
    weight: 600,
  },
  zodiak: {
    id: "zodiak",
    label: "Zodiak",
    family: "Zodiak, Georgia, serif",
    note: "Fontshare — sharp high-contrast modern display serif",
    weight: 700,
  },
  gambetta: {
    id: "gambetta",
    label: "Gambetta",
    family: "Gambetta, Georgia, serif",
    note: "Fontshare — modern high-contrast with ink traps",
    weight: 600,
  },
  instrument: {
    id: "instrument",
    label: "Instrument",
    family: '"Instrument Serif", Georgia, serif',
    note: "Google — condensed contemporary display serif",
    weight: 400,
  },
};

/**
 * Sans faces that hold up when a label is centered inside a circular node:
 * even rhythm, open counters, no serif flare or extreme contrast that clips
 * against the disc edge. Prefer these over display/serif options for graph nodes.
 */
export const CIRCLE_NODE_FONT_IDS: readonly NodeFontId[] = [
  "sans",
  "plexCondensed",
  "jost",
  "leagueSpartan",
  "josefinSans",
  "cabin",
  "brandonGrotesque",
  "switzer",
  "satoshi",
  "generalSans",
  "splineSans",
  "asap",
  "asapCondensed",
  "chivo",
  "archivo",
  "archivoNarrow",
  "dmSans",
] as const;

export const DEFAULT_NODE_FONT: NodeFontId = "sans";
export const DEFAULT_CIRCLE_NODE_FONT: NodeFontId = "plexCondensed";

export const BASE_NODE_STYLE = {
  size: 50,
  labelText: (d: { id: string | number }) => String(d.id),
  labelPlacement: "center" as const,
  labelFill: "#fff",
  labelFontSize: 10,
  labelFontWeight: 600,
  labelFontFamily: NODE_FONTS[DEFAULT_NODE_FONT].family,
  fill: "#111",
  stroke: "#111",
  lineWidth: 1,
};

/** Selection / hover: stroke weight only — no dimming of the rest of the graph. */
export const BASE_NODE_STATE = {
  selected: {
    lineWidth: 3,
    stroke: "#111",
  },
  active: {
    lineWidth: 2.5,
    stroke: "#111",
  },
};

export const BASE_EDGE_STATE = {
  selected: { lineWidth: 2.2, stroke: "#111" },
  active: { lineWidth: 2, stroke: "#111" },
};

export type NodeMotionTuning = {
  durationScale?: number;
  arriveEase?: string;
  leaveEase?: string;
  labelFontFamily?: string;
  labelFontWeight?: number;
};

export function buildNodeOptions(
  spineId: SpineId,
  tuning?: NodeMotionTuning,
): NodeOptions {
  const animations = buildSpineAnimations(spineId, tuning);
  if (spineId === "seed") ensureSeedCircleRegistered();
  const durationScale = tuning?.durationScale ?? 1;
  return {
    ...(spineId === "seed" ? { type: "seed-circle" as const } : {}),
    style: {
      ...BASE_NODE_STYLE,
      ...(tuning?.labelFontFamily
        ? { labelFontFamily: tuning.labelFontFamily }
        : {}),
      ...(tuning?.labelFontWeight != null
        ? { labelFontWeight: tuning.labelFontWeight }
        : {}),
      ...(spineId === "seed"
        ? {
            seedEnterDuration: Math.max(1, Math.round(700 * durationScale)),
            seedExitDuration: Math.max(1, Math.round(500 * durationScale)),
          }
        : {}),
    },
    state: BASE_NODE_STATE,
    animation: asElementAnimation(animations.node),
  };
}

export function buildEdgeOptions(
  spineId: SpineId,
  tuning?: { durationScale?: number; arriveEase?: string; leaveEase?: string },
): EdgeOptions {
  const animations = buildSpineAnimations(spineId, tuning);
  return {
    style: {
      stroke: (d) => edgeStyleMapper(d).stroke,
      lineWidth: (d) => edgeStyleMapper(d).lineWidth,
      endArrow: (d) => edgeStyleMapper(d).endArrow,
      endArrowType: "triangle",
      endArrowSize: 8,
      lineDash: (d) => edgeStyleMapper(d).lineDash,
      lineCap: "round",
    },
    state: BASE_EDGE_STATE,
    animation: animations.edge as unknown as EdgeOptions["animation"],
  };
}

export const BASE_BEHAVIORS = [
  "drag-canvas",
  "zoom-canvas",
  // Plain (non-force) drag: with physics off (see PHYSICS_ENABLED in
  // forcePresets.ts) there's no simulation to hand off to, and this is the
  // behavior that guarantees dragging one node never touches any other.
  "drag-element",
  "click-select",
  // Hover only the target — no inactiveState, so the rest of the graph never greys out.
  {
    type: "hover-activate",
    degree: 0,
    state: "active",
  },
] as const;

/**
 * Swap a behavior list's plain "drag-element" for the force-aware variant
 * when a live simulation is running. Plain drag-element never talks to a
 * layout instance — with physics on, that leaves the simulation holding a
 * stale position and fighting the gesture on the next tick. drag-element-
 * force hands the pointer to the sim (pin-while-dragging, release into
 * alphaTarget after) instead.
 */
export function withPhysicsDrag(
  behaviors: readonly BehaviorOptions[number][],
  physicsEnabled: boolean,
): BehaviorOptions {
  if (!physicsEnabled) return [...behaviors];
  return [
    ...behaviors.filter((behavior) => behavior !== "drag-element"),
    { type: "drag-element-force", fixed: false },
  ];
}
