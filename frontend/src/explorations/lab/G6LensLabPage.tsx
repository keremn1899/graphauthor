import { useEffect, useRef, useState } from "react";
import {
  Graph,
  type LayoutOptions,
} from "@antv/g6";
import {
  BASE_EDGE_STATE,
  BASE_NODE_STATE,
  BASE_NODE_STYLE,
  CIRCLE_NODE_FONT_IDS,
  DEFAULT_CIRCLE_NODE_FONT,
  NODE_FONTS,
  type NodeFontId,
} from "../g6/graphOptions";
import { FORCE_PRESETS } from "../g6/forcePresets";
import {
  ensureContainsEdgeRegistered,
} from "../g6/containsEdge";
import {
  LENS_EDGE_STYLE,
  LENS_EDGE_TYPE,
} from "../g6/lensEdgeOptions";
import {
  createLensLabGraph,
  LENS_FOCUS_NODE,
} from "../g6/lensLabGraph";
import {
  ensureStructuralDagreRegistered,
  LENS_DAGRE_CONTAINS,
  LENS_DAGRE_LEADSTO,
} from "../g6/structuralDagre";
import "../g6/g6Lab.css";

/** Below this, node labels read as noise rather than text — hold the floor. */
const MIN_LEGIBLE_ZOOM = 0.72;

/** Match the production Field node size; keep lens labels slightly larger. */
const LENS_NODE_SIZE = 88;
const LENS_LABEL_FONT_SIZE = 11;
const LENS_LABEL_FONT_WEIGHT = 500;

/**
 * A lens here is a layout applied to the whole graph — not an edge-kind filter.
 * All SST edges stay drawn the same regardless of active lens.
 */
type LensId = "glide" | "nested" | "cascade" | "cluster" | "radial";

const LENSES: Array<{ id: LensId; label: string; note: string }> = [
  {
    id: "glide",
    label: "Glide",
    note: "Link-only Glide — dragging transmits tension through connected edges; unrelated nodes carry no charge.",
  },
  {
    id: "nested",
    label: "Nested",
    note: "antv-dagre top→bottom on CONTAINS, then live d3-force with soft springs back to those anchors. Drag tugs the field; release and it settles home.",
  },
  {
    id: "cascade",
    label: "Cascade",
    note: "antv-dagre left→right on LEADSTO, then live d3-force springs to anchors. Drag tugs the field; release and it settles home.",
  },
  {
    id: "cluster",
    label: "Cluster",
    note: "Open d3-force settle for shape, then the same anchor-spring field. Drag tugs; release settles home.",
  },
  {
    id: "radial",
    label: "Radial",
    note: "Radial around Platform, then live d3-force springs to anchors. Drag tugs the field; release and it settles home.",
  },
];

const EDGE_OPTIONS = {
  type: LENS_EDGE_TYPE,
  style: LENS_EDGE_STYLE,
  state: BASE_EDGE_STATE,
};

/** Per-lens structural knobs — only the 1–2 that actually change the reading. */
type DagreTuning = { nodesep: number; ranksep: number };
type ClusterTuning = { linkDist: number; charge: number };
type RadialTuning = { unitRadius: number; linkDistance: number };
type GlideTuning = { linkDist: number; linkStrength: number };

type LayoutTunings = {
  nested: DagreTuning;
  cascade: DagreTuning;
  cluster: ClusterTuning;
  radial: RadialTuning;
  glide: GlideTuning;
};

const DEFAULT_LAYOUT_TUNINGS: LayoutTunings = {
  nested: { nodesep: 52, ranksep: 84 },
  cascade: { nodesep: 52, ranksep: 92 },
  cluster: { linkDist: 165, charge: 380 },
  radial: { unitRadius: 140, linkDistance: 160 },
  glide: { linkDist: 260, linkStrength: 0.07 },
};

/** Structural pass only — places nodes. Locked lenses then hand off to the
 * anchor-spring field below for interaction. */
function structuralLayoutForLens(
  lens: Exclude<LensId, "glide">,
  tunings: LayoutTunings,
): LayoutOptions {
  if (lens === "nested") {
    const t = tunings.nested;
    return {
      type: LENS_DAGRE_CONTAINS,
      rankdir: "TB",
      nodesep: t.nodesep,
      ranksep: t.ranksep,
      controlPoints: false,
      animation: true,
    };
  }
  if (lens === "cascade") {
    const t = tunings.cascade;
    return {
      type: LENS_DAGRE_LEADSTO,
      rankdir: "LR",
      nodesep: t.nodesep,
      ranksep: t.ranksep,
      controlPoints: false,
      animation: true,
    };
  }
  if (lens === "cluster") {
    const t = tunings.cluster;
    return {
      type: "d3-force",
      link: { distance: t.linkDist, strength: 0.45 },
      manyBody: { strength: -Math.abs(t.charge) },
      collide: {
        radius: LENS_NODE_SIZE / 2 + 4,
        strength: 1,
        iterations: 3,
      },
      alphaDecay: 0.05,
      velocityDecay: 0.42,
      alpha: 0.35,
      alphaTarget: 0,
      animation: true,
    };
  }
  const t = tunings.radial;
  return {
    type: "radial",
    unitRadius: t.unitRadius,
    linkDistance: t.linkDistance,
    preventOverlap: true,
    nodeSize: LENS_NODE_SIZE,
    focusNode: LENS_FOCUS_NODE,
    animation: true,
  };
}

function glideLayout(tunings: LayoutTunings): LayoutOptions {
  const t = tunings.glide;
  const base = FORCE_PRESETS["glide-loose"].layout;
  return {
    ...base,
    link: { distance: t.linkDist, strength: t.linkStrength, iterations: 1 },
    manyBody: false,
    collide: { radius: LENS_NODE_SIZE / 2 + 4, strength: 1, iterations: 3 },
    center: false,
    animation: true,
  } as LayoutOptions;
}

/**
 * Live d3-force field for locked lenses. Each node has a soft forceX/forceY
 * spring toward its structural-layout anchor; links carry tug to neighbors
 * when you drag. `fixed: false` on drag-element-force means release clears
 * the pin and the springs pull the field home — real d3, not a rAF hack.
 *
 * `anchors` is read live on every tick (same Map instance, mutated when a
 * lens switches), so we don't need to rebuild the force closures.
 *
 * Tuning knobs only color the feel — snap-back itself is structural
 * (anchors + springs always on). `snap` is floored above `tug` so the
 * resting shape can't lose to the links.
 */
type FieldTuning = {
  /** forceX/forceY strength — how hard home pulls after release. */
  snap: number;
  /** link strength — how much neighbors follow a drag. */
  tug: number;
  /** velocityDecay — higher = stickier, less wobble on the way home. */
  damping: number;
};

const DEFAULT_FIELD_TUNING: FieldTuning = {
  snap: 0.65,
  tug: 0.35,
  damping: 0.36,
};

function anchoredFieldLayout(
  anchors: Map<string, { x: number; y: number }>,
  tuning: FieldTuning = DEFAULT_FIELD_TUNING,
): LayoutOptions {
  // Keep home springs strictly stronger than links so snap-back always wins.
  const snap = Math.max(tuning.snap, tuning.tug + 0.2);
  return {
    type: "d3-force",
    animation: true,
    center: false,
    link: {
      strength: tuning.tug,
      distance: (edge: {
        source: { id: string | number } | string | number;
        target: { id: string | number } | string | number;
      }) => {
        const sid =
          typeof edge.source === "object" ? String(edge.source.id) : String(edge.source);
        const tid =
          typeof edge.target === "object" ? String(edge.target.id) : String(edge.target);
        const a = anchors.get(sid);
        const b = anchors.get(tid);
        if (!a || !b) return 140;
        return Math.hypot(a.x - b.x, a.y - b.y);
      },
    },
    manyBody: false,
    collide: {
      radius: LENS_NODE_SIZE / 2 + 4,
      strength: 1,
      iterations: 3,
    },
    x: {
      strength: snap,
      x: (d: { id: string | number }) => anchors.get(String(d.id))?.x ?? 0,
    },
    y: {
      strength: snap,
      y: (d: { id: string | number }) => anchors.get(String(d.id))?.y ?? 0,
    },
    alphaDecay: 0.02,
    velocityDecay: tuning.damping,
    alpha: 0,
    alphaTarget: 0,
  } as LayoutOptions;
}

function layoutForLens(
  lens: LensId,
  anchors: Map<string, { x: number; y: number }>,
  fieldTuning: FieldTuning = DEFAULT_FIELD_TUNING,
  layoutTunings: LayoutTunings = DEFAULT_LAYOUT_TUNINGS,
): LayoutOptions {
  if (lens === "glide") {
    return glideLayout(layoutTunings);
  }
  return anchoredFieldLayout(anchors, fieldTuning);
}

/**
 * fitView alone will zoom a tall/wide layout (e.g. dagre on 20 nodes) down
 * far enough that a 9px label stops rendering as legible text. Fit, then
 * hold a minimum zoom floor — the graph may spill past the stage edge, but
 * drag-canvas / zoom-canvas are always on, so panning to see the rest costs
 * nothing.
 */
async function settleView(graph: Graph) {
  if (graph.destroyed) return;
  await graph.fitView();
  if (graph.destroyed) return;
  if (graph.getZoom() < MIN_LEGIBLE_ZOOM) {
    await graph.zoomTo(MIN_LEGIBLE_ZOOM, false);
  }
}

function captureAnchors(graph: Graph, into: Map<string, { x: number; y: number }>) {
  into.clear();
  for (const node of graph.getNodeData()) {
    const x = node.style?.x;
    const y = node.style?.y;
    if (typeof x === "number" && typeof y === "number") {
      into.set(String(node.id), { x, y });
    }
  }
}

/** Drop any leftover hard pins so the soft x/y springs own resting place. */
function clearHardPins(graph: Graph) {
  const updates = graph.getNodeData().map((node) => ({
    id: node.id,
    style: { fx: null, fy: null },
  }));
  if (updates.length) graph.updateNodeData(updates);
}

const SHARED_BEHAVIORS = [
  "drag-canvas",
  "zoom-canvas",
  "click-select",
  { type: "hover-activate", degree: 0, state: "active" },
] as const;

function behaviorsForLens(lens: LensId) {
  if (lens === "glide") {
    return [...SHARED_BEHAVIORS, { type: "drag-element-force", fixed: false }];
  }
  // Locked field — pin only while dragging; release lets anchor springs home.
  return [...SHARED_BEHAVIORS, { type: "drag-element-force", fixed: false }];
}

/** Circle-friendly sans only — serifs / display faces clip oddly in a disc. */
function lensNodeOptions(fontId: NodeFontId) {
  const font = NODE_FONTS[fontId];
  return {
    style: {
      ...BASE_NODE_STYLE,
      // Match the production Field's 88px circles.
      size: LENS_NODE_SIZE,
      labelFontSize: LENS_LABEL_FONT_SIZE,
      labelFontFamily: font.family,
      labelFontWeight: LENS_LABEL_FONT_WEIGHT,
      labelLineHeight: 13,
      labelPlacement: "center" as const,
      labelOffsetY: 4,
      // Use the circle's broad middle band. Two centered 13px lines leave
      // roughly a third of the 88px disc clear above and below.
      labelWordWrap: true,
      labelMaxWidth: "76%",
      labelMaxLines: 2,
      labelTextOverflow: "ellipsis",
      labelText: (d: { id: string; data?: { label?: string } }) =>
        d.data?.label ?? String(d.id),
    },
    state: BASE_NODE_STATE,
  };
}

export function G6LensLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const lensRef = useRef<LensId>("glide");
  const switchingRef = useRef(false);
  /** Canonical per-node position for the active locked lens. The live
   * forceX/forceY springs read this Map every tick. */
  const anchorsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const fieldTuningRef = useRef<FieldTuning>(DEFAULT_FIELD_TUNING);
  const layoutTuningsRef = useRef<LayoutTunings>(DEFAULT_LAYOUT_TUNINGS);
  /**
   * Bumped every time a new layout pass starts (initial mount, or a lens
   * switch). Guards against a stale async settle finishing after a newer one.
   */
  const layoutGenRef = useRef(0);

  const [lens, setLens] = useState<LensId>("glide");
  const [note, setNote] = useState(LENSES[0].note);
  const [switching, setSwitching] = useState(false);
  const [fieldTuning, setFieldTuning] = useState<FieldTuning>(DEFAULT_FIELD_TUNING);
  const [layoutTunings, setLayoutTunings] =
    useState<LayoutTunings>(DEFAULT_LAYOUT_TUNINGS);
  const [fontId, setFontId] = useState<NodeFontId>(DEFAULT_CIRCLE_NODE_FONT);

  const pickFont = (id: NodeFontId) => {
    setFontId(id);
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.setNode(lensNodeOptions(id));
  };

  /** Re-arm the live spring field with new knobs — keeps current anchors,
   * never re-runs the structural layout. No-op on Glide / before first lock. */
  const retuneField = (next: FieldTuning) => {
    fieldTuningRef.current = next;
    setFieldTuning(next);
    const graph = graphRef.current;
    if (!graph || graph.destroyed || lensRef.current === "glide") return;
    if (anchorsRef.current.size === 0) return;
    try {
      graph.stopLayout();
    } catch {
      /* ok */
    }
    clearHardPins(graph);
    graph.setLayout(anchoredFieldLayout(anchorsRef.current, next));
    graph.layout().catch(() => {});
  };

  /** Re-run the active lens's structural layout with new knobs, then
   * (for locked lenses) re-capture anchors and re-engage the spring field. */
  const retuneLayout = async (next: LayoutTunings) => {
    layoutTuningsRef.current = next;
    setLayoutTunings(next);
    const graph = graphRef.current;
    if (!graph || graph.destroyed || switchingRef.current) return;
    const active = lensRef.current;
    const myGen = ++layoutGenRef.current;

    switchingRef.current = true;
    setSwitching(true);
    try {
      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }

      if (active === "glide") {
        clearHardPins(graph);
        graph.setLayout(glideLayout(next));
        await graph.layout();
        await settleView(graph);
        return;
      }

      graph.setLayout(structuralLayoutForLens(active, next));
      await graph.layout();
      if (graph.destroyed || layoutGenRef.current !== myGen) return;
      await settleView(graph);
      if (graph.destroyed || layoutGenRef.current !== myGen) return;
      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }
      captureAnchors(graph, anchorsRef.current);
      clearHardPins(graph);
      graph.setLayout(
        anchoredFieldLayout(anchorsRef.current, fieldTuningRef.current),
      );
      await graph.layout();
    } catch {
      /* destroyed / aborted */
    } finally {
      switchingRef.current = false;
      setSwitching(false);
    }
  };

  useEffect(() => {
    if (!containerRef.current) return;

    ensureContainsEdgeRegistered();
    ensureStructuralDagreRegistered();

    let cancelled = false;
    lensRef.current = "glide";
    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      padding: 28,
      data: createLensLabGraph(),
      node: lensNodeOptions(DEFAULT_CIRCLE_NODE_FONT),
      edge: EDGE_OPTIONS,
      layout: layoutForLens(
        "glide",
        anchorsRef.current,
        fieldTuningRef.current,
        layoutTuningsRef.current,
      ),
      behaviors: behaviorsForLens("glide"),
      animation: true,
    });

    graphRef.current = graph;
    // @ts-expect-error browser-verification hook
    window.__lensLabGraph = graph;

    // Locked lenses use drag-element-force with fixed:false — on release the
    // pin clears, but alpha may already be cooling. A gentle reheat gives
    // the home springs enough energy to finish settling without a jump.
    graph.on("node:dragend", () => {
      if (lensRef.current === "glide") return;
      try {
        // @ts-expect-error layout controller is not on the public Graph type
        const layouts = graph.context?.layout?.getLayoutInstance?.() ?? [];
        for (const layout of layouts as Array<{
          instance?: {
            simulation?: {
              alpha: (a: number) => { restart: () => void };
              alphaTarget: (a: number) => unknown;
            };
          };
          simulation?: {
            alpha: (a: number) => { restart: () => void };
            alphaTarget: (a: number) => unknown;
          };
        }>) {
          const sim = layout.instance?.simulation ?? layout.simulation;
          if (!sim) continue;
          sim.alphaTarget(0);
          sim.alpha(0.35).restart();
        }
      } catch {
        /* ok */
      }
    });

    const myGen = ++layoutGenRef.current;
    graph
      .render()
      .then(() => {
        if (cancelled || graph.destroyed) return;
        return settleView(graph);
      })
      .then(() => {
        if (cancelled || graph.destroyed || layoutGenRef.current !== myGen) return;
        anchorsRef.current.clear();
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      graphRef.current = null;
      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }
      try {
        graph.destroy();
      } catch {
        /* ok */
      }
    };
  }, []);

  const applyLens = async (next: LensId) => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || switchingRef.current) return;
    if (next === lensRef.current) return;

    switchingRef.current = true;
    setSwitching(true);
    lensRef.current = next;
    setLens(next);
    const meta = LENSES.find((l) => l.id === next);
    if (meta) setNote(meta.note);

    const myGen = ++layoutGenRef.current;

    try {
      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }

      graph.setBehaviors(
        behaviorsForLens(next) as Parameters<Graph["setBehaviors"]>[0],
      );

      if (next === "glide") {
        anchorsRef.current.clear();
        clearHardPins(graph);
        graph.setLayout(
          layoutForLens(
            "glide",
            anchorsRef.current,
            fieldTuningRef.current,
            layoutTuningsRef.current,
          ),
        );
        await graph.layout();
        await settleView(graph);
        return;
      }

      // 1) Structural pass — places the graph (dagre / radial / cluster settle).
      graph.setLayout(
        structuralLayoutForLens(next, layoutTuningsRef.current),
      );
      await graph.layout();
      if (graph.destroyed || layoutGenRef.current !== myGen) return;
      await settleView(graph);
      if (graph.destroyed || layoutGenRef.current !== myGen) return;

      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }

      // 2) Capture those positions as springs' homes, clear hard pins, then
      //    hand the graph to a live d3-force field that springs back to them.
      captureAnchors(graph, anchorsRef.current);
      clearHardPins(graph);
      graph.setLayout(
        anchoredFieldLayout(anchorsRef.current, fieldTuningRef.current),
      );
      await graph.layout();
    } catch {
      /* destroyed / aborted mid-switch */
    } finally {
      switchingRef.current = false;
      setSwitching(false);
    }
  };

  const locked = lens !== "glide";

  return (
    <div className="g6-lab">
      <header className="g6-lab__chrome">
        <p className="g6-lab__eyebrow">Design lab</p>
        <h1 className="g6-lab__title">G6 lensing — layout lenses</h1>
        <p className="g6-lab__lede">
          One realistic ~20-node knowledge graph. Each lens is a layout
          algorithm applied to the whole graph — every edge stays drawn
          (straight lines), with no filtering or dimming.{" "}
          <strong>Glide</strong> is free layout (loose physics, you own
          placement). Every other lens runs a structural layout, then a live{" "}
          <strong>d3-force</strong> field with soft springs back to those
          anchors — drag tugs neighbors for real; release and the field
          settles home.
        </p>

        <div className="g6-lab__controls">
          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Lens</span>
            {LENSES.map((l) => (
              <button
                key={l.id}
                type="button"
                className={
                  "g6-lab__chip" + (lens === l.id ? " g6-lab__chip--active" : "")
                }
                onClick={() => void applyLens(l.id)}
                disabled={switching}
              >
                {l.label}
              </button>
            ))}
          </div>

          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Label</span>
            {CIRCLE_NODE_FONT_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={
                  "g6-lab__chip" + (fontId === id ? " g6-lab__chip--active" : "")
                }
                onClick={() => pickFont(id)}
                title={NODE_FONTS[id].note}
                style={{ fontFamily: NODE_FONTS[id].family }}
              >
                {NODE_FONTS[id].label}
              </button>
            ))}
          </div>

          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Layout</span>
            {lens === "nested" || lens === "cascade" ? (
              <>
                <label className="g6-lab__slider">
                  Node sep {layoutTunings[lens].nodesep}
                  <input
                    type="range"
                    min={32}
                    max={120}
                    step={2}
                    value={layoutTunings[lens].nodesep}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        [lens]: {
                          ...layoutTuningsRef.current[lens],
                          nodesep: Number(e.target.value),
                        },
                      })
                    }
                    title="Spacing between nodes in the same rank"
                  />
                </label>
                <label className="g6-lab__slider">
                  Rank sep {layoutTunings[lens].ranksep}
                  <input
                    type="range"
                    min={56}
                    max={160}
                    step={2}
                    value={layoutTunings[lens].ranksep}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        [lens]: {
                          ...layoutTuningsRef.current[lens],
                          ranksep: Number(e.target.value),
                        },
                      })
                    }
                    title="Spacing between ranks (layers)"
                  />
                </label>
              </>
            ) : null}
            {lens === "cluster" ? (
              <>
                <label className="g6-lab__slider">
                  Link {layoutTunings.cluster.linkDist}
                  <input
                    type="range"
                    min={110}
                    max={280}
                    step={5}
                    value={layoutTunings.cluster.linkDist}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        cluster: {
                          ...layoutTuningsRef.current.cluster,
                          linkDist: Number(e.target.value),
                        },
                      })
                    }
                    title="Ideal edge length for the cluster settle"
                  />
                </label>
                <label className="g6-lab__slider">
                  Charge {layoutTunings.cluster.charge}
                  <input
                    type="range"
                    min={160}
                    max={650}
                    step={10}
                    value={layoutTunings.cluster.charge}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        cluster: {
                          ...layoutTuningsRef.current.cluster,
                          charge: Number(e.target.value),
                        },
                      })
                    }
                    title="How hard nodes push apart (many-body)"
                  />
                </label>
              </>
            ) : null}
            {lens === "radial" ? (
              <>
                <label className="g6-lab__slider">
                  Radius {layoutTunings.radial.unitRadius}
                  <input
                    type="range"
                    min={90}
                    max={240}
                    step={5}
                    value={layoutTunings.radial.unitRadius}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        radial: {
                          ...layoutTuningsRef.current.radial,
                          unitRadius: Number(e.target.value),
                        },
                      })
                    }
                    title="Distance between radial rings"
                  />
                </label>
                <label className="g6-lab__slider">
                  Link {layoutTunings.radial.linkDistance}
                  <input
                    type="range"
                    min={100}
                    max={240}
                    step={5}
                    value={layoutTunings.radial.linkDistance}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        radial: {
                          ...layoutTuningsRef.current.radial,
                          linkDistance: Number(e.target.value),
                        },
                      })
                    }
                    title="Ideal edge length in the radial pass"
                  />
                </label>
              </>
            ) : null}
            {lens === "glide" ? (
              <>
                <label className="g6-lab__slider">
                  Link {layoutTunings.glide.linkDist}
                  <input
                    type="range"
                    min={140}
                    max={360}
                    step={5}
                    value={layoutTunings.glide.linkDist}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        glide: {
                          ...layoutTuningsRef.current.glide,
                          linkDist: Number(e.target.value),
                        },
                      })
                    }
                    title="Ideal edge length for Glide Loose"
                  />
                </label>
                <label className="g6-lab__slider">
                  Link strength {layoutTunings.glide.linkStrength.toFixed(2)}
                  <input
                    type="range"
                    min={0.04}
                    max={0.3}
                    step={0.01}
                    value={layoutTunings.glide.linkStrength}
                    disabled={switching}
                    onChange={(e) =>
                      void retuneLayout({
                        ...layoutTuningsRef.current,
                        glide: {
                          ...layoutTuningsRef.current.glide,
                          linkStrength: Number(e.target.value),
                        },
                      })
                    }
                    title="How strongly connected nodes enforce their ideal distance"
                  />
                </label>
              </>
            ) : null}
          </div>

          {locked ? (
            <div className="g6-lab__control-row">
              <span className="g6-lab__control-label">Field</span>
              <label className="g6-lab__slider">
                Tug {fieldTuning.tug.toFixed(2)}
                <input
                  type="range"
                  min={0.1}
                  max={0.5}
                  step={0.01}
                  value={fieldTuning.tug}
                  onChange={(e) =>
                    retuneField({
                      ...fieldTuningRef.current,
                      tug: Number(e.target.value),
                    })
                  }
                  title="How hard neighbors follow a drag (link strength)"
                />
              </label>
              <label className="g6-lab__slider">
                Snap {fieldTuning.snap.toFixed(2)}
                <input
                  type="range"
                  min={0.4}
                  max={0.95}
                  step={0.01}
                  value={fieldTuning.snap}
                  onChange={(e) =>
                    retuneField({
                      ...fieldTuningRef.current,
                      snap: Number(e.target.value),
                    })
                  }
                  title="How hard the field pulls home after release (anchor springs)"
                />
              </label>
              <label className="g6-lab__slider">
                Damping {fieldTuning.damping.toFixed(2)}
                <input
                  type="range"
                  min={0.2}
                  max={0.55}
                  step={0.01}
                  value={fieldTuning.damping}
                  onChange={(e) =>
                    retuneField({
                      ...fieldTuningRef.current,
                      damping: Number(e.target.value),
                    })
                  }
                  title="Stickiness on the way home — higher settles with less wobble"
                />
              </label>
            </div>
          ) : null}
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-edge-layout">Edge layouts</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-physics">Physics</a>
        </p>
      </header>

      <p className="g6-lab__note">{note}</p>
      <div
        className="g6-lab__stage"
        style={{ height: 680 }}
        ref={containerRef}
      />
    </div>
  );
}
