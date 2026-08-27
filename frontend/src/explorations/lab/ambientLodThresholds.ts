/** Pure LOD threshold helpers — shared by AmbientLodLabPage. */

export type LodBand = "far" | "mid" | "near";

export const FAR_IMPORTANCE = 0.62;
export const MID_IMPORTANCE = 0.28;
export const FAR_ZOOM = 0.5;
export const MID_ZOOM = 0.95;
export const NEAR_ZOOM = 1.45;

/** Static graph-space diameters (baked once — camera zoom scales them together). */
export const SIZE_LANDMARK = 64;
export const SIZE_HUB = 44;
export const SIZE_LEAF = 28;

/** Below this on-screen px, glyphs/labels are omitted (readability gate). */
export const READABLE_PX = 8;

export function bandForZoom(zoom: number): LodBand {
  if (zoom < FAR_ZOOM + (MID_ZOOM - FAR_ZOOM) * 0.4) return "far";
  if (zoom < MID_ZOOM + (NEAR_ZOOM - MID_ZOOM) * 0.35) return "mid";
  return "near";
}

/**
 * Band with hysteresis so threshold chatter does not thrash `draw()`.
 * Enter/leave thresholds are asymmetric around the soft band boundaries.
 */
export function bandWithHysteresis(zoom: number, prev: LodBand): LodBand {
  const farExit = FAR_ZOOM + (MID_ZOOM - FAR_ZOOM) * 0.55;
  const farEnter = FAR_ZOOM + (MID_ZOOM - FAR_ZOOM) * 0.28;
  const nearEnter = MID_ZOOM + (NEAR_ZOOM - MID_ZOOM) * 0.45;
  const nearExit = MID_ZOOM + (NEAR_ZOOM - MID_ZOOM) * 0.12;

  if (prev === "far") {
    if (zoom < farExit) return "far";
    return zoom >= nearEnter ? "near" : "mid";
  }
  if (prev === "near") {
    if (zoom > nearExit) return "near";
    return zoom <= farEnter ? "far" : "mid";
  }
  if (zoom <= farEnter) return "far";
  if (zoom >= nearEnter) return "near";
  return "mid";
}

/** Minimum importance drawn at this zoom — soft ramp for crossfade. */
export function importanceFloor(zoom: number): number {
  if (zoom <= FAR_ZOOM) return FAR_IMPORTANCE;
  if (zoom >= NEAR_ZOOM) return 0;
  if (zoom < MID_ZOOM) {
    const t = (zoom - FAR_ZOOM) / (MID_ZOOM - FAR_ZOOM);
    return FAR_IMPORTANCE + (MID_IMPORTANCE - FAR_IMPORTANCE) * t;
  }
  const t = (zoom - MID_ZOOM) / (NEAR_ZOOM - MID_ZOOM);
  return MID_IMPORTANCE * (1 - t);
}

function smoothstep(edge0: number, edge1: number, x: number) {
  const t = Math.max(
    0,
    Math.min(1, (x - edge0) / Math.max(1e-6, edge1 - edge0)),
  );
  return t * t * (3 - 2 * t);
}

/** Opacity 0…1 from importance vs current zoom floor. */
export function lodOpacity(
  importance: number,
  zoom: number,
  landmark: boolean,
) {
  const floor = importanceFloor(zoom);
  if (landmark) {
    return Math.max(0.88, smoothstep(floor - 0.2, floor + 0.08, importance));
  }
  return smoothstep(floor - 0.18, floor + 0.22, importance);
}

/** Fixed size tier — set once at layout; never rewrite on zoom. */
export function staticNodeSize(importance: number, landmark: boolean): number {
  if (landmark) return SIZE_LANDMARK;
  if (importance >= 0.45) return SIZE_HUB;
  return SIZE_LEAF;
}

export function staticLabelFontSize(graphSize: number): number {
  return Math.max(7, Math.min(12, graphSize * 0.18));
}

/** True when the glyph is large enough on screen to keep drawing. */
export function isScreenReadable(graphSize: number, zoom: number): boolean {
  return graphSize * Math.max(0.05, zoom) >= READABLE_PX;
}
