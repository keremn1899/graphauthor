import type { EdgeData } from "@antv/g6";
import { CONTAINS_EDGE } from "./containsEdge";

export type LensVisualEdgeKind =
  | "contains"
  | "leadsto"
  | "expresses"
  | "nearto";

function baseStyleForKind(kind: LensVisualEdgeKind) {
  switch (kind) {
    case "contains":
      return {
        stroke: "#111",
        lineWidth: 1.6,
        endArrow: true,
        endArrowType: "triangle" as const,
        endArrowSize: 8.5,
        lineDash: undefined as number[] | undefined,
      };
    case "leadsto":
      return {
        stroke: "#111",
        lineWidth: 1.75,
        endArrow: true,
        endArrowType: "triangle" as const,
        endArrowSize: 8,
        lineDash: undefined as number[] | undefined,
      };
    case "expresses":
      return {
        stroke: "#111",
        lineWidth: 1.35,
        endArrow: true,
        endArrowType: "triangle" as const,
        endArrowSize: 7,
        lineDash: undefined as number[] | undefined,
      };
    case "nearto":
    default:
      return {
        stroke: "#111",
        lineWidth: 1.25,
        endArrow: false,
        endArrowType: "triangle" as const,
        endArrowSize: 8,
        lineDash: undefined as number[] | undefined,
      };
  }
}

export function lensVisualKindOf(datum: EdgeData): LensVisualEdgeKind {
  const kind = String(datum.data?.kind ?? "").toLowerCase();
  if (
    kind === "contains" ||
    kind === "leadsto" ||
    kind === "expresses" ||
    kind === "nearto"
  ) {
    return kind;
  }

  const label = String(datum.data?.label ?? "").toUpperCase();
  if (label === "CONTAINS") return "contains";
  if (label === "EXPRESSES") return "expresses";
  if (label === "NEARTO" || label === "NEAR TO") return "nearto";

  // Governance relations such as OWNS, GOVERNS, CONSTRAINS, AUTHORIZES,
  // REQUIRES and BOUNDS are directional.
  return "leadsto";
}

export const LENS_EDGE_STYLE = {
  stroke: (datum: EdgeData) => baseStyleForKind(lensVisualKindOf(datum)).stroke,
  lineWidth: (datum: EdgeData) =>
    baseStyleForKind(lensVisualKindOf(datum)).lineWidth,
  endArrow: (datum: EdgeData) =>
    baseStyleForKind(lensVisualKindOf(datum)).endArrow,
  endArrowType: (datum: EdgeData) =>
    baseStyleForKind(lensVisualKindOf(datum)).endArrowType,
  endArrowSize: (datum: EdgeData) =>
    baseStyleForKind(lensVisualKindOf(datum)).endArrowSize,
  lineDash: (datum: EdgeData) =>
    baseStyleForKind(lensVisualKindOf(datum)).lineDash,
  lineCap: () => "round" as const,
  lineJoin: () => "round" as const,
};

export const LENS_EDGE_TYPE = (datum: EdgeData) =>
  lensVisualKindOf(datum) === "contains" ? CONTAINS_EDGE : "line";
