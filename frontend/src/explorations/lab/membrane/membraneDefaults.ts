import type { MembraneNoiseParams } from "./noiseMembrane";

/** Lab specimen radius — amp is authored at this scale. */
export const MEMBRANE_LAB_RADIUS = 84;

export type MembraneStatus = "settled" | "provisional" | "unresolved";

/** Locked defaults from membrane lab tuning. */
export const MEMBRANE_DEFAULTS: Record<
  "provisional" | "unresolved",
  Omit<MembraneNoiseParams, "seed">
> = {
  provisional: { amp: 1.8, spatial: 4.2, step: 0.8, detail: 0.65 },
  unresolved: { amp: 3.6, spatial: 2, step: 0.8, detail: 0.55 },
};

/** Same thresholds as the membrane lab certainty slider. */
export function membraneStatus(certainty01: number): MembraneStatus {
  if (certainty01 >= 0.72) return "settled";
  if (certainty01 >= 0.38) return "provisional";
  return "unresolved";
}

/** Stable 0..1 seed from a string id so nodes don't sync-swim. */
export function membraneSeed(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return (h % 1000) / 1000;
}

/**
 * Params for a mass at `radius` px. Amp scales from the lab specimen size
 * so relative edge height matches the tuned look.
 */
export function membraneParamsFor(
  certainty01: number,
  radius: number,
  seedKey: string,
): MembraneNoiseParams | null {
  const status = membraneStatus(certainty01);
  if (status === "settled") return null;
  const base = MEMBRANE_DEFAULTS[status];
  const scale = radius / MEMBRANE_LAB_RADIUS;
  return {
    ...base,
    amp: base.amp * scale,
    seed: membraneSeed(seedKey),
  };
}
