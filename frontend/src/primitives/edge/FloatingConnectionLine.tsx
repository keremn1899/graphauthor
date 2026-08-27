import {
  useInternalNode,
  type ConnectionLineComponentProps,
} from "@xyflow/react";
import { getConnectionLineParams } from "./floatingEdgeUtils";

/** Connection preview that starts on the source circumference. */
export function FloatingConnectionLine({
  fromNode,
  toX,
  toY,
  connectionLineStyle,
}: ConnectionLineComponentProps) {
  const sourceNode = useInternalNode(fromNode?.id);

  if (!sourceNode) {
    return null;
  }

  const { sx, sy, tx, ty } = getConnectionLineParams(sourceNode, toX, toY);

  return (
    <g>
      <path
        d={`M ${sx},${sy} L ${tx},${ty}`}
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.25}
        style={connectionLineStyle}
      />
    </g>
  );
}
