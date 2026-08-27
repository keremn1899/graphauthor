/**
 * Whether a thing keeps a frame while it runs — and against what.
 *
 * Every motion lab in here could show an effect and none could tell you what it
 * cost. `drawMs` was the closest thing, and it answers a different question:
 * how long one repaint took. An effect that repaints in 8 ms on every frame and
 * one that repaints once are the same `drawMs` and completely different
 * products. The number that decides whether motion ships is the frame
 * distribution while it is running, and the tail of it, because the tail is
 * what an operator feels.
 *
 * **The baseline is not optional.** Read on its own, an absolute threshold
 * condemns the substrate: at 2000 nodes a mounted canvas with nothing running
 * measures 16.7 / 33.3, so any rule strict enough to catch a real problem also
 * fails the empty control. Every verdict here is a difference against a
 * do-nothing arm at the same size, and an effect earns "free" by not moving a
 * number the page would have shown anyway.
 *
 * Shared rather than copied: two labs asking the same question with two
 * implementations is how they end up disagreeing about the same effect.
 */

export type FrameStat = {
  median: number;
  p95: number;
  worst: number;
  frames: number;
  /** Node count this was taken at. A baseline belongs to exactly one size. */
  scale: number;
};

/** Sample frame deltas for `ms`, then report the shape of the distribution. */
export function sampleFrames(ms: number): Promise<Omit<FrameStat, "scale">> {
  return new Promise((resolve) => {
    const deltas: number[] = [];
    let last = performance.now();
    const started = last;
    const tick = (t: number) => {
      deltas.push(t - last);
      last = t;
      if (t - started < ms) requestAnimationFrame(tick);
      else {
        // The opening frames carry whatever scheduled the sample.
        const f = deltas.slice(2).sort((a, b) => a - b);
        // No frames is not zero milliseconds — it is the worst possible
        // result. A main thread blocked for the whole window never runs the
        // callback, so the samples are empty; reading a quantile of nothing
        // returned 0, and 0 against a 43 ms baseline scored **"free"**. A
        // complete freeze was the best grade this page could award.
        //
        // The honest reading is that one frame spanned the window: nothing
        // was painted in it, so that is the frame time.
        if (!f.length) {
          const span = Math.round(t - started);
          resolve({ median: span, p95: span, worst: span, frames: 0 });
          return;
        }
        const q = (p: number) =>
          Math.round((f[Math.floor(f.length * p)] ?? 0) * 10) / 10;
        resolve({
          median: q(0.5),
          p95: q(0.95),
          worst: Math.round(f[f.length - 1] ?? 0),
          frames: f.length,
        });
      }
    };
    requestAnimationFrame(tick);
  });
}

/**
 * The verdict, as a difference.
 *
 * A display can run at 60 or 120 Hz and both are fine, so the bands are read
 * off the *gap* first and only fall back to absolutes once an effect has
 * clearly moved the number.
 */
export function verdictFor(
  stat: FrameStat | null,
  base: FrameStat | null,
): string {
  if (!stat) return "not measured";
  // Checked before the baseline comparison, and before anything else: a
  // starved sample is a result in its own right, and it must never be able to
  // reach the "free" branch by arithmetic.
  if (!stat.frames) return "blocked — no frame painted";
  if (base && base.frames && stat.frames < base.frames / 4) {
    return `stalling — ${stat.frames} frames where idle drew ${base.frames}`;
  }
  if (!base || base.scale !== stat.scale) return "no baseline at this size";
  const delta = stat.p95 - base.p95;
  if (delta <= 2) return "free";
  if (stat.p95 <= 20) return "holds 60";
  if (stat.p95 <= 40) return "costs a frame";
  return "does not hold";
}

/** One line of numbers, so both labs print the comparison identically. */
export function frameSummary(
  stat: FrameStat | null,
  base: FrameStat | null,
): string {
  if (!stat) return "median / p95 unmeasured";
  const against =
    base && base.scale === stat.scale
      ? ` vs ${base.median} / ${base.p95} idle`
      : "";
  // Frame counts are shown, not just the quantiles. They are how a reader
  // sees that a sample was starved rather than fast.
  return `${stat.median} / ${stat.p95} ms${against} at ${stat.scale}n · ${stat.frames}f${
    base && base.scale === stat.scale ? `/${base.frames}f` : ""
  }`;
}
