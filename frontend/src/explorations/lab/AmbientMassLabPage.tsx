import { useEffect, useMemo, useRef, useState } from "react";
import {
  Graph,
  type EdgeData,
  type IElementEvent,
  type NodeData,
} from "@antv/g6";
import { Renderer as CanvasRenderer } from "@antv/g-canvas";
import { Renderer as WebGLRenderer } from "@antv/g-webgl";
import { gray } from "@radix-ui/colors";
import { BASE_NODE_STATE, NODE_FONTS } from "../g6/graphOptions";
import {
  arrowSizeForKind,
  ensureLinkageEdgeRegistered,
  isDirectedKind,
  LINKAGE_EDGE,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import {
  AMBIENT_LOD_GRAPH_VERSION,
  createAmbientLodGraph,
  labelOf,
} from "./ambientLodData";
import {
  buildCoarsenModel,
  continuousResolver,
  massDiameter,
  type CoarsenModel,
  type ContinuousState,
} from "./ambientMassModel";
import { createMassSim, type MassSimHandle } from "./ambientMassSim";
import {
  clearLabelMeasureCache,
  labelBoxWidth,
} from "./nodeLabelFit";
import "../g6/g6Lab.css";
import "./AmbientMassLabPage.css";

/**
 * Perf A/B harness — change ONE axis at a time, remount, run Bench.
 *
 * Ladder results (Brave = Cursor, Intel Arc / Mesa / Wayland):
 *  0. Lag in both browsers → not Electron-only.
 *  1. Canvas2D + DPR1 + freeze → paint fine.
 *  2. Canvas2D + live physics → sim fine.
 *  3. WebGL + DPR1 + freeze → FAIL: blurry + node labels missing
 *     (black discs, no text). WebGL is not a viable paint path here.
 *  4. Next: DPR2 on Canvas2D only (sharpness), if needed.
 *
 * Do not stack WebGL + live physics. Uniform WebGL also forced
 * `enableMultiLayer: false` earlier; that is abandoned — G6 keeps labels as
 * Text children on `main`, and WebGL Text on this stack is unreliable.
 */

type RenderBackend = "canvas" | "webgl";
type DprChoice = 1 | 2;

type LabParams = {
  backend: RenderBackend;
  dpr: DprChoice;
  physicsFrozen: boolean;
};

function readLabParams(): LabParams {
  const raw = window.location.hash.split("?")[1] ?? "";
  const q = new URLSearchParams(raw);
  const r = q.get("r");
  const dprRaw = Number(q.get("dpr"));
  const phys = q.get("phys");
  return {
    backend: r === "webgl" ? "webgl" : "canvas",
    dpr: dprRaw === 2 ? 2 : 1,
    physicsFrozen: phys === "freeze",
  };
}

function writeLabParams(p: LabParams) {
  const base =
    window.location.hash.split("?")[0] || "#/explorations/ambient-mass";
  const q = new URLSearchParams();
  q.set("r", p.backend);
  q.set("dpr", String(p.dpr));
  q.set("phys", p.physicsFrozen ? "freeze" : "live");
  const next = `${base}?${q.toString()}`;
  if (window.location.hash !== next) {
    window.history.replaceState(null, "", next);
  }
}

/**
 * WebGL stays available as a broken-path control, not a recommendation.
 * G6's documented hybrid (WebGL `main`, Canvas elsewhere) still draws node
 * labels on `main` — so missing text is a WebGL Text failure, not a layering
 * mistake. Prefer Canvas2D for the real lab.
 */
function makeRenderer(backend: RenderBackend) {
  return (layer: "background" | "main" | "label" | "transient") => {
    if (backend === "webgl" && layer === "main") return new WebGLRenderer();
    return new CanvasRenderer();
  };
}

/**
 * Ambient canvas as an *abstraction dial* rather than a fade.
 *
 * The wheel drives level-of-abstraction, not the camera. Rolling out folds
 * low-degree nodes into their highest-degree neighbour; a survivor's diameter
 * grows as √(mass), so area ∝ the number of nodes it stands for and total ink
 * stays constant at every level. Rolling in past full detail hands the wheel
 * back to the camera for ordinary magnification.
 *
 * Sizing is graph-space, so the camera still scales everything together — no
 * per-frame `1/zoom` counter-scaling (handoff §4.6), and positions never move,
 * so the mental map holds (§4.1). What changes is which nodes exist and how
 * much each one stands for.
 */

const INK = gray.gray12;
const PAPER = gray.gray1;

/** Defaults for the on-page LOD dial — remount graph when size knobs change. */
export type LodParams = {
  /** Floor on survivors at overview. */
  minLevel: number;
  /** Magnification overview→detail; also sets abstraction range via level∝zoom². */
  zoomRange: number;
  /** Fold ramp width as a fraction of current level. */
  foldWindow: number;
  /** Dial delta per wheel deltaY unit. */
  wheelSensitivity: number;
  /** Graph-space diameter of mass=1. */
  unitDiameter: number;
  /** Extra size multiplier for landmarks. */
  landmarkBoost: number;
  /** Idle ms after scroll before physics reheat / gather. */
  dialSettleMs: number;
};

export const DEFAULT_LOD_PARAMS: LodParams = {
  minLevel: 6,
  zoomRange: 4,
  foldWindow: 0.22,
  wheelSensitivity: 0.00021,
  unitDiameter: 34,
  landmarkBoost: 1.2,
  dialSettleMs: 140,
};

/** Push G6 positions at most every N animation frames while the sim is hot. */
const POSITION_FRAME_STRIDE = 3;
/** Skip translateElementTo once the sim is cooler than this. */
const POSITION_ALPHA_FLOOR = 0.03;
/** World-space epsilon before a node counts as moved. */
const POSITION_EPS = 0.6;

/**
 * Module-level: G6 style callbacks are not closures.
 *
 * Mass and opacity are *fractional* — blended between the two integer levels
 * the dial currently straddles. Folding is inherently discrete, so without this
 * a heavy node releases all its mass in one notch (measured: a 278px disc
 * snapping to 102px between two scroll steps). Blending turns each fold into a
 * continuous handover: the child fades while its absorber grows.
 */
const view = {
  mass: new Map<string, number>(),
  presence: new Map<string, number>(),
  /** Display diameter per node — also the sim's collide radius source. */
  size: new Map<string, number>(),
  landmark: new Set<string>(),
  zoom: 1,
};

/** Size knobs read by G6 style callbacks (not React closures). */
const lodLive: Pick<LodParams, "unitDiameter" | "landmarkBoost"> = {
  unitDiameter: DEFAULT_LOD_PARAMS.unitDiameter,
  landmarkBoost: DEFAULT_LOD_PARAMS.landmarkBoost,
};

/**
 * Per-element varying state lives in element *data*, not in module maps.
 *
 * Reading it from module state forces a full `setNode`/`setEdge` spec reset to
 * invalidate G6's memoised computed styles — which recomputes all 104 nodes and
 * 156 edges on every frame. Profiling a cursor-lens sweep put ~40% of samples
 * in G6 style recomputation for that reason. Held in data, `updateNodeData` /
 * `updateEdgeData` mark exactly the elements that changed and nothing else.
 */
function num(datum: NodeData | EdgeData, key: string, fallback = 0) {
  const value = Number((datum.data as Record<string, unknown> | undefined)?.[key]);
  return Number.isFinite(value) ? value : fallback;
}

function diameterOf(datum: NodeData) {
  return massDiameter(
    num(datum, "_p") * num(datum, "_m", 1),
    lodLive.unitDiameter,
    view.landmark.has(String(datum.id)),
    lodLive.landmarkBoost,
  );
}

/** Labels arrive when the disc is big enough on screen to hold them. */
function labelOpacityOf(datum: NodeData) {
  const screen = diameterOf(datum) * view.zoom;
  if (screen <= 13) return 0;
  return Math.min(1, (screen - 13) / 9);
}

/**
 * Font size as a fixed fraction of disc diameter.
 *
 * `fitLabelFontSize` + absolute 7–15px clamps broke scale invariance: as the
 * dial grew a disc, the font lagged the radius, wrap width caught up in steps,
 * and labels flipped 2-line ↔ 1-line. Keeping font ∝ diameter (and maxWidth ∝
 * diameter) makes layout constant in "disc units" — zoom and mass only scale
 * the whole chip, they don't reflow it.
 */
const LABEL_FONT_PER_DIAMETER = 0.2;

function buildNodeStyle() {
  return {
    // No x/y mappers: the simulation owns position outright. That is what lets
    // physics and the LOD coexist — the dial drives *size*, and the sim turns
    // size into space.
    size: (datum: NodeData) => diameterOf(datum),
    fill: INK,
    stroke: INK,
    lineWidth: 1,
    lineCap: "round" as const,
    halo: false,
    badge: false,
    // Fully opaque whenever it exists at all — presence is carried by the
    // radius. The hard cutoff only stops a zero-radius circle leaving its 1px
    // stroke behind as a speck.
    opacity: (datum: NodeData) => (num(datum, "_p") > 0.002 ? 1 : 0),
    labelText: (datum: NodeData) => labelOf(datum),
    labelPlacement: "center" as const,
    labelFill: PAPER,
    labelOpacity: (datum: NodeData) => labelOpacityOf(datum),
    labelFontFamily: NODE_FONTS.plexCondensed.family,
    labelFontSize: (datum: NodeData) =>
      Math.max(0.1, diameterOf(datum) * LABEL_FONT_PER_DIAMETER),
    labelFontWeight: 600 as const,
    labelWordWrap: true,
    labelMaxWidth: (datum: NodeData) => labelBoxWidth(diameterOf(datum)),
    labelMaxLines: 2,
    cursor: "grab" as const,
  };
}

/** Both endpoints must be present for an edge to exist at all. */
function edgePresence(datum: EdgeData) {
  return num(datum, "_ep");
}

function buildEdgeStyle() {
  return {
    stroke: INK,
    lineCap: "round" as const,
    pointerEvents: "none" as const,
    lineWidth: 1.15,
    opacity: (datum: EdgeData) => edgePresence(datum) * 0.55,
    endArrow: (datum: EdgeData) => isDirectedKind(linkageEdgeKind(datum)),
    endArrowSize: (datum: EdgeData) =>
      arrowSizeForKind(linkageEdgeKind(datum)) / Math.max(0.4, view.zoom),
    endArrowFill: INK,
    // Perf lab: lens / hover labels off — no per-pointer draw tax.
    labelText: "",
  };
}

function applyState(
  model: CoarsenModel,
  state: ContinuousState,
  level: number,
) {
  view.mass = state.mass;
  view.presence = state.presence;
  view.landmark = new Set(
    [...model.facts.values()].filter((f) => f.isLandmark).map((f) => f.id),
  );
  // Publish display sizes for the sim: these become collide radii, which is how
  // a growing survivor pushes room for itself.
  const size = new Map<string, number>();
  for (const id of model.facts.keys()) {
    size.set(id, diameterOf({ id } as NodeData));
  }
  view.size = size;

  // Verification hook. Ink is conserved when every node is accounted for
  // exactly once: a present node by itself, an absent one inside its absorber.
  let ink = 0;
  for (const [id, mass] of state.mass) {
    ink += (state.presence.get(id) ?? 0) * mass;
  }
  (window as Window & { __ambientMassView?: unknown }).__ambientMassView = {
    level,
    survivors: [...state.presence.values()].filter((p) => p > 0.5).length,
    ink: Number(ink.toFixed(2)),
    nodeCount: model.nodeCount,
    top: [...state.mass.entries()]
      .filter(([id]) => (state.presence.get(id) ?? 0) > 0.5)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([id, m]) => ({
        id,
        mass: Number(m.toFixed(2)),
        diameter: diameterOf({ id } as NodeData),
      })),
  };
}

export function AmbientMassLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const benchRef = useRef<() => Promise<void>>(async () => {});
  const applyDialRef = useRef<(force?: boolean) => Promise<void>>(async () => {});
  const lodRef = useRef<LodParams>(DEFAULT_LOD_PARAMS);
  const initial = useMemo(() => readLabParams(), []);
  const [backend, setBackend] = useState<RenderBackend>(initial.backend);
  const [dpr, setDpr] = useState<DprChoice>(initial.dpr);
  const [physicsFrozen, setPhysicsFrozen] = useState(initial.physicsFrozen);
  const [lod, setLod] = useState<LodParams>(DEFAULT_LOD_PARAMS);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState("Building coarsening…");
  const [level, setLevel] = useState(0);
  const [magnify, setMagnify] = useState(1);
  const [biggest, setBiggest] = useState<{ id: string; mass: number } | null>(
    null,
  );
  const [perfHud, setPerfHud] = useState({
    fps: 0,
    drawMs: 0,
    translateMs: 0,
    dialMs: 0,
    draws: 0,
    moves: 0,
  });
  const [benchNote, setBenchNote] = useState("");

  const data = useMemo(() => createAmbientLodGraph(), []);
  lodRef.current = lod;

  useEffect(() => {
    lodLive.unitDiameter = lod.unitDiameter;
    lodLive.landmarkBoost = lod.landmarkBoost;
  }, [lod.unitDiameter, lod.landmarkBoost]);

  useEffect(() => {
    writeLabParams({ backend, dpr, physicsFrozen });
  }, [backend, dpr, physicsFrozen]);

  const setLodField = <K extends keyof LodParams>(key: K, value: LodParams[K]) => {
    setLod((prev) => ({ ...prev, [key]: value }));
  };

  /**
   * Coarsening is cached per `graph_version`. The backend's version is
   * `sha1(path | mtime_ns | n)` — an equality check for drift, not a revision
   * counter — so any change is a full invalidate, never a diff.
   */
  const model = useMemo(() => {
    const ids = (data.nodes ?? []).map((n) => String(n.id));
    const edges = (data.edges ?? []).map((e) => ({
      source: String(e.source),
      target: String(e.target),
    }));
    return buildCoarsenModel(
      ids,
      edges,
      `gv_fixture_${AMBIENT_LOD_GRAPH_VERSION}`,
      // The fixture carries no betweenness, so it is degree-ranked — the same
      // shape the backend reports under SST_FAST_STRUCTURAL_INDEX. Read this,
      // never assume betweenness.
      "degree",
    );
  }, [data]);

  useEffect(() => {
    if (!containerRef.current) return;
    ensureLinkageEdgeRegistered();
    let cancelled = false;
    let self: Graph | null = null;
    setReady(false);
    setNote("Building graph…");
    setBenchNote("");

    let sim: MassSimHandle | null = null;
    let simRaf = 0;
    let latestPositions: Map<string, [number, number]> | null = null;

    /** Lightweight lab HUD — FPS + last draw / translate / dial cost. */
    const perf = {
      frames: 0,
      fpsWindowStart: performance.now(),
      fps: 0,
      drawMs: 0,
      translateMs: 0,
      dialMs: 0,
      draws: 0,
      moves: 0,
    };
    let perfHudRaf = 0;
    let perfSampleRaf = 0;
    const publishPerfHud = () => {
      perfHudRaf = 0;
      if (cancelled) return;
      setPerfHud({
        fps: perf.fps,
        drawMs: perf.drawMs,
        translateMs: perf.translateMs,
        dialMs: perf.dialMs,
        draws: perf.draws,
        moves: perf.moves,
      });
      (
        window as Window & { __ambientMassPerf?: typeof perf }
      ).__ambientMassPerf = { ...perf };
    };
    const schedulePerfHud = () => {
      if (perfHudRaf) return;
      perfHudRaf = requestAnimationFrame(publishPerfHud);
    };
    const samplePerfFrame = () => {
      perfSampleRaf = 0;
      if (cancelled) return;
      perf.frames += 1;
      const now = performance.now();
      const elapsed = now - perf.fpsWindowStart;
      if (elapsed >= 500) {
        perf.fps =
          perf.frames > 0
            ? Math.round((perf.frames * 1000) / Math.max(1, elapsed))
            : -1;
        perf.frames = 0;
        perf.fpsWindowStart = now;
        schedulePerfHud();
      }
      perfSampleRaf = requestAnimationFrame(samplePerfFrame);
    };
    perfSampleRaf = requestAnimationFrame(samplePerfFrame);
    const perfInterval = window.setInterval(() => {
      if (cancelled) return;
      const now = performance.now();
      const elapsed = now - perf.fpsWindowStart;
      if (elapsed >= 500) {
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
        publishPerfHud();
      }
    }, 500);

    const timedDraw = async (graph: Graph) => {
      const t0 = performance.now();
      await graph.draw().catch(() => {});
      perf.drawMs = Math.round((performance.now() - t0) * 10) / 10;
      perf.draws += 1;
      publishPerfHud();
    };

    // One dial: 0 = abstract overview, 1 = full detail. Camera and abstraction
    // are both derived from it, so every scroll changes both.
    let dial = 0;
    let fitZoom = 1;
    let currentLevel = -1;

    /** Exponential, because that is how zoom reads to the hand. */
    const zoomForDial = (t: number) => {
      const range = lodRef.current.zoomRange;
      return fitZoom * Math.pow(range, t);
    };

    /**
     * level ∝ zoom². Graph-space diameter grows as √mass and mass averages
     * N/level, so screen size = √(N/level) · zoom stays constant exactly when
     * level ∝ zoom². Pull out and you get fewer, heavier discs at the same
     * visual weight — which is what makes the scroll feel like one motion
     * rather than a semantic dial bolted onto a camera.
     *
     * Geometric in the same breath: level is a ratio scale, so equal scroll
     * means equal proportional change, not equal absolute change.
     *
     * Top of the level range overshoots nodeCount by the fold window so the
     * lowest-ranked nodes actually reach full presence.
     */
    const levelForDial = (t: number) => {
      const { minLevel, zoomRange, foldWindow } = lodRef.current;
      const levelTop = (model.nodeCount + 1) / (1 - foldWindow);
      return Math.max(
        minLevel,
        Math.min(levelTop, levelTop * Math.pow(zoomRange, 2 * (t - 1))),
      );
    };

    let resolve: ReturnType<typeof continuousResolver> | null = null;
    let resolveWindow = -1;
    const resolveAt = (exact: number) => {
      const window = lodRef.current.foldWindow;
      if (!resolve || resolveWindow !== window) {
        resolveWindow = window;
        resolve = continuousResolver(model, { relativeWindow: window });
      }
      return resolve(exact);
    };

    const pushStats = (state: ContinuousState) => {
      let top: { id: string; mass: number } | null = null;
      let shown = 0;
      for (const [id, mass] of state.mass) {
        if ((state.presence.get(id) ?? 0) <= 0.5) continue;
        shown += 1;
        if (!top || mass > top.mass) top = { id, mass: Math.round(mass) };
      }
      setLevel(shown);
      setBiggest(top);
    };

    /**
     * Push per-element state into element *data*, touching only what changed.
     *
     * The spec is installed once at construction; re-setting it (the old
     * `restyle`) invalidated every element's memoised style, so a lens move
     * over 20 edges recomputed all 104 nodes and 156 edges. Data updates mark
     * exactly the changed elements instead.
     */
    const pushNodes = (rows: { id: string; data: Record<string, number> }[]) => {
      const graph = self;
      if (!graph || graph.destroyed || !rows.length) return;
      graph.updateNodeData(
        rows.map((r) => ({ id: r.id, data: { ...r.data } })),
      );
    };
    const pushEdges = (rows: { id: string; data: Record<string, number> }[]) => {
      const graph = self;
      if (!graph || graph.destroyed || !rows.length) return;
      graph.updateEdgeData(
        rows.map((r) => ({ id: r.id, data: { ...r.data } })),
      );
    };

    /**
     * Write the current level onto the elements whose values actually moved.
     *
     * A scroll notch only shifts presence for nodes near the fold frontier —
     * the rest are pinned at 0 or 1 — so pushing all 104 nodes and 156 edges
     * every notch re-computes styles for elements that did not change. The
     * epsilon is well below one display pixel of radius.
     */
    const sentNode = new Map<string, [number, number]>();
    const sentEdge = new Map<string, number>();
    const EPS = 0.004;
    const publishLevel = (graph: Graph, force = false) => {
      const nodeRows: { id: string; data: Record<string, number> }[] = [];
      for (const node of graph.getNodeData()) {
        const id = String(node.id);
        const m = view.mass.get(id) ?? 1;
        const p = view.presence.get(id) ?? 0;
        const prev = sentNode.get(id);
        if (
          !force &&
          prev &&
          Math.abs(prev[0] - m) < EPS &&
          Math.abs(prev[1] - p) < EPS
        ) {
          continue;
        }
        sentNode.set(id, [m, p]);
        nodeRows.push({
          id,
          data: { _m: m, _p: p },
        });
      }
      pushNodes(nodeRows);
      const edgeRows: { id: string; data: Record<string, number> }[] = [];
      for (const edge of graph.getEdgeData()) {
        const id = String(edge.id);
        const ep = Math.min(
          view.presence.get(String(edge.source)) ?? 0,
          view.presence.get(String(edge.target)) ?? 0,
        );
        const prev = sentEdge.get(id);
        if (!force && prev !== undefined && Math.abs(prev - ep) < EPS) continue;
        sentEdge.set(id, ep);
        edgeRows.push({ id, data: { _ep: ep } });
      }
      pushEdges(edgeRows);
    };

    /** Re-resolve the level and repaint sizes. Physics catch-up is deferred
     *  until the scroll gesture settles — reheating every notch flooded G6
     *  with translateElementTo (~50ms each). */
    let dialSettleTimer = 0;
    let positionsPaused = false;
    const presenceChangedEnough = (
      prev: Map<string, number>,
      next: Map<string, number>,
    ) => {
      if (prev.size !== next.size) return true;
      for (const [id, p] of next) {
        if (Math.abs((prev.get(id) ?? 0) - p) > 0.04) return true;
      }
      return false;
    };
    let lastPushedPresence = new Map<string, number>();

    const flushSimPresence = (reheat: boolean) => {
      if (!sim) return;
      if (!presenceChangedEnough(lastPushedPresence, view.presence) && !reheat) {
        return;
      }
      lastPushedPresence = new Map(view.presence);
      sim.setPresence(view.presence, { reheat });
    };

    const applyDial = async (force = false, origin?: [number, number]) => {
      const graph = self;
      if (cancelled || !graph || graph.destroyed) return;

      const exact = levelForDial(dial);
      const wanted = zoomForDial(dial);
      setMagnify(wanted / fitZoom);
      view.zoom = wanted;

      // Camera first, so the scroll reads as one continuous motion rather than
      // stepping with the folds. Anchored on the cursor, not the viewport
      // centre — zooming about the middle slides whatever you were pointing at
      // out from under you, which reads as the map fighting you.
      if (Math.abs(graph.getZoom() - wanted) > 0.002) {
        await graph.zoomTo(wanted, false, origin).catch(() => {});
      }

      if (Math.abs(exact - currentLevel) > 0.001 || force) {
        const tDial = performance.now();
        currentLevel = exact;
        const state = resolveAt(exact);
        applyState(model, state, exact);
        pushStats(state);
        // Sizes / opacity first — no sim reheat on the hot scroll path.
        positionsPaused = true;
        if (!physicsFrozen) {
          sim?.setPresence(view.presence, { reheat: false });
          lastPushedPresence = new Map(view.presence);
        }
        publishLevel(graph);
        await timedDraw(graph);
        perf.dialMs = Math.round((performance.now() - tDial) * 10) / 10;
        publishPerfHud();

        if (!physicsFrozen) {
          if (dialSettleTimer) window.clearTimeout(dialSettleTimer);
          dialSettleTimer = window.setTimeout(() => {
            dialSettleTimer = 0;
            if (cancelled) return;
            positionsPaused = false;
            flushSimPresence(true);
          }, lodRef.current.dialSettleMs);
        }
      }
    };
    applyDialRef.current = applyDial;

    // Seed at the *starting* dial position (the overview), not full detail:
    // fitView has to measure the layout the user actually opens on.
    applyState(model, resolveAt(levelForDial(0)), levelForDial(0));

    const graph = new Graph({
      container: containerRef.current,
      data,
      animation: false,
      padding: [48, 44, 48, 44],
      zoomRange: [0.05, 8],
      devicePixelRatio: dpr,
      renderer: makeRenderer(backend),
      // Keep G6 multi-layer. Single-layer WebGL was an experiment; it did not
      // fix lag and made the path harder to compare fairly.
      node: { type: "circle", style: buildNodeStyle(), state: BASE_NODE_STATE },
      edge: {
        type: LINKAGE_EDGE,
        style: buildEdgeStyle() as never,
        animation: false,
      },
      behaviors: ["drag-canvas", "click-select"],
    });

    self = graph;
    graphRef.current = graph;
    (window as Window & { __ambientMassLive?: typeof view }).__ambientMassLive =
      view;
    (
      window as Window & { __ambientMassGraph?: Graph | null }
    ).__ambientMassGraph = graph;

    const container = containerRef.current;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      dial = Math.max(
        0,
        Math.min(1, dial - event.deltaY * lodRef.current.wheelSensitivity),
      );
      const rect = container.getBoundingClientRect();
      void applyDial(false, [
        event.clientX - rect.left,
        event.clientY - rect.top,
      ]);
    };
    container.addEventListener("wheel", onWheel, { passive: false });

    // Node drag → the sim. Pinning fx/fy and letting neighbours yield through
    // links is the Glide Loose feel from the linkage lab.
    let dragId: string | null = null;
    const onNodeDown = (event: IElementEvent) => {
      const id = event?.target?.id;
      if (!id) return;
      dragId = String(id);
      positionsPaused = false;
      container.setPointerCapture?.(
        (event as unknown as { pointerId?: number }).pointerId ?? 0,
      );
    };
    const onDragMove = (event: PointerEvent) => {
      if (!dragId) return;
      const graphNow = self;
      if (!graphNow || graphNow.destroyed) return;
      const [wx, wy] = graphNow.getCanvasByClient([
        event.clientX,
        event.clientY,
      ]);
      sim?.dragMove(dragId, wx, wy);
    };
    const onDragUp = () => {
      if (!dragId) return;
      sim?.dragEnd(dragId);
      dragId = null;
    };

    graph.on("node:pointerdown", onNodeDown);
    container.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragUp);

    graph
      .render()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        setNote("Settling…");

        // Positions come from the sim from here on. Tick writes are coalesced
        // and stride-limited: d3 ticks faster than G6 can translate 104 nodes
        // (~50ms per full translateElementTo batch).
        const lastSent = new Map<string, [number, number]>();
        let positionFrame = 0;
        const pushPositions = () => {
          simRaf = 0;
          const graphNow = self;
          const pos = latestPositions;
          if (!graphNow || graphNow.destroyed || !pos) return;
          if (physicsFrozen || positionsPaused) return;
          if ((sim?.alpha() ?? 0) < POSITION_ALPHA_FLOOR && !dragId) return;
          positionFrame += 1;
          if (positionFrame % POSITION_FRAME_STRIDE !== 0 && !dragId) return;

          const moved: Record<string, [number, number]> = {};
          let count = 0;
          for (const [id, [x, y]] of pos) {
            const prev = lastSent.get(id);
            if (
              prev &&
              Math.abs(prev[0] - x) < POSITION_EPS &&
              Math.abs(prev[1] - y) < POSITION_EPS
            ) {
              continue;
            }
            lastSent.set(id, [x, y]);
            moved[id] = [x, y];
            count += 1;
          }
          if (!count) return;
          const t0 = performance.now();
          void graphNow
            .translateElementTo(moved, false)
            .catch(() => {})
            .finally(() => {
              perf.translateMs = Math.round((performance.now() - t0) * 10) / 10;
              perf.moves += 1;
              publishPerfHud();
            });
        };

        sim = createMassSim({
          nodes: (data.nodes ?? []).map((n) => {
            const style = n.style as { x?: number; y?: number } | undefined;
            return {
              id: String(n.id),
              x: style?.x ?? 0,
              y: style?.y ?? 0,
            };
          }),
          edges: (data.edges ?? []).map((e) => ({
            source: String(e.source),
            target: String(e.target),
          })),
          absorber: model.absorber,
          // Constant collide: the space a survivor will grow into, reserved up
          // front. Over-spaces the detail view, which costs nothing — children
          // gather *into* their parent, so the slack around a child is exactly
          // the room its parent grows into.
          footprint: new Map(
            [...model.facts.keys()].map((id) => [
              id,
              massDiameter(
                model.subtreeMass.get(id) ?? 1,
                lod.unitDiameter,
                model.facts.get(id)?.isLandmark ?? false,
                lod.landmarkBoost,
              ),
            ]),
          ),
          // Link distance / strength / decay come from Glide Loose defaults
          // inside createMassSim (same preset as canvas-linkage).
          collidePad: 6,
          onTick: (positions) => {
            latestPositions = positions;
            if (simRaf) return;
            simRaf = requestAnimationFrame(pushPositions);
          },
        });
        sim.setPresence(view.presence, { reheat: !physicsFrozen });
        lastPushedPresence = new Map(view.presence);

        // Let it relax before framing, so fitView measures a settled cloud.
        // Wait for the sim to actually settle before framing — a fixed timeout
        // guesses wrong and the layout keeps moving after it is measured, which
        // is what left the cloud clipped.
        const settled = Date.now() + 6000;
        while (
          !cancelled &&
          !graph.destroyed &&
          sim.alpha() > 0.02 &&
          Date.now() < settled
        ) {
          await new Promise<void>((r) => window.setTimeout(r, 100));
        }
        if (cancelled || graph.destroyed) return;

        setNote("Fitting…");
        /**
         * Frame the *visible* set, not `fitView`.
         *
         * Folded nodes still exist at zero size, and `fitView` includes them in
         * its bounding box — so the box is larger than anything you can see and
         * the survivors end up shoved into a corner. Measuring only what has
         * size, and centring that, is exact.
         */
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        for (const [id, [x, y]] of sim.positions()) {
          const d = view.size.get(id) ?? 0;
          if (d < 2) continue;
          minX = Math.min(minX, x - d / 2);
          maxX = Math.max(maxX, x + d / 2);
          minY = Math.min(minY, y - d / 2);
          maxY = Math.max(maxY, y + d / 2);
        }
        if (Number.isFinite(minX)) {
          const [stageW, stageH] = graph.getSize();
          const pad = 1.12;
          fitZoom = Math.min(
            stageW / Math.max(1, (maxX - minX) * pad),
            stageH / Math.max(1, (maxY - minY) * pad),
          );
          await graph.zoomTo(fitZoom, false).catch(() => {});
          const [vx, vy] = graph.getViewportByCanvas([
            (minX + maxX) / 2,
            (minY + maxY) / 2,
          ]);
          const [ccx, ccy] = graph.getCanvasCenter();
          await graph.translateBy([ccx - vx, ccy - vy], false).catch(() => {});
        } else {
          await graph.fitView({ when: "always", direction: "both" }, false);
          fitZoom = graph.getZoom();
        }
        if (cancelled || graph.destroyed) return;
        view.zoom = fitZoom;
        currentLevel = levelForDial(0);
        publishLevel(graph, true);
        await timedDraw(graph);
        if (cancelled || graph.destroyed) return;

        // Ladder step 1: freeze stops the sim after settle so Bench can isolate
        // G6 paint from d3→translate cost.
        if (physicsFrozen) {
          try {
            sim.stop();
          } catch {
            /* ok */
          }
          positionsPaused = true;
        }

        setNote("");
        setReady(true);
        void document.fonts?.ready.then(() => {
          if (cancelled || graph.destroyed) return;
          clearLabelMeasureCache();
          void applyDial(true);
        });

        benchRef.current = async () => {
          const g = self;
          if (!g || g.destroyed) return;
          setBenchNote("Bench running…");
          const avg = (xs: number[]) =>
            xs.reduce((s, x) => s + x, 0) / Math.max(1, xs.length);
          const draws: number[] = [];
          for (let i = 0; i < 5; i++) {
            const t0 = performance.now();
            await g.draw().catch(() => {});
            draws.push(performance.now() - t0);
          }
          const translates: number[] = [];
          const nodes = g.getNodeData();
          for (let i = 0; i < 5; i++) {
            const moved: Record<string, [number, number]> = {};
            for (const n of nodes) {
              const id = String(n.id);
              const prev = lastSent.get(id) ?? [0, 0];
              moved[id] = [prev[0] + 0.05, prev[1]];
            }
            const t0 = performance.now();
            await g.translateElementTo(moved, false).catch(() => {});
            translates.push(performance.now() - t0);
          }
          const dials: number[] = [];
          const savedDial = dial;
          for (let i = 0; i < 6; i++) {
            dial = Math.min(1, dial + 0.04);
            const t0 = performance.now();
            await applyDial(false);
            dials.push(performance.now() - t0);
          }
          dial = savedDial;
          await applyDial(true);
          const report = {
            backend,
            dpr,
            physicsFrozen,
            drawAvgMs: Math.round(avg(draws) * 10) / 10,
            translateAvgMs: Math.round(avg(translates) * 10) / 10,
            dialAvgMs: Math.round(avg(dials) * 10) / 10,
            draws,
            translates,
            dials,
            gl: (() => {
              const c = containerRef.current?.querySelector("canvas");
              if (!c) return null;
              try {
                const gl =
                  c.getContext("webgl2") ||
                  c.getContext("webgl") ||
                  null;
                if (!gl) return { kind: "canvas2d" as const };
                const dbg = gl.getExtension("WEBGL_debug_renderer_info");
                return {
                  kind: "webgl" as const,
                  renderer: dbg
                    ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)
                    : gl.getParameter(gl.RENDERER),
                };
              } catch {
                return { kind: "busy" as const };
              }
            })(),
          };
          (
            window as Window & { __ambientMassBench?: typeof report }
          ).__ambientMassBench = report;
          setBenchNote(
            `bench draw ${report.drawAvgMs}ms · translate ${report.translateAvgMs}ms · dial ${report.dialAvgMs}ms`,
          );
          console.info("[ambient-mass] bench", report);
        };
      })
      .catch((err) => {
        if (cancelled || graph.destroyed) return;
        console.error("[ambient-mass] init failed", err);
        setNote("Init failed — see console");
      });

    return () => {
      cancelled = true;
      if (perfSampleRaf) cancelAnimationFrame(perfSampleRaf);
      if (perfHudRaf) cancelAnimationFrame(perfHudRaf);
      window.clearInterval(perfInterval);
      if (dialSettleTimer) window.clearTimeout(dialSettleTimer);
      self = null;
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("pointermove", onDragMove);
      window.removeEventListener("pointerup", onDragUp);
      if (simRaf) cancelAnimationFrame(simRaf);
      sim?.stop();
      sim = null;
      graph.off("node:pointerdown", onNodeDown);
      if (graphRef.current === graph) graphRef.current = null;
      const w = window as Window & { __ambientMassGraph?: Graph | null };
      if (w.__ambientMassGraph === graph) w.__ambientMassGraph = null;
      graph.destroy();
    };
  }, [data, model, backend, dpr, physicsFrozen, lod.unitDiameter, lod.landmarkBoost]);

  // Dial-only LOD knobs apply live — no graph remount.
  useEffect(() => {
    if (!ready) return;
    void applyDialRef.current(true);
  }, [
    ready,
    lod.minLevel,
    lod.zoomRange,
    lod.foldWindow,
    lod.dialSettleMs,
  ]);

  const setDialFromButton = (delta: number) => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const event = new WheelEvent("wheel", { deltaY: delta });
    containerRef.current?.dispatchEvent(event);
  };

  return (
    <main className="ambient-mass">
      <header className="ambient-mass__header">
        <div>
          <p className="ambient-mass__eyebrow">Screen 1 · Ambient Canvas</p>
          <h1>Mass LOD lab</h1>
          <p className="ambient-mass__lede">
            One scroll moves the camera and the abstraction together. Rolling out
            magnifies down <em>and</em> folds low-degree nodes into their
            highest-degree neighbour — each folding node <strong>shrinks to a dot
            and slides into its absorber</strong> after the scroll settles.
            Physics is Glide Loose from canvas-linkage (link-only, no charge).
            Tune LOD below; size knobs remount the graph.
          </p>
          <p className="ambient-mass__nav">
            <a href="#/explorations">Explorations</a>
            {" · "}
            <a href="#/explorations/ambient-lod">Ambient LOD (fade)</a>
            {" · "}
            <a href="#/explorations/canvas-linkage">Canvas linkage</a>
          </p>
        </div>
        <aside className="ambient-mass__note">
          <span>Structure</span>
          <strong>
            {model.nodeCount} nodes · importance {model.importanceKind}
          </strong>
          <p>
            {model.graphVersion} · heavy-neighbour coarsening · children drift
            into absorbers · {model.roots.length} local maxima always survive
          </p>
        </aside>
      </header>

      <div className="ambient-mass__toolbar">
        <p className="ambient-mass__status" role="status">
          {ready ? (
            <>
              showing <strong>{level}</strong>/{model.nodeCount}
              {" · "}
              zoom {magnify.toFixed(2)}× of overview
              {biggest ? (
                <>
                  {" · "}
                  largest <strong>{biggest.id}</strong> stands for {biggest.mass}
                </>
              ) : null}
              {" · "}
              <span
                className="ambient-mass__perf"
                title="fps · last draw / translate / dial · config"
              >
                {perfHud.fps < 0 ? "—fps" : `${perfHud.fps}fps`}
                {" · "}
                draw {perfHud.drawMs.toFixed(1)}ms
                {" · "}
                xlat {perfHud.translateMs.toFixed(1)}ms
                {" · "}
                dial {perfHud.dialMs.toFixed(1)}ms
                {" · "}
                {backend} · dpr{dpr} · {physicsFrozen ? "freeze" : "live"}
              </span>
              {benchNote ? (
                <>
                  {" · "}
                  <span className="ambient-mass__bench">{benchNote}</span>
                </>
              ) : null}
            </>
          ) : (
            note || "Loading…"
          )}
        </p>
        <div className="ambient-mass__actions ambient-mass__ab">
          <div className="ambient-mass__ab-group" role="group" aria-label="Renderer">
            <button
              type="button"
              className={backend === "canvas" ? "is-active" : undefined}
              onClick={() => setBackend("canvas")}
            >
              Canvas2D
            </button>
            <button
              type="button"
              className={backend === "webgl" ? "is-active" : undefined}
              title="Control only — labels often missing on this GPU/stack"
              onClick={() => setBackend("webgl")}
            >
              WebGL ✗
            </button>
          </div>
          <div className="ambient-mass__ab-group" role="group" aria-label="DPR">
            <button
              type="button"
              className={dpr === 1 ? "is-active" : undefined}
              onClick={() => setDpr(1)}
            >
              DPR1
            </button>
            <button
              type="button"
              className={dpr === 2 ? "is-active" : undefined}
              onClick={() => setDpr(2)}
            >
              DPR2
            </button>
          </div>
          <div className="ambient-mass__ab-group" role="group" aria-label="Physics">
            <button
              type="button"
              className={!physicsFrozen ? "is-active" : undefined}
              onClick={() => setPhysicsFrozen(false)}
            >
              Live
            </button>
            <button
              type="button"
              className={physicsFrozen ? "is-active" : undefined}
              onClick={() => setPhysicsFrozen(true)}
            >
              Freeze
            </button>
          </div>
          <button
            type="button"
            disabled={!ready}
            onClick={() => void benchRef.current()}
          >
            Bench
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={() => setDialFromButton(240)}
          >
            Abstract
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={() => setDialFromButton(-240)}
          >
            Detail
          </button>
        </div>
      </div>

      <div className="ambient-mass__lod" aria-label="LOD parameters">
        <div className="ambient-mass__lod-head">
          <span>LOD parameters</span>
          <button
            type="button"
            onClick={() => setLod(DEFAULT_LOD_PARAMS)}
          >
            Reset
          </button>
        </div>
        <div className="ambient-mass__lod-grid">
          {(
            [
              {
                key: "minLevel",
                label: "Min level",
                min: 2,
                max: 24,
                step: 1,
                format: (v: number) => String(v),
              },
              {
                key: "zoomRange",
                label: "Zoom range",
                min: 1.5,
                max: 8,
                step: 0.1,
                format: (v: number) => v.toFixed(1),
              },
              {
                key: "foldWindow",
                label: "Fold window",
                min: 0.05,
                max: 0.5,
                step: 0.01,
                format: (v: number) => v.toFixed(2),
              },
              {
                key: "wheelSensitivity",
                label: "Wheel sens.",
                min: 0.00005,
                max: 0.0008,
                step: 0.00001,
                format: (v: number) => v.toFixed(5),
              },
              {
                key: "unitDiameter",
                label: "Unit Ø",
                min: 18,
                max: 56,
                step: 1,
                format: (v: number) => String(v),
              },
              {
                key: "landmarkBoost",
                label: "Landmark ×",
                min: 1,
                max: 1.6,
                step: 0.05,
                format: (v: number) => v.toFixed(2),
              },
              {
                key: "dialSettleMs",
                label: "Settle ms",
                min: 40,
                max: 400,
                step: 10,
                format: (v: number) => String(v),
              },
            ] as const
          ).map((field) => (
            <label key={field.key} className="ambient-mass__lod-field">
              <span>
                {field.label}
                <strong>{field.format(lod[field.key])}</strong>
              </span>
              <input
                type="range"
                min={field.min}
                max={field.max}
                step={field.step}
                value={lod[field.key]}
                onChange={(e) =>
                  setLodField(field.key, Number(e.target.value))
                }
              />
            </label>
          ))}
        </div>
      </div>

      <section className="ambient-mass__stage-shell">
        <div className="ambient-mass__stage" ref={containerRef} />
      </section>
    </main>
  );
}
