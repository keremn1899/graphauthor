import { useEffect, useRef, useState } from "react";
import {
  Graph,
  GraphEvent,
  type EdgeData,
  type NodeData,
} from "@antv/g6";
import { Renderer as CanvasRenderer } from "@antv/g-canvas";
import { gray } from "@radix-ui/colors";
import { BASE_NODE_STATE, NODE_FONTS } from "../g6/graphOptions";
import { FORCE_PRESETS } from "../g6/forcePresets";
import {
  ensureLinkageEdgeRegistered,
  LINKAGE_EDGE,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import {
  AMBIENT_LOD_LANDMARKS,
  AMBIENT_LOD_NODE_COUNT,
  createAmbientLodGraph,
  isLandmark,
  labelOf,
} from "./ambientLodData";
import {
  bandWithHysteresis,
  FAR_ZOOM,
  importanceFloor,
  type LodBand,
} from "./ambientLodThresholds";
import { labelBoxWidth } from "./nodeLabelFit";
import {
  buildCoarsenModel,
  continuousResolver,
  massDiameter,
  type CoarsenModel,
  type ContinuousResolver,
} from "./ambientMassModel";
import {
  authoredLayout,
  tryWasmForceLayout,
  type PerfLayoutEngine,
} from "./ambientPerfLayout";
import {
  bottleneckHint,
  DEFAULT_BOTTLENECK,
  runBottleneckBench,
  subsampleGraph,
  type BottleneckConfig,
  type BottleneckReport,
  type NodeCap,
} from "./ambientPerfBench";
import "../g6/g6Lab.css";
import "./AmbientPerfLabPage.css";

/**
 * Performance-first ambient lab — LOD is constrained by the cheap path.
 *
 * Hard rules:
 *  - Layout seed once (WASM force → else G6 worker d3-force → authored)
 *  - Soft Glide Loose stays on for basic yield (drag / link tug) — not LOD physics
 *  - Every pan/zoom frame: camera transform only
 *  - Mass LOD: one update + draw after zoom settles
 *  - Canvas2D · DPR 2
 *  - No optimize-viewport-transform: it hid labels on pan and could leave
 *    elements stuck `visibility:hidden` after zoom + draw (graph “vanished”).
 */

const INK = gray.gray12;
const PAPER = gray.gray1;
const ZOOM_EPSILON = 0.008;
const MASS_UNIT_DIAMETER = 34;
const LANDMARK_BOOST = 1.2;
const MIN_LEVEL = 6;
const FOLD_WINDOW = 0.22;
const DETAIL_ZOOM_RATIO = 4;
const ZOOM_SETTLE_MS = 120;
/** Font ∝ graph-space diameter — scale-invariant wrap while camera zooms. */
const LABEL_FONT_PER_DIAMETER = 0.2;

const view = {
  /** Absolute G6 camera zoom. */
  zoom: 1,
  /** Zoom at fitView — LOD bands are relative to this so WASM extents still work. */
  fitZoom: 1,
  band: "far" as LodBand,
};

/** Absolute camera zoom → LOD zoom where fitView lands on FAR_ZOOM. */
function lodZoomOf(absoluteZoom: number) {
  const fit = Math.max(0.05, view.fitZoom);
  return (absoluteZoom / fit) * FAR_ZOOM;
}

function num(datum: NodeData | EdgeData, key: string, fallback = 0) {
  const value = Number(
    (datum.data as Record<string, unknown> | undefined)?.[key],
  );
  return Number.isFinite(value) ? value : fallback;
}

function diameterOf(datum: NodeData) {
  return massDiameter(
    num(datum, "_p") * num(datum, "_m", 1),
    MASS_UNIT_DIAMETER,
    isLandmark(datum),
    LANDMARK_BOOST,
  );
}

function buildNodeStyle(labels: boolean) {
  return {
    size: (datum: NodeData) => diameterOf(datum),
    fill: INK,
    stroke: INK,
    lineWidth: 1,
    opacity: (datum: NodeData) => num(datum, "_op"),
    labelText: (datum: NodeData) => (labels ? labelOf(datum) : ""),
    labelPlacement: "center" as const,
    labelFill: PAPER,
    labelOpacity: (datum: NodeData) => (labels ? num(datum, "_lop") : 0),
    labelFontFamily: NODE_FONTS.plexCondensed.family,
    labelFontSize: (datum: NodeData) =>
      Math.max(0.1, diameterOf(datum) * LABEL_FONT_PER_DIAMETER),
    labelFontWeight: 600 as const,
    labelWordWrap: true,
    labelMaxWidth: (datum: NodeData) => labelBoxWidth(diameterOf(datum)),
    labelMaxLines: 2,
    cursor: "default" as const,
  };
}

function buildEdgeStyle() {
  return {
    stroke: INK,
    lineWidth: (datum: EdgeData) =>
      linkageEdgeKind(datum) === "leadsto" ? 1.35 : 1.05,
    opacity: (datum: EdgeData) => num(datum, "_ep"),
    labelText: "",
    endArrow: false,
    pointerEvents: "none" as const,
  };
}

function labelOpacityFor(
  datum: NodeData,
  bodyOpacity: number,
  absoluteZoom: number,
) {
  if (bodyOpacity < 0.28) return 0;
  const screenDiameter = diameterOf(datum) * absoluteZoom;
  if (screenDiameter <= 13) return 0;
  return Math.min(bodyOpacity, (screenDiameter - 13) / 9);
}

function massLevelForZoom(model: CoarsenModel, absoluteZoom: number) {
  const ratio = absoluteZoom / Math.max(0.05, view.fitZoom);
  const levelTop = (model.nodeCount + 1) / (1 - FOLD_WINDOW);
  return Math.max(
    MIN_LEVEL,
    Math.min(
      levelTop,
      levelTop * Math.pow(ratio / DETAIL_ZOOM_RATIO, 2),
    ),
  );
}

function readZoom(graph: Graph): number | null {
  try {
    const z = graph.getZoom();
    return Number.isFinite(z) ? z : null;
  } catch {
    return null;
  }
}

function workerForceLayoutOptions() {
  return {
    type: "d3-force" as const,
    enableWorker: true,
    animation: false,
    link: { distance: 260, strength: 0.07, iterations: 1 },
    manyBody: false,
    collide: { radius: 36, strength: 1, iterations: 2 },
    center: { strength: 0.05 },
    alphaDecay: 0.028,
    velocityDecay: 0.48,
  };
}

/** Soft live physics after seed — Glide Loose, link-only. */
function glideLooseLive() {
  const base = FORCE_PRESETS["glide-loose"].layout;
  return {
    ...base,
    enableWorker: true,
    animation: true,
    collide: {
      radius: 36,
      strength: 1,
      iterations: 2,
    },
  };
}

export function AmbientPerfLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const syncLodRef = useRef<(force?: boolean) => Promise<void>>(
    async () => {},
  );
  const benchRef = useRef<() => Promise<void>>(async () => {});
  const configRef = useRef<BottleneckConfig>(DEFAULT_BOTTLENECK);
  const [config, setConfig] = useState<BottleneckConfig>(DEFAULT_BOTTLENECK);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState("Preparing layout…");
  const [zoom, setZoom] = useState(1);
  const [band, setBand] = useState<LodBand>("far");
  const [visibleCount, setVisibleCount] = useState(0);
  const [graphCounts, setGraphCounts] = useState({ nodes: 0, edges: 0 });
  const [engine, setEngine] = useState<PerfLayoutEngine | "pending">(
    "pending",
  );
  const [layoutMs, setLayoutMs] = useState(0);
  const [pipe, setPipe] = useState({
    transformN: 0,
    syncN: 0,
    drawN: 0,
    bandFlips: 0,
  });
  const [perfHud, setPerfHud] = useState({
    fps: 0,
    drawMs: 0,
    syncMs: 0,
  });
  const [benchNote, setBenchNote] = useState("");
  const [benchReport, setBenchReport] = useState<BottleneckReport | null>(
    null,
  );
  const [benchBusy, setBenchBusy] = useState(false);

  configRef.current = config;

  const setConfigField = <K extends keyof BottleneckConfig>(
    key: K,
    value: BottleneckConfig[K],
  ) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const bumpZoom = (factor: number) => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const next = Math.max(0.2, Math.min(4, graph.getZoom() * factor));
    void graph.zoomTo(next, false).then(() => syncLodRef.current(true));
  };

  useEffect(() => {
    if (!containerRef.current) return;
    ensureLinkageEdgeRegistered();
    let cancelled = false;
    let self: Graph | null = null;
    let zoomSettleTimer = 0;
    const landmarkIds = new Set(AMBIENT_LOD_LANDMARKS);
    const isLandmarkId = (id: string) => landmarkIds.has(id);
    const cfg = config;

    setReady(false);
    setBenchNote("");
    setNote("Preparing layout…");

    const counters = {
      transformN: 0,
      syncN: 0,
      drawN: 0,
      bandFlips: 0,
    };
    const pushPipe = () => setPipe({ ...counters });

    view.zoom = 1;
    view.fitZoom = 1;
    view.band = "far";

    const sentOp = new Map<string, number>();
    const sentLop = new Map<string, number>();
    const sentEp = new Map<string, number>();
    const sentMass = new Map<string, number>();
    const sentPresence = new Map<string, number>();
    const EPS = 0.012;
    let coarsenModel: CoarsenModel | null = null;
    let resolveMass: ContinuousResolver | null = null;

    const perf = {
      frames: 0,
      fpsWindowStart: performance.now(),
      fps: 0,
      drawMs: 0,
      syncMs: 0,
    };
    let perfHudRaf = 0;
    let perfSampleRaf = 0;
    const publishPerfHud = () => {
      perfHudRaf = 0;
      setPerfHud({
        fps: perf.fps,
        drawMs: perf.drawMs,
        syncMs: perf.syncMs,
      });
    };
    const schedulePerfHud = () => {
      if (perfHudRaf) return;
      perfHudRaf = requestAnimationFrame(publishPerfHud);
    };
    const sampleFrame = () => {
      perf.frames += 1;
      const now = performance.now();
      const elapsed = now - perf.fpsWindowStart;
      if (elapsed >= 500) {
        perf.fps =
          perf.frames > 0
            ? Math.round((perf.frames * 1000) / Math.max(1, elapsed))
            : 0;
        perf.frames = 0;
        perf.fpsWindowStart = now;
        schedulePerfHud();
      }
      perfSampleRaf = requestAnimationFrame(sampleFrame);
    };
    perfSampleRaf = requestAnimationFrame(sampleFrame);
    const perfInterval = window.setInterval(() => {
      const now = performance.now();
      const elapsed = now - perf.fpsWindowStart;
      if (elapsed > 1000) {
        if (perf.frames > 0) {
          perf.fps = Math.round((perf.frames * 1000) / elapsed);
          perf.frames = 0;
          perf.fpsWindowStart = now;
        } else if (
          perf.fps !== -1 &&
          performance.now() - perf.fpsWindowStart > 1000
        ) {
          perf.fps = -1;
        }
        schedulePerfHud();
      }
    }, 1000);

    const timedDraw = async (graph: Graph) => {
      const t0 = performance.now();
      await graph.draw().catch(() => {});
      const ms = Math.round((performance.now() - t0) * 10) / 10;
      perf.drawMs = ms;
      schedulePerfHud();
      return ms;
    };
    const syncLod = async (force = false) => {
      const graph = self;
      if (cancelled || !graph || graph.destroyed) return;
      if (!cfg.lodSync && !force) return;
      const tSync = performance.now();
      counters.syncN += 1;
      const zAbs = Math.max(0.05, readZoom(graph) ?? 1);
      const zLod = lodZoomOf(zAbs);
      if (!coarsenModel || !resolveMass) return;
      const massState = resolveMass(massLevelForZoom(coarsenModel, zAbs));
      const nextBand = bandWithHysteresis(zLod, view.band);
      const bandChanged = nextBand !== view.band;
      const zoomChanged = Math.abs(zAbs - view.zoom) >= ZOOM_EPSILON;
      if (bandChanged) counters.bandFlips += 1;
      view.zoom = zAbs;
      view.band = nextBand;
      setZoom(zAbs);
      setBand(nextBand);

      if (!force && !zoomChanged && !bandChanged) {
        pushPipe();
        return;
      }

      const nodeRows: { id: string; data: Record<string, number> }[] = [];
      let readable = 0;
      for (const node of graph.getNodeData()) {
        const id = String(node.id);
        const mass = massState.mass.get(id) ?? 1;
        const presence = massState.presence.get(id) ?? 0;
        const styled = {
          ...node,
          data: { ...(node.data as object), _m: mass, _p: presence },
        } as NodeData;
        const op = presence;
        const lop = cfg.labels ? labelOpacityFor(styled, op, zAbs) : 0;
        if (op >= 0.08) readable += 1;
        const prevOp = sentOp.get(id);
        const prevLop = sentLop.get(id);
        const prevMass = sentMass.get(id);
        const prevPresence = sentPresence.get(id);
        if (
          force ||
          prevOp === undefined ||
          Math.abs(prevOp - op) > EPS ||
          prevLop === undefined ||
          Math.abs(prevLop - lop) > EPS ||
          prevMass === undefined ||
          Math.abs(prevMass - mass) > EPS ||
          prevPresence === undefined ||
          Math.abs(prevPresence - presence) > EPS
        ) {
          sentOp.set(id, op);
          sentLop.set(id, lop);
          sentMass.set(id, mass);
          sentPresence.set(id, presence);
          nodeRows.push({
            id,
            data: { _op: op, _lop: lop, _m: mass, _p: presence },
          });
        }
      }

      const edgeRows: { id: string; data: Record<string, number> }[] = [];
      if (cfg.edges) {
        for (const edge of graph.getEdgeData()) {
          const id = String(edge.id);
          const s = String(edge.source);
          const t = String(edge.target);
          let ep = 0;
          if (view.band === "far") {
            ep = isLandmarkId(s) && isLandmarkId(t) ? 0.45 : 0;
          } else {
            const so = sentOp.get(s) ?? 0;
            const to = sentOp.get(t) ?? 0;
            const weak = Math.min(so, to);
            ep =
              weak < 0.04 ? 0 : weak * (view.band === "mid" ? 0.55 : 0.75);
          }
          const prev = sentEp.get(id);
          if (force || prev === undefined || Math.abs(prev - ep) > EPS) {
            sentEp.set(id, ep);
            edgeRows.push({ id, data: { _ep: ep } });
          }
        }
      }

      if (nodeRows.length) graph.updateNodeData(nodeRows);
      if (edgeRows.length) graph.updateEdgeData(edgeRows);
      setVisibleCount(readable);
      if (nodeRows.length || edgeRows.length || force) {
        counters.drawN += 1;
        await timedDraw(graph);
      }
      perf.syncMs = Math.round((performance.now() - tSync) * 10) / 10;
      schedulePerfHud();
      pushPipe();
    };
    syncLodRef.current = syncLod;

    const scheduleSyncAfterZoom = () => {
      if (!cfg.lodSync) return;
      if (zoomSettleTimer) window.clearTimeout(zoomSettleTimer);
      zoomSettleTimer = window.setTimeout(() => {
        zoomSettleTimer = 0;
        void syncLod(false);
      }, ZOOM_SETTLE_MS);
    };

    const boot = async () => {
      setNote("WASM layout…");
      const fixture = subsampleGraph(createAmbientLodGraph(), cfg.nodeCap);
      coarsenModel = buildCoarsenModel(
        (fixture.nodes ?? []).map((node) => String(node.id)),
        (fixture.edges ?? []).map((edge) => ({
          source: String(edge.source),
          target: String(edge.target),
        })),
        `perf_${cfg.nodeCap}`,
        "degree",
      );
      resolveMass = continuousResolver(coarsenModel, {
        relativeWindow: FOLD_WINDOW,
      });
      const withEdges = cfg.edges
        ? fixture
        : { nodes: fixture.nodes, edges: [] };
      let prepared = await tryWasmForceLayout(withEdges);
      let useWorkerLayout = false;

      if (!prepared) {
        setNote("WASM unavailable — G6 worker d3-force…");
        prepared = authoredLayout(withEdges);
        useWorkerLayout = true;
      } else {
        setEngine(prepared.engine);
        setLayoutMs(prepared.layoutMs);
      }

      if (cancelled || !containerRef.current) return;

      setGraphCounts({
        nodes: prepared.data.nodes?.length ?? 0,
        edges: prepared.data.edges?.length ?? 0,
      });

      const seeded = {
        ...prepared.data,
        nodes: (prepared.data.nodes ?? []).map((n) => ({
          ...n,
          data: {
            ...(n.data as object),
            _op: 0,
            _lop: 0,
            _m: 1,
            _p: 0,
          },
        })),
        edges: (prepared.data.edges ?? []).map((e) => ({
          ...e,
          data: { ...(e.data as object), _ep: 0 },
        })),
      };

      const graph = new Graph({
        container: containerRef.current,
        data: seeded,
        animation: false,
        padding: [40, 36, 40, 36],
        zoomRange: [0.2, 4],
        devicePixelRatio: 2,
        renderer: () => new CanvasRenderer(),
        ...(useWorkerLayout ? { layout: workerForceLayoutOptions() } : {}),
        node: {
          type: "circle",
          style: buildNodeStyle(cfg.labels),
          state: BASE_NODE_STATE,
        },
        edge: {
          type: LINKAGE_EDGE,
          style: buildEdgeStyle() as never,
          animation: false,
        },
        behaviors: [
          "drag-canvas",
          {
            type: "zoom-canvas",
            sensitivity: 0.28,
            onFinish: () => {
              if (zoomSettleTimer) {
                window.clearTimeout(zoomSettleTimer);
                zoomSettleTimer = 0;
              }
              if (cfg.lodSync) void syncLod(false);
            },
          },
          ...(cfg.physics
            ? [{ type: "drag-element-force" as const, fixed: false }]
            : ["drag-element" as const]),
          "click-select",
        ],
      });

      if (cancelled) {
        graph.destroy();
        return;
      }

      self = graph;
      graphRef.current = graph;
      (
        window as Window & { __ambientPerfGraph?: Graph | null }
      ).__ambientPerfGraph = graph;

      const onTransform = () => {
        if (cancelled || !self || self.destroyed) return;
        const raw = readZoom(self);
        if (raw === null) return;
        counters.transformN += 1;
        const z = Math.max(0.05, raw);
        if (!cfg.lodSync) {
          return;
        }
        if (Math.abs(z - view.zoom) < ZOOM_EPSILON) {
          return;
        }
        scheduleSyncAfterZoom();
      };
      graph.on(GraphEvent.AFTER_TRANSFORM, onTransform);
      detachTransform = () => {
        try {
          graph.off(GraphEvent.AFTER_TRANSFORM, onTransform);
        } catch {
          /* ok */
        }
      };

      const dead = () => cancelled || graph.destroyed;

      try {
        const tLayout = performance.now();
        setNote(useWorkerLayout ? "Worker layout…" : "Rendering…");
        await graph.render();
        if (dead()) return;

        if (useWorkerLayout) {
          await new Promise<void>((r) => window.setTimeout(r, 700));
          if (dead()) return;
          setEngine("worker-d3-force");
          setLayoutMs(Math.round(performance.now() - tLayout));
        }

        try {
          graph.stopLayout();
        } catch {
          /* ok */
        }

        if (cfg.physics) {
          graph.setLayout(glideLooseLive());
          await graph.layout().catch(() => {});
          if (dead()) return;
        } else {
          try {
            graph.setLayout([]);
          } catch {
            /* ok */
          }
        }

        setNote("Fitting…");
        await graph.fitView({ when: "overflow", direction: "both" }, false);
        if (dead()) return;
        view.fitZoom = Math.max(0.05, readZoom(graph) ?? 1);
        view.zoom = view.fitZoom;
        await syncLod(true);
        if (dead()) return;
        setNote("");
        setReady(true);

        benchRef.current = async () => {
          const g = self;
          if (!g || g.destroyed) return;
          setBenchBusy(true);
          setBenchNote("Bench running…");
          try {
            const report = await runBottleneckBench({
              graph: g,
              syncLod,
              timedDraw: () => timedDraw(g),
              config: configRef.current,
            });
            setBenchReport(report);
            setBenchNote(bottleneckHint(report));
          } catch (err) {
            console.error("[ambient-perf] bench failed", err);
            setBenchNote("Bench failed — see console");
          } finally {
            setBenchBusy(false);
          }
        };
      } catch (err) {
        if (dead()) return;
        console.error("[ambient-perf] init failed", err);
        setNote("Init failed — see console");
      }
    };

    let detachTransform: (() => void) | undefined;
    void boot();

    return () => {
      cancelled = true;
      if (zoomSettleTimer) window.clearTimeout(zoomSettleTimer);
      if (perfSampleRaf) cancelAnimationFrame(perfSampleRaf);
      if (perfHudRaf) cancelAnimationFrame(perfHudRaf);
      window.clearInterval(perfInterval);
      detachTransform?.();
      const graph = self ?? graphRef.current;
      self = null;
      if (graphRef.current === graph) graphRef.current = null;
      if (graph) {
        const w = window as Window & { __ambientPerfGraph?: Graph | null };
        if (w.__ambientPerfGraph === graph) w.__ambientPerfGraph = null;
        graph.destroy();
      }
    };
  }, [config]);

  return (
    <main className="ambient-perf">
      <header className="ambient-perf__header">
        <div>
          <p className="ambient-perf__eyebrow">Screen 1 · Ambient Canvas</p>
          <h1>Perf LOD lab</h1>
          <p className="ambient-perf__lede">
            Camera-only while wheel or pinch is active. After zoom settles,
            degree-ranked children fold into absorbers and survivor area grows
            with mass. Positions stay fixed. Change <em>one</em> isolation axis,
            remount, then hit <strong>Bench</strong>.
          </p>
          <p className="ambient-perf__nav">
            <a href="#/explorations">Explorations</a>
            {" · "}
            <a href="#/explorations/ambient-lod">Ambient LOD</a>
            {" · "}
            <a href="#/explorations/ambient-mass">Mass LOD</a>
          </p>
        </div>
        <aside className="ambient-perf__note">
          <span>Layout engine</span>
          <strong>
            {engine === "pending" ? "…" : engine}
            {layoutMs > 0 ? ` · ${layoutMs}ms` : ""}
          </strong>
          <p>
            live graph {graphCounts.nodes}n / {graphCounts.edges}e · fixture{" "}
            {AMBIENT_LOD_NODE_COUNT}n · {AMBIENT_LOD_LANDMARKS.length} landmarks
          </p>
        </aside>
      </header>

      <div className="ambient-perf__iso" aria-label="Bottleneck isolation">
        <div className="ambient-perf__iso-head">
          <span>Bottleneck isolation — one change at a time</span>
          <button
            type="button"
            onClick={() => setConfig(DEFAULT_BOTTLENECK)}
          >
            Reset
          </button>
        </div>
        <div className="ambient-perf__iso-row">
          <div className="ambient-perf__ab-group" role="group" aria-label="Node cap">
            {([25, 50, 104] as NodeCap[]).map((n) => (
              <button
                key={n}
                type="button"
                className={config.nodeCap === n ? "is-active" : undefined}
                onClick={() => setConfigField("nodeCap", n)}
              >
                N={n}
              </button>
            ))}
          </div>
          <div className="ambient-perf__ab-group" role="group" aria-label="Labels">
            <button
              type="button"
              className={config.labels ? "is-active" : undefined}
              onClick={() => setConfigField("labels", true)}
            >
              Labels
            </button>
            <button
              type="button"
              className={!config.labels ? "is-active" : undefined}
              onClick={() => setConfigField("labels", false)}
            >
              No labels
            </button>
          </div>
          <div className="ambient-perf__ab-group" role="group" aria-label="Physics">
            <button
              type="button"
              className={config.physics ? "is-active" : undefined}
              onClick={() => setConfigField("physics", true)}
            >
              Physics
            </button>
            <button
              type="button"
              className={!config.physics ? "is-active" : undefined}
              onClick={() => setConfigField("physics", false)}
            >
              Frozen
            </button>
          </div>
          <div className="ambient-perf__ab-group" role="group" aria-label="LOD sync">
            <button
              type="button"
              className={config.lodSync ? "is-active" : undefined}
              onClick={() => setConfigField("lodSync", true)}
            >
              Mass LOD
            </button>
            <button
              type="button"
              className={!config.lodSync ? "is-active" : undefined}
              onClick={() => setConfigField("lodSync", false)}
              title="Camera only — no disclosure updates on zoom"
            >
              Camera only
            </button>
          </div>
          <div className="ambient-perf__ab-group" role="group" aria-label="Edges">
            <button
              type="button"
              className={config.edges ? "is-active" : undefined}
              onClick={() => setConfigField("edges", true)}
            >
              Edges
            </button>
            <button
              type="button"
              className={!config.edges ? "is-active" : undefined}
              onClick={() => setConfigField("edges", false)}
            >
              No edges
            </button>
          </div>
        </div>
      </div>

      <div className="ambient-perf__toolbar">
        <p className="ambient-perf__status" role="status">
          {ready ? (
            <>
              Band <strong>{band}</strong>
              {" · "}
              zoom {zoom.toFixed(2)}
              {" · "}
              lod {lodZoomOf(zoom).toFixed(2)}
              {" · "}
              readable {visibleCount}/{graphCounts.nodes}
              {" · "}
              floor {importanceFloor(lodZoomOf(zoom)).toFixed(2)}
              {" · "}
              <span
                className="ambient-perf__perf"
                title="fps · last draw ms · last LOD sync ms"
              >
                {perfHud.fps < 0 ? "—fps" : `${perfHud.fps}fps`}
                {" · "}
                draw {perfHud.drawMs.toFixed(1)}ms
                {" · "}
                sync {perfHud.syncMs.toFixed(1)}ms
              </span>
              {" · "}
              t{pipe.transformN}/s{pipe.syncN}/d{pipe.drawN}/b{pipe.bandFlips}
              {benchNote ? (
                <>
                  {" · "}
                  <span className="ambient-perf__bench">{benchNote}</span>
                </>
              ) : null}
            </>
          ) : (
            note || "Loading…"
          )}
        </p>
        <div className="ambient-perf__actions">
          <button
            type="button"
            disabled={!ready || benchBusy}
            onClick={() => void benchRef.current()}
          >
            {benchBusy ? "Bench…" : "Bench"}
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={() => bumpZoom(1 / 1.35)}
          >
            Zoom out
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={() => bumpZoom(1.35)}
          >
            Zoom in
          </button>
        </div>
      </div>

      {benchReport ? (
        <div className="ambient-perf__report">
          <table>
            <thead>
              <tr>
                <th>N</th>
                <th>E</th>
                <th>idle fps</th>
                <th>draw ms</th>
                <th>sync ms</th>
                <th>pan fps</th>
                <th>zoom fps</th>
                <th>flags</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{benchReport.nodeCount}</td>
                <td>{benchReport.edgeCount}</td>
                <td>{benchReport.idleFps}</td>
                <td>{benchReport.drawAvgMs}</td>
                <td>{benchReport.syncAvgMs}</td>
                <td>{benchReport.panFps}</td>
                <td>{benchReport.zoomFps}</td>
                <td>
                  {benchReport.config.labels ? "L" : "—"}
                  {benchReport.config.physics ? "P" : "—"}
                  {benchReport.config.lodSync ? "S" : "—"}
                  {benchReport.config.edges ? "E" : "—"}
                </td>
              </tr>
            </tbody>
          </table>
          <p>
            Ladder: N=25 → 50 → 104 (same flags). Then labels off, physics off,
            camera-only, no edges. Whichever jump hurts most is the bottleneck.
          </p>
        </div>
      ) : null}

      <section className="ambient-perf__stage-shell">
        <div className="ambient-perf__stage" ref={containerRef} />
      </section>
    </main>
  );
}
