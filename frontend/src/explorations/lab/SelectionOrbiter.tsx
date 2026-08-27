import { useEffect, useRef } from "react";
import type { Graph, NodeData } from "@antv/g6";
import { ORBIT_SPEED_DEG } from "./orbiter/types";

/** Graph-space selection moon — scales & pans with the host node. */
export const SELECTION_ORBITER_ID = "__galab_selection_orbiter__";

/** Defaults preserve the refined selection treatment used by the older lab. */
const DEFAULT_MOON_OF_HOST = 0.22;
const DEFAULT_ORBIT_OF_HOST_R = 1.32;

type SelectionOrbiterProps = {
  graph: Graph | null;
  nodeId: string | null;
  speedDeg?: number;
  /** Orbit radius as a multiple of the selected node's radius. */
  distance?: number;
  /** Moon diameter as a fraction of the selected node's diameter. */
  moonScale?: number;
};

function hostDiameter(graph: Graph, nodeId: string) {
  const datum = graph.getNodeData(nodeId);
  const d = Number(datum?.data?._d) || Number(datum?.style?.size);
  return Number.isFinite(d) && d > 0 ? d : 50;
}

function hostCenter(graph: Graph, nodeId: string): [number, number] | null {
  try {
    const p = graph.getElementPosition(nodeId);
    const x = Number(p?.[0]);
    const y = Number(p?.[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return [x, y];
  } catch {
    return null;
  }
}

function orbiterPose(
  hostD: number,
  cx: number,
  cy: number,
  angleDeg: number,
  distance: number,
  moonScale: number,
) {
  const moonD = Math.max(6, hostD * moonScale);
  const orbitR = (hostD / 2) * distance;
  const rad = (angleDeg * Math.PI) / 180;
  return {
    moonD,
    x: cx + Math.cos(rad) * orbitR,
    y: cy + Math.sin(rad) * orbitR,
  };
}

function orbiterRow(
  hostId: string,
  cx: number,
  cy: number,
  hostD: number,
  angleDeg: number,
  distance: number,
  moonScale: number,
): NodeData {
  const { moonD, x, y } = orbiterPose(
    hostD,
    cx,
    cy,
    angleDeg,
    distance,
    moonScale,
  );
  return {
    id: SELECTION_ORBITER_ID,
    data: {
      _selectionOrbiter: true,
      _host: hostId,
      _d: moonD,
      _p: 1,
      _m: 1,
      label: "",
    },
    style: { x, y, size: moonD, zIndex: 20 },
  };
}

async function removeOrbiter(graph: Graph) {
  if (graph.destroyed) return;
  if (!graph.getNodeData(SELECTION_ORBITER_ID)) return;
  try {
    graph.removeNodeData([SELECTION_ORBITER_ID]);
    await graph.draw();
  } catch {
    /* ok */
  }
}

/**
 * Selection cue: solid crisp moon in **graph space**, orbiting the host.
 * Zoom/pan/drag keep it tied — unlike a DOM overlay.
 */
export function SelectionOrbiter({
  graph,
  nodeId,
  speedDeg = ORBIT_SPEED_DEG,
  distance = DEFAULT_ORBIT_OF_HOST_R,
  moonScale = DEFAULT_MOON_OF_HOST,
}: SelectionOrbiterProps) {
  const angleRef = useRef(40);
  const lastMoonRef = useRef(0);

  useEffect(() => {
    if (!graph || graph.destroyed || !nodeId) {
      if (graph && !graph.destroyed) void removeOrbiter(graph);
      return;
    }

    angleRef.current = 40;
    lastMoonRef.current = 0;

    let raf = 0;
    let last = performance.now();
    let busy = false;
    let pendingAngle: number | null = null;
    let cancelled = false;
    let mounted = false;

    const paint = async (angle: number) => {
      if (cancelled || graph.destroyed) return;
      if (busy) {
        pendingAngle = angle;
        return;
      }
      const center = hostCenter(graph, nodeId);
      if (!center) return;
      const [cx, cy] = center;
      const hostD = hostDiameter(graph, nodeId);
      const { moonD, x, y } = orbiterPose(
        hostD,
        cx,
        cy,
        angle,
        distance,
        moonScale,
      );

      busy = true;
      try {
        if (!mounted || !graph.getNodeData(SELECTION_ORBITER_ID)) {
          graph.addNodeData([
            orbiterRow(
              nodeId,
              cx,
              cy,
              hostD,
              angle,
              distance,
              moonScale,
            ),
          ]);
          await graph.draw().catch(() => {});
          mounted = true;
          lastMoonRef.current = moonD;
        } else {
          await graph
            .translateElementTo({ [SELECTION_ORBITER_ID]: [x, y] }, false)
            .catch(() => {});
          if (Math.abs(lastMoonRef.current - moonD) > 0.25) {
            lastMoonRef.current = moonD;
            graph.updateNodeData([
              {
                id: SELECTION_ORBITER_ID,
                data: { _d: moonD },
                style: { size: moonD },
              },
            ]);
            await graph.draw().catch(() => {});
          }
        }
      } catch {
        /* ok */
      } finally {
        busy = false;
        if (pendingAngle != null && !cancelled) {
          const next = pendingAngle;
          pendingAngle = null;
          void paint(next);
        }
      }
    };

    void paint(angleRef.current);

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      angleRef.current = (angleRef.current + speedDeg * dt) % 360;
      void paint(angleRef.current);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      void removeOrbiter(graph);
    };
  }, [distance, graph, moonScale, nodeId, speedDeg]);

  return null;
}
