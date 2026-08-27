import type { EdgeKind } from "../../../primitives/edge/types";

export type InitMode = "on-node" | "near-node";
export type TypeTiming = "after-land" | "before-drag";

export type GesturePhase =
  | "idle"
  | "reaching"
  | "dragging"
  | "hover-valid"
  | "landed"
  | "picking-type";

export type ConnectNodeId = "source" | "target" | "decoy";

export const EDGE_KINDS: EdgeKind[] = [
  "LEADSTO",
  "CONTAINS",
  "EXPRESSES",
  "NEARTO",
];

export const LONG_PRESS_MS = 420;
