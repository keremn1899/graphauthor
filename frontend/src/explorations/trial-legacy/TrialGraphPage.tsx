import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  MarkerType,
  ConnectionMode,
  ConnectionLineType,
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

import { FloatingConnectionLine } from "../../primitives/edge/FloatingConnectionLine";
import type { EdgeKind } from "../../primitives/edge/types";
import {
  createInitialSimLinks,
  createInitialSimNodes,
  MASS_NODE_RADIUS,
  type SimLink,
  type SimNode,
  type TrialMassData,
  type TrialGapData,
  type TrialEdgeData,
} from "./data/trialGraph";
import { useForceLayout } from "./physics/useForceLayout";
import { MassNode } from "./components/MassNode";
import { ContextualGap } from "./components/ContextualGap";
import { TypedEdge } from "./components/TypedEdge";
import { TrialControls } from "./controls/TrialControls";
import { TrialUiProvider } from "./TrialUiContext";
import { useReducedMotion } from "./hooks/useReducedMotion";
import "./TrialGraphPage.css";

function simToFlowNodes(sim: SimNode[]): Node[] {
  return sim.map((n) => {
    if (n.kind === "gap" && n.gapData) {
      return {
        id: n.id,
        type: "gap",
        position: { x: n.x - 55, y: n.y - 40 },
        data: n.gapData as TrialGapData,
        draggable: true,
        style: { pointerEvents: "none" as const },
      };
    }
    return {
      id: n.id,
      type: "mass",
      position: {
        x: n.x - MASS_NODE_RADIUS,
        y: n.y - MASS_NODE_RADIUS,
      },
      data: (n.massData ?? {
        label: n.id,
        certainty: n.certainty,
        lifecycle: "alive",
      }) as TrialMassData,
      draggable: true,
      style: { pointerEvents: "none" as const },
    };
  });
}

function simToFlowEdges(links: SimLink[]): Edge<TrialEdgeData>[] {
  return links.map((l) => {
    const source = typeof l.source === "string" ? l.source : l.source.id;
    const target = typeof l.target === "string" ? l.target : l.target.id;
    return {
      id: l.id,
      type: "typed",
      source,
      target,
      sourceHandle: `central-source-${source}`,
      targetHandle: `central-target-${target}`,
      data: { kind: l.kind },
      markerEnd:
        l.kind === "LEADSTO"
          ? {
              type: MarkerType.ArrowClosed,
              width: 12,
              height: 12,
              color: "#1c1c1c",
            }
          : undefined,
    };
  });
}

function TrialGraphInner() {
  const { fitView: fitViewFn } = useReactFlow();
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);

  const [lens, setLens] = useState<EdgeKind>("CONTAINS");
  const [simNodes, setSimNodes] = useState<SimNode[]>(() =>
    createInitialSimNodes(),
  );
  const [simLinks, setSimLinks] = useState<SimLink[]>(() =>
    createInitialSimLinks(),
  );
  const [accretingOrbiterId, setAccretingOrbiterId] = useState<string | null>(
    null,
  );
  const birthCounter = useRef(0);
  const draggingId = useRef<string | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState(
    simToFlowNodes(simNodes),
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    simToFlowEdges(simLinks),
  );

  const onTick = useCallback(
    (next: SimNode[]) => {
      if (draggingId.current) return;
      // Snapshot once — d3 mutates live sim nodes; React state must be detached
      const snapshot = next.map((n) => ({ ...n }));
      setSimNodes(snapshot);
      setNodes(simToFlowNodes(snapshot));
    },
    [setNodes],
  );

  const fitOnce = useRef(false);
  useEffect(() => {
    if (fitOnce.current) return;
    const t = window.setTimeout(() => {
      fitViewFn({ padding: 0.22, duration: reducedMotion ? 0 : 400 });
      fitOnce.current = true;
    }, reducedMotion ? 50 : 900);
    return () => window.clearTimeout(t);
  }, [fitViewFn, reducedMotion]);

  useEffect(() => {
    // Re-frame after lens-driven re-settle
    const t = window.setTimeout(() => {
      fitViewFn({ padding: 0.22, duration: reducedMotion ? 0 : 350 });
    }, reducedMotion ? 40 : 800);
    return () => window.clearTimeout(t);
  }, [lens, fitViewFn, reducedMotion]);

  const physics = useForceLayout({
    nodes: simNodes,
    links: simLinks,
    lens,
    onTick,
    reducedMotion,
  });

  // Keep edges in sync when links change
  useEffect(() => {
    setEdges(simToFlowEdges(simLinks));
  }, [simLinks, setEdges]);

  const nodeTypes: NodeTypes = useMemo(
    () => ({
      mass: MassNode,
      gap: ContextualGap,
    }),
    [],
  );

  const edgeTypes: EdgeTypes = useMemo(
    () => ({
      typed: TypedEdge,
    }),
    [],
  );

  const onNodeDragStart: OnNodeDrag = useCallback(
    (_e, node) => {
      draggingId.current = node.id;
      const cx = node.position.x + (node.type === "gap" ? 55 : MASS_NODE_RADIUS);
      const cy = node.position.y + (node.type === "gap" ? 40 : MASS_NODE_RADIUS);
      physics.pinNode(node.id, cx, cy);
    },
    [physics],
  );

  const onNodeDrag: OnNodeDrag = useCallback(
    (_e, node) => {
      const cx = node.position.x + (node.type === "gap" ? 55 : MASS_NODE_RADIUS);
      const cy = node.position.y + (node.type === "gap" ? 40 : MASS_NODE_RADIUS);
      physics.pinNode(node.id, cx, cy);
    },
    [physics],
  );

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_e, node) => {
      draggingId.current = null;
      physics.releaseNode(node.id);
    },
    [physics],
  );

  const handleLensChange = useCallback(
    (next: EdgeKind) => {
      setLens(next);
      // force layout rebuild via lens dep
    },
    [],
  );

  const handleBirth = useCallback(() => {
    birthCounter.current += 1;
    const id = `born-${birthCounter.current}`;
    const seed = simNodes.find((n) => n.id === "auth") ?? simNodes[0];
    const newborn: SimNode = {
      id,
      kind: "mass",
      x: (seed?.x ?? 400) + 40,
      y: (seed?.y ?? 300) + 40,
      certainty: 0.6,
      massData: {
        label: `New rule ${birthCounter.current}`,
        certainty: 0.6,
        lifecycle: "birthing",
        verdict: null,
      },
    };
    const next = [...simNodes, newborn];
    setSimNodes(next);
    setNodes(simToFlowNodes(next));
    physics.syncNodes(next, { reheat: true });

    // After condensation, mark alive
    window.setTimeout(() => {
      setSimNodes((cur) => {
        const updated = cur.map((n) =>
          n.id === id && n.massData
            ? {
                ...n,
                massData: { ...n.massData, lifecycle: "alive" as const },
              }
            : n,
        );
        setNodes(simToFlowNodes(updated));
        return updated;
      });
    }, reducedMotion ? 0 : 700);
  }, [physics, reducedMotion, setNodes, simNodes]);

  const handleDeath = useCallback(() => {
    // Kill the most recently born mass, else token
    const born = [...simNodes]
      .reverse()
      .find((n) => n.id.startsWith("born-") && n.kind === "mass");
    const target = born ?? simNodes.find((n) => n.id === "token");
    if (!target || !target.massData) return;

    const id = target.id;
    setSimNodes((cur) => {
      const marked = cur.map((n) =>
        n.id === id && n.massData
          ? { ...n, massData: { ...n.massData, lifecycle: "dying" as const } }
          : n,
      );
      setNodes(simToFlowNodes(marked));
      return marked;
    });

    window.setTimeout(() => {
      setSimNodes((cur) => {
        const remaining = cur.filter((n) => n.id !== id);
        setSimLinks((links) =>
          links.filter((l) => {
            const s = typeof l.source === "string" ? l.source : l.source.id;
            const t = typeof l.target === "string" ? l.target : l.target.id;
            return s !== id && t !== id;
          }),
        );
        setNodes(simToFlowNodes(remaining));
        physics.syncNodes(remaining, { reheat: true });
        return remaining;
      });
    }, reducedMotion ? 0 : 450);
  }, [physics, reducedMotion, setNodes, simNodes]);

  const handleConnect = useCallback(() => {
    const exists = simLinks.some((l) => l.id === "e-demo-connect");
    if (exists) return;
    if (!simNodes.some((n) => n.id === "policy") || !simNodes.some((n) => n.id === "mutate")) {
      return;
    }
    const link: SimLink = {
      id: "e-demo-connect",
      source: "policy",
      target: "mutate",
      kind: "LEADSTO",
    };
    const next = [...simLinks, link];
    setSimLinks(next);
    physics.setLinks(next);
  }, [physics, simLinks, simNodes]);

  const handleAccrete = useCallback(() => {
    const auth = simNodes.find((n) => n.id === "auth");
    const first = auth?.massData?.orbiters?.[0];
    if (!first) return;
    setAccretingOrbiterId(first.id);
  }, [simNodes]);

  const onAccretionDone = useCallback(
    (orbiterId: string) => {
      setAccretingOrbiterId(null);
      setSimNodes((cur) => {
        const updated = cur.map((n) => {
          if (n.id !== "auth" || !n.massData?.orbiters) return n;
          return {
            ...n,
            certainty: Math.min(1, n.certainty + 0.05),
            massData: {
              ...n.massData,
              certainty: Math.min(1, n.massData.certainty + 0.05),
              orbiters: n.massData.orbiters.filter((o) => o.id !== orbiterId),
            },
          };
        });
        setNodes(simToFlowNodes(updated));
        return updated;
      });
    },
    [setNodes],
  );

  const canAccrete = Boolean(
    simNodes.find((n) => n.id === "auth")?.massData?.orbiters?.length,
  );

  const uiValue = useMemo(
    () => ({
      reducedMotion,
      lens,
      accretingOrbiterId,
      onAccretionDone,
    }),
    [reducedMotion, lens, accretingOrbiterId, onAccretionDone],
  );

  return (
    <TrialUiProvider value={uiValue}>
      <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
        <div
          className={
            reducedMotion ? "trial-graph reduced-motion" : "trial-graph"
          }
        >
          <header className="trial-graph__chrome">
            <div className="trial-graph__intro">
              <p className="trial-graph__eyebrow">
                Physical prototype · trial graph
              </p>
              <h1 className="trial-graph__title">
                Gravity field of certainty
              </h1>
              <p className="trial-graph__lede">
                <a className="trial-graph__link" href="#/">
                  ← Live Field + Inbox
                </a>
                {" · "}
                Settled masses stay still. Uncertain margins move. Gaps live
                inside the logging containment pocket — sealed intended vs
                sparse oversight. Drag a node to override gravity; release to
                re-settle.{" "}
                <a className="trial-graph__link" href="#/explorations/edges">
                  Edges
                </a>
                {" · "}
                <a className="trial-graph__link" href="#/explorations/tether">
                  Tether
                </a>
                {" · "}
                <a className="trial-graph__link" href="#/explorations/orbiters">
                  Orbiters
                </a>
                {" · "}
                <a className="trial-graph__link" href="#/explorations/connect">
                  Connect
                </a>
                {" · "}
                <a className="trial-graph__link" href="#/explorations/membrane">
                  Membrane
                </a>
              </p>
            </div>
            <TrialControls
              lens={lens}
              onLensChange={handleLensChange}
              reducedMotion={reducedMotion}
              onReducedMotionChange={(v) => setMotionOverride(v)}
              onBirth={handleBirth}
              onDeath={handleDeath}
              onConnect={handleConnect}
              onAccrete={handleAccrete}
              onReheat={() => physics.reheat()}
              canAccrete={canAccrete}
            />
          </header>

          <div className="trial-graph__canvas">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onNodeDragStart={onNodeDragStart}
              onNodeDrag={onNodeDrag}
              onNodeDragStop={onNodeDragStop}
              connectionMode={ConnectionMode.Loose}
              connectionLineType={ConnectionLineType.Straight}
              connectionLineComponent={FloatingConnectionLine}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.35}
              maxZoom={1.6}
              proOptions={{ hideAttribution: true }}
            />
          </div>
        </div>
      </MotionConfig>
    </TrialUiProvider>
  );
}

export function TrialGraphPage() {
  return (
    <ReactFlowProvider>
      <TrialGraphInner />
    </ReactFlowProvider>
  );
}
