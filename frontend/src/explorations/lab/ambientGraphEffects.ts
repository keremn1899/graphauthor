/**
 * Shared ambient canvas visual language for labs that need the real effects
 * (hover bond, charcoal focus, linkage-idle edges) without the full LOD page.
 *
 * Style callbacks read module-level live palettes — same pattern as
 * AmbientCanvasLabPage. Defaults mirror ambient's DEFAULT_LOD_PARAMS /
 * DEFAULT_NODE_STYLE (unit Ø 50, Jost @ 0.12×Ø, weight 400).
 */
import { gray, grayDark } from "@radix-ui/colors";
import type { EdgeData, Graph, GraphData, NodeData } from "@antv/g6";
import { NODE_FONTS } from "../g6/graphOptions";
import {
  arrowSizeForKind,
  isDirectedKind,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import { AMBIENT_LINKAGE_EDGE } from "./ambientLinkageEdge";
import { massDiameter } from "./ambientMassModel";
import { FONT_MONO_FAMILY } from "../../styles/typography";

/** Mirror AmbientCanvasLabPage DEFAULT_LOD_PARAMS (size knobs only). */
const LOD = {
  unitDiameter: 50,
  landmarkBoost: 1,
} as const;

export type ThemeMode = "light" | "dark";

type ThemePalette = {
  ink: string;
  node: string;
  paper: string;
  chip: string;
  lensLabel: string;
  bondLabel: string;
};

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

/** Match AmbientCanvasLabPage DEFAULT_NODE_STYLE. */
const STYLE = {
  fontId: "jost" as const,
  labelOffsetY: 1,
  labelFontPerDiameter: 0.12,
  labelAppearPx: 11,
  lineWidth: 1,
  labelFontWeight: 400,
};

const THEME_LIGHT: ThemePalette = {
  ink: gray.gray12,
  node: gray.gray12,
  paper: gray.gray1,
  chip: gray.gray1,
  lensLabel: gray.gray9,
  bondLabel: gray.gray12,
};

const FOCUS_DARK: FocusPalette = {
  field: grayDark.gray1,
  lit: grayDark.gray12,
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
const LENS_CEILING = 0.82;

const themeLive: ThemePalette & { mode: ThemeMode } = {
  ...THEME_LIGHT,
  mode: "light",
};

const focusLive: FocusPalette & { inverted: boolean } = {
  inverted: false,
  ...FOCUS_DARK,
};

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
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * u)}, ${Math.round(a[1] + (b[1] - a[1]) * u)}, ${Math.round(a[2] + (b[2] - a[2]) * u)})`;
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

function num(datum: NodeData | EdgeData, key: string, fallback = 0) {
  const v = Number(datum.data?.[key]);
  return Number.isFinite(v) ? v : fallback;
}

function intensityOf(datum: NodeData | EdgeData) {
  return num(datum, "intensity", FOCUS_OFF);
}

function isFocusLit(datum: NodeData | EdgeData) {
  return intensityOf(datum) >= FOCUS_ON;
}

function diffOf(datum: NodeData | EdgeData) {
  return String(datum.data?.diff ?? "unchanged");
}

function labelOf(datum: NodeData) {
  return String(datum.data?.label ?? datum.id ?? "");
}

function isLandmark(datum: NodeData) {
  return Boolean(datum.data?.is_landmark);
}

/** Solid selection moon — lives in graph space so zoom/pan keep it tied. */
export function isSelectionOrbiter(datum: NodeData) {
  return Boolean(datum.data?._selectionOrbiter);
}

/** Ambient massDiameter at default LOD (unit Ø 50, landmarkBoost 1). */
function diameterOf(datum: NodeData) {
  if (isSelectionOrbiter(datum)) {
    const stamped = num(datum, "_d", 0);
    if (stamped > 0) return stamped;
    const size = Number(datum.style?.size);
    return Number.isFinite(size) && size > 0 ? size : 11;
  }
  const stamped = num(datum, "_d", 0);
  if (stamped > 0) return stamped;
  return massDiameter(
    Math.max(0, num(datum, "_p", 1) * num(datum, "_m", 1)),
    LOD.unitDiameter,
    isLandmark(datum),
    LOD.landmarkBoost,
  );
}

function edgePresence(datum: EdgeData) {
  const ep = num(datum, "_ep", 1);
  return ep > 0 ? ep : 1;
}

function edgeKindLabel(datum: EdgeData) {
  return String(datum.data?.label ?? "");
}

function lensOf(datum: EdgeData) {
  const value = Number(datum.data?.lens);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
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

export function setAmbientFocusInverted(inverted: boolean) {
  focusLive.inverted = inverted;
}

export function isAmbientFocusInverted() {
  return focusLive.inverted;
}

export function ambientFocusField() {
  return focusLive.field;
}

export function buildAmbientNodeStyle() {
  const font = NODE_FONTS[STYLE.fontId];
  return {
    size: (datum: NodeData) => diameterOf(datum),
    fill: (datum: NodeData) => {
      if (isSelectionOrbiter(datum)) {
        return focusLive.inverted ? focusLive.lit : themeLive.node;
      }
      if (!focusLive.inverted) return themeLive.node;
      const diff = diffOf(datum);
      if (diff === "added") return focusLive.lit;
      if (diff === "removed") return focusLive.field;
      return massColor(intensityOf(datum));
    },
    stroke: (datum: NodeData) => {
      if (isSelectionOrbiter(datum)) {
        return focusLive.inverted ? focusLive.lit : themeLive.node;
      }
      if (!focusLive.inverted) return themeLive.node;
      const diff = diffOf(datum);
      if (diff === "added" || diff === "removed" || diff === "touched") {
        return focusLive.lit;
      }
      return massColor(intensityOf(datum));
    },
    lineWidth: (datum: NodeData) => {
      if (isSelectionOrbiter(datum)) return 0;
      if (!focusLive.inverted) return STYLE.lineWidth;
      if (diffOf(datum) === "removed") return 1.6;
      if (diffOf(datum) === "added" || diffOf(datum) === "touched") return 1.5;
      return STYLE.lineWidth;
    },
    lineDash: (datum: NodeData) => {
      if (isSelectionOrbiter(datum)) return undefined;
      return focusLive.inverted && diffOf(datum) === "removed"
        ? DOTTED
        : undefined;
    },
    lineCap: "round" as const,
    halo: false,
    badge: false,
    haloStrokeOpacity: 0,
    opacity: 1,
    pointerEvents: (datum: NodeData) =>
      isSelectionOrbiter(datum) ? ("none" as const) : ("auto" as const),
    labelText: (datum: NodeData) =>
      isSelectionOrbiter(datum) ? "" : labelOf(datum),
    labelPlacement: "center" as const,
    labelOffsetY: () => STYLE.labelOffsetY,
    labelOffsetX: 0,
    labelFill: (datum: NodeData) => {
      if (isSelectionOrbiter(datum)) return "transparent";
      if (!focusLive.inverted) return themeLive.paper;
      const diff = diffOf(datum);
      if (diff === "added") return focusLive.litLabel;
      if (diff === "touched" || diff === "removed") return focusLive.lit;
      return massLabelFill(intensityOf(datum));
    },
    labelOpacity: (datum: NodeData) => {
      if (isSelectionOrbiter(datum)) return 0;
      if (!focusLive.inverted) return 1;
      const diff = diffOf(datum);
      if (diff === "touched" || diff === "added" || diff === "removed") return 1;
      return intensityOf(datum) >= FOCUS_ON ? 1 : 0.85;
    },
    labelFontFamily: font.family,
    labelFontSize: (datum: NodeData) =>
      isSelectionOrbiter(datum)
        ? 0.1
        : Math.max(0.1, diameterOf(datum) * STYLE.labelFontPerDiameter),
    labelFontWeight: () => STYLE.labelFontWeight,
    labelLineHeight: (datum: NodeData) =>
      Math.max(
        10,
        diameterOf(datum) * STYLE.labelFontPerDiameter * 1.15,
      ),
    labelWordWrap: true,
    labelMaxWidth: (datum: NodeData) => diameterOf(datum) * 0.92,
    labelMaxLines: 2,
    labelTextOverflow: "ellipsis",
    labelTextAlign: "center" as const,
    labelTextBaseline: "middle" as const,
    cursor: (datum: NodeData) =>
      isSelectionOrbiter(datum) ? ("default" as const) : ("grab" as const),
    zIndex: (datum: NodeData) => (isSelectionOrbiter(datum) ? 20 : 0),
  };
}

export function buildAmbientNodeState() {
  return {
    selected: { halo: false, haloStrokeOpacity: 0 },
    active: { halo: false, haloStrokeOpacity: 0 },
  };
}

export function buildAmbientEdgeStyle() {
  const focusTyped = (datum: EdgeData) =>
    focusLive.inverted && isFocusLit(datum);

  // Type lives on Graph `edge.type` — never inside style (ambient canvas).
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
    lineDash: (datum: EdgeData) =>
      focusLive.inverted && diffOf(datum) === "removed" ? DOTTED : undefined,
    opacity: (datum: EdgeData) => {
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
    labelPlacement: 0.5,
    labelOffsetX: 0,
    labelOffsetY: 0,
    labelOpacity: (datum: EdgeData) => {
      if (edgePresence(datum) <= 0.02) return 0;
      if (focusTyped(datum)) return 1;
      const lens = lensOf(datum);
      return lens <= 0 ? 0 : Math.min(1, lens);
    },
    labelBackgroundOpacity: (datum: EdgeData) => {
      if (edgePresence(datum) <= 0.02) return 0;
      if (focusTyped(datum)) return 1;
      return lensOf(datum) <= 0 ? 0 : 1;
    },
    increasedLineWidthForHitTesting: 20,
  };
}

export function buildAmbientEdgeState() {
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
    opacity: (datum: EdgeData) => Math.min(1, edgePresence(datum) * 0.95),
    endArrow: (datum: EdgeData) => isDirectedKind(linkageEdgeKind(datum)),
    endArrowSize: (datum: EdgeData) =>
      arrowSizeForKind(linkageEdgeKind(datum)),
    endArrowFill: () => (focusLive.inverted ? focusLive.lit : themeLive.ink),
    endArrowFillOpacity: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum)) ? 1 : 0,
    endArrowStrokeOpacity: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum)) ? 1 : 0,
    endArrowOffset: (datum: EdgeData) =>
      isDirectedKind(linkageEdgeKind(datum))
        ? arrowSizeForKind(linkageEdgeKind(datum)) / 2 + 1
        : 0.01,
    labelFill: () =>
      focusLive.inverted ? focusLive.lit : themeLive.bondLabel,
    labelBackground: true,
    labelBackgroundFill: () =>
      focusLive.inverted ? focusLive.chip : themeLive.chip,
    labelBackgroundOpacity: 1,
    labelOpacity: 1,
    labelFontSize: 7,
  };
  return {
    selected: { halo: false, haloStrokeOpacity: 0 },
    active: { halo: false, haloStrokeOpacity: 0 },
    out: { ...bondBase, labelOffsetX: 0, labelOffsetY: 0 },
    inn: { ...bondBase, labelOffsetX: 0, labelOffsetY: 0 },
  };
}

export type HoverBundle = { out: Set<string>; inn: Set<string> };

export function emptyHoverBundle(): HoverBundle {
  return { out: new Set(), inn: new Set() };
}

export function hoverBundleFor(graph: Graph, nodeId: string): HoverBundle {
  const out = new Set<string>();
  const inn = new Set<string>();
  for (const edge of graph.getRelatedEdgesData(nodeId)) {
    const id = String(edge.id);
    if (edgePresence(edge) <= 0.02) continue;
    if (focusLive.inverted && isFocusLit(edge)) continue;
    if (String(edge.source) === nodeId) out.add(id);
    else inn.add(id);
  }
  return { out, inn };
}

/** True when focus is inverted and this node is a lit seed. */
export function isAmbientFocusLitNode(graph: Graph, nodeId: string) {
  if (!focusLive.inverted) return false;
  const node = graph.getNodeData(nodeId);
  return Boolean(node && isFocusLit(node));
}

/** Drop out/inn bond states so focus/seam paint isn't fighting hover chips. */
export async function clearAmbientHoverStates(graph: Graph) {
  if (graph.destroyed) return;
  const states: Record<string, string[]> = {};
  for (const edge of graph.getEdgeData()) {
    const id = String(edge.id);
    const cur = graph.getElementState(id);
    if (!cur.includes("out") && !cur.includes("inn")) continue;
    states[id] = cur.filter((s) => s !== "out" && s !== "inn");
  }
  if (Object.keys(states).length === 0) return;
  await graph.setElementState(states, false).catch(() => {});
}

/** Rebind style callbacks after intensity / inverted flips (setData alone can miss). */
export function rebindAmbientStyles(graph: Graph) {
  if (graph.destroyed) return;
  graph.setNode({
    type: "circle",
    style: buildAmbientNodeStyle(),
    state: buildAmbientNodeState(),
  });
  graph.setEdge({
    type: AMBIENT_LINKAGE_EDGE,
    style: buildAmbientEdgeStyle() as never,
    state: buildAmbientEdgeState() as never,
    animation: false,
  });
}

/** Stamp presence / diameter so ambient style callbacks light up without LOD. */
export function prepareAmbientTrialData(data: GraphData): GraphData {
  const unit = LOD.unitDiameter;
  const boost = LOD.landmarkBoost;
  return {
    nodes: (data.nodes ?? []).map((n) => {
      const landmark = Boolean(n.data?.is_landmark);
      const d = massDiameter(1, unit, landmark, boost);
      return {
        ...n,
        data: {
          ...n.data,
          _p: 1,
          _m: 1,
          _d: d,
          _ep: 1,
        },
        style: {
          ...n.style,
          size: d,
        },
      };
    }),
    edges: (data.edges ?? []).map((e) => ({
      ...e,
      data: {
        ...e.data,
        _ep: 1,
        label: e.data?.label ?? linkageEdgeKind(e).toUpperCase(),
      },
    })),
  };
}
