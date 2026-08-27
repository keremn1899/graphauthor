/**
 * Lightweight value-noise field for membrane life.
 * Continuous in space/time — no obvious loop like keyframed border-radius.
 */

function fade(t: number) {
  return t * t * t * (t * (t * 6 - 15) + 10);
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

/** Deterministic hash → 0..1 */
function hash2(ix: number, iy: number) {
  const s = Math.sin(ix * 127.1 + iy * 311.7) * 43758.5453123;
  return s - Math.floor(s);
}

/** Smooth value noise in 2D → roughly 0..1 */
export function valueNoise2D(x: number, y: number): number {
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const fx = fade(x - x0);
  const fy = fade(y - y0);
  const a = hash2(x0, y0);
  const b = hash2(x0 + 1, y0);
  const c = hash2(x0, y0 + 1);
  const d = hash2(x0 + 1, y0 + 1);
  return lerp(lerp(a, b, fx), lerp(c, d, fx), fy);
}

/** Map to -1..1 */
export function noise2D(x: number, y: number): number {
  return valueNoise2D(x, y) * 2 - 1;
}

export type MembraneNoiseParams = {
  /** Peak outward displacement in px */
  amp: number;
  /** Spatial lobule density around the circle */
  spatial: number;
  /** How fast noise coordinates advance per second */
  step: number;
  /** Second octave weight (0 = smooth provisional, >0 = frayed) */
  detail: number;
  /** Stable per-node seed so masses don't sync */
  seed: number;
};

/**
 * Filled mass silhouette — noise displaces the boundary only.
 * One body (no separate ring), so nothing can gap from the fill.
 */
export function noiseMembranePath(
  cx: number,
  cy: number,
  radius: number,
  time: number,
  params: MembraneNoiseParams,
  points = 96,
): string {
  const { amp, spatial, detail, seed } = params;
  let d = "";

  for (let i = 0; i <= points; i++) {
    const a = (i / points) * Math.PI * 2;
    const px = Math.cos(a) * spatial + seed;
    const py = Math.sin(a) * spatial * 1.17 + seed * 0.73;

    const n1 = noise2D(px + time, py + time * 0.81);
    const n2 =
      detail > 0
        ? noise2D(px * 2.3 + time * 1.4 + 10, py * 2.3 - time * 1.1 + 7)
        : 0;
    const n = n1 * (1 - detail) + n2 * detail;

    // Symmetric displace around the resting radius (alive edge, one body)
    const rr = radius + amp * n;
    const x = cx + Math.cos(a) * rr;
    const y = cy + Math.sin(a) * rr;
    d += i === 0 ? `M ${x.toFixed(2)} ${y.toFixed(2)}` : ` L ${x.toFixed(2)} ${y.toFixed(2)}`;
  }

  return `${d} Z`;
}
