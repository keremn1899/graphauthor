/**
 * The product's renderer-independent motion kernel.
 *
 * Renderers do not own the motion language. G6, DOM, SVG, and any future
 * canvas implementation consume the same MotionPlan: intent, physical field,
 * duration, easing, and normalized sampler. Adapters only translate that plan
 * into a renderer's animation API.
 */

export type MotionIntent =
  | "emit"
  | "absorb"
  | "settle"
  | "flow"
  | "hold";

export type MotionCurve = {
  /** Browser-native representation. Exact for the constant-acceleration laws. */
  css: string;
  /** AntV G's native easing name when it has an exact/physical equivalent. */
  g6: string;
  sample: (progress: number) => number;
};

export type MotionField = {
  /** Acceleration of the shared field in CSS pixels per second squared. */
  gravity: number;
  /** Canonical displacement used to derive timing and launch impulse. */
  travel: number;
  /** Inward acceleration multiplier. */
  absorbPull: number;
};

export type MotionPlanOptions = Partial<MotionField> & {
  /** Explicit duration wins; omit it to derive time from the physical field. */
  durationMs?: number;
  /** Intent-specific pull override, useful for calibrated settling. */
  pull?: number;
};

export type MotionPlan = Readonly<{
  intent: MotionIntent;
  durationMs: number;
  easing: MotionCurve;
  field: MotionField;
  pull: number;
  launchImpulse: number;
  sample: (elapsedMs: number) => number;
}>;

export type MotionPlans = Readonly<Record<MotionIntent, MotionPlan>>;

export type MotionPose = {
  x?: number;
  y?: number;
  scale?: number;
  rotate?: number;
  opacity?: number;
};

export const DEFAULT_MOTION_FIELD: MotionField = {
  gravity: 220,
  travel: 8.6,
  absorbPull: 2.18,
};

export const MOTION_DURATION_MS = {
  emit: 280,
  absorb: 190,
  settle: 320,
  flow: 1000,
  hold: 90,
} as const;

export function cubicBezier(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): MotionCurve {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const x = (t: number) => ((ax * t + bx) * t + cx) * t;
  const y = (t: number) => ((ay * t + by) * t + cy) * t;
  const slope = (t: number) => (3 * ax * t + 2 * bx) * t + cx;

  return {
    css: `cubic-bezier(${x1}, ${y1}, ${x2}, ${y2})`,
    g6: `cubic-bezier(${x1}, ${y1}, ${x2}, ${y2})`,
    sample(progress: number) {
      const target = Math.max(0, Math.min(1, progress));
      let t = target;
      for (let iteration = 0; iteration < 5; iteration += 1) {
        const gradient = slope(t);
        if (Math.abs(gradient) < 1e-6) break;
        t = Math.max(0, Math.min(1, t - (x(t) - target) / gradient));
      }
      return y(t);
    },
  };
}

/**
 * Constant acceleration from rest.
 *
 * x(t) = 1/2 at², normalised by x(T), therefore p(u) = u². The cubic-bezier
 * below is not an approximation: with linear x control points it is the exact
 * quadratic polynomial.
 */
export const ABSORB_CURVE: MotionCurve = {
  css: "cubic-bezier(0.333333, 0, 0.666667, 0.333333)",
  g6: "in-quad",
  sample: (progress) => {
    const u = Math.max(0, Math.min(1, progress));
    return u * u;
  },
};

/**
 * The time reverse of Absorb: a body receives the calculated escape impulse
 * and gravity spends it exactly at its authored home. p(u) = 2u - u².
 */
export const EMIT_CURVE: MotionCurve = {
  css: "cubic-bezier(0.333333, 0.666667, 0.666667, 1)",
  g6: "out-quad",
  sample: (progress) => {
    const u = Math.max(0, Math.min(1, progress));
    return 2 * u - u * u;
  },
};

/**
 * Unit damped oscillator around equilibrium.
 *
 * This is an analytic under-damped spring, not a hand-shaped overshoot. The
 * renderer may sample it when it needs the exact trajectory; AntV G can run
 * its native spring without a JavaScript frame loop.
 */
export function dampedOscillator(
  dampingRatio = 0.78,
  angularFrequency = 10,
): MotionCurve {
  const zeta = Math.max(0.01, Math.min(0.999, dampingRatio));
  const omega = Math.max(0.01, angularFrequency);
  const damped = omega * Math.sqrt(1 - zeta * zeta);
  const coefficient = (zeta * omega) / damped;

  return {
    // CSS consumers that cannot sample get the restrained product fallback.
    css: "cubic-bezier(0.2, 0.8, 0.2, 1)",
    g6: "spring",
    sample(progress: number) {
      const u = Math.max(0, Math.min(1, progress));
      if (u === 0 || u === 1) return u;
      return (
        1 -
        Math.exp(-zeta * omega * u) *
          (Math.cos(damped * u) + coefficient * Math.sin(damped * u))
      );
    },
  };
}

/**
 * Product motion grammar.
 *
 * Emit and absorb are deliberately asymmetric: matter arrives with an
 * outward impulse and leaves under inward acceleration. Settle belongs only
 * to released manipulation. Flow is constant signal; hold is pointer-direct.
 *
 * Refine here, not in components. A surface that feels wrong first has the
 * wrong intent (hold during a drag, emit on arrive, absorb on leave). Then
 * it has the wrong pose (which properties, how far — drawers width is geometry,
 * 8.6px is the canonical travel). Only then change this file: a duration or
 * curve edit moves the whole product. `createMotionPlan` accepts a duration
 * override for a calibrated one-off (neighbour preview); do not copy a cubic-
 * bezier into a stylesheet.
 */
export const MOTION_SPINE: Record<MotionIntent, MotionCurve> = {
  emit: EMIT_CURVE,
  absorb: ABSORB_CURVE,
  settle: dampedOscillator(),
  flow: cubicBezier(0, 0, 1, 1),
  hold: cubicBezier(0, 0, 1, 1),
};

export function gravityDurationMs(
  travel: number,
  gravity: number,
  pull = 1,
) {
  const seconds = Math.sqrt(
    (2 * Math.max(0.1, travel)) /
      Math.max(1, gravity * Math.max(0.05, pull)),
  );
  return Math.round(seconds * 1000);
}

export function gravityStrengthForDuration(
  travel: number,
  durationMs: number,
) {
  const seconds = Math.max(0.01, durationMs / 1000);
  return (2 * Math.max(0.1, travel)) / (seconds * seconds);
}

export function gravityPullForDuration(
  travel: number,
  gravity: number,
  durationMs: number,
) {
  return (
    gravityStrengthForDuration(travel, durationMs) /
    Math.max(1, gravity)
  );
}

export function gravityLaunchImpulse(
  travel: number,
  gravity: number,
) {
  return Math.sqrt(
    2 * Math.max(0.1, travel) * Math.max(1, gravity),
  );
}

function defaultPull(intent: MotionIntent, field: MotionField) {
  if (intent === "absorb") return field.absorbPull;
  return 1;
}

function defaultDuration(intent: MotionIntent, field: MotionField, pull: number) {
  if (intent === "emit" || intent === "absorb") {
    return gravityDurationMs(field.travel, field.gravity, pull);
  }
  return MOTION_DURATION_MS[intent];
}

export function createMotionPlan(
  intent: MotionIntent,
  options: MotionPlanOptions = {},
): MotionPlan {
  const field: MotionField = {
    gravity: Math.max(1, options.gravity ?? DEFAULT_MOTION_FIELD.gravity),
    travel: Math.max(0.1, options.travel ?? DEFAULT_MOTION_FIELD.travel),
    absorbPull: Math.max(
      0.05,
      options.absorbPull ?? DEFAULT_MOTION_FIELD.absorbPull,
    ),
  };
  const pull = Math.max(0.05, options.pull ?? defaultPull(intent, field));
  const durationMs = Math.max(
    1,
    Math.round(options.durationMs ?? defaultDuration(intent, field, pull)),
  );
  const easing = MOTION_SPINE[intent];

  return Object.freeze({
    intent,
    durationMs,
    easing,
    field: Object.freeze(field),
    pull,
    launchImpulse: gravityLaunchImpulse(field.travel, field.gravity * pull),
    sample(elapsedMs: number) {
      return easing.sample(
        Math.max(0, Math.min(1, elapsedMs / Math.max(1, durationMs))),
      );
    },
  });
}

export function createMotionPlans(
  field: Partial<MotionField> = {},
  durations: Partial<Record<MotionIntent, number>> = {},
): MotionPlans {
  const shared = {
    gravity: field.gravity,
    travel: field.travel,
    absorbPull: field.absorbPull,
  };
  return Object.freeze({
    emit: createMotionPlan("emit", {
      ...shared,
      durationMs: durations.emit,
    }),
    absorb: createMotionPlan("absorb", {
      ...shared,
      durationMs: durations.absorb,
    }),
    settle: createMotionPlan("settle", {
      ...shared,
      durationMs: durations.settle,
    }),
    flow: createMotionPlan("flow", {
      ...shared,
      durationMs: durations.flow,
    }),
    hold: createMotionPlan("hold", {
      ...shared,
      durationMs: durations.hold,
    }),
  });
}

function poseTransform(pose: MotionPose) {
  const transforms: string[] = [];
  if (pose.x || pose.y) {
    transforms.push(`translate3d(${pose.x ?? 0}px, ${pose.y ?? 0}px, 0)`);
  }
  if (pose.rotate) transforms.push(`rotate(${pose.rotate}deg)`);
  if (pose.scale !== undefined) transforms.push(`scale(${pose.scale})`);
  return transforms.length ? transforms.join(" ") : "none";
}

/**
 * Canonical pose translation for DOM/SVG/Web Animations. The renderer adapter
 * supplies these frames unchanged; the MotionPlan supplies their time law.
 */
export function motionPoseKeyframes(
  from: MotionPose,
  to: MotionPose,
): Keyframe[] {
  return [
    {
      transform: poseTransform(from),
      ...(from.opacity === undefined ? {} : { opacity: from.opacity }),
    },
    {
      transform: poseTransform(to),
      ...(to.opacity === undefined ? {} : { opacity: to.opacity }),
    },
  ];
}

/** CSS-only consumers receive the same plans; no hand-copied timings/curves. */
export function motionCssVariables(plans: MotionPlans) {
  return {
    "--motion-emit-duration": `${plans.emit.durationMs}ms`,
    "--motion-emit-curve": plans.emit.easing.css,
    "--motion-absorb-duration": `${plans.absorb.durationMs}ms`,
    "--motion-absorb-curve": plans.absorb.easing.css,
    "--motion-settle-duration": `${plans.settle.durationMs}ms`,
    "--motion-settle-curve": plans.settle.easing.css,
    "--motion-hold-duration": `${plans.hold.durationMs}ms`,
    "--motion-hold-curve": plans.hold.easing.css,
    "--motion-flow-duration": `${plans.flow.durationMs}ms`,
    "--motion-flow-curve": plans.flow.easing.css,
    "--motion-travel": `${plans.emit.field.travel}px`,
  } as const;
}
