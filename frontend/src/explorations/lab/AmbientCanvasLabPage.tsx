import { useEffect, useMemo, useRef, useState } from "react";
import {
  Graph,
  type EdgeData,
  type IElementEvent,
  type LayoutOptions,
  type NodeData,
} from "@antv/g6";
import { gray, grayDark, mauveDark } from "@radix-ui/colors";
import { CIRCLE_NODE_FONT_IDS, NODE_FONTS, type NodeFontId } from "../g6/graphOptions";
import { FONT_MONO_FAMILY, FONT_SANS_FAMILY } from "../../styles/typography";
import {
  arrowSizeForKind,
  ensureLinkageEdgeRegistered,
  isDirectedKind,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import {
  AMBIENT_LINKAGE_EDGE,
  ensureAmbientLinkageEdgeRegistered,
} from "./ambientLinkageEdge";
import { FORCE_PRESETS } from "../g6/forcePresets";
import {
  ensureStructuralDagreRegistered,
  LENS_DAGRE_CONTAINS,
  LENS_DAGRE_LEADSTO,
} from "../g6/structuralDagre";
import {
  AMBIENT_LOD_GRAPH_VERSION,
  createAmbientLodGraph,
  labelOf,
} from "./ambientLodData";
import { createAmbientContainsComboGraph } from "./ambientContainsComboGraph";
import { useAmbientLiveGraph } from "./ambientLiveData";
import {
  AMBIENT_SEAM_MODES,
  applyAmbientSeamMode,
  diffOf,
  intensityOf,
  isFocusLit,
  type AmbientSeamMode,
} from "./ambientSeamModes";
import {
  buildCoarsenModel,
  continuousResolver,
  massDiameter,
  type CoarsenModel,
  type ContinuousState,
} from "./ambientMassModel";
import {
  clearLabelMeasureCache,
  labelBoxWidth,
} from "./nodeLabelFit";
import "../g6/g6Lab.css";
import "./AmbientCanvasLabPage.css";

/**
 * Ambient canvas — mass LOD + linkage-idle edge/hover look.
 * Layout: structural pass (or brief glide settle) → freeze → drag-element.
 * Physics is never left running.
 */

type ThemeMode = "light" | "dark";

type ThemePalette = {
  /** Filaments / chrome strokes. */
  ink: string;
  /** Node disc fill + stroke. */
  node: string;
  /** Label text sitting on the node disc. */
  paper: string;
  chip: string;
  lensLabel: string;
  bondLabel: string;
};

/** Idle — Radix gray (light), matching canvas-linkage. */
const THEME_LIGHT: ThemePalette = {
  ink: gray.gray12,
  node: gray.gray12,
  paper: gray.gray1,
  chip: gray.gray1,
  lensLabel: gray.gray9,
  bondLabel: gray.gray12,
};

/**
 * Night field — Radix mauve throughout. Filaments stay mauve11; nodes sit
 * a touch under that (between mauve10/11) so discs read softer than strokes.
 */
const THEME_DARK: ThemePalette = {
  ink: mauveDark.mauve11,
  node: "#a4a1ac",
  paper: mauveDark.mauve1,
  chip: mauveDark.mauve3,
  lensLabel: mauveDark.mauve9,
  bondLabel: mauveDark.mauve12,
};

/** Live palette read by G6 style callbacks (not React closures). */
const themeLive: ThemePalette & { mode: ThemeMode } = {
  ...THEME_LIGHT,
  mode: "light",
};

/**
 * Focus / proposal / diff — always charcoal spotlight (not a theme pair).
 * Idle Light/Dark stay independent; entering a seam drops into this night
 * stage so the lit cluster reads clearly. Radix grayDark only (no mauve).
 */
type FocusPalette = {
  field: string;
  lit: string;
  dimNode: string;
  dimEdge: string;
  litLabel: string;
  dimLabel: string;
  lensMuted: string;
  bondMuted: string;
  chip: string;
};

/** Charcoal stage · near-white lit · charcoal sink (Radix grayDark only). */
const FOCUS_DARK: FocusPalette = {
  field: grayDark.gray1,
  lit: grayDark.gray12,
  // Dim mass — bright enough to read structure; still clearly sunk vs lit.
  dimNode: grayDark.gray5,
  dimEdge: grayDark.gray6,
  litLabel: grayDark.gray1,
  dimLabel: grayDark.gray11,
  lensMuted: grayDark.gray9,
  bondMuted: grayDark.gray10,
  chip: grayDark.gray1,
};

const FOCUS_ON = 1;
const FOCUS_OFF = 0;
const DOTTED: [number, number] = [0, 6.5];
/** Soft ceiling for focus-mode edge boost under the cursor lens. */
const LENS_CEILING = 0.82;

const focusLive: FocusPalette & { inverted: boolean } = {
  inverted: false,
  ...FOCUS_DARK,
};

function applyFocusPalette() {
  focusLive.field = FOCUS_DARK.field;
  focusLive.lit = FOCUS_DARK.lit;
  focusLive.dimNode = FOCUS_DARK.dimNode;
  focusLive.dimEdge = FOCUS_DARK.dimEdge;
  focusLive.litLabel = FOCUS_DARK.litLabel;
  focusLive.dimLabel = FOCUS_DARK.dimLabel;
  focusLive.lensMuted = FOCUS_DARK.lensMuted;
  focusLive.bondMuted = FOCUS_DARK.bondMuted;
  focusLive.chip = FOCUS_DARK.chip;
}

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

function focusColor(intensity: number, dim = focusLive.dimEdge) {
  if (intensity >= FOCUS_ON) return focusLive.lit;
  if (intensity <= FOCUS_OFF) return dim;
  return mixHex(dim, focusLive.lit, intensity);
}

function massColor(intensity: number) {
  return focusColor(intensity, focusLive.dimNode);
}

function massLabelFill(intensity: number) {
  return intensity >= FOCUS_ON ? focusLive.litLabel : focusLive.dimLabel;
}

function boostIntensity(base: number, lens: number) {
  if (lens <= 0) return base;
  return base + Math.max(0, LENS_CEILING - base) * lens;
}

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

/** Live graph for style callbacks (collapse self-loop checks, etc.). */
let graphLive: Graph | null = null;

/**
 * Edges whose both ends sit inside the same collapsed hull draw as a self-loop
 * on the disc. Hide those — they're just internal links folded away, not a
 * real region→region edge.
 */
function isCollapsedHullLoopEdge(datum: EdgeData): boolean {
  const s = String(datum.source);
  const t = String(datum.target);
  if (s === t) return true;
  const graph = graphLive;
  if (!graph || graph.destroyed) return false;
  try {
    const sNode = graph.getNodeData(s);
    const tNode = graph.getNodeData(t);
    if (!sNode || !tNode) return false;
    const sCombo =
      sNode.combo != null && sNode.combo !== "" ? String(sNode.combo) : null;
    const tCombo =
      tNode.combo != null && tNode.combo !== "" ? String(tNode.combo) : null;
    if (!sCombo || sCombo !== tCombo) return false;
    return Boolean(graph.getComboData(sCombo)?.style?.collapsed);
  } catch {
    return false;
  }
}

function applyThemePalette(mode: ThemeMode) {
  const next = mode === "dark" ? THEME_DARK : THEME_LIGHT;
  themeLive.mode = mode;
  themeLive.ink = next.ink;
  themeLive.node = next.node;
  themeLive.paper = next.paper;
  themeLive.chip = next.chip;
  themeLive.lensLabel = next.lensLabel;
  themeLive.bondLabel = next.bondLabel;
}

/** Defaults for the on-page LOD dial — remount graph when size knobs change. */
export type LodParams = {
  minLevel: number;
  /**
   * At dial = 1, a unit-Ø disc fills this fraction of the shorter stage side.
   * Max camera zoom is derived from that + current unitDiameter (not a fixed ×).
   */
  nodeFill: number;
  foldWindow: number;
  wheelSensitivity: number;
  unitDiameter: number;
  landmarkBoost: number;
  dialSettleMs: number;
};

export const DEFAULT_LOD_PARAMS: LodParams = {
  minLevel: 6,
  nodeFill: 0.8,
  foldWindow: 0.22,
  wheelSensitivity: 0.00021,
  unitDiameter: 50,
  landmarkBoost: 1,
  dialSettleMs: 140,
};

/** Screen-space pad around the viewport for lens culling. */
const CULL_MARGIN_PX = 80;
/** Invisible cursor lens — radius in screen pixels. */
const LENS_RADIUS_PX = 140;
/** Radial layout focus — ambient fixture root. */
const LAYOUT_FOCUS_NODE = "platform-core";

type CullRect = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

/**
 * Module-level: G6 style callbacks are not closures.
 * Mass / presence / size are fractional and updated after dial settle.
 */
const view = {
  mass: new Map<string, number>(),
  presence: new Map<string, number>(),
  size: new Map<string, number>(),
  landmark: new Set<string>(),
  zoom: 1,
  cull: null as CullRect | null,
};

const lodLive: Pick<LodParams, "unitDiameter" | "landmarkBoost"> = {
  unitDiameter: DEFAULT_LOD_PARAMS.unitDiameter,
  landmarkBoost: DEFAULT_LOD_PARAMS.landmarkBoost,
};

/** Live style knobs read by G6 style callbacks (not React closures). */
const styleLive = {
  fontId: "jost" as NodeFontId,
  labelOffsetY: 1,
  labelFontPerDiameter: 0.12,
  /** Screen-px diameter below which node labels fade out. */
  labelAppearPx: 11,
  lineWidth: 1,
  labelFontWeight: 400,
};

const DEFAULT_NODE_STYLE = {
  fontId: "jost" as NodeFontId,
  labelOffsetY: 1,
  labelFontPerDiameter: 0.12,
  labelAppearPx: 11,
  lineWidth: 1,
  labelFontWeight: 400,
};

/** Collide settle knobs — applied after every structural / glide pass. */
type SettleTuning = {
  collidePad: number;
  collideIterations: number;
  /** Soft spring home in phase 1 only — lower lets collide win. */
  snap: number;
  alpha: number;
  alphaDecay: number;
  velocityDecay: number;
  /** Mild many-body; 0 = off. Helps radial clusters breathe. */
  charge: number;
  /** Stop soft sim when alpha falls below this (objective cool threshold). */
  coolAlpha: number;
  /** Cap how long each soft phase may run (ms). */
  maxMs: number;
};

/**
 * Soft-collide defaults biased for a short layout-switch polish:
 * - faster α decay + higher cool threshold → stop when good enough
 * - pad absorbs residual penetration soft sims leave
 * - snap stays weak so springs don't re-jam discs
 */
const DEFAULT_SETTLE: SettleTuning = {
  collidePad: 16,
  collideIterations: 4,
  snap: 0.08,
  alpha: 0.7,
  alphaDecay: 0.045,
  velocityDecay: 0.34,
  charge: 30,
  coolAlpha: 0.02,
  maxMs: 1200,
};

const settleLive: SettleTuning = { ...DEFAULT_SETTLE };

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
  const appear = styleLive.labelAppearPx;
  if (screen <= appear) return 0;
  return Math.min(1, (screen - appear) / Math.max(6, appear * 0.7));
}

const HULL_PREVIEW_ID = "__ambient-hull-preview__";
/** Match buildComboStyle.padding — expand footprint uses the same pad. */
const HULL_COMBO_PADDING = 22;

/** Font ∝ diameter so mass + zoom scale the chip without reflow thrash. */
function isHullPreview(datum: NodeData) {
  return (
    String(datum.id) === HULL_PREVIEW_ID || Boolean(datum.data?._preview)
  );
}

function buildNodeStyle() {
  const font = NODE_FONTS[styleLive.fontId];
  return {
    size: (datum: NodeData) =>
      isHullPreview(datum)
        ? Number(datum.data?._previewSize ?? 0)
        : diameterOf(datum),
    fill: (datum: NodeData) => {
      if (isHullPreview(datum)) return "transparent";
      if (!focusLive.inverted) return themeLive.node;
      const diff = diffOf(datum);
      if (diff === "added") return focusLive.lit;
      if (diff === "removed") return focusLive.field;
      return massColor(intensityOf(datum));
    },
    stroke: (datum: NodeData) => {
      if (isHullPreview(datum)) return themeLive.ink;
      if (!focusLive.inverted) return themeLive.node;
      const diff = diffOf(datum);
      if (diff === "added" || diff === "removed" || diff === "touched") {
        return focusLive.lit;
      }
      return massColor(intensityOf(datum));
    },
    // Preview ring is faint; normal discs use solid node ink.
    strokeOpacity: (datum: NodeData) => (isHullPreview(datum) ? 0.28 : 1),
    lineWidth: (datum: NodeData) => {
      if (isHullPreview(datum)) return 1;
      if (!focusLive.inverted) return styleLive.lineWidth;
      if (diffOf(datum) === "removed") return 1.6;
      if (diffOf(datum) === "added" || diffOf(datum) === "touched") return 1.5;
      return styleLive.lineWidth;
    },
    lineDash: (datum: NodeData) => {
      if (isHullPreview(datum)) return DOTTED;
      if (focusLive.inverted && diffOf(datum) === "removed") return DOTTED;
      return undefined;
    },
    lineCap: "round" as const,
    halo: false,
    badge: false,
    // Never inherit theme selection halo on the footprint ghost.
    haloStrokeOpacity: 0,
    opacity: (datum: NodeData) =>
      isHullPreview(datum) ? 1 : num(datum, "_p") > 0.002 ? 1 : 0,
    labelText: (datum: NodeData) =>
      isHullPreview(datum) ? "" : labelOf(datum),
    labelPlacement: "center" as const,
    // Optical center — keep at 0 unless tuning; positive values push text down.
    labelOffsetY: () => styleLive.labelOffsetY,
    labelOffsetX: 0,
    labelFill: (datum: NodeData) => {
      if (isHullPreview(datum)) return themeLive.paper;
      if (!focusLive.inverted) return themeLive.paper;
      const diff = diffOf(datum);
      if (diff === "added") return focusLive.litLabel;
      if (diff === "touched" || diff === "removed") return focusLive.lit;
      return massLabelFill(intensityOf(datum));
    },
    labelOpacity: (datum: NodeData) => {
      if (isHullPreview(datum)) return 0;
      if (focusLive.inverted) {
        const diff = diffOf(datum);
        if (diff === "touched" || diff === "added" || diff === "removed") {
          return 1;
        }
        return intensityOf(datum) >= FOCUS_ON ? 1 : 0.85;
      }
      return labelOpacityOf(datum);
    },
    labelFontFamily: font.family,
    labelFontSize: (datum: NodeData) =>
      Math.max(0.1, diameterOf(datum) * styleLive.labelFontPerDiameter),
    labelFontWeight: () => styleLive.labelFontWeight,
    labelLineHeight: (datum: NodeData) =>
      Math.max(
        10,
        diameterOf(datum) * styleLive.labelFontPerDiameter * 1.15,
      ),
    labelWordWrap: true,
    labelMaxWidth: (datum: NodeData) => labelBoxWidth(diameterOf(datum)),
    labelMaxLines: 2,
    labelTextOverflow: "ellipsis",
    labelTextAlign: "center" as const,
    labelTextBaseline: "middle" as const,
    cursor: (datum: NodeData) =>
      isHullPreview(datum) ? ("default" as const) : ("grab" as const),
  };
}

function buildNodeState() {
  // No selection chrome — selected/active look identical to idle.
  return {
    selected: { halo: false, haloStrokeOpacity: 0 },
    active: { halo: false, haloStrokeOpacity: 0 },
  };
}

function edgePresence(datum: EdgeData) {
  return num(datum, "_ep");
}

function edgeKindLabel(datum: EdgeData) {
  return String(datum.data?.label ?? "");
}

function lensOf(datum: EdgeData) {
  const value = Number(datum.data?.lens);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
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
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** 0…1 along source→target for the closest point on the segment to (px,py). */
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
  const t = ((px - ax) * dx + (py - ay) * dy) / len2;
  return Math.max(0, Math.min(1, t));
}

function lensFalloff(dist: number, radius: number) {
  if (dist >= radius) return 0;
  const t = 1 - dist / radius;
  return 0.5 - 0.5 * Math.cos(Math.PI * t);
}

function refreshCull(graph: Graph, marginPx = CULL_MARGIN_PX) {
  if (graph.destroyed) return;
  const [w, h] = graph.getSize();
  const zoom = Math.max(0.05, graph.getZoom() || 1);
  const margin = marginPx / zoom;
  const tl = graph.getCanvasByViewport([-margin, -margin]);
  const br = graph.getCanvasByViewport([w + margin, h + margin]);
  view.cull = {
    minX: Math.min(tl[0], br[0]),
    maxX: Math.max(tl[0], br[0]),
    minY: Math.min(tl[1], br[1]),
    maxY: Math.max(tl[1], br[1]),
  };
}

function expandCull(cull: CullRect | null, padWorld: number): CullRect | null {
  if (!cull) return null;
  return {
    minX: cull.minX - padWorld,
    maxX: cull.maxX + padWorld,
    minY: cull.minY - padWorld,
    maxY: cull.maxY + padWorld,
  };
}

function edgeMayHitCull(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  cull: CullRect | null = view.cull,
) {
  if (!cull) return true;
  if (
    (sx >= cull.minX && sx <= cull.maxX && sy >= cull.minY && sy <= cull.maxY) ||
    (tx >= cull.minX && tx <= cull.maxX && ty >= cull.minY && ty <= cull.maxY)
  ) {
    return true;
  }
  const eminX = Math.min(sx, tx);
  const emaxX = Math.max(sx, tx);
  const eminY = Math.min(sy, ty);
  const emaxY = Math.max(sy, ty);
  return !(
    emaxX < cull.minX ||
    eminX > cull.maxX ||
    emaxY < cull.minY ||
    eminY > cull.maxY
  );
}

/**
 * Linkage-idle edge look: plain filaments at rest; SST arrows + kind labels
 * only via hover bond / cursor lens. No CONTAINS enclosure glyph.
 * Focus invert: lit edges show SST at rest; dim filaments stay quiet.
 */
function buildEdgeStyle() {
  const focusTyped = (datum: EdgeData) =>
    focusLive.inverted && isFocusLit(datum);

  return {
    edgeKind: (datum: EdgeData) => linkageEdgeKind(datum),
    pointerEvents: "none" as const,
    stroke: (datum: EdgeData) => {
      if (!focusLive.inverted) return themeLive.ink;
      return focusColor(
        boostIntensity(peakEdgeIntensity(datum), lensOf(datum)),
      );
    },
    lineCap: "round" as const,
    lineJoin: "round" as const,
    // Rest: no arrows unless focus-lit typed. Hover bond reveals them.
    endArrow: (datum: EdgeData) =>
      focusTyped(datum) && isDirectedKind(linkageEdgeKind(datum)),
    endArrowType: "triangle" as const,
    endArrowSize: (datum: EdgeData) =>
      arrowSizeForKind(linkageEdgeKind(datum)),
    endArrowFill: () =>
      focusLive.inverted ? focusLive.lit : themeLive.ink,
    endArrowFillOpacity: 1,
    endArrowStrokeOpacity: 1,
    endArrowOffset: (datum: EdgeData) =>
      focusTyped(datum) && isDirectedKind(linkageEdgeKind(datum))
        ? arrowSizeForKind(linkageEdgeKind(datum)) / 2 + 1
        : 0.01,
    lineWidth: (datum: EdgeData) => {
      if (focusLive.inverted) {
        if (focusTyped(datum)) {
          return linkageEdgeKind(datum) === "leadsto" ? 1.75 : 1.45;
        }
        const boosted = boostIntensity(peakEdgeIntensity(datum), lensOf(datum));
        return boosted >= FOCUS_ON ? 1.35 : 1.05;
      }
      const base =
        linkageEdgeKind(datum) === "leadsto"
          ? 1.25
          : linkageEdgeKind(datum) === "contains"
            ? 1.1
            : 1.05;
      return base + 0.55 * lensOf(datum);
    },
    lineDash: (datum: EdgeData) => {
      if (focusLive.inverted && diffOf(datum) === "removed") return DOTTED;
      return undefined;
    },
    opacity: (datum: EdgeData) => {
      if (isCollapsedHullLoopEdge(datum)) return 0;
      const ep = edgePresence(datum);
      if (ep <= 0.02) return 0;
      if (focusLive.inverted) return 1;
      return Math.min(1, ep * (0.55 + 0.35 * lensOf(datum)));
    },
    labelText: (datum: EdgeData) => edgeKindLabel(datum),
    labelFontFamily: FONT_MONO_FAMILY,
    labelFontSize: 7,
    labelFill: (datum: EdgeData) => {
      if (!focusLive.inverted) return themeLive.lensLabel;
      const i = boostIntensity(peakEdgeIntensity(datum), lensOf(datum));
      if (i >= FOCUS_ON) return focusLive.lit;
      if (i <= FOCUS_OFF) return focusLive.lensMuted;
      return mixHex(focusLive.lensMuted, focusLive.lit, i);
    },
    labelBackground: true,
    labelBackgroundFill: () =>
      focusLive.inverted ? focusLive.chip : themeLive.chip,
    labelAutoRotate: false,
    labelPadding: [2, 3] as [number, number],
    // Bond states override near the hovered endpoint. Lens placement is
    // applied inside AmbientLinkageEdge from `_lp` (on-edge, nearest cursor).
    labelPlacement: 0.5,
    labelOffsetX: 0,
    labelOffsetY: 0,
    labelOpacity: (datum: EdgeData) => {
      if (isCollapsedHullLoopEdge(datum)) return 0;
      if (edgePresence(datum) <= 0.02) return 0;
      if (focusTyped(datum)) return 1;
      const lens = lensOf(datum);
      return lens <= 0 ? 0 : Math.min(1, lens);
    },
    // Solid chip whenever the label is shown — never see the stroke through.
    labelBackgroundOpacity: (datum: EdgeData) => {
      if (isCollapsedHullLoopEdge(datum)) return 0;
      if (edgePresence(datum) <= 0.02) return 0;
      if (focusTyped(datum)) return 1;
      return lensOf(datum) <= 0 ? 0 : 1;
    },
    visibility: (datum: EdgeData) =>
      isCollapsedHullLoopEdge(datum) ? ("hidden" as const) : ("visible" as const),
    increasedLineWidthForHitTesting: 20,
  };
}

/** Hover bond — SST kind + arrow for directed kinds (linkage idle). */
function buildEdgeState() {
  const bondBase = {
    lineWidth: (datum: EdgeData) => {
      if (isFocusLit(datum) && focusLive.inverted) {
        return linkageEdgeKind(datum) === "leadsto" ? 1.75 : 1.45;
      }
      const base =
        linkageEdgeKind(datum) === "leadsto"
          ? 1.75
          : linkageEdgeKind(datum) === "contains"
            ? 1.6
            : 1.35;
      return base + 0.45;
    },
    stroke: () => (focusLive.inverted ? focusLive.bondMuted : themeLive.ink),
    strokeOpacity: 1,
    opacity: (datum: EdgeData) =>
      isCollapsedHullLoopEdge(datum)
        ? 0
        : Math.min(1, edgePresence(datum) * 0.95),
    endArrow: (datum: EdgeData) =>
      !isCollapsedHullLoopEdge(datum) &&
      isDirectedKind(linkageEdgeKind(datum)),
    endArrowSize: (datum: EdgeData) =>
      arrowSizeForKind(linkageEdgeKind(datum)),
    endArrowFill: () => (focusLive.inverted ? focusLive.lit : themeLive.ink),
    endArrowFillOpacity: (datum: EdgeData) =>
      !isCollapsedHullLoopEdge(datum) &&
      isDirectedKind(linkageEdgeKind(datum))
        ? 1
        : 0,
    endArrowStrokeOpacity: (datum: EdgeData) =>
      !isCollapsedHullLoopEdge(datum) &&
      isDirectedKind(linkageEdgeKind(datum))
        ? 1
        : 0,
    endArrowOffset: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum))
        ? arrowSizeForKind(linkageEdgeKind(datum)) / 2 + 1
        : 0.01,
    labelFill: () =>
      focusLive.inverted ? focusLive.lit : themeLive.bondLabel,
    labelBackground: true,
    labelBackgroundFill: () =>
      focusLive.inverted ? focusLive.chip : themeLive.chip,
    labelBackgroundOpacity: (datum: EdgeData) =>
      isCollapsedHullLoopEdge(datum) ? 0 : 1,
    labelOpacity: (datum: EdgeData) =>
      isCollapsedHullLoopEdge(datum) ? 0 : 1,
    labelFontSize: 7,
  };
  // Placement is a fixed px distance from the hovered endpoint — computed
  // in AmbientLinkageEdge (out = source side, inn = target side).
  return {
    selected: {
      halo: false,
      haloStrokeOpacity: 0,
    },
    active: {
      halo: false,
      haloStrokeOpacity: 0,
    },
    out: {
      ...bondBase,
      labelOffsetX: 0,
      labelOffsetY: 0,
    },
    inn: {
      ...bondBase,
      labelOffsetX: 0,
      labelOffsetY: 0,
    },
  };
}

type HoverBundle = {
  out: Set<string>;
  inn: Set<string>;
};

function emptyHoverBundle(): HoverBundle {
  return { out: new Set(), inn: new Set() };
}

function hoverBundleFor(graph: Graph, nodeId: string): HoverBundle {
  const out = new Set<string>();
  const inn = new Set<string>();
  for (const edge of graph.getRelatedEdgesData(nodeId)) {
    const id = String(edge.id);
    if (isCollapsedHullLoopEdge(edge)) continue;
    if (Number(edge.data?._ep ?? 0) <= 0.02) continue;
    // Focus-lit filaments already show SST — hover must not restyle them.
    if (focusLive.inverted && isFocusLit(edge)) continue;
    if (String(edge.source) === nodeId) out.add(id);
    else inn.add(id);
  }
  return { out, inn };
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
  const size = new Map<string, number>();
  for (const id of model.facts.keys()) {
    size.set(id, diameterOf({ id } as NodeData));
  }
  view.size = size;

  let ink = 0;
  for (const [id, mass] of state.mass) {
    ink += (state.presence.get(id) ?? 0) * mass;
  }
  (window as Window & { __ambientCanvasView?: unknown }).__ambientCanvasView = {
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

/* ── Layout lenses (from g6-lens; settle then freeze) ─────────────── */

/**
 * Mass/LOD is EXPERIMENTAL and hidden (2026-07-27). Layout presets are
 * experimental too but stay reachable — LOD is the one that changes what the
 * graph *says*, since nodes vanish, so it is off until that is settled.
 */
const SHOW_EXPERIMENTAL_LOD = false;

type LayoutId =
  | "nested"
  | "cascade"
  | "spine"
  | "radial"
  | "concentric"
  | "cluster"
  | "glide";

const LAYOUTS: Array<{ id: LayoutId; label: string; note: string }> = [
  {
    id: "nested",
    label: "Nested",
    note: "antv-dagre TB on CONTAINS → soft collide → freeze. Off while Hulls on.",
  },
  {
    id: "cascade",
    label: "Cascade",
    note: "antv-dagre LR on LEADSTO → soft collide → freeze. Hulls: dagre outer · concentric inner.",
  },
  {
    id: "spine",
    label: "Spine",
    note: "LEADSTO dagre + CONTAINS attach → soft collide → freeze. Off while Hulls on.",
  },
  {
    id: "radial",
    label: "Radial",
    note: "Radial → soft collide → freeze. Hulls: radial outer · concentric inner.",
  },
  {
    id: "concentric",
    label: "Concentric",
    note: "Rings by mass × landmark → soft collide → freeze. Hulls: concentric outer · concentric inner.",
  },
  {
    id: "cluster",
    label: "Cluster",
    note: "Seeded d3-force settle → soft collide → freeze. Hulls: force outer · force inner.",
  },
  {
    id: "glide",
    label: "Glide",
    note: "Seeded glide-loose settle → soft collide → freeze. Hulls: loose force outer · concentric inner.",
  },
];

/** Stable seed so the same chip always starts from the same scatter. */
const LAYOUT_POSITION_SEED = 0x4c41594f; // "LAYO"

function hashString(input: string, seed = 0): number {
  let h = seed >>> 0;
  for (let i = 0; i < input.length; i++) {
    h = Math.imul(h ^ input.charCodeAt(i), 0x9e3779b1);
  }
  return h >>> 0;
}

/** Mulberry32 — deterministic [0,1) from a 32-bit seed. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Wipe inherited x/y before a layout pass so Cluster/Glide (and sticky
 * structural seeds) don't depend on whichever lens ran last.
 */
async function resetPositionsForLayout(graph: Graph, layoutId: LayoutId) {
  if (graph.destroyed) return;
  const seed = hashString(layoutId, LAYOUT_POSITION_SEED);
  const rand = mulberry32(seed);
  const nodes = graph
    .getNodeData()
    .filter((n) => String(n.id) !== HULL_PREVIEW_ID)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const n = nodes.length;
  if (n === 0) return;
  const R = 420 + Math.sqrt(n) * 48;
  const updates = nodes.map((node, i) => {
    const id = String(node.id);
    const h = hashString(id, seed);
    const jitter = rand();
    const angle = (2 * Math.PI * (i + (h % 1000) / 1000)) / n;
    const radius = R * (0.28 + ((h % 1000) / 1000) * 0.72 + jitter * 0.04);
    return {
      id,
      style: {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      },
    };
  });
  graph.updateNodeData(updates);
  await graph.draw().catch(() => {});
}

type DagreTuning = { nodesep: number; ranksep: number };
type SpineTuning = {
  nodesep: number;
  ranksep: number;
  /** Vertical gap between siblings fanned under a parent. */
  attachSep: number;
  /** How far below the parent the child fan sits (LR spine). */
  attachOffset: number;
};
type RadialTuning = { unitRadius: number; linkDistance: number };
type ConcentricTuning = { nodeSize: number; maxLevelDiff: number };
type ClusterTuning = { linkDist: number; charge: number };
type GlideTuning = { linkDist: number; linkStrength: number };

type LayoutTunings = {
  nested: DagreTuning;
  cascade: DagreTuning;
  spine: SpineTuning;
  radial: RadialTuning;
  concentric: ConcentricTuning;
  cluster: ClusterTuning;
  glide: GlideTuning;
};

const DEFAULT_LAYOUT_TUNINGS: LayoutTunings = {
  nested: { nodesep: 64, ranksep: 100 },
  cascade: { nodesep: 64, ranksep: 110 },
  spine: { nodesep: 64, ranksep: 120, attachSep: 56, attachOffset: 90 },
  // Room between rings ≈ unit Ø + pad; radial was too tight at 140.
  radial: { unitRadius: 220, linkDistance: 240 },
  concentric: { nodeSize: 96, maxLevelDiff: 0.2 },
  // Larger than g6-lens defaults — ambient unit Ø is bigger.
  cluster: { linkDist: 240, charge: 520 },
  glide: { linkDist: 280, linkStrength: 0.07 },
};

/** Per-node collide radius from current mass LOD sizes (folded ≈ no push). */
function nodeCollideRadius(node: { id?: string | number }) {
  const id = String(node.id ?? "");
  const d = view.size.get(id) ?? lodLive.unitDiameter;
  if (d < 2) return 1;
  return d / 2 + settleLive.collidePad;
}

/** Higher score → closer to centre (mass × landmark boost). */
function concentricSortScore(node: {
  id?: string | number;
  data?: Record<string, unknown>;
}) {
  const id = String(node.id ?? "");
  const mass = view.mass.get(id) ?? Number(node.data?._m ?? 1);
  const landmark = view.landmark.has(id) ? lodLive.landmarkBoost : 1;
  return Math.max(0.01, mass * landmark);
}

function structuralLayout(
  id: Exclude<LayoutId, "glide" | "cluster" | "spine">,
  tunings: LayoutTunings,
): LayoutOptions {
  if (id === "nested") {
    const t = tunings.nested;
    return {
      type: LENS_DAGRE_CONTAINS,
      rankdir: "TB",
      nodesep: t.nodesep,
      ranksep: t.ranksep,
      controlPoints: false,
      animation: false,
    };
  }
  if (id === "cascade") {
    const t = tunings.cascade;
    return {
      type: LENS_DAGRE_LEADSTO,
      rankdir: "LR",
      nodesep: t.nodesep,
      ranksep: t.ranksep,
      controlPoints: false,
      animation: false,
    };
  }
  if (id === "concentric") {
    const t = tunings.concentric;
    return {
      type: "concentric",
      preventOverlap: true,
      nodeSize: Math.max(24, t.nodeSize),
      equidistant: true,
      maxLevelDiff: t.maxLevelDiff,
      sortBy: (node) => concentricSortScore(node as never),
      animation: false,
    };
  }
  const t = tunings.radial;
  const nodeSize = lodLive.unitDiameter + settleLive.collidePad * 2;
  return {
    type: "radial",
    unitRadius: t.unitRadius,
    linkDistance: t.linkDistance,
    preventOverlap: true,
    nodeSize,
    focusNode: LAYOUT_FOCUS_NODE,
    animation: false,
  };
}

function spineDagreLayout(tunings: LayoutTunings): LayoutOptions {
  const t = tunings.spine;
  return {
    type: LENS_DAGRE_LEADSTO,
    rankdir: "LR",
    nodesep: t.nodesep,
    ranksep: t.ranksep,
    controlPoints: false,
    animation: false,
  };
}

/**
 * After LEADSTO dagre: keep spine endpoints where they are; fan non-spine
 * CONTAINS children under each parent (parent-first so nested regions work).
 */
async function attachContainsBesideParents(
  graph: Graph,
  tunings: SpineTuning,
) {
  if (graph.destroyed) return;

  const spineIds = new Set<string>();
  const childrenOf = new Map<string, string[]>();
  for (const edge of graph.getEdgeData()) {
    const kind = linkageEdgeKind(edge);
    const s = String(edge.source);
    const t = String(edge.target);
    if (kind === "leadsto") {
      spineIds.add(s);
      spineIds.add(t);
      continue;
    }
    if (kind !== "contains") continue;
    const list = childrenOf.get(s);
    if (list) list.push(t);
    else childrenOf.set(s, [t]);
  }

  // Parents before children in the CONTAINS forest.
  const parentCount = new Map<string, number>();
  for (const id of childrenOf.keys()) parentCount.set(id, parentCount.get(id) ?? 0);
  for (const kids of childrenOf.values()) {
    for (const kid of kids) {
      parentCount.set(kid, (parentCount.get(kid) ?? 0) + 1);
    }
  }
  const queue: string[] = [];
  for (const id of childrenOf.keys()) {
    if ((parentCount.get(id) ?? 0) === 0) queue.push(id);
  }
  // Also enqueue spine parents that only appear as CONTAINS sources.
  for (const id of spineIds) {
    if (childrenOf.has(id) && !queue.includes(id)) queue.push(id);
  }
  const seen = new Set<string>();
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    for (const kid of childrenOf.get(id) ?? []) {
      if (childrenOf.has(kid) && !seen.has(kid)) queue.push(kid);
    }
  }
  for (const id of childrenOf.keys()) {
    if (!seen.has(id)) order.push(id);
  }

  const moves: Record<string, [number, number]> = {};
  const sep = Math.max(24, tunings.attachSep);
  const offset = Math.max(24, tunings.attachOffset);

  const posOf = (id: string): [number, number] | null => {
    if (moves[id]) return moves[id]!;
    try {
      const p = graph.getElementPosition(id);
      return [p[0], p[1]];
    } catch {
      return null;
    }
  };

  for (const parent of order) {
    const kids = (childrenOf.get(parent) ?? []).filter((c) => !spineIds.has(c));
    if (!kids.length) continue;
    const parentPos = posOf(parent);
    if (!parentPos) continue;
    const [px, py] = parentPos;
    const n = kids.length;
    kids.forEach((child, i) => {
      const x = px;
      const y = py + offset + (i - (n - 1) / 2) * sep;
      moves[child] = [x, y];
    });
  }

  const ids = Object.keys(moves);
  if (!ids.length) return;
  await graph.translateElementTo(moves, false).catch(() => {});
}

/**
 * Force-settle link weights by SST kind.
 * CONTAINS / LEADSTO keep the base spring; EXPRESSES / NEARTO stay weak so
 * they don't fight enclosure or the causal spine (Cluster / Glide only —
 * dagre lenses already ignore them via kind filter).
 */
function forceLinkStrength(
  base: number,
  edge: { data?: Record<string, unknown> },
) {
  const kind = linkageEdgeKind(edge as never);
  if (kind === "expresses" || kind === "nearto") {
    return Math.max(0.01, base * 0.18);
  }
  if (kind === "contains" || kind === "leadsto") return base;
  // Unknown labels (BOUNDS / GOVERNS / …) — soft, like association.
  return Math.max(0.01, base * 0.22);
}

function forceLinkDistance(
  base: number,
  edge: { data?: Record<string, unknown> },
) {
  const kind = linkageEdgeKind(edge as never);
  if (kind === "expresses" || kind === "nearto") return base * 1.4;
  if (kind === "contains") return base * 0.92;
  if (kind === "leadsto") return base;
  return base * 1.25;
}

/** Open force settle — links + charge; EXPRESSES/NEARTO springs stay weak. */
function clusterSettleLayout(tunings: LayoutTunings): LayoutOptions {
  const t = tunings.cluster;
  const baseStrength = 0.45;
  const baseDist = t.linkDist;
  return {
    type: "d3-force",
    link: {
      distance: (edge) => forceLinkDistance(baseDist, edge as never),
      strength: (edge) => forceLinkStrength(baseStrength, edge as never),
    },
    manyBody: { strength: -Math.abs(t.charge) },
    collide: {
      radius: nodeCollideRadius,
      strength: 1,
      iterations: Math.max(3, settleLive.collideIterations),
    },
    alphaDecay: 0.05,
    velocityDecay: 0.42,
    // After seeded scatter, run hot so we don't sit in the previous basin.
    alpha: 0.9,
    alphaTarget: 0,
    animation: true,
  } as LayoutOptions;
}

function glideSettleLayout(tunings: LayoutTunings): LayoutOptions {
  const t = tunings.glide;
  const base = FORCE_PRESETS["glide-loose"].layout;
  return {
    ...base,
    link: {
      distance: (edge) => forceLinkDistance(t.linkDist, edge as never),
      strength: (edge) => forceLinkStrength(t.linkStrength, edge as never),
      iterations: 1,
    },
    manyBody: settleLive.charge > 0
      ? { strength: -Math.abs(settleLive.charge) }
      : false,
    collide: {
      radius: nodeCollideRadius,
      strength: 1,
      iterations: settleLive.collideIterations,
    },
    center: false,
    alpha: 0.9,
    alphaTarget: 0,
    animation: true,
  } as LayoutOptions;
}

/**
 * Hulls: each chip maps to real combo-combined inner (comboId set) /
 * outer (comboId null) strategies — not one shared default.
 */
function hullsCombinedLayout(
  id: LayoutId,
  tunings: LayoutTunings,
): LayoutOptions {
  const nodeSize = Math.max(
    40,
    lodLive.unitDiameter + settleLive.collidePad * 2,
  );

  const innerFor = (): Record<string, unknown> => {
    switch (id) {
      case "cluster":
        return {
          type: "force",
          preventOverlap: true,
          linkDistance: Math.max(40, tunings.cluster.linkDist * 0.4),
        };
      case "glide":
        return {
          type: "concentric",
          preventOverlap: true,
          equidistant: true,
          nodeSize: Math.max(24, tunings.concentric.nodeSize * 0.75),
        };
      case "cascade":
      case "radial":
      case "concentric":
      default:
        return {
          type: "concentric",
          preventOverlap: true,
          equidistant: true,
          maxLevelDiff: tunings.concentric.maxLevelDiff,
          nodeSize: Math.max(24, tunings.concentric.nodeSize),
        };
    }
  };

  const outerFor = (): Record<string, unknown> => {
    switch (id) {
      case "cascade":
        return {
          type: "dagre",
          rankdir: "LR",
          nodesep: tunings.cascade.nodesep,
          ranksep: tunings.cascade.ranksep,
        };
      case "radial":
        return {
          type: "radial",
          unitRadius: tunings.radial.unitRadius,
          linkDistance: tunings.radial.linkDistance,
          preventOverlap: true,
          nodeSize,
          focusNode: LAYOUT_FOCUS_NODE,
        };
      case "concentric":
        return {
          type: "concentric",
          preventOverlap: true,
          equidistant: true,
          maxLevelDiff: tunings.concentric.maxLevelDiff,
          nodeSize: Math.max(24, tunings.concentric.nodeSize),
        };
      case "cluster":
        return {
          type: "force",
          preventOverlap: true,
          linkDistance: tunings.cluster.linkDist,
        };
      case "glide":
        return {
          type: "force",
          preventOverlap: true,
          linkDistance: tunings.glide.linkDist,
        };
      default:
        return { type: "force", preventOverlap: true };
    }
  };

  return {
    type: "combo-combined",
    spacing: 48,
    comboPadding: 28,
    nodeSize,
    layout: (comboId: string | null) => (comboId ? innerFor() : outerFor()),
  } as LayoutOptions;
}

/** Layouts that need CONTAINS edges — blocked while Hulls are on. */
const HULLS_BLOCKED_LAYOUTS: ReadonlySet<LayoutId> = new Set([
  "nested",
  "spine",
]);

/**
 * Member nodes still in the model while a combo is collapsed (with last known
 * graph positions). Returns expand circumdiameter + member mean (where G6
 * parks the collapsed disc).
 */
function hullExpandPreviewGeom(
  graph: Graph,
  comboId: string,
): {
  x: number;
  y: number;
  size: number;
  membersCx: number;
  membersCy: number;
} | null {
  const nodes = graph
    .getDescendantsData(comboId)
    .filter((d) => {
      try {
        return graph.getElementType(String(d.id)) === "node";
      } catch {
        return false;
      }
    });
  if (nodes.length === 0) return null;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let sumX = 0;
  let sumY = 0;
  let counted = 0;
  for (const d of nodes) {
    const x = Number(d.style?.x);
    const y = Number(d.style?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const raw = d.style?.size;
    const diam = Array.isArray(raw)
      ? Number(raw[0])
      : Number(raw ?? diameterOf(d as NodeData));
    const r = Math.max(4, (Number.isFinite(diam) ? diam : 40) / 2);
    minX = Math.min(minX, x - r);
    maxX = Math.max(maxX, x + r);
    minY = Math.min(minY, y - r);
    maxY = Math.max(maxY, y + r);
    sumX += x;
    sumY += y;
    counted += 1;
  }
  if (!Number.isFinite(minX) || counted === 0) return null;

  const pad = HULL_COMBO_PADDING;
  minX -= pad;
  maxX += pad;
  minY -= pad;
  maxY += pad;
  const width = maxX - minX;
  const height = maxY - minY;
  return {
    x: (minX + maxX) / 2,
    y: (minY + maxY) / 2,
    size: Math.sqrt(width * width + height * height),
    membersCx: sumX / counted,
    membersCy: sumY / counted,
  };
}

/**
 * After dragging a collapsed hull, bake the same translation into member
 * positions so expand + preview stay aligned with the disc.
 */
function syncCollapsedComboMembers(graph: Graph, comboId: string) {
  if (graph.destroyed) return;
  const geom = hullExpandPreviewGeom(graph, comboId);
  if (!geom) return;
  let px = geom.membersCx;
  let py = geom.membersCy;
  try {
    const pos = graph.getElementPosition(comboId);
    px = pos[0];
    py = pos[1];
  } catch {
    return;
  }
  const dx = px - geom.membersCx;
  const dy = py - geom.membersCy;
  if (Math.hypot(dx, dy) < 0.5) return;

  const updates: { id: string; style: { x: number; y: number } }[] = [];
  for (const d of graph.getDescendantsData(comboId)) {
    try {
      if (graph.getElementType(String(d.id)) !== "node") continue;
    } catch {
      continue;
    }
    const x = Number(d.style?.x);
    const y = Number(d.style?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    updates.push({ id: String(d.id), style: { x: x + dx, y: y + dy } });
  }
  if (updates.length) graph.updateNodeData(updates);
}

async function clearHullExpandPreview(graph: Graph) {
  if (graph.destroyed) return;
  try {
    if (!graph.getNodeData(HULL_PREVIEW_ID)) return;
  } catch {
    return;
  }
  graph.removeNodeData([HULL_PREVIEW_ID]);
  await graph.draw().catch(() => {});
}

async function showHullExpandPreview(graph: Graph, comboId: string) {
  if (graph.destroyed) return;
  const geom = hullExpandPreviewGeom(graph, comboId);
  if (!geom) {
    await clearHullExpandPreview(graph);
    return;
  }
  // Collapsed disc may have been dragged — members stay at collapse-time
  // coords until sync. Shift the footprint so it rides with the disc.
  let x = geom.x;
  let y = geom.y;
  try {
    const [cx, cy] = graph.getElementPosition(comboId);
    x = geom.x + (cx - geom.membersCx);
    y = geom.y + (cy - geom.membersCy);
  } catch {
    /* keep stored geom */
  }
  const row = {
    id: HULL_PREVIEW_ID,
    data: {
      _preview: true,
      _previewSize: geom.size,
      _p: 1,
      _m: 1,
    },
    style: {
      x,
      y,
      size: geom.size,
      zIndex: -2,
      pointerEvents: "none" as const,
    },
  };
  try {
    if (graph.getNodeData(HULL_PREVIEW_ID)) {
      graph.updateNodeData([row]);
    } else {
      graph.addNodeData([row]);
    }
  } catch {
    graph.addNodeData([row]);
  }
  try {
    await graph.setElementState(HULL_PREVIEW_ID, [], false);
  } catch {
    /* ok */
  }
  await graph.draw().catch(() => {});
}

function buildComboStyle() {
  return {
    // Open: outline hull + name on top. Collapsed: same disc as a node,
    // region label centered inside (no member-count marker).
    fill: "transparent",
    fillOpacity: 0,
    stroke: () => (focusLive.inverted ? focusLive.dimEdge : themeLive.ink),
    lineWidth: 1.25,
    padding: HULL_COMBO_PADDING,
    // Transparent fill is skipped under pointerEvents "auto". Force fill
    // hits so empty interior can drag the hull; members stay above (zIndex 1).
    pointerEvents: "fill" as const,
    collapsedFill: "transparent",
    collapsedFillOpacity: 0,
    collapsedStroke: () =>
      focusLive.inverted ? focusLive.dimEdge : themeLive.ink,
    collapsedLineWidth: 1.25,
    // Solid disc at rest; hover expand-preview ring stays dotted.
    collapsedLineDash: 0,
    collapsedPointerEvents: "fill" as const,
    labelText: (datum: {
      id?: string | number;
      data?: Record<string, unknown>;
    }) => String(datum.data?.label ?? datum.id ?? ""),
    // Default top; collapse handlers force `style.labelPlacement: "center"`.
    // Don't pin labelTextBaseline — G6 uses bottom for "top" so the name
    // sits above the stroke; "middle" was bisecting the border.
    labelPlacement: (datum: {
      style?: { collapsed?: boolean; labelPlacement?: string };
    }) => {
      if (datum.style?.collapsed) return "center" as const;
      if (datum.style?.labelPlacement === "center") return "center" as const;
      return "top" as const;
    },
    // Expanded: a few px above the rim. Collapsed/center: stay put.
    labelOffsetY: (datum: {
      style?: { collapsed?: boolean; labelPlacement?: string };
    }) => {
      if (datum.style?.collapsed) return 0;
      if (datum.style?.labelPlacement === "center") return 0;
      return -6;
    },
    labelFill: () =>
      focusLive.inverted ? focusLive.dimLabel : themeLive.bondLabel,
    labelFontSize: 11,
    labelFontWeight: () => styleLive.labelFontWeight,
              labelFontFamily: FONT_SANS_FAMILY,
    labelTextAlign: "center" as const,
    collapsedSize: 72,
    collapsedMarker: false,
    cursor: "pointer" as const,
  };
}

/** After collapse/expand, pin label placement — G6 won't rebind it on its own. */
function syncHullLabelPlacement(graph: Graph, comboId: string, collapsed: boolean) {
  if (graph.destroyed) return;
  graph.updateComboData([
    {
      id: comboId,
      style: { labelPlacement: collapsed ? "center" : "top" },
    },
  ]);
}

/**
 * Soft overlap polish after a structural layout — one short budgeted pass.
 * Weak snap to anchors + collide (+ mild charge). Pad absorbs residual
 * penetration; always stopped before interaction.
 */
function shapedSettleLayout(
  anchors: Map<string, { x: number; y: number }>,
): LayoutOptions {
  const snap = Math.max(0.02, settleLive.snap);
  return {
    type: "d3-force",
    link: false,
    manyBody: settleLive.charge > 0
      ? { strength: -Math.abs(settleLive.charge) }
      : false,
    collide: {
      radius: nodeCollideRadius,
      strength: 1,
      iterations: settleLive.collideIterations,
    },
    x: {
      strength: snap,
      x: (d: { id: string | number }) => anchors.get(String(d.id))?.x ?? 0,
    },
    y: {
      strength: snap,
      y: (d: { id: string | number }) => anchors.get(String(d.id))?.y ?? 0,
    },
    alpha: settleLive.alpha,
    alphaDecay: settleLive.alphaDecay,
    velocityDecay: settleLive.velocityDecay,
    alphaTarget: 0,
    center: false,
    // Positions still tick; skip declarative animation overhead while settling.
    animation: false,
  } as LayoutOptions;
}

function readSimAlpha(graph: Graph): number | null {
  try {
    // @ts-expect-error layout controller is not on the public Graph type
    const layouts = graph.context?.layout?.getLayoutInstance?.() ?? [];
    for (const layout of layouts as Array<{
      instance?: { simulation?: { alpha: () => number } };
      simulation?: { alpha: () => number };
    }>) {
      const sim = layout.instance?.simulation ?? layout.simulation;
      if (!sim || typeof sim.alpha !== "function") continue;
      const a = sim.alpha();
      if (typeof a === "number" && Number.isFinite(a)) return a;
    }
  } catch {
    /* ok */
  }
  return null;
}

/** Run a force layout and wait until alpha cools (or maxMs), then stop. */
async function runSoftPhase(
  graph: Graph,
  options: LayoutOptions,
  opts: {
    cancelled: boolean;
    gen: number;
    layoutGen: { current: number };
  },
) {
  if (graph.destroyed || opts.cancelled) return;
  await stopLayoutQuiet(graph);
  if (graph.destroyed || opts.cancelled || opts.layoutGen.current !== opts.gen) {
    return;
  }
  graph.setLayout(options);
  // Do not bare-await layout() — stopLayout often leaves that promise pending.
  void graph.layout().catch(() => {});
  const cool = Math.max(1e-4, settleLive.coolAlpha);
  const deadline = Date.now() + Math.max(400, settleLive.maxMs);
  while (Date.now() < deadline) {
    if (
      opts.cancelled ||
      graph.destroyed ||
      opts.layoutGen.current !== opts.gen
    ) {
      break;
    }
    const a = readSimAlpha(graph);
    // null = sim already gone / finished
    if (a === null || a < cool) break;
    await new Promise<void>((r) => window.setTimeout(r, 40));
  }
  await stopLayoutQuiet(graph);
}

function captureAnchors(
  graph: Graph,
  into: Map<string, { x: number; y: number }>,
) {
  into.clear();
  for (const node of graph.getNodeData()) {
    const id = String(node.id);
    if (id === HULL_PREVIEW_ID) continue;
    let x = Number(node.style?.x);
    let y = Number(node.style?.y);
    try {
      const p = graph.getElementPosition(id);
      x = p[0];
      y = p[1];
    } catch {
      /* style */
    }
    if (Number.isFinite(x) && Number.isFinite(y)) {
      into.set(id, { x, y });
    }
  }
}

async function stopLayoutQuiet(graph: Graph) {
  try {
    graph.stopLayout();
  } catch {
    /* ok */
  }
}

/**
 * Zoom where a graph-space disc of `diameter` fills `fill` of the shorter
 * stage side — the node-level max zoom budget.
 */
function zoomForNodeFill(graph: Graph, diameter: number, fill: number): number {
  if (graph.destroyed) return 1;
  const [stageW, stageH] = graph.getSize();
  const target = Math.min(stageW, stageH) * Math.max(0.35, Math.min(0.98, fill));
  return target / Math.max(4, diameter);
}

/** Frame visible (present) discs — folded zero-size nodes must not inflate the box. */
async function frameVisible(graph: Graph): Promise<number> {
  if (graph.destroyed) return graph.getZoom();
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of graph.getNodeData()) {
    const id = String(node.id);
    const d = view.size.get(id) ?? 0;
    if (d < 2) continue;
    let x = Number(node.style?.x);
    let y = Number(node.style?.y);
    try {
      const p = graph.getElementPosition(id);
      x = p[0];
      y = p[1];
    } catch {
      /* use style */
    }
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    minX = Math.min(minX, x - d / 2);
    maxX = Math.max(maxX, x + d / 2);
    minY = Math.min(minY, y - d / 2);
    maxY = Math.max(maxY, y + d / 2);
  }
  if (!Number.isFinite(minX)) {
    await graph.fitView({ when: "always", direction: "both" }, false);
    return graph.getZoom();
  }
  const [stageW, stageH] = graph.getSize();
  const pad = 1.14;
  const fitZoom = Math.min(
    stageW / Math.max(1, (maxX - minX) * pad),
    stageH / Math.max(1, (maxY - minY) * pad),
  );
  // No min-zoom floor — tall nested/cascade graphs must be allowed to shrink
  // so overview survivors stay in frame (legibility comes from mass LOD sizes).
  await graph.zoomTo(fitZoom, false).catch(() => {});
  const [vx, vy] = graph.getViewportByCanvas([
    (minX + maxX) / 2,
    (minY + maxY) / 2,
  ]);
  const [ccx, ccy] = graph.getCanvasCenter();
  await graph.translateBy([ccx - vx, ccy - vy], false).catch(() => {});
  return fitZoom;
}

export function AmbientCanvasLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const applyDialRef = useRef<(force?: boolean) => Promise<void>>(async () => {});
  const applyLayoutRef = useRef<(id: LayoutId) => Promise<void>>(async () => {});
  const lodRef = useRef<LodParams>(DEFAULT_LOD_PARAMS);
  const lodEnabledRef = useRef(true);
  const layoutTuningsRef = useRef<LayoutTunings>(DEFAULT_LAYOUT_TUNINGS);
  const layoutGenRef = useRef(0);

  const [lod, setLod] = useState<LodParams>(DEFAULT_LOD_PARAMS);
  const [lodEnabled, setLodEnabled] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>("light");
  const [seamMode, setSeamMode] = useState<AmbientSeamMode>("idle");
  const [fontId, setFontId] = useState<NodeFontId>(DEFAULT_NODE_STYLE.fontId);
  const [labelOffsetY, setLabelOffsetY] = useState(
    DEFAULT_NODE_STYLE.labelOffsetY,
  );
  const [labelFontPerDiameter, setLabelFontPerDiameter] = useState(
    DEFAULT_NODE_STYLE.labelFontPerDiameter,
  );
  const [labelFontWeight, setLabelFontWeight] = useState(
    DEFAULT_NODE_STYLE.labelFontWeight,
  );
  const [labelAppearPx, setLabelAppearPx] = useState(
    DEFAULT_NODE_STYLE.labelAppearPx,
  );
  const [nodeLineWidth, setNodeLineWidth] = useState(
    DEFAULT_NODE_STYLE.lineWidth,
  );
  const [settle, setSettle] = useState<SettleTuning>(DEFAULT_SETTLE);
  const [layoutId, setLayoutId] = useState<LayoutId>("radial");
  const [hulls, setHulls] = useState(false);
  const hullsRef = useRef(false);
  const [layoutTunings, setLayoutTunings] = useState<LayoutTunings>(
    DEFAULT_LAYOUT_TUNINGS,
  );
  const [switching, setSwitching] = useState(false);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState("Building coarsening…");
  const [level, setLevel] = useState(0);
  const [magnify, setMagnify] = useState(1);
  const [maxMagnify, setMaxMagnify] = useState(1);
  const [biggest, setBiggest] = useState<{ id: string; mass: number } | null>(
    null,
  );
  const [perfHud, setPerfHud] = useState({
    fps: 0,
    drawMs: 0,
    dialMs: 0,
    draws: 0,
  });

  // The canvas is data-source agnostic: a real committed graph arrives in the
  // same shape as the fixture, so mass/LOD, hulls, the lens and the hover bond
  // all apply to it unchanged. Fixture is the fallback so the lab still runs
  // with no server.
  const liveGraph = useAmbientLiveGraph();
  const baseData = useMemo(() => {
    const source = liveGraph.data;
    if (source) {
      return hulls ? createAmbientContainsComboGraph(source) : source;
    }
    return hulls ? createAmbientContainsComboGraph() : createAmbientLodGraph();
  }, [hulls, liveGraph.data]);
  const seam = useMemo(
    () => applyAmbientSeamMode(baseData, seamMode),
    [baseData, seamMode],
  );
  const data = seam.data;
  lodRef.current = lod;
  lodEnabledRef.current = lodEnabled;
  layoutTuningsRef.current = layoutTunings;
  hullsRef.current = hulls;
  focusLive.inverted = seam.inverted;
  applyFocusPalette();

  useEffect(() => {
    lodLive.unitDiameter = lod.unitDiameter;
    lodLive.landmarkBoost = lod.landmarkBoost;
  }, [lod.unitDiameter, lod.landmarkBoost]);

  useEffect(() => {
    Object.assign(settleLive, settle);
  }, [settle]);

  useEffect(() => {
    styleLive.fontId = fontId;
    styleLive.labelOffsetY = labelOffsetY;
    styleLive.labelFontPerDiameter = labelFontPerDiameter;
    styleLive.labelFontWeight = labelFontWeight;
    styleLive.labelAppearPx = labelAppearPx;
    styleLive.lineWidth = nodeLineWidth;
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !ready) return;
    graph.setNode({
      type: "circle",
      style: buildNodeStyle(),
      state: buildNodeState(),
    });
    void graph.draw().catch(() => {});
  }, [
    fontId,
    labelOffsetY,
    labelFontPerDiameter,
    labelFontWeight,
    labelAppearPx,
    nodeLineWidth,
    ready,
  ]);

  useEffect(() => {
    applyThemePalette(themeMode);
    applyFocusPalette();
    focusLive.inverted = seam.inverted;
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !ready) return;
    graph.setNode({
      type: "circle",
      style: buildNodeStyle(),
      state: buildNodeState(),
    });
    graph.setEdge({
      type: AMBIENT_LINKAGE_EDGE,
      style: buildEdgeStyle() as never,
      state: buildEdgeState() as never,
      animation: false,
    });
    if (hulls) {
      graph.setCombo({
        type: "circle",
        style: buildComboStyle() as never,
      });
    }
    void graph.draw().catch(() => {});
  }, [themeMode, ready, hulls, seam.inverted]);

  const setLodField = <K extends keyof LodParams>(key: K, value: LodParams[K]) => {
    setLod((prev) => ({ ...prev, [key]: value }));
  };

  const resetNodeTuning = () => {
    setFontId(DEFAULT_NODE_STYLE.fontId);
    setLabelOffsetY(DEFAULT_NODE_STYLE.labelOffsetY);
    setLabelFontPerDiameter(DEFAULT_NODE_STYLE.labelFontPerDiameter);
    setLabelFontWeight(DEFAULT_NODE_STYLE.labelFontWeight);
    setLabelAppearPx(DEFAULT_NODE_STYLE.labelAppearPx);
    setNodeLineWidth(DEFAULT_NODE_STYLE.lineWidth);
    setLod((prev) => ({
      ...prev,
      unitDiameter: DEFAULT_LOD_PARAMS.unitDiameter,
      landmarkBoost: DEFAULT_LOD_PARAMS.landmarkBoost,
      nodeFill: DEFAULT_LOD_PARAMS.nodeFill,
    }));
  };

  const model = useMemo(() => {
    const ids = (data.nodes ?? []).map((n) => String(n.id));
    const edges = (data.edges ?? []).map((e) => ({
      source: String(e.source),
      target: String(e.target),
    }));
    return buildCoarsenModel(
      ids,
      edges,
      liveGraph.map
        ? `gv_live_${liveGraph.map.graph_id}_${liveGraph.map.graph_version}`
        : `gv_fixture_${AMBIENT_LOD_GRAPH_VERSION}`,
      "degree",
    );
  }, [data, liveGraph.map]);

  const layoutNote =
    seamMode !== "idle"
      ? (AMBIENT_SEAM_MODES.find((m) => m.id === seamMode)?.note ?? seam.label)
      : hulls
        ? HULLS_BLOCKED_LAYOUTS.has(layoutId)
          ? "Hulls on — Nested/Spine paused."
          : `${LAYOUTS.find((l) => l.id === layoutId)?.note ?? ""}`
        : (LAYOUTS.find((l) => l.id === layoutId)?.note ?? LAYOUTS[0]!.note);

  useEffect(() => {
    if (!containerRef.current) return;
    ensureLinkageEdgeRegistered();
    ensureAmbientLinkageEdgeRegistered();
    ensureStructuralDagreRegistered();
    let cancelled = false;
    let self: Graph | null = null;
    setReady(false);
    setNote("Building graph…");

    const perf = {
      frames: 0,
      fpsWindowStart: performance.now(),
      fps: 0,
      drawMs: 0,
      dialMs: 0,
      draws: 0,
    };
    let perfHudRaf = 0;
    let perfSampleRaf = 0;
    const publishPerfHud = () => {
      perfHudRaf = 0;
      if (cancelled) return;
      setPerfHud({
        fps: perf.fps,
        drawMs: perf.drawMs,
        dialMs: perf.dialMs,
        draws: perf.draws,
      });
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

    const timedDraw = async (graph: Graph) => {
      const t0 = performance.now();
      await graph.draw().catch(() => {});
      perf.drawMs = Math.round((performance.now() - t0) * 10) / 10;
      perf.draws += 1;
      publishPerfHud();
    };

    let dial = 0;
    let fitZoom = 1;
    /** Dial = 1 camera — unit-Ø disc fills `nodeFill` of the stage. */
    let nodeZoom = 8;
    let currentLevel = -1;

    /** Overview → single-node span from actual fit + node scale (not a fixed ×). */
    const cameraSpan = () =>
      Math.max(1.05, nodeZoom / Math.max(1e-6, fitZoom));

    const zoomForDial = (t: number) => {
      const u = Math.max(0, Math.min(1, t));
      return fitZoom * Math.pow(cameraSpan(), u);
    };

    const refreshZoomBudget = (graph: Graph, overviewZoom: number) => {
      fitZoom = Math.max(1e-4, overviewZoom);
      nodeZoom = zoomForNodeFill(
        graph,
        lodLive.unitDiameter,
        lodRef.current.nodeFill,
      );
      // Always allow zooming past overview onto a unit disc.
      if (nodeZoom < fitZoom * 1.2) {
        nodeZoom = fitZoom * 1.2;
      }
      setMaxMagnify(nodeZoom / fitZoom);
      try {
        graph.setOptions({
          zoomRange: [
            Math.min(0.02, fitZoom * 0.45),
            Math.max(nodeZoom * 1.15, 8),
          ],
        });
      } catch {
        /* ok */
      }
    };

    const levelTop = () => {
      const { foldWindow } = lodRef.current;
      return (model.nodeCount + 1) / (1 - foldWindow);
    };

    const levelForDial = (t: number) => {
      const { minLevel } = lodRef.current;
      const top = levelTop();
      const span = cameraSpan();
      // level ∝ zoom² — same span as the camera, so abstraction tracks magnification.
      return Math.max(
        minLevel,
        Math.min(top, top * Math.pow(span, 2 * (t - 1))),
      );
    };

    /** Full graph — every node present at unit mass (no coarsening). */
    const disclosureLevel = (t: number) =>
      lodEnabledRef.current ? levelForDial(t) : levelTop();

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

    const sentNode = new Map<string, [number, number]>();
    const sentEdge = new Map<string, number>();
    const EPS = 0.004;
    const publishLevel = (graph: Graph, force = false) => {
      const nodeRows: { id: string; data: Record<string, number> }[] = [];
      for (const node of graph.getNodeData()) {
        const id = String(node.id);
        if (id === HULL_PREVIEW_ID) continue;
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
        nodeRows.push({ id, data: { _m: m, _p: p } });
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

    let dialSettleTimer = 0;

    const applyLod = async (force = false) => {
      const graph = self;
      if (cancelled || !graph || graph.destroyed) return;

      const exact = disclosureLevel(dial);
      if (!(Math.abs(exact - currentLevel) > 0.001 || force)) return;

      const tDial = performance.now();
      currentLevel = exact;
      const state = resolveAt(exact);
      applyState(model, state, exact);
      pushStats(state);
      publishLevel(graph);
      refreshCull(graph);
      await timedDraw(graph);
      perf.dialMs = Math.round((performance.now() - tDial) * 10) / 10;
      publishPerfHud();
    };

    const applyDial = async (force = false, origin?: [number, number]) => {
      const graph = self;
      if (cancelled || !graph || graph.destroyed) return;

      // Recompute node-level max when unit Ø / fill knobs change.
      if (force) {
        refreshZoomBudget(graph, fitZoom);
      }

      const wanted = zoomForDial(dial);
      setMagnify(wanted / fitZoom);
      view.zoom = wanted;

      if (Math.abs(graph.getZoom() - wanted) > 0.002) {
        await graph.zoomTo(wanted, false, origin).catch(() => {});
      }
      refreshCull(graph);

      if (force) {
        if (dialSettleTimer) {
          window.clearTimeout(dialSettleTimer);
          dialSettleTimer = 0;
        }
        await applyLod(true);
        return;
      }

      if (dialSettleTimer) window.clearTimeout(dialSettleTimer);
      dialSettleTimer = window.setTimeout(() => {
        dialSettleTimer = 0;
        if (cancelled) return;
        void applyLod(false);
      }, lodRef.current.dialSettleMs);
    };
    applyDialRef.current = applyDial;

    applyState(model, resolveAt(disclosureLevel(0)), disclosureLevel(0));

    const graph = new Graph({
      container: containerRef.current,
      data,
      animation: false,
      padding: [48, 44, 48, 44],
      // Hard ceiling — live budget is fitZoom→nodeZoom from unit Ø + nodeFill.
      zoomRange: [0.02, 64],
      devicePixelRatio: 2,
      node: {
        type: "circle",
        style: buildNodeStyle(),
        state: buildNodeState(),
      },
      edge: {
        type: AMBIENT_LINKAGE_EDGE,
        style: buildEdgeStyle() as never,
        state: buildEdgeState() as never,
        animation: false,
      },
      ...(hulls
        ? {
            combo: {
              type: "circle",
              style: buildComboStyle() as never,
              state: {
                selected: { halo: false, haloStrokeOpacity: 0 },
                active: { halo: false, haloStrokeOpacity: 0 },
              },
            },
          }
        : {}),
      behaviors: [
        "drag-canvas",
        // Free node/combo drag after layout freeze — no live force.
        // No click-select: selection halos/strokes are off entirely.
        "drag-element",
        // Hull collapse/expand is right-click (see combo:contextmenu below) —
        // G6's collapse-expand only supports click/dblclick.
      ],
    });

    self = graph;
    graphRef.current = graph;
    graphLive = graph;
    (window as Window & { __ambientCanvasLive?: typeof view }).__ambientCanvasLive =
      view;
    (
      window as Window & { __ambientCanvasGraph?: Graph | null }
    ).__ambientCanvasGraph = graph;

    const onComboContextMenu = (event: IElementEvent) => {
      event.preventDefault?.();
      const native = (event as { originalEvent?: Event; nativeEvent?: Event })
        .originalEvent ?? (event as { nativeEvent?: Event }).nativeEvent;
      native?.preventDefault?.();
      if (!hullsRef.current || graph.destroyed) return;
      const id = String(event.target?.id ?? "");
      if (!id) return;
      const datum = graph.getComboData(id);
      if (!datum) return;
      const closed = Boolean(datum.style?.collapsed);
      void (async () => {
        previewComboId = null;
        await clearHullExpandPreview(graph);
        if (closed) {
          // Bake any pending drag offset before expand so members land right.
          syncCollapsedComboMembers(graph, id);
          await graph.expandElement(id, { animation: true }).catch(() => {});
          syncHullLabelPlacement(graph, id, false);
          setNote(`Expanded “${id}” — members and edges restored.`);
        } else {
          await graph.collapseElement(id, { animation: true }).catch(() => {});
          syncHullLabelPlacement(graph, id, true);
          setNote(`Collapsed “${id}” — crossing edges retarget onto the hull.`);
        }
        // Re-evaluate edge visibility (hide internal→self-loop filaments).
        await graph.draw().catch(() => {});
        if (!closed) {
          previewComboId = id;
          void showHullExpandPreview(graph, id);
        }
      })();
    };

    let previewComboId: string | null = null;
    let previewRaf = 0;
    let draggingCombo = false;
    const onComboPreviewEnter = (event: IElementEvent) => {
      if (!hullsRef.current || graph.destroyed) return;
      const id = String(event.target?.id ?? "");
      if (!id) return;
      const datum = graph.getComboData(id);
      if (!datum?.style?.collapsed) return;
      previewComboId = id;
      void showHullExpandPreview(graph, id);
    };
    const onComboPreviewLeave = () => {
      // Keep the footprint while dragging — only clear on true hover-out.
      if (graph.destroyed || draggingCombo) return;
      previewComboId = null;
      void clearHullExpandPreview(graph);
    };
    const onComboDragStart = (event: IElementEvent) => {
      if (!hullsRef.current || graph.destroyed) return;
      const id = String(event.target?.id ?? "");
      if (!id) return;
      const datum = graph.getComboData(id);
      if (!datum?.style?.collapsed) return;
      draggingCombo = true;
      previewComboId = id;
      // Keep / show footprint for the whole drag (follows via combo:drag).
      void showHullExpandPreview(graph, id);
    };
    const onComboDrag = (event: IElementEvent) => {
      if (!hullsRef.current || graph.destroyed || !draggingCombo) return;
      const id = String(event.target?.id ?? "");
      if (!id || previewComboId !== id) return;
      if (previewRaf) return;
      previewRaf = requestAnimationFrame(() => {
        previewRaf = 0;
        if (!draggingCombo || previewComboId !== id || graph.destroyed) return;
        void showHullExpandPreview(graph, id);
      });
    };
    const onComboDragEnd = (event: IElementEvent) => {
      if (!hullsRef.current || graph.destroyed) return;
      const id = String(event.target?.id ?? "");
      draggingCombo = false;
      if (!id) return;
      const datum = graph.getComboData(id);
      if (!datum?.style?.collapsed) return;
      syncCollapsedComboMembers(graph, id);
      if (previewComboId === id) void showHullExpandPreview(graph, id);
      else previewComboId = null;
    };

    if (hulls) {
      graph.on("combo:contextmenu", onComboContextMenu);
      graph.on("combo:pointerenter", onComboPreviewEnter);
      graph.on("combo:pointerleave", onComboPreviewLeave);
      graph.on("combo:dragstart", onComboDragStart);
      graph.on("combo:drag", onComboDrag);
      graph.on("combo:dragend", onComboDragEnd);
    }

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

    let hoverActive = emptyHoverBundle();
    let hoverRaf = 0;
    let hoverPending: HoverBundle | null = null;
    let hoverLeaveTimer = 0;

    const clearHoverState = (id: string, state: string) =>
      graph.getElementState(id).filter((s) => s !== state);

    const syncNamedState = (
      states: Record<string, string[]>,
      prev: Set<string>,
      next: Set<string>,
      state: string,
      cleanAlso?: string[],
    ) => {
      for (const id of prev) {
        if (next.has(id)) continue;
        states[id] = clearHoverState(id, state);
      }
      for (const id of next) {
        const cur = states[id] ?? graph.getElementState(id);
        let cleaned = cur.filter((s) => s !== state);
        if (cleanAlso) {
          cleaned = cleaned.filter((s) => !cleanAlso.includes(s));
        }
        states[id] = cleaned.includes(state) ? cleaned : [...cleaned, state];
      }
    };

    const commitHover = async (next: HoverBundle) => {
      if (graph.destroyed) return;
      const states: Record<string, string[]> = {};
      syncNamedState(states, hoverActive.out, next.out, "out", ["inn"]);
      syncNamedState(states, hoverActive.inn, next.inn, "inn", ["out"]);
      hoverActive = next;
      await graph.setElementState(states, false).catch(() => {});
    };

    const scheduleHover = (next: HoverBundle) => {
      hoverPending = next;
      if (hoverRaf) return;
      hoverRaf = requestAnimationFrame(() => {
        hoverRaf = 0;
        const bundle = hoverPending ?? emptyHoverBundle();
        hoverPending = null;
        void commitHover(bundle);
      });
    };

    const onHoverEnter = (event: IElementEvent) => {
      if (graph.destroyed) return;
      if (hoverLeaveTimer) {
        window.clearTimeout(hoverLeaveTimer);
        hoverLeaveTimer = 0;
      }
      const id = String(event.target.id);
      const node = graph.getNodeData(id);
      // Focus seeds already expose typed edges — hover bond is a no-op.
      if (node && focusLive.inverted && isFocusLit(node)) {
        scheduleHover(emptyHoverBundle());
        return;
      }
      scheduleHover(hoverBundleFor(graph, id));
    };

    const onHoverLeave = () => {
      if (graph.destroyed) return;
      if (hoverLeaveTimer) window.clearTimeout(hoverLeaveTimer);
      hoverLeaveTimer = window.setTimeout(() => {
        hoverLeaveTimer = 0;
        scheduleHover(emptyHoverBundle());
      }, 60);
    };

    graph.on("node:pointerenter", onHoverEnter);
    graph.on("node:pointerleave", onHoverLeave);

    let cullRaf = 0;
    const onAfterTransform = () => {
      if (cullRaf) return;
      cullRaf = requestAnimationFrame(() => {
        cullRaf = 0;
        if (cancelled || graph.destroyed) return;
        refreshCull(graph);
        view.zoom = Math.max(0.05, graph.getZoom() || 1);
      });
    };
    graph.on("aftertransform", onAfterTransform);

    const runLayout = async (id: LayoutId) => {
      const graphNow = self;
      if (!graphNow || graphNow.destroyed || cancelled) return;
      const myGen = ++layoutGenRef.current;
      setSwitching(true);
      setNote(
        id === "glide" || id === "cluster"
          ? `Settling ${id}…`
          : `Laying out · ${id}…`,
      );

      await stopLayoutQuiet(graphNow);
      if (cancelled || graphNow.destroyed || layoutGenRef.current !== myGen) {
        return;
      }

      // Deterministic scatter so this chip doesn't inherit the previous lens.
      setNote(`Seeding · ${id}…`);
      await resetPositionsForLayout(graphNow, id);
      if (cancelled || graphNow.destroyed || layoutGenRef.current !== myGen) {
        return;
      }

      // Size discs for the current dial *before* collide, so overlap push
      // matches what will actually paint (mass LOD or full detail).
      currentLevel = -1;
      const exact = disclosureLevel(dial);
      const state = resolveAt(exact);
      applyState(model, state, exact);
      pushStats(state);
      publishLevel(graphNow, true);
      await timedDraw(graphNow);
      if (cancelled || graphNow.destroyed || layoutGenRef.current !== myGen) {
        return;
      }

      const tunings = layoutTuningsRef.current;
      const useHulls = hullsRef.current;
      if (useHulls && !HULLS_BLOCKED_LAYOUTS.has(id)) {
        // Each chip → real combo-combined inner/outer (see hullsCombinedLayout).
        setNote(`Hulls · ${id} (combo-combined)…`);
        graphNow.setLayout(hullsCombinedLayout(id, tunings));
        await graphNow.layout().catch(() => {});
        await stopLayoutQuiet(graphNow);
      } else if (id === "glide") {
        await runSoftPhase(graphNow, glideSettleLayout(tunings), {
          cancelled,
          gen: myGen,
          layoutGen: layoutGenRef,
        });
      } else if (id === "cluster") {
        await runSoftPhase(graphNow, clusterSettleLayout(tunings), {
          cancelled,
          gen: myGen,
          layoutGen: layoutGenRef,
        });
      } else if (id === "spine") {
        setNote("Spine · LEADSTO…");
        graphNow.setLayout(spineDagreLayout(tunings));
        await graphNow.layout().catch(() => {});
        await stopLayoutQuiet(graphNow);
        if (cancelled || graphNow.destroyed || layoutGenRef.current !== myGen) {
          return;
        }
        setNote("Spine · attach CONTAINS…");
        await attachContainsBesideParents(graphNow, tunings.spine);
      } else {
        graphNow.setLayout(structuralLayout(id, tunings));
        await graphNow.layout().catch(() => {});
        await stopLayoutQuiet(graphNow);
      }
      if (cancelled || graphNow.destroyed || layoutGenRef.current !== myGen) {
        return;
      }

      // Soft collide after dagre/radial/force — but not after combo-combined.
      // Collide ticks reflow hull bounds every frame and add lag for little
      // gain (combo-combined already pads regions).
      if (!useHulls) {
        setNote("Soft collide…");
        const anchors = new Map<string, { x: number; y: number }>();
        captureAnchors(graphNow, anchors);
        if (anchors.size > 0) {
          await runSoftPhase(graphNow, shapedSettleLayout(anchors), {
            cancelled,
            gen: myGen,
            layoutGen: layoutGenRef,
          });
          if (cancelled || graphNow.destroyed || layoutGenRef.current !== myGen) {
            return;
          }
        }
      }

      publishLevel(graphNow, true);
      await timedDraw(graphNow);

      fitZoom = await frameVisible(graphNow);
      refreshZoomBudget(graphNow, fitZoom);
      view.zoom = fitZoom;
      refreshCull(graphNow);
      dial = Math.min(1, Math.max(0, dial));
      await applyDial(true);

      if (cancelled || layoutGenRef.current !== myGen) return;
      setNote("");
      setSwitching(false);
      setReady(true);
    };
    applyLayoutRef.current = runLayout;

    graph
      .render()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        await runLayout(layoutId);
        if (cancelled || graph.destroyed) return;
        void document.fonts?.ready.then(() => {
          if (cancelled || graph.destroyed) return;
          clearLabelMeasureCache();
          void applyDial(true);
        });
      })
      .catch((err) => {
        if (cancelled || graph.destroyed) return;
        console.error("[ambient-canvas] init failed", err);
        setNote("Init failed — see console");
        setSwitching(false);
      });

    return () => {
      cancelled = true;
      if (perfSampleRaf) cancelAnimationFrame(perfSampleRaf);
      if (perfHudRaf) cancelAnimationFrame(perfHudRaf);
      if (dialSettleTimer) window.clearTimeout(dialSettleTimer);
      if (hoverLeaveTimer) window.clearTimeout(hoverLeaveTimer);
      if (hoverRaf) cancelAnimationFrame(hoverRaf);
      if (cullRaf) cancelAnimationFrame(cullRaf);
      self = null;
      if (graphLive === graph) graphLive = null;
      container.removeEventListener("wheel", onWheel);
      graph.off("node:pointerenter", onHoverEnter);
      graph.off("node:pointerleave", onHoverLeave);
      graph.off("aftertransform", onAfterTransform);
      graph.off("combo:contextmenu", onComboContextMenu);
      graph.off("combo:pointerenter", onComboPreviewEnter);
      graph.off("combo:pointerleave", onComboPreviewLeave);
      graph.off("combo:dragstart", onComboDragStart);
      graph.off("combo:drag", onComboDrag);
      graph.off("combo:dragend", onComboDragEnd);
      if (previewRaf) cancelAnimationFrame(previewRaf);
      void stopLayoutQuiet(graph);
      if (graphRef.current === graph) graphRef.current = null;
      const w = window as Window & { __ambientCanvasGraph?: Graph | null };
      if (w.__ambientCanvasGraph === graph) w.__ambientCanvasGraph = null;
      graph.destroy();
    };
    // layoutId is applied after render via runLayout(layoutId); size / hulls remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, model, lod.unitDiameter, lod.landmarkBoost, hulls]);

  useEffect(() => {
    if (!ready) return;
    void applyDialRef.current(true);
  }, [
    ready,
    lodEnabled,
    lod.minLevel,
    lod.nodeFill,
    lod.foldWindow,
    lod.dialSettleMs,
  ]);

  // Cursor lens — kind chips on the stroke at the closest point to the pointer.
  useEffect(() => {
    const graph = graphRef.current;
    const el = containerRef.current;
    if (!ready || !graph || graph.destroyed || !el) return;

    let prevLens = new Map<string, number>();
    let prevLp = new Map<string, number>();
    let drawing = false;
    let pending: { x: number; y: number } | null = null;
    let raf = 0;

    const commitLens = (
      next: Map<string, number>,
      nextLp: Map<string, number>,
    ) => {
      if (graph.destroyed) return false;
      const updates: { id: string; data: Record<string, unknown> }[] = [];
      const seen = new Set<string>();
      for (const [id, lens] of next) {
        seen.add(id);
        const lp = nextLp.get(id) ?? 0.5;
        const lensChanged = Math.abs((prevLens.get(id) ?? 0) - lens) >= 0.004;
        const lpChanged = Math.abs((prevLp.get(id) ?? 0.5) - lp) >= 0.008;
        if (!lensChanged && !lpChanged) continue;
        const edge = graph.getEdgeData(id);
        if (!edge) continue;
        updates.push({
          id,
          data: { ...edge.data, lens, _lp: lp, _lox: 0, _loy: 0 },
        });
      }
      for (const id of prevLens.keys()) {
        if (seen.has(id)) continue;
        const edge = graph.getEdgeData(id);
        if (!edge) continue;
        updates.push({
          id,
          data: {
            ...edge.data,
            lens: 0,
            _lp: 0.5,
            _lox: 0,
            _loy: 0,
          },
        });
      }
      prevLens = next;
      prevLp = nextLp;
      if (!updates.length) return false;
      graph.updateEdgeData(updates);
      return true;
    };

    const paint = async () => {
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
      const lensCull = expandCull(view.cull, radius);
      const next = new Map<string, number>();
      const nextLp = new Map<string, number>();

      for (const edge of graph.getEdgeData()) {
        if (isCollapsedHullLoopEdge(edge)) continue;
        if (Number(edge.data?._ep ?? 0) <= 0.02) continue;
        // Focus-lit edges already show mid-stroke SST; lens chips must not
        // slide onto (or fight) default labels on highlighted nodes.
        if (focusLive.inverted && isFocusLit(edge)) continue;
        const id = String(edge.id);
        try {
          const s = graph.getElementPosition(String(edge.source));
          const t = graph.getElementPosition(String(edge.target));
          if (!edgeMayHitCull(s[0], s[1], t[0], t[1], lensCull)) continue;
          const dist = distPointToSegment(cx, cy, s[0], s[1], t[0], t[1]);
          const strength = lensFalloff(dist, radius);
          if (strength <= 0.008) continue;

          next.set(id, strength);
          // Stay on the filament — closest point to the cursor, no pull off-edge.
          nextLp.set(id, closestTOnSegment(cx, cy, s[0], s[1], t[0], t[1]));
        } catch {
          /* skip */
        }
      }

      const wrote = commitLens(next, nextLp);
      if (wrote) {
        drawing = true;
        await paint();
        drawing = false;
      }
      if (pending && !raf) {
        raf = requestAnimationFrame(() => void runFrame());
      }
    };

    const clearLens = async () => {
      if (graph.destroyed) return;
      pending = null;
      if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
      if (commitLens(new Map(), new Map())) {
        await paint();
      }
    };

    const onMove = (event: PointerEvent) => {
      // Skip lens work while dragging the canvas — otherwise every pan frame
      // also does updateEdgeData + draw on top of combo repaints.
      if (event.buttons !== 0) {
        pending = null;
        return;
      }
      pending = { x: event.clientX, y: event.clientY };
      if (drawing || raf) return;
      raf = requestAnimationFrame(() => void runFrame());
    };
    const onLeave = () => void clearLens();
    const onUp = (event: PointerEvent) => {
      if (event.buttons !== 0) return;
      pending = { x: event.clientX, y: event.clientY };
      if (drawing || raf) return;
      raf = requestAnimationFrame(() => void runFrame());
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("pointercancel", onLeave);
    el.addEventListener("pointerup", onUp);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("pointercancel", onLeave);
      el.removeEventListener("pointerup", onUp);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [ready]);

  const pickLayout = (id: LayoutId) => {
    if (hulls && HULLS_BLOCKED_LAYOUTS.has(id)) return;
    setLayoutId(id);
    if (!ready) return;
    void applyLayoutRef.current(id);
  };

  const setHullsMode = (next: boolean) => {
    if (next === hulls) return;
    if (next && HULLS_BLOCKED_LAYOUTS.has(layoutId)) {
      setLayoutId("radial");
    }
    setHulls(next);
  };

  const collapseAllHulls = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !hulls) return;
    for (const combo of graph.getComboData()) {
      await graph.collapseElement(combo.id, { animation: true }).catch(() => {});
      syncHullLabelPlacement(graph, String(combo.id), true);
    }
    await graph.draw().catch(() => {});
    setNote("All region hulls collapsed.");
  };

  const expandAllHulls = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !hulls) return;
    for (const combo of graph.getComboData()) {
      await graph.expandElement(combo.id, { animation: true }).catch(() => {});
      syncHullLabelPlacement(graph, String(combo.id), false);
    }
    await graph.draw().catch(() => {});
    setNote("All region hulls expanded.");
  };

  const retuneLayout = (next: LayoutTunings) => {
    layoutTuningsRef.current = next;
    setLayoutTunings(next);
    if (!ready || switching) return;
    void applyLayoutRef.current(layoutId);
  };

  const retuneSettle = (next: SettleTuning) => {
    setSettle(next);
    Object.assign(settleLive, next);
    if (!ready || switching) return;
    void applyLayoutRef.current(layoutId);
  };

  return (
    <main
      className={
        themeMode === "dark" ? "ambient-canvas is-dark" : "ambient-canvas"
      }
    >
      <header className="ambient-canvas__header">
        <div>
          <p className="ambient-canvas__eyebrow">Screen 1 · Ambient Canvas</p>
          <h1>Ambient canvas</h1>
          <p className="ambient-canvas__lede">
            Layout settles with collide then freezes. Hulls turn leaf-region
            CONTAINS into outline combos — right-click to collapse/expand
            (Nested/Spine pause). Focus / proposal / diff always use a charcoal
            spotlight (Radix grayDark) — independent of Light/Dark idle theme.
            LOD as-is.
          </p>
          <p className="ambient-canvas__nav">
            <a href="#/explorations">Explorations</a>
            {" · "}
            <a href="#/explorations/ledger-feed">Ledger feed</a>
            {" · "}
            <a href="#/explorations/canvas-linkage">Canvas linkage</a>
            {" · "}
            <a href="#/construct?api=live">Construct</a>
          </p>
        </div>
        <aside className="ambient-canvas__note">
          <span>Structure</span>
          <strong>
            {model.nodeCount} nodes
            {hulls ? ` · ${data.combos?.length ?? 0} hulls` : ""}
            {" · "}
            {layoutId}
            {hulls ? " · hulls" : ""}
            {" · collide then freeze"}
          </strong>
          <p>{layoutNote}</p>
        </aside>
      </header>

      <div className="ambient-canvas__toolbar">
        <p className="ambient-canvas__status" role="status">
          {ready ? (
            <>
              {lodEnabled ? "LOD on" : "LOD off"}
              {" · "}
              showing <strong>{level}</strong>/{model.nodeCount}
              {" · "}
              zoom {magnify.toFixed(2)}× of overview
              {" · "}
              max {maxMagnify.toFixed(1)}× (unit Ø fill)
              {lodEnabled && biggest ? (
                <>
                  {" · "}
                  largest <strong>{biggest.id}</strong> stands for {biggest.mass}
                </>
              ) : null}
              {" · "}
              <span className="ambient-canvas__perf">
                {perfHud.fps < 0 ? "—fps" : `${perfHud.fps}fps`}
                {" · "}
                draw {perfHud.drawMs.toFixed(1)}ms
                {" · "}
                dial {perfHud.dialMs.toFixed(1)}ms
              </span>
            </>
          ) : (
            note || "Loading…"
          )}
        </p>
      </div>

      <div className="ambient-canvas__lod" aria-label="Nodes">
        <div className="ambient-canvas__lod-head">
          <span>Nodes</span>
          <button type="button" onClick={resetNodeTuning}>
            Reset
          </button>
        </div>
        <div
          className="ambient-canvas__layout-chips"
          role="group"
          aria-label="Theme"
        >
          <button
            type="button"
            className={themeMode === "light" ? "is-active" : undefined}
            onClick={() => setThemeMode("light")}
          >
            Light
          </button>
          <button
            type="button"
            className={themeMode === "dark" ? "is-active" : undefined}
            onClick={() => setThemeMode("dark")}
          >
            Dark
          </button>
        </div>
        <div
          className="ambient-canvas__layout-chips"
          role="group"
          aria-label="Focus seams"
        >
          {AMBIENT_SEAM_MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={seamMode === m.id ? "is-active" : undefined}
              title={m.note}
              onClick={() => setSeamMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div
          className="ambient-canvas__layout-chips"
          role="group"
          aria-label="Node label font"
        >
          {CIRCLE_NODE_FONT_IDS.map((id) => (
            <button
              key={id}
              type="button"
              className={fontId === id ? "is-active" : undefined}
              style={{ fontFamily: NODE_FONTS[id].family }}
              title={NODE_FONTS[id].note}
              onClick={() => setFontId(id)}
            >
              {NODE_FONTS[id].label}
            </button>
          ))}
        </div>
        <div className="ambient-canvas__lod-grid">
          <label className="ambient-canvas__lod-field">
            <span>
              Unit Ø
              <strong>{lod.unitDiameter}</strong>
            </span>
            <input
              type="range"
              min={24}
              max={140}
              step={1}
              value={lod.unitDiameter}
              onChange={(e) =>
                setLodField("unitDiameter", Number(e.target.value))
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Landmark ×
              <strong>{lod.landmarkBoost.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.8}
              max={2.2}
              step={0.05}
              value={lod.landmarkBoost}
              onChange={(e) =>
                setLodField("landmarkBoost", Number(e.target.value))
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Label / Ø
              <strong>{labelFontPerDiameter.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.06}
              max={0.36}
              step={0.01}
              value={labelFontPerDiameter}
              onChange={(e) =>
                setLabelFontPerDiameter(Number(e.target.value))
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Weight
              <strong>{labelFontWeight}</strong>
            </span>
            <input
              type="range"
              min={200}
              max={700}
              step={100}
              value={labelFontWeight}
              onChange={(e) => setLabelFontWeight(Number(e.target.value))}
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Label Y
              <strong>{labelOffsetY}</strong>
            </span>
            <input
              type="range"
              min={-16}
              max={16}
              step={1}
              value={labelOffsetY}
              onChange={(e) => setLabelOffsetY(Number(e.target.value))}
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Label appear
              <strong>{labelAppearPx}px</strong>
            </span>
            <input
              type="range"
              min={4}
              max={36}
              step={1}
              value={labelAppearPx}
              onChange={(e) => setLabelAppearPx(Number(e.target.value))}
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Stroke
              <strong>{nodeLineWidth.toFixed(1)}</strong>
            </span>
            <input
              type="range"
              min={0}
              max={4}
              step={0.25}
              value={nodeLineWidth}
              onChange={(e) => setNodeLineWidth(Number(e.target.value))}
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Node fill
              <strong>{lod.nodeFill.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.35}
              max={0.98}
              step={0.01}
              value={lod.nodeFill}
              onChange={(e) => setLodField("nodeFill", Number(e.target.value))}
            />
          </label>
        </div>
      </div>

      <div className="ambient-canvas__lod" aria-label="Layout">
        <div className="ambient-canvas__lod-head">
          <span>Layout</span>
          <button
            type="button"
            onClick={() => {
              setLayoutTunings(DEFAULT_LAYOUT_TUNINGS);
              setSettle(DEFAULT_SETTLE);
              layoutTuningsRef.current = DEFAULT_LAYOUT_TUNINGS;
              Object.assign(settleLive, DEFAULT_SETTLE);
              if (ready) void applyLayoutRef.current(layoutId);
            }}
          >
            Reset
          </button>
        </div>
        <div
          className="ambient-canvas__layout-chips"
          role="group"
          aria-label="CONTAINS hulls"
        >
          <button
            type="button"
            className={!hulls ? "is-active" : undefined}
            onClick={() => setHullsMode(false)}
          >
            Edges
          </button>
          <button
            type="button"
            className={hulls ? "is-active" : undefined}
            onClick={() => setHullsMode(true)}
          >
            Hulls
          </button>
          {hulls ? (
            <>
              <button
                type="button"
                disabled={!ready || switching}
                onClick={() => void collapseAllHulls()}
              >
                Collapse all
              </button>
              <button
                type="button"
                disabled={!ready || switching}
                onClick={() => void expandAllHulls()}
              >
                Expand all
              </button>
            </>
          ) : null}
        </div>
        <div className="ambient-canvas__layout-chips" role="group" aria-label="Layout lens">
          {LAYOUTS.map((l) => {
            const blocked = hulls && HULLS_BLOCKED_LAYOUTS.has(l.id);
            return (
            <button
              key={l.id}
              type="button"
              className={layoutId === l.id ? "is-active" : undefined}
              disabled={switching || blocked}
              title={blocked ? "Needs CONTAINS edges — turn Hulls off" : undefined}
              onClick={() => pickLayout(l.id)}
            >
              {l.label}
            </button>
            );
          })}
        </div>
        <div className="ambient-canvas__lod-grid">
          {layoutId === "nested" || layoutId === "cascade" ? (
            <>
              <label className="ambient-canvas__lod-field">
                <span>
                  Node sep
                  <strong>{layoutTunings[layoutId].nodesep}</strong>
                </span>
                <input
                  type="range"
                  min={32}
                  max={140}
                  step={2}
                  value={layoutTunings[layoutId].nodesep}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      [layoutId]: {
                        ...layoutTunings[layoutId],
                        nodesep: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Rank sep
                  <strong>{layoutTunings[layoutId].ranksep}</strong>
                </span>
                <input
                  type="range"
                  min={56}
                  max={180}
                  step={2}
                  value={layoutTunings[layoutId].ranksep}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      [layoutId]: {
                        ...layoutTunings[layoutId],
                        ranksep: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </>
          ) : null}
          {layoutId === "spine" ? (
            <>
              <label className="ambient-canvas__lod-field">
                <span>
                  Node sep
                  <strong>{layoutTunings.spine.nodesep}</strong>
                </span>
                <input
                  type="range"
                  min={32}
                  max={140}
                  step={2}
                  value={layoutTunings.spine.nodesep}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      spine: {
                        ...layoutTunings.spine,
                        nodesep: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Rank sep
                  <strong>{layoutTunings.spine.ranksep}</strong>
                </span>
                <input
                  type="range"
                  min={56}
                  max={200}
                  step={2}
                  value={layoutTunings.spine.ranksep}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      spine: {
                        ...layoutTunings.spine,
                        ranksep: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Attach sep
                  <strong>{layoutTunings.spine.attachSep}</strong>
                </span>
                <input
                  type="range"
                  min={28}
                  max={120}
                  step={2}
                  value={layoutTunings.spine.attachSep}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      spine: {
                        ...layoutTunings.spine,
                        attachSep: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Attach offset
                  <strong>{layoutTunings.spine.attachOffset}</strong>
                </span>
                <input
                  type="range"
                  min={40}
                  max={200}
                  step={4}
                  value={layoutTunings.spine.attachOffset}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      spine: {
                        ...layoutTunings.spine,
                        attachOffset: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </>
          ) : null}
          {layoutId === "radial" ? (
            <>
              <label className="ambient-canvas__lod-field">
                <span>
                  Ring radius
                  <strong>{layoutTunings.radial.unitRadius}</strong>
                </span>
                <input
                  type="range"
                  min={120}
                  max={400}
                  step={5}
                  value={layoutTunings.radial.unitRadius}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      radial: {
                        ...layoutTunings.radial,
                        unitRadius: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Link dist
                  <strong>{layoutTunings.radial.linkDistance}</strong>
                </span>
                <input
                  type="range"
                  min={120}
                  max={400}
                  step={5}
                  value={layoutTunings.radial.linkDistance}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      radial: {
                        ...layoutTunings.radial,
                        linkDistance: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </>
          ) : null}
          {layoutId === "concentric" ? (
            <>
              <label className="ambient-canvas__lod-field">
                <span>
                  Ring node Ø
                  <strong>{layoutTunings.concentric.nodeSize}</strong>
                </span>
                <input
                  type="range"
                  min={48}
                  max={160}
                  step={4}
                  value={layoutTunings.concentric.nodeSize}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      concentric: {
                        ...layoutTunings.concentric,
                        nodeSize: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Level band
                  <strong>
                    {layoutTunings.concentric.maxLevelDiff.toFixed(2)}
                  </strong>
                </span>
                <input
                  type="range"
                  min={0.05}
                  max={0.5}
                  step={0.01}
                  value={layoutTunings.concentric.maxLevelDiff}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      concentric: {
                        ...layoutTunings.concentric,
                        maxLevelDiff: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </>
          ) : null}
          {layoutId === "cluster" ? (
            <>
              <label className="ambient-canvas__lod-field">
                <span>
                  Link dist
                  <strong>{layoutTunings.cluster.linkDist}</strong>
                </span>
                <input
                  type="range"
                  min={120}
                  max={400}
                  step={5}
                  value={layoutTunings.cluster.linkDist}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      cluster: {
                        ...layoutTunings.cluster,
                        linkDist: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Charge
                  <strong>{layoutTunings.cluster.charge}</strong>
                </span>
                <input
                  type="range"
                  min={120}
                  max={900}
                  step={10}
                  value={layoutTunings.cluster.charge}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      cluster: {
                        ...layoutTunings.cluster,
                        charge: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </>
          ) : null}
          {layoutId === "glide" ? (
            <>
              <label className="ambient-canvas__lod-field">
                <span>
                  Link dist
                  <strong>{layoutTunings.glide.linkDist}</strong>
                </span>
                <input
                  type="range"
                  min={140}
                  max={400}
                  step={5}
                  value={layoutTunings.glide.linkDist}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      glide: {
                        ...layoutTunings.glide,
                        linkDist: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="ambient-canvas__lod-field">
                <span>
                  Link str
                  <strong>{layoutTunings.glide.linkStrength.toFixed(2)}</strong>
                </span>
                <input
                  type="range"
                  min={0.02}
                  max={0.2}
                  step={0.01}
                  value={layoutTunings.glide.linkStrength}
                  disabled={switching}
                  onChange={(e) =>
                    retuneLayout({
                      ...layoutTunings,
                      glide: {
                        ...layoutTunings.glide,
                        linkStrength: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </>
          ) : null}
          <label className="ambient-canvas__lod-field">
            <span>
              Collide pad
              <strong>{settle.collidePad}</strong>
            </span>
            <input
              type="range"
              min={4}
              max={36}
              step={1}
              value={settle.collidePad}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({
                  ...settle,
                  collidePad: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Collide iters
              <strong>{settle.collideIterations}</strong>
            </span>
            <input
              type="range"
              min={2}
              max={12}
              step={1}
              value={settle.collideIterations}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({
                  ...settle,
                  collideIterations: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Snap
              <strong>{settle.snap.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.02}
              max={0.55}
              step={0.01}
              value={settle.snap}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({ ...settle, snap: Number(e.target.value) })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Charge
              <strong>{settle.charge}</strong>
            </span>
            <input
              type="range"
              min={0}
              max={180}
              step={5}
              value={settle.charge}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({ ...settle, charge: Number(e.target.value) })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Alpha
              <strong>{settle.alpha.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.25}
              max={1}
              step={0.05}
              value={settle.alpha}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({ ...settle, alpha: Number(e.target.value) })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              α decay
              <strong>{settle.alphaDecay.toFixed(3)}</strong>
            </span>
            <input
              type="range"
              min={0.012}
              max={0.08}
              step={0.002}
              value={settle.alphaDecay}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({
                  ...settle,
                  alphaDecay: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Damping
              <strong>{settle.velocityDecay.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.2}
              max={0.6}
              step={0.02}
              value={settle.velocityDecay}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({
                  ...settle,
                  velocityDecay: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Cool α
              <strong>{settle.coolAlpha.toFixed(3)}</strong>
            </span>
            <input
              type="range"
              min={0.002}
              max={0.05}
              step={0.002}
              value={settle.coolAlpha}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({
                  ...settle,
                  coolAlpha: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="ambient-canvas__lod-field">
            <span>
              Max ms
              <strong>{settle.maxMs}</strong>
            </span>
            <input
              type="range"
              min={400}
              max={10000}
              step={200}
              value={settle.maxMs}
              disabled={switching}
              onChange={(e) =>
                retuneSettle({
                  ...settle,
                  maxMs: Number(e.target.value),
                })
              }
            />
          </label>
        </div>
      </div>

      {/* EXPERIMENTAL — hidden. Server-persisted layout stands and LOD bands
          were dropped, so mass coarsening is not part of the decided canvas.
          Kept rather than deleted: it is the only place the coarsening model
          is exercised, and the question it answers — what a large graph shows
          at distance — is still open. Flip the flag to bring it back. */}
      {SHOW_EXPERIMENTAL_LOD ? (
      <div className="ambient-canvas__lod" aria-label="LOD parameters">
        <div className="ambient-canvas__lod-head">
          <span>LOD</span>
          <button type="button" onClick={() => setLod(DEFAULT_LOD_PARAMS)}>
            Reset
          </button>
        </div>
        <div
          className="ambient-canvas__layout-chips"
          role="group"
          aria-label="Mass LOD"
        >
          <button
            type="button"
            className={lodEnabled ? "is-active" : undefined}
            onClick={() => setLodEnabled(true)}
          >
            LOD on
          </button>
          <button
            type="button"
            className={!lodEnabled ? "is-active" : undefined}
            onClick={() => setLodEnabled(false)}
          >
            LOD off
          </button>
        </div>
        <div className="ambient-canvas__lod-grid">
          {(
            [
              {
                key: "minLevel",
                label: "Min level",
                min: 2,
                max: 24,
                step: 1,
                format: (v: number) => String(v),
                needsLod: true,
              },
              {
                key: "foldWindow",
                label: "Fold window",
                min: 0.05,
                max: 0.5,
                step: 0.01,
                format: (v: number) => v.toFixed(2),
                needsLod: true,
              },
              {
                key: "wheelSensitivity",
                label: "Wheel sens.",
                min: 0.00005,
                max: 0.0008,
                step: 0.00001,
                format: (v: number) => v.toFixed(5),
                needsLod: false,
              },
              {
                key: "dialSettleMs",
                label: "Settle ms",
                min: 40,
                max: 400,
                step: 10,
                format: (v: number) => String(v),
                needsLod: true,
              },
            ] as const
          ).map((field) => (
            <label
              key={field.key}
              className="ambient-canvas__lod-field"
              style={
                !lodEnabled && field.needsLod ? { opacity: 0.4 } : undefined
              }
            >
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
                disabled={!lodEnabled && field.needsLod}
                onChange={(e) =>
                  setLodField(field.key, Number(e.target.value))
                }
              />
            </label>
          ))}
        </div>
      </div>
      ) : null}

      <section
        className={
          seam.inverted
            ? "ambient-canvas__stage-shell is-focus"
            : "ambient-canvas__stage-shell"
        }
      >
        <div
          className="ambient-canvas__stage"
          ref={containerRef}
          onContextMenu={(e) => e.preventDefault()}
        />
      </section>
    </main>
  );
}
