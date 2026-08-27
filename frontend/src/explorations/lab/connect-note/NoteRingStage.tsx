import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  ConnectionMode,
  ConnectionLineType,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeTypes,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { FloatingConnectionLine } from "../../../primitives/edge/FloatingConnectionLine";
import { FlowStraightEdge } from "../connect-flow/FlowStraightEdge";
import {
  NoteRingNode,
  type NoteRingFlowNode,
} from "./NoteRingNode";
import "./NoteRingStage.css";

const nodeTypes: NodeTypes = { noteRing: NoteRingNode };
const edgeTypes: EdgeTypes = { straight: FlowStraightEdge };

const INITIAL_NODES: NoteRingFlowNode[] = [
  {
    id: "a",
    type: "noteRing",
    position: { x: 120, y: 180 },
    data: { label: "Source A" },
  },
  {
    id: "b",
    type: "noteRing",
    position: { x: 420, y: 100 },
    data: { label: "Target B" },
  },
  {
    id: "c",
    type: "noteRing",
    position: { x: 420, y: 280 },
    data: { label: "Target C" },
  },
];

type NoteRingStageInnerProps = {
  onLog: (msg: string) => void;
};

function NoteRingStageInner({ onLog }: NoteRingStageInnerProps) {
  const [nodes, , onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const connectionSourceIdRef = useRef<string | null>(null);
  const defaultViewport = useMemo(() => ({ x: 40, y: 20, zoom: 1 }), []);

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            id: `e-${params.source}-${params.target}-${Date.now().toString(36)}`,
            type: "straight",
            animated: false,
          },
          eds,
        ),
      );
      onLog(`Connected ${params.source} → ${params.target}.`);
    },
    [onLog, setEdges],
  );

  const onConnectStart = useCallback(
    (_: unknown, params: { nodeId: string | null }) => {
      connectionSourceIdRef.current = params.nodeId;
      onLog(`Connecting from ${params.nodeId}…`);
    },
    [onLog],
  );

  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent) => {
      if (!event) {
        connectionSourceIdRef.current = null;
        return;
      }

      let target: Element | null = null;
      if ("changedTouches" in event && event.changedTouches[0]) {
        const t = event.changedTouches[0];
        target = document.elementFromPoint(t.clientX, t.clientY);
      } else if ("clientX" in event) {
        target = event.target as Element;
      }

      const nodeElement = target?.closest("[data-node-id]");
      const targetNodeId = nodeElement?.getAttribute("data-node-id");
      const sourceNodeId = connectionSourceIdRef.current;

      if (
        targetNodeId &&
        sourceNodeId &&
        targetNodeId !== sourceNodeId
      ) {
        setEdges((eds) => {
          const exists = eds.some(
            (e) => e.source === sourceNodeId && e.target === targetNodeId,
          );
          if (exists) return eds;
          return addEdge(
            {
              id: `e-${sourceNodeId}-${targetNodeId}-${Date.now().toString(36)}`,
              source: sourceNodeId,
              target: targetNodeId,
              sourceHandle: `central-source-${sourceNodeId}`,
              targetHandle: `central-target-${targetNodeId}`,
              type: "straight",
              animated: false,
            },
            eds,
          );
        });
        onLog(`Connected ${sourceNodeId} → ${targetNodeId}.`);
      } else if (!targetNodeId) {
        onLog("Miss — connection cancelled.");
      }

      connectionSourceIdRef.current = null;
    },
    [onLog, setEdges],
  );

  // Touch: highlight node under finger while connecting (Note Prototype)
  useEffect(() => {
    let lastTarget: Element | null = null;

    const handleTouchMove = (e: TouchEvent) => {
      if (!connectionSourceIdRef.current) return;
      const touch = e.touches[0];
      if (!touch) return;
      const el = document.elementFromPoint(touch.clientX, touch.clientY);
      const nodeWrapper = el?.closest("[data-node-id]") ?? null;
      if (nodeWrapper === lastTarget) return;
      if (lastTarget) lastTarget.classList.remove("touch-target");
      if (nodeWrapper) {
        const targetId = nodeWrapper.getAttribute("data-node-id");
        if (targetId !== connectionSourceIdRef.current) {
          nodeWrapper.classList.add("touch-target");
          lastTarget = nodeWrapper;
        } else {
          lastTarget = null;
        }
      } else {
        lastTarget = null;
      }
    };

    const handleTouchEnd = () => {
      if (lastTarget) {
        lastTarget.classList.remove("touch-target");
        lastTarget = null;
      }
    };

    window.addEventListener("touchmove", handleTouchMove, { passive: true });
    window.addEventListener("touchend", handleTouchEnd);
    return () => {
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("touchend", handleTouchEnd);
    };
  }, []);

  return (
    <div className="note-ring-stage" onContextMenu={(e) => e.preventDefault()}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onConnectStart={onConnectStart}
        onConnectEnd={onConnectEnd}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        connectionMode={ConnectionMode.Loose}
        connectionLineType={ConnectionLineType.Straight}
        connectionLineComponent={FloatingConnectionLine}
        connectionLineStyle={{ stroke: "var(--ink)", strokeWidth: 1.75 }}
        defaultEdgeOptions={{ type: "straight", animated: false }}
        nodesConnectable
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        fitView={false}
        defaultViewport={defaultViewport}
        proOptions={{ hideAttribution: true }}
        minZoom={0.4}
        maxZoom={2}
        nodeOrigin={[0, 0]}
      />
      <p className="note-ring-stage__hint">
        Note Prototype connect on React Flow: right-click or long-press →
        dotted ring → drag from the annulus. Drop on another node. No land
        animation — firm floating edge.
      </p>
    </div>
  );
}

type NoteRingStageProps = {
  onLog: (msg: string) => void;
};

export function NoteRingStage({ onLog }: NoteRingStageProps) {
  return (
    <ReactFlowProvider>
      <NoteRingStageInner onLog={onLog} />
    </ReactFlowProvider>
  );
}
