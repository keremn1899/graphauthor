import type { EdgeKind } from "../../../primitives/edge/types";
import type { SimLink, SimNode } from "../data/trialGraph";
import { FIELD_RING_OUTER, MASS_NODE_RADIUS } from "../data/trialGraph";

/** Charge strength: settled masses push harder (occupy field); uncertain weaker. */
export function chargeStrength(d: SimNode): number {
  const c = d.certainty ?? 0.5;
  // Negative = repulsion. Stronger magnitude for high certainty.
  return -180 - c * 220;
}

export function collideRadius(d: SimNode): number {
  if (d.kind === "gap") return 48;
  return MASS_NODE_RADIUS + 28;
}

export function linkDistance(link: SimLink): number {
  switch (link.kind) {
    case "CONTAINS":
      return 140;
    case "LEADSTO":
      return 180;
    case "EXPRESSES":
      return 160;
    case "NEARTO":
      return 150;
    default:
      return 160;
  }
}

export function linkStrength(link: SimLink): number {
  switch (link.kind) {
    case "CONTAINS":
      return 0.85;
    case "LEADSTO":
      return 0.65;
    case "EXPRESSES":
      return 0.45;
    case "NEARTO":
      return 0.35;
    default:
      return 0.5;
  }
}

/** High decay → things settle to stillness (certainty = at rest). */
export const VELOCITY_DECAY = 0.72;
export const ALPHA_MIN = 0.001;
export const ALPHA_DECAY = 0.028;
export const REHEAT_ALPHA = 0.35;

export function linksForLens(all: SimLink[], lens: EdgeKind): SimLink[] {
  return all.filter((l) => l.kind === lens);
}

export const FIELD_PADDING = FIELD_RING_OUTER - MASS_NODE_RADIUS;
