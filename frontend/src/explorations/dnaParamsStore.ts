/**
 * Graph DNA workbench parameters — authored here, stored in the browser so a
 * tuned look survives reload. Defaults come from `styles/graphDna` + motion.
 */

import {
  GRAPH_DNA_CHROME,
  GRAPH_DNA_FOCUS,
  GRAPH_DNA_GEOMETRY,
  GRAPH_DNA_INTERACTION,
  GRAPH_DNA_THEME,
  type GraphDnaChrome,
  type GraphDnaFocusTheme,
  type GraphDnaTheme,
  type RadixScaleId,
  type RadixToken,
  type ThemeMode,
} from "../styles/graphDna";
import { MOTION_DURATION_MS } from "../styles/motion";
import type { NodeFontId } from "./g6/graphOptions";

const STORAGE_KEY = "graphauthor.graphDnaParams";

/**
 * Bump when the shipped look in `styles/graphDna` changes family or contrast.
 *
 * The workbench writes the whole blob to localStorage, including the look
 * tokens. Without a revision, a stale mauve dark would keep winning over a
 * newly shipped slate, and the workbench would report a product that is no
 * longer the product. Geometry and motion knobs survive a bump; only the
 * look tokens reset to whatever `graphDna.ts` now ships.
 */
export const DNA_LOOK_REVISION = 3;

export type DragTreatment = "weight" | "compression";

/**
 * Product chrome tokens — shell, Graphs panel, Ask, Node finder, reader.
 * Distinct from graph matter (nodes/edges) so UI and map can be tuned apart,
 * but defined beside it in `styles/graphDna`, which is the one source the
 * shipping product reads.
 */
export type DnaChromeTheme = GraphDnaChrome;

export type DnaParams = {
  lookRevision: number;
  light: GraphDnaTheme;
  dark: GraphDnaTheme;
  focus: GraphDnaFocusTheme;
  /** Shell / overlay chrome for light product theme. */
  chromeLight: DnaChromeTheme;
  /** Shell / overlay chrome for dark product theme. */
  chromeDark: DnaChromeTheme;
  nodeDiameter: number;
  nodeLine: number;
  labelFontId: NodeFontId;
  /** Node label weight inside the disc (G6 labelFontWeight). */
  labelFontWeight: number;
  labelSize: number;
  labelMaxWidth: number;
  labelBaselineNudge: number;
  /** Multiple of the label size between wrapped lines. */
  labelLineHeight: number;
  /** Lines a node label may wrap to before it is elided. */
  labelMaxLines: number;
  /** The disc itself, independent of the name inside it. */
  nodeFillOpacity: number;
  /** The name inside the disc, independent of the disc. */
  nodeLabelOpacity: number;
  edgeWidth: number;
  edgeOpacity: number;
  edgeLabelSize: number;
  /** The relation chip on a lit edge, independent of the line under it. */
  edgeLabelOpacity: number;
  /** What a spoke keeps at rest, as a fraction of what it would have had. */
  spokeRestOpacity: number;
  dottedGap: number;
  hoverRadius: number;
  hoverResponse: number;
  motionEmit: number;
  motionAbsorb: number;
  motionSettle: number;
  gravityStrength: number;
  gravityTravel: number;
  absorbPull: number;
  gripScale: number;
  dragTreatment: DragTreatment;
  dragCompression: number;
  dragNodeRelief: number;
  dragEdgeLoad: number;
  dragEdgePresence: number;
  /** Ring arrival/exit — screen-space SVG, not canvas elements. */
  selectionMotion: boolean;
  selectionSpeed: number;
  selectionClearance: number;
  selectionDotGap: number;
  selectionLine: number;
  /** Live-map display spacing, same meaning as product graphPrefs.spacing. */
  spacing: number;
  /** Graphs sidebar body width (px). */
  overlayWidth: number;
  /** Node reader default width (px). */
  readerWidth: number;
  /**
   * Opacity of a floating chrome cluster over the map. Flat translucency only —
   * there is no blur behind it. A frosted panel is a light-source effect, and
   * this product separates a floating surface from the map with a rule.
   */
  chromeOpacity: number;
};

export const DNA_CHROME_DEFAULTS = GRAPH_DNA_CHROME;

export const DNA_PARAM_DEFAULTS: DnaParams = {
  lookRevision: DNA_LOOK_REVISION,
  light: GRAPH_DNA_THEME.light,
  dark: GRAPH_DNA_THEME.dark,
  focus: { ...GRAPH_DNA_FOCUS },
  chromeLight: { ...DNA_CHROME_DEFAULTS.light },
  chromeDark: { ...DNA_CHROME_DEFAULTS.dark },
  nodeDiameter: GRAPH_DNA_GEOMETRY.nodeDiameter,
  nodeLine: GRAPH_DNA_GEOMETRY.nodeLine,
  labelFontId: "jost",
  labelFontWeight: 400,
  labelSize: GRAPH_DNA_GEOMETRY.labelSize,
  labelMaxWidth: GRAPH_DNA_GEOMETRY.labelMaxWidth,
  labelBaselineNudge: GRAPH_DNA_GEOMETRY.labelBaselineNudge,
  labelLineHeight: GRAPH_DNA_GEOMETRY.labelLineHeight,
  labelMaxLines: GRAPH_DNA_GEOMETRY.labelMaxLines,
  nodeFillOpacity: GRAPH_DNA_GEOMETRY.nodeFillOpacity,
  nodeLabelOpacity: GRAPH_DNA_GEOMETRY.nodeLabelOpacity,
  edgeWidth: GRAPH_DNA_GEOMETRY.edgeWidth,
  edgeOpacity: GRAPH_DNA_GEOMETRY.edgeOpacity,
  edgeLabelSize: GRAPH_DNA_GEOMETRY.edgeLabelSize,
  edgeLabelOpacity: GRAPH_DNA_GEOMETRY.edgeLabelOpacity,
  spokeRestOpacity: GRAPH_DNA_GEOMETRY.spokeRestOpacity,
  dottedGap: GRAPH_DNA_GEOMETRY.dottedGap,
  hoverRadius: GRAPH_DNA_INTERACTION.hoverRadius,
  hoverResponse: GRAPH_DNA_INTERACTION.hoverResponse,
  motionEmit: MOTION_DURATION_MS.emit,
  motionAbsorb: MOTION_DURATION_MS.absorb,
  motionSettle: MOTION_DURATION_MS.settle,
  selectionMotion: GRAPH_DNA_INTERACTION.selectionMotion,
  gravityStrength: GRAPH_DNA_INTERACTION.gravityStrength,
  gravityTravel: GRAPH_DNA_INTERACTION.gravityTravel,
  absorbPull: GRAPH_DNA_INTERACTION.absorbPull,
  gripScale: GRAPH_DNA_INTERACTION.gripScale,
  dragTreatment: "weight",
  dragCompression: 0.96,
  dragNodeRelief: GRAPH_DNA_INTERACTION.dragNodeRelief,
  dragEdgeLoad: GRAPH_DNA_INTERACTION.dragEdgeLoad,
  dragEdgePresence: GRAPH_DNA_INTERACTION.dragEdgePresence,
  selectionSpeed: GRAPH_DNA_INTERACTION.selectionSpeed,
  selectionClearance: GRAPH_DNA_INTERACTION.selectionClearance,
  selectionDotGap: GRAPH_DNA_INTERACTION.selectionDotGap,
  selectionLine: GRAPH_DNA_INTERACTION.selectionLine,
  /** 1 = as arranged (collision-safe baseline); only multiplies room upward. */
  spacing: 1,
  overlayWidth: 360,
  readerWidth: 420,
  chromeOpacity: 1,
};

function isToken(value: unknown): value is RadixToken {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    typeof (value as RadixToken).scale === "string" &&
    typeof (value as RadixToken).step === "number"
  );
}

function mergeTheme(
  base: GraphDnaTheme,
  patch: Partial<GraphDnaTheme> | undefined,
): GraphDnaTheme {
  if (!patch) return base;
  const next = { ...base };
  for (const key of Object.keys(base) as Array<keyof GraphDnaTheme>) {
    if (isToken(patch[key])) next[key] = patch[key] as RadixToken;
  }
  return next;
}

function mergeFocus(
  base: GraphDnaFocusTheme,
  patch: Partial<GraphDnaFocusTheme> | undefined,
): GraphDnaFocusTheme {
  if (!patch) return base;
  const next = { ...base };
  for (const key of Object.keys(base) as Array<keyof GraphDnaFocusTheme>) {
    if (isToken(patch[key])) next[key] = patch[key] as RadixToken;
  }
  return next;
}

function mergeChrome(
  base: DnaChromeTheme,
  patch: Partial<DnaChromeTheme> | undefined,
): DnaChromeTheme {
  if (!patch) return base;
  const next = { ...base };
  for (const key of Object.keys(base) as Array<keyof DnaChromeTheme>) {
    if (isToken(patch[key])) next[key] = patch[key] as RadixToken;
  }
  return next;
}

function clamp(value: unknown, min: number, max: number, fallback: number) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

export function chromeForTheme(
  params: DnaParams,
  mode: ThemeMode,
): DnaChromeTheme {
  return mode === "dark" ? params.chromeDark : params.chromeLight;
}

export function readDnaParams(): DnaParams {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DNA_PARAM_DEFAULTS;
    const stored = JSON.parse(raw) as Partial<DnaParams>;
    const keepLook = stored.lookRevision === DNA_LOOK_REVISION;
    const next: DnaParams = {
      ...DNA_PARAM_DEFAULTS,
      ...stored,
      lookRevision: DNA_LOOK_REVISION,
      light: keepLook
        ? mergeTheme(DNA_PARAM_DEFAULTS.light, stored.light)
        : DNA_PARAM_DEFAULTS.light,
      dark: keepLook
        ? mergeTheme(DNA_PARAM_DEFAULTS.dark, stored.dark)
        : DNA_PARAM_DEFAULTS.dark,
      focus: keepLook
        ? mergeFocus(DNA_PARAM_DEFAULTS.focus, stored.focus)
        : DNA_PARAM_DEFAULTS.focus,
      chromeLight: keepLook
        ? mergeChrome(DNA_PARAM_DEFAULTS.chromeLight, stored.chromeLight)
        : DNA_PARAM_DEFAULTS.chromeLight,
      chromeDark: keepLook
        ? mergeChrome(DNA_PARAM_DEFAULTS.chromeDark, stored.chromeDark)
        : DNA_PARAM_DEFAULTS.chromeDark,
      labelFontId: (stored.labelFontId as NodeFontId) || "jost",
      labelFontWeight: clamp(
        stored.labelFontWeight,
        400,
        800,
        DNA_PARAM_DEFAULTS.labelFontWeight,
      ),
      dragTreatment:
        stored.dragTreatment === "compression" ? "compression" : "weight",
      // Coerced rather than spread through: a value stored before this
      // parameter existed is `undefined`, and only an explicit `false` should
      // mean off. Everything else — missing, corrupt, a string — falls back to
      // the authored default rather than silently disabling the one piece of
      // motion the product ships.
      selectionMotion: stored.selectionMotion !== false,
      nodeDiameter: clamp(
        stored.nodeDiameter,
        24,
        120,
        DNA_PARAM_DEFAULTS.nodeDiameter,
      ),
      spacing: clamp(stored.spacing, 1, 2, DNA_PARAM_DEFAULTS.spacing),
      overlayWidth: clamp(
        stored.overlayWidth,
        240,
        520,
        DNA_PARAM_DEFAULTS.overlayWidth,
      ),
      readerWidth: clamp(
        stored.readerWidth,
        280,
        640,
        DNA_PARAM_DEFAULTS.readerWidth,
      ),
      chromeOpacity: clamp(
        stored.chromeOpacity,
        0.6,
        1,
        DNA_PARAM_DEFAULTS.chromeOpacity,
      ),
      labelLineHeight: clamp(
        stored.labelLineHeight,
        0.9,
        1.8,
        DNA_PARAM_DEFAULTS.labelLineHeight,
      ),
      labelMaxLines: Math.round(
        clamp(stored.labelMaxLines, 1, 4, DNA_PARAM_DEFAULTS.labelMaxLines),
      ),
      nodeFillOpacity: clamp(
        stored.nodeFillOpacity,
        0.1,
        1,
        DNA_PARAM_DEFAULTS.nodeFillOpacity,
      ),
      nodeLabelOpacity: clamp(
        stored.nodeLabelOpacity,
        0.2,
        1,
        DNA_PARAM_DEFAULTS.nodeLabelOpacity,
      ),
      edgeLabelOpacity: clamp(
        stored.edgeLabelOpacity,
        0.2,
        1,
        DNA_PARAM_DEFAULTS.edgeLabelOpacity,
      ),
      spokeRestOpacity: clamp(
        stored.spokeRestOpacity,
        0.05,
        1,
        DNA_PARAM_DEFAULTS.spokeRestOpacity,
      ),
      labelBaselineNudge: clamp(
        stored.labelBaselineNudge,
        -8,
        12,
        DNA_PARAM_DEFAULTS.labelBaselineNudge,
      ),
    };
    if (!keepLook) writeDnaParams(next);
    return next;
  } catch {
    return DNA_PARAM_DEFAULTS;
  }
}

export function writeDnaParams(params: DnaParams): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(params));
  } catch {
    /* storage full — workbench still works in memory */
  }
}

export type { RadixScaleId, RadixToken };
