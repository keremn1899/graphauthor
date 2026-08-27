import {
  EdgeLabelRenderer,
  useInternalNode,
} from "@xyflow/react";
import { getEdgeParams } from "./floatingEdgeUtils";
import type { RelationEdgeProps } from "./types";
import "./RelationEdge.css";

/**
 * Floating straight edge — attaches on the circle circumference, not box sides.
 * Flat stroke only (no decorative gradient).
 */
export function RelationEdge({
  id,
  source,
  target,
  data,
  markerEnd,
  style,
}: RelationEdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);

  if (!sourceNode || !targetNode) {
    return null;
  }

  const { sx, sy, tx, ty } = getEdgeParams(sourceNode, targetNode);
  const path = `M ${sx},${sy} L ${tx},${ty}`;
  const labelX = (sx + tx) / 2;
  const labelY = (sy + ty) / 2;
  const kind = data?.kind ?? "LEADSTO";

  return (
    <g>
      {/* Wider invisible hit path */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        className="relation-edge__hit"
      />
      <path
        id={id}
        d={path}
        fill="none"
        markerEnd={markerEnd}
        className="relation-edge"
        style={style}
      />
      <EdgeLabelRenderer>
        <span
          className="relation-edge__label"
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY + 14}px)`,
          }}
        >
          {kind}
        </span>
      </EdgeLabelRenderer>
    </g>
  );
}
