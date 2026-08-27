import { useEffect, useRef, useState } from "react";
import { Graph, GraphEvent, type EdgeData, type NodeData } from "@antv/g6";
import { gray } from "@radix-ui/colors";
import { BASE_NODE_STATE, NODE_FONTS } from "../g6/graphOptions";
import {
  ensureLinkageEdgeRegistered,
  LINKAGE_EDGE,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import {
  AMBIENT_LOD_EDGE_COUNT,
  AMBIENT_LOD_GRAPH_VERSION,
  AMBIENT_LOD_LANDMARKS,
  AMBIENT_LOD_NODE_COUNT,
  createAmbientLodGraph,
  importanceOf,
  isLandmark,
  labelOf,
} from "./ambientLodData";
import {
  bandForZoom,
  importanceFloor,
  isScreenReadable,
  lodOpacity,
  MID_ZOOM,
  NEAR_ZOOM,
  staticLabelFontSize,
  staticNodeSize,
  type LodBand,
} from "./ambientLodThresholds";
import {
  clearLabelMeasureCache,
  fitLabelFontSize,
  labelBoxWidth,
} from "./nodeLabelFit";
import "../g6/g6Lab.css";
import "./AmbientLodLabPage.css";

/**
 * Ambient LOD (handoff §4): one fixed layout per `graph_version`, continuous
 * camera, soft disclosure by importance.
 *
 * The layout is the fixture's authored x/y — it *is* the "layout cache keyed by
 * graph_version" the handoff calls for (§4.2). An earlier pass threw those away
 * and ran dagre TB + a force settle instead; on a CONTAINS star (1 root → 7
 * regions → ~90 leaves) dagre puts every leaf on one rank, which smears the map
 * ~5000px wide and ~250px tall. fitView then bottomed out at the `zoomRange`
 * floor and every glyph was 4–10px. Don't reintroduce a layout pass here: the
 * disclosure thresholds in `ambientLodThresholds` are calibrated against the
 * authored extent (fit lands ≈0.64 → landmarks ≈41px, leaves still folded away).
 */

/**
 * LOD state for style mappers. Module-level: G6 style callbacks are not closures.
 */
const lod = {
  zoom: 1,
  band: "far" as LodBand,
  endpointOpacity: new Map<string, number>(),
};

/** Step 0 instrumentation — also mirrored on window.__ambientLodDebug. */
const debug = {
  transformN: 0,
  syncN: 0,
  drawN: 0,
  bandFlips: 0,
  lastZoom: 1,
  lastLodZoom: 1,
};

const ZOOM_EPSILON = 0.008;

const INK = gray.gray12;
const PAPER = gray.gray1;
const LABEL_MIN_IMPORTANCE = 0.42;

function nodeSize(datum: NodeData) {
  return staticNodeSize(importanceOf(datum), isLandmark(datum));
}

function nodeOpacity(datum: NodeData) {
  const size = nodeSize(datum);
  if (!isScreenReadable(size, lod.zoom)) return 0;
  return lodOpacity(importanceOf(datum), lod.zoom, isLandmark(datum));
}

function edgeOpacity(datum: EdgeData, getLandmark: (id: string) => boolean) {
  const s = String(datum.source);
  const t = String(datum.target);
  if (lod.band === "far") {
    return getLandmark(s) && getLandmark(t) ? 0.45 : 0;
  }
  const so = lod.endpointOpacity.get(s) ?? 0;
  const to = lod.endpointOpacity.get(t) ?? 0;
  const weak = Math.min(so, to);
  if (weak < 0.04) return 0;
  return weak * (lod.band === "mid" ? 0.55 : 0.75);
}

function labelOpacityFor(datum: NodeData, bodyOpacity: number) {
  if (bodyOpacity < 0.28) return 0;
  const size = nodeSize(datum);
  if (!isScreenReadable(size * 1.15, lod.zoom)) return 0;
  if (isLandmark(datum)) return Math.min(1, bodyOpacity);
  if (importanceOf(datum) < LABEL_MIN_IMPORTANCE) {
    if (lod.zoom < NEAR_ZOOM * 0.88) return 0;
    const t = (lod.zoom - NEAR_ZOOM * 0.88) / 0.25;
    return Math.min(1, bodyOpacity * Math.max(0, Math.min(1, t)));
  }
  if (lod.zoom < MID_ZOOM * 0.8) return 0;
  const t = (lod.zoom - MID_ZOOM * 0.8) / 0.25;
  return Math.min(1, bodyOpacity * Math.max(0, Math.min(1, t)));
}

/** Largest font that keeps the longest word inside the disc. */
function fittedLabelFontSize(datum: NodeData) {
  const diameter = nodeSize(datum);
  return fitLabelFontSize(
    labelOf(datum),
    diameter,
    staticLabelFontSize(diameter),
    NODE_FONTS.plexCondensed.family,
  );
}

function buildNodeStyle() {
  return {
    size: (datum: NodeData) => nodeSize(datum),
    fill: INK,
    stroke: INK,
    lineWidth: 1,
    opacity: (datum: NodeData) => nodeOpacity(datum),
    labelText: (datum: NodeData) => labelOf(datum),
    labelPlacement: "center" as const,
    labelFill: PAPER,
    labelOpacity: (datum: NodeData) =>
      labelOpacityFor(datum, nodeOpacity(datum)),
    labelFontFamily: NODE_FONTS.plexCondensed.family,
    labelFontSize: (datum: NodeData) => fittedLabelFontSize(datum),
    labelFontWeight: 600 as const,
    labelWordWrap: true,
    labelMaxWidth: (datum: NodeData) => labelBoxWidth(nodeSize(datum)),
    labelMaxLines: 2,
    cursor: "grab" as const,
  };
}

function buildEdgeStyle(getLandmark: (id: string) => boolean) {
  return {
    stroke: INK,
    lineWidth: (datum: EdgeData) => {
      const kind = linkageEdgeKind(datum);
      return kind === "leadsto" ? 1.35 : 1.05;
    },
    opacity: (datum: EdgeData) => edgeOpacity(datum, getLandmark),
    labelText: "",
    endArrow: false,
  };
}

function countReadable() {
  let n = 0;
  for (const opacity of lod.endpointOpacity.values()) {
    if (opacity >= 0.08) n += 1;
  }
  return n;
}

function refreshEndpointOpacities(graph: Graph) {
  lod.endpointOpacity.clear();
  for (const node of graph.getNodeData()) {
    lod.endpointOpacity.set(String(node.id), nodeOpacity(node));
  }
}

/**
 * `getZoom()` reaches into the viewport, which G6 tears down slightly before it
 * flips `destroyed` — and it can still emit AFTER_TRANSFORM in that window.
 * Returns null when the camera is not readable.
 */
function readZoom(graph: Graph): number | null {
  try {
    const z = graph.getZoom();
    return Number.isFinite(z) ? z : null;
  } catch {
    return null;
  }
}

function publishDebug() {
  (
    window as Window & { __ambientLodDebug?: typeof debug }
  ).__ambientLodDebug = { ...debug };
}

export function AmbientLodLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const syncLodRef = useRef<(force?: boolean) => Promise<void>>(async () => {});
  const [graphReady, setGraphReady] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [visibleCount, setVisibleCount] = useState(0);
  const [band, setBand] = useState<LodBand>("far");
  const [seedNote, setSeedNote] = useState("Seeding…");
  const [pipe, setPipe] = useState({
    transformN: 0,
    syncN: 0,
    drawN: 0,
    bandFlips: 0,
    lastLodZoom: 1,
  });

  const bumpZoom = (factor: number) => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const next = Math.max(0.25, Math.min(3, graph.getZoom() * factor));
    void graph.zoomTo(next, { duration: 280 }).then(() =>
      syncLodRef.current(true),
    );
  };

  useEffect(() => {
    if (!containerRef.current) return;
    ensureLinkageEdgeRegistered();
    let cancelled = false;
    /**
     * This mount's graph. Listeners must read `self`, never `graphRef.current`:
     * under StrictMode the ref already points at the *next* mount's graph while
     * this one is still emitting, and reading a half-built graph threw
     * `getZoom` of undefined.
     */
    let self: Graph | null = null;
    lod.zoom = 1;
    lod.band = "far";
    lod.endpointOpacity.clear();
    debug.transformN = 0;
    debug.syncN = 0;
    debug.drawN = 0;
    debug.bandFlips = 0;
    debug.lastZoom = 1;
    debug.lastLodZoom = 1;
    publishDebug();

    const landmarkIds = new Set(AMBIENT_LOD_LANDMARKS);
    const isLandmarkId = (id: string) => landmarkIds.has(id);

    const pushPipe = () => {
      setPipe({
        transformN: debug.transformN,
        syncN: debug.syncN,
        drawN: debug.drawN,
        bandFlips: debug.bandFlips,
        lastLodZoom: debug.lastLodZoom,
      });
      publishDebug();
    };

    /**
     * Disclosure sync — redraw when zoom moves (soft fade) or band flips.
     * Pan-only transforms (zoom unchanged) skip draw.
     */
    const syncLod = async (force = false) => {
      const graph = self;
      if (cancelled || !graph || graph.destroyed) return;
      debug.syncN += 1;
      const z = Math.max(0.05, readZoom(graph) ?? 1);
      debug.lastZoom = z;
      const nextBand = bandForZoom(z);
      const bandChanged = nextBand !== lod.band;
      const zoomChanged = Math.abs(z - lod.zoom) >= ZOOM_EPSILON;

      if (bandChanged) debug.bandFlips += 1;

      lod.zoom = z;
      lod.band = nextBand;
      debug.lastLodZoom = z;
      setZoom(z);
      setBand(nextBand);

      if (!force && !zoomChanged && !bandChanged) {
        publishDebug();
        return;
      }

      refreshEndpointOpacities(graph);
      setVisibleCount(countReadable());
      debug.drawN += 1;
      pushPipe();
      // `draw()` alone re-renders but reuses each element's memoised computed
      // style, so the opacity mappers keep returning their construction-time
      // values (every glyph frozen at lod.zoom = 1) while the status text moved
      // on — the "status lies about what is painted" bug. Re-setting the element
      // specs marks the styles dirty so the mappers actually re-run.
      graph.setNode({
        type: "circle",
        style: buildNodeStyle(),
        state: BASE_NODE_STATE,
      });
      graph.setEdge({
        type: LINKAGE_EDGE,
        style: buildEdgeStyle(isLandmarkId) as never,
        animation: false,
      });
      await graph.draw().catch(() => {});
    };
    syncLodRef.current = syncLod;

    let lodRaf = 0;
    const scheduleSyncFromTransform = () => {
      if (lodRaf) return;
      lodRaf = requestAnimationFrame(() => {
        lodRaf = 0;
        void syncLod(false);
      });
    };

    // Authored x/y is the frozen layout for this graph_version — no layout pass.
    const data = createAmbientLodGraph();

    const graph = new Graph({
      container: containerRef.current,
      data,
      animation: false,
      padding: [40, 36, 40, 36],
      zoomRange: [0.25, 3],
      node: {
        type: "circle",
        style: buildNodeStyle(),
        state: BASE_NODE_STATE,
      },
      edge: {
        type: LINKAGE_EDGE,
        style: buildEdgeStyle(isLandmarkId) as never,
        animation: false,
      },
      behaviors: [
        "drag-canvas",
        {
          type: "zoom-canvas",
          // 1.15 traversed the whole zoom range in ~12 wheel notches.
          sensitivity: 0.28,
          // Backup path — AFTER_TRANSFORM is primary for wheel reactivity.
          onFinish: () => {
            void syncLod(true);
          },
        },
        "drag-element",
        "click-select",
      ],
    });

    self = graph;
    graphRef.current = graph;
    (
      window as Window & { __ambientLodGraph?: Graph | null }
    ).__ambientLodGraph = graph;

    const onTransform = () => {
      if (cancelled || !self || self.destroyed) return;
      const raw = readZoom(self);
      if (raw === null) return;
      debug.transformN += 1;
      const z = Math.max(0.05, raw);
      // Pan-only: camera moved, zoom did not — skip disclosure work + React churn.
      if (Math.abs(z - lod.zoom) < ZOOM_EPSILON) {
        publishDebug();
        return;
      }
      scheduleSyncFromTransform();
    };
    graph.on(GraphEvent.AFTER_TRANSFORM, onTransform);

    /** True once this mount is torn down — StrictMode remounts destroy `graph`. */
    const dead = () => cancelled || graph.destroyed;

    graph
      .render()
      .then(async () => {
        if (dead()) return;
        setSeedNote("Fitting view…");
        // Fit *is* the ambient overview zoom. Don't clamp it down afterwards:
        // bandForZoom decides whether that reads as "far", not a second zoomTo.
        await graph.fitView({ when: "overflow", direction: "both" }, false);
        if (dead()) return;
        await syncLod(true);
        if (dead()) return;
        setSeedNote("");
        setGraphReady(true);
        // Text measured before the condensed face lands is measured against the
        // fallback, so drop the cache and re-fit once fonts settle.
        void document.fonts?.ready.then(() => {
          if (dead()) return;
          clearLabelMeasureCache();
          void syncLod(true);
        });
      })
      .catch((err) => {
        if (dead()) return;
        console.error("[ambient-lod] init failed", err);
        setSeedNote("Init failed — see console");
      });

    return () => {
      cancelled = true;
      self = null;
      if (lodRaf) cancelAnimationFrame(lodRaf);
      if (graphRef.current === graph) graphRef.current = null;
      const w = window as Window & { __ambientLodGraph?: Graph | null };
      if (w.__ambientLodGraph === graph) w.__ambientLodGraph = null;
      // Detach before destroy: an in-flight AFTER_TRANSFORM otherwise reaches a
      // half-torn-down graph and throws `getZoom` of undefined on remount.
      graph.off(GraphEvent.AFTER_TRANSFORM, onTransform);
      graph.destroy();
    };
  }, []);

  return (
    <main className="ambient-lod">
      <header className="ambient-lod__header">
        <div>
          <p className="ambient-lod__eyebrow">Screen 1 · Ambient Canvas</p>
          <h1>LOD lab</h1>
          <p className="ambient-lod__lede">
            Reactive disclosure: wheel / pinch / buttons move <code>lod.zoom</code>{" "}
            with the camera and redraw opacities when zoom changes (status shows{" "}
            <code>t/s/d/b</code> pipeline counters). One frozen layout —
            the fixture's authored x/y, no layout pass — plus static size tiers,
            so zoom only ever changes opacity and labels. Opens at fitView in the{" "}
            <strong>far</strong> band: landmarks and top hubs readable, leaves
            folded away until you come closer.
          </p>
          <p className="ambient-lod__nav">
            <a href="#/explorations">Explorations</a>
            {" · "}
            <a href="#/explorations/canvas-linkage">Canvas linkage</a>
            {" · "}
            <a href="#/explorations/ledger-feed">Ledger feed</a>
          </p>
        </div>
        <aside className="ambient-lod__note">
          <span>Fixture</span>
          <strong>
            V{AMBIENT_LOD_GRAPH_VERSION} · {AMBIENT_LOD_NODE_COUNT} nodes ·{" "}
            {AMBIENT_LOD_EDGE_COUNT} edges
          </strong>
          <p>
            {AMBIENT_LOD_LANDMARKS.length} Compass landmarks · layout frozen ·
            transform→sync→draw
          </p>
        </aside>
      </header>

      <div className="ambient-lod__toolbar">
        <p className="ambient-lod__status" role="status">
          {graphReady ? (
            <>
              Band <strong>{band}</strong>
              {" · "}
              zoom {zoom.toFixed(2)}
              {" · "}
              lod {pipe.lastLodZoom.toFixed(2)}
              {" · "}
              readable {visibleCount}/{AMBIENT_LOD_NODE_COUNT}
              {" · "}
              floor {importanceFloor(zoom).toFixed(2)}
              {" · "}
              t{pipe.transformN}/s{pipe.syncN}/d{pipe.drawN}/b{pipe.bandFlips}
            </>
          ) : (
            seedNote || "Loading…"
          )}
        </p>
        <div className="ambient-lod__zoom-actions">
          <button
            type="button"
            disabled={!graphReady}
            onClick={() => bumpZoom(1 / 1.35)}
          >
            Zoom out
          </button>
          <button
            type="button"
            disabled={!graphReady}
            onClick={() => bumpZoom(1.35)}
          >
            Zoom in
          </button>
        </div>
      </div>

      <section className="ambient-lod__stage-shell">
        <div className="ambient-lod__stage" ref={containerRef} />
      </section>
    </main>
  );
}
