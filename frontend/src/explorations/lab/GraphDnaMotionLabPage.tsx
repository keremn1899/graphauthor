import {
  Graph,
  type EdgeData,
  type GraphData,
  type IElementEvent,
  type NodeData,
} from "@antv/g6";
import {
  type CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
// Typeface alternatives are scoped to this explicit workbench. The real
// product entry remains Jost-only until a later identity decision is made.
import "@fontsource/archivo/latin-500.css";
import "@fontsource/archivo/latin-600.css";
import "@fontsource/archivo-narrow/latin-500.css";
import "@fontsource/archivo-narrow/latin-600.css";
import "@fontsource/asap/latin-500.css";
import "@fontsource/asap/latin-600.css";
import "@fontsource/asap-condensed/latin-500.css";
import "@fontsource/asap-condensed/latin-600.css";
import "@fontsource/cabin/latin-500.css";
import "@fontsource/cabin/latin-600.css";
import "@fontsource/chivo/latin-500.css";
import "@fontsource/chivo/latin-600.css";
import "@fontsource/dm-sans/latin-500.css";
import "@fontsource/dm-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans-condensed/latin-500.css";
import "@fontsource/ibm-plex-sans-condensed/latin-600.css";
import "@fontsource/instrument-serif/latin-400.css";
import "@fontsource/josefin-sans/latin-500.css";
import "@fontsource/josefin-sans/latin-600.css";
import {
  CIRCLE_NODE_FONT_IDS,
  NODE_FONTS,
} from "../g6/graphOptions";
import {
  type GraphDnaTheme,
  mixHex,
  type RadixScaleId,
  type RadixToken,
  radixValue,
  type ThemeMode,
} from "../../styles/graphDna";
import {
  DNA_PARAM_DEFAULTS,
  readDnaParams,
  writeDnaParams,
  type DnaParams,
} from "../dnaParamsStore";
import {
  createMotionPlans,
  gravityDurationMs,
  gravityLaunchImpulse,
  gravityPullForDuration,
  gravityStrengthForDuration,
  motionCssVariables,
  motionPoseKeyframes,
  MOTION_DURATION_MS,
  MOTION_SPINE,
  type MotionPlans,
} from "../../styles/motion";
import { g6StateMotion } from "../../styles/motionG6";
import { useMotion } from "../../styles/useMotion";
import {
  arrowSizeForKind,
  isDirectedKind,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import {
  AMBIENT_LINKAGE_EDGE,
  ensureAmbientLinkageEdgeRegistered,
} from "./ambientLinkageEdge";
import { createAmbientLodGraph } from "./ambientLodData";
import {
  applyAmbientSeamMode,
  type AmbientSeamMode,
} from "./ambientSeamModes";
import { SelectionAntRing } from "../SelectionAntRing";
import { RegionalMassLodSection } from "../RegionalMassLodSection";
import {
  fetchMap,
  isLiveMode,
  listGraphs,
  type GraphMap,
} from "../../api/graph";
import { useResource } from "../../api/resource";
import { displayPositions } from "../../product/graphModel";
import "../../styles/fonts.css";
import {
  type FrameStat,
  frameSummary,
  sampleFrames,
  verdictFor,
} from "./frameSampler";
import "./GraphDnaMotionLabPage.css";

/**
 * The scales this workbench offers in its picker — a curated subset, not the
 * whole Radix catalogue. The *types* come from `styles/graphDna`; this is UI
 * data.
 */
const RADIX_SCALE_IDS: readonly RadixScaleId[] = [
  "gray",
  "mauve",
  "slate",
  "sage",
  "olive",
  "sand",
  "tomato",
  "red",
  "ruby",
  "crimson",
  "pink",
  "plum",
  "purple",
  "violet",
  "iris",
  "indigo",
  "blue",
  "cyan",
  "teal",
  "jade",
  "green",
  "grass",
  "brown",
  "bronze",
  "gold",
  "sky",
  "mint",
  "lime",
  "yellow",
  "amber",
  "orange",
  "black",
  "grayDark",
  "mauveDark",
  "slateDark",
  "sageDark",
  "oliveDark",
  "sandDark",
  "tomatoDark",
  "redDark",
  "rubyDark",
  "crimsonDark",
  "pinkDark",
  "plumDark",
  "purpleDark",
  "violetDark",
  "irisDark",
  "indigoDark",
  "blueDark",
  "cyanDark",
  "tealDark",
  "jadeDark",
  "greenDark",
  "grassDark",
  "brownDark",
  "bronzeDark",
  "goldDark",
  "skyDark",
  "mintDark",
  "limeDark",
  "yellowDark",
  "amberDark",
  "orangeDark",
] as const;

type ViewMode = "ambient" | "focus" | "proposal" | "diff";
type DiffKind = "added" | "removed" | "touched" | "unchanged";
/** The idle look is defined once, in `styles/graphDna`. */
type ThemeTokens = GraphDnaTheme;

type FocusTokens = {
  field: RadixToken;
  lit: RadixToken;
  dimNode: RadixToken;
  dimEdge: RadixToken;
  litLabel: RadixToken;
  dimLabel: RadixToken;
  chip: RadixToken;
  lensLabel: RadixToken;
  bondLabel: RadixToken;
};

type ResolvedTheme = Record<keyof ThemeTokens, string>;
type ResolvedFocus = Record<keyof FocusTokens, string>;
type HoverBundle = { out: Set<string>; inn: Set<string> };

const DEFAULTS = DNA_PARAM_DEFAULTS;

const SOURCE_GRAPH = createAmbientLodGraph();

/** A controlled crop of the visible Ambient Canvas fixture. */
const WORKBENCH_NODE_IDS = new Set([
  "ownership-rule",
  "order-ledger",
  "checkout-api",
  "service-boundary",
  "dependency-direction-rule",
  "domain-package",
  "adapter-package",
  "funnel-jobs",
  "metrics-lake",
  "commerce",
  "payments",
  "sku-1",
  "ports-inward-policy",
  "import-boundary",
]);

const WORKBENCH_POSITIONS: Record<string, { x: number; y: number }> = {
  "ownership-rule": { x: 130, y: 130 },
  "checkout-api": { x: 360, y: 90 },
  "order-ledger": { x: 610, y: 130 },
  "service-boundary": { x: 370, y: 250 },
  "dependency-direction-rule": { x: 370, y: 390 },
  "domain-package": { x: 220, y: 520 },
  "adapter-package": { x: 520, y: 520 },
  "funnel-jobs": { x: 90, y: 360 },
  "metrics-lake": { x: 90, y: 520 },
  commerce: { x: 730, y: 260 },
  payments: { x: 730, y: 430 },
  "sku-1": { x: 760, y: 90 },
  "ports-inward-policy": { x: 250, y: 650 },
  "import-boundary": { x: 500, y: 650 },
};

const VIEW_CONTRACT = [
  {
    title: "Ambient",
    source: "Committed graph version",
    rule: "Quiet inspection. Proposal encoding is absent.",
  },
  {
    title: "Focus",
    source: "Ledger subject_node_ids",
    rule: "Group or single focus is entered from Ledger.",
  },
  {
    title: "Proposal",
    source: "Ledger proposal encoding",
    rule: "Encoding is grafted into a solid charcoal spotlight.",
  },
  {
    title: "Version diff",
    source: "graph_version_before → graph_version_after",
    rule: "Added, removed, and touched matter use the Ambient Canvas vocabulary.",
  },
] as const;

function initialViewMode(): ViewMode {
  const value = new URLSearchParams(
    window.location.hash.split("?")[1] ?? "",
  ).get("view");
  return value === "focus" || value === "proposal" || value === "diff"
    ? value
    : "ambient";
}

function resolveRecord<T extends Record<string, RadixToken>>(
  values: T,
): Record<keyof T, string> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key, radixValue(value)]),
  ) as Record<keyof T, string>;
}

function resolvedTheme(params: DnaParams, mode: ThemeMode): ResolvedTheme {
  return resolveRecord(params[mode]);
}

function resolvedFocus(params: DnaParams): ResolvedFocus {
  return resolveRecord(params.focus);
}

function intensityOf(datum: NodeData | EdgeData) {
  const value = Number(datum.data?.intensity);
  return Number.isFinite(value) ? value : 0;
}

function isFocusLit(datum: NodeData | EdgeData) {
  return intensityOf(datum) >= 1;
}

function diffOf(datum: NodeData | EdgeData): DiffKind {
  const value = String(datum.data?.diff ?? "unchanged");
  return value === "added" || value === "removed" || value === "touched"
    ? value
    : "unchanged";
}

function lensOf(datum: EdgeData) {
  const value = Number(datum.data?.lens);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

function bondOf(datum: EdgeData) {
  const value = Number(datum.data?._bond);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

/** Live map currently open on the operator — set by the workbench page. */
let liveMapSource: GraphMap | null = null;
let liveSpacing = 1;

function setLiveMapSource(map: GraphMap | null, spacing: number) {
  liveMapSource = map;
  liveSpacing = spacing;
}

function fixtureDataForMode(mode: ViewMode): GraphData {
  const seamMode: AmbientSeamMode =
    mode === "ambient"
      ? "idle"
      : mode === "focus"
        ? "focus-group"
        : mode === "proposal"
          ? "proposal"
          : "version-diff";
  const source = applyAmbientSeamMode(SOURCE_GRAPH, seamMode).data;
  const nodes: NodeData[] = (source.nodes ?? [])
    .filter((node) => WORKBENCH_NODE_IDS.has(String(node.id)))
    .map((node) => ({
      ...node,
      data: { ...node.data },
      style: {
        ...node.style,
        ...(WORKBENCH_POSITIONS[String(node.id)] ?? {}),
      },
    }));
  const admitted = new Set(nodes.map((node) => String(node.id)));
  const edges: EdgeData[] = (source.edges ?? [])
    .filter(
      (edge) =>
        admitted.has(String(edge.source)) &&
        admitted.has(String(edge.target)),
    )
    .map((edge) => ({
      ...edge,
      data: {
        ...edge.data,
        lens: 0,
        _lp: 0.5,
        _bond: 0,
        _bondSide: "source",
      },
      style: { ...edge.style },
    }));
  return { nodes, edges };
}

/**
 * The product graph — same arrangement the Graph page draws — with DNA view
 * modes overlaid as intensity / proposal / diff annotations.
 */
function liveDataForMode(map: GraphMap, mode: ViewMode, spacing: number): GraphData {
  const positions = displayPositions(map, spacing);
  const ranked = [...map.nodes].sort(
    (a, b) => (b.betweenness ?? 0) - (a.betweenness ?? 0),
  );
  const focusSeed = new Set(
    ranked.slice(0, Math.min(8, Math.max(3, Math.floor(ranked.length / 8)))).map(
      (node) => node.id,
    ),
  );
  // Neighbourhood of seeds for a readable focus cluster.
  if (mode === "focus" || mode === "proposal") {
    for (const edge of map.edges) {
      if (focusSeed.has(edge.source)) focusSeed.add(edge.target);
      if (focusSeed.has(edge.target)) focusSeed.add(edge.source);
    }
  }
  const added = new Set(ranked.slice(0, 3).map((node) => node.id));
  const removed = new Set(ranked.slice(3, 5).map((node) => node.id));
  const touched = new Set(ranked.slice(5, 8).map((node) => node.id));

  const nodes: NodeData[] = map.nodes.map((node) => {
    const inFocus = focusSeed.has(node.id);
    let intensity = 0;
    let proposed = false;
    let diff: DiffKind = "unchanged";
    if (mode === "focus") intensity = inFocus ? 1 : 0;
    if (mode === "proposal") {
      intensity = inFocus ? 1 : 0;
      proposed = inFocus && added.has(node.id);
    }
    if (mode === "diff") {
      if (added.has(node.id)) {
        diff = "added";
        intensity = 1;
      } else if (removed.has(node.id)) {
        diff = "removed";
        intensity = 1;
      } else if (touched.has(node.id)) {
        diff = "touched";
        intensity = 1;
      }
    }
    const point = positions.get(node.id) ?? { x: node.x, y: node.y };
    return {
      id: node.id,
      data: {
        label: node.label,
        semantic_anchor: node.semantic_anchor,
        intensity,
        proposed,
        diff,
      },
      style: { x: point.x, y: point.y },
    };
  });
  const edges: EdgeData[] = map.edges.map((edge, index) => ({
    id: `e${index}`,
    source: edge.source,
    target: edge.target,
    data: {
      type: edge.type,
      kind: edge.type.toLowerCase(),
      label: edge.label || edge.type,
      intensity:
        mode === "ambient"
          ? 0
          : focusSeed.has(edge.source) || focusSeed.has(edge.target)
            ? 1
            : 0,
      lens: 0,
      _lp: 0.5,
      _bond: 0,
      _bondSide: "source",
      diff: "unchanged",
    },
  }));
  return { nodes, edges };
}

function dataForMode(mode: ViewMode): GraphData {
  if (liveMapSource) return liveDataForMode(liveMapSource, mode, liveSpacing);
  return fixtureDataForMode(mode);
}

function seedSelectionId(data: GraphData): string | null {
  const nodes = data.nodes ?? [];
  if (!nodes.length) return null;
  const lit = nodes.find((node) => Number(node.data?.intensity) >= 1);
  return String((lit ?? nodes[0])?.id ?? "") || null;
}

function distPointToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-8) return Math.hypot(px - ax, py - ay);
  const t = Math.max(
    0,
    Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2),
  );
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function closestTOnSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-8) return 0.5;
  return Math.max(
    0,
    Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2),
  );
}

function lensFalloff(distance: number, radius: number) {
  if (distance >= radius) return 0;
  const t = 1 - distance / radius;
  return 0.5 - 0.5 * Math.cos(Math.PI * t);
}

function emptyHoverBundle(): HoverBundle {
  return { out: new Set(), inn: new Set() };
}

function plansFor(params: DnaParams): MotionPlans {
  return createMotionPlans(
    {
      gravity: params.gravityStrength,
      travel: params.gravityTravel,
      absorbPull: params.absorbPull,
    },
    {
      emit: params.motionEmit,
      absorb: params.motionAbsorb,
      settle: params.motionSettle,
      hold: MOTION_DURATION_MS.hold,
    },
  );
}

function hoverBundleFor(graph: Graph, nodeId: string): HoverBundle {
  const bundle = emptyHoverBundle();
  for (const edge of graph.getRelatedEdgesData(nodeId)) {
    if (isFocusLit(edge)) continue;
    const id = String(edge.id);
    if (String(edge.source) === nodeId) bundle.out.add(id);
    else bundle.inn.add(id);
  }
  return bundle;
}

function RangeControl({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="gdna__range">
      <span>
        {label}
        <output>
          {value}
          {unit}
        </output>
      </span>
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function RadixControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: RadixToken;
  onChange: (value: RadixToken) => void;
}) {
  return (
    <label className="gdna__radix">
      <span>{label}</span>
      <i style={{ background: radixValue(value) }} />
      <select
        value={value.scale}
        onChange={(event) =>
          onChange({
            ...value,
            scale: event.target.value as RadixScaleId,
          })
        }
      >
        {RADIX_SCALE_IDS.map((scale) => (
          <option key={scale} value={scale}>
            {scale}
          </option>
        ))}
      </select>
      <select
        value={value.step}
        aria-label={`${label} Radix step`}
        onChange={(event) =>
          onChange({ ...value, step: Number(event.target.value) })
        }
      >
        {Array.from({ length: 12 }, (_, index) => index + 1).map((step) => (
          <option key={step} value={step}>
            {step}
          </option>
        ))}
      </select>
    </label>
  );
}

function humanizeKey(value: string) {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
}

function MotionParityPanel({
  motion,
  gravityTravel,
  gripScale,
  ink,
  surface,
}: {
  motion: MotionPlans;
  gravityTravel: number;
  gripScale: number;
  ink: string;
  surface: string;
}) {
  const mass = useMotion<HTMLDivElement>();
  const ring = useMotion<SVGSVGElement>();
  const row = useMotion<HTMLElement>();
  const [selected, setSelected] = useState(true);
  const [arrivalRun, setArrivalRun] = useState(0);

  useEffect(() => {
    row.play(
      motionPoseKeyframes(
        { y: -gravityTravel, scale: 0.994, opacity: 0 },
        { y: 0, scale: 1, opacity: 1 },
      ),
      motion.emit,
      { fill: "backwards" },
    );
  }, [arrivalRun, gravityTravel, motion.emit, row]);

  useEffect(() => {
    ring.play(
      motionPoseKeyframes(
        selected
          ? { scale: 0.76, opacity: 0 }
          : { scale: 1, opacity: 1 },
        selected
          ? { scale: 1, opacity: 1 }
          : { scale: 0.76, opacity: 0 },
      ),
      selected ? motion.emit : motion.absorb,
      { fill: "forwards" },
    );
  }, [motion.absorb, motion.emit, ring, selected]);

  const setHeld = (held: boolean) => {
    mass.play(
      motionPoseKeyframes(
        { scale: held ? 1 : gripScale },
        { scale: held ? gripScale : 1 },
      ),
      held ? motion.hold : motion.settle,
      { fill: "forwards" },
    );
  };

  return (
    <aside
      className="gdna__motion-parity"
      style={{ "--parity-ink": ink, "--parity-surface": surface } as CSSProperties}
      aria-label="DOM motion parity reference"
    >
      <header>
        <strong>Same field · DOM</strong>
        <span>React Web Animations adapter</span>
      </header>

      <div className="gdna__parity-node-area">
        <div className="gdna__parity-mass" ref={mass.ref}>
          <svg
            ref={ring.ref}
            className="gdna__parity-ring"
            viewBox="0 0 92 92"
            aria-hidden="true"
          >
            <circle
              cx="46"
              cy="46"
              r="43"
              pathLength="100"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeDasharray="0 6"
            />
          </svg>
          <button
            type="button"
            className="gdna__parity-node"
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              setHeld(true);
            }}
            onPointerUp={() => setHeld(false)}
            onPointerCancel={() => setHeld(false)}
            onClick={() => setSelected((value) => !value)}
          >
            DOM matter
          </button>
        </div>
        <p>Press for hold/settle · click for emit/absorb</p>
      </div>

      <article className="gdna__parity-row" ref={row.ref}>
        <i />
        <span>
          <strong>Authority became human</strong>
          <small>Activity arrival · same emit plan</small>
        </span>
      </article>
      <button
        type="button"
        className="gdna__parity-replay"
        onClick={() => setArrivalRun((run) => run + 1)}
      >
        Replay DOM arrival
      </button>

      <dl>
        <div>
          <dt>gravity</dt>
          <dd>{Math.round(motion.emit.field.gravity)} px/s²</dd>
        </div>
        <div>
          <dt>travel</dt>
          <dd>{motion.emit.field.travel.toFixed(1)} px</dd>
        </div>
        <div>
          <dt>emit</dt>
          <dd>{motion.emit.durationMs} ms</dd>
        </div>
        <div>
          <dt>settle</dt>
          <dd>{motion.settle.durationMs} ms</dd>
        </div>
      </dl>
    </aside>
  );
}

export function GraphDnaMotionLabPage() {
  const [params, setParams] = useState(() => readDnaParams());
  const [themeMode, setThemeMode] = useState<ThemeMode>("light");
  const [mode, setMode] = useState<ViewMode>(initialViewMode);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [note, setNote] = useState(
    "Ambient graph. Move across a filament or hover a node to reveal relationship type.",
  );
  const [ready, setReady] = useState(false);
  const [copied, setCopied] = useState(false);
  /**
   * What the motion costs, and what the same map costs with none running.
   *
   * This page keeps motion and interaction *on* against the live product
   * graph, which is what makes it the right place to tune the DNA — and it
   * could show every parameter without ever saying what one costs. Emit,
   * absorb and settle were chosen by eye on an 11-node map.
   *
   * Both arms are needed: at 2000 nodes the canvas drops frames by itself, so
   * an absolute reading condemns the graph and blames the animation. Open a
   * larger map with `Open Graph`, measure the idle arm, then run the motion.
   */
  const [frameStat, setFrameStat] = useState<FrameStat | null>(null);
  const [frameBase, setFrameBase] = useState<FrameStat | null>(null);
  const [sampling, setSampling] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const paramsRef = useRef(params);
  const modeRef = useRef(mode);
  const themeModeRef = useRef(themeMode);
  const hoverActiveRef = useRef<HoverBundle>(emptyHoverBundle());
  const dragMotionRef = useRef<"engage" | "release">("engage");
  paramsRef.current = params;
  modeRef.current = mode;
  themeModeRef.current = themeMode;

  const live = useMemo(() => isLiveMode(), []);
  const catalogue = useResource((signal) => listGraphs(signal), {
    enabled: live,
    watch: "graph",
  });
  const selectedGraphId = useMemo(() => {
    const rows = catalogue.data ?? [];
    return (
      rows.find((row) => row.is_current)?.id ??
      rows.find((row) => (row.node_count ?? 0) > 0)?.id ??
      rows[0]?.id
    );
  }, [catalogue.data]);
  const mapRead = useResource(
    (signal) => fetchMap(selectedGraphId, signal),
    {
      enabled: live && Boolean(selectedGraphId),
      deps: [selectedGraphId],
      watch: "graph",
      fallbackError: "Could not read the live graph.",
    },
  );
  const liveMap = mapRead.data ?? null;
  /** Nodes actually on screen — the size any frame verdict is true of. */
  const liveNodeCount = liveMap?.nodes.length ?? 0;
  const liveLabel =
    catalogue.data?.find((row) => row.id === selectedGraphId)?.label ??
    selectedGraphId ??
    "";

  useEffect(() => {
    writeDnaParams(params);
  }, [params]);

  useEffect(() => {
    setLiveMapSource(liveMap, params.spacing);
  }, [liveMap, params.spacing]);

  // A different map is a different size, and a baseline taken on the last one
  // would silently make the next verdict a comparison between two graphs.
  useEffect(() => {
    setFrameBase(null);
    setFrameStat(null);
  }, [liveNodeCount]);

  // When the live map arrives or spacing changes, refresh the specimen in place.
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !ready || !liveMap) return;
    setLiveMapSource(liveMap, params.spacing);
    const next = dataForMode(modeRef.current);
    graph.setData(next);
    void graph
      .draw()
      .then(async () => {
        await graph.fitView();
        if (!graph.destroyed) setSelectedId(seedSelectionId(next));
      })
      .catch(() => {});
  }, [liveMap, params.spacing, ready]);

  const patch = <K extends keyof DnaParams>(key: K, value: DnaParams[K]) =>
    setParams((current) => ({ ...current, [key]: value }));

  const patchTheme = <K extends keyof ThemeTokens>(
    theme: ThemeMode,
    key: K,
    value: ThemeTokens[K],
  ) =>
    setParams((current) => ({
      ...current,
      [theme]: { ...current[theme], [key]: value },
    }));

  const patchFocus = <K extends keyof FocusTokens>(
    key: K,
    value: FocusTokens[K],
  ) =>
    setParams((current) => ({
      ...current,
      focus: { ...current.focus, [key]: value },
    }));

  const patchGravityStrength = (gravityStrength: number) =>
    setParams((current) => ({
      ...current,
      gravityStrength,
      motionEmit: gravityDurationMs(
        current.gravityTravel,
        gravityStrength,
      ),
      motionAbsorb: gravityDurationMs(
        current.gravityTravel,
        gravityStrength,
        current.absorbPull,
      ),
    }));

  const patchGravityTravel = (gravityTravel: number) =>
    setParams((current) => ({
      ...current,
      gravityTravel,
      motionEmit: gravityDurationMs(
        gravityTravel,
        current.gravityStrength,
      ),
      motionAbsorb: gravityDurationMs(
        gravityTravel,
        current.gravityStrength,
        current.absorbPull,
      ),
    }));

  const patchAbsorbPull = (absorbPull: number) =>
    setParams((current) => ({
      ...current,
      absorbPull,
      motionAbsorb: gravityDurationMs(
        current.gravityTravel,
        current.gravityStrength,
        absorbPull,
      ),
    }));

  const patchEmitDuration = (motionEmit: number) =>
    setParams((current) => {
      const gravityStrength = gravityStrengthForDuration(
        current.gravityTravel,
        motionEmit,
      );
      return {
        ...current,
        gravityStrength,
        motionEmit,
        motionAbsorb: gravityDurationMs(
          current.gravityTravel,
          gravityStrength,
          current.absorbPull,
        ),
      };
    });

  const patchAbsorbDuration = (motionAbsorb: number) =>
    setParams((current) => ({
      ...current,
      motionAbsorb,
      absorbPull: gravityPullForDuration(
        current.gravityTravel,
        current.gravityStrength,
        motionAbsorb,
      ),
    }));

  const nodeOptions = useCallback(() => {
    const p = paramsRef.current;
    const activeMode = modeRef.current;
    const theme = resolvedTheme(p, themeModeRef.current);
    const focus = resolvedFocus(p);
    const motion = plansFor(p);
    const inverted = activeMode !== "ambient";
    const nodeLineWidth = (datum: NodeData) =>
      inverted && diffOf(datum) !== "unchanged"
        ? p.nodeLine + 0.5
        : p.nodeLine;
    const dragMotion = dragMotionRef.current;
    return {
      type: "circle",
      style: {
        size: p.nodeDiameter,
        fill: (datum: NodeData) => {
          if (!inverted) return theme.node;
          const diff = diffOf(datum);
          if (diff === "added") return focus.lit;
          if (diff === "removed") return focus.field;
          return isFocusLit(datum) ? focus.lit : focus.dimNode;
        },
        stroke: (datum: NodeData) => {
          if (!inverted) return theme.node;
          return diffOf(datum) !== "unchanged" || isFocusLit(datum)
            ? focus.lit
            : focus.dimNode;
        },
        lineWidth: nodeLineWidth,
        lineDash: (datum: NodeData) =>
          inverted && diffOf(datum) === "removed"
            ? [0, p.dottedGap]
            : [],
        lineCap: "round" as const,
        halo: false,
        badge: false,
        labelText: (datum: NodeData) =>
          String(datum.data?.label ?? ""),
        labelFill: (datum: NodeData) => {
          if (!inverted) return theme.nodeLabel;
          const diff = diffOf(datum);
          if (diff === "added" || isFocusLit(datum)) return focus.litLabel;
          if (diff === "removed" || diff === "touched") return focus.lit;
          return focus.dimLabel;
        },
        labelFontFamily: NODE_FONTS[p.labelFontId].family,
        labelFontSize: p.labelSize,
        labelFontWeight: p.labelFontWeight,
        labelLineHeight: p.labelSize * 1.15,
        labelPlacement: "center" as const,
        labelWordWrap: true,
        // Resolve wrapping against canonical node geometry. Drag compression
        // scales this already-laid-out label as one shape, so line breaks can
        // never change during the gesture.
        labelMaxWidth: p.nodeDiameter * (p.labelMaxWidth / 100),
        labelMaxLines: 2,
        labelTextOverflow: "ellipsis",
        labelTransform: [["scale", 1, 1]] as [
          ["scale", number, number],
        ],
        // Center-placed labels are authored at the node-local origin. Using
        // explicit pixels avoids G's percentage-origin geometry pass, which
        // runs before the Label's text/background children exist.
        labelTransformOrigin: "0px 0px",
        cursor: "grab" as const,
      },
      state: {
        selected: { halo: false, haloStrokeOpacity: 0 },
        active: { halo: false, haloStrokeOpacity: 0 },
        dragLoad: {
          lineWidth: (datum: NodeData) =>
            p.dragTreatment === "weight"
              ? Math.max(
                  0.35,
                  nodeLineWidth(datum) - p.dragNodeRelief,
                )
              : nodeLineWidth(datum),
          size:
            p.dragTreatment === "compression"
              ? p.nodeDiameter * p.dragCompression
              : p.nodeDiameter,
          labelTransform: [
            [
              "scale",
              p.dragTreatment === "compression"
                ? p.dragCompression
                : 1,
              p.dragTreatment === "compression"
                ? p.dragCompression
                : 1,
            ],
          ] as [["scale", number, number]],
        },
      },
      animation: {
        enter: false as const,
        update: false as const,
        exit: false as const,
        show: false as const,
        hide: false as const,
        translate: false as const,
        state: [
          g6StateMotion(
            dragMotion === "engage" ? motion.hold : motion.settle,
            {
            fields: ["lineWidth", "size"],
            },
          ),
          g6StateMotion(
            dragMotion === "engage" ? motion.hold : motion.settle,
            { shape: "label", fields: ["transform"] },
          ),
        ],
      },
    };
  }, []);

  const edgeOptions = useCallback(() => {
    const p = paramsRef.current;
    const activeMode = modeRef.current;
    const theme = resolvedTheme(p, themeModeRef.current);
    const focus = resolvedFocus(p);
    const inverted = activeMode !== "ambient";
    const focusTyped = (datum: EdgeData) =>
      inverted && isFocusLit(datum);
    const arrowPresence = (datum: EdgeData) =>
      focusTyped(datum) ? 1 : bondOf(datum);
    const restingStroke = (datum: EdgeData) => {
      if (!inverted) return theme.filament;
      const lens = lensOf(datum);
      return mixHex(
        isFocusLit(datum) ? focus.lit : focus.dimEdge,
        focus.lit,
        lens * 0.82,
      );
    };
    const restingLineWidth = (datum: EdgeData) =>
      p.edgeWidth + 0.55 * lensOf(datum) + 0.65 * bondOf(datum);
    const restingOpacity = (datum: EdgeData) =>
      inverted
        ? 1
        : Math.min(
            1,
            p.edgeOpacity +
              0.25 * lensOf(datum) +
              (1 - p.edgeOpacity) * bondOf(datum),
          );
    const dragMotion = dragMotionRef.current;
    return {
      type: AMBIENT_LINKAGE_EDGE,
      style: {
        edgeKind: (datum: EdgeData) => linkageEdgeKind(datum),
        pointerEvents: "none" as const,
        stroke: (datum: EdgeData) =>
          mixHex(
            restingStroke(datum),
            inverted ? focus.bondLabel : theme.filament,
            bondOf(datum),
          ),
        lineWidth: restingLineWidth,
        strokeOpacity: 1,
        opacity: restingOpacity,
        lineDash: (datum: EdgeData) =>
          inverted && diffOf(datum) === "removed"
            ? [0, p.dottedGap]
            : [],
        lineCap: "round" as const,
        lineJoin: "round" as const,
        // Keep directed arrow matter mounted at zero opacity so hover can
        // reveal it continuously rather than create it with a pop.
        endArrow: (datum: EdgeData) =>
          isDirectedKind(linkageEdgeKind(datum)),
        endArrowType: "triangle" as const,
        endArrowSize: (datum: EdgeData) =>
          arrowSizeForKind(linkageEdgeKind(datum)) *
          Math.max(0.02, arrowPresence(datum)),
        endArrowFill: inverted ? focus.lit : theme.filament,
        endArrowFillOpacity: arrowPresence,
        endArrowStrokeOpacity: arrowPresence,
        endArrowOffset: (datum: EdgeData) =>
          arrowSizeForKind(linkageEdgeKind(datum)) *
            arrowPresence(datum) /
            2 +
          arrowPresence(datum),
        labelText: (datum: EdgeData) => String(datum.data?.label ?? ""),
        labelFontFamily: NODE_FONTS[p.labelFontId].family,
        labelFontSize: p.edgeLabelSize,
        labelFill: (datum: EdgeData) => {
          const lensColor = inverted ? focus.lensLabel : theme.lensLabel;
          const bondColor = inverted ? focus.lit : theme.bondLabel;
          return mixHex(lensColor, bondColor, bondOf(datum));
        },
        labelBackground: true,
        labelBackgroundFill: inverted ? focus.chip : theme.chip,
        labelBackgroundOpacity: (datum: EdgeData) =>
          focusTyped(datum) || lensOf(datum) > 0 || bondOf(datum) > 0
            ? 1
            : 0,
        labelOpacity: (datum: EdgeData) =>
          focusTyped(datum)
            ? 1
            : Math.max(lensOf(datum), bondOf(datum)),
        labelPadding: [2, 3] as [number, number],
        labelAutoRotate: false,
        labelPlacement: 0.5,
        increasedLineWidthForHitTesting: 20,
      },
      state: {
        selected: { halo: false, haloStrokeOpacity: 0 },
        active: { halo: false, haloStrokeOpacity: 0 },
        dragLoad: {
          lineWidth: (datum: EdgeData) =>
            restingLineWidth(datum) +
            (p.dragTreatment === "weight" ? p.dragEdgeLoad : 0),
          opacity: (datum: EdgeData) =>
            Math.min(
              1,
              restingOpacity(datum) +
                (p.dragTreatment === "weight"
                  ? p.dragEdgePresence
                  : 0),
            ),
        },
      },
      animation: {
        enter: false as const,
        update: false as const,
        exit: false as const,
        show: false as const,
        hide: false as const,
        translate: false as const,
        state: [
          {
            fields: ["lineWidth", "opacity"],
            duration:
              dragMotion === "engage"
                ? MOTION_DURATION_MS.hold
                : p.motionSettle,
            easing:
              dragMotion === "engage"
                ? "linear"
                : MOTION_SPINE.settle.css,
          },
        ],
      },
    };
  }, []);

  const selectNode = useCallback((id: string) => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !graph.getNodeData(id)) return;
    setSelectedId(id);
    setNote(
      `${String(graph.getNodeData(id)?.data?.label ?? id)} selected. This cue will hand off to node content and history.`,
    );
  }, []);

  useEffect(() => {
    if (!stageRef.current) return;
    ensureAmbientLinkageEdgeRegistered();
    const graph = new Graph({
      container: stageRef.current,
      data: dataForMode("ambient"),
      // Element stages opt in individually. This keeps lens/data draws
      // immediate while allowing the bounded drag-load state to interpolate.
      animation: true,
      autoFit: {
        type: "view",
        options: { when: "always", direction: "both" },
        animation: false,
      },
      padding: [68, 86, 70, 86],
      node: nodeOptions(),
      edge: edgeOptions() as never,
      behaviors: ["drag-canvas", "zoom-canvas", "drag-element"],
    });
    graphRef.current = graph;
    let leaveTimer = 0;
    let hoverRaf = 0;
    let bondRaf = 0;
    let bondGeneration = 0;
    let pendingHover: HoverBundle | null = null;
    let suppressedSelection: { id: string; until: number } | null = null;
    let dragLoadIds = new Set<string>();
    let nodeDragActive = false;
    let compressionHeldId: string | null = null;

    const setDragLoad = (
      nodeId: string,
      active: boolean,
      phase: "engage" | "release",
    ) => {
      if (graph.destroyed) return;
      const ids = active
        ? new Set([
            nodeId,
            ...(paramsRef.current.dragTreatment === "weight"
              ? graph
                  .getRelatedEdgesData(nodeId)
                  .map((edge) => String(edge.id))
              : []),
          ])
        : dragLoadIds;
      if (!ids.size) return;
      dragLoadIds = active ? ids : new Set();
      dragMotionRef.current = phase;
      // Animation timing is stage configuration in G6, so refresh the
      // config before entering or leaving the same semantic state.
      graph.setNode(nodeOptions());
      graph.setEdge(edgeOptions() as never);
      const states: Record<string, string[]> = {};
      for (const id of ids) {
        const current = graph.getElementState(id);
        states[id] = active
          ? [...current.filter((state) => state !== "dragLoad"), "dragLoad"]
          : current.filter((state) => state !== "dragLoad");
      }
      void graph.setElementState(states, true).catch(() => {});
    };

    const releaseCompressionHold = (nodeId?: string) => {
      const id = nodeId || compressionHeldId;
      if (!id || compressionHeldId !== id) return;
      compressionHeldId = null;
      setDragLoad(id, false, "release");
      if (!nodeDragActive) setDraggingId(null);
    };

    const commitHover = (next: HoverBundle) => {
      if (graph.destroyed) return;
      const previous = hoverActiveRef.current;
      const ids = new Set([
        ...previous.out,
        ...previous.inn,
        ...next.out,
        ...next.inn,
      ]);
      const transitions = [...ids].flatMap((id) => {
        const edge = graph.getEdgeData(id);
        if (!edge) return [];
        const entering = next.out.has(id) || next.inn.has(id);
        return [
          {
            id,
            from: bondOf(edge),
            to: entering ? 1 : 0,
            side: next.inn.has(id)
              ? "target"
              : next.out.has(id)
                ? "source"
                : String(edge.data?._bondSide ?? "source"),
          },
        ];
      });
      hoverActiveRef.current = next;
      if (!transitions.length) return;

      if (bondRaf) cancelAnimationFrame(bondRaf);
      const generation = ++bondGeneration;
      const startedAt = performance.now();
      const duration = Math.max(1, paramsRef.current.hoverResponse);

      const tick = async (now: number) => {
        bondRaf = 0;
        if (graph.destroyed || generation !== bondGeneration) return;
        const progress = Math.max(0, Math.min(1, (now - startedAt) / duration));
        const updates = transitions.map((transition) => {
          const edge = graph.getEdgeData(transition.id);
          const curve =
            transition.to > transition.from
              ? MOTION_SPINE.emit
              : MOTION_SPINE.absorb;
          const eased = curve.sample(progress);
          return {
            id: transition.id,
            data: {
              ...edge?.data,
              _bond:
                transition.from +
                (transition.to - transition.from) * eased,
              _bondSide: transition.side,
            },
          };
        });
        graph.updateEdgeData(updates);
        await graph.draw().catch(() => {});
        if (
          progress < 1 &&
          !graph.destroyed &&
          generation === bondGeneration
        ) {
          bondRaf = requestAnimationFrame((time) => void tick(time));
        }
      };

      bondRaf = requestAnimationFrame((time) => void tick(time));
    };

    const scheduleHover = (next: HoverBundle) => {
      pendingHover = next;
      if (hoverRaf) return;
      hoverRaf = requestAnimationFrame(() => {
        hoverRaf = 0;
        const bundle = pendingHover ?? emptyHoverBundle();
        pendingHover = null;
        commitHover(bundle);
      });
    };

    const onEnter = (event: IElementEvent) => {
      if (nodeDragActive) return;
      if (leaveTimer) window.clearTimeout(leaveTimer);
      const id = String(event.target?.id ?? "");
      const node = graph.getNodeData(id);
      if (!id || id.startsWith("__") || (node && isFocusLit(node))) {
        scheduleHover(emptyHoverBundle());
        return;
      }
      scheduleHover(hoverBundleFor(graph, id));
    };
    const onLeave = () => {
      if (nodeDragActive) return;
      leaveTimer = window.setTimeout(
        () => scheduleHover(emptyHoverBundle()),
        60,
      );
    };
    const onClick = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      if (!id || id.startsWith("__")) return;
      if (
        suppressedSelection?.id === id &&
        performance.now() < suppressedSelection.until
      ) {
        return;
      }
      selectNode(id);
    };
    const onCanvasClick = () => {
      setSelectedId(null);
      setNote(
        "Selection cleared. The ring is absorbed into its node before leaving the surface.",
      );
    };
    const onDragStart = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      if (!id || id.startsWith("__")) return;
      // A drag is manipulation, never selection. Keep suppression alive
      // through the release because some renderers emit click after dragend.
      nodeDragActive = true;
      suppressedSelection = { id, until: Number.POSITIVE_INFINITY };
      // Manipulation keeps the node's relationship bond legible. The cursor
      // lens yields, but node-hover edge types remain attached to the object.
      commitHover(hoverBundleFor(graph, id));
      setDraggingId(id);
      // Compression engages on held press (pointerdown). Weight transfer
      // still waits for the drag to begin so load only appears with motion.
      if (paramsRef.current.dragTreatment === "weight") {
        setDragLoad(id, true, "engage");
      }
    };
    const onDragEnd = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      nodeDragActive = false;
      if (id) {
        suppressedSelection = { id, until: performance.now() + 240 };
        if (paramsRef.current.dragTreatment === "weight") {
          setDragLoad(id, false, "release");
        } else {
          releaseCompressionHold(id);
        }
      }
      setDraggingId(null);
    };
    const onPointerDown = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      if (!id || id.startsWith("__")) return;
      if (paramsRef.current.dragTreatment !== "compression") return;
      // Local compression is a press response — it should read on held click,
      // before the pointer has moved enough to start a drag.
      if (compressionHeldId && compressionHeldId !== id) {
        releaseCompressionHold(compressionHeldId);
      }
      compressionHeldId = id;
      setDraggingId(id);
      setDragLoad(id, true, "engage");
    };
    const onPointerUp = () => {
      if (!compressionHeldId) return;
      // If a drag is in progress, dragend owns the release so the held scale
      // stays through the gesture. Otherwise this is a press without motion.
      if (nodeDragActive) return;
      releaseCompressionHold();
    };

    graph.on("node:pointerenter", onEnter);
    graph.on("node:pointerleave", onLeave);
    graph.on("node:click", onClick);
    graph.on("canvas:click", onCanvasClick);
    graph.on("node:pointerdown", onPointerDown);
    graph.on("node:dragstart", onDragStart);
    graph.on("node:dragend", onDragEnd);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    graph
      .render()
      .then(() => {
        if (!graph.destroyed) setReady(true);
      })
      .catch((error) => {
        // A graph torn down by this effect's own cleanup rejects whatever
        // render was still in flight. That is a teardown, not a failure — and
        // under StrictMode's double mount it is the *common* path, so logging
        // it printed a red "init failed" on every healthy load and trained the
        // eye to ignore the one that would matter.
        if (graph.destroyed) return;
        console.error("[graph-dna] init failed", error);
        if (graph.getNodeData().length > 0) {
          setReady(true);
          return;
        }
        setNote("G6 could not render the specimen.");
      });

    return () => {
      if (leaveTimer) window.clearTimeout(leaveTimer);
      if (hoverRaf) cancelAnimationFrame(hoverRaf);
      if (bondRaf) cancelAnimationFrame(bondRaf);
      bondGeneration += 1;
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
      graph.destroy();
      graphRef.current = null;
      setReady(false);
    };
  }, [edgeOptions, nodeOptions, selectNode]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !ready) return;
    hoverActiveRef.current = emptyHoverBundle();
    // The mode swap replaces graph data, including the synthetic selection
    // ring. Re-select only after the new specimen has painted.
    setSelectedId(null);
    // Built once. It was built twice — a second full pass over every node and
    // edge, inside the `.then()`, to read a single seed id out of the result.
    // On a 2000-node map that is ~5000 objects allocated and thrown away to
    // obtain one string.
    const next = dataForMode(mode);
    graph.setData(next);
    graph.setNode(nodeOptions());
    graph.setEdge(edgeOptions() as never);
    void graph
      .draw()
      .then(() => {
        // No `fitView` here. A mode change cannot move anything: every mode
        // maps *all* nodes and edges, and positions come from
        // `displayPositions(map, spacing)`, which never sees `mode`. Only
        // `intensity`, `proposed` and `diff` differ. Re-fitting identical
        // bounds is a whole extra camera pass and redraw for a view that is
        // already where it belongs.
        if (!graph.destroyed) setSelectedId(seedSelectionId(next));
      })
      .catch(() => {});

    const notes: Record<ViewMode, string> = {
      ambient: liveMapSource
        ? "Live product graph with DNA motion. Hover a filament or node to reveal relationship type."
        : "Fixture ambient graph. Move across a filament or hover a node to reveal relationship type.",
      focus:
        "Focus vocabulary on the open graph — high-betweenness seeds and their neighbourhood.",
      proposal:
        "Proposal vocabulary — focus field with a grafted subset marked as proposed matter.",
      diff:
        "Version-diff vocabulary — added solid, removed hollow dotted, touched rimmed.",
    };
    setNote(notes[mode]);
  }, [edgeOptions, mode, nodeOptions, ready]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !ready) return;
    graph.setNode(nodeOptions());
    graph.setEdge(edgeOptions() as never);
    void graph.draw().catch(() => {});
  }, [edgeOptions, nodeOptions, params, ready, themeMode]);

  // Ambient Canvas cursor lens: labels emerge continuously near the pointer
  // and sit on the closest point of the filament.
  useEffect(() => {
    const graph = graphRef.current;
    const element = stageRef.current;
    if (!ready || !graph || graph.destroyed || !element) return;

    let previousLens = new Map<string, number>();
    let previousPlacement = new Map<string, number>();
    let pending: { x: number; y: number } | null = null;
    let drawing = false;
    let frame = 0;

    const commit = (
      nextLens: Map<string, number>,
      nextPlacement: Map<string, number>,
    ) => {
      const updates: Array<{ id: string; data: Record<string, unknown> }> = [];
      const seen = new Set<string>();
      for (const [id, lens] of nextLens) {
        seen.add(id);
        const placement = nextPlacement.get(id) ?? 0.5;
        if (
          Math.abs((previousLens.get(id) ?? 0) - lens) < 0.004 &&
          Math.abs((previousPlacement.get(id) ?? 0.5) - placement) < 0.008
        ) {
          continue;
        }
        const edge = graph.getEdgeData(id);
        if (!edge) continue;
        updates.push({
          id,
          data: { ...edge.data, lens, _lp: placement },
        });
      }
      for (const id of previousLens.keys()) {
        if (seen.has(id)) continue;
        const edge = graph.getEdgeData(id);
        if (!edge) continue;
        updates.push({
          id,
          data: {
            ...edge.data,
            lens: 0,
            // Preserve the handoff origin while a node bond owns the label.
            _lp: bondOf(edge) > 0.008 ? edge.data?._lp : 0.5,
          },
        });
      }
      previousLens = nextLens;
      previousPlacement = nextPlacement;
      if (!updates.length) return false;
      graph.updateEdgeData(updates);
      return true;
    };

    const run = async () => {
      frame = 0;
      const point = pending;
      pending = null;
      if (!point || graph.destroyed) return;
      const [cx, cy] = graph.getCanvasByClient([point.x, point.y]);
      const radius =
        paramsRef.current.hoverRadius /
        Math.max(0.05, graph.getZoom() || 1);
      const nextLens = new Map<string, number>();
      const nextPlacement = new Map<string, number>();

      for (const edge of graph.getEdgeData()) {
        if (isFocusLit(edge)) continue;
        try {
          const source = graph.getElementPosition(String(edge.source));
          const target = graph.getElementPosition(String(edge.target));
          const distance = distPointToSegment(
            cx,
            cy,
            source[0],
            source[1],
            target[0],
            target[1],
          );
          const strength = lensFalloff(distance, radius);
          if (strength <= 0.008) continue;
          const id = String(edge.id);
          nextLens.set(id, strength);
          nextPlacement.set(
            id,
            closestTOnSegment(
              cx,
              cy,
              source[0],
              source[1],
              target[0],
              target[1],
            ),
          );
        } catch {
          /* an edge can disappear during a mode swap */
        }
      }

      if (commit(nextLens, nextPlacement)) {
        drawing = true;
        await graph.draw().catch(() => {});
        drawing = false;
      }
      if (pending && !frame) frame = requestAnimationFrame(() => void run());
    };

    const onMove = (event: PointerEvent) => {
      if (event.buttons !== 0) {
        pending = null;
        if (previousLens.size && commit(new Map(), new Map())) {
          void graph.draw().catch(() => {});
        }
        return;
      }
      pending = { x: event.clientX, y: event.clientY };
      if (!drawing && !frame) frame = requestAnimationFrame(() => void run());
    };
    const clear = () => {
      pending = null;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      if (commit(new Map(), new Map())) void graph.draw().catch(() => {});
    };

    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerleave", clear);
    element.addEventListener("pointercancel", clear);
    return () => {
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerleave", clear);
      element.removeEventListener("pointercancel", clear);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [mode, ready]);

  const exportConfig = useMemo(
    () => JSON.stringify({ graphDna: params }, null, 2),
    [params],
  );

  const copyConfig = async () => {
    try {
      await navigator.clipboard.writeText(exportConfig);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setNote("Clipboard unavailable. Select the JSON directly.");
    }
  };

  const theme = resolvedTheme(params, themeMode);
  const focus = resolvedFocus(params);
  const inverted = mode !== "ambient";
  const palette = params[themeMode];
  const motion = useMemo(() => plansFor(params), [params]);

  return (
    <main
      className={`gdna${themeMode === "dark" ? " is-dark" : ""}`}
      style={
        {
          "--gdna-canvas": theme.canvas,
          "--gdna-surface": theme.surface,
          "--gdna-ink": theme.filament,
          "--gdna-muted": theme.lensLabel,
          "--gdna-focus-field": focus.field,
          "--gdna-focus-lit": focus.lit,
          "--gdna-duration": `${params.hoverResponse}ms`,
          ...motionCssVariables(motion),
        } as CSSProperties
      }
    >
      <header className="gdna__header">
        <div>
          <p className="gdna__nav">
            <a href="#/explorations">Explorations</a> / Graph DNA motion
          </p>
          <h1>Graph DNA motion lab</h1>
          <p>
            The live product graph, with motion and interaction kept on so the
            DNA can be tuned against real matter. Palette tokens are{" "}
            <a
              href="https://www.radix-ui.com/colors"
              target="_blank"
              rel="noreferrer"
            >
              Radix Colors
            </a>
            ; parameters persist in this browser.
            {liveMap ? (
              <>
                {" "}
                Open map: <strong>{liveLabel}</strong> · {liveMap.nodes.length}{" "}
                nodes.
              </>
            ) : live ? (
              <> Waiting for the live map…</>
            ) : (
              <> Fixture specimen — open with <code>?api=live</code>.</>
            )}
          </p>
        </div>
        <div className="gdna__header-actions">
          <span>
            AntV G6 · {NODE_FONTS[params.labelFontId].label} ·{" "}
            <a
              href="https://www.radix-ui.com/colors"
              target="_blank"
              rel="noreferrer"
            >
              Radix
            </a>
          </span>
          <a
            className="gdna__header-link"
            href="#/explorations/graph-dna?api=live&apiToken=devtoken"
          >
            Graph DNA
          </a>
          <a className="gdna__header-link" href="#/graph?api=live">
            Open Graph
          </a>
          <button type="button" onClick={copyConfig}>
            {copied ? "Copied" : "Copy parameters"}
          </button>
          <button type="button" onClick={() => setParams(DEFAULTS)}>
            Reset
          </button>
        </div>
        {/* The cost of the thing being tuned, beside the controls that tune
            it. Idle first: a verdict without the do-nothing arm at the same
            size is a statement about the canvas, not about the motion. */}
        <div className="gdna__frames">
          <button
            type="button"
            disabled={sampling || !ready}
            onClick={async () => {
              setSampling(true);
              const s = await sampleFrames(1400);
              setFrameBase({ ...s, scale: liveNodeCount });
              setSampling(false);
            }}
          >
            {sampling ? "Sampling…" : "Measure idle"}
          </button>
          <button
            type="button"
            disabled={sampling || !ready}
            onClick={async () => {
              setSampling(true);
              const s = await sampleFrames(1400);
              setFrameStat({ ...s, scale: liveNodeCount });
              setSampling(false);
            }}
          >
            {sampling ? "Sampling…" : "Measure motion"}
          </button>
          <p aria-live="polite">
            <strong>{verdictFor(frameStat, frameBase)}</strong>
            <span>{frameSummary(frameStat, frameBase)}</span>
          </p>
        </div>
      </header>

      <div className="gdna__workbench">
        <aside className="gdna__controls">
          <section>
            <h2>
              Idle theme ·{" "}
              <a
                className="gdna__inline-link"
                href="https://www.radix-ui.com/colors"
                target="_blank"
                rel="noreferrer"
              >
                Radix
              </a>
            </h2>
            <div className="gdna__switch">
              <button
                type="button"
                className={themeMode === "light" ? "is-active" : ""}
                onClick={() => setThemeMode("light")}
              >
                Light
              </button>
              <button
                type="button"
                className={themeMode === "dark" ? "is-active" : ""}
                onClick={() => setThemeMode("dark")}
              >
                Dark
              </button>
            </div>
            {(Object.keys(palette) as Array<keyof ThemeTokens>).map((key) => (
              <RadixControl
                key={`${themeMode}-${key}`}
                label={humanizeKey(key)}
                value={palette[key]}
                onChange={(value) => patchTheme(themeMode, key, value)}
              />
            ))}
          </section>

          <details className="gdna__control-group">
            <summary>Focus palette · Radix</summary>
            <section>
              {(Object.keys(params.focus) as Array<keyof FocusTokens>).map(
                (key) => (
                  <RadixControl
                    key={key}
                    label={humanizeKey(key)}
                    value={params.focus[key]}
                    onChange={(value) => patchFocus(key, value)}
                  />
                ),
              )}
            </section>
          </details>

          <section>
            <h2>Live layout</h2>
            <RangeControl
              label="Spacing"
              value={Math.round(params.spacing * 100)}
              min={100}
              max={200}
              step={5}
              unit="%"
              onChange={(value) => patch("spacing", value / 100)}
            />
            <p className="gdna__hint">
              Same room-between-nodes preference as the product Graph page.
              Animated specimen — static DNA tuning lives on Graph DNA.
            </p>
          </section>

          <section>
            <h2>Nodes</h2>
            <div
              className="gdna__font-chips"
              role="group"
              aria-label="Node label font"
            >
              {CIRCLE_NODE_FONT_IDS.map((id) => (
                <button
                  key={id}
                  type="button"
                  className={params.labelFontId === id ? "is-active" : ""}
                  style={{ fontFamily: NODE_FONTS[id].family }}
                  title={NODE_FONTS[id].note}
                  onClick={() => patch("labelFontId", id)}
                >
                  {NODE_FONTS[id].label}
                </button>
              ))}
            </div>
            <RangeControl
              label="Font weight"
              value={params.labelFontWeight}
              min={400}
              max={800}
              step={100}
              onChange={(value) => patch("labelFontWeight", value)}
            />
            <RangeControl
              label="Diameter"
              value={params.nodeDiameter}
              min={42}
              max={100}
              unit="px"
              onChange={(value) => patch("nodeDiameter", value)}
            />
            <RangeControl
              label="Boundary"
              value={params.nodeLine}
              min={0.5}
              max={4}
              step={0.1}
              unit="px"
              onChange={(value) => patch("nodeLine", value)}
            />
            <RangeControl
              label="Internal label"
              value={params.labelSize}
              min={7}
              max={16}
              unit="px"
              onChange={(value) => patch("labelSize", value)}
            />
            <RangeControl
              label="Text width"
              value={params.labelMaxWidth}
              min={45}
              max={92}
              unit="%"
              onChange={(value) => patch("labelMaxWidth", value)}
            />
          </section>

          <section>
            <h2>Relationships</h2>
            <RangeControl
              label="Resting filament"
              value={params.edgeWidth}
              min={0.4}
              max={4}
              step={0.1}
              unit="px"
              onChange={(value) => patch("edgeWidth", value)}
            />
            <RangeControl
              label="Resting opacity"
              value={params.edgeOpacity}
              min={0.1}
              max={1}
              step={0.05}
              onChange={(value) => patch("edgeOpacity", value)}
            />
            <RangeControl
              label="Type label"
              value={params.edgeLabelSize}
              min={6}
              max={14}
              unit="px"
              onChange={(value) => patch("edgeLabelSize", value)}
            />
            <RangeControl
              label="Removed dot gap"
              value={params.dottedGap}
              min={2}
              max={14}
              step={0.5}
              unit="px"
              onChange={(value) => patch("dottedGap", value)}
            />
          </section>

          <section>
            <h2>Physical interaction</h2>
            <RangeControl
              label="Cursor lens"
              value={params.hoverRadius}
              min={40}
              max={260}
              step={5}
              unit="px"
              onChange={(value) => patch("hoverRadius", value)}
            />
            <RangeControl
              label="Hover response"
              value={params.hoverResponse}
              min={60}
              max={500}
              step={10}
              unit="ms"
              onChange={(value) => patch("hoverResponse", value)}
            />
          </section>

          <section>
            <h2>Motion spine</h2>
            <p className="gdna__control-copy">
              Emit outward · absorb inward · settle only after release. Flow
              remains linear and held matter remains direct.
            </p>
            <RangeControl
              label="Emit"
              value={params.motionEmit}
              min={100}
              max={600}
              step={10}
              unit="ms"
              onChange={patchEmitDuration}
            />
            <RangeControl
              label="Absorb"
              value={params.motionAbsorb}
              min={80}
              max={500}
              step={10}
              unit="ms"
              onChange={patchAbsorbDuration}
            />
            <RangeControl
              label="Settle"
              value={params.motionSettle}
              min={120}
              max={700}
              step={10}
              unit="ms"
              onChange={(value) => patch("motionSettle", value)}
            />
            <RangeControl
              label="Held ring"
              value={Math.round(params.gripScale * 100)}
              min={72}
              max={100}
              unit="%"
              onChange={(value) => patch("gripScale", value / 100)}
            />
          </section>

          <section>
            <h2>Gravity field</h2>
            <p className="gdna__control-copy">
              Timing and physics are linked. Changing either recalibrates the
              same field rather than layering another animation system.
            </p>
            <RangeControl
              label="Gravity"
              value={Math.round(params.gravityStrength)}
              min={40}
              max={1200}
              step={10}
              unit="px/s²"
              onChange={patchGravityStrength}
            />
            <RangeControl
              label="Radial travel"
              value={params.gravityTravel}
              min={2}
              max={20}
              step={0.2}
              unit="px"
              onChange={patchGravityTravel}
            />
            <RangeControl
              label="Inward pull"
              value={params.absorbPull}
              min={0.5}
              max={5}
              step={0.05}
              unit="×"
              onChange={patchAbsorbPull}
            />
            <p className="gdna__field-reading">
              <span>Derived launch impulse</span>
              <output>
                {Math.round(
                  gravityLaunchImpulse(
                    params.gravityTravel,
                    params.gravityStrength,
                  ),
                )}{" "}
                px/s
              </output>
            </p>
          </section>

          <section>
            <h2>Drag treatment</h2>
            <p className="gdna__control-copy">
              Manipulation never implies selection. Compare connected weight
              transfer with a local compression of the held node.
            </p>
            <div className="gdna__switch">
              <button
                type="button"
                className={
                  params.dragTreatment === "weight" ? "is-active" : ""
                }
                onClick={() => patch("dragTreatment", "weight")}
              >
                Weight transfer
              </button>
              <button
                type="button"
                className={
                  params.dragTreatment === "compression"
                    ? "is-active"
                    : ""
                }
                onClick={() => patch("dragTreatment", "compression")}
              >
                Compression
              </button>
            </div>
            {params.dragTreatment === "weight" ? (
              <>
                <RangeControl
                  label="Node relief"
                  value={params.dragNodeRelief}
                  min={0}
                  max={0.8}
                  step={0.05}
                  unit="px"
                  onChange={(value) => patch("dragNodeRelief", value)}
                />
                <RangeControl
                  label="Edge load"
                  value={params.dragEdgeLoad}
                  min={0}
                  max={1.2}
                  step={0.05}
                  unit="px"
                  onChange={(value) => patch("dragEdgeLoad", value)}
                />
                <RangeControl
                  label="Edge presence"
                  value={params.dragEdgePresence}
                  min={0}
                  max={0.3}
                  step={0.01}
                  onChange={(value) =>
                    patch("dragEdgePresence", value)
                  }
                />
              </>
            ) : (
              <RangeControl
                label="Held size"
                value={Math.round(params.dragCompression * 100)}
                min={90}
                max={100}
                unit="%"
                onChange={(value) =>
                  patch("dragCompression", value / 100)
                }
              />
            )}
          </section>

          <section>
            <h2>Selection signal</h2>
            {/* The one animation the product ships, and the switch that
                decides it.

                It is here rather than among the canvas motion parameters
                because it is not canvas motion: the ring is a single
                screen-space SVG on the Web Animations API, so its cost is one
                element's opacity and scale and does not grow with the graph.
                Animating canvas *elements* is the thing that measured a 2.09 s
                block at 2000 nodes, and that stays off.

                Arrival and departure read from the shared emit/absorb plans
                above, so tuning those tunes this. */}
            <div className="gdna__switch">
              <button
                type="button"
                className={params.selectionMotion ? "is-active" : ""}
                onClick={() => patch("selectionMotion", true)}
              >
                Ring arrives
              </button>
              <button
                type="button"
                className={!params.selectionMotion ? "is-active" : ""}
                onClick={() => patch("selectionMotion", false)}
              >
                Appears
              </button>
            </div>
            <RangeControl
              label="Ant speed"
              value={params.selectionSpeed}
              min={0}
              max={80}
              unit="px/s"
              onChange={(value) => patch("selectionSpeed", value)}
            />
            <RangeControl
              label="Ring clearance"
              value={params.selectionClearance}
              min={2}
              max={24}
              unit="px"
              onChange={(value) => patch("selectionClearance", value)}
            />
            <RangeControl
              label="Ant spacing"
              value={params.selectionDotGap}
              min={2}
              max={12}
              step={0.5}
              unit="px"
              onChange={(value) => patch("selectionDotGap", value)}
            />
            <RangeControl
              label="Ring boundary"
              value={params.selectionLine}
              min={0.5}
              max={4}
              step={0.1}
              unit="px"
              onChange={(value) => patch("selectionLine", value)}
            />
          </section>
        </aside>

        <section
          className={`gdna__specimen${inverted ? " is-inverted" : ""}`}
        >
          <nav className="gdna__scenarios" aria-label="Backend-bound graph views">
            <button
              type="button"
              className={mode === "ambient" ? "is-active" : ""}
              onClick={() => setMode("ambient")}
            >
              Ambient
            </button>
            <button
              type="button"
              className={mode === "focus" ? "is-active" : ""}
              onClick={() => setMode("focus")}
            >
              Ledger focus
            </button>
            <button
              type="button"
              className={mode === "proposal" ? "is-active" : ""}
              onClick={() => setMode("proposal")}
            >
              Ledger proposal
            </button>
            <button
              type="button"
              className={mode === "diff" ? "is-active" : ""}
              onClick={() => setMode("diff")}
            >
              Ledger version diff
            </button>
          </nav>

          <div className="gdna__stage-shell">
            <div className="gdna__graph-stage">
              <div className="gdna__stage" ref={stageRef} />
              <SelectionAntRing
                key={mode}
                graph={ready ? graphRef.current : null}
                nodeId={selectedId}
                nodeDiameter={params.nodeDiameter}
                speed={params.selectionSpeed}
                clearance={params.selectionClearance}
                dotGap={params.selectionDotGap}
                lineWidth={params.selectionLine}
                color={inverted ? focus.lit : theme.node}
                dragging={
                  selectedId !== null && draggingId === selectedId
                }
                motion={motion}
                heldScale={params.gripScale}
                gravityTravel={params.gravityTravel}
              />
              <p className="gdna__note" aria-live="polite">
                {note}
              </p>
            </div>
            <MotionParityPanel
              motion={motion}
              gravityTravel={params.gravityTravel}
              gripScale={params.gripScale}
              ink={inverted ? focus.lit : theme.node}
              surface={inverted ? focus.field : theme.surface}
            />
          </div>

          <div className="gdna__key">
            <div>
              <strong>Nodes</strong>
              <span>equal mass · internal Jost label</span>
            </div>
            <div>
              <strong>Cursor lens</strong>
              <span>type emerges gradually at the nearest point on a filament</span>
            </div>
            <div>
              <strong>Ledger seams</strong>
              <span>proposal and diff copied from Ambient Canvas</span>
            </div>
          </div>
        </section>
      </div>

      <RegionalMassLodSection
        palette={{
          canvas: theme.canvas,
          surface: theme.surface,
          node: theme.node,
          nodeLabel: theme.nodeLabel,
          filament: theme.filament,
          muted: theme.lensLabel,
        }}
        nodeDiameter={params.nodeDiameter}
        labelSize={params.labelSize}
        labelMaxWidth={params.labelMaxWidth}
        edgeWidth={params.edgeWidth}
        edgeOpacity={params.edgeOpacity}
        motion={motion}
      />

      <section className="gdna__grammar">
        <header>
          <p>Product boundary</p>
          <h2>The backend decides which graph state exists</h2>
        </header>
        <div>
          {VIEW_CONTRACT.map((item) => (
            <article key={item.title}>
              <h3>{item.title}</h3>
              <p>{item.source}</p>
              <span>{item.rule}</span>
            </article>
          ))}
        </div>
      </section>

      <details className="gdna__json">
        <summary>Current Radix parameter object</summary>
        <pre>{exportConfig}</pre>
      </details>
    </main>
  );
}
