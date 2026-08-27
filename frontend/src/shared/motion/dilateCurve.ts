/**
 * Shared "dilate" curve — one curve family reused by every dilation-style
 * effect (edge forming, future ring/selection reveals) so they read as the
 * same gesture rather than each screen inventing its own easing.
 *
 * The model is a damped-spring *step response*, not an arbitrary easing
 * polynomial. That choice is deliberate: "dilation" (pupil, iris, aperture)
 * isn't a smooth mechanical glide — it's a held beat of tension, then a
 * release that slightly overshoots before settling, because the muscle
 * doing it isn't fully under conscious control. Two knobs carry that:
 *
 * - `hesitation` — a short pre-roll where almost nothing moves (the beat
 *   before the iris "decides" to open — pupillary latency is real and ~200ms).
 * - `damping` (ζ) < 1 — underdamped, so the value overshoots past 1 and
 *   settles back. That overshoot *is* the vulnerability: a reaction that
 *   isn't perfectly controlled. ζ ≥ 1 removes it (a "constrict" reads
 *   tighter, more reflexive, closer to critically damped).
 * - `tension` (ωₙ) — how fast the spring wants to move; higher reads sharper.
 *
 * `linear` and `easeOutPow` are kept only as reference / legacy comparisons.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type DilateCurveKind = "spring" | "linear" | "easeOutPow";

export type DilateCurveParams = {
  kind: DilateCurveKind;
  /** Fraction of the timeline spent in the pre-roll (0–0.4). Spring only. */
  hesitation: number;
  /** Natural frequency ωₙ — speed of the response (≈3–16). Spring only. */
  tension: number;
  /** Damping ratio ζ — <1 overshoots (vulnerable), ≥1 settles clean. Spring only. */
  damping: number;
  /** Exponent for the legacy `easeOutPow` curve. */
  power: number;
};

export type DilatePreset = {
  id: string;
  label: string;
  hint: string;
  params: DilateCurveParams;
};

export const DILATE_PRESETS: DilatePreset[] = [
  {
    id: "pupil-dilate",
    label: "Pupil dilate",
    hint: "Held beat, then opens past target and settles back — tension, released.",
    params: { kind: "spring", hesitation: 0.12, tension: 7.5, damping: 0.42, power: 2.85 },
  },
  {
    id: "pupil-constrict",
    label: "Pupil constrict",
    hint: "Fast, controlled close — reflexive, almost no overshoot.",
    params: { kind: "spring", hesitation: 0.03, tension: 13, damping: 0.92, power: 2.85 },
  },
  {
    id: "mechanical-ease",
    label: "Mechanical ease (old)",
    hint: "Previous edge-dilate curve — monotonic, no tension or release.",
    params: { kind: "easeOutPow", hesitation: 0, tension: 8, damping: 0.5, power: 2.85 },
  },
  {
    id: "linear",
    label: "Linear (reference)",
    hint: "No shaping — baseline to judge the others against.",
    params: { kind: "linear", hesitation: 0, tension: 8, damping: 0.5, power: 1 },
  },
];

export const DEFAULT_DILATE_PRESET = DILATE_PRESETS[0];

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

function easeInQuad(u: number): number {
  return u * u;
}

/** Closed-form unit step response of a damped harmonic oscillator, t ≥ 0. */
function springStep(t: number, omegaN: number, zeta: number): number {
  if (t <= 0) return 0;
  const wn = Math.max(0.001, omegaN);
  if (zeta < 0.999) {
    const wd = wn * Math.sqrt(1 - zeta * zeta);
    const decay = Math.exp(-zeta * wn * t);
    return (
      1 -
      decay *
        (Math.cos(wd * t) + (zeta / Math.sqrt(1 - zeta * zeta)) * Math.sin(wd * t))
    );
  }
  if (zeta > 1.001) {
    const s = Math.sqrt(zeta * zeta - 1);
    const r1 = -wn * (zeta - s);
    const r2 = -wn * (zeta + s);
    return 1 - (r2 * Math.exp(r1 * t) - r1 * Math.exp(r2 * t)) / (r2 - r1);
  }
  const decay = Math.exp(-wn * t);
  return 1 - decay * (1 + wn * t);
}

/**
 * Evaluate the curve at normalized time t ∈ [0,1]. For `spring`, the return
 * value can exceed 1 (overshoot) or dip slightly below it on the way back —
 * that's intentional signal, not a bug; callers decide whether to clamp.
 */
export function evaluateDilateCurve(t: number, params: DilateCurveParams): number {
  const x = clamp01(t);
  if (params.kind === "linear") return x;
  if (params.kind === "easeOutPow") {
    return 1 - Math.pow(1 - x, Math.max(0.1, params.power));
  }

  const hesitation = Math.min(0.4, Math.max(0, params.hesitation));
  if (hesitation > 0 && x < hesitation) {
    return easeInQuad(x / hesitation) * 0.05;
  }
  const span = 1 - hesitation;
  const localT = span > 0 ? (x - hesitation) / span : x;
  const floor = hesitation > 0 ? 0.05 : 0;
  return floor + (1 - floor) * springStep(localT, params.tension, params.damping);
}

export function sampleDilateCurve(
  params: DilateCurveParams,
  steps = 140,
): { t: number; v: number }[] {
  const samples: { t: number; v: number }[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    samples.push({ t, v: evaluateDilateCurve(t, params) });
  }
  return samples;
}

/**
 * Drives normalized time t from 0→1 over `durationMs`, shared by every
 * dilate-style playback (edge rows, the curve tuner, future effects) so
 * "play" always means the same thing: one rAF loop, one clock.
 */
export function useDilatePlayback(durationMs: number) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rafRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    setPlaying(false);
  }, []);

  const play = useCallback(
    (durationOverrideMs?: number) => {
      stop();
      const duration = Math.max(1, durationOverrideMs ?? durationMs);
      setPlaying(true);
      setT(0);
      const t0 = performance.now();
      const tick = (now: number) => {
        const elapsed = now - t0;
        const next = Math.min(1, elapsed / duration);
        setT(next);
        if (next < 1) {
          rafRef.current = requestAnimationFrame(tick);
        } else {
          rafRef.current = null;
          setPlaying(false);
        }
      };
      rafRef.current = requestAnimationFrame(tick);
    },
    [durationMs, stop],
  );

  useEffect(() => stop, [stop]);

  return { t, setT, playing, play, stop };
}
