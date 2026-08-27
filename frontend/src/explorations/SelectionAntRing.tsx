import { useEffect, useRef, useState } from "react";
import type { Graph } from "@antv/g6";
import {
  motionPoseKeyframes,
  type MotionPlans,
} from "../styles/motion";
import { useMotion } from "../styles/useMotion";

type SelectionAntRingProps = {
  graph: Graph | null;
  nodeId: string | null;
  nodeDiameter: number;
  clearance: number;
  dotGap: number;
  lineWidth: number;
  speed: number;
  color: string;
  dragging: boolean;
  motion: MotionPlans;
  heldScale: number;
  gravityTravel: number;
  animated?: boolean;
  /** Swallow the ring into the disc while a node is moving. */
  withdrawOnDrag?: boolean;
};

/**
 * A screen-space SVG driven by graph-space coordinates. This keeps the ring
 * crisp while it remains attached through graph pan, zoom, and node dragging.
 * The border itself never spins; stroke offset makes round dots travel around
 * the circular path like marching ants.
 *
 * Bead count is locked to the graph-space circumference so mid zoom keeps the
 * same dotted look. When that count would collide on screen, the count drops
 * until beads fit — still dotted, never a solid ring.
 */
/**
 * Scale that puts the rest-sized ring inside the disc fill.
 * Used when a drag swallows the ring so wraps do not re-solve in motion.
 */
function ringInsideScale(nodeDiameter: number, clearance: number) {
  const outer = nodeDiameter + clearance * 2;
  if (!(outer > 0)) return 0;
  return (nodeDiameter * 0.35) / outer;
}

export function SelectionAntRing({
  graph,
  nodeId,
  nodeDiameter,
  clearance,
  dotGap,
  lineWidth,
  speed,
  color,
  dragging,
  motion,
  heldScale,
  gravityTravel,
  animated = true,
  withdrawOnDrag = false,
}: SelectionAntRingProps) {
  const [renderedNodeId, setRenderedNodeId] = useState(nodeId);
  const [motionRun, setMotionRun] = useState(0);
  const lastNodeId = useRef(nodeId);
  const previousDragging = useRef(dragging);
  const circleRef = useRef<SVGCircleElement | null>(null);
  const lifecycle = useMotion<SVGSVGElement>();

  useEffect(() => {
    if (nodeId) {
      lastNodeId.current = nodeId;
      setRenderedNodeId(nodeId);
      setMotionRun((run) => run + 1);
      return;
    }
    if (!lastNodeId.current) {
      setRenderedNodeId(null);
      return;
    }
    if (!animated) {
      lastNodeId.current = null;
      setRenderedNodeId(null);
      return;
    }
    const originScale = Math.max(
      0.5,
      1 - (gravityTravel * 2) / (nodeDiameter + clearance * 2),
    );
    const animation = lifecycle.play(
      motionPoseKeyframes(
        { scale: 1, opacity: 1 },
        { scale: originScale, opacity: 0 },
      ),
      motion.absorb,
      {
        fill: "forwards",
        onFinish: () => {
          lastNodeId.current = null;
          setRenderedNodeId(null);
        },
      },
    );
    if (!animation) {
      lastNodeId.current = null;
      setRenderedNodeId(null);
    }
  }, [
    clearance,
    animated,
    gravityTravel,
    lifecycle,
    motion.absorb,
    nodeDiameter,
    nodeId,
  ]);

  useEffect(() => {
    const svg = lifecycle.ref.current;
    const circle = circleRef.current;
    if (!graph || graph.destroyed || !renderedNodeId || !svg || !circle) return;

    let frame = 0;

    const update = () => {
      if (graph.destroyed) return;
      try {
        const center = graph.getElementPosition(renderedNodeId);
        const viewport = graph.getViewportByCanvas(center);
        const zoom = Math.max(0.05, graph.getZoom() || 1);
        const graphDiameter = nodeDiameter + clearance * 2;
        const diameter = graphDiameter * zoom;
        const circumference = Math.PI * diameter;
        // Path-locked count for mid zoom; thin (never solid) when beads
        // would overlap on screen.
        const idealCount = Math.max(
          1,
          Math.round((Math.PI * graphDiameter) / Math.max(0.01, dotGap)),
        );
        const maxFit = Math.max(
          3,
          Math.floor(circumference / (lineWidth + 1)),
        );
        const beadCount = Math.min(idealCount, maxFit);
        const cycleSeconds =
          speed <= 0 ? 0 : Math.max(0.25, circumference / speed);
        svg.style.left = `${viewport[0] - diameter / 2}px`;
        svg.style.top = `${viewport[1] - diameter / 2}px`;
        svg.style.width = `${diameter}px`;
        svg.style.height = `${diameter}px`;
        svg.style.setProperty(
          "--gdna-ant-cycle",
          cycleSeconds > 0 ? `${cycleSeconds}s` : "0s",
        );
        svg.setAttribute("viewBox", `0 0 ${diameter} ${diameter}`);
        circle.setAttribute("cx", String(diameter / 2));
        circle.setAttribute("cy", String(diameter / 2));
        circle.setAttribute(
          "r",
          String(Math.max(1, diameter / 2 - lineWidth)),
        );
        circle.setAttribute("stroke-width", String(lineWidth));
        circle.setAttribute("stroke-dasharray", `0 ${100 / beadCount}`);
        svg.dataset.pattern = "dotted";
        svg.style.visibility = "visible";
      } catch {
        svg.style.visibility = "hidden";
      }
    };

    const scheduleUpdate = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        update();
      });
    };
    const observer = new ResizeObserver(scheduleUpdate);
    const container = graph.getCanvas().getContainer();
    if (container) observer.observe(container);
    graph.on("node:drag", scheduleUpdate);
    graph.on("aftertransform", scheduleUpdate);
    graph.on("afterdraw", scheduleUpdate);
    update();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      graph.off("node:drag", scheduleUpdate);
      graph.off("aftertransform", scheduleUpdate);
      graph.off("afterdraw", scheduleUpdate);
    };
  }, [
    clearance,
    dotGap,
    graph,
    lifecycle.ref,
    lineWidth,
    nodeDiameter,
    renderedNodeId,
    speed,
  ]);

  useEffect(() => {
    if (!animated) return;
    if (!renderedNodeId || !nodeId || !motionRun) return;
    const originScale = Math.max(
      0.5,
      1 - (gravityTravel * 2) / (nodeDiameter + clearance * 2),
    );
    lifecycle.play(
      motionPoseKeyframes(
        { scale: originScale, opacity: 0 },
        { scale: 1, opacity: 1 },
      ),
      motion.emit,
      { fill: "backwards" },
    );
  }, [
    animated,
    clearance,
    gravityTravel,
    lifecycle,
    motion.emit,
    motionRun,
    nodeDiameter,
    nodeId,
    renderedNodeId,
  ]);

  useEffect(() => {
    if (!renderedNodeId) return;
    if (previousDragging.current === dragging) return;
    previousDragging.current = dragging;
    const inside = ringInsideScale(nodeDiameter, clearance);
    const from = withdrawOnDrag
      ? dragging
        ? { scale: 1, opacity: 1 }
        : { scale: inside, opacity: 0 }
      : { scale: dragging ? 1 : heldScale };
    const to = withdrawOnDrag
      ? dragging
        ? { scale: inside, opacity: 0 }
        : { scale: 1, opacity: 1 }
      : { scale: dragging ? heldScale : 1 };
    const plan = withdrawOnDrag
      ? dragging
        ? motion.absorb
        : motion.emit
      : dragging
        ? motion.hold
        : motion.settle;
    if (!animated) {
      const svg = lifecycle.ref.current;
      if (svg) {
        svg.style.opacity = String(to.opacity ?? 1);
        svg.style.transform = `scale(${to.scale ?? 1})`;
      }
      return;
    }
    lifecycle.play(motionPoseKeyframes(from, to), plan, { fill: "forwards" });
  }, [
    animated,
    clearance,
    dragging,
    heldScale,
    lifecycle,
    motion.absorb,
    motion.emit,
    motion.hold,
    motion.settle,
    nodeDiameter,
    renderedNodeId,
    withdrawOnDrag,
  ]);

  if (!renderedNodeId) return null;

  return (
    <svg
      ref={lifecycle.ref}
      className={[
        "gdna__ant-ring",
        speed <= 0 ? "is-still" : "",
        dragging ? "is-held" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={{ color, visibility: "hidden" }}
      aria-hidden="true"
    >
      <circle
        ref={circleRef}
        cx={0}
        cy={0}
        r={1}
        pathLength={100}
        fill="none"
        stroke="currentColor"
        strokeWidth={lineWidth}
        strokeLinecap="round"
        strokeDasharray="0 5"
      />
    </svg>
  );
}
