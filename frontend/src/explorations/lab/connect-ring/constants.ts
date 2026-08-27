/** Connect-ring lab constants — Note Prototype RING_SCALE, Field-scale discs. */

export const NODE_R = 52;
export const RING_SCALE = 1.25;
export const RING_R = NODE_R * RING_SCALE; // 65
export const LONG_PRESS_MS = 400;
/** Damped-sine drive duration before waiting for spring rest to lock. */
export const TAUT_DRIVE_MS = 580;

/** SVG even-odd annulus: outer RING_R, hole NODE_R, centered in a (RING_R*2) box. */
export function annulusClipPath(outer = RING_R, inner = NODE_R): string {
  const box = outer * 2;
  const mid = outer;
  const hole = outer - inner;
  return `path('M ${mid} 0 A ${outer} ${outer} 0 1 1 ${mid} ${box} A ${outer} ${outer} 0 1 1 ${mid} 0 Z M ${mid} ${hole} A ${inner} ${inner} 0 1 0 ${mid} ${box - hole} A ${inner} ${inner} 0 1 0 ${mid} ${hole} Z')`;
}

export function dist(
  a: { x: number; y: number },
  b: { x: number; y: number },
): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Point on circumference of a disc, from center toward `toward`. */
export function boundaryPoint(
  center: { x: number; y: number },
  toward: { x: number; y: number },
  radius = NODE_R,
): { x: number; y: number } {
  const d = dist(center, toward) || 1;
  return {
    x: center.x + ((toward.x - center.x) / d) * radius,
    y: center.y + ((toward.y - center.y) / d) * radius,
  };
}

/**
 * Floating chord ends (Note Prototype getEdgeParams): rim↔rim along centre line.
 * Same helper for drag-preview, land tether, and firm edge — no endpoint jump.
 */
export function chordEnds(
  a: { x: number; y: number },
  b: { x: number; y: number },
  radius = NODE_R,
): { from: { x: number; y: number }; to: { x: number; y: number } } {
  return {
    from: boundaryPoint(a, b, radius),
    to: boundaryPoint(b, a, radius),
  };
}

export function inAnnulus(
  center: { x: number; y: number },
  point: { x: number; y: number },
  inner = NODE_R,
  outer = RING_R,
): boolean {
  const d = dist(center, point);
  return d > inner - 2 && d <= outer + 2;
}

export function inDisc(
  center: { x: number; y: number },
  point: { x: number; y: number },
  radius = NODE_R + 8,
): boolean {
  return dist(center, point) <= radius;
}
