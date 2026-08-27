import { Circle, ExtensionCategory, register } from "@antv/g6";
import {
  buildRadiusKeyframes,
  driveFromFamily,
  SEED_CURVE_FAMILIES,
  type SeedDriveConfig,
} from "./seedLabDrive";

const GRAVITY =
  SEED_CURVE_FAMILIES.find((f) => f.id === "gravity") ?? SEED_CURVE_FAMILIES[0];

/** Chosen Seed language — Gravity. Shared by lifecycle + connect spines. */
export const SEED_SPINE_DRIVE: SeedDriveConfig = driveFromFamily(GRAVITY);

/**
 * Seed spine node.
 *
 * Tier-1 note: G6 enter/exit only inject opacity:0 — not size/r — so a bare
 * `{ fields: ["r"] }` is a no-op. Seed keeps the Tier-1 *stage contract*
 * (enter: false → onCreate; exit stage → collapse) but drives scale with
 * Gravity keyframes. Prefer built-ins everywhere else.
 */
class SeedCircle extends Circle {
  onCreate() {
    const key = this.getShape("key");
    if (!key) return;

    const cfg = resolveDrive(this.attributes as Record<string, unknown>);
    const targetR = Number(key.attr("r")) || 25;
    const pinR = Math.max(0.35, targetR * cfg.pinRatio);
    key.attr("r", pinR);

    const label = this.getShape("label");
    if (label) label.attr("opacity", 0);

    const { keyframes, options } = buildRadiusKeyframes(pinR, targetR, cfg, "enter");
    const anim = key.animate(keyframes, options);
    anim?.finished.then(() => {
      if (!this.destroyed) {
        key.attr("r", targetR);
        if (label) label.attr("opacity", 1);
      }
    });
  }

  animate(keyframes: any, options?: number | KeyframeAnimationOptions) {
    const exiting = Boolean(
      (this as unknown as { __to_be_destroyed__?: boolean }).__to_be_destroyed__,
    );
    if (!exiting) return super.animate(keyframes, options);

    const key = this.getShape("key");
    if (!key) return super.animate(keyframes, options);

    const cfg = resolveDrive(this.attributes as Record<string, unknown>);
    const fromR = Number(key.attr("r")) || 25;
    const pinR = Math.max(0.35, fromR * cfg.pinRatio);

    const label = this.getShape("label");
    label?.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: Math.min(cfg.exitMs, 240),
      fill: "forwards",
    });

    const baked = buildRadiusKeyframes(fromR, pinR, cfg, "exit");
    return key.animate(baked.keyframes, baked.options);
  }
}

function resolveDrive(attrs: Record<string, unknown>): SeedDriveConfig {
  const base = { ...SEED_SPINE_DRIVE };
  if (typeof attrs.seedEnterDuration === "number") {
    base.enterMs = attrs.seedEnterDuration;
  }
  if (typeof attrs.seedExitDuration === "number") {
    base.exitMs = attrs.seedExitDuration;
  }
  return base;
}

let registered = false;

export function ensureSeedCircleRegistered() {
  if (registered) return;
  register(ExtensionCategory.NODE, "seed-circle", SeedCircle);
  registered = true;
}
