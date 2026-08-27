import {
  BaseEdge,
  useInternalNode,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";
import { getEdgeParams } from "../../../primitives/edge/floatingEdgeUtils";

/** Straight floating rim↔rim edge — no animation. */
export function FlowStraightEdge({
  id,
  source,
  target,
  style,
}: EdgeProps<Edge>) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  if (!sourceNode || !targetNode) return null;

  const { sx, sy, tx, ty } = getEdgeParams(sourceNode, targetNode);
  return (
    <BaseEdge
      id={id}
      path={`M ${sx},${sy} L ${tx},${ty}`}
      style={{
        stroke: "var(--ink)",
        strokeWidth: 1.75,
        strokeLinecap: "square",
        ...style,
      }}
    />
  );
}
