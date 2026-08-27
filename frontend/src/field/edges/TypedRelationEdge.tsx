import {
  useInternalNode,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";
import { getEdgeParams } from "../../primitives/edge/floatingEdgeUtils";
import {
  containsGeometry,
  leadstoGeometry,
  neartoGeometry,
} from "../../primitives/edge/edgeGeometry";
import type { EdgeKind } from "../../shared/edges/types";
import type { FieldEdgeData } from "../data/fieldGraph";
import { useFieldUi } from "../state/FieldUiContext";
import "./TypedRelationEdge.css";

export type TypedRelationFlowEdge = Edge<FieldEdgeData, "typed">;
export type TypedRelationEdgeProps = EdgeProps<TypedRelationFlowEdge>;

/**
 * Four typed edges — geometric.
 * EXPRESSES: thinner/lighter directed (not dotted).
 * NEARTO: undirected plain.
 */
export function TypedRelationEdge({
  id,
  source,
  target,
  data,
  markerEnd,
  style,
  selected,
}: TypedRelationEdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const { focusedEdgeId } = useFieldUi();

  if (!sourceNode || !targetNode) return null;

  const kind: EdgeKind = data?.kind ?? "NEARTO";
  const weight = data?.weight ?? 1;
  const { sx, sy, tx, ty } = getEdgeParams(sourceNode, targetNode);
  const tw = targetNode.measured?.width ?? targetNode.width ?? 88;
  const th = targetNode.measured?.height ?? targetNode.height ?? 88;
  const abs = targetNode.internals.positionAbsolute;
  const targetCenter = {
    x: abs.x + tw / 2,
    y: abs.y + th / 2,
  };
  const targetRadius = Math.min(tw, th) / 2;

  let linePath = `M ${sx},${sy} L ${tx},${ty}`;
  let parenPath: string | undefined;

  if (kind === "CONTAINS") {
    const g = containsGeometry({
      sx,
      sy,
      tx,
      ty,
      targetRadius,
      targetCenter,
    });
    linePath = g.linePath;
    parenPath = g.parenPath;
  } else if (kind === "LEADSTO") {
    linePath = leadstoGeometry({ sx, sy, tx, ty }).linePath;
  } else if (kind === "EXPRESSES") {
    linePath = `M ${sx},${sy} L ${tx},${ty}`;
  } else {
    linePath = neartoGeometry({ sx, sy, tx, ty }).linePath;
  }

  const strokeWidth =
    kind === "EXPRESSES" ? 1.15 * weight : 1.75 * Math.min(weight, 2.5);
  const opacity = kind === "EXPRESSES" ? 0.72 : 1;
  const showLabel =
    !!data?.label && (selected || focusedEdgeId === id);

  return (
    <g className="typed-relation">
      <path d={linePath} fill="none" stroke="transparent" strokeWidth={18} />
      <path
        id={id}
        d={linePath}
        fill="none"
        markerEnd={
          kind === "LEADSTO" || kind === "EXPRESSES" ? markerEnd : undefined
        }
        className="typed-relation__stroke"
        style={{
          ...style,
          strokeWidth,
          opacity,
        }}
        strokeLinecap={kind === "CONTAINS" ? "butt" : "square"}
      />
      {parenPath && (
        <path
          d={parenPath}
          fill="none"
          className="typed-relation__stroke typed-relation__paren"
          strokeLinecap="butt"
          style={{ strokeWidth }}
        />
      )}
      {showLabel && (
        <text className="typed-relation__label">
          <textPath href={`#${id}`} startOffset="50%" textAnchor="middle">
            {data?.label}
          </textPath>
        </text>
      )}
    </g>
  );
}
