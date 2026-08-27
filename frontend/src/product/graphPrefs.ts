/**
 * How this browser draws a graph — as distinct from what the graph says.
 *
 * These are *display* preferences, so they live in the browser rather than on
 * the operator host. Nothing here can change a claim, an arrangement, or a
 * verdict: the server still decides where every node sits and what every edge
 * asserts. Turning edge types off does not make them stop existing, and the
 * node reader still names the relation in full when you open one.
 *
 * Kept out of `SettingsPanel`'s server-backed account state on purpose. Those
 * settings describe one host and follow the operator between machines; these
 * describe one screen and should not.
 */

import {
  FONT_MONO,
  FONT_MONO_TRIALS,
  fontMonoFamily,
  type FontMonoId,
} from "../styles/typography";

const STORAGE_KEY = "graphauthor.graphPrefs";
const CHANGED = "graphauthor:graphPrefs";

export type GraphPrefs = {
  /**
   * Room between nodes as a multiple of the anti-collision baseline.
   * 1 = “As arranged” (already prevents disc collisions for the drawn
   * diameter). Values above 1 only add air, up to 2.
   */
  spacing: number;
  /**
   * Whether an edge announces its type — "Contains", "Near to" — on the canvas.
   * Default off: on a dense map the four type names repeat hundreds of times
   * and say the same thing the arrow already says. A recorded label is
   * specific to the edge, so it survives either way.
   */
  edgeTypeLabels: boolean;
  /**
   * Whether spokes — the edges from a packed root to each of its branches —
   * are drawn quietly. They are the single largest source of crossings on real
   * maps and carry the least, but on a graph that genuinely *is* a star they
   * are the structure, so it stays a choice.
   */
  dimSpokes: boolean;
  /**
   * Which loaded mono to try against Jost. Authored default is `FONT_MONO`.
   */
  mono: FontMonoId;
};

export type MonoFace = FontMonoId;

export const MONO_FACES: Array<{
  id: FontMonoId;
  label: string;
  family: string;
  note: string;
}> = (Object.keys(FONT_MONO_TRIALS) as FontMonoId[]).map((id) => ({
  id,
  label: FONT_MONO_TRIALS[id].name,
  family: fontMonoFamily(id),
  note: FONT_MONO_TRIALS[id].note,
}));

export const DEFAULT_GRAPH_PREFS: GraphPrefs = {
  spacing: 1,
  edgeTypeLabels: false,
  dimSpokes: true,
  mono: FONT_MONO,
};

export const SPACING_RANGE = { min: 1, max: 2, step: 0.05 } as const;

function readMono(value: unknown): FontMonoId {
  return typeof value === "string" && value in FONT_MONO_TRIALS
    ? (value as FontMonoId)
    : FONT_MONO;
}

export function monoFamily(face: FontMonoId): string {
  return fontMonoFamily(face);
}

function clampSpacing(value: unknown): number {
  const number = Number(value);
  if (!Number.isFinite(number)) return DEFAULT_GRAPH_PREFS.spacing;
  return Math.min(SPACING_RANGE.max, Math.max(SPACING_RANGE.min, number));
}

/** How the current spacing reads to a person, without exposing the multiplier. */
export function spacingLabel(spacing: number): string {
  if (spacing <= 1.01) return "As arranged";
  return `+${Math.round((spacing - 1) * 100)}% room`;
}

export function readGraphPrefs(): GraphPrefs {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_GRAPH_PREFS;
    const stored = JSON.parse(raw) as Partial<GraphPrefs>;
    return {
      spacing: clampSpacing(stored.spacing ?? DEFAULT_GRAPH_PREFS.spacing),
      edgeTypeLabels:
        stored.edgeTypeLabels ?? DEFAULT_GRAPH_PREFS.edgeTypeLabels,
      dimSpokes: stored.dimSpokes ?? DEFAULT_GRAPH_PREFS.dimSpokes,
      mono: readMono(stored.mono),
    };
  } catch {
    return DEFAULT_GRAPH_PREFS;
  }
}

export function writeGraphPrefs(next: Partial<GraphPrefs>): GraphPrefs {
  const merged = { ...readGraphPrefs(), ...next };
  merged.spacing = clampSpacing(merged.spacing);
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  } catch {
    // Private-mode browsers refuse writes. The change still applies to this
    // session; it just will not outlive it.
  }
  window.dispatchEvent(new CustomEvent<GraphPrefs>(CHANGED, { detail: merged }));
  return merged;
}

/** Subscribe to preference changes made anywhere in this tab. */
export function onGraphPrefsChange(listener: (prefs: GraphPrefs) => void) {
  const handle = (event: Event) => {
    listener((event as CustomEvent<GraphPrefs>).detail ?? readGraphPrefs());
  };
  window.addEventListener(CHANGED, handle);
  return () => window.removeEventListener(CHANGED, handle);
}
