/**
 * The graph's design DNA — one source for how graph matter looks.
 *
 * These values are the Graph DNA workbench's defaults. They live here rather
 * than inside that page so a second surface cannot quietly ship a *stale* copy
 * of the look, which is exactly how the ambient canvas and the workbench
 * drifted apart. Anything drawing graph matter should read from here.
 *
 * The language, briefly: a gray field, nodes as solid discs of the
 * darkest ink with their label set *inside* them in the field colour, and edges
 * as thin filaments of the same ink. Weight comes from fill, not from stroke.
 *
 * The workbench is where this language is *authored*, and it reads these
 * exports rather than keeping its own copy — the two were byte-identical and
 * staying in sync only by luck, which is the drift this module exists to stop.
 * The workbench still owns the knobs that are its own: focus tokens, motion,
 * gravity, drag and selection.
 */

import * as radixColors from "@radix-ui/colors";

export type RadixScaleId = keyof typeof radixColors | "black";
export type RadixToken = { scale: RadixScaleId; step: number };
export type ThemeMode = "light" | "dark";

/** Shorthand for a scale+step pair. Exported so no surface re-declares it. */
export const token = (scale: RadixScaleId, step: number): RadixToken => ({
  scale,
  step,
});

export type GraphDnaTheme = {
  /** Page chrome behind the canvas. */
  surface: RadixToken;
  /** The field the graph sits on. */
  canvas: RadixToken;
  /** Edge filaments. */
  filament: RadixToken;
  /** Node fill. */
  node: RadixToken;
  /** Node label, set inside the node. */
  nodeLabel: RadixToken;
  /** Chip / label backing. */
  chip: RadixToken;
  /** Secondary label ink. */
  lensLabel: RadixToken;
  /** Emphasised label ink. */
  bondLabel: RadixToken;
};

export type GraphDnaFocusTheme = {
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

export const GRAPH_DNA_THEME: Record<ThemeMode, GraphDnaTheme> = {
  light: {
    surface: token("gray", 3),
    canvas: token("gray", 3),
    filament: token("gray", 12),
    node: token("gray", 12),
    nodeLabel: token("gray", 3),
    chip: token("gray", 3),
    lensLabel: token("gray", 9),
    bondLabel: token("gray", 12),
  },
  dark: {
    surface: token("slateDark", 1),
    canvas: token("slateDark", 1),
    filament: token("slateDark", 11),
    node: token("slateDark", 11),
    nodeLabel: token("slateDark", 1),
    // The chip is a *knockout*, not a card: it exists so a label reads over the
    // filaments crossing under it, which means it has to be the field exactly.
    // Shipping step 3 against a step 1 canvas drew a visible plate behind every
    // edge label — chips stay the field colour in both rooms.
    chip: token("slateDark", 1),
    lensLabel: token("slateDark", 9),
    bondLabel: token("slateDark", 12),
  },
};

/**
 * Provisional matter — a graph nobody has published yet.
 *
 * A construction is looked at for the same reason a published graph is, so it
 * has to stay legible; what it must never do is read as settled. The move is
 * therefore *within* the scale rather than out of it: the field comes up one
 * step, matter comes down one or two, and the gap between them narrows.
 * Everything is still the same gray in the same room — the graph just has less
 * presence in it.
 *
 * Matter sat two to three steps down at first and read as fog rather than as a
 * state: legibility is the whole reason to open this surface, so the mute has
 * to be the smallest one that still cannot be mistaken for a published graph.
 * It is a step gentler than it was.
 *
 * Done as a palette rather than as `opacity` on the stage, which is what this
 * replaced. Opacity fades a whole subtree including its labels and any focus
 * state drawn over it, so a lit answer on a construction came out fainter than
 * unlit matter on a published graph — the emphasis inverted. A palette moves
 * the resting look and leaves every state that is drawn *on top* at full
 * strength.
 */
export const GRAPH_DNA_PROVISIONAL_THEME: Record<ThemeMode, GraphDnaTheme> = {
  light: {
    surface: token("gray", 4),
    canvas: token("gray", 4),
    filament: token("gray", 10),
    node: token("gray", 11),
    // The label sits inside the disc, so it tracks the field, not the ink.
    nodeLabel: token("gray", 4),
    chip: token("gray", 4),
    lensLabel: token("gray", 9),
    bondLabel: token("gray", 11),
  },
  dark: {
    surface: token("slateDark", 2),
    canvas: token("slateDark", 2),
    filament: token("slateDark", 9),
    node: token("slateDark", 10),
    nodeLabel: token("slateDark", 2),
    chip: token("slateDark", 2),
    lensLabel: token("slateDark", 9),
    bondLabel: token("slateDark", 11),
  },
};

/**
 * Ledger focus is a separate reading state, not the ambient dark theme. The
 * field inverts so a subject set can be read as one bounded object while the
 * rest of the committed graph remains present as quiet context.
 *
 * Greyscale on purpose, even though ambient dark is slate: if both rooms used
 * the same family, asking a question would look like dimming the lights. The
 * field is off-scale black rather than grayDark 1, so it cannot share a colour
 * with slateDark 1. Lit matter and dim context stay on grayDark; only the
 * paper leaves the scale.
 */
export const GRAPH_DNA_FOCUS: GraphDnaFocusTheme = {
  field: token("black", 1),
  lit: token("grayDark", 12),
  dimNode: token("grayDark", 3),
  dimEdge: token("grayDark", 4),
  litLabel: token("grayDark", 1),
  dimLabel: token("grayDark", 10),
  chip: token("black", 1),
  lensLabel: token("grayDark", 8),
  bondLabel: token("grayDark", 9),
};

/**
 * Product chrome — shell, panels, rules, type.
 *
 * Here rather than beside the product because the graph is the design source:
 * chrome is the same ink and the same paper as node matter, one step apart on
 * the same Radix scale, and that relationship is the thing worth keeping. The
 * shell reads these on every render, so the DNA workbench tunes what actually
 * ships.
 *
 * This used to be stated twice — as hex in `ProductShell.css` and as tokens in
 * the workbench — and the two had already drifted: `ink-muted` shipped as
 * `#646464` while the workbench showed `gray9`, and `rule` as `#d9d9d9` against
 * `gray6`. Every chrome knob on that page was tuning a value the product did
 * not use.
 */
export type GraphDnaChrome = {
  canvas: RadixToken;
  panel: RadixToken;
  ink: RadixToken;
  inkMuted: RadixToken;
  rule: RadixToken;
};

/** Shell chrome tokens — kept in step with graph matter on the same Radix scales. */
export const GRAPH_DNA_CHROME: Record<ThemeMode, GraphDnaChrome> = {
  light: {
    canvas: token("gray", 3),
    panel: token("gray", 4),
    ink: token("gray", 12),
    inkMuted: token("gray", 9),
    rule: token("gray", 6),
  },
  dark: {
    canvas: token("slateDark", 1),
    panel: token("slateDark", 2),
    ink: token("slateDark", 12),
    inkMuted: token("slateDark", 9),
    rule: token("slateDark", 6),
  },
};

/**
 * Provisional chrome — the shell around a graph nobody has published.
 *
 * Same move as the matter palette and it has to be applied together: chrome
 * one step quieter under an unchanged map would read as a rendering fault
 * rather than as a state. Ink drops from the scale's text step to its readable
 * step, and the field rises, so the whole surface loses contrast without
 * anything becoming hard to read.
 */
export const GRAPH_DNA_PROVISIONAL_CHROME: Record<ThemeMode, GraphDnaChrome> = {
  light: {
    canvas: token("gray", 4),
    panel: token("gray", 5),
    ink: token("gray", 11),
    inkMuted: token("gray", 8),
    rule: token("gray", 5),
  },
  dark: {
    canvas: token("slateDark", 2),
    panel: token("slateDark", 3),
    ink: token("slateDark", 11),
    inkMuted: token("slateDark", 8),
    rule: token("slateDark", 5),
  },
};

/**
 * The three things colour is allowed to mean.
 *
 * The map is monochrome because geometry and weight carry meaning there, so
 * colour would be decoration. A queue is not a map: which decisions are on fire
 * is the first thing an operator needs, and colour earns its place by encoding
 * a state that changes what you do. Three states, and adding a fourth is a
 * design decision that has to be made here.
 *
 * These lived as six hex literals inside `ReviewWorkspace.css`, from when
 * Review was the only surface with status to report. Two things broke that:
 *
 *   The nav now reports the same "waiting for you" in the top bar. A value that
 *   means one thing in two places has to *be* one value, or it drifts into two
 *   — which is the failure `GRAPH_DNA_CHROME` was written for, after
 *   `--ink-muted` was declared as hex in one place and a Radix token in
 *   another and the workbench spent a release tuning a value nothing used.
 *
 *   Hand-mixed hex has no theme. The literals were picked against a light
 *   panel and never changed for dark, so a correction that runs one way ran the
 *   wrong way on half the product. Radix's step 11 is the readable-text step of
 *   its scale in both modes, which is exactly the guarantee that was missing.
 *
 * One step for fill and text alike. The old pair — a fill and a darkened form
 * of it for small type — existed because the two were mixed by hand and the
 * fill was unreadable at 0.6rem; a step engineered for text is legible as both,
 * and one token cannot disagree with itself.
 */
export type GraphDnaStatus = {
  /** Waiting on this operator. */
  attention: RadixToken;
  /** Something failed and is blocking. */
  alarm: RadixToken;
  /** Decided; no longer demanding. */
  settled: RadixToken;
};

export const GRAPH_DNA_STATUS: Record<ThemeMode, GraphDnaStatus> = {
  light: {
    attention: token("orange", 11),
    alarm: token("tomato", 11),
    settled: token("jade", 11),
  },
  dark: {
    attention: token("orangeDark", 11),
    alarm: token("tomatoDark", 11),
    settled: token("jadeDark", 11),
  },
};

/** The status tokens as CSS custom properties, ready to spread onto a root. */
export function statusCssVariables(
  status: GraphDnaStatus,
): Record<string, string> {
  return {
    "--attention": radixValue(status.attention),
    "--alarm": radixValue(status.alarm),
    "--settled": radixValue(status.settled),
  };
}

/** The chrome tokens as CSS custom properties, ready to spread onto a root. */
export function chromeCssVariables(
  chrome: GraphDnaChrome,
): Record<string, string> {
  return {
    "--canvas": radixValue(chrome.canvas),
    "--panel": radixValue(chrome.panel),
    "--ink": radixValue(chrome.ink),
    "--ink-muted": radixValue(chrome.inkMuted),
    "--rule": radixValue(chrome.rule),
  };
}

/**
 * The focus palette as CSS, for the canvas's inverted reading state.
 *
 * Named `--focus-*` and never spelled as hex in a stylesheet, for the reason
 * `GRAPH_DNA_CHROME` exists. Ask does not read these directly: it uses the
 * shell's `--canvas` / `--ink`, which `ProductShell` remaps onto this palette
 * when the map inverts. Wiring Ask at `--focus-*` while the map was still
 * light put dark-room ink on a light field.
 */
export function focusCssVariables(
  focus: GraphDnaFocusTheme,
): Record<string, string> {
  return {
    "--focus-field": radixValue(focus.field),
    "--focus-ink": radixValue(focus.lit),
    "--focus-ink-muted": radixValue(focus.dimLabel),
    "--focus-rule": radixValue(focus.dimEdge),
    "--focus-on-ink": radixValue(focus.litLabel),
  };
}

/**
 * Geometry and weight. Defaults match the Graph DNA workbench shipping look:
 * ~90px discs, 11px node type at 80% width, quieter filaments and spokes.
 */
export const GRAPH_DNA_GEOMETRY = {
  nodeDiameter: 90,
  nodeLine: 1,
  labelSize: 11,
  /** Percentage of the node diameter the label may occupy. */
  labelMaxWidth: 80,
  /** Optical centring correction for a label inside a node, in pixels. */
  labelBaselineNudge: 2,
  /** Multiple of the label size between wrapped lines. */
  labelLineHeight: 1.15,
  /** Lines a node label may wrap to before it is elided. */
  labelMaxLines: 2,
  /** The disc itself. Below 1 the field shows through node matter. */
  nodeFillOpacity: 1,
  /** The name inside the disc, independent of the disc. */
  nodeLabelOpacity: 1,
  edgeWidth: 1,
  edgeOpacity: 0.5,
  edgeLabelSize: 9,
  /** The relation chip on a lit edge, independent of the line under it. */
  edgeLabelOpacity: 1,
  /**
   * What a spoke keeps at rest, as a fraction of the opacity it would have had.
   * See `spokeDimOf` in the product canvas for why spokes are a class at all.
   */
  spokeRestOpacity: 0.05,
  dottedGap: 6.5,
};

/** Approved physical/interaction defaults shared by lab and product canvas. */
export const GRAPH_DNA_INTERACTION = {
  hoverRadius: 140,
  hoverResponse: 180,
  gravityStrength: 220,
  gravityTravel: 8.6,
  absorbPull: 2.18,
  gripScale: 0.9,
  dragNodeRelief: 0.25,
  dragEdgeLoad: 0.3,
  dragEdgePresence: 0.08,
  selectionSpeed: 8,
  selectionClearance: 11,
  selectionDotGap: 4.5,
  selectionLine: 1.5,
  /**
   * Whether the selection ring arrives and leaves, rather than appearing.
   *
   * The product ran with motion off wholesale, and one flag covered two things
   * that are not alike. Animating *canvas elements* means G6 interpolating
   * every element that differs — measured at 2000 nodes as a **2.09 second
   * block with no frame painted**, and that stays off.
   *
   * The ring is not a canvas element. It is a single screen-space SVG driven
   * by the Web Animations API, so its cost is one element's opacity and scale
   * and does not move when the graph grows. It is also the one piece of motion
   * that carries meaning: a selection that fades in is a thing that *became*
   * selected, where one that blinks into place is indistinguishable from a
   * redraw.
   *
   * Timings come from the same `MotionPlans` as everything else — emit on the
   * way in, absorb on the way out — so it is tunable on the DNA motion lab
   * beside the parameters it shares.
   */
  selectionMotion: true,
} as const;

export function radixValue(value: RadixToken): string {
  // Not a Radix step. Focus's paper sits off the scale so it cannot share a
  // colour with slateDark 1, which is the ambient dark field.
  if (value.scale === "black") return "#000000";
  const palette = radixColors[value.scale] as unknown as Record<string, string>;
  const stem = String(value.scale).replace("Dark", "");
  return (
    palette[`${stem}${value.step}`] ??
    (radixColors.gray as Record<string, string>).gray12
  );
}

export type ResolvedGraphDna = Record<keyof GraphDnaTheme, string>;
export type ResolvedGraphDnaFocus = Record<keyof GraphDnaFocusTheme, string>;

export function resolveGraphDna(mode: ThemeMode = "light"): ResolvedGraphDna {
  return Object.fromEntries(
    Object.entries(GRAPH_DNA_THEME[mode]).map(([key, value]) => [
      key,
      radixValue(value as RadixToken),
    ]),
  ) as ResolvedGraphDna;
}

/** The provisional matter palette, resolved. Never a workbench knob: the
 * workbench authors the shipping look, and a construction is a state of a
 * graph rather than a second look to tune. */
export function resolveGraphDnaProvisional(
  mode: ThemeMode = "light",
): ResolvedGraphDna {
  return Object.fromEntries(
    Object.entries(GRAPH_DNA_PROVISIONAL_THEME[mode]).map(([key, value]) => [
      key,
      radixValue(value as RadixToken),
    ]),
  ) as ResolvedGraphDna;
}

export function resolveGraphDnaFocus(): ResolvedGraphDnaFocus {
  return Object.fromEntries(
    Object.entries(GRAPH_DNA_FOCUS).map(([key, value]) => [
      key,
      radixValue(value as RadixToken),
    ]),
  ) as ResolvedGraphDnaFocus;
}

/**
 * Read a colour this module may have produced, not only one it was given.
 *
 * `mixHex` returns `rgb(r, g, b)`, and the graph styles legitimately nest it —
 * "the resting stroke, then tinted towards the bond ink". A hex-only reader
 * cannot read its own output: `hexToRgb("rgb(238, 238, 238)")` took `"rg"` and
 * `"b("` as hex digits and returned `[NaN, 11, …]`, so the mix came out as
 * `rgb(NaN, 11, 35)`.
 *
 * That failure was invisible in the worst way. Assigning an invalid colour to
 * a canvas `strokeStyle` is *silently ignored* — the context keeps whatever it
 * was last set to — so focus-mode edges were drawn in a stale near-black on a
 * near-black field rather than in `dimEdge`. Nothing threw, nothing warned, and
 * the map simply lost its filaments.
 *
 * Returns null rather than a guess: a colour we cannot read must not be
 * silently replaced by one we invented.
 */
function readColor(value: string): [number, number, number] | null {
  const text = value.trim();

  const rgb = text.match(
    /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i,
  );
  if (rgb) {
    const channels = [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
    if (channels.every(Number.isFinite)) {
      return channels as [number, number, number];
    }
    return null;
  }

  if (!text.startsWith("#")) return null;
  const digits = text.slice(1);
  // #rgb, #rgba, #rrggbb, #rrggbbaa — alpha is dropped: these mixes are about
  // ink, and opacity is carried separately by the renderer.
  const full =
    digits.length === 3 || digits.length === 4
      ? digits
          .slice(0, 3)
          .split("")
          .map((c) => c + c)
          .join("")
      : digits.slice(0, 6);
  if (full.length !== 6 || !/^[0-9a-f]{6}$/i.test(full)) return null;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

/**
 * Blend two colours. Used to tint node matter without leaving the language.
 *
 * Named `mixHex` for its callers' sake, but it accepts anything `readColor`
 * reads — including its own `rgb(...)` output, which is what nested mixes hand
 * it. An unreadable input yields that input unchanged rather than a fabricated
 * colour, so a mistake shows up as "this did not tint" instead of as matter
 * drawn in a colour nobody chose.
 */
export function mixHex(from: string, to: string, amount: number): string {
  const a = readColor(from);
  const b = readColor(to);
  if (!a || !b) return from;
  const t = Math.max(0, Math.min(1, amount));
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * t)}, ${Math.round(
    a[1] + (b[1] - a[1]) * t,
  )}, ${Math.round(a[2] + (b[2] - a[2]) * t)})`;
}
