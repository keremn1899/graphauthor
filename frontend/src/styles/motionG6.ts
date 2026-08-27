import type { MotionPlan } from "./motion";

export type G6MotionOptions = {
  fields: string[];
  shape?: string;
};

/**
 * Translate a product MotionPlan into G6's native state-animation contract.
 * Values still come from G6 element states; only the renderer boundary lives
 * here.
 */
export function g6StateMotion(
  plan: MotionPlan,
  { fields, shape }: G6MotionOptions,
) {
  return {
    ...(shape ? { shape } : {}),
    fields,
    duration: plan.durationMs,
    easing: plan.easing.g6,
  };
}

/** Options for custom G/G6 shapes that animate through `shape.animate()`. */
export function g6KeyframeMotion(plan: MotionPlan) {
  return {
    duration: plan.durationMs,
    easing: plan.easing.g6,
    fill: "both" as const,
  };
}
