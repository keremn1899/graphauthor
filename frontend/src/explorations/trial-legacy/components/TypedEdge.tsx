import {
  useInternalNode,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";
import { getEdgeParams } from "../../../primitives/edge/floatingEdgeUtils";
import {
  containsGeometry,
  expressesGeometry,
  leadstoGeometry,
  neartoGeometry,
} from "../../../primitives/edge/edgeGeometry";
import type { EdgeKind } from "../../../primitives/edge/types";
import type { TrialEdgeData } from "../data/trialGraph";
import { useTrialUi } from "../TrialUiContext";
import "./TypedEdge.css";

export type TypedFlowEdge = Edge<TrialEdgeData, "typed">;
export type TypedEdgeProps = EdgeProps<TypedFlowEdge>;

/**
 * Four SST bridges — light relation strokes.
 * CONTAINS: parent --------( child (undashed, no arrow).
 * LEADSTO: arrow. EXPRESSES: dash. NEARTO: plain.
 */
export function TypedEdge({
  id,
  source,
  target,
  data,
  markerEnd,
  style,
}: TypedEdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  const { lens } = useTrialUi();

  if (!sourceNode || !targetNode) return null;

  const kind: EdgeKind = data?.kind ?? "NEARTO";
  if (kind !== lens) return null;

  const { sx, sy, tx, ty } = getEdgeParams(sourceNode, targetNode);
  let linePath = `M ${sx},${sy} L ${tx},${ty}`;
  let parenPath: string | undefined;
  let dash: string | undefined;

  if (kind === "CONTAINS") {
    const g = containsGeometry({ sx, sy, tx, ty });
    linePath = g.linePath;
    parenPath = g.parenPath;
  } else if (kind === "LEADSTO") {
    linePath = leadstoGeometry({ sx, sy, tx, ty }).linePath;
  } else if (kind === "EXPRESSES") {
    const g = expressesGeometry({ sx, sy, tx, ty });
    linePath = g.linePath;
    dash = g.dash;
  } else {
    linePath = neartoGeometry({ sx, sy, tx, ty }).linePath;
  }

  return (
    <g className="typed-edge">
      <path d={linePath} fill="none" stroke="transparent" strokeWidth={18} />
      <path
        id={id}
        d={linePath}
        fill="none"
        markerEnd={kind === "LEADSTO" ? markerEnd : undefined}
        strokeDasharray={dash}
        className="typed-edge__stroke"
        style={style}
        strokeLinecap={dash ? "round" : undefined}
      />
      {parenPath && (
        <path
          d={parenPath}
          fill="none"
          className="typed-edge__stroke typed-edge__paren"
          strokeLinecap="square"
        />
      )}
    </g>
  );
}
