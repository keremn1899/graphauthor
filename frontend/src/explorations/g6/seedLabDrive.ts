import {
  evaluateDilateCurve,
  type DilateCurveParams,
} from "../../shared/motion/dilateCurve";

/**
 * Live drive config for the Seed lab node.
 * Module-level so tuning updates apply to the next birth/death without
 * rebuilding the graph — SeedLabCircle reads this at onCreate / exit.
 */
export type SeedDriveMode = "dilate" | "css";

export type SeedDriveConfig = {
  mode: SeedDriveMode;
  enterMs: number;
  exitMs: number;
  /** CSS easing when mode === "css". */
  enterEase: string;
  exitEase: string;
  enterDilate: DilateCurveParams;
  exitDilate: DilateCurveParams;
  /** Pin radius as fraction of final r (0.02–0.15). */
  pinRatio: number;
  /** Let dilate overshoot past 1 (pupil habit). */
  allowOvershoot: boolean;
};

export type SeedCurveFamily = {
  id: string;
  label: string;
  metaphor: string;
  /** Why it might cohere with Glide Loose — or when it doesn't. */
  glideNote: string;
  mode: SeedDriveMode;
  enterMs: number;
  exitMs: number;
  enterEase?: string;
  exitEase?: string;
  enterDilate?: DilateCurveParams;
  exitDilate?: DilateCurveParams;
  allowOvershoot?: boolean;
};

/**
 * Candidate languages for a shared motion curve.
 * Asymmetry is intentional: arrival ≠ departure (same rule as the spines).
 */
export const SEED_CURVE_FAMILIES: SeedCurveFamily[] = [
  {
    id: "aperture",
    label: "Aperture",
    metaphor:
      "Mechanical iris — open decelerates into frame, close accelerates shut. No overshoot.",
    glideNote: "Cleaner than pupil; still asymmetric. Reads well beside Yield physics.",
    mode: "dilate",
    enterMs: 720,
    exitMs: 480,
    enterDilate: {
      // A bit more held beat and a much higher ωₙ than before, with ζ
      // pulled down to exactly critical (1.0) — the fastest possible open
      // that still can't overshoot. Reads as sharper / more "violent" than
      // the old 1.05, without borrowing Pupil's actual bounce.
      kind: "spring",
      hesitation: 0.09,
      tension: 13,
      damping: 1.0,
      power: 2.85,
    },
    exitDilate: {
      kind: "spring",
      hesitation: 0.02,
      tension: 12,
      damping: 1.1,
      power: 2.85,
    },
    allowOvershoot: false,
  },
  {
    id: "pupil",
    label: "Pupil",
    metaphor:
      "Held beat, then opens past target and settles — close is snug and reflexive.",
    glideNote:
      "Organic punctuation on soft physics. Overshoot is muscle, not bounce theatre.",
    mode: "dilate",
    enterMs: 900,
    exitMs: 420,
    enterDilate: {
      kind: "spring",
      hesitation: 0.12,
      tension: 7.5,
      damping: 0.42,
      power: 2.85,
    },
    exitDilate: {
      kind: "spring",
      hesitation: 0.03,
      tension: 13,
      damping: 0.92,
      power: 2.85,
    },
    allowOvershoot: true,
  },
  {
    id: "glide-yield",
    label: "Glide yield",
    metaphor:
      "Same dialect as loose glide: soft arrival into place, soft leave into the point.",
    glideNote: "Most continuous with field physics — punctuation stays yielding.",
    mode: "css",
    enterMs: 780,
    exitMs: 560,
    enterEase: "cubic-bezier(0.22, 0.61, 0.36, 1)",
    exitEase: "cubic-bezier(0.55, 0.06, 0.68, 0.19)",
    allowOvershoot: false,
  },
  {
    id: "gravity",
    label: "Gravity",
    metaphor:
      "Mass falls into size (decelerates into rest); collapses by accelerating into the void.",
    glideNote: "Classic physics punctuation. Stronger character than Glide yield.",
    mode: "css",
    enterMs: 700,
    exitMs: 500,
    enterEase: "cubic-bezier(0.16, 1, 0.3, 1)",
    exitEase: "cubic-bezier(0.7, 0, 0.84, 0)",
    allowOvershoot: false,
  },
  {
    id: "mercury",
    label: "Mercury",
    metaphor:
      "Surface tension bead — grows with slow resolve, pulls into itself near the end.",
    glideNote: "Material metaphor; pairs with soft charge — a bit more decorative.",
    mode: "css",
    enterMs: 860,
    exitMs: 620,
    enterEase: "cubic-bezier(0.33, 0.0, 0.2, 1)",
    exitEase: "cubic-bezier(0.4, 0.0, 0.2, 1)",
    allowOvershoot: false,
  },
  {
    id: "tide",
    label: "Tide",
    metaphor: "Patient symmetric swell — almost no attack or release accent.",
    glideNote: "May under-punctuate against loose glide (physics already soft).",
    mode: "css",
    enterMs: 960,
    exitMs: 960,
    enterEase: "ease-in-out",
    exitEase: "ease-in-out",
    allowOvershoot: false,
  },
  {
    id: "drop",
    label: "Syrup drop",
    metaphor: "Heavy decelerating land; leaving has to overcome viscosity then falls.",
    glideNote: "Contrast — denser than Glide Loose; good for stress-testing softness.",
    mode: "css",
    enterMs: 1100,
    exitMs: 700,
    enterEase: "cubic-bezier(0.08, 0.82, 0.17, 1)",
    exitEase: "cubic-bezier(0.76, 0.05, 0.86, 0.06)",
    allowOvershoot: false,
  },
];

export const DEFAULT_SEED_FAMILY =
  SEED_CURVE_FAMILIES.find((f) => f.id === "gravity") ?? SEED_CURVE_FAMILIES[0];

export function driveFromFamily(family: SeedCurveFamily): SeedDriveConfig {
  return {
    mode: family.mode,
    enterMs: family.enterMs,
    exitMs: family.exitMs,
    enterEase: family.enterEase ?? "ease-in",
    exitEase: family.exitEase ?? "ease-out",
    enterDilate: family.enterDilate ?? {
      kind: "spring",
      hesitation: 0.1,
      tension: 8,
      damping: 0.7,
      power: 2.85,
    },
    exitDilate: family.exitDilate ?? {
      kind: "spring",
      hesitation: 0.02,
      tension: 12,
      damping: 1,
      power: 2.85,
    },
    pinRatio: 0.04,
    allowOvershoot: family.allowOvershoot ?? false,
  };
}

let drive: SeedDriveConfig = driveFromFamily(DEFAULT_SEED_FAMILY);

export function getSeedDrive(): SeedDriveConfig {
  return drive;
}

export function setSeedDrive(next: Partial<SeedDriveConfig> | SeedDriveConfig) {
  drive = { ...drive, ...next };
}

/** Sample a CSS cubic-bezier / named ease for curve drawing. */
export function sampleCssEase(easing: string, n = 64): { t: number; v: number }[] {
  const bezier = parseCssEase(easing);
  const out: { t: number; v: number }[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    out.push({ t, v: unitBezier(bezier[0], bezier[1], bezier[2], bezier[3], t) });
  }
  return out;
}

export function sampleDilateEase(
  params: DilateCurveParams,
  n = 64,
): { t: number; v: number }[] {
  const out: { t: number; v: number }[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    out.push({ t, v: evaluateDilateCurve(t, params) });
  }
  return out;
}

/** Build WAAPI keyframes for radius; bakes custom curves as linear segments. */
export function buildRadiusKeyframes(
  fromR: number,
  toR: number,
  cfg: SeedDriveConfig,
  stage: "enter" | "exit",
): { keyframes: Keyframe[]; options: KeyframeAnimationOptions } {
  const duration = stage === "enter" ? cfg.enterMs : cfg.exitMs;
  const span = toR - fromR;

  if (cfg.mode === "css") {
    const easing = stage === "enter" ? cfg.enterEase : cfg.exitEase;
    return {
      keyframes: [{ r: fromR }, { r: toR }],
      options: { duration, easing, fill: "both" },
    };
  }

  const params = stage === "enter" ? cfg.enterDilate : cfg.exitDilate;
  const samples = 28;
  const keyframes: Keyframe[] = [];
  for (let i = 0; i < samples; i++) {
    const t = i / (samples - 1);
    let v = evaluateDilateCurve(t, params);
    if (!cfg.allowOvershoot) v = Math.min(1, Math.max(0, v));
    keyframes.push({ r: fromR + span * v });
  }
  return {
    keyframes,
    options: { duration, easing: "linear", fill: "both" },
  };
}

const NAMED_BEZIERS: Record<string, [number, number, number, number]> = {
  linear: [0, 0, 1, 1],
  ease: [0.25, 0.1, 0.25, 1],
  "ease-in": [0.42, 0, 1, 1],
  "ease-out": [0, 0, 0.58, 1],
  "ease-in-out": [0.42, 0, 0.58, 1],
};

function parseCssEase(easing: string): [number, number, number, number] {
  const named = NAMED_BEZIERS[easing.trim()];
  if (named) return named;
  const m = easing.match(
    /cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/,
  );
  if (!m) return NAMED_BEZIERS["ease-in-out"];
  return [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])];
}

/** Unit bezier Y given X≈t (Newton solve). */
function unitBezier(
  p1x: number,
  p1y: number,
  p2x: number,
  p2y: number,
  x: number,
): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  let t = x;
  for (let i = 0; i < 6; i++) {
    const xEst = bezierX(t, p1x, p2x) - x;
    const dx = bezierDX(t, p1x, p2x);
    if (Math.abs(xEst) < 1e-5 || Math.abs(dx) < 1e-6) break;
    t -= xEst / dx;
  }
  t = Math.min(1, Math.max(0, t));
  return bezierY(t, p1y, p2y);
}

function bezierX(t: number, p1x: number, p2x: number) {
  const u = 1 - t;
  return 3 * u * u * t * p1x + 3 * u * t * t * p2x + t * t * t;
}

function bezierDX(t: number, p1x: number, p2x: number) {
  const u = 1 - t;
  return 3 * u * u * p1x + 6 * u * t * (p2x - p1x) + 3 * t * t * (1 - p2x);
}

function bezierY(t: number, p1y: number, p2y: number) {
  const u = 1 - t;
  return 3 * u * u * t * p1y + 3 * u * t * t * p2y + t * t * t;
}
