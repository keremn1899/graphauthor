import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  ViewportPortal,
  useEdgesState,
  useInternalNode,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeTypes,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  getConnectionLineParams,
  getEdgeParams,
} from "../../../primitives/edge/floatingEdgeUtils";
import {
  FLOW_DISC_SIZE,
  FlowDiscNode,
  type FlowDiscNode as FlowDiscNodeType,
} from "./FlowDiscNode";
import { FlowStraightEdge } from "./FlowStraightEdge";
import "./FlowStage.css";

type Point = { x: number; y: number };

const nodeTypes: NodeTypes = { disc: FlowDiscNode };
const edgeTypes: EdgeTypes = { straight: FlowStraightEdge };

const INITIAL_NODES: FlowDiscNodeType[] = [
  {
    id: "a",
    type: "disc",
    position: { x: 120, y: 180 },
    data: { label: "Source A", role: "idle" },
  },
  {
    id: "b",
    type: "disc",
    position: { x: 420, y: 100 },
    data: { label: "Target B", role: "idle" },
  },
  {
    id: "c",
    type: "disc",
    position: { x: 420, y: 280 },
    data: { label: "Target C", role: "idle" },
  },
];

function nodeCenter(n: FlowDiscNodeType): Point {
  return {
    x: n.position.x + FLOW_DISC_SIZE / 2,
    y: n.position.y + FLOW_DISC_SIZE / 2,
  };
}

function hitNode(
  nodes: FlowDiscNodeType[],
  flow: Point,
  exclude?: string,
): FlowDiscNodeType | null {
  const r = FLOW_DISC_SIZE / 2 + 4;
  for (const n of nodes) {
    if (n.id === exclude) continue;
    const c = nodeCenter(n);
    if (Math.hypot(flow.x - c.x, flow.y - c.y) <= r) return n;
  }
  return null;
}

function ReachLine({
  sourceId,
  cursor,
  hoverTargetId,
}: {
  sourceId: string;
  cursor: Point;
  hoverTargetId: string | null;
}) {
  const source = useInternalNode(sourceId);
  const target = useInternalNode(hoverTargetId ?? "__none__");

  if (!source) return null;

  let sx: number;
  let sy: number;
  let tx: number;
  let ty: number;

  if (hoverTargetId && target) {
    ({ sx, sy, tx, ty } = getEdgeParams(source, target));
  } else {
    ({ sx, sy, tx, ty } = getConnectionLineParams(source, cursor.x, cursor.y));
  }

  return (
    <svg
      width={1}
      height={1}
      style={{ overflow: "visible", pointerEvents: "none" }}
    >
      <path
        d={`M ${sx},${sy} L ${tx},${ty}`}
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.75}
        strokeLinecap="square"
      />
    </svg>
  );
}

type FlowStageInnerProps = {
  onLog: (msg: string) => void;
};

function FlowStageInner({ onLog }: FlowStageInnerProps) {
  const { screenToFlowPosition } = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<Point | null>(null);
  const [hoverTargetId, setHoverTargetId] = useState<string | null>(null);

  const reaching = sourceId != null;

  const applyRoles = useCallback(
    (src: string | null, hover: string | null) => {
      setNodes((list) =>
        list.map((n) => {
          let role: "idle" | "source" | "target" = "idle";
          if (src && n.id === src) role = "source";
          else if (hover && n.id === hover) role = "target";
          if (n.data.role === role) return n;
          return { ...n, data: { ...n.data, role } };
        }),
      );
    },
    [setNodes],
  );

  const disengage = useCallback(() => {
    setSourceId(null);
    setCursor(null);
    setHoverTargetId(null);
    applyRoles(null, null);
    onLog("Disengaged.");
  }, [applyRoles, onLog]);

  const beginReach = useCallback(
    (nodeId: string, clientX: number, clientY: number) => {
      const flow = screenToFlowPosition({ x: clientX, y: clientY });
      setSourceId(nodeId);
      setCursor(flow);
      setHoverTargetId(null);
      applyRoles(nodeId, null);
      onLog(
        `Reaching from ${nodeId} — left-click a disc to connect, empty to cancel.`,
      );
    },
    [applyRoles, onLog, screenToFlowPosition],
  );

  const landOn = useCallback(
    (targetId: string) => {
      if (!sourceId || sourceId === targetId) return;
      const id = `e-${sourceId}-${targetId}-${Date.now().toString(36)}`;
      setEdges((eds) => [
        ...eds,
        {
          id,
          source: sourceId,
          target: targetId,
          sourceHandle: `central-source-${sourceId}`,
          targetHandle: `central-target-${targetId}`,
          type: "straight",
        },
      ]);
      setSourceId(null);
      setCursor(null);
      setHoverTargetId(null);
      applyRoles(null, null);
      onLog(`Connected ${sourceId} → ${targetId}.`);
    },
    [applyRoles, onLog, setEdges, sourceId],
  );

  const onNodeContextMenu = useCallback(
    (e: React.MouseEvent, node: FlowDiscNodeType) => {
      e.preventDefault();
      beginReach(node.id, e.clientX, e.clientY);
    },
    [beginReach],
  );

  const onNodeClick = useCallback(
    (e: React.MouseEvent, node: FlowDiscNodeType) => {
      if (!reaching) return;
      e.stopPropagation();
      if (node.id === sourceId) {
        disengage();
        return;
      }
      landOn(node.id);
    },
    [disengage, landOn, reaching, sourceId],
  );

  const onPaneClick = useCallback(() => {
    if (reaching) disengage();
  }, [disengage, reaching]);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!reaching || !sourceId) return;
      const flow = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      setCursor(flow);
      const hit = hitNode(nodes as FlowDiscNodeType[], flow, sourceId);
      const nextHover = hit?.id ?? null;
      setHoverTargetId(nextHover);
      applyRoles(sourceId, nextHover);
    },
    [applyRoles, nodes, reaching, screenToFlowPosition, sourceId],
  );

  const defaultViewport = useMemo(() => ({ x: 40, y: 20, zoom: 1 }), []);

  return (
    <div
      className={`flow-stage${reaching ? " flow-stage--reaching" : ""}`}
      onPointerMove={onPointerMove}
      onContextMenu={(e) => e.preventDefault()}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeContextMenu={onNodeContextMenu}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodesDraggable={!reaching}
        nodesConnectable={false}
        elementsSelectable={!reaching}
        panOnDrag={!reaching}
        zoomOnScroll
        zoomOnPinch
        fitView={false}
        defaultViewport={defaultViewport}
        proOptions={{ hideAttribution: true }}
        minZoom={0.4}
        maxZoom={2}
      >
        {reaching && sourceId && cursor && (
          <ViewportPortal>
            <div
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                width: 1,
                height: 1,
                overflow: "visible",
                pointerEvents: "none",
              }}
            >
              <ReachLine
                sourceId={sourceId}
                cursor={cursor}
                hoverTargetId={hoverTargetId}
              />
            </div>
          </ViewportPortal>
        )}
      </ReactFlow>
      <p className="flow-stage__hint">
        Right-click a disc to start — straight line follows the cursor.
        Left-click another disc to connect (no land animation). Click empty to
        cancel. Nodes are draggable when idle.
      </p>
    </div>
  );
}

type FlowStageProps = {
  onLog: (msg: string) => void;
};

export function FlowStage({ onLog }: FlowStageProps) {
  return (
    <ReactFlowProvider>
      <FlowStageInner onLog={onLog} />
    </ReactFlowProvider>
  );
}
