/**
 * One-shot layout for the performance-first ambient lab.
 *
 * Preference order:
 *  1. `@antv/layout-wasm` ForceLayout (off main thread when threads init)
 *  2. Caller falls back to G6 `d3-force` + `enableWorker`
 *
 * Positions are baked once per graph_version. LOD must not move them.
 */

import type { GraphData } from "@antv/g6";

export type PerfLayoutEngine = "wasm-force" | "worker-d3-force" | "authored";

export type PerfLayoutResult = {
  data: GraphData;
  engine: PerfLayoutEngine;
  layoutMs: number;
  note: string;
};

type DuckNode = {
  id: string;
  data: { x: number; y: number; mass?: number };
};

type DuckEdge = {
  id: string;
  source: string;
  target: string;
  data: { weight?: number };
};

/** Minimal graph shape `layout-wasm` ForceLayout reads via getAllNodes/Edges. */
function duckGraph(nodes: DuckNode[], edges: DuckEdge[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return {
    getAllNodes: () => nodes,
    getAllEdges: () => edges,
    mergeNodeData: (id: string, data: Partial<DuckNode["data"]>) => {
      const node = byId.get(id);
      if (node) Object.assign(node.data, data);
    },
  };
}

function seedXY(i: number): { x: number; y: number } {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const r = 40 + Math.sqrt(i) * 28;
  const a = i * golden;
  return { x: 400 + Math.cos(a) * r, y: 300 + Math.sin(a) * r };
}

/**
 * Run WASM force layout and return G6 graph data with baked style.x/y.
 * Returns null when WASM cannot init (import / threads / runtime error).
 */
export async function tryWasmForceLayout(
  source: GraphData,
): Promise<PerfLayoutResult | null> {
  const t0 = performance.now();
  try {
    const { ForceLayout, initThreads } = await import("@antv/layout-wasm");
    // Single-thread WASM — no COOP/COEP headers required. Multithread is a
    // later opt-in once the lab proves the disclosure path.
    const threads = await initThreads(false);

    const rawNodes = source.nodes ?? [];
    const rawEdges = source.edges ?? [];
    const duckNodes: DuckNode[] = rawNodes.map((n, i) => {
      const style = n.style as { x?: number; y?: number } | undefined;
      const seeded =
        typeof style?.x === "number" && typeof style?.y === "number"
          ? { x: style.x, y: style.y }
          : seedXY(i);
      return { id: String(n.id), data: { ...seeded, mass: 1 } };
    });
    const duckEdges: DuckEdge[] = rawEdges.map((e, i) => ({
      id: String(e.id ?? `e${i}`),
      source: String(e.source),
      target: String(e.target),
      data: { weight: 1 },
    }));

    const layout = new ForceLayout({
      threads,
      dimensions: 2,
      width: 900,
      height: 700,
      center: [450, 350],
      maxIteration: 450,
      minMovement: 0.5,
      linkDistance: 260,
      edgeStrength: 180,
      nodeStrength: 900,
      damping: 0.88,
      maxSpeed: 400,
      preventOverlap: true,
    });

    const mapping = await layout.execute(duckGraph(duckNodes, duckEdges) as never);
    const pos = new Map<string, { x: number; y: number }>();
    for (const node of mapping.nodes ?? []) {
      const x = Number(node.data?.x);
      const y = Number(node.data?.y);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        pos.set(String(node.id), { x, y });
      }
    }
    if (pos.size < rawNodes.length * 0.5) return null;

    const data: GraphData = {
      nodes: rawNodes.map((n) => {
        const p = pos.get(String(n.id));
        if (!p) return n;
        return {
          ...n,
          style: { ...(n.style as object), x: p.x, y: p.y },
        };
      }),
      edges: rawEdges,
    };

    return {
      data,
      engine: "wasm-force",
      layoutMs: Math.round(performance.now() - t0),
      note: "WASM ForceLayout · single-thread · positions baked",
    };
  } catch (err) {
    console.warn("[ambient-perf] WASM layout unavailable", err);
    return null;
  }
}

/** Strip live layout intent — keep whatever x/y the fixture already has. */
export function authoredLayout(source: GraphData): PerfLayoutResult {
  return {
    data: source,
    engine: "authored",
    layoutMs: 0,
    note: "Authored fixture x/y · no layout pass",
  };
}
