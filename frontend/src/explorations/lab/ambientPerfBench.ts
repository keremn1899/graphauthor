/**
 * Isolate what actually costs frames on the ambient perf lab.
 *
 * Change ONE axis, remount, hit Bench. Compare rows — don't stack knobs.
 */

import type { Graph, GraphData } from "@antv/g6";
import { importanceOf, isLandmark } from "./ambientLodData";

export type NodeCap = 25 | 50 | 104;

export type BottleneckConfig = {
  nodeCap: NodeCap;
  labels: boolean;
  physics: boolean;
  /** When false, wheel/pan never runs disclosure sync — camera only. */
  lodSync: boolean;
  edges: boolean;
};

export const DEFAULT_BOTTLENECK: BottleneckConfig = {
  nodeCap: 104,
  labels: true,
  // Measurements showed live force drops idle from ~120fps to ~27fps at N=104.
  // Product/perf default: layout once, then freeze.
  physics: false,
  lodSync: true,
  edges: true,
};

/** Keep landmarks + highest-importance nodes, then induced edges. */
export function subsampleGraph(data: GraphData, cap: NodeCap): GraphData {
  const nodes = [...(data.nodes ?? [])];
  if (nodes.length <= cap) {
    return {
      nodes,
      edges: data.edges ?? [],
    };
  }

  const ranked = [...nodes].sort((a, b) => {
    const la = isLandmark(a) ? 1 : 0;
    const lb = isLandmark(b) ? 1 : 0;
    if (la !== lb) return lb - la;
    return importanceOf(b) - importanceOf(a);
  });
  const keep = new Set(ranked.slice(0, cap).map((n) => String(n.id)));
  return {
    nodes: nodes.filter((n) => keep.has(String(n.id))),
    edges: (data.edges ?? []).filter(
      (e) => keep.has(String(e.source)) && keep.has(String(e.target)),
    ),
  };
}

export type BottleneckReport = {
  config: BottleneckConfig;
  nodeCount: number;
  edgeCount: number;
  idleFps: number;
  drawAvgMs: number;
  syncAvgMs: number;
  panFps: number;
  zoomFps: number;
  panMs: number;
  zoomMs: number;
  draws: number[];
  syncs: number[];
};

function avg(xs: number[]) {
  return xs.reduce((s, x) => s + x, 0) / Math.max(1, xs.length);
}

function round1(n: number) {
  return Math.round(n * 10) / 10;
}

async function measureFpsDuring(
  ms: number,
  work: (frame: number) => void | Promise<void>,
): Promise<{ fps: number; elapsedMs: number }> {
  let frames = 0;
  const t0 = performance.now();
  while (performance.now() - t0 < ms) {
    await work(frames);
    frames += 1;
    await new Promise<void>((r) => requestAnimationFrame(() => r()));
  }
  const elapsed = performance.now() - t0;
  return {
    fps: Math.round((frames * 1000) / Math.max(1, elapsed)),
    elapsedMs: Math.round(elapsed),
  };
}

export type BottleneckHooks = {
  graph: Graph;
  syncLod: (force?: boolean) => Promise<void>;
  timedDraw: () => Promise<number>;
  config: BottleneckConfig;
};

/**
 * Controlled microbench. Run after the graph is ready; results also land on
 * `window.__ambientPerfBench`.
 */
export async function runBottleneckBench(
  hooks: BottleneckHooks,
): Promise<BottleneckReport> {
  const { graph, syncLod, timedDraw, config } = hooks;
  if (graph.destroyed) {
    throw new Error("graph destroyed");
  }

  const nodeCount = graph.getNodeData().length;
  const edgeCount = graph.getEdgeData().length;

  // Idle — no camera work.
  const idle = await measureFpsDuring(800, async () => {});

  const draws: number[] = [];
  for (let i = 0; i < 8; i++) {
    draws.push(await timedDraw());
  }

  const syncs: number[] = [];
  if (config.lodSync) {
    for (let i = 0; i < 8; i++) {
      const t0 = performance.now();
      await syncLod(true);
      syncs.push(performance.now() - t0);
    }
  }

  const startZoom = graph.getZoom();
  const [cx, cy] = graph.getCanvasByViewport([
    graph.getSize()[0] / 2,
    graph.getSize()[1] / 2,
  ]);

  // Pan — translate camera in small steps (no LOD if lodSync false; transform
  // handler still fires but sync is skipped).
  const pan = await measureFpsDuring(900, async (frame) => {
    const dx = ((frame % 2) * 2 - 1) * 18;
    const dy = (((frame >> 1) % 2) * 2 - 1) * 12;
    await graph.translateBy([dx, dy], false).catch(() => {});
  });

  // Zoom — alternate in/out about the centre.
  const zoom = await measureFpsDuring(900, async (frame) => {
    const factor = frame % 2 === 0 ? 1.06 : 1 / 1.06;
    const next = Math.max(0.2, Math.min(4, graph.getZoom() * factor));
    await graph.zoomTo(next, false, [cx, cy]).catch(() => {});
  });

  // Restore framing roughly.
  await graph.zoomTo(startZoom, false).catch(() => {});
  await syncLod(true).catch(() => {});

  const report: BottleneckReport = {
    config: { ...config },
    nodeCount,
    edgeCount,
    idleFps: idle.fps,
    drawAvgMs: round1(avg(draws)),
    syncAvgMs: syncs.length ? round1(avg(syncs)) : 0,
    panFps: pan.fps,
    zoomFps: zoom.fps,
    panMs: pan.elapsedMs,
    zoomMs: zoom.elapsedMs,
    draws: draws.map(round1),
    syncs: syncs.map(round1),
  };

  (
    window as Window & { __ambientPerfBench?: BottleneckReport }
  ).__ambientPerfBench = report;
  console.info("[ambient-perf] bottleneck bench", report);
  return report;
}

/** One-line verdict helper for the HUD. */
export function bottleneckHint(report: BottleneckReport): string {
  const { drawAvgMs, syncAvgMs, panFps, zoomFps, config, nodeCount } = report;
  if (drawAvgMs >= 12) {
    return `draw ${drawAvgMs}ms dominates at N=${nodeCount} — paint/scene cost`;
  }
  if (config.lodSync && syncAvgMs >= 10) {
    return `LOD sync ${syncAvgMs}ms — disclosure/update+draw path`;
  }
  if (panFps < 40 && zoomFps >= panFps - 5) {
    return `pan/zoom ~${Math.min(panFps, zoomFps)}fps — camera/compositing`;
  }
  if (config.physics && panFps < 45) {
    return `try physics off — live force may share the main thread`;
  }
  if (nodeCount >= 80 && drawAvgMs >= 6) {
    return `scales with N — try nodeCap 50 / 25`;
  }
  return `no single spike — compare rows across nodeCap / labels / physics`;
}
