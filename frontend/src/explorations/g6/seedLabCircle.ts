import { Circle, ExtensionCategory, register } from "@antv/g6";
import { buildRadiusKeyframes, getSeedDrive } from "./seedLabDrive";

/**
 * Seed lab node — reads live drive config so tuning applies on the next
 * birth/death without remounting the graph.
 */
class SeedLabCircle extends Circle {
  onCreate() {
    const key = this.getShape("key");
    if (!key) return;

    const cfg = getSeedDrive();
    const targetR = Number(key.attr("r")) || 25;
    const pinR = Math.max(0.35, targetR * cfg.pinRatio);
    key.attr("r", pinR);

    const label = this.getShape("label");
    if (label) label.attr("opacity", 0);

    const { keyframes, options } = buildRadiusKeyframes(pinR, targetR, cfg, "enter");
    const anim = key.animate(keyframes, options);
    anim?.finished.then(() => {
      if (!this.destroyed) {
        // Snap to exact target after possible overshoot settle.
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

    const cfg = getSeedDrive();
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

let registered = false;

export function ensureSeedLabCircleRegistered() {
  if (registered) return;
  register(ExtensionCategory.NODE, "seed-lab-circle", SeedLabCircle);
  registered = true;
}
