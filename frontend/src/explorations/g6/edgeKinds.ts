import type { EdgeData } from "@antv/g6";

export type EdgeKind = "leadsto" | "expresses" | "nearto";

/**
 * Round line-cap + zero-length dash → dots (not dashes).
 * Wider gap = sparser beads.
 */
export const DOTTED_STROKE: [number, number] = [0, 6.5];

export const KIND_LABEL: Record<EdgeKind, string> = {
  leadsto: "LEADSTO — arrow",
  expresses: "EXPRESSES — dotted",
  nearto: "NEARTO — plain",
};

export const KIND_STROKE: Record<EdgeKind, string> = {
  leadsto: "#111",
  expresses: "#111",
  nearto: "#888",
};

export const KIND_CYCLE: EdgeKind[] = ["leadsto", "expresses", "nearto"];

export function edgeStyleForKind(kind: EdgeKind) {
  return {
    stroke: KIND_STROKE[kind],
    lineWidth: kind === "leadsto" ? 1.75 : 1.4,
    endArrow: kind === "leadsto",
    endArrowType: "triangle" as const,
    endArrowSize: 8,
    lineDash: kind === "expresses" ? DOTTED_STROKE : undefined,
    lineCap: "round" as const,
  };
}

export function edgeStyleMapper(d: EdgeData) {
  const kind = (d.data?.kind as EdgeKind) ?? "nearto";
  return edgeStyleForKind(kind);
}
