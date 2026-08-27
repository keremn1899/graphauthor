import type { Edge, EdgeProps } from "@xyflow/react";

/** SST edge kinds — only LEADSTO rendered distinctly in this basic scene. */
export type EdgeKind = "CONTAINS" | "LEADSTO" | "EXPRESSES" | "NEARTO";

export type RelationEdgeData = {
  kind: EdgeKind;
};

export type RelationEdgeType = Edge<RelationEdgeData, "relation">;

export type RelationEdgeProps = EdgeProps<RelationEdgeType>;
