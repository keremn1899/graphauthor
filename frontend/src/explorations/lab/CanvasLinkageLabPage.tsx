import { useEffect, useMemo, useRef, useState } from "react";
import {
  Graph,
  type EdgeData,
  type IElementEvent,
  type NodeData,
} from "@antv/g6";
import { FONT_MONO_FAMILY } from "../../styles/typography";
import { gray, grayDark } from "@radix-ui/colors";
import { BASE_EDGE_STATE, BASE_NODE_STATE, NODE_FONTS } from "../g6/graphOptions";
import {
  arrowSizeForKind,
  ensureLinkageEdgeRegistered,
  isDirectedKind,
  LINKAGE_EDGE,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import { LENS_EDGE_STYLE } from "../g6/lensEdgeOptions";
import { FORCE_PRESETS, PHYSICS_ENABLED } from "../g6/forcePresets";
import {
  buildCanvasSeamHref,
  buildLedgerHref,
  readHashSeamParams,
  resolveSeamView,
  type ScenarioGraphView,
  type SeamParams,
} from "./platformCoreScenario";
import "../g6/g6Lab.css";
import "./CanvasLinkageLabPage.css";

type LinkageMode =
  | "idle"
  | "focus-group"
  | "focus-single"
  | "proposal-ghost"
  | "version-diff";

type EdgeLightRule = "both" | "either";
type EdgeVisual = "typed" | "uniform";

const LAB_MODES: LinkageMode[] = [
  "idle",
  "focus-group",
  "focus-single",
  "proposal-ghost",
  "version-diff",
];

function isLabMode(value: string | undefined): value is LinkageMode {
  return Boolean(value && (LAB_MODES as string[]).includes(value));
}

/** Idle — Radix gray (light). */
const INK = gray.gray12;
/** Inverted focus field — Radix gray (dark). */
const FIELD = grayDark.gray1;
/** Focus on — near-white. */
const FOCUS_LIT = grayDark.gray12;
/** Focus off — nodes one step darker than edges. */
const FOCUS_DIM_NODE = grayDark.gray3;
const FOCUS_DIM_EDGE = grayDark.gray4;
const FOCUS_LIT_LABEL = grayDark.gray1;
const FOCUS_DIM_LABEL = grayDark.gray11;
const NODE_SIZE = 78;
const GHOST_SIZE = 52;
/**
 * Round line-cap + zero-length dash → dots (not dashes).
 * Wider gap = sparser beads on removed rims and filaments.
 */
const DOTTED: [number, number] = [0, 6.5];
/** Above this intensity, the body is treated as fully lit. */
const FOCUS_ON = 1;
const FOCUS_OFF = 0;

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    Number.parseInt(h.slice(0, 2), 16),
    Number.parseInt(h.slice(2, 4), 16),
    Number.parseInt(h.slice(4, 6), 16),
  ];
}

function mixHex(from: string, to: string, t: number) {
  const a = hexToRgb(from);
  const b = hexToRgb(to);
  const u = Math.max(0, Math.min(1, t));
  const r = Math.round(a[0] + (b[0] - a[0]) * u);
  const g = Math.round(a[1] + (b[1] - a[1]) * u);
  const bl = Math.round(a[2] + (b[2] - a[2]) * u);
  return `rgb(${r}, ${g}, ${bl})`;
}

/** Binary focus colour; mid values (lens boost) mix dim → lit. */
function focusColor(intensity: number, dim = FOCUS_DIM_EDGE) {
  if (intensity >= FOCUS_ON) return FOCUS_LIT;
  if (intensity <= FOCUS_OFF) return dim;
  return mixHex(dim, FOCUS_LIT, intensity);
}

/**
 * Edge label text on the inverted field — muted at rest, lights toward
 * gray12 with focus intensity and cursor-lens boost.
 */
function focusLabelColor(intensity: number) {
  if (intensity >= FOCUS_ON) return FOCUS_LIT;
  if (intensity <= FOCUS_OFF) return grayDark.gray9;
  return mixHex(grayDark.gray9, FOCUS_LIT, intensity);
}

function massColor(intensity: number) {
  return focusColor(intensity, FOCUS_DIM_NODE);
}

function massLabelFill(intensity: number) {
  return intensity >= FOCUS_ON ? FOCUS_LIT_LABEL : FOCUS_DIM_LABEL;
}

function filamentWidth(intensity: number) {
  return intensity >= FOCUS_ON ? 2.4 : 1.15;
}

/** Invisible cursor lens — radius in screen pixels (stable across zoom). */
const LENS_RADIUS_PX = 140;
/** Soft ceiling for focus-mode edge boost (full white stays white). */
const LENS_CEILING = 0.82;
/** Idle / non-inverted lens labels — muted gray. */
const LENS_LABEL = gray.gray9;
/** Node-hover connected edge labels — full ink. */
const BOND_LABEL = gray.gray12;

/** Hover bond arrow opacity — same for incoming and outgoing. */
const ARROW_BOND = 1;

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
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** Smooth 1 at the stroke → 0 at the lens rim (cosine ease). */
function lensFalloff(dist: number, radius: number) {
  if (dist >= radius) return 0;
  const t = 1 - dist / radius;
  return 0.5 - 0.5 * Math.cos(Math.PI * t);
}

/** Lift toward a ceiling — bright stays bright, dark becomes a little grey. */
function boostIntensity(base: number, lens: number) {
  if (lens <= 0) return base;
  return base + Math.max(0, LENS_CEILING - base) * lens;
}

/** Brightest hop intensity on an edge — lens boost must never dim a filament. */
function peakEdgeIntensity(datum: EdgeData) {
  const base = intensityOf(datum);
  const sourceI = Number(datum.data?.sourceIntensity);
  const targetI = Number(datum.data?.targetIntensity);
  return Math.max(
    base,
    Number.isFinite(sourceI) ? sourceI : base,
    Number.isFinite(targetI) ? targetI : base,
  );
}

function lensOf(datum: NodeData | EdgeData) {
  const value = Number(datum.data?.lens);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

const MODES: { id: LinkageMode; label: string; note: string }[] = [
  {
    id: "idle",
    label: "Idle",
    note: "Paper field, ink masses",
  },
  {
    id: "focus-group",
    label: "Focus · group",
    note: "Field inverts; ownership cluster full paper, the rest dark grey",
  },
  {
    id: "focus-single",
    label: "Focus · single",
    note: "Point focus — only the seed and its edges light up",
  },
  {
    id: "proposal-ghost",
    label: "Proposal",
    note: "PROP-247 encoding on V12 — proposed cluster full paper; ambient dim",
  },
  {
    id: "version-diff",
    label: "Version diff",
    note: "Real V12→V13 — solid added, hollow dotted removed, dim+white border touched",
  },
];

function lightOf(datum: NodeData | EdgeData) {
  return String(datum.data?.light ?? "idle");
}

function intensityOf(datum: NodeData | EdgeData) {
  const value = Number(datum.data?.intensity);
  return Number.isFinite(value) ? value : 1;
}

function isFocusLit(datum: NodeData | EdgeData) {
  return intensityOf(datum) >= FOCUS_ON;
}

type DiffKind = "added" | "removed" | "touched" | "unchanged";

function diffOf(datum: NodeData | EdgeData): DiffKind {
  const value = String(datum.data?.diff ?? "unchanged");
  if (value === "added" || value === "removed" || value === "touched") {
    return value;
  }
  return "unchanged";
}

function buildFocusNodeStyle(inverted: boolean) {
  return {
    size: (datum: NodeData) =>
      lightOf(datum) === "ghost" ? GHOST_SIZE : NODE_SIZE,
    fill: (datum: NodeData) => {
      if (!inverted) return INK;
      const diff = diffOf(datum);
      // Added: solid paper. Removed: hollow (field shows through).
      if (diff === "added") return FOCUS_LIT;
      if (diff === "removed") return FIELD;
      return massColor(intensityOf(datum));
    },
    fillOpacity: (datum: NodeData) => {
      if (lightOf(datum) === "ghost") return 0.28;
      if (inverted && diffOf(datum) === "removed") return 1;
      return 1;
    },
    stroke: (datum: NodeData) => {
      if (!inverted) return INK;
      const diff = diffOf(datum);
      // Added / removed / touched: white rim. Bodies differ.
      if (diff === "added" || diff === "removed" || diff === "touched") {
        return FOCUS_LIT;
      }
      return massColor(intensityOf(datum));
    },
    strokeOpacity: (datum: NodeData) =>
      lightOf(datum) === "ghost" ? 0.4 : 1,
    lineWidth: (datum: NodeData) => {
      if (!inverted) {
        if (lightOf(datum) === "ghost") return 1.25;
        return 1;
      }
      if (diffOf(datum) === "removed") return 1.6;
      if (diffOf(datum) === "added" || diffOf(datum) === "touched") return 1.5;
      return 1.25;
    },
    lineDash: (datum: NodeData) => {
      if (lightOf(datum) === "ghost") return DOTTED;
      if (inverted && diffOf(datum) === "removed") return DOTTED;
      return undefined;
    },
    lineCap: "round" as const,
    halo: false,
    badge: false,
    labelText: (datum: NodeData) => String(datum.data?.label ?? datum.id),
    labelPlacement: "center" as const,
    labelFill: (datum: NodeData) => {
      if (!inverted) return gray.gray1;
      const diff = diffOf(datum);
      if (diff === "added") return FOCUS_LIT_LABEL;
      // Touched + removed: bright type on the dark field / hollow.
      if (diff === "touched" || diff === "removed") return FOCUS_LIT;
      return massLabelFill(intensityOf(datum));
    },
    labelOpacity: (datum: NodeData) => {
      if (inverted) {
        const diff = diffOf(datum);
        if (diff === "touched" || diff === "added" || diff === "removed") {
          return 1;
        }
        return intensityOf(datum) >= FOCUS_ON ? 1 : 0.85;
      }
      if (lightOf(datum) === "ghost") return 0.55;
      return 1;
    },
    labelFontFamily: NODE_FONTS.plexCondensed.family,
    labelFontSize: (datum: NodeData) =>
      lightOf(datum) === "ghost" ? 8 : 11,
    labelFontWeight: 600 as const,
    labelLineHeight: (datum: NodeData) =>
      lightOf(datum) === "ghost" ? 10 : 13,
    labelWordWrap: true,
    labelMaxWidth: (datum: NodeData) =>
      lightOf(datum) === "ghost" ? "88%" : "76%",
    labelMaxLines: (datum: NodeData) =>
      lightOf(datum) === "ghost" ? 3 : 2,
    cursor: "grab" as const,
  };
}

/** Split related edges by direction relative to the hovered mass. */
function relatedEdgesByDirection(graph: Graph, nodeId: string) {
  const out = new Set<string>();
  const inn = new Set<string>();
  for (const edge of graph.getRelatedEdgesData(nodeId)) {
    const id = String(edge.id);
    if (String(edge.source) === nodeId) out.add(id);
    else inn.add(id);
  }
  return { out, inn };
}

type HoverBundle = {
  nodes: Set<string>;
  out: Set<string>;
  inn: Set<string>;
};

function emptyHoverBundle(): HoverBundle {
  return { nodes: new Set(), out: new Set(), inn: new Set() };
}

function hoverBundleFor(graph: Graph, nodeId: string): HoverBundle {
  const { out, inn } = relatedEdgesByDirection(graph, nodeId);
  // Focus-lit filaments keep their brightness — hover must not dim them.
  const keepMutable = (ids: Set<string>) => {
    const next = new Set<string>();
    for (const id of ids) {
      const edge = graph.getEdgeData(id);
      if (edge && isFocusLit(edge)) continue;
      next.add(id);
    }
    return next;
  };
  return {
    nodes: new Set([nodeId]),
    out: keepMutable(out),
    inn: keepMutable(inn),
  };
}

function hoverHasEdges(bundle: HoverBundle) {
  return bundle.out.size > 0 || bundle.inn.size > 0;
}

/**
 * True directional gradient along an edge's own line. G resolves gradient
 * angle against the shape's bounding box, and a straight edge's bounding
 * box is exactly its own span — so an angle equal to the edge's bearing
 * lines the gradient up perfectly with the line itself.
 */
function edgeGradient(datum: EdgeData, lens: number) {
  const angle = Number(datum.data?.angleDeg);
  const sourceI = boostIntensity(
    Number(datum.data?.sourceIntensity ?? intensityOf(datum)),
    lens,
  );
  const targetI = boostIntensity(
    Number(datum.data?.targetIntensity ?? intensityOf(datum)),
    lens,
  );
  if (!Number.isFinite(angle)) return null;
  const from = focusColor(sourceI);
  const to = focusColor(targetI);
  return `linear-gradient(${angle}deg, ${from} 0%, ${to} 100%)`;
}

function buildEdgeStyle(edgeVisual: EdgeVisual, inverted: boolean) {
  const typed = edgeVisual === "typed";
  const focusTyped = (datum: EdgeData) =>
    inverted && typed && isFocusLit(datum);
  const focusDirected = (datum: EdgeData) =>
    focusTyped(datum) && isDirectedKind(linkageEdgeKind(datum));

  return {
    edgeKind: (datum: EdgeData) => linkageEdgeKind(datum),
    // Edges never capture the pointer — otherwise a thickened bond or
    // label under the cursor steals node:pointerenter/leave and the
    // hover animation restarts in a pulse.
    pointerEvents: "none" as const,
    // Focus-lit edges show SST type at rest (arrows + labels). Plain
    // lines otherwise; hover bonds only apply on non-focus masses.
    endArrow: (datum: EdgeData) => focusDirected(datum),
    endArrowType: "triangle" as const,
    endArrowSize: (datum: EdgeData) =>
      arrowSizeForKind(linkageEdgeKind(datum)),
    endArrowFillOpacity: 1,
    endArrowStrokeOpacity: 1,
    endArrowOffset: (datum: EdgeData) =>
      focusDirected(datum)
        ? arrowSizeForKind(linkageEdgeKind(datum)) / 2 + 1
        : 0.01,
    lineCap: "round" as const,
    lineJoin: "round" as const,
    stroke: (datum: EdgeData) => {
      const lens = lensOf(datum);
      if (inverted) {
        return (
          edgeGradient(datum, lens) ??
          focusColor(boostIntensity(peakEdgeIntensity(datum), lens))
        );
      }
      if (lightOf(datum) === "disk" || lightOf(datum) === "removed") return INK;
      return INK;
    },
    strokeOpacity: (datum: EdgeData) => {
      if (inverted) return 1;
      if (lightOf(datum) === "ghost") return 0.32;
      if (lightOf(datum) === "removed") return 0.7;
      return 1;
    },
    lineWidth: (datum: EdgeData) => {
      if (inverted) {
        if (focusTyped(datum)) return sstWidthForKind(datum, edgeVisual);
        const lens = lensOf(datum);
        return filamentWidth(
          boostIntensity(peakEdgeIntensity(datum), lens),
        );
      }
      if (lightOf(datum) === "disk") return 2.1;
      if (lightOf(datum) === "removed") return 1.6;
      if (lightOf(datum) === "ghost") return 1.15;
      return 1.1;
    },
    lineDash: (datum: EdgeData) => {
      if (inverted && diffOf(datum) === "removed") return DOTTED;
      if (lightOf(datum) === "ghost" || lightOf(datum) === "removed") {
        return DOTTED;
      }
      return undefined;
    },
    labelText: (datum: EdgeData) =>
      typed ? String(datum.data?.label ?? "") : "",
    labelFontFamily: FONT_MONO_FAMILY,
    labelFontSize: 7,
    // Focus-lit: bright type labels. Lens: muted→lit. Bond overrides ink.
    labelFill: (datum: EdgeData) => {
      if (!inverted) return LENS_LABEL;
      return focusLabelColor(
        boostIntensity(peakEdgeIntensity(datum), lensOf(datum)),
      );
    },
    labelBackground: true,
    labelBackgroundFill: inverted ? FIELD : gray.gray1,
    // Keep label upright — auto-rotate can flip across updates.
    labelAutoRotate: false,
    labelPadding: [2, 3] as [number, number],
    labelOpacity: (datum: EdgeData) => {
      if (focusTyped(datum)) return 1;
      const lens = lensOf(datum);
      if (lens <= 0) return 0;
      return Math.min(1, lens);
    },
    labelBackgroundOpacity: (datum: EdgeData) => {
      if (focusTyped(datum)) return 0.75;
      const lens = lensOf(datum);
      if (lens <= 0) return 0;
      return (inverted ? 0.75 : 0.9) * Math.min(1, lens);
    },
    increasedLineWidthForHitTesting: 20,
  };
}

function hoverEdgeStroke(
  datum: EdgeData,
  edgeVisual: EdgeVisual,
  inverted: boolean,
  floor: number,
  ceiling = 0.95,
) {
  if (inverted) {
    return focusColor(Math.min(ceiling, Math.max(floor, intensityOf(datum))));
  }
  if (lightOf(datum) === "disk" || lightOf(datum) === "removed") return INK;
  return edgeVisual === "uniform" ? INK : LENS_EDGE_STYLE.stroke(datum);
}

function sstWidthForKind(datum: EdgeData, edgeVisual: EdgeVisual) {
  if (edgeVisual === "uniform") return 1.45;
  return LENS_EDGE_STYLE.lineWidth(datum);
}

/**
 * Hover bonds — only for non-focus masses. Incoming and outgoing share
 * the same brightness (no directional dimming). Focus-lit edges already
 * show SST type at rest, so hovering a focus seed is a no-op.
 */
function buildEdgeState(edgeVisual: EdgeVisual, inverted: boolean) {
  const typed = edgeVisual === "typed";
  const bond = {
    lineWidth: (datum: EdgeData) =>
      // Focus-lit edges are immutable — keep resting SST width if state
      // somehow lands on one (e.g. race); otherwise lift equally.
      isFocusLit(datum)
        ? sstWidthForKind(datum, edgeVisual)
        : sstWidthForKind(datum, edgeVisual) + (inverted ? 0.55 : 0.45),
    stroke: (datum: EdgeData) => {
      if (isFocusLit(datum)) return FOCUS_LIT;
      return inverted
        ? grayDark.gray10
        : hoverEdgeStroke(datum, edgeVisual, inverted, 0.78);
    },
    strokeOpacity: 1,
    endArrow: (datum: EdgeData) => isDirectedKind(linkageEdgeKind(datum)),
    endArrowSize: (datum: EdgeData) =>
      arrowSizeForKind(linkageEdgeKind(datum)),
    endArrowFillOpacity: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum)) ? ARROW_BOND : 0,
    endArrowStrokeOpacity: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum)) ? ARROW_BOND : 0,
    endArrowOffset: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum))
        ? arrowSizeForKind(linkageEdgeKind(datum)) / 2 + 1
        : 0.01,
    // Field-coloured chip cuts a readable gap in the stroke — same as
    // the cursor lens — without inverting the label text.
    labelFill: inverted ? FOCUS_LIT : BOND_LABEL,
    labelBackground: true,
    labelBackgroundFill: inverted ? FIELD : gray.gray1,
    labelBackgroundOpacity: typed ? (inverted ? 1 : 0.92) : 0,
    labelOpacity: typed ? 1 : 0,
    labelFontSize: 7,
  };
  return {
    ...BASE_EDGE_STATE,
    out: bond,
    inn: bond,
  };
}

type LensMaps = { edges: Map<string, number> };

function emptyLensMaps(): LensMaps {
  return { edges: new Map() };
}

/**
 * Sparse write — only edges whose lens value actually changed.
 * Returns true if anything was written (caller should paint).
 */
function commitLensStrengths(
  graph: Graph,
  next: LensMaps,
  previous: LensMaps,
) {
  if (graph.destroyed) return false;

  const edgeUpdates: { id: string; data: Record<string, unknown> }[] = [];
  const seen = new Set<string>();

  for (const [id, lens] of next.edges) {
    seen.add(id);
    const prev = previous.edges.get(id) ?? 0;
    if (Math.abs(prev - lens) < 0.002) continue;
    const edge = graph.getEdgeData(id);
    if (!edge) continue;
    edgeUpdates.push({ id, data: { ...edge.data, lens } });
  }
  for (const id of previous.edges.keys()) {
    if (seen.has(id)) continue;
    const edge = graph.getEdgeData(id);
    if (!edge) continue;
    edgeUpdates.push({ id, data: { ...edge.data, lens: 0 } });
  }

  if (edgeUpdates.length === 0) return false;
  graph.updateEdgeData(edgeUpdates);
  return true;
}

/**
 * Positions only exist once layout has settled, so the bearing of each
 * edge — and therefore its gradient angle — is computed in a pass after
 * the first draw, then written back onto the edge data.
 */
async function applyEdgeGradients(graph: Graph, edges: EdgeData[]) {
  if (graph.destroyed) return;
  const ids = new Set<string>();
  for (const edge of edges) {
    ids.add(String(edge.source));
    ids.add(String(edge.target));
  }
  const positions = new Map<string, [number, number]>();
  for (const id of ids) {
    try {
      const p = graph.getElementPosition(id);
      positions.set(id, [p[0], p[1]]);
    } catch {
      // element not rendered yet — edge falls back to a flat fill
    }
  }
  if (graph.destroyed) return;

  const updates = edges.map((edge) => {
    const s = positions.get(String(edge.source));
    const t = positions.get(String(edge.target));
    let angleDeg: number | undefined;
    if (s && t) {
      const dx = t[0] - s[0];
      const dy = t[1] - s[1];
      angleDeg = (Math.atan2(dx, -dy) * 180) / Math.PI;
    }
    return { id: String(edge.id), data: { ...edge.data, angleDeg } };
  });

  graph.updateEdgeData(updates);
  await graph.draw();
}

function dagreSeedLayout() {
  return {
    type: "antv-dagre" as const,
    rankdir: "TB" as const,
    nodesep: 100,
    ranksep: 140,
    controlPoints: false,
  };
}

/** Link-only Glide Loose — no ambient charge; collide sized to mass. */
function glideLooseLayout() {
  return {
    ...FORCE_PRESETS["glide-loose"].layout,
    collide: {
      radius: NODE_SIZE / 2 + 6,
      strength: 1,
      iterations: 3,
    },
    animation: true,
  };
}

/** Structural dagre pass, then soft Glide Loose so drag yields through links. */
async function seedThenGlideLoose(graph: Graph) {
  if (graph.destroyed) return;
  try {
    graph.stopLayout();
  } catch {
    /* ok */
  }
  graph.setLayout(dagreSeedLayout());
  await graph.layout().catch(() => {});
  if (graph.destroyed || !PHYSICS_ENABLED) return;
  try {
    graph.stopLayout();
  } catch {
    /* ok */
  }
  graph.setLayout(glideLooseLayout());
  await graph.layout().catch(() => {});
}

export function CanvasLinkageLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const lensStrengthRef = useRef<LensMaps>(emptyLensMaps());
  const [graphReady, setGraphReady] = useState(false);
  const [seamParams, setSeamParams] = useState<SeamParams>(() =>
    readHashSeamParams(),
  );
  const [edgeRule, setEdgeRule] = useState<EdgeLightRule>("either");
  const [edgeVisual, setEdgeVisual] = useState<EdgeVisual>("typed");

  useEffect(() => {
    const sync = () => setSeamParams(readHashSeamParams());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const scenario: ScenarioGraphView = useMemo(
    () => resolveSeamView(seamParams),
    [seamParams],
  );

  const activeLabMode: LinkageMode | null = isLabMode(seamParams.mode)
    ? seamParams.mode
    : seamParams.activity ||
        seamParams.seam ||
        seamParams.proposal ||
        seamParams.focus?.length
      ? null
      : "idle";

  const drivenFromLedger = Boolean(
    seamParams.activity || seamParams.seam || seamParams.proposal,
  );

  const modeMeta =
    MODES.find((item) => item.id === activeLabMode) ??
    (drivenFromLedger
      ? { id: "idle" as LinkageMode, label: "Ledger", note: scenario.label }
      : MODES[0]!);

  const selectLabMode = (next: LinkageMode) => {
    window.location.hash = buildCanvasSeamHref({ mode: next });
  };

  const clearSeam = () => {
    window.location.hash = buildCanvasSeamHref({ mode: "idle" });
  };

  useEffect(() => {
    if (!containerRef.current) return;
    ensureLinkageEdgeRegistered();
    let cancelled = false;
    const inverted = scenario.inverted;

    const graph = new Graph({
      container: containerRef.current,
      data: scenario.data,
      // Global on so hover swell can animate; element update stages stay off
      // so the cursor lens still paints without style tweens.
      animation: true,
      autoFit: {
        type: "view",
        options: { when: "always", direction: "both" },
        animation: false,
      },
      padding: [48, 40, 48, 40],
      layout: dagreSeedLayout(),
      node: {
        type: "circle",
        style: buildFocusNodeStyle(inverted),
        state: BASE_NODE_STATE,
      },
      edge: {
        type: LINKAGE_EDGE,
        style: buildEdgeStyle(edgeVisual, inverted) as never,
        state: buildEdgeState(edgeVisual, inverted),
        animation: false,
      },
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        "click-select",
        // Plain drag fights a live force sim — hand the pointer to Glide Loose.
        PHYSICS_ENABLED
          ? { type: "drag-element-force", fixed: false }
          : "drag-element",
      ],
    });

    graphRef.current = graph;
    graph
      .render()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        await seedThenGlideLoose(graph);
        if (cancelled || graph.destroyed) return;
        if (inverted) {
          await applyEdgeGradients(graph, scenario.data.edges ?? []);
        }
        if (cancelled || graph.destroyed) return;
        setGraphReady(true);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      graphRef.current = null;
      try {
        graph.stopLayout();
      } catch {
        /* already stopped */
      }
      graph.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graphReady || !graph || graph.destroyed) return;
    let cancelled = false;
    const { inverted } = scenario;

    lensStrengthRef.current = emptyLensMaps();
    try {
      graph.stopLayout();
    } catch {
      /* ok */
    }
    graph.setData(scenario.data);
    graph.setOptions({
      node: {
        type: "circle",
        style: buildFocusNodeStyle(inverted),
        state: BASE_NODE_STATE,
      },
      edge: {
        type: LINKAGE_EDGE,
        style: buildEdgeStyle(edgeVisual, inverted) as never,
        state: buildEdgeState(edgeVisual, inverted),
        animation: false,
      },
    });

    graph
      .draw()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        await seedThenGlideLoose(graph);
        if (cancelled || graph.destroyed) return;
        if (scenario.camera === "focus" && scenario.focusIds.length > 0) {
          await graph.focusElement(scenario.focusIds, {
            duration: 420,
            easing: "ease-in-out",
          });
        } else {
          await graph.fitView({ when: "always", direction: "both" }, false);
        }
        if (cancelled || graph.destroyed) return;
        if (inverted) {
          await applyEdgeGradients(graph, scenario.data.edges ?? []);
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [scenario, edgeVisual, graphReady]);

  // Directed bonds on connected edges — out (leaves) vs in (arrives).
  // The hovered node's own style never changes; only its edges do.
  useEffect(() => {
    const graph = graphRef.current;
    if (!graphReady || !graph || graph.destroyed) return;

    let active = emptyHoverBundle();
    let frozen = false;
    let raf = 0;
    let pending: HoverBundle | null = null;
    let leaveTimer = 0;

    const clearState = (id: string, state: string) =>
      graph.getElementState(id).filter((s) => s !== state);

    const syncEdgeState = (
      states: Record<string, string[]>,
      prev: Set<string>,
      next: Set<string>,
      state: string,
    ) => {
      for (const id of prev) {
        if (next.has(id)) continue;
        states[id] = clearState(id, state);
      }
      for (const id of next) {
        const cur = states[id] ?? graph.getElementState(id);
        const cleaned = cur.filter((s) => s !== "out" && s !== "inn");
        states[id] = cleaned.includes(state) ? cleaned : [...cleaned, state];
      }
    };

    const commit = async (next: HoverBundle) => {
      if (graph.destroyed) return;
      const states: Record<string, string[]> = {};

      syncEdgeState(states, active.out, next.out, "out");
      syncEdgeState(states, active.inn, next.inn, "inn");

      active = next;

      await graph.setElementState(states, false).catch(() => {});
    };

    const schedule = (next: HoverBundle) => {
      pending = next;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const bundle = pending ?? emptyHoverBundle();
        pending = null;
        void commit(bundle);
      });
    };

    const onEnter = (event: IElementEvent) => {
      if (frozen || graph.destroyed) return;
      if (leaveTimer) {
        window.clearTimeout(leaveTimer);
        leaveTimer = 0;
      }
      const id = String(event.target.id);
      const node = graph.getNodeData(id);
      // Focus seeds already expose typed edges — hover bond does nothing.
      if (node && isFocusLit(node)) {
        schedule(emptyHoverBundle());
        return;
      }
      schedule(hoverBundleFor(graph, id));
    };

    const onLeave = () => {
      if (frozen || graph.destroyed) return;
      // Brief grace so a bond label/stroke under the cursor can't
      // flicker node:pointerleave → clear → re-enter into a pulse.
      if (leaveTimer) window.clearTimeout(leaveTimer);
      leaveTimer = window.setTimeout(() => {
        leaveTimer = 0;
        schedule(emptyHoverBundle());
      }, 60);
    };

    const onDragStart = () => {
      frozen = true;
    };
    const onDragEnd = () => {
      frozen = false;
    };

    graph.on("node:pointerenter", onEnter);
    graph.on("node:pointerleave", onLeave);
    graph.on("node:dragstart", onDragStart);
    graph.on("node:dragend", onDragEnd);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      if (leaveTimer) window.clearTimeout(leaveTimer);
      graph.off("node:pointerenter", onEnter);
      graph.off("node:pointerleave", onLeave);
      graph.off("node:dragstart", onDragStart);
      graph.off("node:dragend", onDragEnd);
      if (!graph.destroyed && hoverHasEdges(active)) {
        const clear: Record<string, string[]> = {};
        for (const id of active.out) clear[id] = clearState(id, "out");
        for (const id of active.inn) clear[id] = clearState(id, "inn");
        void graph.setElementState(clear, false).catch(() => {});
      }
    };
  }, [graphReady, scenario]);

  // Invisible cursor lens — edge proximity (muted labels + filament lift).
  // Stays on while a node is hovered; node bonds layer on top (additive).
  useEffect(() => {
    const graph = graphRef.current;
    const el = containerRef.current;
    if (!graphReady || !graph || graph.destroyed || !el) return;

    let drawing = false;
    let pending: { x: number; y: number } | null = null;
    let raf = 0;

    const paintImmediate = async () => {
      if (graph.destroyed) return;
      await graph.draw().catch(() => {});
    };

    const runFrame = async () => {
      raf = 0;
      if (graph.destroyed) return;
      const point = pending;
      pending = null;
      if (!point) return;

      const [cx, cy] = graph.getCanvasByClient([point.x, point.y]);
      const zoom = Math.max(0.05, graph.getZoom() || 1);
      const radius = LENS_RADIUS_PX / zoom;
      const next = emptyLensMaps();

      for (const edge of graph.getEdgeData()) {
        const id = String(edge.id);
        try {
          const s = graph.getElementPosition(String(edge.source));
          const t = graph.getElementPosition(String(edge.target));
          const dist = distPointToSegment(cx, cy, s[0], s[1], t[0], t[1]);
          const strength = lensFalloff(dist, radius);
          if (strength > 0.008) next.edges.set(id, strength);
        } catch {
          // skip
        }
      }

      const prev = lensStrengthRef.current;
      const wrote = commitLensStrengths(graph, next, prev);
      lensStrengthRef.current = next;

      if (wrote) {
        drawing = true;
        await paintImmediate();
        drawing = false;
      }

      // If the cursor moved during the draw, process the latest sample.
      if (pending && !raf) {
        raf = requestAnimationFrame(() => {
          void runFrame();
        });
      }
    };

    const clearLens = async () => {
      if (graph.destroyed) return;
      pending = null;
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
      const prev = lensStrengthRef.current;
      const empty = emptyLensMaps();
      const wrote = commitLensStrengths(graph, empty, prev);
      lensStrengthRef.current = empty;
      if (wrote) await paintImmediate();
    };

    const onMove = (event: PointerEvent) => {
      pending = { x: event.clientX, y: event.clientY };
      if (drawing || raf) return;
      raf = requestAnimationFrame(() => {
        void runFrame();
      });
    };

    const onLeave = () => {
      void clearLens();
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("pointercancel", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("pointercancel", onLeave);
      void clearLens();
    };
  }, [graphReady, scenario]);

  return (
    <main className="canvas-linkage">
      <header className="canvas-linkage__header">
        <div>
          <p className="canvas-linkage__eyebrow">Screen 1 · Canvas seams</p>
          <h1>Linkage lab</h1>
          <p className="canvas-linkage__lede">
            Focus inverts the field. Focused masses and their edges go full
            paper; the rest stay dark grey on the field. An invisible cursor lens
            reveals edge labels in muted grey and softly lifts dim filaments.
            At rest, bonds are plain straight lines; hover a mass and its edges
            bond on top of the lens — connected labels go full black, directed
            kinds (CONTAINS, LEADSTO) show an arrow tip, EXPRESSES / NEARTO stay
            undirected strokes. Incoming and outgoing share the same brightness.
          </p>
          <p className="canvas-linkage__nav">
            <a href="#/explorations">Explorations</a>
            {" · "}
            <a href={buildLedgerHref(seamParams.activity)}>Ledger feed</a>
            {" · "}
            <a href="#/construct?api=live">Construct</a>
            {" · "}
            <a href="#/explorations/ambient-canvas">Ambient canvas</a>
            {drivenFromLedger ? (
              <>
                {" · "}
                <button
                  type="button"
                  className="canvas-linkage__clear"
                  onClick={clearSeam}
                >
                  Clear focus
                </button>
              </>
            ) : null}
          </p>
        </div>
        <aside className="canvas-linkage__note">
          <span>Cursor lens</span>
          <strong>Plain lines · SST reveal on hover</strong>
          <p>{scenario.label}</p>
        </aside>
      </header>

      <div className="canvas-linkage__controls">
        <div className="canvas-linkage__modes" role="tablist" aria-label="Modes">
          {MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeLabMode === item.id}
              className={activeLabMode === item.id ? "is-active" : ""}
              onClick={() => selectLabMode(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="canvas-linkage__toggles">
          <div>
            <span>Focus edges</span>
            <button
              type="button"
              className={edgeRule === "either" ? "is-active" : ""}
              onClick={() => setEdgeRule("either")}
              disabled={
                activeLabMode !== "focus-group" &&
                activeLabMode !== "focus-single" &&
                activeLabMode !== "proposal-ghost" &&
                !drivenFromLedger
              }
            >
              geometric mean
            </button>
            <button
              type="button"
              className={edgeRule === "both" ? "is-active" : ""}
              onClick={() => setEdgeRule("both")}
              disabled={
                activeLabMode !== "focus-group" &&
                activeLabMode !== "focus-single" &&
                activeLabMode !== "proposal-ghost" &&
                !drivenFromLedger
              }
            >
              darker end
            </button>
          </div>
          <div>
            <span>Edge look</span>
            <button
              type="button"
              className={edgeVisual === "typed" ? "is-active" : ""}
              onClick={() => setEdgeVisual("typed")}
            >
              SST typed
            </button>
            <button
              type="button"
              className={edgeVisual === "uniform" ? "is-active" : ""}
              onClick={() => setEdgeVisual("uniform")}
            >
              single
            </button>
          </div>
        </div>
      </div>

      <p className="canvas-linkage__status">
        {scenario.label}
        {modeMeta.note && modeMeta.note !== scenario.label
          ? ` · ${modeMeta.note}`
          : ""}
        {PHYSICS_ENABLED ? " · Glide Loose (link-only)" : ""}
        {scenario.inverted
          ? " · binary focus (no hop decay) · cursor lens lifts dim filaments"
          : " · cursor lens reveals edge labels"}
      </p>

      <section
        className={[
          "canvas-linkage__stage-shell",
          scenario.inverted ? "is-inverted" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="canvas-linkage__stage" ref={containerRef} />
      </section>
    </main>
  );
}
