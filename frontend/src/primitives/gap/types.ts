import type { ComponentType } from "react";
import type { Node, NodeProps } from "@xyflow/react";

export type GapKind = "intended" | "oversight";

export type GapNodeData = {
  kind: GapKind;
};

/** Any gap placed on a React Flow canvas. */
export type GapFlowNode = Node<GapNodeData>;

/** Canonical scene gap node types. */
export type GapNode = Node<GapNodeData, "gapIntended" | "gapOversight">;

export type GapVariationMeta = {
  id: string;
  thesis: string;
  note: string;
};

export type GapVariation = GapVariationMeta & {
  Intended: ComponentType<NodeProps<GapFlowNode>>;
  Oversight: ComponentType<NodeProps<GapFlowNode>>;
};
