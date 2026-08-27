import { useMemo } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  MarkerType,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { Handle, Position } from "@xyflow/react";
import {
  EdgeLabelRenderer,
  useInternalNode,
  type EdgeProps,
} from "@xyflow/react";
import { getEdgeParams } from "../../primitives/edge/floatingEdgeUtils";
import {
  containsGeometry,
  expressesGeometry,
  leadstoGeometry,
  neartoGeometry,
} from "../../primitives/edge/edgeGeometry";
import type { EdgeKind } from "../../primitives/edge/types";
import "./EdgeLabPage.css";

const SIZE = 88;

function LabNode({ data }: { data: { label: string } }) {
  return (
    <div className="edge-lab-node" style={{ width: SIZE, height: SIZE }}>
      <Handle
        type="target"
        position={Position.Left}
        id="t"
        style={centerHandle}
      />
      <div className="edge-lab-node__face">
        <span>{data.label}</span>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        id="s"
        style={centerHandle}
      />
    </div>
  );
}

const centerHandle = {
  position: "absolute" as const,
  top: "50%",
  left: "50%",
  transform: "translate(-50%, -50%)",
  width: 1,
  height: 1,
  opacity: 0,
  pointerEvents: "none" as const,
  border: "none",
};

type LabEdgeData = { kind: EdgeKind };

function LabEdge({
  id,
  source,
  target,
  data,
  markerEnd,
}: EdgeProps<Edge<LabEdgeData>>) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  if (!sourceNode || !targetNode) return null;

  const kind = data?.kind ?? "NEARTO";
  const { sx, sy, tx, ty } = getEdgeParams(sourceNode, targetNode);
  const labelX = (sx + tx) / 2;
  const labelY = (sy + ty) / 2;

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
    <g>
      <path
        id={id}
        d={linePath}
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.5}
        strokeDasharray={dash}
        strokeLinecap={dash ? "round" : undefined}
        markerEnd={kind === "LEADSTO" ? markerEnd : undefined}
      />
      {parenPath && (
        <path
          d={parenPath}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={1.5}
          strokeLinecap="square"
        />
      )}
      <EdgeLabelRenderer>
        <span
          className="edge-lab__label"
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

function row(
  kind: EdgeKind,
  y: number,
): { nodes: Node[]; edges: Edge<LabEdgeData>[] } {
  const parent = `${kind}-parent`;
  const child = `${kind}-child`;
  return {
    nodes: [
      {
        id: parent,
        type: "lab",
        position: { x: 80, y },
        data: { label: "parent" },
        style: { pointerEvents: "none" },
      },
      {
        id: child,
        type: "lab",
        position: { x: 420, y },
        data: { label: "child" },
        style: { pointerEvents: "none" },
      },
    ],
    edges: [
      {
        id: `${kind}-edge`,
        type: "labEdge",
        source: parent,
        target: child,
        sourceHandle: "s",
        targetHandle: "t",
        data: { kind },
        markerEnd:
          kind === "LEADSTO"
            ? {
                type: MarkerType.ArrowClosed,
                width: 14,
                height: 14,
                color: "#1c1c1c",
              }
            : undefined,
      },
    ],
  };
}

function EdgeLabInner() {
  const { nodes, edges } = useMemo(() => {
    const kinds: EdgeKind[] = ["CONTAINS", "LEADSTO", "EXPRESSES", "NEARTO"];
    const nodesAcc: Node[] = [];
    const edgesAcc: Edge<LabEdgeData>[] = [];
    kinds.forEach((k, i) => {
      const r = row(k, 40 + i * 160);
      nodesAcc.push(...r.nodes);
      edgesAcc.push(...r.edges);
    });
    return { nodes: nodesAcc, edges: edgesAcc };
  }, []);

  const nodeTypes: NodeTypes = useMemo(() => ({ lab: LabNode }), []);
  const edgeTypes: EdgeTypes = useMemo(() => ({ labEdge: LabEdge }), []);

  return (
    <div className="edge-lab">
      <header className="edge-lab__chrome">
        <p className="edge-lab__eyebrow">Design lab</p>
        <h1 className="edge-lab__title">Typed edge forms</h1>
        <p className="edge-lab__lede">
          CONTAINS target form:{" "}
          <code>parent --------( child</code> — solid, no arrow. Iterate
          geometry in <code>edgeGeometry.ts</code>.
        </p>
        <p className="edge-lab__nav">
          <a href="#/explorations/trial">← Trial</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/orbiters">Orbiters</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/connect">Connect</a>
        </p>
      </header>
      <div className="edge-lab__canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable
          panOnDrag
          zoomOnScroll
          proOptions={{ hideAttribution: true }}
        />
      </div>
    </div>
  );
}

export function EdgeLabPage() {
  return (
    <ReactFlowProvider>
      <EdgeLabInner />
    </ReactFlowProvider>
  );
}
