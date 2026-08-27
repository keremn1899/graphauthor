import type { AnimationOptions } from "@antv/g6";

/**
 * @deprecated Exploration-only motion studies.
 *
 * These named metaphors are intentionally retained for the lifecycle labs,
 * where comparing incompatible animation ideas is the point. Product
 * interactions must consume `styles/motion.ts` through the G6 or React
 * adapters; adding a product dependency here would fork the motion DNA.
 */
export type SpineId = "breath" | "bloom" | "ripple" | "ember" | "seed";

export interface SpineTuning {
  /** Multiplier applied to all spine durations (1 = default). */
  durationScale: number;
  /** Optional override for arrival easing. */
  arriveEase?: string;
  /** Optional override for departure easing. */
  leaveEase?: string;
}

export interface SpineAnimations {
  enter: AnimationOptions[] | string | false;
  exit: AnimationOptions[] | string | false;
  update: AnimationOptions[];
}

export interface SpineDef {
  id: SpineId;
  label: string;
  metaphor: string;
  node: SpineAnimations;
  edge: SpineAnimations;
  defaults: SpineTuning;
}

const DEFAULT_TUNING: SpineTuning = {
  durationScale: 1,
};

function scaleMs(ms: number, tuning: SpineTuning) {
  return Math.max(1, Math.round(ms * tuning.durationScale));
}

function cloneOptions(
  options: AnimationOptions[],
  tuning: SpineTuning,
  arriveEase?: string,
  leaveEase?: string,
): AnimationOptions[] {
  return options.map((opt, index) => {
    const isArrival = index > 0 || opt.easing?.includes("cubic-bezier");
    const easing =
      (isArrival ? tuning.arriveEase ?? arriveEase : tuning.leaveEase ?? leaveEase) ??
      opt.easing;
    return {
      ...opt,
      duration: opt.duration != null ? scaleMs(opt.duration, tuning) : undefined,
      delay: opt.delay != null ? scaleMs(opt.delay, tuning) : undefined,
      easing,
    };
  });
}

const BREATH_ARRIVE = "cubic-bezier(0.34, 1.56, 0.64, 1)";
const BREATH_LEAVE = "ease-in";

const BREATH_NODE_ENTER: AnimationOptions[] = [
  { fields: ["opacity"], duration: 90, easing: BREATH_LEAVE },
  { fields: ["opacity"], duration: 360, delay: 30, easing: BREATH_ARRIVE },
  { fields: ["r"], shape: "key", duration: 360, delay: 30, easing: BREATH_ARRIVE },
];

const BREATH_NODE_EXIT: AnimationOptions[] = [
  { fields: ["opacity"], duration: 200, easing: BREATH_LEAVE },
  { fields: ["r"], shape: "key", duration: 200, easing: BREATH_LEAVE },
];

const BLOOM_NODE_ENTER: AnimationOptions[] = [
  { fields: ["opacity", "r"], shape: "key", duration: 420, easing: "ease-out" },
];

const BLOOM_NODE_EXIT: AnimationOptions[] = [
  { fields: ["opacity"], duration: 320, easing: "ease-in" },
  { fields: ["y"], duration: 320, easing: "ease-in" },
];

const RIPPLE_NODE_ENTER: AnimationOptions[] = [
  { fields: ["opacity", "r"], shape: "key", duration: 360, easing: "ease-out" },
];

const RIPPLE_NODE_EXIT: AnimationOptions[] = [
  { fields: ["opacity"], duration: 260, easing: "ease-out" },
  { fields: ["r"], shape: "key", duration: 260, easing: "ease-out" },
];

const EMBER_NODE_ENTER: AnimationOptions[] = [
  { fields: ["opacity"], duration: 150, easing: "ease-out" },
];

const EMBER_NODE_EXIT: AnimationOptions[] = [
  { fields: ["opacity"], duration: 560, easing: "ease-in" },
];

/**
 * Pure scale — no opacity. G6 Tier-1 enter only injects opacity:0, so size/r
 * alone is a no-op. Seed uses enter:false + SeedCircle.onCreate (Gravity)
 * and replaces exit with a real r collapse.
 */
const SEED_NODE_ENTER = false as const;

const SEED_NODE_EXIT: AnimationOptions[] = [
  // Duration/easing overwritten by SeedCircle (Gravity exit Ms).
  { fields: ["size"], duration: 500, easing: "linear" },
];

const QUICK_UPDATE: AnimationOptions[] = [
  {
    fields: ["fill", "stroke", "lineWidth"],
    shape: "key",
    duration: 150,
    easing: "ease-out",
  },
];

const EDGE_QUICK_UPDATE: AnimationOptions[] = [
  {
    fields: ["stroke", "lineWidth"],
    shape: "key",
    duration: 150,
    easing: "ease-out",
  },
];

/** @deprecated Exploration-only. Use the product motion kernel instead. */
export const MOTION_SPINES: Record<SpineId, SpineDef> = {
  breath: {
    id: "breath",
    label: "Breath",
    metaphor: "Hesitate, then spring — leaving is quicker than arriving",
    node: {
      enter: BREATH_NODE_ENTER,
      exit: BREATH_NODE_EXIT,
      update: QUICK_UPDATE,
    },
    edge: {
      enter: "path-in",
      exit: "path-out",
      update: EDGE_QUICK_UPDATE,
    },
    defaults: DEFAULT_TUNING,
  },
  bloom: {
    id: "bloom",
    label: "Bloom",
    metaphor: "Organic growth — decelerating ease-out, wilt on death",
    node: {
      enter: BLOOM_NODE_ENTER,
      exit: BLOOM_NODE_EXIT,
      update: QUICK_UPDATE,
    },
    edge: {
      enter: [{ fields: ["opacity"], duration: 420, easing: "ease-out" }],
      exit: [{ fields: ["opacity"], duration: 280, easing: "ease-in" }],
      update: EDGE_QUICK_UPDATE,
    },
    defaults: DEFAULT_TUNING,
  },
  ripple: {
    id: "ripple",
    label: "Ripple",
    metaphor: "Water — radiating halo on birth, dissolve on death",
    node: {
      enter: RIPPLE_NODE_ENTER,
      exit: RIPPLE_NODE_EXIT,
      update: QUICK_UPDATE,
    },
    edge: {
      enter: [
        { fields: ["opacity"], duration: 200, easing: "ease-out" },
        { fields: ["lineWidth"], shape: "key", duration: 220, delay: 80, easing: "ease-out" },
      ],
      exit: [{ fields: ["opacity", "lineWidth"], shape: "key", duration: 240, easing: "ease-out" }],
      update: EDGE_QUICK_UPDATE,
    },
    defaults: DEFAULT_TUNING,
  },
  ember: {
    id: "ember",
    label: "Ember",
    metaphor: "Quiet arrival, long fade — smoke leaving the field",
    node: {
      enter: EMBER_NODE_ENTER,
      exit: EMBER_NODE_EXIT,
      update: QUICK_UPDATE,
    },
    edge: {
      enter: [{ fields: ["opacity"], duration: 150, easing: "ease-out" }],
      exit: [{ fields: ["opacity"], duration: 520, easing: "ease-in" }],
      update: EDGE_QUICK_UPDATE,
    },
    defaults: DEFAULT_TUNING,
  },
  seed: {
    id: "seed",
    label: "Seed",
    metaphor: "Gravity — mass falls into size, collapses into the void",
    node: {
      enter: SEED_NODE_ENTER,
      exit: SEED_NODE_EXIT,
      update: QUICK_UPDATE,
    },
    edge: {
      // Geometry draw, also no opacity — matches the solid-scale family.
      enter: "path-in",
      exit: "path-out",
      update: EDGE_QUICK_UPDATE,
    },
    defaults: DEFAULT_TUNING,
  },
};

/** @deprecated Exploration-only. */
export const SPINE_IDS = Object.keys(MOTION_SPINES) as SpineId[];

/** @deprecated Exploration-only. Product G6 code uses `g6StateMotion`. */
export function buildSpineAnimations(
  spineId: SpineId,
  tuning: Partial<SpineTuning> = {},
): { node: SpineAnimations; edge: SpineAnimations } {
  const spine = MOTION_SPINES[spineId];
  const merged: SpineTuning = { ...spine.defaults, ...tuning };

  const nodeEnter =
    spine.node.enter === false
      ? false
      : Array.isArray(spine.node.enter)
        ? cloneOptions(spine.node.enter, merged, BREATH_ARRIVE, BREATH_LEAVE)
        : spine.node.enter;
  const nodeExit =
    spine.node.exit === false
      ? false
      : Array.isArray(spine.node.exit)
        ? cloneOptions(spine.node.exit, merged, BREATH_ARRIVE, BREATH_LEAVE)
        : spine.node.exit;
  const nodeUpdate = cloneOptions(spine.node.update, merged, BREATH_ARRIVE, BREATH_LEAVE);

  const edgeEnter =
    spine.edge.enter === false
      ? false
      : Array.isArray(spine.edge.enter)
        ? cloneOptions(spine.edge.enter, merged, BREATH_ARRIVE, BREATH_LEAVE)
        : spine.edge.enter;
  const edgeExit =
    spine.edge.exit === false
      ? false
      : Array.isArray(spine.edge.exit)
        ? cloneOptions(spine.edge.exit, merged, BREATH_ARRIVE, BREATH_LEAVE)
        : spine.edge.exit;
  const edgeUpdate = cloneOptions(spine.edge.update, merged, BREATH_ARRIVE, BREATH_LEAVE);

  return {
    node: { enter: nodeEnter, exit: nodeExit, update: nodeUpdate },
    edge: { enter: edgeEnter, exit: edgeExit, update: edgeUpdate },
  };
}
