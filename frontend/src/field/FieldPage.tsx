import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  MarkerType,
  ConnectionMode,
  ViewportPortal,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  type OnNodeDrag,
} from "@xyflow/react";
import { MotionConfig } from "motion/react";
import "@xyflow/react/dist/style.css";

import { useGraphController } from "../app/GraphController";
import { useReducedMotion } from "../shared/hooks/useReducedMotion";
import type { EdgeKind } from "../shared/edges/types";
import {
  CONCEPT_NODE_RADIUS,
  type FieldEdgeData,
  type SimLink,
  type SimNode,
} from "./data/fieldGraph";
import { ConceptNode } from "./nodes/ConceptNode";
import { TypedRelationEdge } from "./edges/TypedRelationEdge";
import { FieldUiProvider, useFieldUi } from "./state/FieldUiContext";
import { useForceLayout } from "./physics/useForceLayout";
import { ReachTether } from "./gestures/ReachTether";
import { TypePicker } from "./gestures/TypePicker";
import "./FieldPage.css";

const LONG_PRESS_MS = 420;
const HIT_PAD = 28;

function simToFlowNodes(
  sim: SimNode[],
  highlightId: string | null,
): Node[] {
  return sim.map((n) => ({
    id: n.id,
    type: "concept",
    position: {
      x: n.x - CONCEPT_NODE_RADIUS,
      y: n.y - CONCEPT_NODE_RADIUS,
    },
    data: n.concept,
    draggable: true,
    className: highlightId === n.id ? "concept-node-highlighted" : undefined,
  }));
}

function simToFlowEdges(links: SimLink[]): Edge<FieldEdgeData>[] {
  return links.map((l) => {
    const source = typeof l.source === "string" ? l.source : l.source.id;
    const target = typeof l.target === "string" ? l.target : l.target.id;
    const directed = l.kind === "LEADSTO" || l.kind === "EXPRESSES";
    return {
      id: l.id,
      type: "typed",
      source,
      target,
      sourceHandle: `central-source-${source}`,
      targetHandle: `central-target-${target}`,
      data: { kind: l.kind, weight: l.weight, label: l.label },
      markerEnd: directed
        ? {
            type: MarkerType.ArrowClosed,
            width: l.kind === "EXPRESSES" ? 10 : 12,
            height: l.kind === "EXPRESSES" ? 10 : 12,
            color: "#1c1c1c",
          }
        : undefined,
    };
  });
}

type ReachState = {
  sourceId: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  hoverTargetId: string | null;
};

function FieldCanvas() {
  const {
    simNodes,
    setSimNodes,
    simLinks,
    setSimLinks,
    flyToId,
    clearFlyTo,
    applyWrite,
  } = useGraphController();

  const {
    reducedMotion,
    setSelectedId,
    setPendingConnect,
    pendingConnect,
    setProvisionalPreviewId,
    highlightId,
    setHighlightId,
  } = useFieldUi();

  const { screenToFlowPosition, flowToScreenPosition, setCenter, getZoom } =
    useReactFlow();
  const draggingId = useRef<string | null>(null);
  const pressTimer = useRef<number | null>(null);
  const pressOrigin = useRef<{
    id: string;
    clientX: number;
    clientY: number;
  } | null>(null);
  const lastPaneTap = useRef<{ t: number; x: number; y: number } | null>(
    null,
  );
  const reachRef = useRef<ReachState | null>(null);

  const [reach, setReach] = useState<ReachState | null>(null);
  reachRef.current = reach;

  const [pickerFlow, setPickerFlow] = useState<{
    x: number;
    y: number;
  } | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState(
    simToFlowNodes(simNodes, null),
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    simToFlowEdges(simLinks),
  );

  const onTick = useCallback(
    (next: SimNode[]) => {
      if (draggingId.current) return;
      // Never replace React's node set from the sim — only update positions.
      // Replacing wiped newborn nodes that were not yet in the force sim.
      setSimNodes((prev) => {
        const byId = new Map(next.map((n) => [n.id, n]));
        return prev.map((p) => {
          const n = byId.get(p.id);
          if (!n) return p;
          return {
            ...p,
            x: n.x,
            y: n.y,
            vx: n.vx,
            vy: n.vy,
            fx: n.fx,
            fy: n.fy,
          };
        });
      });
      setNodes((prev) => {
        const byId = new Map(next.map((n) => [n.id, n]));
        return prev.map((node) => {
          const n = byId.get(node.id);
          if (!n) return node;
          return {
            ...node,
            position: {
              x: n.x - CONCEPT_NODE_RADIUS,
              y: n.y - CONCEPT_NODE_RADIUS,
            },
          };
        });
      });
    },
    [setNodes, setSimNodes],
  );

  const physics = useForceLayout({
    nodes: simNodes,
    links: simLinks,
    onTick,
    reducedMotion,
  });

  const nodeIdsKey = simNodes.map((n) => n.id).join(",");
  const conceptSig = simNodes
    .map(
      (n) =>
        `${n.id}:${n.concept.lifecycle}:${n.concept.unread}:${n.concept.pulseToken ?? 0}:${n.concept.label}`,
    )
    .join("|");

  // Keep force sim + flow graph in lockstep: nodes first, then links
  useEffect(() => {
    physics.syncNodes(simNodes, { reheat: false });
    physics.syncLinks(simLinks);
    setNodes(simToFlowNodes(simNodes, highlightId));
    setEdges(simToFlowEdges(simLinks));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeIdsKey, simLinks, highlightId]);

  useEffect(() => {
    setNodes(simToFlowNodes(simNodes, highlightId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conceptSig, highlightId]);

  useEffect(() => {
    if (!flyToId) return;
    const n = simNodes.find((node) => node.id === flyToId);
    if (!n) return;
    setHighlightId(flyToId);
    setSelectedId(flyToId);
    setCenter(n.x, n.y, {
      zoom: Math.max(getZoom(), 1),
      duration: reducedMotion ? 0 : 450,
    });
    const t = window.setTimeout(() => clearFlyTo(), 80);
    return () => window.clearTimeout(t);
  }, [
    flyToId,
    simNodes,
    setCenter,
    getZoom,
    reducedMotion,
    clearFlyTo,
    setHighlightId,
    setSelectedId,
  ]);

  const fitOnce = useRef(false);
  useEffect(() => {
    if (fitOnce.current || simNodes.length === 0) return;
    const t = window.setTimeout(() => {
      const cx =
        simNodes.reduce((s, n) => s + n.x, 0) / simNodes.length;
      const cy =
        simNodes.reduce((s, n) => s + n.y, 0) / simNodes.length;
      setCenter(cx, cy, {
        zoom: 0.95,
        duration: reducedMotion ? 0 : 400,
      });
      fitOnce.current = true;
    }, reducedMotion ? 40 : 700);
    return () => window.clearTimeout(t);
  }, [setCenter, simNodes, reducedMotion]);

  const nodeTypes: NodeTypes = useMemo(() => ({ concept: ConceptNode }), []);
  const edgeTypes: EdgeTypes = useMemo(
    () => ({ typed: TypedRelationEdge }),
    [],
  );

  const clearPress = () => {
    if (pressTimer.current) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
  };

  const hitNode = useCallback(
    (flow: { x: number; y: number }, excludeId?: string) => {
      let best: SimNode | null = null;
      let bestD = CONCEPT_NODE_RADIUS + HIT_PAD;
      for (const n of simNodes) {
        if (n.id === excludeId) continue;
        const d = Math.hypot(n.x - flow.x, n.y - flow.y);
        if (d < bestD) {
          bestD = d;
          best = n;
        }
      }
      return best;
    },
    [simNodes],
  );

  const beginReach = useCallback(
    (sourceId: string) => {
      const src = simNodes.find((n) => n.id === sourceId);
      if (!src) return;
      setReach({
        sourceId,
        from: { x: src.x, y: src.y },
        to: { x: src.x + 96, y: src.y },
        hoverTargetId: null,
      });
      setSelectedId(sourceId);
      setPendingConnect(null);
      setProvisionalPreviewId(null);
      setPickerFlow(null);
    },
    [simNodes, setPendingConnect, setProvisionalPreviewId, setSelectedId],
  );

  const cancelConnect = useCallback(() => {
    setPendingConnect(null);
    setProvisionalPreviewId(null);
    setPickerFlow(null);
    setReach(null);
  }, [setPendingConnect, setProvisionalPreviewId]);

  const commitEdge = useCallback(
    (kind: EdgeKind) => {
      if (!pendingConnect) return;
      const { sourceId, targetId } = pendingConnect;
      const id = `e-${sourceId}-${targetId}-${Date.now().toString(36)}`;
      setSimLinks((list) => [
        ...list,
        { id, source: sourceId, target: targetId, kind },
      ]);
      cancelConnect();
    },
    [pendingConnect, setSimLinks, cancelConnect],
  );

  // Global move/up while reaching
  useEffect(() => {
    if (!reach) return;

    const onMove = (e: PointerEvent) => {
      const flow = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const hover = hitNode(flow, reach.sourceId);
      setReach((r) =>
        r
          ? { ...r, to: flow, hoverTargetId: hover?.id ?? null }
          : null,
      );
      setProvisionalPreviewId(hover?.id ?? null);
    };

    const onUp = (e: PointerEvent) => {
      const current = reachRef.current;
      if (!current) return;
      const flow = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const target = hitNode(flow, current.sourceId);
      if (!target) {
        cancelConnect();
        return;
      }
      setPendingConnect({
        sourceId: current.sourceId,
        targetId: target.id,
      });
      setProvisionalPreviewId(target.id);
      setPickerFlow({ x: target.x, y: target.y });
      setReach(null);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [
    reach,
    screenToFlowPosition,
    hitNode,
    setProvisionalPreviewId,
    setPendingConnect,
    cancelConnect,
  ]);

  const onNodeDragStart: OnNodeDrag = useCallback(
    (_e, node) => {
      if (reachRef.current) return;
      clearPress();
      draggingId.current = node.id;
      const cx = node.position.x + CONCEPT_NODE_RADIUS;
      const cy = node.position.y + CONCEPT_NODE_RADIUS;
      physics.dragFix(node.id, cx, cy);
    },
    [physics],
  );

  const onNodeDrag: OnNodeDrag = useCallback(
    (_e, node) => {
      if (reachRef.current) return;
      const cx = node.position.x + CONCEPT_NODE_RADIUS;
      const cy = node.position.y + CONCEPT_NODE_RADIUS;
      physics.dragFix(node.id, cx, cy);
      setSimNodes((list) =>
        list.map((n) =>
          n.id === node.id ? { ...n, x: cx, y: cy, fx: cx, fy: cy } : n,
        ),
      );
    },
    [physics, setSimNodes],
  );

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_e, node) => {
      draggingId.current = null;
      physics.dragEnd(node.id);
      setSimNodes((list) =>
        list.map((n) =>
          n.id === node.id ? { ...n, fx: null, fy: null } : n,
        ),
      );
    },
    [physics, setSimNodes],
  );

  const onNodeClick = useCallback(
    (_e: React.MouseEvent, node: Node) => {
      if (reachRef.current || pendingConnect) return;
      setSelectedId(node.id);
      setHighlightId(null);
    },
    [pendingConnect, setHighlightId, setSelectedId],
  );

  const onHostPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      if (pendingConnect) return;

      const nodeEl = (e.target as HTMLElement).closest(
        ".react-flow__node",
      ) as HTMLElement | null;
      const nodeId = nodeEl?.getAttribute("data-id");

      if (nodeId) {
        pressOrigin.current = {
          id: nodeId,
          clientX: e.clientX,
          clientY: e.clientY,
        };
        clearPress();
        pressTimer.current = window.setTimeout(() => {
          const meta = pressOrigin.current;
          if (!meta || meta.id !== nodeId) return;
          beginReach(nodeId);
        }, LONG_PRESS_MS);
        return;
      }

      // Long-press empty pane → create
      clearPress();
      pressTimer.current = window.setTimeout(() => {
        applyWrite({ label: "New concept" });
      }, LONG_PRESS_MS);
    },
    [applyWrite, beginReach, pendingConnect],
  );

  const onHostPointerMove = useCallback((e: React.PointerEvent) => {
    const origin = pressOrigin.current;
    if (!pressTimer.current || !origin) return;
    if (
      Math.hypot(e.clientX - origin.clientX, e.clientY - origin.clientY) > 10
    ) {
      clearPress();
    }
  }, []);

  const onHostPointerUp = useCallback(() => {
    clearPress();
    pressOrigin.current = null;
  }, []);

  const onPaneClick = useCallback(
    (e: React.MouseEvent) => {
      if (reachRef.current || pendingConnect) {
        cancelConnect();
        return;
      }
      const now = Date.now();
      const prev = lastPaneTap.current;
      if (
        prev &&
        now - prev.t < 320 &&
        Math.hypot(e.clientX - prev.x, e.clientY - prev.y) < 28
      ) {
        lastPaneTap.current = null;
        const flow = screenToFlowPosition({ x: e.clientX, y: e.clientY });
        applyWrite({ label: "New concept" });
        // nudge fly-to near click — applyWrite already fly-tos new node
        void flow;
        return;
      }
      lastPaneTap.current = { t: now, x: e.clientX, y: e.clientY };
      setSelectedId(null);
      setHighlightId(null);
    },
    [
      applyWrite,
      cancelConnect,
      pendingConnect,
      screenToFlowPosition,
      setHighlightId,
      setSelectedId,
    ],
  );

  const slack = reach?.hoverTargetId ? 0.15 : 0.85;

  let pickerScreen: { left: number; top: number } | null = null;
  if (pickerFlow) {
    const scr = flowToScreenPosition(pickerFlow);
    const host = document.querySelector(".field-page")?.getBoundingClientRect();
    pickerScreen = {
      left: host ? scr.x - host.left : scr.x,
      top: host ? scr.y - host.top : scr.y,
    };
  }

  return (
    <div
      className="field-page"
      onPointerDown={onHostPointerDown}
      onPointerMove={onHostPointerMove}
      onPointerUp={onHostPointerUp}
      onPointerCancel={onHostPointerUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="field-page__chrome">
        <p className="field-page__eyebrow">Surface 1</p>
        <h1 className="field-page__title">Field</h1>
        <p className="field-page__hint">
          Tap select · long-press connect · double-tap empty to create
        </p>
      </div>

      <ReactFlow
        className="field-page__flow"
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeDragStart={onNodeDragStart}
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onNodeDragStop}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        connectionMode={ConnectionMode.Loose}
        nodesConnectable={false}
        elementsSelectable
        panOnDrag={[1, 2]}
        panOnScroll
        zoomOnPinch
        minZoom={0.35}
        maxZoom={2.2}
        proOptions={{ hideAttribution: true }}
      >
        {reach && (
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
              <ReachTether
                x1={reach.from.x}
                y1={reach.from.y}
                x2={reach.to.x}
                y2={reach.to.y}
                slack={slack}
                reducedMotion={reducedMotion}
              />
            </div>
          </ViewportPortal>
        )}
      </ReactFlow>

      {pendingConnect && pickerScreen && (
        <div
          className="field-page__picker-host"
          style={{
            position: "absolute",
            left: pickerScreen.left,
            top: pickerScreen.top,
          }}
        >
          <TypePicker onPick={commitEdge} onCancel={cancelConnect} />
        </div>
      )}
    </div>
  );
}

function FieldInner() {
  const reducedMotion = useReducedMotion();
  const { markNodeRead } = useGraphController();

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "never"}>
      <FieldUiProvider reducedMotion={reducedMotion} onMarkRead={markNodeRead}>
        <FieldCanvas />
      </FieldUiProvider>
    </MotionConfig>
  );
}

export function FieldPage() {
  return (
    <ReactFlowProvider>
      <FieldInner />
    </ReactFlowProvider>
  );
}
