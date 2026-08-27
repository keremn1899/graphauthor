import { useEffect, useRef, useState } from "react";
import { Graph, type EdgeData, type GraphData, type NodeData } from "@antv/g6";
import {
  BASE_BEHAVIORS,
  BASE_EDGE_STATE,
  BASE_NODE_STYLE,
  BASE_NODE_STATE,
} from "../g6/graphOptions";
import { edgeStyleForKind, type EdgeKind } from "../g6/edgeKinds";
import "../g6/g6Lab.css";

/**
 * Edge-type → layout proposals (pure graphs of one kind):
 *   LEADSTO   → antv-dagre (layered cascade)
 *   CONTAINS  → antv-dagre TB (parent above child — still edges, not combos)
 *   NEARTO    → d3-force once, then rest (neighborhood / kinship puddle)
 *   EXPRESSES → radial around a focus (soft “maps onto” reading)
 *
 * Multiple layouts at once?
 *   G6 supports a *pipeline*: layout: [cfgA, cfgB, …] run in sequence.
 *   Each stage can use nodeFilter to touch only some nodes.
 *   That is NOT “this edge type uses layout A while that edge type uses
 *   layout B on the same nodes.” A node has one (x, y). Filters partition
 *   *nodes*, not edge kinds — and there is no edgeFilter. Edges between
 *   the filtered nodes all feed that stage, regardless of kind.
 *
 *   So: native multi-layout = disjoint (or staged) node subsets.
 *   True “layout by edge kind on a shared connected KG” needs a custom
 *   layout or a lens (run one kind’s algorithm; still draw all edges).
 */

type EdgeKindUi = "leadsto" | "contains" | "nearto" | "expresses";

type ModeId = EdgeKindUi | "pipeline" | "mixed-single";

type RankDir = "TB" | "LR";

const KIND_TO_G6: Record<EdgeKindUi, EdgeKind | "leadsto"> = {
  leadsto: "leadsto",
  // G6 seed lab only styles leadsto|expresses|nearto — map contains → leadsto
  // stroke for now, but we mark data.kind distinctly for filters/copy.
  contains: "leadsto",
  nearto: "nearto",
  expresses: "expresses",
};

function styleForUiKind(kind: EdgeKindUi) {
  if (kind === "contains") {
    return {
      stroke: "#111",
      lineWidth: 1.6,
      endArrow: true,
      endArrowType: "vee" as const,
      endArrowSize: 10,
      lineDash: undefined as number[] | undefined,
    };
  }
  return edgeStyleForKind(KIND_TO_G6[kind] as EdgeKind);
}

/** Pure LEADSTO fragment */
const LEADSTO_DATA: GraphData = {
  nodes: [
    { id: "a", data: { group: "leadsto" } },
    { id: "b", data: { group: "leadsto" } },
    { id: "hub", data: { group: "leadsto" } },
    { id: "c", data: { group: "leadsto" } },
    { id: "d", data: { group: "leadsto" } },
    { id: "e", data: { group: "leadsto" } },
  ],
  edges: [
    { id: "l1", source: "a", target: "hub", data: { kind: "leadsto" } },
    { id: "l2", source: "b", target: "hub", data: { kind: "leadsto" } },
    { id: "l3", source: "hub", target: "c", data: { kind: "leadsto" } },
    { id: "l4", source: "hub", target: "d", data: { kind: "leadsto" } },
    { id: "l5", source: "hub", target: "e", data: { kind: "leadsto" } },
    { id: "l6", source: "a", target: "c", data: { kind: "leadsto" } },
  ],
};

/** Pure CONTAINS fragment — parent → child */
const CONTAINS_DATA: GraphData = {
  nodes: [
    { id: "region", data: { group: "contains" } },
    { id: "chapter-a", data: { group: "contains" } },
    { id: "chapter-b", data: { group: "contains" } },
    { id: "section-a1", data: { group: "contains" } },
    { id: "section-a2", data: { group: "contains" } },
    { id: "section-b1", data: { group: "contains" } },
  ],
  edges: [
    { id: "c1", source: "region", target: "chapter-a", data: { kind: "contains" } },
    { id: "c2", source: "region", target: "chapter-b", data: { kind: "contains" } },
    {
      id: "c3",
      source: "chapter-a",
      target: "section-a1",
      data: { kind: "contains" },
    },
    {
      id: "c4",
      source: "chapter-a",
      target: "section-a2",
      data: { kind: "contains" },
    },
    {
      id: "c5",
      source: "chapter-b",
      target: "section-b1",
      data: { kind: "contains" },
    },
  ],
};

/** Pure NEARTO — undirected kinship (drawn undirected) */
const NEARTO_DATA: GraphData = {
  nodes: [
    { id: "n1", data: { group: "nearto" } },
    { id: "n2", data: { group: "nearto" } },
    { id: "n3", data: { group: "nearto" } },
    { id: "n4", data: { group: "nearto" } },
    { id: "n5", data: { group: "nearto" } },
    { id: "n6", data: { group: "nearto" } },
  ],
  edges: [
    { id: "n-e1", source: "n1", target: "n2", data: { kind: "nearto" } },
    { id: "n-e2", source: "n1", target: "n3", data: { kind: "nearto" } },
    { id: "n-e3", source: "n2", target: "n4", data: { kind: "nearto" } },
    { id: "n-e4", source: "n3", target: "n4", data: { kind: "nearto" } },
    { id: "n-e5", source: "n3", target: "n5", data: { kind: "nearto" } },
    { id: "n-e6", source: "n4", target: "n6", data: { kind: "nearto" } },
    { id: "n-e7", source: "n5", target: "n6", data: { kind: "nearto" } },
  ],
};

/** Pure EXPRESSES — soft directed maps */
const EXPRESSES_DATA: GraphData = {
  nodes: [
    { id: "theme", data: { group: "expresses" } },
    { id: "form-a", data: { group: "expresses" } },
    { id: "form-b", data: { group: "expresses" } },
    { id: "form-c", data: { group: "expresses" } },
    { id: "detail-a", data: { group: "expresses" } },
    { id: "detail-b", data: { group: "expresses" } },
  ],
  edges: [
    { id: "x1", source: "theme", target: "form-a", data: { kind: "expresses" } },
    { id: "x2", source: "theme", target: "form-b", data: { kind: "expresses" } },
    { id: "x3", source: "theme", target: "form-c", data: { kind: "expresses" } },
    {
      id: "x4",
      source: "form-a",
      target: "detail-a",
      data: { kind: "expresses" },
    },
    {
      id: "x5",
      source: "form-b",
      target: "detail-b",
      data: { kind: "expresses" },
    },
  ],
};

/**
 * Disjoint node groups for the pipeline demo — what G6 natively supports:
 * two separate node sets, two layout algorithms, one canvas.
 */
const PIPELINE_DATA: GraphData = {
  nodes: [
    ...(LEADSTO_DATA.nodes ?? []),
    ...(NEARTO_DATA.nodes ?? []),
  ],
  edges: [
    ...(LEADSTO_DATA.edges ?? []),
    ...(NEARTO_DATA.edges ?? []),
  ],
};

/** Connected mixed KG — all edge kinds share nodes. One (x,y) per node. */
const MIXED_DATA: GraphData = {
  nodes: [
    { id: "world", data: { group: "mixed" } },
    { id: "domain", data: { group: "mixed" } },
    { id: "claim", data: { group: "mixed" } },
    { id: "lemma", data: { group: "mixed" } },
    { id: "symbol", data: { group: "mixed" } },
    { id: "neighbor", data: { group: "mixed" } },
  ],
  edges: [
    { id: "m1", source: "world", target: "domain", data: { kind: "contains" } },
    { id: "m2", source: "domain", target: "claim", data: { kind: "contains" } },
    { id: "m3", source: "claim", target: "lemma", data: { kind: "leadsto" } },
    { id: "m4", source: "claim", target: "symbol", data: { kind: "expresses" } },
    { id: "m5", source: "lemma", target: "neighbor", data: { kind: "nearto" } },
    { id: "m6", source: "symbol", target: "neighbor", data: { kind: "nearto" } },
  ],
};

const MODES: Record<
  ModeId,
  { label: string; note: string; data: GraphData }
> = {
  leadsto: {
    label: "LEADSTO",
    note: "Proposal: antv-dagre — layered cascade. Fan-in/out are native.",
    data: LEADSTO_DATA,
  },
  contains: {
    label: "CONTAINS",
    note: "Proposal: antv-dagre TB — parent above child. Still edges (not combos).",
    data: CONTAINS_DATA,
  },
  nearto: {
    label: "NEARTO",
    note: "Proposal: d3-force (one settle) — neighborhood puddle, no ranks.",
    data: NEARTO_DATA,
  },
  expresses: {
    label: "EXPRESSES",
    note: "Proposal: radial around a focus — soft “maps onto,” weak geometry.",
    data: EXPRESSES_DATA,
  },
  pipeline: {
    label: "Pipeline (native)",
    note: "G6 native multi-layout: LEADSTO nodes → antv-dagre, NEARTO nodes → force. Disjoint node sets only — not per edge type on shared nodes.",
    data: PIPELINE_DATA,
  },
  "mixed-single": {
    label: "Mixed (one layout)",
    note: "Connected KG with all four edge kinds. One layout (antv-dagre) places everything; edges stay multi-typed. This is the realistic default — not four layouts at once.",
    data: MIXED_DATA,
  },
};

const MODE_IDS = Object.keys(MODES) as ModeId[];

function layoutForMode(mode: ModeId, rankdir: RankDir) {
  if (mode === "leadsto") {
    return {
      type: "antv-dagre" as const,
      rankdir,
      nodesep: 48,
      ranksep: 72,
      controlPoints: false,
    };
  }
  if (mode === "contains") {
    return {
      type: "antv-dagre" as const,
      rankdir: "TB" as const,
      nodesep: 40,
      ranksep: 64,
      controlPoints: false,
    };
  }
  if (mode === "nearto") {
    return {
      type: "d3-force" as const,
      link: { distance: 110, strength: 0.35 },
      manyBody: { strength: -280 },
      collide: { radius: 36, strength: 0.8 },
      alphaDecay: 0.05,
      velocityDecay: 0.4,
      alphaTarget: 0,
      animation: false,
    };
  }
  if (mode === "expresses") {
    return {
      type: "radial" as const,
      unitRadius: 90,
      linkDistance: 120,
      preventOverlap: true,
      nodeSize: 50,
      focusNode: "theme",
    };
  }
  if (mode === "pipeline") {
    // Native G6: array of layouts + nodeFilter. Partitions NODES, not edge kinds.
    return [
      {
        type: "antv-dagre" as const,
        rankdir: "TB" as const,
        nodesep: 40,
        ranksep: 60,
        controlPoints: false,
        nodeFilter: (node: NodeData) => node.data?.group === "leadsto",
      },
      {
        type: "d3-force" as const,
        link: { distance: 90, strength: 0.4 },
        manyBody: { strength: -220 },
        collide: { radius: 34, strength: 0.7 },
        alphaDecay: 0.06,
        alphaTarget: 0,
        animation: false,
        center: { x: 520, y: 220 },
        nodeFilter: (node: NodeData) => node.data?.group === "nearto",
      },
    ];
  }
  // mixed-single: one structural layout; all edge kinds still drawn
  return {
    type: "antv-dagre" as const,
    rankdir,
    nodesep: 48,
    ranksep: 70,
    controlPoints: false,
  };
}

function edgeStyleMapper(d: EdgeData) {
  const kind = (d.data?.kind as EdgeKindUi) ?? "nearto";
  if (
    kind === "contains" ||
    kind === "leadsto" ||
    kind === "nearto" ||
    kind === "expresses"
  ) {
    return styleForUiKind(kind);
  }
  return edgeStyleForKind("nearto");
}

export function G6EdgeLayoutLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [mode, setMode] = useState<ModeId>("pipeline");
  const [rankdir, setRankdir] = useState<RankDir>("TB");
  const [layoutTick, setLayoutTick] = useState(0);
  const [note, setNote] = useState(MODES.pipeline.note);

  useEffect(() => {
    if (!containerRef.current) return;

    const scenario = MODES[mode];
    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      padding: 24,
      data: structuredClone(scenario.data),
      node: {
        style: { ...BASE_NODE_STYLE, size: 46, labelFontSize: 9 },
        state: BASE_NODE_STATE,
      },
      edge: {
        // Straight line edges only — no polyline bends / layout control points.
        type: "line",
        style: {
          stroke: (d: EdgeData) => edgeStyleMapper(d).stroke,
          lineWidth: (d: EdgeData) => edgeStyleMapper(d).lineWidth,
          endArrow: (d: EdgeData) => edgeStyleMapper(d).endArrow,
          endArrowType: "triangle",
          endArrowSize: 8,
          lineDash: (d: EdgeData) => edgeStyleMapper(d).lineDash,
        },
        state: BASE_EDGE_STATE,
      },
      layout: layoutForMode(mode, rankdir) as never,
      behaviors: [...BASE_BEHAVIORS],
    });

    graph
      .render()
      .then(() => graph.fitView())
      .catch(() => {});
    graphRef.current = graph;
    setNote(scenario.note);

    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, [mode, rankdir, layoutTick]);

  const showRankdir = mode === "leadsto" || mode === "mixed-single";

  return (
    <div className="g6-lab">
      <header className="g6-lab__chrome">
        <p className="g6-lab__eyebrow">Design lab</p>
        <h1 className="g6-lab__title">Edge-type layouts</h1>
        <p className="g6-lab__lede">
          Pure graphs per edge kind, plus what G6 can do natively for
          “multiple layouts.” Spoiler:{" "}
          <code>layout: […]</code> with <code>nodeFilter</code> partitions{" "}
          <em>nodes</em> in sequence — it does not assign a layout per edge
          type on a shared connected graph. A node has one position.
        </p>

        <div className="g6-lab__controls">
          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Mode</span>
            {MODE_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={
                  "g6-lab__chip" + (mode === id ? " g6-lab__chip--active" : "")
                }
                onClick={() => setMode(id)}
              >
                {MODES[id].label}
              </button>
            ))}
          </div>

          {showRankdir ? (
            <div className="g6-lab__control-row">
              <span className="g6-lab__control-label">Direction</span>
              {(["TB", "LR"] as RankDir[]).map((dir) => (
                <button
                  key={dir}
                  type="button"
                  className={
                    "g6-lab__chip" + (rankdir === dir ? " g6-lab__chip--active" : "")
                  }
                  onClick={() => setRankdir(dir)}
                >
                  {dir === "TB" ? "Top → bottom" : "Left → right"}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="g6-lab__actions">
          <button
            type="button"
            onClick={() => {
              setLayoutTick((n) => n + 1);
              setNote(`Re-ran layout for “${MODES[mode].label}”.`);
            }}
          >
            Re-layout
          </button>
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-connect">Connect</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-physics">Physics</a>
        </p>
      </header>

      <p className="g6-lab__note">{note}</p>
      <div className="g6-lab__stage" ref={containerRef} />
    </div>
  );
}
