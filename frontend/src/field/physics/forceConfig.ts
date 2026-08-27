import type { SimLink, SimNode } from "../data/fieldGraph";
import { CONCEPT_NODE_RADIUS } from "../data/fieldGraph";

/**
 * Watery / fluid force tuning (inspired by d3-force defaults + looser recipes):
 * - Default velocityDecay is 0.4; 0.72 felt solid. Lower decay ≈ less “air friction”,
 *   nodes keep momentum and settle like in a viscous fluid.
 * - Softer links + milder charge so edges are elastic tethers, not rigid rods.
 * - Gentler collide + slower alphaDecay so the field keeps breathing longer.
 *
 * Refs: d3-force velocityDecay docs; Steve Haroz force playground.
 */

export function chargeStrength(_d: SimNode): number {
  return -150;
}

export function collideRadius(_d: SimNode): number {
  return CONCEPT_NODE_RADIUS + 36;
}

export function linkDistance(link: SimLink): number {
  switch (link.kind) {
    case "CONTAINS":
      return 165;
    case "LEADSTO":
      return 210;
    case "EXPRESSES":
      return 190;
    case "NEARTO":
      return 180;
    default:
      return 185;
  }
}

export function linkStrength(link: SimLink): number {
  switch (link.kind) {
    case "CONTAINS":
      return 0.35;
    case "LEADSTO":
      return 0.28;
    case "EXPRESSES":
      return 0.18;
    case "NEARTO":
      return 0.14;
    default:
      return 0.22;
  }
}

/** Was 0.72 (very sticky). ~0.28 keeps glide; above d3 default 0.4 would stiffen again. */
export const VELOCITY_DECAY = 0.28;
export const ALPHA_MIN = 0.0008;
/** Slower cool-down so the pond keeps rippling. */
export const ALPHA_DECAY = 0.016;
export const REHEAT_ALPHA = 0.22;
/** Soft collide — resolve overlaps without packing hard. */
export const COLLIDE_STRENGTH = 0.32;
